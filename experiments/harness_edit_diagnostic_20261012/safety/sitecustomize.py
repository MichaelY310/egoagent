"""Defense in depth for reviewed offline upstream tests; NOT an OS sandbox."""
import sys


def deny_network(event, args):
    if event == "socket.connect":
        address = args[1]
        # Textual/asyncio may use local sockets; never permit internet endpoints.
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise PermissionError("Diagnostic test process: external network disabled")


sys.addaudithook(deny_network)
