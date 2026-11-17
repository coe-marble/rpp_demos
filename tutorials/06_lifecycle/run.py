"""Manage native lifecycles and transfer typed state through public APIs."""

from contextlib import ExitStack
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

    manager = LibraryManager(rpp_home=home)
    manager.get_plugin_info_from_lib("example_library::AccumulatingProcessor")
    workspace = Workspace(home / "tutorials/06_lifecycle/workspace", manager)
    workspace.ensure_layout()
    records = []
    for name in ("source", "target"):
        try:
            record = workspace.get_component(name)
        except ValueError:
            record = workspace.create_component(name, "example_library::AccumulatingProcessor")
        workspace.component_parameter_store.save(record.folder, {})
        records.append(record)
    builder = ComponentRuntimeBuilder(data_manager=DataManager(
        library_manager=manager, workspace_path=workspace.root))

    # ExitStack is standard Python resource management; no tutorial framework.
    with ExitStack() as stack:
        source = builder.build_component(ComponentRequest(records[0].folder))
        stack.callback(lambda: source.close().require_success("close source"))
        target = builder.build_component(ComponentRequest(records[1].folder))
        stack.callback(lambda: target.close().require_success("close target"))

        # UNCONFIGURED cannot become ACTIVE until configuration succeeds.
        early = source.activate()
        print(f"Activate before configure: success={early.success}")
        source.configure().require_success("configure source")
        target.configure().require_success("configure target")
        source_instance = source.get_instance()
        try:
            source_instance.process(3.0)
        except RuntimeError as error:
            print(f"Call while inactive: {error}")

        source.activate().require_success("activate source")
        print(f"Source total = {source_instance.process(3.0):g}")
        print(f"Source total = {source_instance.process(4.0):g}")
        handover = source.deactivate()
        handover.result.require_success("deactivate source")
        print(f"Handover total = {handover.state.total:g}")
        source.cleanup().require_success("cleanup source")
        # The owned snapshot remains valid after its source has been cleaned up.
        target.activate(handover.state).require_success("activate target with state")
        target_instance = target.get_instance()
        print(f"Target total = {target_instance.process(5.0):g}")

        paused = target.deactivate()
        paused.result.require_success("deactivate target")
        target.activate(paused.state).require_success("reactivate target")
        print(f"Reactivated total = {target_instance.process(1.0):g}")
        try:
            target_instance.process(float("nan"))
        except ValueError as error:
            print(f"Rejected input: {error}")
        print(f"Total after rejected input = {target_instance.process(0.0):g}")

    # Retaining a plugin reference does not retain an active runtime.
    try:
        target_instance.process(1.0)
    except RuntimeError as error:
        print(f"Call after shutdown: {error}")


if __name__ == "__main__":
    main()
