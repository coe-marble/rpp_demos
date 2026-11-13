# RPP integrated demos

Status: planned after the six core tutorials.

The first demo will be `localization/`: run multiple localization algorithms
under ROS 2 and demonstrate RPP lifecycle management through `rpp_ros2`.
Reuse the existing localization contracts and implementations from
`rpp_localization`; keep algorithm implementation in that library.

Run EKF and UKF as separately configured components with the same input stream
and distinct estimate topics. Demonstrate independent activation and
deactivation, reactivation, and cleanup. Stopping one algorithm should leave
the other running. State explicitly whether reactivation resets or retains its
estimate, according to the selected plugin's behavior.

The demo will own launch files, workspace configuration, deterministic sample
inputs, ROS CLI examples, and expected observations. `rpp_ros2` will own the
ROS interface to RPP lifecycle management. Use topics for measurements,
estimates, and lifecycle state/events; use request/response services for
lifecycle commands so CLI callers receive transition results. Inspect the
available `rpp_ros2` API before fixing endpoint names or message types.

Use `ros2 topic` to inspect data and state and the bridge's supported CLI
command path to request transitions. Explain the relationship between RPP
component state and any ROS node lifecycle; avoid assuming they are identical.
