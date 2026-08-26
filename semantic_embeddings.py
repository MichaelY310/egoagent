"""Small, optional embedding backends used by EgoAgent search.

The search index must remain useful without a network connection or a GPU.
This module therefore exposes one narrow interface with two interchangeable
implementations:

* an OpenAI-compatible ``/embeddings`` endpoint; and
* FastEmbed's local ONNX runtime.

Callers cache returned vectors and always retain a lexical fallback.  Secrets
are read from environment variables only and are never included in status
payloads or persisted beside vectors.
"""

from __future__ import annotations

import math
import os
import threading
import warnings
from pathlib import Path
from typing import Any, Iterable, Protocol


DEFAULT_LOCAL_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def normalize_vector(values: Iterable[Any]) -> list[float]:
    vector = [float(value) for value in values]
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


class EmbeddingBackend(Protocol):
    provider_name: str
    model_id: str
    remote: bool

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...

    def status(self) -> dict[str, Any]: ...


class OpenAICompatibleEmbeddings:
    provider_name = "openai-compatible"
    remote = True

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float = 60):
        self.base_url = str(base_url).rstrip("/")
        self.api_key = str(api_key)
        self.model_id = str(model)
        self.timeout = max(1.0, float(timeout))

    def _embed(self, texts: list[str]) -> list[list[float]]:
        import requests

        response = requests.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model_id, "input": texts, "encoding_format": "float"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        rows = sorted(payload.get("data") or [], key=lambda item: int(item.get("index", 0)))
        if len(rows) != len(texts):
            raise RuntimeError(f"embedding endpoint returned {len(rows)} vectors for {len(texts)} inputs")
        return [normalize_vector(item.get("embedding") or []) for item in rows]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def status(self) -> dict[str, Any]:
        return {
            "available": True,
            "provider": self.provider_name,
            "model": self.model_id,
            "remote": True,
        }


_FASTEMBED_MODELS: dict[tuple[str, str], Any] = {}
_FASTEMBED_LOCK = threading.RLock()


class FastEmbedEmbeddings:
    provider_name = "fastembed"
    remote = False

    def __init__(self, *, model: str = DEFAULT_LOCAL_MODEL, cache_dir: str | Path | None = None):
        self.model_id = str(model)
        self.cache_dir = str(Path(cache_dir).resolve()) if cache_dir else None

    def _model(self):
        key = (self.model_id, self.cache_dir or "")
        with _FASTEMBED_LOCK:
            model = _FASTEMBED_MODELS.get(key)
            if model is None:
                from fastembed import TextEmbedding

                kwargs = {"model_name": self.model_id}
                if self.cache_dir:
                    Path(self.cache_dir).mkdir(parents=True, exist_ok=True)
                    kwargs["cache_dir"] = self.cache_dir
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message=r"The model .* now uses mean pooling instead of CLS embedding.*",
                        category=UserWarning,
                    )
                    model = TextEmbedding(**kwargs)
                _FASTEMBED_MODELS[key] = model
            return model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [normalize_vector(vector) for vector in self._model().embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        # The default multilingual paraphrase model is symmetric.  Custom E5
        # models can opt into their conventional query prefix by name.
        query = f"query: {text}" if "e5" in self.model_id.casefold() else text
        return [normalize_vector(vector) for vector in self._model().embed([query])][0]

    def status(self) -> dict[str, Any]:
        return {
            "available": True,
            "provider": self.provider_name,
            "model": self.model_id,
            "remote": False,
            "cache_dir": self.cache_dir,
        }


def create_embedding_backend(project_root: str | Path) -> tuple[EmbeddingBackend | None, dict[str, Any]]:
    """Resolve a backend without ever failing the lexical search path."""

    mode = os.environ.get("EGOAGENT_EMBEDDING_PROVIDER", "auto").strip().casefold()
    if mode in {"0", "off", "false", "none", "disabled", "lexical"}:
        return None, {"available": False, "provider": "disabled", "fallback_reason": "disabled_by_configuration"}

    api_key = os.environ.get("EGOAGENT_EMBEDDING_API_KEY", "").strip()
    base_url = os.environ.get("EGOAGENT_EMBEDDING_BASE_URL", "").strip()
    model = os.environ.get("EGOAGENT_EMBEDDING_MODEL", "").strip()
    if mode in {"auto", "api", "remote", "openai-compatible"} and api_key and base_url and model:
        backend = OpenAICompatibleEmbeddings(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=float(os.environ.get("EGOAGENT_EMBEDDING_TIMEOUT", "60")),
        )
        return backend, backend.status()

    if mode in {"auto", "fastembed", "local"}:
        try:
            import fastembed  # noqa: F401

            local_model = model or os.environ.get("EGOAGENT_LOCAL_EMBEDDING_MODEL", DEFAULT_LOCAL_MODEL)
            cache_dir = Path(project_root).resolve() / ".egoagent" / "embedding-models"
            backend = FastEmbedEmbeddings(model=local_model, cache_dir=cache_dir)
            return backend, backend.status()
        except (ImportError, OSError, ValueError) as error:
            return None, {
                "available": False,
                "provider": "fastembed",
                "model": model or DEFAULT_LOCAL_MODEL,
                "fallback_reason": f"local_backend_unavailable: {error}",
            }

    missing = []
    if not api_key:
        missing.append("EGOAGENT_EMBEDDING_API_KEY")
    if not base_url:
        missing.append("EGOAGENT_EMBEDDING_BASE_URL")
    if not model:
        missing.append("EGOAGENT_EMBEDDING_MODEL")
    return None, {
        "available": False,
        "provider": mode or "auto",
        "fallback_reason": "missing " + ", ".join(missing) if missing else "unsupported_provider",
    }
