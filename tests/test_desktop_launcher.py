"""Desktop lifecycle tests: local HTTP only; never invoke a model or real IDE."""
import json
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

import pytest

from desktop import bootstrap


def test_clipboard_is_automatic_only_for_current_ide_origin():
    source = (Path(__file__).resolve().parents[1] / 'desktop/DesktopApp.cs').read_text(encoding='utf-8')
    handler = source.split('core.PermissionRequested +=', 1)[1].split('private async Task ResetOldClipboardDenials', 1)[0]
    assert 'args.PermissionKind == CoreWebView2PermissionKind.ClipboardRead' in handler
    assert 'DesktopPolicy.IsClipboardOrigin(args.Uri, core.Source, allowedPorts)' in handler
    assert '? CoreWebView2PermissionState.Allow : CoreWebView2PermissionState.Deny' in handler
    assert 'args.SavesInProfile = false' in handler
    assert 'MessageBox.Show' not in handler
    assert 'args.IsUserInitiated' not in handler


@pytest.fixture
def local_service(tmp_path):
    responses = {
        '/api/remote/runtime': {'id': '', 'hostname': 'test-host', 'system': 'Windows', 'app_root': str(tmp_path)},
        '/api/ai/status': {'provider': 'test', 'configured': False},
        '/': '<!DOCTYPE html><title>EgoAgent test</title>',
    }
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            value = responses[self.path]
            is_json = not isinstance(value, str)
            payload = (json.dumps(value) if is_json else value).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json' if is_json else 'text/html')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_port, responses, calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)


def test_probe_checks_editor_and_api_without_model_request(tmp_path, local_service):
    port, _, calls = local_service
    result = bootstrap.probe(tmp_path, port)
    assert result == {'ok': True, 'origin': f'http://127.0.0.1:{port}', 'model_configured': False}
    assert calls == ['/api/remote/runtime', '/api/ai/status', '/']


@pytest.mark.parametrize('field,value', [('id', 'remote-connection'), ('system', 'Linux'), ('hostname', ''), ('app_root', 'C:/other-repository')])
def test_probe_rejects_wrong_runtime(tmp_path, local_service, field, value):
    port, responses, _ = local_service
    responses['/api/remote/runtime'][field] = value
    with pytest.raises(ValueError):
        bootstrap.probe(tmp_path, port)


def test_html_error_is_not_accepted_as_json(tmp_path, local_service):
    port, responses, _ = local_service
    responses['/api/remote/runtime'] = '<!DOCTYPE html>Not an API'
    with pytest.raises(ValueError, match='Expected EgoAgent JSON'):
        bootstrap.probe(tmp_path, port)


def test_local_health_check_ignores_system_proxy(tmp_path, local_service, monkeypatch):
    port, _, _ = local_service
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:1')
    monkeypatch.setenv('http_proxy', 'http://127.0.0.1:1')
    monkeypatch.setenv('NO_PROXY', '')
    assert bootstrap.probe(tmp_path, port)['ok']


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows file locking / process flags')
def test_reuses_healthy_service_without_spawning(tmp_path, local_service):
    port, _, _ = local_service
    with patch.object(bootstrap.subprocess, 'Popen') as launch:
        assert bootstrap.ensure_services(tmp_path, {'LISTEN': port})['started'] is False
        launch.assert_not_called()


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows file locking')
def test_unknown_port_owner_is_not_terminated_or_replaced(tmp_path):
    with patch.object(bootstrap, 'probe', side_effect=ValueError('foreign app')), \
            patch.object(bootstrap, 'can_connect', return_value=True), \
            patch.object(bootstrap.time, 'sleep'), patch.object(bootstrap.subprocess, 'Popen') as launch:
        with pytest.raises(RuntimeError, match='没有强制结束'):
            bootstrap.ensure_services(tmp_path, {'LISTEN': 18880})
        launch.assert_not_called()


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows file locking / process flags')
def test_cold_start_records_ownership_and_passes_explicit_ports(tmp_path):
    python = tmp_path / '.venv/Scripts/python.exe'
    python.parent.mkdir(parents=True)
    python.touch()
    server = tmp_path / 'void-web/out/server-main.js'
    server.parent.mkdir(parents=True)
    server.touch()
    ports = {'LISTEN': 18880, 'BACKEND': 18765, 'VOID': 18869, 'WS': 18766}
    process = Mock(pid=1234)
    process.poll.return_value = None
    with patch.object(bootstrap, 'probe', side_effect=[OSError('offline'), {'ok': True}]), \
            patch.object(bootstrap, 'can_connect', return_value=False), \
            patch.object(bootstrap.subprocess, 'Popen', return_value=process) as launch:
        assert bootstrap.ensure_services(tmp_path, ports)['started'] is True
    args, kwargs = launch.call_args
    assert args[0][:3] == [str(python), '-u', str(tmp_path / 'start-all.py')]
    assert args[0][3] == '--stop-file'
    assert kwargs['env']['EGOAGENT_LISTEN_PORT'] == '18880'
    assert kwargs['env']['EGOAGENT_HOST'] == '127.0.0.1'
    assert kwargs['creationflags'] & bootstrap.subprocess.CREATE_NO_WINDOW
    record = json.loads((tmp_path / '.runtime/desktop/services.json').read_text())
    assert record['pid'] == 1234
    assert not Path(record['stop_file']).exists()
    assert bootstrap.stop_services(tmp_path)['ok']
    assert Path(record['stop_file']).exists()
    process.kill.assert_not_called()


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows file locking')
@pytest.mark.parametrize('marker', ['../../not-owned.stop', 'not-a-uuid.stop'])
def test_stop_cannot_write_outside_private_marker(tmp_path, marker):
    state = tmp_path / '.runtime/desktop'
    state.mkdir(parents=True)
    (state / 'services.json').write_text(json.dumps({'root': str(tmp_path), 'stop_file': str(state / marker)}))
    with pytest.raises(ValueError, match='ownership'):
        bootstrap.stop_services(tmp_path)
    assert not (state / marker).exists()


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows file locking')
def test_stop_cannot_take_over_manual_service(tmp_path):
    with pytest.raises(RuntimeError, match='不是桌面版启动'):
        bootstrap.stop_services(tmp_path)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows file locking')
def test_two_windows_serialize_startup(tmp_path):
    path = tmp_path / 'start.lock'
    entered = threading.Event()
    acquired = threading.Event()

    def second_window():
        entered.set()
        with bootstrap.startup_lock(path, timeout=3):
            acquired.set()

    with bootstrap.startup_lock(path):
        worker = threading.Thread(target=second_window)
        worker.start()
        assert entered.wait(1)
        assert not acquired.wait(0.15)
    worker.join(4)
    assert acquired.is_set()


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows file locking / process flags')
def test_cold_start_timeout_signals_only_owned_child(tmp_path):
    for relative in ['.venv/Scripts/python.exe', 'void-web/out/server-main.js']:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    process = Mock(pid=4321)
    with patch.object(bootstrap, 'probe', side_effect=OSError('offline')), \
            patch.object(bootstrap, 'can_connect', return_value=False), \
            patch.object(bootstrap.subprocess, 'Popen', return_value=process):
        with pytest.raises(TimeoutError):
            bootstrap.ensure_services(tmp_path, {'LISTEN': 18880}, timeout=0)
    markers = list((tmp_path / '.runtime/desktop').glob('*.stop'))
    assert len(markers) == 1
    process.kill.assert_not_called()
