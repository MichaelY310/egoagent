"""Headless EgoAgent SDK. Importing this package never starts a server or UI.

The historical root modules remain public for existing Flow scripts. New code
can import the same runtime objects here; there is only one implementation.
"""
from importlib import import_module

_EXPORTS = {
    "Agent": ("agent", "Agent"),
    "AgentFactory": ("agent_factory", "AgentFactory"),
    "Harness": ("harness", "Harness"),
    "Session": ("harness", "Session"),
    "PipelineRunner": ("pipeline_engine", "PipelineRunner"),
    "CapabilityRegistry": ("capability_registry", "CapabilityRegistry"),
    "TrajectoryReader": ("trajectory", "TrajectoryReader"),
    "TaskBenchManager": ("task_bench", "TaskBenchManager"),
    "SessionBranchService": ("session_branching", "SessionBranchService"),
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, member = _EXPORTS[name]
    value = getattr(import_module(module), member)
    globals()[name] = value
    return value
