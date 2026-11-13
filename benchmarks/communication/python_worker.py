"""RPP script / ROS node-pair benchmark worker. Started by run.py."""

import argparse
from array import array
from contextlib import ExitStack
import json
import os
from pathlib import Path
import time

from measurement import measure


def rpp(config):
    state = json.loads(Path(config["state"]).read_text(encoding="utf-8"))
    os.environ["RPP_HOME"] = state["home"]
    from rpp_plugin_registrator.library_manager import LibraryManager
    from rpp_py.build_requests import ScriptDescriptionPath, ScriptRequest
    from rpp_py.context_builder import ComponentRuntimeBuilder
    from rpp_py.data_manager import DataManager
    from rpp_py.capnp_schema import get_struct_class
    from rpp_py.logger import RppLogger, LoggerOptions, LogLevel

    manager = LibraryManager(rpp_home=Path(state["home"]))
    logger = RppLogger(LoggerOptions(level=LogLevel.ERROR, name="benchmark"))
    builder = ComponentRuntimeBuilder(logger=logger, data_manager=DataManager(
        library_manager=manager, workspace_path=state["workspace"]))
    placement = config["placement"]
    with ExitStack() as stack:
        script = builder.build_script(ScriptRequest(ScriptDescriptionPath(
            state["scripts"][f"python_{placement}"])))
        stack.callback(lambda: script.close().require_success("close benchmark script"))
        script.configure().require_success("configure script")
        context = script.get_context()
        context.activate_subcomponents().require_success("activate script endpoints")
        source = context.get_subcomponent_instance("source")
        if placement == "native":
            responder = context.get_subcomponent_instance("responder")
        else:
            from rpp_py.adapter_info import AdapterClientParams
            from rpp_py.plugin_loader import PluginAdapter
            from rpp_py.external_component_process import (
                ExternalComponentProcess, CppExternalComponentProcess, ExternalComponentSpec)

            record = state["responders"][config["receiver"]]
            info = manager.get_plugin_info_from_lib(record["plugin"])
            responder = PluginAdapter.create_client(manager, info, AdapterClientParams(
                plugin_name=record["plugin"], connection_name="benchmark"), logger=logger)
            arguments = dict(components=[(responder, ExternalComponentSpec(
                record["path"], record["plugin"], "benchmark",
                "communication_benchmarks::Endpoint"))], rpp_home=state["home"], logger=logger)
            if config["receiver"] == "cpp":
                process = CppExternalComponentProcess(command=config["cpp_server"], **arguments)
            else:
                process = ExternalComponentProcess(
                    command=config["python_server"], **arguments)
            stack.callback(process.close)
            process.prepare()
            process.configure_component("benchmark").require_success("configure responder")
            process.activate_component("benchmark").require_success("activate responder")
            # Shutdown closes the host and its managed lifecycle outside timing.

        from rpp_plugin_types.communication_benchmarks import Endpoint
        expected_payload = b"\x5a" * config["payload_bytes"]
        packet = Endpoint.Packet(sequence=0, payload=expected_payload)
        schema = get_struct_class("communication_benchmarks", "Packet")
        serialized_bytes = len(schema.new_message(**packet.as_dict()).to_bytes())

        def exchange(sequence, full=False):
            packet.sequence = sequence
            # The source plugin originates the frame; the script passes it to
            # the responder. Both dispatches are included in round-trip timing.
            response = responder.exchange(source.exchange(packet))
            # A remote Data accessor materializes bytes: access once and reuse.
            received_payload = response.payload
            valid = (response.sequence == sequence and len(received_payload) == len(expected_payload)
                    and (received_payload == expected_payload if full else
                         (not received_payload or
                          (received_payload[0] == 0x5a and received_payload[-1] == 0x5a))))
            if not valid:
                raise RuntimeError("RPP response sequence/payload mismatch")
            return True

        measure(config, exchange, serialized_bytes, full_validation=lambda: exchange(0, True),
                metadata={"transport": "direct_plugin_calls" if placement == "native"
                          else "capnp_rpc_tcp_loopback"})


def ros(config, echo_only):
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
    from rclpy.serialization import serialize_message
    from rpp_communication_benchmarks.msg import Packet

    rclpy.init(args=[])
    executor = SingleThreadedExecutor()
    nodes = []
    qos = QoSProfile(depth=config["qos_depth"],
                     reliability=ReliabilityPolicy.RELIABLE if config["reliability"] == "reliable"
                     else ReliabilityPolicy.BEST_EFFORT,
                     durability=DurabilityPolicy.VOLATILE)
    request_topic = config["topic"] + "/request"
    reply_topic = config["topic"] + "/reply"

    def add_echo():
        node = Node("benchmark_echo")
        publisher = node.create_publisher(Packet, reply_topic, qos)
        subscription = node.create_subscription(Packet, request_topic, publisher.publish, qos)
        nodes.append(node)
        executor.add_node(node)
        return publisher, subscription

    try:
        if echo_only:
            add_echo()
            executor.spin()
            return
        sender = Node("benchmark_source")
        nodes.append(sender)
        executor.add_node(sender)
        publisher = sender.create_publisher(Packet, request_topic, qos)
        received = [None]

        def receive(message):
            received[0] = message

        subscription = sender.create_subscription(Packet, reply_topic, receive, qos)
        if config["placement"] == "native":
            add_echo()
        deadline = time.monotonic() + config["startup_timeout_s"]
        while publisher.get_subscription_count() == 0 or sender.count_publishers(reply_topic) == 0:
            if time.monotonic() >= deadline:
                raise TimeoutError("ROS endpoint discovery timed out")
            executor.spin_once(timeout_sec=0.01)
        expected_payload = array("B", [0x5a]) * config["payload_bytes"]
        packet = Packet(sequence=0, payload=expected_payload)
        serialized_bytes = len(serialize_message(packet))

        def exchange(sequence, full=False):
            received[0] = None
            packet.sequence = sequence
            publisher.publish(packet)
            until = time.monotonic() + config["reply_timeout_s"]
            while time.monotonic() < until:
                executor.spin_once(timeout_sec=max(0.0, until - time.monotonic()))
                response = received[0]
                if response is not None and response.sequence == sequence:
                    received_payload = response.payload
                    if len(received_payload) != len(expected_payload):
                        raise RuntimeError("ROS payload length mismatch")
                    valid = (received_payload == expected_payload if full else
                             (not received_payload or
                              (received_payload[0] == 0x5a and received_payload[-1] == 0x5a)))
                    if not valid:
                        raise RuntimeError("ROS payload corruption")
                    return True
            return False

        from rclpy.utilities import get_rmw_implementation_identifier
        measure(config, exchange, serialized_bytes, full_validation=lambda: exchange(0, True),
                metadata={"transport": "rclpy_same_process_rmw" if config["placement"] == "native"
                          else "rmw_inter_process", "rmw": get_rmw_implementation_identifier()})
    finally:
        executor.shutdown()
        for node in reversed(nodes):
            node.destroy_node()
        rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--echo", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if config["backend"] == "rpp":
        if args.echo:
            parser.error("RPP responders use the standard component server")
        rpp(config)
    else:
        ros(config, args.echo)


if __name__ == "__main__":
    main()
