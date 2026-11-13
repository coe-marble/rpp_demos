#pragma once

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <nlohmann/json.hpp>

namespace bench
{
using json = nlohmann::json;
using Clock = std::chrono::steady_clock;
inline int64_t now_ns()
{
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
    Clock::now().time_since_epoch()).count();
}
inline void write_json(const std::filesystem::path & path, const json & value)
{
  auto temporary = path;
  temporary += ".tmp";
  {std::ofstream out(temporary); out.exceptions(std::ios::badbit | std::ios::failbit);
    out << value.dump(2);}
  std::filesystem::rename(temporary, path);
}
inline void wait_file(const std::filesystem::path & path, double timeout = 120)
{
  const auto until = now_ns() + static_cast<int64_t>(timeout * 1e9);
  while (!std::filesystem::exists(path)) {
    if (now_ns() >= until) {throw std::runtime_error("Timed out waiting for " + path.string());}
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  }
}
struct Sample
{
  uint64_t sequence;
  int64_t scheduled_ns, start_ns, end_ns;
  bool ok;
  int64_t missed_before;
};
struct Window
{
  std::vector<Sample> samples;
  json timing;
};
template<class Exchange>
Window window(const json & config, Exchange && exchange, double duration,
  bool record, uint64_t sequence_start)
{
  const auto period = std::max<int64_t>(1, std::llround(1e9 / config.at("rate_hz").get<double>()));
  const auto begin = now_ns();
  const auto finish = begin + static_cast<int64_t>(duration * 1e9);
  auto due = begin;
  uint64_t sequence = sequence_start;
  Window result;
  if (record) {result.samples.reserve(static_cast<size_t>(duration * config.at("rate_hz").get<double>()) + 1);}
  while (due < finish) {
    auto now = now_ns();
    if (now < due) {
      std::this_thread::sleep_until(Clock::time_point(std::chrono::nanoseconds(due)));
      now = now_ns();
    }
    if (now >= finish) {break;}
    const auto missed = (now - due) / period;
    due += missed * period;
    const auto start = now_ns();
    const auto ok = exchange(sequence);
    const auto end = now_ns();
    if (record) {result.samples.push_back({sequence, due, start, end, ok, missed});}
    ++sequence;
    due += period;
  }
  const auto end = now_ns();
  const auto trailing = due < finish ? (finish - due + period - 1) / period : 0;
  result.timing = {{"begin_ns", begin}, {"end_ns", end}, {"elapsed_s", (end - begin) / 1e9},
    {"trailing_missed", trailing}, {"attempts", sequence - sequence_start}};
  return result;
}
template<class Exchange, class Validate>
void measure(const json & config, Exchange && exchange, size_t serialized_bytes, Validate && validate,
  const json & metadata = json::object())
{
  constexpr size_t preflight_attempts = 3;
  bool preflight_success = false;
  for (size_t attempt = 0; attempt < preflight_attempts; ++attempt) {
    if (validate()) {
      preflight_success = true;
      break;
    }
  }
  // Best-effort sensor traffic may lose every packet. Keep that outcome in
  // the measured samples rather than treating it as a process-start failure.
  if (!preflight_success && config.value("ros_qos", "") != "sensor") {
    throw std::runtime_error("Preflight payload validation failed");
  }
  const auto warmup = window(config, exchange, config.at("warmup_s"), false, 1);
  const std::filesystem::path directory = config.at("directory").get<std::string>();
  auto ready = metadata;
  ready["serialized_message_bytes"] = serialized_bytes;
  ready["preflight_success"] = preflight_success;
  write_json(directory / "ready.json", ready);
  wait_file(directory / "go");
  auto result = window(config, exchange, config.at("duration_s"), true,
    warmup.timing.at("attempts").template get<uint64_t>() + 1);
  write_json(directory / "done.json", result.timing);
  wait_file(directory / "release");
  std::ofstream out(directory / "samples.csv");
  out.exceptions(std::ios::badbit | std::ios::failbit);
  out << "sequence,scheduled_ns,start_ns,end_ns,ok,missed_before\n";
  for (const auto & sample : result.samples) {
    out << sample.sequence << ',' << sample.scheduled_ns << ',' << sample.start_ns << ','
        << sample.end_ns << ',' << sample.ok << ',' << sample.missed_before << '\n';
  }
}
inline json config_from_args(int argc, char ** argv, bool & echo)
{
  std::string path;
  echo = false;
  for (int i = 1; i < argc; ++i) {
    const std::string argument = argv[i];
    if (argument == "--config" && i + 1 < argc) {path = argv[++i];}
    else if (argument == "--echo") {echo = true;}
    else {throw std::invalid_argument("Unknown or incomplete argument: " + argument);}
  }
  if (path.empty()) {throw std::invalid_argument("--config is required");}
  std::ifstream input(path);
  if (!input) {throw std::runtime_error("Cannot read " + path);}
  return json::parse(input);
}
}  // namespace bench
