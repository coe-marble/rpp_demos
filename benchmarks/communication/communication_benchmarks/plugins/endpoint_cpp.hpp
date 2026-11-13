#pragma once

#include <rpp_plugin_types/communication_benchmarks/Endpoint.hpp>

// Used for both source and responder. The script mediates their exchange.
// Returning the reader retains the native fast path; RPC adapters marshal it.
class EndpointCpp : public communication_benchmarks::Endpoint
{
public:
  Packet::Const exchange(Packet::Const packet) override
  {
    return packet;
  }
};
