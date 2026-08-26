"""Single construction boundary for all model-provider implementations."""

from __future__ import annotations

import copy
from typing import Any, Callable, Mapping, Optional

from llm.providers import create_provider
from runtime_contracts import ModelProvider, capability_descriptor, missing_model_provider_members


class ModelGatewayError(ValueError):
    pass


class ModelGateway:
    """Create and validate providers without leaking vendor logic to Agents.

    The returned object is the native provider adapter, so existing code can
    still tune fields such as ``max_tokens``.  The boundary is construction and
    conformance, not an extra proxy layer around every streamed token.
    """

    def __init__(self, provider_factory: Callable[[dict[str, Any]], ModelProvider] = create_provider):
        self._provider_factory = provider_factory

    @staticmethod
    def validate(provider: Any) -> ModelProvider:
        missing = missing_model_provider_members(provider)
        if missing:
            raise ModelGatewayError(
                f"Model provider {type(provider).__name__} does not satisfy ModelProvider: "
                f"missing {', '.join(missing)}"
            )
        return provider

    def create(self, config: Mapping[str, Any]) -> ModelProvider:
        if not isinstance(config, Mapping):
            raise ModelGatewayError("Model configuration must be an object")
        provider = self._provider_factory(copy.deepcopy(dict(config)))
        return self.validate(provider)

    def resolve(
        self,
        *,
        provider: Optional[ModelProvider] = None,
        config: Optional[Mapping[str, Any]] = None,
    ) -> ModelProvider:
        if provider is not None and config is not None:
            raise ModelGatewayError("Pass either a provider instance or provider config, not both")
        if provider is not None:
            return self.validate(provider)
        if config is None:
            raise ModelGatewayError("A provider instance or provider config is required")
        return self.create(config)

    def describe(self, provider: Any) -> dict[str, Any]:
        return capability_descriptor(provider)


DEFAULT_MODEL_GATEWAY = ModelGateway()


__all__ = ["DEFAULT_MODEL_GATEWAY", "ModelGateway", "ModelGatewayError"]
