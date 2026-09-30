"""Run inside a connected Linux target; never alters the user's project.

Creates a disposable demo directory and a saved Chat session. A model call is
optional and separate, so offline checks aren't reported as AI validation.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--model-env', type=Path)
    args = parser.parse_args()
    app = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(app))
    base = f'http://127.0.0.1:{args.port}'

    def api(path, body=None):
        # Read the owner-only installed runtime configuration locally, without
        # printing the token or putting it on the command line.
        config_file = app.parent / 'editor/extensions/egoagent-dag-chat/connection-runtime.js'
        config = json.loads(config_file.read_text().split('=', 1)[1].strip().rstrip(';'))
        request = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={'Content-Type': 'application/json', 'X-EgoAgent-Remote-Token': config.get('accessToken', '')})
        with urlopen(request, timeout=20) as response:
            return json.load(response)

    workspace = Path(tempfile.mkdtemp(prefix='egoagent-remote-demo-'))
    sample = workspace / 'hello.py'
    old = 'def answer():\n    return 1\n\nprint(answer())\n'
    new = 'def answer():\n    return 42\n\nprint(answer())\n'
    sample.write_text(old)
    (workspace / 'README.md').write_text('# EgoAgent remote smoke demo\n\nRun `python3 hello.py`. This directory is a generated test fixture.\n')
    result = {'workspace': str(workspace), 'system': platform.system(), 'checks': []}
    print('SMOKE_WORKSPACE=' + str(workspace), flush=True)
    assert api('/api/remote/runtime')['system'] == 'Linux'
    assert len(api('/api/harnesses')) > 10
    assert len(api('/api/identities')) > 5
    result['checks'].extend(['target_identity', 'flow_catalog', 'identity_catalog'])
    # Chat and Workbench need simultaneous live subscriptions. Exercise the
    # browser's token-subprotocol handshake rather than only REST requests.
    import websocket
    config_file = app.parent / 'editor/extensions/egoagent-dag-chat/connection-runtime.js'
    token = json.loads(config_file.read_text().split('=', 1)[1].strip().rstrip(';'))['accessToken']
    connections = []
    try:
        for _ in range(2):
            ws = websocket.create_connection(f'ws://127.0.0.1:{args.port + 2}', timeout=8,
                subprotocols=['egoagent-token.' + token], origin=f'http://test.localhost:{args.port}')
            connections.append(ws)
            assert isinstance(json.loads(ws.recv()), dict)
        result['checks'].append('simultaneous_chat_workbench_websockets')
    finally:
        for ws in connections:
            ws.close()
    edit = api('/api/session/changes/apply-text', {
        'workspace': str(workspace), 'file': str(sample), 'old_text': old, 'new_text': new,
        'transaction_id': workspace.name, 'tool_name': 'remote-smoke',
    })
    change_id = edit['change']['id']
    assert sample.read_text() == new
    api('/api/session/changes/reject', {'id': change_id})
    assert sample.read_text() == old
    api('/api/session/changes/undo', {'id': change_id})
    assert sample.read_text() == new
    api('/api/session/changes/accept', {'id': change_id})
    assert sample.read_text() == new
    api('/api/session/changes/undo', {'id': change_id})
    changes = api('/api/session/changes?' + urlencode({'workspace': str(workspace)}))
    assert any(c['id'] == change_id and c['status'] == 'pending' for c in changes)
    result['checks'].extend(['file_edit', 'refuse', 'undo_refuse', 'accept', 'undo_accept'])
    command = subprocess.run([sys.executable, 'hello.py'], cwd=workspace, capture_output=True, text=True, check=True)
    assert command.stdout.strip() == '42'
    result['checks'].append('linux_command')
    started = api('/api/execution/start', {'workspace': str(workspace), 'harness': 'react_single',
        'agents': {'agent': 'identity/test_bot'}, 'mode': 'chat', 'surface': 'chat'})
    run_id = started.get('run_id') or started.get('state', {}).get('run_id')
    assert run_id, started
    try:
        deadline = time.monotonic() + 15
        state = {}
        while time.monotonic() < deadline:
            state = api('/api/execution/state?' + urlencode({'run_id': run_id}))
            if state.get('waiting_for_input'):
                break
            time.sleep(0.15)
        assert state.get('waiting_for_input'), state
        session_name = state['session_name']
        result['session'] = session_name
        result['checks'].append('chat_flow_waiting_for_user')
    finally:
        api('/api/execution/stop', {'run_id': run_id})
    # Session persistence is finalized by the worker's stop/finally path.
    metadata_path = app / 'sessions' / session_name / 'session.json'
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not metadata_path.is_file():
        time.sleep(0.1)
    metadata = json.loads(metadata_path.read_text())
    assert metadata['workspace'] == str(workspace), metadata['workspace']
    assert metadata['agent_config']['harness'] == 'react_single'
    result['checks'].extend(['target_local_session', 'session_agent_config'])
    # Leave one pending diff for manual editor Accept/Refuse UI inspection.
    result['model_call'] = 'not_requested'
    if args.model_env:
        from llm.env_config import load_local_env
        from llm.custom_llm import CustomLLM
        load_local_env(args.model_env)
        llm = CustomLLM({'max_tokens': 40, 'timeout': 45, 'enable_thinking': False})
        response = llm.chat([{'role': 'user', 'content': 'Reply with only REMOTE_OK.'}])
        result['model_call'] = {'response': response['choices'][0]['message'].get('content', ''), 'model': llm.model}
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
