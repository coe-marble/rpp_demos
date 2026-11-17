"""Save independent component configurations and inspect resolved parameters."""

from contextlib import ExitStack
import os
from pathlib import Path


def main():
    if not os.environ.get("RPP_HOME"):
        raise RuntimeError('Set RPP_HOME="$HOME/.rpp_tutorials" and follow Tutorial 02')
    home = Path(os.environ["RPP_HOME"]).expanduser().resolve()

    from rpp_plugin_registrator.library_manager import LibraryManager
    from rpp_orchestrator.workspace import Workspace
    from rpp_py.build_requests import ComponentRequest
    from rpp_py.context_builder import ComponentRuntimeBuilder
    from rpp_py.data_manager import DataManager

    manager = LibraryManager(rpp_home=home)
    manager.get_plugin_info_from_lib("example_library::AffineProcessor")
    workspace = Workspace(home / "tutorials/03_configuration/workspace", manager)
    workspace.ensure_layout()
    builder = ComponentRuntimeBuilder(data_manager=DataManager(
        library_manager=manager, workspace_path=workspace.root))
    records = {}
    with ExitStack() as stack:
        for name, parameters in (
                ("processor", {"gain": 2.0, "offset": 1.0}),
                ("identity", {}), ("invalid", {"gain": "invalid"})):
            try:
                record = workspace.get_component(name)
            except ValueError:
                record = workspace.create_component(name, "example_library::AffineProcessor")
            workspace.component_parameter_store.save(record.folder, parameters)
            records[name] = record
            runtime = builder.build_component(ComponentRequest(record.folder))
            stack.callback(lambda runtime=runtime: runtime.close().require_success("close component"))
            result = runtime.configure()
            if name == "invalid":
                print(f"Expected failure (invalid saved gain): success={result.success}; {result.message}")
                continue
            result.require_success(f"configure {name}")
            context = runtime.get_context()
            print(f"{name}: {record.plugin_name}")
            print(f"  component: {record.id}")
            print(f"  parameters: {workspace.part_parameters_path(record.folder)}")
            print(f"  gain={context.get_parameter('gain'):g}, "
                  f"offset={context.get_parameter('offset'):g}")

        # Overrides affect future runtime construction without editing saved files.
        builder.set_parameter_overrides({"example_library::AffineProcessor": {"gain": float("inf")}})
        overridden = builder.build_component(ComponentRequest(records["processor"].folder))
        stack.callback(lambda: overridden.close().require_success("close overridden component"))
        result = overridden.configure()
        print(f"Expected failure (invalid gain override): success={result.success}; {result.message}")


if __name__ == "__main__":
    main()
