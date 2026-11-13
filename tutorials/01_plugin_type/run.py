"""Discover a contract without registering an implementation."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tutorial_support import LIBRARY, PLUGIN_TYPE, Tutorial, expected_error


def main():
    with Tutorial() as tutorial:
        tutorial.register(type_only=True)
        info = tutorial.manager.get_plugin_type_info_from_lib(PLUGIN_TYPE)
        print(f"Registered type: {info['PluginTypeName']}")
        from rpp_plugin_types.example_library import ScalarProcessor

        print(f"Generated interface: {ScalarProcessor.__name__}")
        print(f"Implementations: {len(tutorial.manager.get_library_plugins(LIBRARY))}")
        with expected_error(ValueError, "not found"):
            tutorial.manager.get_plugin_type_info_from_lib(f"{LIBRARY}::MissingType")


if __name__ == "__main__":
    main()
