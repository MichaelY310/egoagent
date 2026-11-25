"""Small HTTP adapter; deployment/state logic lives in remote_workspaces."""
import os
from pathlib import Path
from remote_workspaces import RemoteWorkspaceManager, discover_targets, runtime_location

_manager = None


def manager():
    global _manager
    if _manager is None:
        _manager = RemoteWorkspaceManager(Path(__file__).resolve().parents[1])
    return _manager


def handle(handler, path, method):
    if not path.startswith('/api/remote/'):
        return False
    try:
        if method == 'GET' and path == '/api/remote/runtime':
            handler._send_json(runtime_location())
            return True
        if os.environ.get('EGOAGENT_REMOTE_ID'):
            handler._send_error('请在本机 EgoAgent 窗口管理 SSH/WSL 连接', 409)
            return True
        if method == 'GET' and path == '/api/remote/targets':
            handler._send_json(discover_targets())
        elif method == 'GET' and path == '/api/remote/connections':
            handler._send_json({'connections': manager().status()})
        elif method == 'GET' and path.startswith('/api/remote/open/'):
            url = manager().private_urls.get(path.rsplit('/', 1)[-1])
            if not url:
                handler._send_error('连接已断开；请从本机 SSH/WSL 菜单重新连接', 409)
            else:
                handler.send_response(302)
                handler.send_header('Location', url)
                handler.send_header('Cache-Control', 'no-store')
                handler.send_header('Referrer-Policy', 'no-referrer')
                handler.send_header('Content-Length', '0')
                handler.end_headers()
        elif method == 'POST':
            body = handler._read_body()
            if path == '/api/remote/connections':
                handler._send_json(manager().save(body))
            elif path == '/api/remote/connect':
                manager().connect(str(body.get('id', '')), consent=body.get('consent') is True,
                                  include_model_config=body.get('includeModelConfig') is True)
                handler._send_json({'ok': True})
            elif path == '/api/remote/disconnect':
                manager().disconnect(str(body.get('id', '')))
                handler._send_json({'ok': True})
            elif path == '/api/remote/remove':
                manager().delete(str(body.get('id', '')))
                handler._send_json({'ok': True})
            elif path == '/api/remote/rename':
                profile = manager().get(str(body.get('id', '')))
                label = str(body.get('label', '')).strip()
                if not profile or not label:
                    raise ValueError('连接或名称无效')
                profile['label'] = label[:240]
                manager()._update(profile)
                handler._send_json({'ok': True})
            else:
                handler._send_error('Unknown remote operation', 404)
        else:
            handler._send_error('Unknown remote operation', 404)
    except (ValueError, OSError, RuntimeError) as error:
        handler._send_error(str(error), 400)
    return True
