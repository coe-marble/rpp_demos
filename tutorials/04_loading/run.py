"""Load saved components and call their generated contract using public APIs."""

import os
from pathlib import Path


def main():
    if not os.environ.get("RPP_HOME"):
        raise RuntimeError('First export RPP_HOME="$HOME/.rpp_tutorials" and follow Tutorial 02')
    home = Path(os.environ["RPP_HOME"]).expanduser().resolve()

    from rpp_plugin_registrator.library_manager import LibraryManager
    from rpp_orchestrator.workspace import Workspace
    from rpp_py.build_requests import ComponentRequest
    from rpp_py.context_builder import ComponentRuntimeBuilder
    from rpp_py.data_manager import DataManager

    # Tutorial 02 link-registers example_library with the CLI. Here we work with that registration.
    manager = LibraryManager(rpp_home=home)
    manager.get_plugin_info_from_lib("example_library::AffineProcessor")
    from rpp_plugin_types.example_library import ScalarProcessor

    workspace = Workspace(home / "tutorials/04_loading/workspace", manager)
    workspace.ensure_layout()
    builder = ComponentRuntimeBuilder(data_manager=DataManager(
        library_manager=manager, workspace_path=workspace.root))

    for name, parameters in (("processor", {"gain": 2.0, "offset": 1.0}), ("identity", {})):
        try:
            record = workspace.get_component(name)
        except ValueError:
            record = workspace.create_component(name, "example_library::AffineProcessor")
        workspace.component_parameter_store.save(record.folder, parameters)

        # A saved component folder is the public input to runtime construction.
        runtime = builder.build_component(ComponentRequest(record.folder))
        try:
            print(f"Loaded {name}; active={runtime.get_context().is_active()}")
            runtime.configure().require_success(f"configure {name}")
            runtime.activate().require_success(f"activate {name}")
            processor: ScalarProcessor = runtime.get_instance()
            print(f"{name} = {processor.process(3.0):g}")
        finally:
            # The application owns cleanup even if a plugin call raises.
            runtime.close().require_success(f"close {name}")

    try:
        workspace.get_component("missing")
    except ValueError as error:
        print(f"Expected failure (unknown component): {error}")
    try:
        builder.build_component(ComponentRequest(workspace.root / "missing"))
    except FileNotFoundError as error:
        print(f"Expected failure (missing component folder): {error}")


if __name__ == "__main__":
    main()
