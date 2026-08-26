"""Immutable references and snapshots for runtime capabilities.

Catalog IDs intentionally identify a logical capability at a stable path.  A
reproducible trajectory also needs to identify the *contents* that were loaded
from that path.  This module keeps those two concerns separate and provides a
compact snapshot that model-call events can reference without copying every
tool definition into every event.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


REFERENCE_SCHEMA = "ego.capability-ref.v1"
SNAPSHOT_SCHEMA = "ego.capability-snapshot.v1"
_IGNORED_DIRECTORIES = {".git", ".egoagent", "__pycache__", "node_modules", "sessions"}


def _logical_id(kind: str, path: Path) -> str:
    digest = hashlib.sha256(f"{kind}\0{path.resolve()}".encode("utf-8")).hexdigest()[:24]
    return f"{kind}:{digest}"


def digest_capability_source(path: str | Path, *, metadata: Iterable[str] = ()) -> str:
    """Hash a capability source deterministically without importing its code."""

    source = Path(path).resolve()
    digest = hashlib.sha256()
    digest.update(b"ego.capability-source.v1\0")
    for item in metadata:
        digest.update(str(item).encode("utf-8", errors="replace"))
        digest.update(b"\0")

    if source.is_file():
        candidates = [(source.name, source)]
    elif source.is_dir():
        candidates = []
        for candidate in source.rglob("*"):
            try:
                relative = candidate.relative_to(source)
            except ValueError:
                continue
            if any(part in _IGNORED_DIRECTORIES for part in relative.parts):
                continue
            if candidate.is_symlink():
                digest.update(relative.as_posix().encode("utf-8", errors="replace"))
                digest.update(b"\0symlink\0")
                try:
                    digest.update(str(candidate.readlink()).encode("utf-8", errors="replace"))
                except OSError:
                    digest.update(b"unreadable")
                continue
            if candidate.is_file():
                candidates.append((relative.as_posix(), candidate))
        candidates.sort(key=lambda item: item[0].casefold())
    else:
        candidates = []
        digest.update(b"missing\0")

    for relative, candidate in candidates:
        digest.update(relative.encode("utf-8", errors="replace"))
        digest.update(b"\0")
        try:
            with candidate.open("rb") as stream:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
        except OSError as error:
            digest.update(f"unreadable:{type(error).__name__}".encode("ascii", errors="replace"))
        digest.update(b"\0")
    return digest.hexdigest()


@dataclass(frozen=True)
class CapabilityRef:
    id: str
    kind: str
    name: str
    version: str
    digest: str
    scope: str = "runtime"
    source: str = ""

    @property
    def revision(self) -> str:
        return f"{self.id}@{self.digest[:16]}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": REFERENCE_SCHEMA,
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "version": self.version,
            "digest": self.digest,
            "revision": self.revision,
            "scope": self.scope,
            "source": self.source,
        }

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "CapabilityRef":
        path = Path(str(item.get("path") or item.get("source") or ""))
        kind = str(item.get("kind") or "capability")
        content_digest = str(item.get("content_hash") or item.get("digest") or "")
        if not content_digest:
            content_digest = digest_capability_source(path)
        return cls(
            id=str(item.get("id") or _logical_id(kind, path)),
            kind=kind,
            name=str(item.get("name") or path.name),
            version=str(item.get("version") or "local"),
            digest=content_digest,
            scope=str(item.get("scope") or "runtime"),
            source=str(path.resolve()) if str(path) else "",
        )


def source_reference(
    *,
    kind: str,
    name: str,
    path: str | Path,
    version: str = "local",
    scope: str = "runtime",
) -> CapabilityRef:
    source = Path(path).resolve()
    return CapabilityRef(
        id=_logical_id(kind, source),
        kind=str(kind),
        name=str(name or source.name),
        version=str(version or "local"),
        digest=digest_capability_source(source),
        scope=str(scope or "runtime"),
        source=str(source),
    )


def build_capability_snapshot(
    *,
    agent: str,
    identity: CapabilityRef,
    capabilities: Iterable[CapabilityRef | Mapping[str, Any]],
) -> dict[str, Any]:
    refs: dict[str, CapabilityRef] = {}
    for value in capabilities:
        ref = value if isinstance(value, CapabilityRef) else CapabilityRef.from_mapping(value)
        refs[ref.revision] = ref
    ordered = [refs[key].as_dict() for key in sorted(refs)]
    payload = {
        "schema": SNAPSHOT_SCHEMA,
        "agent": str(agent),
        "identity": identity.as_dict(),
        "capabilities": ordered,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    snapshot_id = f"caps_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
    return {"snapshot_id": snapshot_id, **payload}


__all__ = [
    "CapabilityRef",
    "REFERENCE_SCHEMA",
    "SNAPSHOT_SCHEMA",
    "build_capability_snapshot",
    "digest_capability_source",
    "source_reference",
]
