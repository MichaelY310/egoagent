import json
from pathlib import Path

import pytest

from agent import Agent
from egoagent_core import tool_library as library

ROOT = Path(__file__).resolve().parents[1]


def make_tool(path, name='sample'):
    (path / 'scripts').mkdir(parents=True)
    (path / 'meta.json').write_text(json.dumps({'name': name, 'description': 'test tool', 'parameters': {'type': 'object'}}))
    # Parsing/listing must not execute module-level code.
    (path / 'scripts' / f'{name}.py').write_text(f"raise RuntimeError('must not import during catalog')\ndef {name}(): return 'ok'\n")
    return path


@pytest.fixture
def project(tmp_path):
    root, workspace = tmp_path / 'project', tmp_path / 'workspace'
    identity = root / 'identity' / 'reader'
    identity.mkdir(parents=True)
    data = {'name': 'reader', 'llm': {'type': 'dummy_llm'}, 'ego_inherits': ['@pack/reading'],
            'custom': {'keep': True}, 'personality': {'language': '中文'}}
    (identity / 'id.json').write_text(json.dumps(data), encoding='utf-8')
    make_tool(root / 'capability_packs' / 'reading' / 'skills' / 'read', 'read_file')
    make_tool(identity / 'ego' / 'skills' / 'local', 'local_tool')
    make_tool(root / '.environment' / 'tools' / 'read', 'read_file')
    make_tool(workspace / '.environment' / 'tools' / 'custom', 'workspace_tool')
    skill = workspace / '.agents' / 'skills' / 'review'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('# Review\nReview carefully; report evidence.')
    return root, workspace, identity, data


def test_catalog_preserves_duplicate_sources_and_lists_instruction_skills(project, monkeypatch):
    monkeypatch.setenv('EGOAGENT_EMBEDDING_PROVIDER', 'disabled')
    root, workspace, _, _ = project
    items = library.catalog(root, workspace, refresh=True)
    reads = [item for item in items if item['name'] == 'read_file']
    assert len(reads) == 2
    assert len({item['ref'] for item in reads}) == 2
    assert all(item['entry_file'].endswith('read_file.py') for item in reads)
    assert any(item['type'] == 'skill' and item['entry_file'].endswith('SKILL.md') for item in items)
    assert all(item['files'] for item in items)


def test_default_composition_matches_environment_override(project):
    root, workspace, _, _ = project
    value = library.identity_selection(root, workspace, 'reader')
    assert value['selection'] is None
    assert set(value['defaults']) == {'repo:identity/reader/ego/skills/local', 'repo:.environment/tools/read', 'workspace:.environment/tools/custom'}


def test_selection_roundtrip_preserves_all_other_identity_fields(project):
    root, workspace, identity, original = project
    state = library.identity_selection(root, workspace, 'reader')
    selection = {'version': 1, 'tools': ['repo:capability_packs/reading/skills/read', 'workspace:.agents/skills/review']}
    saved = library.save_identity_selection(root, workspace, 'reader', selection, state['revision'])
    assert json.loads((identity / 'id.json').read_text(encoding='utf-8')) == {**original, 'capability_selection': selection}
    assert saved['selection'] == selection
    restored = library.save_identity_selection(root, workspace, 'reader', None, saved['revision'])
    assert restored['selection'] is None
    assert json.loads((identity / 'id.json').read_text(encoding='utf-8')) == original


def test_concurrent_edits_are_not_overwritten(project):
    root, workspace, identity, _ = project
    state = library.identity_selection(root, workspace, 'reader')
    (identity / 'id.json').write_text('{"name":"external change"}')
    with pytest.raises(ValueError, match='其他编辑器'):
        library.save_identity_selection(root, workspace, 'reader', {'version': 1, 'tools': []}, state['revision'])
    assert json.loads((identity / 'id.json').read_text())['name'] == 'external change'


@pytest.mark.parametrize('ref', ['repo:../secret', 'workspace:../../x', 'repo:/etc', 'repo:C:/secret', 'repo:identity/reader', 'repo:.env.local', 'arbitrary:foo', 'repo:identity\\reader'])
def test_source_references_reject_unapproved_paths(project, ref):
    root, workspace, _, _ = project
    with pytest.raises(ValueError):
        library.resolve_source(ref, root, workspace)


def test_missing_or_duplicate_sources_cannot_be_saved(project):
    root, workspace, _, _ = project
    revision = library.identity_selection(root, workspace, 'reader')['revision']
    with pytest.raises(ValueError, match='同名'):
        library.save_identity_selection(root, workspace, 'reader', {'version': 1, 'tools': ['repo:.environment/tools/read', 'repo:capability_packs/reading/skills/read']}, revision)
    with pytest.raises(ValueError, match='missing'):
        library.save_identity_selection(root, workspace, 'reader', {'version': 1, 'tools': ['repo:.environment/tools/missing']}, revision)


def test_explicit_empty_list_really_removes_all_startup_tools_and_reload_applies_changes(project):
    root, workspace, identity, data = project
    (identity / 'id.json').write_text(json.dumps({**data, 'ego_inherits': [], 'capability_selection': {'version': 1, 'tools': []}}))
    agent = Agent(identity, workspace=workspace)
    assert agent.tools == {}
    assert agent.get_tools_desc() == []
    state = json.loads((identity / 'id.json').read_text())
    state.pop('capability_selection')
    (identity / 'id.json').write_text(json.dumps(state))
    agent.reload_identity()
    assert 'local_tool' in {agent._short_name(name) for name in agent.tools}


def test_real_runtime_loads_selected_source_and_skill_not_other_defaults(tmp_path):
    identity = tmp_path / 'identity' / 'reader'
    identity.mkdir(parents=True)
    skill = tmp_path / '.agents' / 'skills' / 'review'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('Review this code carefully and give evidence.')
    (identity / 'id.json').write_text(json.dumps({'name': 'selected', 'llm': {'type': 'dummy_llm'},
        'capability_selection': {'version': 1, 'tools': ['repo:capability_packs/filesystem_readonly/skills/read', 'workspace:.agents/skills/review']}}))
    agent = Agent(identity, workspace=tmp_path)
    assert {agent._short_name(key) for key in agent.tools} == {'read_file'}
    assert 'Review this code carefully' in agent.build_system_prompt()
    assert any('filesystem_readonly' in ref.source for ref in agent._activated_capability_refs.values())


def test_api_catalog_and_identity_save_use_same_selection_contract(project, monkeypatch):
    from egoagent_server import api_extensions
    root, workspace, _, _ = project
    monkeypatch.setattr(api_extensions, 'PROJECT_ROOT', root)
    monkeypatch.setenv('EGOAGENT_EMBEDDING_PROVIDER', 'disabled')
    data, code = api_extensions.handle_api_request('POST', '/api/tool-library/list', {'workspace': str(workspace), 'refresh': True})
    assert code == 200 and len(data['items']) >= 5
    state, code = api_extensions.handle_api_request('POST', '/api/tool-library/identity', {'workspace': str(workspace), 'identity': 'reader'})
    result, code = api_extensions.handle_api_request('POST', '/api/tool-library/save', {'workspace': str(workspace), 'identity': 'reader', 'selection': {'version': 1, 'tools': []}, 'revision': state['revision']})
    assert code == 200 and result['selection']['tools'] == []
    result, code = api_extensions.handle_api_request('POST', '/api/tool-library/identity', {'identity': '../reader'})
    assert code == 400
