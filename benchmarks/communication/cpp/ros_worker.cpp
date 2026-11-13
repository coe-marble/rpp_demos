#include "measurement.hpp"

#include <algorithm>
#include <iostream>
#include <memory>
#include <rclcpp/rclcpp.hpp>
#include <rclcpp/serialization.hpp>
#include <rmw/rmw.h>
#include <rpp_communication_benchmarks/msg/packet.hpp>

using Packet = rpp_communication_benchmarks::msg::Packet;

class Echo : public rclcpp::Node
{
  rclcpp::Publisher<Packet>::SharedPtr publisher_;
  rclcpp::Subscription<Packet>::SharedPtr subscription_;
public:
  Echo(const bench::json & config, const rclcpp::NodeOptions & options, const rclcpp::QoS & qos)
  : Node("benchmark_echo", options)
  {
    const auto prefix = config.at("topic").get<std::string>();
    publisher_ = create_publisher<Packet>(prefix + "/reply", qos);
    subscription_ = create_subscription<Packet>(prefix + "/request", qos,
      [this](Packet::UniquePtr message) {publisher_->publish(std::move(message));});
  }
};

int main(int argc, char ** argv)
{
  try {
    bool echo_only;
    const auto config = bench::config_from_args(argc, argv, echo_only);
    rclcpp::init(0, nullptr);
    rclcpp::NodeOptions options;
    options.use_intra_process_comms(config.at("placement") == "native");
    rclcpp::QoS qos(rclcpp::KeepLast(config.at("qos_depth").get<size_t>()));
    qos.durability_volatile();
    if (config.at("reliability") == "reliable") {qos.reliable();}
    else {qos.best_effort();}
    rclcpp::executors::SingleThreadedExecutor executor;
    std::shared_ptr<Echo> echo;
    if (echo_only || config.at("placement") == "native") {
      echo = std::make_shared<Echo>(config, options, qos);
      executor.add_node(echo);
    }
    if (echo_only) {
      executor.spin();
      rclcpp::shutdown();
      return 0;
    }
    auto source = std::make_shared<rclcpp::Node>("benchmark_source", options);
    executor.add_node(source);
    const auto prefix = config.at("topic").get<std::string>();
    auto publisher = source->create_publisher<Packet>(prefix + "/request", qos);
    Packet::UniquePtr received;
    auto subscription = source->create_subscription<Packet>(prefix + "/reply", qos,
      [&received](Packet::UniquePtr message) {received = std::move(message);});
    const auto until = bench::now_ns() + static_cast<int64_t>(config.at("startup_timeout_s").get<double>() * 1e9);
    while (publisher->get_subscription_count() == 0 || subscription->get_publisher_count() == 0) {
      if (bench::now_ns() >= until) {throw std::runtime_error("ROS discovery timed out");}
      executor.spin_once(std::chrono::milliseconds(10));
    }
    Packet packet;
    packet.payload.assign(config.at("payload_bytes").get<size_t>(), 0x5a);
    rclcpp::Serialization<Packet> serializer;
    rclcpp::SerializedMessage serialized;
    serializer.serialize_message(&packet, &serialized);
    const auto & expected_payload = packet.payload;
    const auto exchange = [&](uint64_t sequence, bool full = false) {
        received.reset();
        packet.sequence = sequence;
        publisher->publish(std::make_unique<Packet>(packet));
        const auto deadline = bench::now_ns() + static_cast<int64_t>(config.at("reply_timeout_s").get<double>() * 1e9);
        while (bench::now_ns() < deadline && rclcpp::ok()) {
          executor.spin_once(std::chrono::nanoseconds(std::max<int64_t>(0, deadline - bench::now_ns())));
          if (!received || received->sequence != sequence) {continue;}
          const auto & received_payload = received->payload;
          bool valid = received_payload.size() == expected_payload.size();
          if (valid && full) {valid = received_payload == expected_payload;}
          else if (valid && !expected_payload.empty()) {
            valid = received_payload.front() == 0x5a && received_payload.back() == 0x5a;
          }
          if (!valid) {throw std::runtime_error("ROS payload corruption");}
          return true;
        }
        return false;
      };
    bench::measure(config, [&](uint64_t seq) {return exchange(seq);}, serialized.size(),
      [&] {return exchange(0, true);},
      {{"transport", config.at("placement") == "native" ? "rclcpp_intra_process" : "rmw_inter_process"},
       {"rmw", rmw_get_implementation_identifier()}});
    rclcpp::shutdown();
    return 0;
  } catch (const std::exception & error) {
    std::cerr << error.what() << '\n';
    if (rclcpp::ok()) {rclcpp::shutdown();}
    return 1;
  }
}
