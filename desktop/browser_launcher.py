"""Windowless browser entry point; reuse the same services as EgoAgent Desktop.

The desktop shortcut runs this file with pythonw.exe, never EgoAgent.exe.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop import bootstrap
from llm.env_config import load_local_env
from runtime_endpoints import runtime_ports


def browser_url(origin: str, workspace: Path | None = None) -> str:
    parsed = urlsplit(origin)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost')
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/')):
        raise ValueError('Browser launcher requires a local EgoAgent origin')
    url = origin.rstrip('/') + '/'
    if workspace is not None:
        folder = workspace.resolve(strict=True)
        if not folder.is_dir():
            raise ValueError('Workspace must be a directory')
        path = folder.as_posix()
        if not path.startswith('/'):
            path = '/' + path
        url += '?folder=' + quote(path, safe='')
    return url


def launch(root: Path = ROOT, workspace: Path | None = None) -> dict:
    root = root.resolve(strict=True)
    # Validate the folder before starting services; do not leave an unwanted stack.
    if workspace is not None:
        browser_url('http://127.0.0.1:8880', workspace)
    load_local_env(root)
    result = bootstrap.ensure_services(root, runtime_ports())
    url = browser_url(result['origin'], workspace)
    # ShellExecute uses the user's default browser, with no shell command or
    # change to default-app settings. Opening succeeds only after IDE/API health.
    os.startfile(url)
    return {**result, 'url': url, 'browser_requested': True}


def report_failure(message: str, log_path: Path) -> None:
    ctypes.windll.user32.MessageBoxW(
        None, f'无法打开 EgoAgent 浏览器版。\n\n{message}\n\n启动日志：{log_path}\n'
        f'服务日志：{log_path.parent / "services.log"}\n\n没有强制结束其他程序。',
        'EgoAgent 浏览器版 · 启动失败', 0x10,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, help='Optional local project folder')
    args = parser.parse_args(argv)
    log_path = ROOT / '.runtime/desktop/browser-launcher.log'
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # pythonw has no standard streams; dependency diagnostics must not crash it.
        with log_path.open('a', encoding='utf-8', buffering=1) as log:
            old_out, old_err = sys.stdout, sys.stderr
            try:
                sys.stdout = sys.stderr = log
                print(f'\n{datetime.now(timezone.utc).isoformat()} Launch requested', flush=True)
                try:
                    result = launch(workspace=args.workspace)
                except Exception as error:
                    message = str(error)
                    print(json.dumps({'ok': False, 'error': message}, ensure_ascii=False), flush=True)
                    report_failure(message, log_path)
                    return 1
                print(json.dumps(result, ensure_ascii=False), flush=True)
                return 0
            finally:
                sys.stdout, sys.stderr = old_out, old_err
    except OSError as error:
        report_failure(str(error), log_path)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
