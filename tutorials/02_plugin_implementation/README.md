# Tutorial 2 Plugin implementation

[AffineProcessor](../example_library/plugins/affine_processor.py) inherits the
generated interface. `PARAMETERS` declares gain and offset defaults.
Configuration validates both values before committing them to instance state.
Activation permits processing, deactivation blocks it, and cleanup releases
its coefficients. Separate instances share no mutable configuration.

Use the [shared prerequisites](../../README.md#prerequisites-and-execution).
The driver prepares registration and components automatically:

```bash
python3 tutorials/02_plugin_implementation/run.py
```

Look for:

```text
default = 3
configured = 7
Expected failure (configure invalid.gain): ...gain must be a finite number...
```

The last component supplies a string gain and fails configuration. The plugin
also rejects non-finite coefficients, inputs, and results. Its own active flag
protects calls through retained native references while inactive. All runtime
handles close before the temporary workspace and registry are deleted,
including the partially configured component.
