"""Isolated setup shared by standalone tutorial entry points.

RPP imports deliberately occur after selecting the temporary home. Each driver
must run in a fresh Python process because RPP caches configuration and imports.
"""

from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory


LIBRARY = "example_library"
PLUGIN_TYPE = f"{LIBRARY}::ScalarProcessor"
PLUGIN = f"{LIBRARY}::AffineProcessor"
EXAMPLE_LIBRARY = Path(__file__).resolve().parent / LIBRARY


@contextmanager
def expected_error(error_type, containing):
    """Keep intentional failures readable; let unrelated failures propagate."""
    try:
        yield
    except error_type as error:
        if containing not in str(error):
            raise
        print(f"Expected failure: {error}")
    else:
        raise RuntimeError(f"Expected {error_type}: {containing}")


def rejected(result, operation):
    if result.success:
        raise RuntimeError(f"{operation} unexpectedly succeeded")
    print(f"Expected failure ({operation}): {result.message}")


def show_value(name, actual, expected):
    if actual != expected:
        raise RuntimeError(f"{name}: expected {expected}, got {actual}")
    print(f"{name} = {actual:g}")


class Tutorial:
    """One temporary registry, copied source library, workspace, and runtimes."""

    def __enter__(self):
        if any(name == "rpp_plugin_types" or name.startswith((
                "rpp_plugin_types.", "rpp_py.", "rpp_plugin_registrator."))
               for name in sys.modules):
            raise RuntimeError("Run each tutorial in a fresh Python process")
        self._stack = ExitStack()
        try:
            self.root = Path(self._stack.enter_context(
                TemporaryDirectory(prefix="rpp-tutorial-")))
            previous_home = os.environ.get("RPP_HOME")
            self._stack.callback(self._restore_home, previous_home)
            os.environ["RPP_HOME"] = str(self.root / "home")
            # Copy before registration: RPP can normalize library metadata.
            self.library = Path(shutil.copytree(EXAMPLE_LIBRARY, self.root / LIBRARY))
            from rpp_plugin_registrator.library_manager import LibraryManager

            self.manager = LibraryManager(init_anot_only=True)
            self.workspace = None
            print(f"Temporary RPP home: {self.root / 'home'}")
            return self
        except BaseException:
            self._stack.close()
            raise

    @staticmethod
    def _restore_home(previous_home):
        if previous_home is None:
            os.environ.pop("RPP_HOME", None)
        else:
            os.environ["RPP_HOME"] = previous_home

    def __exit__(self, *exception):
        return self._stack.__exit__(*exception)

    def register(self, *, type_only=False):
        if type_only:
            manifest_path = self.library / "plugins.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["Plugins"] = []
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        self.manager.register_plugin_library(self.library, link_register=True)

    def component(self, name, **parameters):
        from rpp_orchestrator.workspace import Workspace

        if self.workspace is None:
            self.workspace = Workspace(self.root / "workspace", self.manager)
            self.workspace.ensure_layout()
        record = self.workspace.create_component(name, PLUGIN)
        if parameters:
            self.workspace.component_parameter_store.save(record.folder, parameters)
        return record

    def builder(self):
        from rpp_py.context_builder import ComponentRuntimeBuilder
        from rpp_py.data_manager import DataManager

        return ComponentRuntimeBuilder(data_manager=DataManager(
            library_manager=self.manager, workspace_path=self.root / "workspace"))

    def load(self, record, *, builder=None):
        from rpp_py.build_requests import ComponentRequest

        runtime = (builder or self.builder()).build_component(ComponentRequest(record.folder))
        self._stack.callback(lambda: runtime.close().require_success(f"close {record.name}"))
        return runtime
