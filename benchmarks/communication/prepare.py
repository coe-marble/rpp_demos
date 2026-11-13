"""Register an isolated library and create all benchmark script configurations.

This is an explicit preparation command: registration generates/compiles RPP
artifacts. The benchmark runner itself never builds or registers anything.
"""

import argparse
import json
import os
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parent
LIBRARY = "communication_benchmarks"
TYPE = f"{LIBRARY}::Endpoint"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--cpp-core", type=Path, help="Directory containing librpp_cpp and librpp_cpp_core")
    args = parser.parse_args()
    state = args.state.expanduser().resolve()
    # Exclusive creation prevents overwriting another registry or workspace.
    state.mkdir(parents=True, exist_ok=False)
    home = state / "home"
    os.environ["RPP_HOME"] = str(home)
    home.mkdir()
    settings = {"USE_ROS2_COMPILATION": True, "BUILD_TYPE": "Release"}
    if args.cpp_core:
        settings["RPP_CPP_CORE_PATH"] = str(args.cpp_core.expanduser().resolve())
    # Configure compilation before LibraryManager initializes common schemas.
    (home / "config.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
    from rpp_plugin_registrator.library_manager import LibraryManager
    from rpp_orchestrator.workspace import Workspace

    source = Path(shutil.copytree(ROOT / LIBRARY, state / LIBRARY))
    manager = LibraryManager(init_anot_only=True)
    manager.register_plugin_library(source, link_register=True, build_type="Release")
    workspace = Workspace(state / "workspace", manager)
    workspace.ensure_layout()
    records = {}
    for language, plugin in (("cpp", "EndpointCpp"), ("python", "EndpointPython")):
        for role in ("source", "responder"):
            records[f"{role}_{language}"] = workspace.create_component(
                f"{role}_{language}", f"{LIBRARY}::{plugin}")

    # Explicit ScriptDescriptionPath is a public construction input in both
    # runtimes. These script descriptions select components; the drivers below
    # are the script bodies and execute the benchmark loop.
    scripts = {}
    for language in ("cpp", "python"):
        for placement in ("native", "subprocess"):
            selected = {"source": records[f"source_{language}"]}
            if placement == "native":
                selected["responder"] = records[f"responder_{language}"]
            name = f"{language}_{placement}"
            path = workspace.script_descriptions_path / f"{name}.json"
            description = {
                "ScriptPath": str(ROOT / ("cpp/rpp_worker.cpp" if language == "cpp"
                                          else "python_worker.py")),
                "Language": language,
                "Spec": {slot: TYPE for slot in selected},
                "ActiveConfiguration": "Default",
                "Configurations": {"Default": {"Components": {
                    slot: [{"Id": record.id, "PluginName": record.plugin_name}]
                    for slot, record in selected.items()}}},
            }
            path.write_text(json.dumps(description, indent=2), encoding="utf-8")
            scripts[name] = str(path)
    metadata = {
        "home": str(home), "workspace": str(workspace.root), "scripts": scripts,
        "responders": {language: {"path": str(records[f"responder_{language}"].folder),
                                   "plugin": records[f"responder_{language}"].plugin_name}
                       for language in ("cpp", "python")},
    }
    (state / "state.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Prepared state: {state}")
    print(f"Generated C++ include directory: {home / 'interfaces/cpp'}")


if __name__ == "__main__":
    main()
