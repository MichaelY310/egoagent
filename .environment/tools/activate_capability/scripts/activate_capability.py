"""Activate a selected local capability for the current Agent."""

from capability_registry import registry_from_context


def activate_capability(capability_id: str, _context=None):
    context = _context or {}
    agent = context.get("agent")
    if agent is None or not callable(getattr(agent, "activate_capability", None)):
        return {
            "ok": False,
            "error": "Capability activation requires an active EgoAgent runtime.",
        }
    registry = registry_from_context(context)
    result = agent.activate_capability(capability_id, registry=registry)
    if result.get("ok"):
        registry.record_event(capability_id, "activate")
    return result

