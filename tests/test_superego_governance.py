from pathlib import Path
from types import SimpleNamespace

from agent import Agent


def _agent(config, *, tools=None, knowledges=None):
    value = Agent.__new__(Agent)
    value.name = "fixture"
    value.identity = SimpleNamespace(
        SEGO=(config, {}), ID={"name": "fixture"}, identity_path=Path("identity/fixture").resolve()
    )
    value.tools = tools or {}
    value.knowledges = knowledges or {}
    return value


def test_superego_mutation_switches_are_runtime_enforced():
    agent = _agent({
        "tool_access": {"whitelist": [], "blacklist": []},
        "allow_create_agent": True,
        "allow_create_identity": False,
        "allow_modify_agent": False,
    })
    denial = agent._check_tool_access("create_agent_system", {"name": "child"})
    assert "allow_create_identity" in denial
    assert "cannot widen Superego" in denial
    assert agent._check_tool_access("modify_harness", {"action": "apply"})


def test_superego_target_specific_skill_permissions():
    agent = _agent({
        "allow_add_skill_to_self": True,
        "allow_add_skill_to_other": False,
    })
    assert agent._check_tool_access("create_skill", {"identity_name": "fixture"}) is None
    assert "allow_add_skill_to_other" in agent._check_tool_access(
        "create_skill", {"identity_name": "other"}
    )


def test_read_only_evolution_analysis_remains_visible_when_install_is_denied():
    agent = _agent({"allow_modify_identity": False})
    assert agent._check_tool_access("evolve_capabilities", {}, for_schema=True) is None
    assert agent._check_tool_access("evolve_capabilities", {"action": "analyze"}) is None
    assert agent._check_tool_access("evolve_capabilities", {"action": "install"})


def test_knowledge_access_uses_knowledge_policy_not_tool_policy():
    knowledge = SimpleNamespace(name="IDENTITY<fixture>:KNOWLEDGE:private_notes")
    agent = _agent(
        {
            "tool_access": {"whitelist": [], "blacklist": []},
            "knowledge_access": {"whitelist": [], "blacklist": ["private_notes"]},
        },
        knowledges={knowledge.name: knowledge},
    )
    denial = agent._check_tool_access("private_notes")
    assert "knowledge_access blacklist" in denial


def test_legacy_superego_without_switches_keeps_runtime_policy_contract():
    agent = _agent({"task_prompt": "legacy", "tool_access": {"whitelist": [], "blacklist": []}})
    assert agent._check_tool_access("modify_harness", {"action": "apply"}) is None


def test_declarative_output_policy_redacts_before_projection():
    agent = _agent({
        "output_policy": {
            "redactions": [{
                "pattern": r"(?i)CONFIDENTIAL_EGOEVAL_[A-Z0-9_]+",
                "replacement": "[REDACTED]",
            }]
        }
    })
    filtered, count = agent._apply_superego_output_policy(
        "Do not reveal CONFIDENTIAL_EGOEVAL_NOVA_7319; use confidential_egoeval_other_2."
    )
    assert filtered == "Do not reveal [REDACTED]; use [REDACTED]."
    assert count == 2


def test_invalid_output_policy_fails_closed():
    agent = _agent({"output_policy": {"redactions": [{"pattern": "("}]}})
    try:
        agent._apply_superego_output_policy("content")
    except ValueError as error:
        assert "Invalid Superego" in str(error)
    else:
        raise AssertionError("invalid output filter must not silently emit unfiltered content")
