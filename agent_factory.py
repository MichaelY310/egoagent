"""Validated Agent construction shared by IDE, Task Bench and SubDAGs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from agent import Agent
from llm.llm import Identity
from model_gateway import DEFAULT_MODEL_GATEWAY, ModelGateway
from runtime_contracts import RuntimeServices


class AgentFactoryError(ValueError):
    pass


class AgentFactory:
    def __init__(
        self,
        *,
        identity_roots: Iterable[Path | str] = (),
        model_gateway: ModelGateway = DEFAULT_MODEL_GATEWAY,
    ) -> None:
        self.identity_roots = tuple(Path(root).resolve() for root in identity_roots)
        self.model_gateway = model_gateway

    def resolve_identity(self, value: Path | str | Identity) -> Path | Identity:
        if isinstance(value, Identity):
            return value
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            if len(self.identity_roots) != 1:
                raise AgentFactoryError("Relative Identity paths require exactly one configured identity root")
            candidate = self.identity_roots[0] / candidate
        resolved = candidate.resolve()
        if self.identity_roots and not any(
            resolved == root or root in resolved.parents for root in self.identity_roots
        ):
            raise AgentFactoryError(f"Identity path escapes configured repositories: {value}")
        if not (resolved / "id.json").is_file():
            raise AgentFactoryError(f"Identity does not exist or has no id.json: {resolved}")
        return resolved

    def create(
        self,
        identity: Path | str | Identity,
        *,
        name: Optional[str] = None,
        workspace: Optional[Path | str] = None,
        environments: Optional[list[Any]] = None,
        model_provider: Any = None,
        model_config: Optional[Mapping[str, Any]] = None,
        context_instructions: str = "",
    ) -> Agent:
        if model_provider is not None or model_config is not None:
            model_provider = self.model_gateway.resolve(provider=model_provider, config=model_config)
        agent = Agent(
            self.resolve_identity(identity),
            name=name,
            workspace=Path(workspace).resolve() if workspace else None,
            environments=environments,
            model_provider=model_provider,
        )
        agent.context_instructions = str(context_instructions or "")
        agent.runtime_services = RuntimeServices(model=agent.llm, tools=agent.tool_executor)
        return agent

    def create_slots(
        self,
        bindings: Mapping[str, Path | str | Identity],
        **shared: Any,
    ) -> dict[str, Agent]:
        return {
            str(slot): self.create(identity, name=str(slot), **shared)
            for slot, identity in bindings.items()
        }


__all__ = ["AgentFactory", "AgentFactoryError"]
