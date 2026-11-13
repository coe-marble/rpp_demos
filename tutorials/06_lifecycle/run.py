"""Transitions, inactive calls, failed configuration, recovery, and shutdown."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tutorial_support import Tutorial, expected_error, rejected, show_value


def transition(runtime, operation):
    result = getattr(runtime, operation)()
    callback = result.result if operation == "deactivate" else result
    callback.require_success(operation)
    print(f"{operation}: success; active={runtime.get_context().is_active()}")


def main():
    with Tutorial() as tutorial:
        tutorial.register()
        record = tutorial.component("processor", gain=2.0, offset=1.0)
        runtime = tutorial.load(record)
        rejected(runtime.activate(), "activate before configure")
        transition(runtime, "configure")
        processor = runtime.get_instance()
        with expected_error(RuntimeError, "inactive"):
            processor.process(3.0)
        transition(runtime, "activate")
        show_value("active", processor.process(3.0), 7)
        transition(runtime, "deactivate")
        with expected_error(RuntimeError, "inactive"):
            processor.process(3.0)
        transition(runtime, "activate")
        show_value("reactivated", processor.process(3.0), 7)
        transition(runtime, "deactivate")
        transition(runtime, "cleanup")

        invalid = tutorial.component("recoverable", gain="invalid")
        failed = tutorial.load(invalid)
        rejected(failed.configure(), "configure recoverable.gain")
        rejected(failed.activate(), "activate after failed configure")
        transition(failed, "cleanup")
        # Runtimes snapshot parameters at construction. Correct the saved
        # configuration and build a new runtime to read the new values.
        failed.close().require_success("close failed configuration")
        tutorial.workspace.component_parameter_store.save(
            invalid.folder, {"gain": 2.0, "offset": 1.0})
        recovered = tutorial.load(invalid)
        transition(recovered, "configure")
        transition(recovered, "activate")
        retained_instance = recovered.get_instance()
        show_value("recovered", retained_instance.process(3.0), 7)
        try:
            with expected_error(ValueError, "value must be finite"):
                retained_instance.process(float("nan"))
        finally:
            recovered.close().require_success("close after invocation failure")
        with expected_error(RuntimeError, "inactive"):
            retained_instance.process(3.0)
        print("Closed after invocation failure; retained instance is inactive")


if __name__ == "__main__":
    main()
