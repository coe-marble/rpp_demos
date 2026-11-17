"""Define script assignments, load a script runtime, and execute its Python body."""

import os
from pathlib import Path
import runpy


def main():
    if not os.environ.get("RPP_HOME"):
        raise RuntimeError('First export RPP_HOME="$HOME/.rpp_tutorials" and follow Tutorial 02')
    home = Path(os.environ["RPP_HOME"]).expanduser().resolve()

    from rpp_plugin_registrator.library_manager import LibraryManager
    from rpp_orchestrator.workspace import Workspace
    from rpp_py.build_requests import LibraryScript, ScriptRequest
    from rpp_py.context_builder import ComponentRuntimeBuilder
    from rpp_py.data_manager import DataManager

    manager = LibraryManager(rpp_home=home)
    library = manager.get_library_path("example_library")
    if library is None:
        raise RuntimeError("Follow Tutorial 02 to link-register example_library first")
    library = Path(library).resolve()
    if library != home / "tutorials/example_library":
        raise RuntimeError("Use the example_library copy linked in Tutorial 02")
    script_path = library / "scripts/scalar_pipeline.py"
    if not script_path.is_file():
        raise RuntimeError("Follow Tutorial 02 to copy the current script and refresh the library")

    # A registered library can also be a workspace that publishes scripts.
    workspace = Workspace(library, manager)
    workspace.ensure_layout()
    records = {}
    for name, plugin, parameters in (
            ("pipeline_processor", "example_library::AffineProcessor",
             {"gain": 2.0, "offset": 1.0}),
            ("pipeline_accumulator", "example_library::AccumulatingProcessor", {})):
        try:
            record = workspace.get_component(name)
        except ValueError:
            record = workspace.create_component(name, plugin)
        workspace.component_parameter_store.save(record.folder, parameters)
        records[name] = record

    # Read the existing implementation and publish its slot description.
    # Recreating this description clears old assignments before a repeat run.
    script = workspace.create_script(
        Path("scripts/scalar_pipeline.py"), source=script_path.read_text(encoding="utf-8"))
    workspace.assign_component_to_script(script, "processor", records["pipeline_processor"].id)
    workspace.assign_component_to_script(script, "accumulator", records["pipeline_accumulator"].id)
    print(f"Declared slots: {script.slots}")
    print(f"Script description: {script.description_path}")

    builder = ComponentRuntimeBuilder(data_manager=DataManager(
        library_manager=manager, workspace_path=workspace.root))
    # LibraryScript resolves the published description and its saved assignments.
    runtime = builder.build_script(ScriptRequest(
        LibraryScript("example_library", "scalar_pipeline"), configuration="Default"))
    try:
        runtime.configure().require_success("configure pipeline components")
        context = runtime.get_context()
        context.activate_subcomponents().require_success("activate pipeline components")

        # Building the runtime does not execute the Python body. Load and call it.
        module = runpy.run_path(str(script.path))
        pipeline = module["ScalarPipeline"]()
        totals = pipeline.run(context, [1.0, 2.0, 3.0])
        print(f"Pipeline totals: {totals}")
    finally:
        runtime.close().require_success("close pipeline components")


if __name__ == "__main__":
    main()
