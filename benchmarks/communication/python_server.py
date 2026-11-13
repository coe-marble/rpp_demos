#!/usr/bin/env python3
"""Standard RPP component server with per-call debug logging disabled."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--plugin", required=True)
    parser.add_argument("--conn", required=True)
    args = parser.parse_args()
    from rpp_plugin_registrator.library_manager import LibraryManager
    from rpp_py.build_requests import ComponentRequest, ComponentServerRequest, ComponentServerSlotRequest
    from rpp_py.context_builder import ComponentRuntimeBuilder
    from rpp_py.data_manager import DataManager
    from rpp_py.logger import RppLogger, LoggerOptions, LogLevel

    manager = LibraryManager(rpp_home=args.home)
    logger = RppLogger(LoggerOptions(level=LogLevel.ERROR, name="benchmark_server"))
    builder = ComponentRuntimeBuilder(data_manager=DataManager(library_manager=manager), logger=logger)
    host = builder.build_component_server(ComponentServerRequest(
        host=args.host, port=args.port, slots=(ComponentServerSlotRequest(
            args.conn, "communication_benchmarks::Endpoint",
            (ComponentRequest(args.path, args.plugin),)),)))
    try:
        host.run()
    finally:
        host.close().require_success("close responder host")


if __name__ == "__main__":
    main()
