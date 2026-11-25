"""The default main HTTP surface, without enabling any development features."""
import json
import threading
import urllib.request
import urllib.error
import pytest


@pytest.fixture
def api_server(tmp_path, monkeypatch):
    from egoagent_server import server
    monkeypatch.setattr(server, 'SESSIONS_DIR', tmp_path / 'sessions')
    monkeypatch.setattr(server, '_PROJECT_ROOT_FOR_IMPORTS', tmp_path)
    http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.APIHandler)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    yield f'http://127.0.0.1:{http.server_port}'
    http.shutdown(); http.server_close(); worker.join(timeout=3)


@pytest.mark.parametrize('path', ['/api/task-bench/tasks', '/api/evolution/proposals', '/api/research/conformance',
                                  '/api/packages', '/api/runs', '/api/training/annotations', '/api/coc/characters',
                                  '/api/agent/create', '/api/remote/connect'])
def test_unreleased_api_is_rejected(api_server, path):
    with pytest.raises(urllib.error.HTTPError) as raised:
        urllib.request.urlopen(api_server + path, timeout=5)
    assert raised.value.code == 403
    assert 'not released' in raised.value.read().decode()


def test_catalog_and_detailed_list_hide_transitive_unreleased_flows(api_server):
    def read(path):
        with urllib.request.urlopen(api_server + path, timeout=10) as response:
            return json.load(response)
    public = read('/api/harnesses')
    identities = read('/api/identities')
    assert any(item['name'] == 'cookbook_reader' for item in identities)
    assert not any(item['name'].startswith(('arc_', 'experiment_', 'coc_')) for item in identities)
    detailed = read('/api/harnesses/detailed')
    assert {'code_agent_fast', 'cookbook_01_react'} <= set(public)
    assert 'adaptive_code_agent' not in public
    assert 'cookbook_22_flow_designer' not in public
    assert not any(item.get('catalog_visibility') == 'unreleased' for item in detailed)
    from product_features import flow_blocker
    assert all(flow_blocker(name) is None for name in public)


def test_new_session_uses_saved_version_configuration(api_server, tmp_path):
    body = {'workspace': str(tmp_path), 'name': 'release-smoke', 'title': 'Release smoke',
            'flow_selection': {'harness': 'code_agent_fast', 'version': 'latest'},
            'agent_config': {'harness': 'ignored', 'mode': 'evolve', 'agents': {'agent': 'test_bot'}}}
    request = urllib.request.Request(api_server + '/api/sessions/create', data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(request, timeout=10) as response:
        created = json.load(response)
    metadata = json.loads((tmp_path / 'sessions' / created['session'] / 'session.json').read_text(encoding='utf-8'))
    config = metadata['agent_config']
    assert config['harness'] == 'code_agent_fast'
    assert config['mode'] == 'agent'
    assert config['harness_version'] and config['harness_version'] != 'latest'
    assert config['agents']['agent'].endswith('adaptive_deepseek_coder')
