"""Port allocation shared by local and tunneled, target-local runtimes."""
import os


def runtime_ports(environ=None):
    env = os.environ if environ is None else environ
    ports = {name: int(env.get(f'EGOAGENT_{name}_PORT', default)) for name, default in (
        ('LISTEN', 8880), ('BACKEND', 8765), ('WS', 8766), ('VOID', 8869),
    )}
    if any(not 1024 <= port <= 65535 for port in ports.values()) or len(set(ports.values())) != 4:
        raise ValueError('EgoAgent requires four distinct unprivileged ports (1024–65535)')
    return ports
