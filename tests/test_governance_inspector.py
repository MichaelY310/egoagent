import json
from pathlib import Path

from governance import inspect_governance


def _write(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_governance_inspector_explains_intersection_and_conflicts(tmp_path):
    _write(tmp_path / "harness" / "demo" / "config.json", {
        "name": "demo",
        "pipeline": {
            "permissions": {"defaults": {"mutation": "allow", "network": "deny"}},
            "nodes": {
                "model": {"op": "模型", "system_prompt": "Flow-specific instructions"},
                "review": {"op": "工具审查"},
            },
        },
    })
    _write(tmp_path / "identity" / "fixture" / "id.json", {
        "name": "fixture", "role": "tester", "personality": {},
    })
    _write(tmp_path / "identity" / "fixture" / "superego" / "config.json", {
        "task_prompt": "Identity-level rules",
        "tool_access": {"whitelist": ["read_file"], "blacklist": ["read_file"]},
        "allow_create_agent": False,
        "allow_modify_agent": False,
    })
    (tmp_path / "identity" / "fixture" / "superego" / "pre_llm_hook.py").write_text(
        "def pre_llm_hook(**kwargs): pass\n", encoding="utf-8"
    )

    report = inspect_governance(tmp_path, "demo", "fixture", "evolve")

    assert report["schema"] == "ego.governance-inspection.v1"
    assert report["superego_layer"]["mutation_contract"] == "explicit"
    assert report["flow_layer"]["approval_nodes"] == ["review"]
    codes = {item["code"] for item in report["conflicts"]}
    assert "superego.tool_list_overlap" in codes
    assert "superego.imperative_hooks" in codes
    assert "instructions.multiple_authorities" in codes
    create_flow = next(item for item in report["matrix"] if item["capability"] == "create Flow")
    assert create_flow["runtime"] in {"allow", "ask"}
    assert create_flow["superego"] == "deny"
    assert create_flow["effective"] == "deny"
    read = next(item for item in report["matrix"] if item["capability"] == "read")
    assert read["superego"] == "deny"
    assert "blacklist" in read["superego_reason"]
    assert "visible approval nodes are workflow checkpoints" in report["effective_rule"]


def test_governance_inspector_marks_legacy_superego(tmp_path):
    _write(tmp_path / "harness" / "demo" / "config.json", {"name": "demo", "pipeline": {"nodes": {}}})
    _write(tmp_path / "identity" / "fixture" / "id.json", {"name": "fixture", "role": "tester"})
    _write(tmp_path / "identity" / "fixture" / "superego" / "config.json", {"task_prompt": "legacy"})
    report = inspect_governance(tmp_path, "demo", "fixture", "agent")
    assert report["superego_layer"]["mutation_contract"] == "legacy"
    assert any(item["code"] == "superego.legacy_mutation_contract" for item in report["conflicts"])


def test_non_empty_superego_whitelist_is_reflected_in_effective_matrix(tmp_path):
    _write(tmp_path / "harness" / "demo" / "config.json", {"name": "demo", "pipeline": {"nodes": {}}})
    _write(tmp_path / "identity" / "fixture" / "id.json", {"name": "fixture", "role": "tester"})
    _write(tmp_path / "identity" / "fixture" / "superego" / "config.json", {
        "tool_access": {"whitelist": ["read_file"], "blacklist": []},
        "allow_create_agent": True,
    })
    report = inspect_governance(tmp_path, "demo", "fixture", "evolve")
    read = next(item for item in report["matrix"] if item["capability"] == "read")
    process = next(item for item in report["matrix"] if item["capability"] == "process")
    assert read["superego"] == "allow"
    assert process["superego"] == "deny"
    assert process["effective"] == "deny"


def test_knowledge_access_is_visible_and_fail_closed(tmp_path):
    _write(tmp_path / "harness" / "demo" / "config.json", {"name": "demo", "pipeline": {"nodes": {}}})
    _write(tmp_path / "identity" / "fixture" / "id.json", {"name": "fixture", "role": "tester"})
    _write(tmp_path / "identity" / "fixture" / "superego" / "config.json", {
        "knowledge_access": {"whitelist": ["other"], "blacklist": ["guide", "other"]},
    })
    (tmp_path / "identity" / "fixture" / "ego" / "knowledge" / "guide").mkdir(parents=True)

    report = inspect_governance(tmp_path, "demo", "fixture", "agent")

    knowledge = next(item for item in report["matrix"] if item["capability"] == "read Knowledge")
    assert knowledge["tool"] == "knowledge:guide"
    assert knowledge["superego"] == "deny"
    assert knowledge["effective"] == "deny"
    assert "knowledge_access blacklist" in knowledge["superego_reason"]
    assert any(item["code"] == "superego.knowledge_list_overlap" for item in report["conflicts"])
