#include "measurement.hpp"

#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <capnp/serialize.h>
#include <rpp_cpp/component_runtime_builder.hpp>
#include <rpp_cpp/external_component_process.hpp>
#include <rpp_cpp/rpp_server_host.hpp>
#include <rpp_plugin_types/communication_benchmarks/Endpoint.hpp>

using Endpoint = communication_benchmarks::Endpoint;

// Support the standard component-server arguments on this same executable.
// The transport, lifecycle protocol, and host are the normal RPP implementation.
int server(int argc, char ** argv)
{
  std::map<std::string, std::string> arguments;
  for (int i = 1; i < argc; i += 2) {
    if (i + 1 >= argc) {throw std::invalid_argument("Missing component-server argument");}
    arguments[argv[i]] = argv[i + 1];
  }
  rpp::RPP_HOME = arguments.at("--home");
  rpp::RppDataManager data_manager(rpp::RPP_HOME);
  rpp::ComponentRuntimeBuilder builder(data_manager);
  rpp::ComponentServerRequest request;
  request.host = arguments.at("--host");
  request.port = static_cast<uint16_t>(std::stoul(arguments.at("--port")));
  request.logger = std::make_shared<rpp::RppLogger>(
    rpp::LoggerOptions{rpp::LogLevel::ERROR, "benchmark_server"});
  request.slots.push_back({arguments.at("--conn"), arguments.at("--slot"),
    {{arguments.at("--path"), arguments.at("--plugin")}}});
  auto host = builder.build_component_server(request);
  host->run();
  host->close().require_success("close responder host");
  return 0;
}

int main(int argc, char ** argv)
{
  try {
    if (argc > 1 && std::string(argv[1]) == "--host") {return server(argc, argv);}
    bool echo = false;
    const auto config = bench::config_from_args(argc, argv, echo);
    if (echo) {throw std::invalid_argument("RPP responders use the component server");}
    std::ifstream state_file(config.at("state").get<std::string>());
    const auto state = bench::json::parse(state_file);
    rpp::RPP_HOME = state.at("home").get<std::string>();
    rpp::RppDataManager data_manager(rpp::RPP_HOME, state.at("workspace"));
    rpp::ComponentRuntimeBuilder builder(data_manager);
    const auto placement = config.at("placement").get<std::string>();
    auto script = builder.build_script({rpp::ScriptDescriptionPath{
      state.at("scripts").at("cpp_" + placement).get<std::string>()}, std::nullopt, std::nullopt});
    script.configure().require_success("configure benchmark script");
    const auto & context = script.get_context();
    context.activate_subcomponents().require_success("activate script endpoints");
    auto source = context.get_subcomponent_context("source").get_instance<Endpoint>();
    std::shared_ptr<Endpoint> responder;
    std::shared_ptr<rpp::ExternalComponentProcess> process;
    if (placement == "native") {
      responder = context.get_subcomponent_context("responder").get_instance<Endpoint>();
    } else {
      const auto language = config.at("receiver").get<std::string>();
      const auto record = state.at("responders").at(language);
      const auto info = data_manager.get_plugin_info_from_lib(record.at("plugin"));
      rpp::ExternalComponentProcessRegistry registry;
      registry.register_server("cpp", config.at("cpp_server"));
      registry.register_server("python", config.at("python_server"));
      auto logger = std::make_shared<rpp::RppLogger>(
        rpp::LoggerOptions{rpp::LogLevel::ERROR, "benchmark_client"});
      auto prepared = rpp::ExternalComponentProcess::create(language, rpp::RPP_HOME,
        {{record.at("path"), info, "benchmark", "communication_benchmarks::Endpoint"}}, registry,
        "127.0.0.1", logger);
      process = std::move(prepared.process);
      responder = std::dynamic_pointer_cast<Endpoint>(prepared.instances.at(0));
      if (!responder) {throw std::runtime_error("Responder does not implement Endpoint");}
      process->configure_component("benchmark").require_success("configure responder");
      const auto * adapter = dynamic_cast<const rpp::ClientAdapter *>(responder.get());
      if (!adapter) {throw std::runtime_error("Responder has no RPC adapter");}
      process->activate_component("benchmark", *adapter, {}).require_success("activate responder");
    }

    Endpoint::Packet packet;
    packet.sequence() = 0;
    const auto bytes = config.at("payload_bytes").get<size_t>();
    auto payload = packet.payload();
    payload.resize(bytes);
    for (size_t i = 0; i < bytes; ++i) {payload[i] = 0x5a;}
    // A standalone serialized Packet size, excluding RPC/control/TCP envelopes.
    capnp::MallocMessageBuilder serialization;
    serialization.setRoot(static_cast<schema::communication_benchmarks::Packet::Reader>(packet.as_const()));
    const auto serialized_bytes = capnp::messageToFlatArray(serialization).asBytes().size();
    const auto exchange = [&](uint64_t sequence, bool full = false) {
        packet.sequence() = sequence;
        auto response = responder->exchange(source->exchange(packet.as_const()));
        const auto received_payload = response.payload();
        bool valid = response.sequence() == sequence && received_payload.size() == bytes;
        if (valid && full) {
          valid = std::all_of(received_payload.begin(), received_payload.end(), [](uint8_t v) {return v == 0x5a;});
        } else if (valid && bytes) {
          valid = received_payload[0] == 0x5a && received_payload[bytes - 1] == 0x5a;
        }
        if (!valid) {throw std::runtime_error("RPP response sequence/payload mismatch");}
        return true;
      };
    bench::measure(config, [&](uint64_t sequence) {return exchange(sequence);}, serialized_bytes,
      [&] {return exchange(0, true);},
      {{"transport", placement == "native" ? "direct_plugin_calls" : "capnp_rpc_tcp_loopback"}});
    // Script runtime and external host own cleanup on exception paths too.
    if (process) {process->close().require_success("close responder process");}
    script.close().require_success("close benchmark script");
    return 0;
  } catch (const std::exception & error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
