# RPP and ROS communication benchmarks

Compare two RPP plugins coordinated by a script with two ROS 2 nodes. Each
exchange sends a sequence number and a byte payload, then echoes the complete
payload. Timings use the sender's monotonic clock and report round trips.
The matrix covers both default workloads with three repetitions per case.

| Case | Source | Responder | Placement |
| --- | --- | --- | --- |
| `cpp_native` | C++ | C++ | One process |
| `python_native` | Python | Python | One process |
| `cpp_subprocess` | C++ | C++ | Two processes |
| `python_subprocess` | Python | Python | Two processes |
| `cpp_to_python` | C++ | Python | Two processes |
| `python_to_cpp` | Python | C++ | Two processes |

RPP native cases load both endpoint plugins into a script runtime. The script
passes the source plugin's output to the responder. Native dispatch operates
on the language's generated objects and performs no RPC serialization. RPP
subprocess cases keep the source plugin in that script and use the normal
Cap'n Proto RPC adapter and component server for the responder over loopback
TCP. The benchmark server launchers use the public host API with per-call
debug logging disabled.

ROS native C++ uses two nodes in a single-threaded executor with
`use_intra_process_comms(true)` and ownership-transferring publication. Python
uses two `rclpy` nodes in one single-threaded executor; this does not claim the
same optimization as C++ intra-process delivery. Separate-process cases use
the selected RMW's transport, which can include shared memory. Keep the RMW
and its configuration constant when comparing runs. See the upstream
[ROS intra-process demo](https://github.com/ros2/demos/tree/humble/intra_process_demo)
and [QoS design](https://design.ros2.org/articles/qos).

A subprocess is a real separate OS process with its own PID and address space.
Here both endpoints run on the same host. RPP's responder is a child of the
source worker; the ROS endpoints are separate workers launched by the runner.
CPU accounting includes both endpoints in either arrangement. Reports show
the observed OS process count, and JSON retains individual process IDs.
Future runs also record their parent process IDs.

The comparison matches application payload, requested exchange rate, echo
semantics, warmup, and measurement duration. It compares the requested RPP
and ROS architectures. A direct native plugin call and an executor-driven
ROS message exchange have different scheduling and allocation costs. Across
processes, reliable Cap'n Proto RPC over TCP and ROS messaging through an RMW
can use different transport and delivery mechanisms. A serialization-only
or identical-transport comparison would need a separate benchmark.

## Prerequisites

Use Linux with `/proc`, ROS 2 Humble or a compatible ROS 2 installation, and
an installed RPP Python development environment. Source a current RPP C++
overlay built from the same checkout as the Python runtime. The registration
step needs the RPP development toolchain, including its supported Cap'n Proto
version. The C++ drivers and registered plugins should use Release builds.

The commands below use your existing `~/ros2_ws/install` RPP overlay. Substitute
your current overlay if it is elsewhere. Activate your normal RPP Python
environment as well if it is a virtual environment; it must have access to
the sourced ROS Python packages.

## Prepare and build once

From `~/fer/rpp/rpp_dev`:

```bash
source /opt/ros/humble/setup.bash
source ~/ros2_ws/install/setup.bash
export RPP_BENCH_ROOT="$HOME/.cache/rpp-communication"

python3 src/rpp_demos/benchmarks/communication/prepare.py \
  --state "$RPP_BENCH_ROOT/state"

colcon --log-base "$RPP_BENCH_ROOT/log" build \
  --base-paths src/rpp_demos/benchmarks/communication/ros2 \
  --build-base "$RPP_BENCH_ROOT/build" \
  --install-base "$RPP_BENCH_ROOT/install" \
  --packages-select rpp_communication_benchmarks \
  --cmake-args -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release \
    -DRPP_BENCH_HOME="$RPP_BENCH_ROOT/state/home"

source "$RPP_BENCH_ROOT/install/setup.bash"
```

`prepare.py` explicitly generates and compiles registered RPP interfaces and
plugins. It creates a new state directory, copies the example library, and
creates isolated script/workspace configurations. It does not modify your
regular RPP home. If the state directory already exists, reuse it; preparation
refuses to overwrite it. After changing the contract or plugins, prepare a
new state directory and rebuild the C++ driver against that state's headers.
`--cpp-core /path/to/lib` can select the RPP shared library directory explicitly.

If you need to build the RPP runtime from this checkout first, do that before
preparation and source its overlay. For example, using a separate prefix:

```bash
colcon --log-base "$RPP_BENCH_ROOT/runtime-log" build \
  --base-paths src/rpp_cpp \
  --build-base "$RPP_BENCH_ROOT/runtime-build" \
  --install-base "$RPP_BENCH_ROOT/runtime-install" \
  --packages-select rpp_cpp \
  --cmake-args -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release
source "$RPP_BENCH_ROOT/runtime-install/setup.bash"
```

## Start with one short comparison

This runs the Python native case in RPP and ROS, including warmup:

```bash
python3 src/rpp_demos/benchmarks/communication/run.py \
  --state "$RPP_BENCH_ROOT/state" \
  --output "$RPP_BENCH_ROOT/quick-results" \
  --case python_native --profile small_fast \
  --duration 3 --warmup 1 --repeats 1
```

Output directories must be new. Keep completed result directories for comparing
changes. To inspect the planned cases without launching endpoints, add `--plan`.

## Run the complete matrix

```bash
python3 src/rpp_demos/benchmarks/communication/run.py \
  --state "$RPP_BENCH_ROOT/state" \
  --output "$RPP_BENCH_ROOT/full-results"
```

The default matrix is 162 runs: one RPP baseline plus two ROS QoS modes, across
six arrangements, three profiles, and three repetitions. Each run has two seconds
of warmup and ten seconds of measurement, plus startup and cleanup. Cases are
shuffled with a recorded seed to reduce ordering bias. Defaults in
[profiles.json](profiles.json) are:

| Profile | Payload bytes per message | Target exchanges per second |
| --- | --- | --- |
| `small_fast` | 64 | 10000 |
| `medium` | 1048576 | 100 |
| `large_slow` | 10485760 | 30 |

Select frameworks with `--backend rpp` or `--backend ros2`, arrangements with
`--case cpp_native cpp_subprocess`, and profiles with
`--profile small_fast medium large_slow`. Supply your own size/rate map using
`--profiles /path/to/profiles.json` with the same structure as the checked-in
file. Each successful exchange contains two messages: request and full echo.

The large-frame profile uses 10 MiB (10,485,760 payload bytes) at 30 requested
exchanges per second, with a full-size reply. This is 300 MiB/s of payload in
each direction if the requested rate is sustained. Select that workload alone
with `--profile large_slow`. To lower the rate without editing JSON, add
`--rate-hz 15` (or another positive rate). Overrides apply to every selected
profile and are saved in case metadata and reports.

```bash
python3 src/rpp_demos/benchmarks/communication/run.py \
  --state "$RPP_BENCH_ROOT/state" \
  --output "$RPP_BENCH_ROOT/large-frame-results" \
  --profile large_slow --rate-hz 30
```

## Regenerate adapters after the C++ response lifetime fix

Earlier generated C++ RPC clients returned a struct reader borrowed from a
local response. That response was destroyed as the method returned, leaving
the result dangling. The 1 MiB C++-sender subprocess cases in the saved results
exited with `SIGSEGV`; this lifetime defect is consistent with those crashes.
Smaller calls could also appear to succeed while reading invalid memory.

The registrator now moves the original RPC response into shared ownership.
Returned struct, list, and data views retain that response, with no payload
clone and no `from_wire` call for ordinary method results. Nested views share
the same owner. Executor-managed responses are destroyed on their existing RPC
worker when the final view is released. Release all response views before
closing the runtime/executor; shutdown is unchanged. Direct clients without an
executor must release their views on the original RPC thread before closing
its client context/event loop. The fix needs a fresh registration and rebuild
because generated adapter code is compiled into shared libraries.

Use a new state directory with the updated registrator:

```bash
python3 src/rpp_demos/benchmarks/communication/prepare.py \
  --state "$RPP_BENCH_ROOT/state-v2"
```

Rerun the build command above with
`-DRPP_BENCH_HOME="$RPP_BENCH_ROOT/state-v2/home"`, source that installation,
and run benchmarks using `--state "$RPP_BENCH_ROOT/state-v2"` and a new results
directory. Old samples remain historical measurements; regenerating a report
cannot apply a runtime fix or add measurements for the new 10 MiB workload.
The crash fix has not been verified by rerunning the benchmark.

Both language implementations now bind the received payload once per response
and reuse it for validation in RPP and ROS. Python therefore materializes a
remote Data field once instead of repeatedly reading it; C++ holds one reader
or reference. This describes application-level validation access, not the
number of copies made internally by an adapter or transport.

Every matrix runs these ROS QoS modes by default: `reliable` (reliable, volatile,
keep-last 64) and `sensor` (the ROS SensorDataQoS profile: best-effort, volatile,
keep-last 5). Restrict a run with `--ros-qos reliable` or `--ros-qos sensor`.
Cap'n Proto RPC remains reliable; the selected ROS mode and resolved QoS values
are recorded in every case configuration. `--cpp-rpp` and `--cpp-ros` accept
explicit executable paths.

## Results and interpretation

Open `report.html` for a compact card layout, grouped first by commanded
workload and then by language pair and process placement. Each workload heading
shows payload size, requested exchange frequency, and measurement/warmup
duration. Every card has just three columns: metric, RPP, and ROS. It shows
completed runs, mean and worst RTT, achieved rate, completed load, payload
bandwidth, and CPU. `report.md` contains the same layout in Markdown.

Individual runs, percentile latencies, serialized sizes, process counts,
timeouts, missed slots, failures, and detailed metadata are expandable inside
each card. Summary averages use summed counters across completed runs. Mean
RTT is weighted by successful exchange count. The mean is shown as
`mean ± SD`, using sample standard deviation (n−1 denominator). Summary SD
pools within-run and between-run variation across completed runs; it is not
the average of their SDs, a standard error, or a confidence interval. Worst RTT is the maximum across
all completed runs and is never averaged. Failed or missing runs remain
visible in the completed-run count. Exact per-run scenario metadata and paired
results are in `comparison.json`.

Bold marks the numerically better observed metric, with ties left unmarked.
It does not establish statistical significance. CPU percentage is only
highlighted when achieved rates differ by at most 5%; otherwise, lower CPU
could reflect less delivered work. CPU microseconds per successful exchange
is also reported. Failed planned cases remain visible without a fabricated
comparison winner; incomplete repetition sets receive no summary winner
highlighting. `summary.csv` provides one row per run;
`summary.json` retains full distributions and per-process CPU details.
Each case also contains `samples.csv`, its configuration, exact commands,
endpoint logs, phase timings, and its summary. `environment.json` records
platform, affinity, Python and package versions, ROS/RMW configuration, and
the demos commit. `failures.json` preserves failed cases; the runner exits
unsuccessfully if any case fails or has no successful measured replies.

| Measurement | Definition |
| --- | --- |
| Payload size | Application byte array length, excluding the sequence field |
| Serialized message size | One standalone Packet: unpacked Cap'n Proto framing or ROS serialized CDR |
| RTT | Before source dispatch/publication through reply handling and sequence/size/boundary validation |
| Time statistics | Minimum, mean, p50, p95, p99, p99.9, and maximum observed successful RTT |
| Scheduled RTT | Completion minus the attempted exchange's scheduled release |
| Send lateness | Actual release minus scheduled release |
| Achieved rate | Successful round trips divided by measured wall time |
| Application bandwidth | Successful request and reply payload bytes per second, summed across both directions |
| Serialized equivalent bandwidth | Successful exchanges times twice the standalone serialized message size per second |
| CPU usage | User plus system CPU across both endpoint process trees; 100 percent equals one CPU core |

Serialized equivalent bandwidth describes message volume. It does not include
RPC envelopes, DDS metadata, retransmissions, TCP/IP headers, or memory copies,
and does not claim actual NIC bandwidth. Native RPP performs no wire transfer;
its standalone serialized size is provided for comparison. Failed or timed-out
traffic does not count toward successful application bandwidth.

CPU snapshots bracket only the steady-state measurement phase. They include
the source, responder, RPC executor threads, and component subprocesses.
The runner and any external middleware daemons are excluded. Snapshots use
Linux process CPU ticks; their resolution and slightly wider sampling window
are recorded. If the endpoint process tree changes between snapshots, total
CPU is marked unavailable instead of undercounted silently. Raw sample export
and report generation happen after the final CPU snapshot.

The load generator is paced and closed loop with one exchange outstanding.
When it falls behind it skips expired schedule slots instead of issuing a
catch-up burst. Both missed slots and achieved rates are reported. These
measurements characterize request/reply operation at the attempted load;
they do not measure asynchronous open-loop saturation. Python scheduling and
executor overhead remain part of the measured system.

ROS reply timeouts are counted separately from successful RTTs. RPP's
synchronous call API has no per-call deadline here; an outer watchdog aborts
a stalled case and records the failure. `--reply-timeout` controls ROS waits,
and `--watchdog-slack` bounds extra time beyond a run's duration for either
framework. A full payload comparison runs before warmup; timed exchanges
check sequence, length, and boundary bytes. Worst time means the maximum
observed value for this run, not a guaranteed worst-case execution time.

Rebuild reports from exported samples without rerunning endpoints:

```bash
python3 src/rpp_demos/benchmarks/communication/report.py \
  "$RPP_BENCH_ROOT/full-results"
```

Repetitions remain separate in the report, including each observed maximum.
Preserve raw data when comparing tail latency across versions. After all
processes stop, the dedicated state/build directories can be removed without
unregistering anything in your normal RPP home.
