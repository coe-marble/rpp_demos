"""Persistent setup shared by standalone tutorial entry points.

RPP imports deliberately occur after checking the selected home. Each driver
must run in a fresh Python process because RPP caches configuration and imports.
"""

from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import shutil
import sys


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
    """Tutorial sources and workspaces in RPP_HOME, with scoped runtime handles."""

    def __enter__(self):
        if any(name == "rpp_plugin_types" or name.startswith((
                "rpp_plugin_types.", "rpp_py.", "rpp_plugin_registrator."))
               for name in sys.modules):
            raise RuntimeError("Run each tutorial in a fresh Python process")
        self._stack = ExitStack()
        try:
            home = os.environ.get("RPP_HOME")
            if not home:
                raise RuntimeError("Set RPP_HOME and run rpp init-home before the tutorials")
            self.home = Path(home).expanduser().resolve()
            self.root = self.home / "tutorials"
            self.root.mkdir(parents=True, exist_ok=True)
            self.workspace_path = self.root / Path(sys.argv[0]).resolve().parent.name / "workspace"
            # Copy before registration: RPP can normalize library metadata.
            self.library = Path(shutil.copytree(
                EXAMPLE_LIBRARY, self.root / LIBRARY, dirs_exist_ok=True))
            from rpp_plugin_registrator.library_manager import LibraryManager

            self.manager = LibraryManager(init_anot_only=True)
            # Initialized homes can contain Anot without a current library
            # registration version. Refresh its library before dependents.
            self.manager.refresh_plugin_library("rpp_common")
            existing = self.manager.get_library_path(LIBRARY)
            if existing is not None and Path(existing).resolve() != self.library:
                raise RuntimeError(f"{LIBRARY} is already registered from {existing}")
            self.workspace = None
            print(f"RPP home: {self.home}")
            print(f"Tutorial files: {self.root}")
            return self
        except BaseException:
            self._stack.close()
            raise

    def __exit__(self, *exception):
        return self._stack.__exit__(*exception)

    def register(self, *, type_only=False):
        existing = self.manager.get_library_path(LIBRARY)
        if type_only:
            if existing is not None:
                self.manager.unregister_plugin(PLUGIN, throw_if_not_found=False)
            manifest_path = self.library / "plugins.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["Plugins"] = []
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if existing is None:
            self.manager.register_plugin_library(self.library, link_register=True)
        else:
            self.manager.refresh_plugin_library(LIBRARY)

    def component(self, name, **parameters):
        from rpp_orchestrator.workspace import Workspace

        if self.workspace is None:
            self.workspace = Workspace(self.workspace_path, self.manager)
            self.workspace.ensure_layout()
        try:
            record = self.workspace.get_component(name)
        except ValueError:
            record = self.workspace.create_component(name, PLUGIN)
        self.workspace.component_parameter_store.save(record.folder, parameters)
        return record

    def builder(self):
        from rpp_py.context_builder import ComponentRuntimeBuilder
        from rpp_py.data_manager import DataManager

        return ComponentRuntimeBuilder(data_manager=DataManager(
            library_manager=self.manager, workspace_path=self.workspace_path))

    def load(self, record, *, builder=None):
        from rpp_py.build_requests import ComponentRequest

        runtime = (builder or self.builder()).build_component(ComponentRequest(record.folder))
        self._stack.callback(lambda: runtime.close().require_success(f"close {record.name}"))
        return runtime
