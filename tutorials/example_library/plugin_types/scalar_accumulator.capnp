@0xf1a9c36db70e8245;

using Anot = import "rpp_common/anot.capnp";

# Application state transferred during deactivation and activation.
# Keep this file ID and the state field ordinals stable across implementations.
struct AccumulatorState {
  total @0 :Float64;
}

interface ScalarAccumulator $Anot.plugin("ScalarAccumulator")
    $Anot.lifecycleState("AccumulatorState") {
  process @0 (value :Float64) -> (result :Float64);
}
