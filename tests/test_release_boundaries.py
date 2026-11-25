"""Regression checks for the independently reproduced 2026-11-23 findings.

No real credentials, network models or user workspaces are used.
"""
import json
import time
import zipfile
from unittest.mock import patch

import pytest

from environment import render_knowledge_content
from llm.env_config import SecretView
from llm.providers import AnthropicCompatibleLLM
from product_features import disabled_api, enabled, flow_blocker, manifests
from product_runtime import ProductRuntimeError, _archive_member, apply_local_update, create_diagnostics_bundle, save_product_settings
from agent_package import PackageError, build_manifest, pack_package, inspect_package


@pytest.mark.parametrize('path', ['C:/escape.txt', 'C:escape.txt', '/absolute', '\\\\host\\share\\x', '../x', 'a/../x', 'safe/file:stream', 'a. /x'])
def test_update_rejects_windows_and_posix_escape(path):
    with pytest.raises(ProductRuntimeError):
        _archive_member(path)


def test_unsafe_archive_does_not_partially_update(tmp_path):
    (tmp_path / 'safe.txt').write_text('old')
    archive_path = tmp_path / 'update.zip'
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr('.egoagent-update.json', json.dumps({'format': 'ego.update.v1'}))
        archive.writestr('safe.txt', 'new')
        archive.writestr('C:/escape.txt', 'bad')
    with pytest.raises(ProductRuntimeError):
        apply_local_update(tmp_path, archive_path)
    assert (tmp_path / 'safe.txt').read_text() == 'old'


def test_knowledge_secrets_require_scoped_authority():
    secret = 'not-a-real-credential'
    with patch.dict('os.environ', {'AUDIT_SECRET': secret}):
        for view in [None, SecretView([])]:
            with pytest.raises(PermissionError):
                render_knowledge_content('{{env.AUDIT_SECRET}}', secret_view=view)
        view = SecretView(['AUDIT_SECRET'])
        assert view.redact_value(render_knowledge_content('{{env.AUDIT_SECRET}}', secret_view=view)) == '[REDACTED]'
    assert render_knowledge_content('ordinary knowledge') == 'ordinary knowledge'


def test_anthropic_credential_origin_and_explicit_priority():
    with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'global-fake', 'MY_KEY': 'configured-fake'}, clear=True):
        cfg = {'base_url': 'https://custom.invalid', 'model': 'fixture', 'api_key': 'explicit-fake'}
        assert AnthropicCompatibleLLM(cfg)._headers()['x-api-key'] == 'explicit-fake'
        cfg.pop('api_key')
        assert 'x-api-key' not in AnthropicCompatibleLLM(cfg)._headers()
        cfg['api_key_env'] = 'MY_KEY'
        assert AnthropicCompatibleLLM(cfg)._headers()['x-api-key'] == 'configured-fake'
        assert AnthropicCompatibleLLM({'base_url': 'https://api.anthropic.com', 'model': 'fixture'})._headers()['x-api-key'] == 'global-fake'


def test_signature_required_is_not_merely_present(tmp_path):
    identity = tmp_path / 'identity' / 'fixture'
    identity.mkdir(parents=True)
    (identity / 'id.json').write_text('{}')
    manifest = build_manifest('fixture', '1.0.0', [{'kind': 'identity', 'name': 'fixture', 'source': 'identity/fixture'}])
    archive = tmp_path / 'fixture.zip'
    pack_package(manifest, tmp_path, archive, signing_key=b'fake-key')
    assert inspect_package(archive)['signature_status'] == 'present-unverified'
    with pytest.raises(PackageError, match='verification key'):
        inspect_package(archive, require_signature=True)
    assert inspect_package(archive, signing_key=b'fake-key', require_signature=True)['signature_status'] == 'verified'


def test_diagnostics_excludes_prompt_logs_by_default(tmp_path):
    log = tmp_path / '.runtime-logs' / 'app.log'
    log.parent.mkdir()
    log.write_text('private-user-prompt-fixture')
    with patch('product_runtime.product_diagnostics', return_value={'healthy': True}):
        with zipfile.ZipFile(create_diagnostics_bundle(tmp_path)) as archive:
            assert not any(name.startswith('logs/') for name in archive.namelist())
        save_product_settings(tmp_path, {'privacy': {'include_prompts': True}})
        with zipfile.ZipFile(create_diagnostics_bundle(tmp_path)) as archive:
            assert any(name.startswith('logs/') for name in archive.namelist())


def test_product_gates_include_dependencies_not_only_tabs(tmp_path):
    assert disabled_api('/api/task-bench/runs') == 'evaluation'
    assert disabled_api('/api/security/settings') is None
    assert flow_blocker('cookbook_01_react') is None
    assert flow_blocker('code_agent_fast') is None
    assert flow_blocker('any_custom', {'pipeline': {'nodes': {'child': {'harness': 'evolution_cycle'}}}}) == 'evolution'
    flags = json.loads(json.dumps(manifests()))
    flags['evolution']['enabled'] = True
    assert not enabled('evolution', flags)
    flags['evaluation']['enabled'] = True
    assert enabled('evolution', flags)


def test_parallel_inherits_policy_secrets_lineage_and_approval(tmp_path):
    from tests.test_pipeline_runtime import FakeHarness
    from pipeline_engine import PipelineRunner
    graph = {'start': 'fan', 'mode': 'chat', 'nodes': {
        'fan': {'op': '并行', 'branches': [{'name': 'a', 'start': 'leaf'}, {'name': 'b', 'start': 'leaf'}], 'join': 'done', 'edges': []},
        'leaf': {'op': '输出', 'value': 'ok', 'edges': []},
        'done': {'op': '结束', 'edges': []}}}
    approval = lambda *args: False
    runner = PipelineRunner(FakeHarness(tmp_path, graph), get_approval=approval, secret_names=['FIXTURE'])
    original = PipelineRunner._execute_node
    observed = []
    def inspect(child, node_id, node, op):
        if node_id == 'leaf':
            observed.append(child.ctx)
        return original(child, node_id, node, op)
    with patch.object(PipelineRunner, '_execute_node', inspect):
        runner.run()
    assert len(observed) == 2
    for context in observed:
        assert context.permission_policy is runner.ctx.permission_policy
        assert context.secret_view is runner.ctx.secret_view
        assert context.parent is runner.ctx
        assert context.get_approval is approval


def test_timeout_does_not_leave_background_mutation_after_return():
    from pipeline_engine import NodeTimeout, _call_with_timeout
    effects = []
    def slow():
        time.sleep(0.04)
        effects.append('completed')
    with pytest.raises(NodeTimeout):
        _call_with_timeout(slow, .005)
    assert effects == ['completed']  # timeout means drained, not pre-empted
    time.sleep(.05)
    assert effects == ['completed']
