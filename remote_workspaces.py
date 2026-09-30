"""SSH/WSL connection manager. The entire runtime lives with the project.

This is a user-facing deployment service, deliberately NOT an Agent tool.
Profiles contain endpoints only; runtime data stays on the target. Standard
OpenSSH owns authentication, host-key verification, ProxyJump and encryption.
"""
from __future__ import annotations

import atexit
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import tarfile
import tempfile
import threading
import time
from urllib.parse import quote
from urllib.request import build_opener, ProxyHandler

VOID_VERSION = '1.99.30044'
PRODUCT_PACKAGES = ('llm', 'harness_editor', 'self_evolution', 'task_bench',
                    'tabletop', 'capability_packs', 'scripts', 'environment')
DEPENDENCIES = ('yaml', 'requests', 'urllib3', 'certifi', 'charset_normalizer', 'idna', 'websocket', 'tomli')
SKIP_PARTS = {'__pycache__', 'node_modules', '.git', '.versions', 'sessions', 'data',
              '_runs', 'external', '.egoagent', '.env', '.env.local'}


def _json_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def validate_profile(value):
    kind = value.get('kind')
    if kind not in ('ssh', 'wsl'):
        raise ValueError('连接类型必须是 ssh 或 wsl')
    target = str(value.get('target', '')).strip()
    if kind == 'ssh':
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]{0,199}', target):
            raise ValueError('SSH 请输入 ~/.ssh/config 中的 Host 别名，或 user@host；端口请配置在 SSH config 中')
    elif not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_. -]{0,99}', target):
        raise ValueError('请选择已安装的 WSL 发行版')
    workspace = str(value.get('workspace', '')).strip()
    if not (workspace.startswith('/') or workspace == '~' or workspace.startswith('~/')):
        raise ValueError('项目路径需要是目标机器的 Linux 绝对路径，或 ~/ 开头的路径')
    if any(ord(c) < 32 for c in workspace) or len(workspace) > 2048:
        raise ValueError('项目路径包含无效字符或过长')
    return {'kind': kind, 'target': target, 'workspace': workspace,
            'label': str(value.get('label') or f'{kind.upper()}: {target} · {workspace}')[:240]}


def command_for(profile, argv, *, forwards=False):
    """Never pass user input as shell syntax or SSH options."""
    if profile['kind'] == 'wsl':
        return ['wsl.exe', '--distribution', profile['target'], '--exec', *argv]
    command = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', 'ConnectTimeout=12', '-o', 'ServerAliveInterval=15',
               '-o', 'ServerAliveCountMax=3', '-o', 'ExitOnForwardFailure=yes']
    if forwards:
        for port in range(profile['port'], profile['port'] + 3):
            command.extend(['-L', f'127.0.0.1:{port}:127.0.0.1:{port}'])
    return [*command, profile['target'], shlex.join(argv)]


def _spawn_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def _run(profile, argv, *, data=None, timeout=90):
    try:
        result = subprocess.run(command_for(profile, argv), input=data, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=timeout, **_spawn_options())
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f'{profile["target"]} 的远程操作超过 {timeout} 秒；请检查连接并重试。') from error
    if result.returncode:
        error = result.stderr.decode('utf-8', errors='replace').strip()
        raise RuntimeError(error[-2500:] or f'远程命令退出码 {result.returncode}')
    return result.stdout.decode('utf-8', errors='replace').strip()


def discover_targets():
    hosts = []
    # Read aliases only. Do not return key paths, addresses, proxy commands etc.
    path = Path.home() / '.ssh/config'
    if path.is_file():
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            match = re.match(r'^\s*Host\s+(.+)', line, re.I)
            if match:
                hosts.extend(name for name in match[1].split() if re.fullmatch(r'[A-Za-z0-9_][\w.-]*', name))
    distros, warning = [], ''
    if os.name == 'nt' and shutil.which('wsl.exe'):
        try:
            result = subprocess.run(['wsl.exe', '--list', '--quiet'], capture_output=True,
                                    timeout=10, **_spawn_options())
            output = result.stdout.decode('utf-16-le' if b'\x00' in result.stdout else 'utf-8', errors='replace')
            if result.returncode:
                warning = output.strip()
            else:
                distros = [x.strip() for x in output.splitlines() if x.strip()]
        except (OSError, subprocess.TimeoutExpired) as error:
            warning = str(error)
    return {'ssh': sorted(set(hosts)), 'wsl': distros, 'warning': warning}


def _add_bytes(archive, name, value, mode=0o600):
    info = tarfile.TarInfo(name)
    info.size, info.mode = len(value), mode
    archive.addfile(info, io.BytesIO(value))


def product_files(root):
    """An explicit source allowlist: never glob the user's whole checkout."""
    files = set(root.glob('*.py')) | {root / 'config.yaml', root / 'LICENSE'}
    for package in PRODUCT_PACKAGES:
        files.update((root / package).rglob('*.py'))
    for package in ('harness', 'identity', '.environment/tools', 'capability_packs'):
        base = root / package
        files.update(p for p in base.rglob('*') if p.suffix in {'.py', '.json', '.md', '.txt', '.yaml'})
    # Ship only frontend build outputs, no node_modules or compiler toolchain.
    for package in ('void_extension/egoagent-dag-chat', 'harness_editor/dist'):
        files.update(p for p in (root / package).rglob('*') if p.is_file())
    for path in sorted(files):
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            continue
        relative = path.relative_to(root)
        if set(relative.parts) & SKIP_PARTS or any(part.startswith('.env.') for part in relative.parts):
            continue
        yield path, relative.as_posix()


def product_digest(root):
    digest = hashlib.sha256()
    for path, relative in product_files(root):
        digest.update(relative.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build_bundle(root, destination, editor_archive=None, *, include_model_config=False):
    """Ship pure-Python dependencies; no sudo/pip/large embedding model needed."""
    with tarfile.open(destination, 'w:gz') as archive:
        for path, relative in product_files(root):
            archive.add(path, arcname=f'app/{relative}', recursive=False)
        for module in DEPENDENCIES:
            spec = importlib.util.find_spec(module)
            if spec is None and module == 'tomli':
                spec = importlib.util.find_spec('pip._vendor.tomli')
            if spec is None or not spec.submodule_search_locations:
                raise RuntimeError(f'本机 Python 缺少依赖 {module}；请使用 EgoAgent 的 .venv 启动后端')
            directory = Path(next(iter(spec.submodule_search_locations)))
            for path in directory.rglob('*'):
                if path.is_file() and path.suffix in {'.py', '.pem', '.txt', '.json'} and '__pycache__' not in path.parts:
                    archive.add(path, arcname='app/.deps/' + module + '/' + path.relative_to(directory).as_posix(), recursive=False)
        if editor_archive:
            archive.add(editor_archive, arcname='editor.tar.gz', recursive=False)
        _add_bytes(archive, '.source-digest', product_digest(root).encode())
        if include_model_config:
            # Only known model-provider variables, never arbitrary .env secrets.
            names = re.compile(r'^(DEEPSEEK|SILICONFLOW|OPENAI|ANTHROPIC)_(API_KEY|BASE_URL|MODEL)$|^LLM_(PROVIDER|MODEL|BASE_URL|API_KEY)$|^EGOAGENT_LLM_.*$')
            text = '\n'.join(f'{k}={json.dumps(v)}' for k, v in os.environ.items() if names.fullmatch(k)) + '\n'
            _add_bytes(archive, 'app/.env.local', text.encode())
    return destination


# Input is a product archive; validate every entry before writing ANY file.
# The destination is fixed under the authenticated user's home, not user text.
INSTALL_CODE = r'''
import json,sys,tarfile,tempfile,shutil,os
from pathlib import Path
profile_id=sys.argv[1]
assert len(profile_id)==16 and all(c in '0123456789abcdef' for c in profile_id)
root=Path.home()/'.local/share/egoagent/connections'/profile_id
if root.exists() and not (root/'.egoagent-remote').is_file():
    raise RuntimeError('Refusing to overwrite an unmanaged directory')
root.mkdir(parents=True,exist_ok=True)
root.chmod(0o700)
with tempfile.TemporaryFile() as buffer:
    shutil.copyfileobj(sys.stdin.buffer,buffer); buffer.seek(0)
    with tarfile.open(fileobj=buffer) as arc:
        members=arc.getmembers()
        for m in members:
            p=root/m.name
            if not p.resolve().is_relative_to(root.resolve()) or not (m.isfile() or m.isdir()):
                raise ValueError('Unsafe bundle member: '+m.name)
        for m in members:
            # Retain target-local user modifications of identity/flow on reconnect.
            p=root/m.name
            if p.exists() and m.name.startswith(('app/harness/','app/identity/')): continue
            if m.isdir(): p.mkdir(parents=True,exist_ok=True)
            else:
                p.parent.mkdir(parents=True,exist_ok=True)
                with arc.extractfile(m) as src,p.open('wb') as dst: shutil.copyfileobj(src,dst)
                p.chmod(m.mode & 0o777)
(root/'.egoagent-remote').write_text(profile_id)
print(json.dumps({'root':str(root)}))
'''


class RemoteWorkspaceManager:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.store = self.root / '.egoagent/remote_workspaces.json'
        self.lock = threading.RLock()
        self.jobs = {}
        self.processes = {}
        self.private_urls = {}
        self.cache_lock = threading.Lock()
        self.opener = build_opener(ProxyHandler({}))
        atexit.register(self.close)

    def profiles(self):
        with self.lock:
            return json.loads(self.store.read_text(encoding='utf-8')) if self.store.is_file() else []

    def save(self, value):
        profile = validate_profile(value)
        profile['id'] = secrets.token_hex(8)
        with self.lock:
            profiles = self.profiles()
            profiles.append(profile)
            _json_write(self.store, profiles)
        return profile

    def get(self, profile_id):
        return next((p for p in self.profiles() if p['id'] == profile_id), None)

    def _update(self, profile):
        with self.lock:
            _json_write(self.store, [profile if p['id'] == profile['id'] else p for p in self.profiles()])

    def delete(self, profile_id):
        self.disconnect(profile_id)
        with self.lock:
            _json_write(self.store, [p for p in self.profiles() if p['id'] != profile_id])
        # Keep remote sessions and project files; removing a bookmark is not rm -rf.

    def status(self):
        result = []
        for profile in self.profiles():
            process = self.processes.get(profile['id'])
            job = self.jobs.get(profile['id'], {})
            state = job.get('state', 'disconnected')
            if state == 'connected' and (not process or process.poll() is not None):
                state = 'disconnected'
            result.append({**profile, **job, 'state': state})
        return result

    def _stage(self, profile_id, state, message, **extra):
        with self.lock:
            self.jobs[profile_id] = {'state': state, 'message': message, **extra}

    def connect(self, profile_id, *, consent=False, include_model_config=False):
        if not consent:
            raise ValueError('请先确认安装目标端运行时；默认不传输 API Key、会话或项目内容')
        profile = self.get(profile_id)
        if not profile:
            raise ValueError('找不到这个远程连接')
        with self.lock:
            if self.jobs.get(profile_id, {}).get('state') in {'connecting', 'connected'}:
                process = self.processes.get(profile_id)
                if self.jobs[profile_id]['state'] == 'connecting' or (process and process.poll() is None):
                    return
            self._stage(profile_id, 'connecting', '检查目标环境与项目路径…')
        threading.Thread(target=self._connect, args=(profile, include_model_config), daemon=True).start()

    def _editor(self, arch):
        name = f'void-reh-web-linux-{arch}-{VOID_VERSION}.tar.gz'
        cache = self.root / '.runtime/remote-cache'
        cache.mkdir(parents=True, exist_ok=True)
        path = cache / name
        base = f'https://github.com/voideditor/binaries/releases/download/{VOID_VERSION}/{name}'
        with self.cache_lock:
            checksum_path = path.with_suffix('.sha256')
            if not checksum_path.is_file():
                with self.opener.open(base + '.sha256', timeout=40) as response:
                    checksum = response.read(512).decode().split()[0]
                if not re.fullmatch('[0-9a-fA-F]{64}', checksum):
                    raise ValueError('Void 官方 SHA256 清单无效')
                checksum_path.write_text(checksum)
            expected = checksum_path.read_text().strip().lower()
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
                return path
            temp = path.with_suffix('.download')
            try:
                with self.opener.open(base, timeout=60) as response, temp.open('wb') as output:
                    shutil.copyfileobj(response, output)
                if hashlib.sha256(temp.read_bytes()).hexdigest() != expected:
                    raise ValueError('Void 安装包校验失败；没有执行下载的文件')
                temp.replace(path)
            finally:
                temp.unlink(missing_ok=True)
        return path

    def _allocate(self):
        used = {p.get('port') for p in self.profiles()}
        for base in range(19100, 25000, 10):
            if base in used:
                continue
            sockets = []
            try:
                for port in range(base, base + 4):
                    sock = socket.socket()
                    sockets.append(sock)
                    sock.bind(('127.0.0.1', port))
                return base
            except OSError:
                pass
            finally:
                for sock in sockets:
                    sock.close()
        raise RuntimeError('没有可用的本机端口')

    def _connect(self, profile, include_model_config):
        pid = profile['id']
        try:
            probe = '''import json,platform,sys
from pathlib import Path
p=Path(sys.argv[1]).expanduser().resolve()
r=Path.home()/'.local/share/egoagent/connections'/sys.argv[2]
installed=(r/'editor/out/server-main.js').is_file() and (r/'.egoagent-remote').is_file()
d=r/'.source-digest'
print(json.dumps(dict(system=platform.system(),arch=platform.machine(),version=list(sys.version_info[:2]),workspace=str(p),exists=p.is_dir(),root=str(r) if installed else '',digest=d.read_text() if d.is_file() else '')))
'''
            target = json.loads(_run(profile, ['python3', '-c', probe, profile['workspace'], pid]))
            if target['system'] != 'Linux' or target['arch'] not in {'x86_64', 'aarch64', 'arm64'}:
                raise ValueError('此版本支持 Linux x64/arm64 SSH 主机与 WSL；目标系统不支持')
            if target['version'] < [3, 10]:
                raise ValueError('远程 Python 需要 3.10 或以上；请先配置 python3')
            if not target['exists']:
                raise ValueError('目标项目目录不存在；请输入目标机器上的真实目录，不是 Windows 路径')
            profile['workspace'] = target['workspace']
            with self.lock:
                if not profile.get('port'):
                    profile['port'] = self._allocate()
                self._update(profile)
            # Reconnection does not replace source, Flow versions or identity.
            target_root = target['root']
            if not target_root or include_model_config or target['digest'] != product_digest(self.root):
                editor = None
                if not target_root:
                    self._stage(pid, 'connecting', '准备 Linux 编辑器（首次约 62 MB，直连下载并校验 SHA256）…')
                    editor = self._editor('x64' if target['arch'] == 'x86_64' else 'arm64')
                self._stage(pid, 'connecting', '安装目标端应用与独立依赖；不改动你的项目…')
                with tempfile.TemporaryDirectory(prefix='egoagent-remote-') as temporary:
                    bundle = build_bundle(self.root, Path(temporary) / 'product.tar.gz', editor,
                                          include_model_config=include_model_config)
                    installed = json.loads(_run(profile, ['python3', '-c', INSTALL_CODE, pid],
                                                data=bundle.read_bytes(), timeout=240))
                    target_root = installed['root']
                _run(profile, ['python3', f'{target_root}/app/scripts/remote_runtime.py', 'prepare', target_root], timeout=120)
            profile['runtimeRoot'] = target_root
            self._update(profile)
            self._stage(pid, 'connecting', '启动远程文件、终端、Agent 服务并验证连接…')
            log_path = self.root / '.runtime' / f'remote-{pid}.log'
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open('ab') as log:
                token = secrets.token_urlsafe(32)
                process = subprocess.Popen(command_for(profile, ['python3', f'{target_root}/app/scripts/remote_runtime.py',
                    'serve', target_root], forwards=True),
                    stdout=log, stderr=log, stdin=subprocess.PIPE, **_spawn_options())
            self.processes[pid] = process
            # Secrets travel over stdin, never command-line arguments or profiles.
            process.stdin.write((json.dumps({**profile, 'access_token': token}) + '\n').encode())
            process.stdin.flush()
            deadline = time.monotonic() + 90
            last_error = ''
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(log_path.read_text(encoding='utf-8', errors='replace')[-2500:])
                try:
                    from urllib.request import Request
                    headers = {'X-EgoAgent-Remote-Token': token}
                    with self.opener.open(Request(f'http://127.0.0.1:{profile["port"]}/api/remote/runtime', headers=headers), timeout=2) as response:
                        proof = json.load(response)
                    if proof.get('id') != pid:
                        raise RuntimeError('端口连接到了另一个后端，已拒绝打开以保护本机项目')
                    with self.opener.open(Request(f'http://127.0.0.1:{profile["port"]}/', headers=headers), timeout=3) as response:
                        if response.status != 200:
                            raise RuntimeError('远程编辑器尚未就绪')
                    self.private_urls[pid] = f'http://127.0.0.1:{profile["port"]}/?folder={quote(profile["workspace"], safe="/")}&tkn={token}'
                    from runtime_endpoints import runtime_ports
                    url = f'http://127.0.0.1:{runtime_ports()["LISTEN"]}/api/remote/open/{pid}'
                    self._stage(pid, 'connected', f'已连接 {profile["label"]}', url=url, runtime=proof)
                    return
                except (OSError, ValueError) as error:
                    last_error = str(error)
                time.sleep(0.6)
            raise RuntimeError('远程服务启动超时：' + last_error)
        except Exception as error:
            self._stop_process(pid)
            self._stage(pid, 'error', str(error)[-2500:])

    def _stop_process(self, profile_id):
        self.private_urls.pop(profile_id, None)
        process = self.processes.pop(profile_id, None)
        if process and process.poll() is None:
            # EOF reaches the target supervisor through SSH/WSL. Let it stop
            # its own process group before forcibly terminating the transport.
            if process.stdin:
                process.stdin.close()
            try:
                process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()

    def disconnect(self, profile_id):
        if self.jobs.get(profile_id, {}).get('state') == 'connecting':
            raise ValueError('正在准备连接，请等待完成后断开')
        self._stop_process(profile_id)
        self._stage(profile_id, 'disconnected', '已断开；目标机器上的项目与 Session 保留')

    def close(self):
        for profile_id in list(self.processes):
            self._stop_process(profile_id)


def runtime_location():
    return {'id': os.environ.get('EGOAGENT_REMOTE_ID', ''),
            'app_root': str(Path(__file__).resolve().parent),
            'label': os.environ.get('EGOAGENT_REMOTE_LABEL', '本机'),
            'workspace': os.environ.get('EGOAGENT_REMOTE_WORKSPACE', ''),
            'hostname': socket.gethostname(), 'system': platform.system()}
