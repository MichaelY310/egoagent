"""Local desktop service lifecycle; no browser UI, credentials or shell commands.

The desktop reuses an existing healthy stack and leaves it running on window
close. An explicit stop only signals a stack started with our own stop marker.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid


def read_json(url, timeout=3):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=timeout) as response:
        if 'application/json' not in response.headers.get('Content-Type', ''):
            raise ValueError('Expected EgoAgent JSON, not a different web page')
        return json.load(response)


def probe(root: Path, port: int):
    origin = f'http://127.0.0.1:{port}'
    runtime = read_json(origin + '/api/remote/runtime')
    if (not isinstance(runtime, dict) or runtime.get('id') != ''
            or runtime.get('system') != 'Windows' or not runtime.get('hostname')):
        raise ValueError('This port does not point to the local EgoAgent runtime')
    if runtime.get('app_root') and Path(runtime['app_root']).resolve() != root.resolve():
        raise ValueError('端口已被另一份 EgoAgent 仓库使用，请先关闭那份服务')
    status = read_json(origin + '/api/ai/status')
    if not isinstance(status, dict) or 'provider' not in status or 'configured' not in status:
        raise ValueError('EgoAgent API is not ready')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(origin + '/', timeout=3) as response:
        if response.status != 200 or 'text/html' not in response.headers.get('Content-Type', ''):
            raise ValueError('IDE is not ready')
    return {'ok': True, 'origin': origin, 'model_configured': status['configured']}


@contextlib.contextmanager
def startup_lock(path: Path, timeout=120):
    import msvcrt
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as lock:
        if path.stat().st_size == 0:
            lock.write(b'0')
            lock.flush()
        until = time.monotonic() + timeout
        while True:
            try:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= until:
                    raise TimeoutError('另一个窗口仍在启动服务；请稍后重试')
                time.sleep(0.25)
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def can_connect(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.4):
            return True
    except OSError:
        return False


def ensure_services(root: Path, ports, timeout=100):
    state_dir = root / '.runtime' / 'desktop'
    with startup_lock(state_dir / 'start.lock'):
        try:
            return {**probe(root, ports['LISTEN']), 'started': False}
        except (OSError, ValueError, urllib.error.URLError):
            if can_connect(ports['LISTEN']):
                # A previous launcher can still be warming up, but never kill
                # an unknown port owner or silently display an unrelated app.
                for _ in range(10):
                    time.sleep(0.5)
                    try:
                        return {**probe(root, ports['LISTEN']), 'started': False}
                    except (OSError, ValueError, urllib.error.URLError):
                        pass
                raise RuntimeError(f'{ports["LISTEN"]} 端口已有服务，但 IDE/API 健康检查未通过。请查看日志；没有强制结束任何进程。')
        python = root / '.venv' / 'Scripts' / 'python.exe'
        if not python.is_file() or not (root / 'void-web' / 'out' / 'server-main.js').is_file():
            raise RuntimeError('缺少 .venv 或 void-web，请先按 README 完成仓库运行环境安装')
        instance = uuid.uuid4().hex
        stop_file = state_dir / (instance + '.stop')
        log_file = state_dir / 'services.log'
        env = os.environ.copy()
        env.update({f'EGOAGENT_{name}_PORT': str(value) for name, value in ports.items()})
        env['EGOAGENT_HOST'] = '127.0.0.1'
        with log_file.open('ab') as log:
            process = subprocess.Popen(
                [str(python), '-u', str(root / 'start-all.py'), '--stop-file', str(stop_file)],
                cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        record = {'pid': process.pid, 'stop_file': str(stop_file), 'root': str(root), 'port': ports['LISTEN']}
        temporary = state_dir / 'services.json.tmp'
        temporary.write_text(json.dumps(record), encoding='utf-8')
        temporary.replace(state_dir / 'services.json')
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if process.poll() is not None:
                raise RuntimeError(f'后台启动失败（退出码 {process.returncode}）。日志：{log_file}')
            try:
                return {**probe(root, ports['LISTEN']), 'started': True, 'pid': process.pid}
            except (OSError, ValueError, urllib.error.URLError):
                time.sleep(0.5)
        stop_file.touch(exist_ok=True)  # Signal only the process we just started.
        raise TimeoutError(f'启动超过 {timeout} 秒，已请求停止此次启动。日志：{log_file}')


def stop_services(root: Path):
    state_dir = root / '.runtime' / 'desktop'
    with startup_lock(state_dir / 'start.lock'):
        record_path = state_dir / 'services.json'
        if not record_path.is_file():
            raise RuntimeError('当前后台不是桌面版启动的，因此不会强制关闭。关闭窗口不会影响该后台。')
        record = json.loads(record_path.read_text(encoding='utf-8'))
        marker = Path(record['stop_file']).resolve()
        if (Path(record['root']).resolve() != root.resolve() or marker.parent != state_dir.resolve()
                or not re.fullmatch(r'[0-9a-f]{32}\.stop', marker.name)):
            raise ValueError('Invalid desktop ownership record')
        marker.touch(exist_ok=True)
        return {'ok': True, 'message': '已请求桌面版启动的后台安全退出；其他手动启动的服务不会被强杀。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    sys.path.insert(0, str(root))
    from llm.env_config import load_local_env
    from runtime_endpoints import runtime_ports
    load_local_env(root)
    ports = runtime_ports()
    result = stop_services(root) if args.stop else probe(root, ports['LISTEN']) if args.check else ensure_services(root, ports)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        main()
    except Exception as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False))
        sys.exit(1)
