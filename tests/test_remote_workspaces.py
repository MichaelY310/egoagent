"""Remote routing, packaging and lifecycle regressions; no SSH/API calls."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import threading
import socket
import ast
import time
from types import SimpleNamespace
import urllib.request
import urllib.error
from unittest.mock import patch

from remote_workspaces import (RemoteWorkspaceManager, command_for, validate_profile,
                               product_files, runtime_location, INSTALL_CODE)
from runtime_endpoints import runtime_ports
from scripts.remote_runtime import safe_extract
from local_api_security import remote_request_authorized

ROOT = Path(__file__).resolve().parents[1]


class RemoteWorkspaceTests(unittest.TestCase):
    def test_editor_tunnel_survives_idle_after_connection_timeout(self):
        # Execute the actual relay method without importing the launcher's
        # process/environment setup. A short initial timeout models idle loss.
        tree = ast.parse((ROOT / 'start-all.py').read_text(encoding='utf-8'))
        handler_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ProxyHandler')
        method = next(n for n in handler_class.body if isinstance(n, ast.FunctionDef) and n.name == '_ws_tunnel')
        client, relay_client = socket.socketpair()
        upstream, relay_upstream = socket.socketpair()
        relay_upstream.settimeout(0.03)
        client.settimeout(2); upstream.settimeout(2)
        namespace = {'socket': socket, 'threading': threading, 'VOID_PORT': 19103,
                     '_connect_void': lambda: relay_upstream}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<actual relay>', 'exec'), namespace)
        handler = SimpleNamespace(_guard=lambda: True, request=relay_client, command='GET', path='/',
                                  request_version='HTTP/1.1', headers={'Host': 'localhost'})
        worker = threading.Thread(target=namespace['_ws_tunnel'], args=(handler,), daemon=True)
        worker.start()
        try:
            request = b''
            while not request.endswith(b'\r\n\r\n'):
                request += upstream.recv(1024)
            upstream.sendall(b'ready')
            self.assertEqual(client.recv(5), b'ready')
            time.sleep(0.08)
            self.assertTrue(worker.is_alive())
            client.sendall(b'ping')
            self.assertEqual(upstream.recv(4), b'ping')
            upstream.sendall(b'pong')
            self.assertEqual(client.recv(4), b'pong')
        finally:
            for channel in (client, upstream, relay_client, relay_upstream):
                try: channel.shutdown(socket.SHUT_RDWR)
                except OSError: pass
            worker.join(timeout=2)
            for channel in (client, upstream, relay_client, relay_upstream): channel.close()
        self.assertFalse(worker.is_alive())

    def test_real_websocket_handshake_auth_origin_and_selected_protocol(self):
        from harness_editor.server import accept_ws_connection
        cases = [('', 'http://localhost:19100', '401'),
                 ('egoagent-token.test-secret', 'https://evil.example', '403'),
                 ('egoagent-token.test-secret', 'http://test.localhost:19100', '101')]
        for protocol, origin, status in cases:
            with self.subTest(status=status), patch.dict(os.environ, {'EGOAGENT_REMOTE_TOKEN': 'test-secret'}):
                client, server = socket.socketpair()
                client.settimeout(3)
                with patch('harness_editor.server.handle_ws') as handle:
                    thread = threading.Thread(target=accept_ws_connection, args=(server,))
                    thread.start()
                    request = ('GET / HTTP/1.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                               'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
                               f'Origin: {origin}\r\nSec-WebSocket-Protocol: {protocol}\r\n\r\n')
                    client.sendall(request.encode())
                    response = client.recv(4096).decode()
                    thread.join(timeout=3)
                    client.close()
                    self.assertIn('HTTP/1.1 ' + status, response)
                    self.assertEqual(handle.call_count, int(status == '101'))
                    if status == '101':
                        self.assertIn('Sec-WebSocket-Protocol: egoagent-token.test-secret\r\n', response)

    def test_remote_http_auth_and_preflight_without_weakening_origin_guard(self):
        from harness_editor.server import ThreadingHTTPServer, APIHandler
        with patch.dict(os.environ, {'EGOAGENT_REMOTE_TOKEN': 'test-secret', 'EGOAGENT_REMOTE_ID': 'test'}):
            server = ThreadingHTTPServer(('127.0.0.1', 0), APIHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f'http://127.0.0.1:{server.server_port}/api/remote/runtime'
            try:
                with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                    urllib.request.urlopen(url)
                self.assertEqual(unauthorized.exception.code, 401)
                request = urllib.request.Request(url, headers={'X-EgoAgent-Remote-Token': 'test-secret'})
                with urllib.request.urlopen(request) as response:
                    self.assertEqual(json.load(response)['id'], 'test')
                preflight = urllib.request.Request(url, method='OPTIONS', headers={
                    'Origin': 'http://test.localhost:19100', 'Access-Control-Request-Headers': 'X-EgoAgent-Remote-Token'})
                with urllib.request.urlopen(preflight) as response:
                    self.assertIn('x-egoagent-remote-token', response.headers['Access-Control-Allow-Headers'].lower())
                evil = urllib.request.Request(url, headers={'X-EgoAgent-Remote-Token': 'test-secret', 'Origin': 'https://evil.example'})
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(evil)
                self.assertEqual(denied.exception.code, 403)
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)
    def test_remote_auth_requires_secret_and_supports_browser_websocket(self):
        with patch.dict(os.environ, {'EGOAGENT_REMOTE_TOKEN': 'test-secret', 'EGOAGENT_REMOTE_ID': 'test'}):
            self.assertFalse(remote_request_authorized({}))
            self.assertFalse(remote_request_authorized({'Origin': 'http://localhost:8880'}))
            self.assertFalse(remote_request_authorized({'X-EgoAgent-Remote-Token': 'wrong'}))
            self.assertFalse(remote_request_authorized({'X-EgoAgent-Remote-Token': '非法'}))
            self.assertTrue(remote_request_authorized({'X-EgoAgent-Remote-Token': 'test-secret'}))
            self.assertTrue(remote_request_authorized({'Cookie': 'egoagent_remote_test=test-secret'}))
            self.assertTrue(remote_request_authorized({'Sec-WebSocket-Protocol': 'egoagent-token.test-secret'}))
    def test_profiles_reject_options_control_characters_and_host_shell_injection(self):
        for target in ('-oProxyCommand=oops', 'x;touch foo', 'host\narg', '$(id)', 'a b', 'x:22'):
            with self.assertRaises(ValueError):
                validate_profile(dict(kind='ssh', target=target, workspace='/tmp/project'))
        for workspace in ('C:\\repo', '', 'relative/path', '/tmp/\nsecret'):
            with self.assertRaises(ValueError):
                validate_profile(dict(kind='ssh', target='server', workspace=workspace))
        self.assertEqual(validate_profile(dict(kind='wsl', target='Ubuntu', workspace='~/My Project'))['workspace'], '~/My Project')

    def test_ssh_uses_verified_host_keys_and_loopback_only_forwarding(self):
        p = dict(kind='ssh', target='server', port=19100)
        args = command_for(p, ['python3', '-c', 'print(1)', '/tmp/my project; echo oops'], forwards=True)
        self.assertIn('StrictHostKeyChecking=yes', args)
        self.assertIn('BatchMode=yes', args)
        self.assertIn('ExitOnForwardFailure=yes', args)
        self.assertEqual(args.count('-L'), 3)
        self.assertIn('127.0.0.1:19101:127.0.0.1:19101', args)
        self.assertIn("'/tmp/my project; echo oops'", args[-1])
        self.assertNotIn('-A', args)

    def test_wsl_preserves_paths_as_arguments(self):
        args = command_for(dict(kind='wsl', target='Ubuntu'), ['python3', '-c', 'x', '/tmp/a b'])
        self.assertEqual(args, ['wsl.exe', '--distribution', 'Ubuntu', '--exec', 'python3', '-c', 'x', '/tmp/a b'])

    def test_ports_default_and_invalid(self):
        self.assertEqual(runtime_ports({})['BACKEND'], 8765)
        with self.assertRaises(ValueError):
            runtime_ports({'EGOAGENT_BACKEND_PORT': '8880'})
        with self.assertRaises(ValueError):
            runtime_ports({'EGOAGENT_VOID_PORT': '80'})

    def test_bundle_excludes_runtime_and_private_material(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in ('agent.py', '.env.local', 'sessions/a.py', 'research/key.py',
                         '.environment/user_info.txt', '.environment/tools/x/meta.json',
                         'identity/coder/.versions/a.json', 'harness/x/config.json',
                         'harness_editor/node_modules/foo.py', 'scripts/__pycache__/x.py'):
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('test')
            files = {relative for _, relative in product_files(root)}
            self.assertEqual(files, {'agent.py', '.environment/tools/x/meta.json', 'harness/x/config.json'})

    def test_archive_rejects_traversal_and_symlinks_before_writing(self):
        for bad_name, symlink in [('../escape', False), ('/tmp/escape', False), ('link', True)]:
            with tempfile.TemporaryDirectory() as d:
                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode='w') as arc:
                    first = tarfile.TarInfo('ok.txt'); first.size = 1
                    arc.addfile(first, io.BytesIO(b'x'))
                    bad = tarfile.TarInfo(bad_name)
                    if symlink:
                        bad.type, bad.linkname = tarfile.SYMTYPE, '/tmp'
                    arc.addfile(bad)
                stream.seek(0)
                with tarfile.open(fileobj=stream) as arc, self.assertRaises(ValueError):
                    safe_extract(arc, d)
                self.assertEqual(list(Path(d).iterdir()), [])

    def test_safe_archive_restores_newlines_and_executable_bits(self):
        with tempfile.TemporaryDirectory() as d:
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w') as arc:
                item = tarfile.TarInfo('nested/program'); item.size = 4; item.mode = 0o755
                arc.addfile(item, io.BytesIO(b'a\nb\n'))
            stream.seek(0)
            with tarfile.open(fileobj=stream) as arc:
                safe_extract(arc, d)
            self.assertEqual((Path(d) / 'nested/program').read_bytes(), b'a\nb\n')

    def test_manager_roundtrip_consent_and_remove_only_bookmark(self):
        with tempfile.TemporaryDirectory() as d:
            manager = RemoteWorkspaceManager(d)
            p = manager.save(dict(kind='wsl', target='Ubuntu', workspace='/tmp/demo'))
            self.assertEqual(manager.get(p['id'])['target'], 'Ubuntu')
            with self.assertRaises(ValueError):
                manager.connect(p['id'])
            file = Path(d) / 'preserved.txt'; file.write_text('keep')
            manager.delete(p['id'])
            self.assertEqual(manager.profiles(), [])
            self.assertTrue(file.is_file())

    def test_remote_identity_proof_does_not_depend_on_folder_name(self):
        with patch.dict(os.environ, {'EGOAGENT_REMOTE_ID': 'abc', 'EGOAGENT_REMOTE_WORKSPACE': '/same/path'}):
            self.assertEqual(runtime_location()['id'], 'abc')

    def test_frontend_forces_target_api_and_routes_websockets(self):
        script = r'''
const Module=require('module'); const old=Module._load;
Module._load=function(id,...args){
  if(id==='vscode')return {workspace:{getConfiguration:()=>({get:()=> 'http://127.0.0.1:8765'})}};
  if(id==='./connection-runtime')return {id:'remote',backendUrl:'http://127.0.0.1:19101'};
  return old.call(this,id,...args);
};
const r=require('./void_extension/egoagent-dag-chat/remote-workspaces.js');
if(r.backendUrl()!=='http://127.0.0.1:19101')throw Error('Local backend leak');
if(r.webSocketUrl(r.backendUrl())!=='ws://127.0.0.1:19102')throw Error('Wrong WS port');
'''
        subprocess.run(['node', '-e', script], cwd=ROOT, check=True, capture_output=True)

    def test_workbench_can_load_scoped_auth_script(self):
        source = (ROOT / 'void_extension/egoagent-dag-chat/extension-v21.js').read_text(encoding='utf-8')
        panel_options = source.split("createWebviewPanel('egoagent.workbench'", 1)[1].split('});', 1)[0]
        self.assertIn("vscode.Uri.joinPath(workbenchContext.extensionUri, 'media')", panel_options)
        self.assertIn("'media', 'remote-network.js'", source)
        self.assertIn('runtimeLabel: remoteWorkspaces.runtimeLabel', source)

    def test_workbench_change_links_open_the_review_transaction(self):
        bridge = (ROOT / 'harness_editor/src/ideBridge.ts').read_text(encoding='utf-8')
        dashboard = (ROOT / 'harness_editor/src/components/ChangeDashboard.tsx').read_text(encoding='utf-8')
        extension = (ROOT / 'void_extension/egoagent-dag-chat/extension-v21.js').read_text(encoding='utf-8')
        self.assertIn("'open-change', { id, hunkId }", bridge)
        self.assertIn('openAgentChangeInIde(change.id, hunk?.id)', dashboard)
        self.assertIn('void openChange(change, hunk)', dashboard)
        self.assertIn('openBackendDiff(message.id, message.hunkId)', extension)

    def test_editor_path_matching_preserves_linux_case_and_root(self):
        script = r'''
const fs=require('fs'), vm=require('vm');
const source=fs.readFileSync('void_extension/egoagent-dag-chat/extension-v21.js','utf8');
const functions=source.slice(source.indexOf('function fsPathForBackend('),source.indexOf('function applyLineHunks('));
const scope={};vm.createContext(scope);vm.runInContext(functions,scope);
if(scope.sameDocumentPath({path:'/tmp/Foo.py'},'/tmp/foo.py'))throw Error('Case conflation');
if(!scope.sameDocumentPath({path:'/C:/Foo.py'},'c:/foo.py'))throw Error('Windows regression');
if(scope.fsPathForBackend({path:'/'})!=='/')throw Error('Lost root');
'''
        subprocess.run(['node', '-e', script], cwd=ROOT, check=True, capture_output=True)

    def test_webview_auth_does_not_leak_to_external_requests(self):
        script = r'''
const vm=require('vm'), fs=require('fs');
const calls=[];
class WebSocket {constructor(url,protocols){this.protocols=protocols;}}
const window={__EGOAGENT_WORKBENCH__:{apiBase:'http://127.0.0.1:19101',wsBase:'ws://127.0.0.1:19102',accessToken:'test-token'},
 fetch:(url,options)=>{calls.push({url,options});return Promise.resolve({});},WebSocket};
vm.runInNewContext(fs.readFileSync('void_extension/egoagent-dag-chat/media/remote-network.js','utf8'),
 {window,document:{},Headers,Request,URL,location:{href:'http://test.localhost:19100/'}});
window.fetch('http://127.0.0.1:19101/api/runtime');
window.fetch('https://external.example/research');
if(calls[0].options.headers.get('X-EgoAgent-Remote-Token')!=='test-token')throw Error('Missing auth');
if(calls[1].options.headers)throw Error('Leaked auth');
if(!new window.WebSocket('ws://127.0.0.1:19102').protocols.includes('egoagent-token.test-token'))throw Error('Missing WS auth');
if(new window.WebSocket('wss://external.example').protocols.length)throw Error('Leaked WS auth');
'''
        subprocess.run(['node', '-e', script], cwd=ROOT, check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
