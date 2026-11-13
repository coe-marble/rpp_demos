# RPP demos and tutorials

Six runnable tutorials follow one plugin from its contract to lifecycle
management. Integrated demos and benchmarks have separate folders.

```text
rpp_demos/
  tutorials/
    example_library/          # Schema, implementation, and library metadata
    tutorial_support.py       # Isolated setup and cleanup
    01_plugin_type/
    02_plugin_implementation/
    03_registration/
    04_configuration/
    05_loading/
    06_lifecycle/
  demos/                      # Localization and ROS integration planned
  benchmarks/                 # RPP and ROS communication comparisons
```

## Prerequisites and execution

Use Python 3.10 or newer in an installed RPP development environment providing
`rpp_common`, `rpp_plugin_registrator`, `rpp_orchestrator`, and `rpp_py` and their
dependencies. These drivers use the public `LibraryManager`, `Workspace`,
`ComponentRequest`, and `ComponentRuntimeBuilder` APIs. ROS is not required.

Registration generates interfaces and may compile native supporting artifacts
even for Python plugins. Have the Cap'n Proto and native development tools
required by your RPP installation available. The examples do not install
dependencies or build the RPP runtime for you.

Run from this directory using your RPP environment's Python:

```bash
python3 tutorials/01_plugin_type/run.py
python3 tutorials/02_plugin_implementation/run.py
python3 tutorials/03_registration/run.py
python3 tutorials/04_configuration/run.py
python3 tutorials/05_loading/run.py
python3 tutorials/06_lifecycle/run.py
```

Each driver includes its prerequisites from earlier stages and runs
independently. Run each in a fresh Python process because RPP caches
configuration and generated modules. Absolute driver paths also work from
other working directories.

Every driver copies the example library to a temporary directory, sets a
temporary `RPP_HOME` before importing RPP, registers the necessary artifacts,
and creates workspace components as needed. Runtime handles close before the
temporary sources, registry, generated artifacts, and workspace are deleted,
including on exceptions. The normal registry and checked-in sources are not
modified. A forcibly killed process may leave the printed temporary directory
behind; remove it after confirming the process has stopped.

## Learning path

`example_library::ScalarProcessor` declares `process(value)`.
`example_library::AffineProcessor` implements `gain * value + offset`.
Defaults are gain `1` and offset `0`; the component `processor` uses gain `2`
and offset `1`.

| Tutorial | Main lesson | Observable result |
| --- | --- | --- |
| [1. Plugin type](tutorials/01_plugin_type/README.md) | Annotated schema and generated contract | Type registered with zero implementations |
| [2. Implementation](tutorials/02_plugin_implementation/README.md) | Method, parameters, and lifecycle hooks | Default result `3`, configured result `7` |
| [3. Registration](tutorials/03_registration/README.md) | Identities, source refresh, and missing sources | Plugin resolves to its registered type |
| [4. Configuration and composition](tutorials/04_configuration/README.md) | Component identity, defaults, and overrides | Independent workspace settings |
| [5. Loading and invocation](tutorials/05_loading/README.md) | Runtime construction and typed calls | `processor` returns `7`, `identity` returns `3` |
| [6. Lifecycle](tutorials/06_lifecycle/README.md) | Transitions, recovery, and resource ownership | Inactive calls fail; reactivation succeeds |

Each driver includes an intentional failure and checks the expected outcome.
Unexpected errors propagate and produce an unsuccessful exit. READMEs show
application output; initialization logs and detailed diagnostics depend on
the installed RPP version.

Registration publishes an implementation. Workspace configuration selects its
settings for a component instance. Loading constructs runtime objects.
Lifecycle transitions govern configuration, operation, and cleanup.

## Later work

Add a C++ implementation of the same contract and cross-language examples.
The [localization demo plan](demos/README.md) covers multiple algorithms and
ROS lifecycle control through `rpp_ros2`. The
[communication benchmarks](benchmarks/communication/README.md) compare native
and subprocess RPP/ROS communication with reproducible workloads.
