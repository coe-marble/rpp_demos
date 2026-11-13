@0xcde5a6d64b3e219f;

using Anot = import "rpp_common/anot.capnp";

struct Packet {
  sequence @0 :UInt64;
  payload @1 :Data;
}

interface Endpoint $Anot.plugin("Endpoint") {
  exchange @0 (packet :Packet) -> (packet :Packet);
}
