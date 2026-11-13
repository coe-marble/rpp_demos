"""Exercise defaults, configured behavior, and parameter validation."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tutorial_support import Tutorial, rejected, show_value


def main():
    with Tutorial() as tutorial:
        tutorial.register()
        for name, parameters, expected in (
                ("default", {}, 3),
                ("configured", {"gain": 2.0, "offset": 1.0}, 7)):
            runtime = tutorial.load(tutorial.component(name, **parameters))
            runtime.configure().require_success(f"configure {name}")
            runtime.activate().require_success(f"activate {name}")
            show_value(name, runtime.get_instance().process(3.0), expected)
        invalid = tutorial.load(tutorial.component("invalid", gain="invalid"))
        rejected(invalid.configure(), "configure invalid.gain")


if __name__ == "__main__":
    main()
