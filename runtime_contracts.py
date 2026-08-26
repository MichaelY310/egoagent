"""Stable runtime capability contracts.

EgoAgent intentionally keeps DAG components as its composition language.  The
contracts in this module separate those components from concrete model,
process, storage, tool and child-Agent implementations without introducing a
plugin framework or forcing every implementation into a package.

The protocols are structural: existing adapters conform without inheritance,
which keeps third-party integrations small and testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional, Protocol, runtime_checkable


@runtime_checkable
class ModelProvider(Protocol):
    model: str
    last_response_metadata: Mapping[str, Any]

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **parameters: Any,
    ) -> dict[str, Any]: ...

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **parameters: Any,
    ) -> Iterator[dict[str, Any]]: ...


@runtime_checkable
class TrajectorySink(Protocol):
    trace_id: str

    def append(self, event_type: str, data: Any = None, **metadata: Any) -> Optional[dict[str, Any]]: ...


@runtime_checkable
class SessionStore(Protocol):
    def save(self, session: Any) -> None: ...
    def load(self, location: Path | str) -> Any: ...


@dataclass(frozen=True)
class ToolExecutionRequest:
    name: str
    arguments: Mapping[str, Any]
    call_id: str
    agent: str
    workspace: Optional[Path] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolExecutionResult:
    status: str
    raw_result: Any
    model_observation: Any
    side_effects: tuple[Mapping[str, Any], ...] = ()
    error: Optional[str] = None


@runtime_checkable
class ToolExecutor(Protocol):
    def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult: ...


@dataclass(frozen=True)
class ProcessRequest:
    argv: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str] = field(default_factory=dict)
    stdin: Optional[bytes] = None
    timeout_seconds: float = 120.0


@dataclass(frozen=True)
class ProcessResult:
    returncode: Optional[int]
    stdout: str
    stderr: str
    status: str
    duration_ms: float
    backend: str


@runtime_checkable
class ProcessProvider(Protocol):
    name: str
    def execute(self, request: ProcessRequest, *, cancelled: Any = None) -> ProcessResult: ...


@dataclass(frozen=True)
class SubagentInvocation:
    invocation_id: str
    harness: str
    parent_harness: Optional[str]
    workspace: Optional[Path]
    share_session: bool = False
    agent_bindings: Mapping[str, str] = field(default_factory=dict)
    identity_bindings: Mapping[str, str] = field(default_factory=dict)
    purpose: str = "subdag"


@dataclass(frozen=True)
class SubagentResult:
    invocation_id: str
    status: str
    result: Any = None
    child_session_id: Optional[str] = None
    error: Optional[str] = None


@runtime_checkable
class SubagentRuntime(Protocol):
    def invoke(self, invocation: SubagentInvocation) -> SubagentResult: ...


@dataclass
class RuntimeServices:
    """Explicit service bag for embedding/testing; fields are all optional.

    The default product continues to construct its local adapters lazily.  An
    embedding host can replace one service without changing a DAG or Identity.
    """

    model: Optional[ModelProvider] = None
    tools: Optional[ToolExecutor] = None
    processes: Optional[ProcessProvider] = None
    sessions: Optional[SessionStore] = None
    subagents: Optional[SubagentRuntime] = None
    trajectory: Optional[TrajectorySink] = None


def missing_model_provider_members(provider: Any) -> list[str]:
    """Human-readable conformance diagnostics for Settings/tests."""

    return [name for name in ("chat", "chat_stream") if not callable(getattr(provider, name, None))]


def capability_descriptor(provider: Any, *, name: Optional[str] = None) -> dict[str, Any]:
    """Return a serializable contract view without exposing provider secrets."""

    members = missing_model_provider_members(provider)
    return {
        "name": str(name or type(provider).__name__),
        "contract": "ModelProvider",
        "conforms": not members,
        "missing": members,
        "model": str(getattr(provider, "model", "")),
        "streaming": callable(getattr(provider, "chat_stream", None)),
        "provider_metadata": hasattr(provider, "last_response_metadata"),
    }
