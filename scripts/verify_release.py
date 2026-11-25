"""Run deterministic release tests in an exported checkout, without credentials.

Usage: python scripts/verify_release.py --output tmp/verification [pytest args...]
Use a fresh copy, not a workspace containing real Sessions. Real-provider and
real IDE/platform tests are separate, explicitly recorded acceptance work.
"""
import argparse
import ipaddress
import os
from pathlib import Path
import socket
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args, extra = parser.parse_known_args()
    root = Path(__file__).resolve().parents[1]
    if (root / '.env.local').exists() or (root / '.env').exists():
        parser.error('Use a clean exported checkout without local credential files.')
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for key in list(os.environ):
        if key.startswith(('EGOAGENT_', 'DEEPSEEK_', 'SILICONFLOW_', 'OPENAI_', 'ANTHROPIC_')) or key.endswith(('_API_KEY', '_TOKEN')):
            os.environ.pop(key, None)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', EGOAGENT_EMBEDDING_PROVIDER='disabled')
    connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple):
            host = str(address[0])
            try:
                allowed = host == 'localhost' or ipaddress.ip_address(host).is_loopback
            except ValueError:
                allowed = False
            if not allowed:
                raise RuntimeError('External network is disabled during release unit tests')
        return connect(sock, address)
    socket.socket.connect = local_connect
    os.chdir(root)
    sys.path.insert(0, str(root))
    import pytest
    return pytest.main([*(extra or ['tests']), '-q', '-p', 'no:cacheprovider',
                        f'--basetemp={output / "pytest"}', f'--junitxml={output / "results.xml"}'])


if __name__ == '__main__':
    raise SystemExit(main())
