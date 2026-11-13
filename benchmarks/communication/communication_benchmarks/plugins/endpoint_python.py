from rpp_plugin_types.communication_benchmarks import Endpoint


class EndpointPython(Endpoint):
    def exchange(self, packet: Endpoint.Packet) -> Endpoint.Packet:
        return packet
