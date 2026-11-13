@0xeadca781e2fba5cd;

using Anot = import "rpp_common/anot.capnp";

# Gain and offset are instance parameters, not part of each request.
# Keep existing ordinals stable when extending the contract.
interface ScalarProcessor $Anot.plugin("ScalarProcessor") {
  process @0 (value :Float64) -> (result :Float64);
}
