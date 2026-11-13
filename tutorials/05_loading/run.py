"""Call configured instances using their generated contract."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tutorial_support import Tutorial, expected_error, show_value


def main():
    with Tutorial() as tutorial:
        tutorial.register()
        from rpp_plugin_types.example_library import ScalarProcessor

        records = [tutorial.component("processor", gain=2.0, offset=1.0),
                   tutorial.component("identity")]
        for record, expected in zip(records, (7, 3)):
            runtime = tutorial.load(record)
            print(f"Loaded {record.name}; active={runtime.get_context().is_active()}")
            runtime.configure().require_success(f"configure {record.name}")
            runtime.activate().require_success(f"activate {record.name}")
            processor: ScalarProcessor = runtime.get_instance()
            if not isinstance(processor, ScalarProcessor):
                raise TypeError("Loaded instance does not implement ScalarProcessor")
            show_value(record.name, processor.process(3.0), expected)
        with expected_error(ValueError, "Component not found"):
            tutorial.workspace.get_component("missing")
        from rpp_py.build_requests import ComponentRequest

        with expected_error(FileNotFoundError, "missing"):
            tutorial.builder().build_component(ComponentRequest(tutorial.root / "missing"))


if __name__ == "__main__":
    main()
