# Tutorial 1 Plugin type definition

Read [the annotated schema](../example_library/plugin_types/scalar_processor.capnp)
and its `PluginTypes` entry in [plugins.json](../example_library/plugins.json).
The contract accepts and returns one `Float64`. Gain and offset will be instance
settings. The annotation marks an RPP plugin type; an unannotated interface is
an ordinary Cap'n Proto interface. Keep published file IDs and ordinals stable.

Use the [shared prerequisites](../../README.md#prerequisites-and-execution),
then run from `rpp_demos/`:

```bash
python3 tutorials/01_plugin_type/run.py
```

[run.py](run.py) omits implementations from the temporary manifest, registers
the type, and imports its generated interface. Tutorial 3 explains registration.
Look for:

```text
Registered type: example_library::ScalarProcessor
Generated interface: ScalarProcessor
Implementations: 0
```

A lookup for `MissingType` produces an expected failure: only registered
identities resolve. The temporary registry and generated interfaces are
removed automatically on exit.
