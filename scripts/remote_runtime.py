"""Target-side, stdlib-only lifecycle for an isolated EgoAgent installation.

Invoked over an existing authenticated SSH channel or wsl.exe, never as root.
No system packages, project files, SSH settings or firewall rules are changed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time


def safe_extract(archive, destination):
    """Accept regular files/directories only, including on Python < 3.12."""
    root = Path(destination).resolve()
    for member in archive.getmembers():
        path = root / member.name
        if not path.resolve().is_relative_to(root) or not (member.isfile() or member.isdir()):
            raise ValueError(f'Unsafe archive member: {member.name}')
    for member in archive.getmembers():
        path = root / member.name
        if member.isdir():
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, path.open('wb') as target:
                shutil.copyfileobj(source, target)
            path.chmod(member.mode & 0o777)


def prepare(root: Path):
    editor = root / 'editor'
    if not (editor / 'out/server-main.js').is_file():
        editor.mkdir(exist_ok=True)
        with tarfile.open(root / 'editor.tar.gz') as archive:
            safe_extract(archive, editor)
    (editor / 'node').chmod(0o755)
    # Native terminal helpers need execute permissions as well.
    for pattern in ('node_modules/node-pty/build/Release/spawn-helper',
                    'node_modules/@vscode/ripgrep/bin/rg'):
        item = editor / pattern
        if item.is_file():
            item.chmod(0o755)
    print(json.dumps({'prepared': True, 'root': str(root)}), flush=True)


def serve(root: Path, profile: dict):
    app = root / 'app'
    port = profile['port']
    sockets = []
    try:
        for value in range(port, port + 4):
            sock = socket.socket()
            sockets.append(sock)
            # Match the real listeners: recently closed TCP connections can
            # remain in TIME_WAIT after a clean disconnect. They are not a
            # competing server and must not prevent an immediate reconnect.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', value))
    finally:
        for sock in sockets:
            sock.close()
    env = os.environ.copy()
    env.update({
        'PYTHONPATH': str(app / '.deps') + os.pathsep + str(app),
        'PYTHONUNBUFFERED': '1', 'EGOAGENT_HOST': '127.0.0.1',
        'EGOAGENT_VOID_ROOT': str(root / 'editor'),
        'EGOAGENT_LISTEN_PORT': str(port), 'EGOAGENT_BACKEND_PORT': str(port + 1),
        'EGOAGENT_WS_PORT': str(port + 2), 'EGOAGENT_VOID_PORT': str(port + 3),
        'EGOAGENT_REMOTE_ID': profile['id'],
        'EGOAGENT_REMOTE_LABEL': profile['label'],
        'EGOAGENT_REMOTE_WORKSPACE': profile['workspace'],
    })
    # Isolate editor preferences/extensions for each remote connection.
    # start-all consumes this rather than contaminating an existing Void install.
    env['EGOAGENT_VOID_DATA'] = str(root / 'editor-data')
    env['EGOAGENT_REMOTE_TOKEN'] = profile.pop('access_token')
    # Void's static resources include installed extension code. Put the whole
    # editor behind a private Unix socket, not a second unauthenticated port.
    env['EGOAGENT_VOID_SOCKET'] = str(root / 'editor.sock')
    process = subprocess.Popen([sys.executable, str(app / 'start-all.py')],
                               cwd=app, env=env, start_new_session=True)

    def stop(*_args):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, stop)
    def watch_transport():
        try:
            # Do not hold Python's buffered-stdin lock in a daemon thread at
            # interpreter shutdown (notably Python 3.10 reports a fatal error).
            while os.read(sys.stdin.fileno(), 4096):
                pass
        finally:
            stop()
    threading.Thread(target=watch_transport, daemon=True).start()
    try:
        while process.poll() is None:
            time.sleep(0.5)
        return process.returncode
    finally:
        stop()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'serve'])
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / '.egoagent-remote').is_file():
        raise ValueError('Not an EgoAgent-managed remote directory')
    if args.operation == 'prepare':
        prepare(root)
    else:
        profile = json.loads(sys.stdin.buffer.readline())
        sys.exit(serve(root, profile))


if __name__ == '__main__':
    main()
