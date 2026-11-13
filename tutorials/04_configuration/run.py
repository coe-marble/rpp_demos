"""Create independent workspace components from the same implementation."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tutorial_support import PLUGIN, Tutorial, rejected


def main():
    with Tutorial() as tutorial:
        tutorial.register()
        processor = tutorial.component("processor", gain=2.0, offset=1.0)
        identity = tutorial.component("identity")
        for record in (processor, identity):
            print(f"{record.name}: {record.plugin_name}")
            print(f"  component: {record.id}")
            print(f"  parameters: {tutorial.workspace.part_parameters_path(record.folder)}")
            runtime = tutorial.load(record)
            runtime.configure().require_success(f"configure {record.name}")
            context = runtime.get_context()
            print(f"  gain={context.get_parameter('gain'):g}, "
                  f"offset={context.get_parameter('offset'):g}")
        invalid = tutorial.component("invalid", gain="invalid")
        rejected(tutorial.load(invalid).configure(), "configure invalid.gain")
        builder = tutorial.builder()
        builder.set_parameter_overrides({PLUGIN: {"gain": float("inf")}})
        rejected(tutorial.load(processor, builder=builder).configure(),
                 "configure processor.gain override")


if __name__ == "__main__":
    main()
