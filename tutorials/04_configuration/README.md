# Tutorial 4 Configuration and composition

An implementation is reusable; a component is a workspace-owned configured
instance. [run.py](run.py) creates `processor` and `identity` with
`Workspace.create_component`, using the same plugin and distinct component IDs.
`component_parameter_store.save` persists processor settings. Identity uses
the defaults. Both are configured without activation.

Use the [shared prerequisites](../../README.md#prerequisites-and-execution):

```bash
python3 tutorials/04_configuration/run.py
```

The driver prints component IDs and parameter file paths. Look for gain `2`,
offset `1` for processor, and gain `1`, offset `0` for identity.

Resolution is plugin defaults, saved component settings, then builder overrides.
The driver demonstrates a string gain in saved settings and an infinite gain
through `set_parameter_overrides`; both produce expected configuration failures.
Builder overrides are keyed by qualified plugin identity and affect matching
native Python components in future builds, rather than editing one component.

Runtime construction snapshots parameters. Close and rebuild to read changed
workspace settings. Independent roots are sufficient here; scripts and nested
component slots can follow in another tutorial. Runtime handles and temporary
workspace data are cleaned up automatically.
