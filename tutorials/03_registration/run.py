"""Inspect registration, refresh a source change, and report a missing file."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tutorial_support import LIBRARY, PLUGIN, PLUGIN_TYPE, Tutorial, expected_error


def main():
    with Tutorial() as tutorial:
        with expected_error(ValueError, "not"):
            tutorial.manager.get_plugin_info_from_lib(PLUGIN)
        tutorial.register()
        info = tutorial.manager.get_plugin_info_from_lib(PLUGIN)
        print(f"Registered: {info['PluginName']} -> {info['PluginType']}")
        if info["PluginType"] != PLUGIN_TYPE:
            raise RuntimeError("Registered plugin has the wrong contract")
        source = tutorial.library / "plugins" / "affine_processor.py"
        with source.open("a", encoding="utf-8") as output:
            output.write("\n# Tutorial registration refresh example.\n")
        tutorial.manager.refresh_plugin_library(LIBRARY)
        print(f"Refreshed: {PLUGIN}")
        source.unlink()  # Only the temporary copy is modified.
        with expected_error(FileNotFoundError, "affine_processor.py"):
            tutorial.manager.register_plugin_from_source(source, LIBRARY)


if __name__ == "__main__":
    main()
