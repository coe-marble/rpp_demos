# Tutorial 3 Registration

[package.json](../example_library/package.json) identifies the library.
[plugins.json](../example_library/plugins.json) lists contracts under
`PluginTypes` and implementations under `Plugins`, with relative source paths.

[run.py](run.py) calls `LibraryManager.register_plugin_library` with
`link_register=True`. RPP registers the type and generates its interface before
registering the implementation. The linked source is a temporary copy.

Use the [shared prerequisites](../../README.md#prerequisites-and-execution):

```bash
python3 tutorials/03_registration/run.py
```

A lookup fails before registration. Then look for:

```text
Registered: example_library::AffineProcessor -> example_library::ScalarProcessor
Refreshed: example_library::AffineProcessor
```

The driver appends a comment to the copied source and calls
`refresh_plugin_library`, updating the same identity. It then removes that
source and calls explicit `register_plugin_from_source`, producing an expected
missing-file error. Whole-library refresh may skip missing files with a warning;
explicit registration demonstrates the error directly.

Registration creates no configured component or active instance. Removing the
temporary RPP home on exit cleans registry records and generated artifacts
without changing your regular registry or this checkout.
