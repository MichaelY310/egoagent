"""Local, workspace-aware capability discovery for EgoAgent.

The registry intentionally uses SQLite instead of requiring a long-running
search service.  Capability metadata is small, changes far less often than
source code, and benefits from transactional usage counters.  SQLite FTS5 is
used when available; the deterministic Python scorer remains the fallback and
also handles CJK substring matching better than the default FTS tokenizer.

Only compact metadata is returned by :meth:`CapabilityRegistry.search`.
Executable code and knowledge content are loaded on explicit activation, which
implements progressive disclosure and keeps unused tool schemas out of model
context.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from capability_reference import CapabilityRef, digest_capability_source


SCHEMA_VERSION = 2
_AUTO_EMBEDDINGS = object()
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_WORD_RE = re.compile(r"[a-zA-Z0-9_.+#-]+")
_LOCAL_SKILL_DIRS = (Path(".agents/skills"), Path(".codex/skills"))
_QUERY_STOPWORDS = {
    "a", "an", "and", "for", "in", "new", "of", "please", "the", "to", "use", "with",
    "can", "could", "help", "me", "need", "want",
}


def _now() -> float:
    return time.time()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def _read_text(path: Path, limit: int = 16_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _description(meta: dict[str, Any]) -> str:
    function = meta.get("function") if isinstance(meta.get("function"), dict) else {}
    return str(meta.get("description") or function.get("description") or "").strip()


def _name(meta: dict[str, Any], fallback: str) -> str:
    function = meta.get("function") if isinstance(meta.get("function"), dict) else {}
    return str(meta.get("name") or function.get("name") or fallback).strip()


def _tags(meta: dict[str, Any]) -> list[str]:
    raw = meta.get("tags", [])
    if isinstance(raw, str):
        raw = re.split(r"[,;\s]+", raw)
    if not isinstance(raw, list):
        return []
    return sorted({str(item).strip() for item in raw if str(item).strip()})


def _content_hash(parts: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8", errors="replace"))
        digest.update(b"\0")
    return digest.hexdigest()


def _reuse_contract(item: dict[str, Any]) -> dict[str, Any] | None:
    """Return a compact, machine-readable way to reuse a structural result.

    Search intentionally omits executable bodies, but a name alone was not
    enough for a small model to reuse an Identity or Harness safely.  This
    contract exposes only bindings and typed component ports; it never loads a
    prompt, script, or knowledge body into the caller's context.
    """
    kind = str(item.get("kind") or "")
    path = Path(str(item.get("path") or ""))
    if kind == "identity":
        return {
            "modes": ["harness_slot"],
            "identity": path.name,
            "binding": f"<slot>:identity/{path.name}",
        }
    if kind != "harness":
        return None

    config = _read_json(path / "config.json")
    slots = config.get("slots") if isinstance(config.get("slots"), dict) else {}
    component = config.get("component") if isinstance(config.get("component"), dict) else None
    slot_contract = {
        str(name): {
            "required": spec.get("required", True),
            "default_identity": spec.get("identity"),
            "description": str(spec.get("description") or ""),
        }
        for name, spec in slots.items()
        if isinstance(spec, dict)
    }
    default_bindings = ",".join(
        f"{name}:identity/{spec.get('identity')}"
        for name, spec in slots.items()
        if isinstance(spec, dict) and spec.get("identity")
    )
    contract: dict[str, Any] = {
        "modes": ["subagent_session", "subflow_node"],
        "harness": path.name,
        "slots": slot_contract,
        "invoke": {
            "tool": "create_harness",
            "arguments": {
                "harness_dir": f"harness/{path.name}",
                "agents": default_bindings or "<slot>:identity/<identity>",
                "return_mode": str(config.get("return_mode") or "last"),
            },
        },
        "subflow": {
            "op": "子流程",
            "harness": path.name,
            "agent_map": {name: name for name in slots},
        },
    }
    if component:
        contract["modes"].insert(0, "typed_subdag")
        contract["subflow"].update({
            "share_session": bool(component.get("share_session")),
            "inputs": component.get("inputs") if isinstance(component.get("inputs"), dict) else {},
            "outputs": component.get("outputs") if isinstance(component.get("outputs"), dict) else {},
        })
    return contract


def _query_terms(value: str) -> list[str]:
    normalized = value.casefold().strip()
    terms = _WORD_RE.findall(normalized)
    for block in _CJK_RE.findall(normalized):
        # Whole phrases preserve precise matching; overlapping bigrams make
        # short Chinese discovery queries useful without a custom tokenizer.
        terms.append(block)
        if len(block) > 2:
            terms.extend(block[index:index + 2] for index in range(len(block) - 1))
    return list(dict.fromkeys(term for term in terms if term and term not in _QUERY_STOPWORDS))


@dataclass(frozen=True)
class Capability:
    id: str
    kind: str
    name: str
    display_name: str
    description: str
    tags: tuple[str, ...]
    scope: str
    workspace_root: str
    path: str
    owner: str
    version: str
    content_hash: str
    search_text: str

    def row(self) -> tuple[Any, ...]:
        return (
            self.id,
            self.kind,
            self.name,
            self.display_name,
            self.description,
            json.dumps(list(self.tags), ensure_ascii=False),
            self.scope,
            self.workspace_root,
            self.path,
            self.owner,
            self.version,
            self.content_hash,
            self.search_text,
        )


class CapabilityRegistry:
    """Transactional local catalog with deterministic workspace-first search."""

    def __init__(
        self,
        project_root: str | Path,
        workspace: str | Path | None = None,
        *,
        embedding_backend: Any = _AUTO_EMBEDDINGS,
    ):
        self.project_root = Path(project_root).resolve()
        self.workspace = Path(workspace).resolve() if workspace else self.project_root
        state_dir = self.project_root / ".egoagent"
        state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = state_dir / "capabilities.sqlite3"
        self._lock = threading.RLock()
        self._fts_available = True
        self._embedding_backend_spec = embedding_backend
        self._embedding_backend = None
        self._embedding_status: dict[str, Any] = {}
        self._embedding_resolved = False
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS catalog_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS capabilities (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    workspace_root TEXT NOT NULL,
                    path TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    version TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    discovered_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS capabilities_kind ON capabilities(kind);
                CREATE INDEX IF NOT EXISTS capabilities_path ON capabilities(path);
                CREATE INDEX IF NOT EXISTS capabilities_workspace ON capabilities(workspace_root, scope);
                CREATE TABLE IF NOT EXISTS capability_metrics (
                    capability_id TEXT PRIMARY KEY REFERENCES capabilities(id) ON DELETE CASCADE,
                    impressions INTEGER NOT NULL DEFAULT 0,
                    activations INTEGER NOT NULL DEFAULT 0,
                    successes INTEGER NOT NULL DEFAULT 0,
                    failures INTEGER NOT NULL DEFAULT 0,
                    total_runtime_ms REAL NOT NULL DEFAULT 0,
                    last_seen REAL,
                    last_used REAL,
                    last_success REAL
                );
                CREATE TABLE IF NOT EXISTS capability_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capability_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    success INTEGER,
                    runtime_ms REAL,
                    workspace_root TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS capability_events_created ON capability_events(created_at);
                CREATE TABLE IF NOT EXISTS search_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    workspace_root TEXT NOT NULL,
                    result_count INTEGER NOT NULL,
                    creation_recommended INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS capability_embeddings (
                    capability_id TEXT NOT NULL REFERENCES capabilities(id) ON DELETE CASCADE,
                    model TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    vector TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(capability_id, model)
                );
                CREATE INDEX IF NOT EXISTS capability_embeddings_model
                    ON capability_embeddings(model, content_hash);
                """
            )
            try:
                connection.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS capabilities_fts "
                    "USING fts5(id UNINDEXED, name, display_name, description, tags, owner, search_text, tokenize='unicode61')"
                )
            except sqlite3.OperationalError:
                self._fts_available = False
            connection.execute(
                "INSERT OR REPLACE INTO catalog_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _capability(
        *,
        kind: str,
        name: str,
        description: str,
        tags: Iterable[str],
        scope: str,
        workspace_root: Path | None,
        path: Path,
        owner: str = "",
        version: str = "local",
        extra_text: str = "",
    ) -> Capability:
        resolved = path.resolve()
        clean_tags = tuple(sorted({str(tag).strip() for tag in tags if str(tag).strip()}))
        display_name = name.replace("_", " ").strip().title() or resolved.name
        search_text = " ".join(
            item for item in (name, display_name, description, " ".join(clean_tags), owner, extra_text) if item
        )[:32_000]
        identifier = hashlib.sha256(f"{kind}\0{resolved}".encode("utf-8")).hexdigest()[:24]
        return Capability(
            id=f"{kind}:{identifier}",
            kind=kind,
            name=name,
            display_name=display_name,
            description=description,
            tags=clean_tags,
            scope=scope,
            workspace_root=str(workspace_root or ""),
            path=str(resolved),
            owner=owner,
            version=version,
            # The logical ID remains stable for usage metrics while this digest
            # changes whenever executable instructions or knowledge at the
            # source path changes. This is what makes old runs reproducible.
            content_hash=digest_capability_source(
                resolved,
                metadata=(kind, name, description, json.dumps(clean_tags), search_text),
            ),
            search_text=search_text,
        )

    def _scan_skill_root(
        self,
        root: Path,
        *,
        kind: str,
        scope: str,
        workspace_root: Path | None,
        owner: str = "",
    ) -> Iterator[Capability]:
        if not root.is_dir():
            return
        for directory in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
            if not directory.is_dir():
                continue
            meta_path = directory / "meta.json"
            if not meta_path.is_file():
                meta_path = directory / "description.json"
            meta = _read_json(meta_path) if meta_path.is_file() else {}
            skill_doc = _read_text(directory / "SKILL.md", 8_000)
            scripts = " ".join(path.stem for path in sorted((directory / "scripts").glob("*.py")))
            name = _name(meta, directory.name)
            description = _description(meta)
            if not description and skill_doc:
                description = next((line.lstrip("# ").strip() for line in skill_doc.splitlines() if line.strip()), "")
            if not meta and not skill_doc and not scripts:
                continue
            yield self._capability(
                kind=kind,
                name=name,
                description=description,
                tags=_tags(meta),
                scope=scope,
                workspace_root=workspace_root,
                path=directory,
                owner=str(meta.get("author") or owner),
                version=str(meta.get("version") or meta.get("updated_at") or "local"),
                extra_text=f"{scripts} {skill_doc[:2000]}",
            )

    def _scan_knowledge_root(
        self,
        root: Path,
        *,
        scope: str,
        workspace_root: Path | None,
        owner: str = "",
    ) -> Iterator[Capability]:
        if not root.is_dir():
            return
        for item in sorted(root.iterdir(), key=lambda value: value.name.casefold()):
            directory = item if item.is_dir() else item.parent
            if item.is_dir():
                meta = _read_json(item / "meta.json")
                content_files = [path for path in sorted(item.iterdir()) if path.suffix.lower() in {".txt", ".md"}]
                if not meta and not content_files:
                    continue
                name = _name(meta, item.name)
                text = "\n".join(_read_text(path, 4_000) for path in content_files[:3])
                path = item
            elif item.suffix.lower() in {".txt", ".md"}:
                meta = {}
                name = item.stem
                text = _read_text(item, 8_000)
                path = item
            else:
                continue
            description = _description(meta)
            if not description:
                description = next((line.lstrip("# ").strip() for line in text.splitlines() if line.strip()), "")[:500]
            yield self._capability(
                kind="knowledge",
                name=name,
                description=description,
                tags=_tags(meta),
                scope=scope,
                workspace_root=workspace_root,
                path=path,
                owner=str(meta.get("author") or owner),
                version=str(meta.get("version") or meta.get("updated_at") or "local"),
                extra_text=text[:8_000],
            )

    def discover(self) -> list[Capability]:
        discovered: list[Capability] = []
        identity_root = self.project_root / "identity"
        if identity_root.is_dir():
            for identity_dir in sorted(identity_root.iterdir(), key=lambda item: item.name.casefold()):
                if not identity_dir.is_dir() or not (identity_dir / "id.json").is_file():
                    continue
                meta = _read_json(identity_dir / "id.json")
                discovered.append(
                    self._capability(
                        kind="identity",
                        name=_name(meta, identity_dir.name),
                        description=_description(meta),
                        tags=_tags(meta) + [str(meta.get("role", ""))],
                        scope="project",
                        workspace_root=None,
                        path=identity_dir,
                        owner=str(meta.get("author", "")),
                        version=str(meta.get("version", "local")),
                        extra_text=json.dumps(meta.get("personality", {}), ensure_ascii=False),
                    )
                )
                discovered.extend(
                    self._scan_skill_root(
                        identity_dir / "ego" / "skills",
                        kind="skill",
                        scope="identity",
                        workspace_root=None,
                        owner=identity_dir.name,
                    )
                )
                discovered.extend(
                    self._scan_knowledge_root(
                        identity_dir / "ego" / "knowledge",
                        scope="identity",
                        workspace_root=None,
                        owner=identity_dir.name,
                    )
                )

        harness_root = self.project_root / "harness"
        if harness_root.is_dir():
            for harness_dir in sorted(harness_root.iterdir(), key=lambda item: item.name.casefold()):
                config_path = harness_dir / "config.json"
                if not config_path.is_file():
                    continue
                config = _read_json(config_path)
                pipeline = config.get("pipeline") if isinstance(config.get("pipeline"), dict) else {}
                nodes = pipeline.get("nodes") if isinstance(pipeline.get("nodes"), dict) else {}
                discovered.append(
                    self._capability(
                        kind="harness",
                        name=_name(config, harness_dir.name),
                        description=_description(config),
                        tags=list(config.get("tags", [])) if isinstance(config.get("tags"), list) else [],
                        scope="project",
                        workspace_root=None,
                        path=harness_dir,
                        owner=str(config.get("author", "")),
                        version=str(config.get("version", "local")),
                        extra_text=" ".join(
                            [str(key) for key in nodes]
                            + [str(key) for key in (config.get("slots") or {})]
                        ),
                    )
                )

        capability_pack_root = self.project_root / "capability_packs"
        if capability_pack_root.is_dir():
            for pack_dir in sorted(capability_pack_root.iterdir(), key=lambda item: item.name.casefold()):
                if not pack_dir.is_dir():
                    continue
                discovered.extend(
                    self._scan_skill_root(
                        pack_dir / "skills",
                        kind="skill",
                        scope="project",
                        workspace_root=None,
                        owner=f"pack:{pack_dir.name}",
                    )
                )
                discovered.extend(
                    self._scan_knowledge_root(
                        pack_dir / "knowledge",
                        scope="project",
                        workspace_root=None,
                        owner=f"pack:{pack_dir.name}",
                    )
                )

        # Repository environment and named environments are reusable project
        # capabilities.  Workspace-local capabilities receive a strong search
        # boost and remain isolated by workspace_root.
        environment_roots = [self.project_root / ".environment", self.project_root / "environment"]
        for root in environment_roots:
            candidates = [root] if (root / "tools").is_dir() else ([item for item in root.iterdir() if item.is_dir()] if root.is_dir() else [])
            for environment_dir in candidates:
                discovered.extend(
                    self._scan_skill_root(
                        environment_dir / "tools",
                        kind="tool",
                        scope="project",
                        workspace_root=None,
                        owner=environment_dir.name,
                    )
                )
                discovered.extend(
                    self._scan_knowledge_root(
                        environment_dir / "knowledge",
                        scope="project",
                        workspace_root=None,
                        owner=environment_dir.name,
                    )
                )

        if self.workspace != self.project_root:
            local_environment = self.workspace / ".environment"
            discovered.extend(
                self._scan_skill_root(
                    local_environment / "tools",
                    kind="tool",
                    scope="workspace",
                    workspace_root=self.workspace,
                    owner=self.workspace.name,
                )
            )
            discovered.extend(
                self._scan_knowledge_root(
                    local_environment / "knowledge",
                    scope="workspace",
                    workspace_root=self.workspace,
                    owner=self.workspace.name,
                )
            )
            for relative in _LOCAL_SKILL_DIRS:
                discovered.extend(
                    self._scan_skill_root(
                        self.workspace / relative,
                        kind="skill",
                        scope="workspace",
                        workspace_root=self.workspace,
                        owner=self.workspace.name,
                    )
                )

        # A canonical path can be reached through compatibility roots.  Keep
        # the more local occurrence without duplicating cards.
        by_id: dict[str, Capability] = {}
        for capability in discovered:
            previous = by_id.get(capability.id)
            if previous is None or capability.scope == "workspace":
                by_id[capability.id] = capability
        return list(by_id.values())

    def reindex(self) -> dict[str, Any]:
        capabilities = self.discover()
        now = _now()
        workspace_value = str(self.workspace)
        with self._lock, self._connection() as connection:
            existing = {
                row["id"]: row["content_hash"]
                for row in connection.execute("SELECT id, content_hash FROM capabilities")
            }
            ids = {capability.id for capability in capabilities}
            # Remove stale project entries and stale entries for this workspace,
            # but do not erase local catalogs belonging to other workspaces.
            stale = [
                row["id"]
                for row in connection.execute("SELECT id, scope, workspace_root FROM capabilities")
                if row["id"] not in ids
                and (row["scope"] != "workspace" or row["workspace_root"] == workspace_value)
            ]
            if stale:
                connection.executemany("DELETE FROM capabilities WHERE id = ?", ((item,) for item in stale))
            for capability in capabilities:
                discovered_at = now if capability.id not in existing else None
                connection.execute(
                    """
                    INSERT INTO capabilities(
                        id, kind, name, display_name, description, tags, scope,
                        workspace_root, path, owner, version, content_hash,
                        search_text, discovered_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        kind=excluded.kind, name=excluded.name,
                        display_name=excluded.display_name,
                        description=excluded.description, tags=excluded.tags,
                        scope=excluded.scope, workspace_root=excluded.workspace_root,
                        path=excluded.path, owner=excluded.owner,
                        version=excluded.version, content_hash=excluded.content_hash,
                        search_text=excluded.search_text,
                        updated_at=CASE WHEN capabilities.content_hash != excluded.content_hash
                            THEN excluded.updated_at ELSE capabilities.updated_at END
                    """,
                    capability.row() + (discovered_at or now, now),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO capability_metrics(capability_id) VALUES(?)",
                    (capability.id,),
                )
            if self._fts_available:
                connection.execute("DELETE FROM capabilities_fts")
                connection.execute(
                    """
                    INSERT INTO capabilities_fts(id, name, display_name, description, tags, owner, search_text)
                    SELECT id, name, display_name, description, tags, owner, search_text FROM capabilities
                    """
                )
            connection.execute(
                "INSERT OR REPLACE INTO catalog_meta(key, value) VALUES('last_indexed', ?)",
                (str(now),),
            )
            connection.execute(
                "DELETE FROM capability_events WHERE event_id NOT IN "
                "(SELECT event_id FROM capability_events ORDER BY event_id DESC LIMIT 10000)"
            )
        return {
            "ok": True,
            "count": len(capabilities),
            "added": sum(1 for item in capabilities if item.id not in existing),
            "updated": sum(1 for item in capabilities if existing.get(item.id) not in {None, item.content_hash}),
            "removed": len(stale),
            "database": str(self.db_path),
            "fts5": self._fts_available,
            "workspace": workspace_value,
        }

    def _ensure_index(self) -> None:
        with self._connection() as connection:
            row = connection.execute("SELECT value FROM catalog_meta WHERE key='last_indexed'").fetchone()
            count = connection.execute("SELECT COUNT(*) AS count FROM capabilities").fetchone()["count"]
        if not row or not count:
            self.reindex()

    @staticmethod
    def _public_row(row: sqlite3.Row, *, include_search_text: bool = False) -> dict[str, Any]:
        result = dict(row)
        result["tags"] = json.loads(result.get("tags") or "[]")
        result["ref"] = CapabilityRef.from_mapping(result).as_dict()
        # `search_text` can contain an entire SKILL.md or knowledge document.
        # It is useful to the local ranker, but sending it to the Workbench card
        # grid made the catalog payload grow with the source corpus.
        if not include_search_text:
            result.pop("search_text", None)
            result.pop("content_hash", None)
        attempts = int(result.get("successes") or 0) + int(result.get("failures") or 0)
        result["usage_count"] = int(result.get("activations") or 0)
        result["success_rate"] = round(int(result.get("successes") or 0) / attempts, 4) if attempts else None
        result["average_runtime_ms"] = round(float(result.get("total_runtime_ms") or 0) / attempts, 2) if attempts else None
        reuse = _reuse_contract(result)
        if reuse:
            result["reuse"] = reuse
        return result

    def list(
        self,
        *,
        kind: str | None = None,
        limit: int = 500,
        _include_search_text: bool = False,
        _deduplicate: bool = True,
    ) -> list[dict[str, Any]]:
        self._ensure_index()
        sql = """
            SELECT c.*, m.impressions, m.activations, m.successes, m.failures,
                   m.total_runtime_ms, m.last_seen, m.last_used, m.last_success
            FROM capabilities c JOIN capability_metrics m ON m.capability_id = c.id
        """
        # Workspace capabilities are private to the workspace that discovered
        # them.  The SQLite catalog is intentionally shared so usage metrics
        # survive switching projects, but rows from another workspace must
        # never become candidates (even at a lower rank).
        clauses = ["(c.scope != 'workspace' OR c.workspace_root = ?)"]
        params: list[Any] = [str(self.workspace)]
        if kind:
            clauses.append("c.kind = ?")
            params.append(kind)
        sql += " WHERE " + " AND ".join(clauses)
        sql += """
            ORDER BY
              CASE
                WHEN c.scope='workspace' AND c.workspace_root=? THEN 0
                WHEN c.scope='pack' THEN 1
                WHEN c.scope='identity' THEN 2
                ELSE 3
              END,
              m.activations DESC, c.updated_at DESC, c.name
            LIMIT ?
        """
        params.append(str(self.workspace))
        # Deduplication happens after the query so a repeated inherited Skill
        # does not consume the caller's requested result budget.
        query_limit = 5_000 if _deduplicate else max(1, min(int(limit), 5_000))
        params.append(query_limit)
        with self._connection() as connection:
            items = [
                self._public_row(row, include_search_text=_include_search_text)
                for row in connection.execute(sql, params)
            ]
        if not _deduplicate:
            return items
        logical: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in items:
            key = (str(item["kind"]), str(item["name"]).casefold())
            if key in seen:
                continue
            seen.add(key)
            logical.append(item)
            if len(logical) >= max(1, min(int(limit), 5_000)):
                break
        return logical

    def get(self, capability_id: str) -> dict[str, Any] | None:
        self._ensure_index()
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT c.*, m.impressions, m.activations, m.successes, m.failures,
                       m.total_runtime_ms, m.last_seen, m.last_used, m.last_success
                FROM capabilities c JOIN capability_metrics m ON m.capability_id = c.id
                WHERE c.id = ?
                  AND (c.scope != 'workspace' OR c.workspace_root = ?)
                """,
                (capability_id, str(self.workspace)),
            ).fetchone()
        return self._public_row(row) if row else None

    def find_by_path(self, path: str | Path) -> dict[str, Any] | None:
        self._ensure_index()
        resolved = str(Path(path).resolve())
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT c.*, m.impressions, m.activations, m.successes, m.failures,
                       m.total_runtime_ms, m.last_seen, m.last_used, m.last_success
                FROM capabilities c JOIN capability_metrics m ON m.capability_id = c.id
                WHERE c.path = ?
                  AND (c.scope != 'workspace' OR c.workspace_root = ?)
                LIMIT 1
                """,
                (resolved, str(self.workspace)),
            ).fetchone()
        return self._public_row(row) if row else None

    def _resolve_embedding_backend(self):
        if self._embedding_resolved:
            return self._embedding_backend
        self._embedding_resolved = True
        if self._embedding_backend_spec is False:
            self._embedding_status = {
                "available": False,
                "provider": "disabled",
                "fallback_reason": "disabled_for_registry",
            }
            return None
        if self._embedding_backend_spec is not _AUTO_EMBEDDINGS:
            self._embedding_backend = self._embedding_backend_spec
            status = getattr(self._embedding_backend, "status", None)
            self._embedding_status = status() if callable(status) else {
                "available": True,
                "provider": getattr(self._embedding_backend, "provider_name", "custom"),
                "model": getattr(self._embedding_backend, "model_id", "custom"),
                "remote": bool(getattr(self._embedding_backend, "remote", False)),
            }
            return self._embedding_backend
        from semantic_embeddings import create_embedding_backend

        self._embedding_backend, self._embedding_status = create_embedding_backend(self.project_root)
        return self._embedding_backend

    @staticmethod
    def _embedding_document(row: dict[str, Any]) -> str:
        """Compact capability card text suitable for dense retrieval.

        Executable bodies are deliberately excluded.  Embedding metadata is
        enough to discover a capability; activation remains the only operation
        that loads code or knowledge into an Agent context.
        """

        tags = " ".join(str(value) for value in row.get("tags", []))
        body = str(row.get("search_text") or "")
        return "\n".join(
            value for value in (
                f"type: {row.get('kind', '')}",
                f"name: {row.get('name', '')}",
                f"title: {row.get('display_name', '')}",
                f"description: {row.get('description', '')}",
                f"tags: {tags}",
                f"owner: {row.get('owner', '')}",
                f"details: {body[:2400]}",
            ) if value.strip(": ")
        )

    def _semantic_scores(
        self,
        rows: list[dict[str, Any]],
        query: str,
    ) -> tuple[dict[str, float], dict[str, Any]]:
        backend = self._resolve_embedding_backend()
        status = dict(self._embedding_status)
        if backend is None:
            return {}, status
        model = str(getattr(backend, "model_id", status.get("model") or "unknown"))
        cached_vectors: dict[str, list[float]] = {}
        missing: list[dict[str, Any]] = []
        try:
            with self._connection() as connection:
                cached = {
                    str(row["capability_id"]): row
                    for row in connection.execute(
                        "SELECT capability_id, content_hash, vector FROM capability_embeddings WHERE model=?",
                        (model,),
                    )
                }
            for row in rows:
                item = cached.get(str(row["id"]))
                if item and str(item["content_hash"]) == str(row.get("content_hash") or ""):
                    value = json.loads(str(item["vector"]))
                    if isinstance(value, list) and value:
                        cached_vectors[str(row["id"])] = [float(number) for number in value]
                        continue
                missing.append(row)

            embedded = 0
            batch_size = 32
            for offset in range(0, len(missing), batch_size):
                batch = missing[offset:offset + batch_size]
                vectors = backend.embed_documents([self._embedding_document(row) for row in batch])
                if len(vectors) != len(batch):
                    raise RuntimeError("embedding backend returned an incomplete document batch")
                now = _now()
                with self._lock, self._connection() as connection:
                    for row, vector in zip(batch, vectors):
                        normalized = [float(number) for number in vector]
                        if not normalized:
                            continue
                        cached_vectors[str(row["id"])] = normalized
                        connection.execute(
                            """
                            INSERT INTO capability_embeddings(
                                capability_id, model, content_hash, dimensions, vector, updated_at
                            ) VALUES(?, ?, ?, ?, ?, ?)
                            ON CONFLICT(capability_id, model) DO UPDATE SET
                                content_hash=excluded.content_hash,
                                dimensions=excluded.dimensions,
                                vector=excluded.vector,
                                updated_at=excluded.updated_at
                            """,
                            (
                                row["id"], model, row.get("content_hash") or "", len(normalized),
                                json.dumps(normalized, separators=(",", ":")), now,
                            ),
                        )
                        embedded += 1
            query_vector = backend.embed_query(query)
            from semantic_embeddings import cosine_similarity

            scores = {
                capability_id: float(cosine_similarity(query_vector, vector))
                for capability_id, vector in cached_vectors.items()
            }
            status.update({
                "available": True,
                "model": model,
                "cached_documents": len(rows) - len(missing),
                "embedded_documents": embedded,
                "indexed_documents": len(cached_vectors),
            })
            return scores, status
        except Exception as error:
            # Dense retrieval is an enhancement.  An unavailable model, rate
            # limit, or corrupt cache must never break exact-name tool lookup.
            status.update({"available": False, "fallback_reason": str(error)[:500]})
            return {}, status

    def search(
        self,
        query: str,
        *,
        kinds: Iterable[str] | None = None,
        limit: int = 8,
        record_impressions: bool = True,
        mode: str = "auto",
    ) -> dict[str, Any]:
        self._ensure_index()
        query = str(query or "").strip()
        mode = str(mode or "auto").strip().casefold().replace("_", "-")
        if mode not in {"auto", "hybrid", "semantic", "lexical"}:
            raise ValueError("mode must be auto, hybrid, semantic, or lexical")
        allowed_kinds = {str(kind) for kind in (kinds or []) if str(kind)}
        rows = [
            row for row in self.list(limit=5_000, _include_search_text=True, _deduplicate=False)
            if not allowed_kinds or row["kind"] in allowed_kinds
        ]
        terms = _query_terms(query)
        folded_query = query.casefold()
        action_aliases = {
            "create": ("create", "创建", "新建", "生成", "构建"),
            "modify": ("modify", "edit", "修改", "编辑", "调整"),
            "search": ("search", "find", "搜索", "查找", "检索"),
        }
        object_aliases = {
            "harness": ("harness", "dag", "流程", "智能体结构"),
            "skill": ("skill", "技能"),
            "tool": ("tool", "工具"),
            "knowledge": ("knowledge", "知识"),
            "identity": ("identity", "persona", "身份", "人格"),
            "agent": ("agent", "智能体"),
        }
        requested_actions = {
            canonical for canonical, aliases in action_aliases.items()
            if any(alias in folded_query for alias in aliases)
        }
        requested_objects = {
            canonical for canonical, aliases in object_aliases.items()
            if any(alias in folded_query for alias in aliases)
        }
        # "agent" is a generic modifier in phrases such as "agent harness".
        # Prefer the explicitly named capability type for action-object intent.
        if "agent" in requested_objects and len(requested_objects) > 1:
            requested_objects.remove("agent")
        current_workspace = str(self.workspace)
        lexical: list[tuple[float, float, dict[str, Any], list[str], bool]] = []
        diagnostics: dict[str, dict[str, Any]] = {}
        for row in rows:
            name = str(row["name"]).casefold()
            display = str(row["display_name"]).casefold()
            description = str(row["description"]).casefold()
            tags = " ".join(str(value) for value in row["tags"]).casefold()
            search_text = str(row["search_text"]).casefold()
            reasons: list[str] = []
            score = 0.0
            coverage = 1.0 if not query else 0.0
            exact_match = False
            matched = 0
            pair_hits: list[str] = []
            if query:
                exact_query = query.casefold()
                if exact_query == name or exact_query == display:
                    score += 8.0
                    reasons.append("exact name")
                    exact_match = True
                elif exact_query in name or exact_query in display:
                    score += 4.0
                    reasons.append("name")
                field_scores = {"name": 0.0, "tags": 0.0, "description": 0.0, "content": 0.0}
                for term in terms:
                    term_score = 0.0
                    if term in name or term in display:
                        term_score = 2.5
                        field_scores["name"] += term_score
                    elif term in tags:
                        term_score = 1.8
                        field_scores["tags"] += term_score
                    elif term in description:
                        term_score = 1.0
                        field_scores["description"] += term_score
                    elif term in search_text:
                        term_score = 0.55
                        field_scores["content"] += term_score
                    if term_score:
                        matched += 1
                # Cap per-field lexical contribution so verbose generated
                # names/documents cannot overwhelm concise canonical assets.
                score += min(7.5, field_scores["name"])
                score += min(5.4, field_scores["tags"])
                score += min(6.0, field_scores["description"])
                score += min(4.4, field_scores["content"])
                coverage = matched / max(1, len(terms))
                score += coverage
                if terms and matched == len(terms):
                    score += 1.5
                    reasons.append("all terms")
                # Long user-created names can accidentally win lexical search.
                # When the query clearly requests an action on a capability
                # type, reward the reusable executable whose stable name states
                # that same action-object pair (for example create_harness).
                canonical_name = re.sub(r"[^a-z0-9]+", "_", name).strip("_")
                intent_pairs = {
                    f"{action}_{object_name}"
                    for action in requested_actions
                    for object_name in requested_objects
                }
                pair_hits = [pair for pair in intent_pairs if pair in canonical_name]
                if pair_hits:
                    score += 8.0
                    reasons.append(f"task intent {pair_hits[0]}")
                    if row["kind"] in {"skill", "tool"}:
                        score += 0.75
            else:
                score = 0.25

            if row["scope"] == "workspace" and row["workspace_root"] == current_workspace:
                score += 3.0
                reasons.append("current workspace")
            elif row["scope"] in {"identity", "project"}:
                score += 0.25
            successes = int(row.get("successes") or 0)
            failures = int(row.get("failures") or 0)
            attempts = successes + failures
            if attempts:
                # Wilson lower bound rewards evidence while limiting feedback
                # loops caused by a single lucky execution.
                z = 1.2815515655446004
                rate = successes / attempts
                denominator = 1 + z * z / attempts
                wilson = (
                    rate + z * z / (2 * attempts)
                    - z * math.sqrt((rate * (1 - rate) + z * z / (4 * attempts)) / attempts)
                ) / denominator
                score += 0.9 * wilson
                reasons.append(f"{successes}/{attempts} successful")
            score += min(0.6, math.log1p(int(row.get("activations") or 0)) * 0.12)
            last_success = float(row.get("last_success") or 0)
            if last_success:
                age_days = max(0.0, (_now() - last_success) / 86400)
                score += 0.25 * math.exp(-age_days / 30)
            diagnostics[str(row["id"])] = {
                "lexical_score": score,
                "coverage": 1.0 if exact_match else coverage,
                "reasons": reasons,
                "exact": exact_match,
            }
            # One accidental CJK bigram inside a long document is not a useful
            # lexical candidate.  Keep exact/task-intent hits, otherwise demand
            # modest query coverage before the row participates in RRF.
            if not query or exact_match or pair_hits or (matched and coverage >= 0.2):
                lexical.append((score, 1.0 if exact_match else coverage, row, reasons, exact_match))

        lexical.sort(key=lambda item: (-item[0], -item[1], -int(item[2].get("activations") or 0), item[2]["name"]))
        semantic_scores: dict[str, float] = {}
        embedding_status: dict[str, Any] = {
            "available": False,
            "provider": "not-requested",
            "fallback_reason": None,
        }
        if query and mode != "lexical":
            semantic_scores, embedding_status = self._semantic_scores(rows, query)

        semantic_ranked: list[tuple[float, dict[str, Any]]] = []
        if semantic_scores:
            semantic_ranked = sorted(
                ((semantic_scores.get(str(row["id"]), -1.0), row) for row in rows),
                key=lambda item: (-item[0], -int(item[1].get("activations") or 0), item[1]["name"]),
            )
            top_semantic = semantic_ranked[0][0] if semantic_ranked else 0.0
            floor = max(0.15, top_semantic - 0.25)
            semantic_ranked = [item for item in semantic_ranked if item[0] >= floor][:100]

        lexical_rank = {str(item[2]["id"]): index for index, item in enumerate(lexical, 1)}
        semantic_rank = {str(item[1]["id"]): index for index, item in enumerate(semantic_ranked, 1)}
        rows_by_id = {str(row["id"]): row for row in rows}
        if mode == "semantic" and semantic_rank:
            candidate_ids = set(semantic_rank)
            retrieval = "semantic"
        elif semantic_rank and mode in {"auto", "hybrid"}:
            candidate_ids = set(lexical_rank) | set(semantic_rank)
            retrieval = "hybrid" if lexical_rank else "semantic"
        else:
            candidate_ids = set(lexical_rank)
            retrieval = "lexical"

        rank_constant = 60
        scored: list[tuple[float, float, dict[str, Any], list[str]]] = []
        for capability_id in candidate_ids:
            row = rows_by_id[capability_id]
            detail = diagnostics.get(capability_id, {})
            lexical_score = float(detail.get("lexical_score", 0.0))
            semantic_score = float(semantic_scores.get(capability_id, 0.0))
            reasons = list(detail.get("reasons", []))
            if semantic_rank.get(capability_id):
                reasons.append(f"semantic {semantic_score:.3f}")
            if retrieval == "semantic":
                final_score = semantic_score * 10.0
            elif retrieval == "hybrid":
                # Rank fusion avoids comparing provider-specific cosine values
                # with lexical scores. Exact names keep a small deterministic
                # tie-break advantage without suppressing synonym-only hits.
                final_score = 0.0
                if capability_id in lexical_rank:
                    final_score += 115.0 / (rank_constant + lexical_rank[capability_id])
                if capability_id in semantic_rank:
                    final_score += 100.0 / (rank_constant + semantic_rank[capability_id])
                final_score += min(0.35, lexical_score * 0.01)
                if detail.get("exact"):
                    final_score += 0.75
                if any(str(reason).startswith("task intent ") for reason in reasons):
                    final_score += 2.0
            else:
                final_score = lexical_score
            scored.append((final_score, float(detail.get("coverage", 0.0)), row, reasons))

        scored.sort(key=lambda item: (-item[0], -item[1], -int(item[2].get("activations") or 0), item[2]["name"]))
        selected = []
        logical_keys = set()
        for candidate in scored:
            key = (candidate[2]["kind"], candidate[2]["name"].casefold())
            if key in logical_keys:
                continue
            logical_keys.add(key)
            selected.append(candidate)
            if len(selected) >= max(1, min(int(limit), 50)):
                break
        top_score = selected[0][0] if selected else 0.0
        top_coverage = selected[0][1] if selected else 0.0
        top_semantic_score = max((semantic_scores.get(str(item[2]["id"]), 0.0) for item in selected), default=0.0)
        if retrieval == "semantic":
            strong_match = top_semantic_score >= 0.38
        elif retrieval == "hybrid":
            strong_match = top_coverage >= 0.45 or top_semantic_score >= 0.38
        else:
            strong_match = top_score >= 2.0 and top_coverage >= 0.45
        creation_recommended = not selected or (bool(query) and not strong_match)
        compact_results = []
        for score, coverage, row, reasons in selected:
            compact_results.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "name": row["name"],
                    "description": row["description"],
                    "tags": row["tags"],
                    "scope": row["scope"],
                    "owner": row["owner"],
                    "usage_count": row["usage_count"],
                    "success_rate": row["success_rate"],
                    "score": round(score, 4),
                    "lexical_score": round(float(diagnostics.get(str(row["id"]), {}).get("lexical_score", 0.0)), 4),
                    "semantic_score": round(float(semantic_scores.get(str(row["id"]), 0.0)), 6) if semantic_scores else None,
                    "query_coverage": round(coverage, 4),
                    "match_reason": ", ".join(reasons) or "catalog ranking",
                    "reuse": row.get("reuse"),
                    "ref": row.get("ref"),
                }
            )
        with self._lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO search_events(query, workspace_root, result_count, creation_recommended, created_at) VALUES(?, ?, ?, ?, ?)",
                (query, current_workspace, len(compact_results), int(creation_recommended), _now()),
            )
            if record_impressions and compact_results:
                now = _now()
                connection.executemany(
                    "UPDATE capability_metrics SET impressions=impressions+1, last_seen=? WHERE capability_id=?",
                    ((now, item["id"]) for item in compact_results),
                )
        return {
            "query": query,
            "workspace": current_workspace,
            "results": compact_results,
            "retrieval": retrieval,
            "requested_mode": mode,
            "embedding": embedding_status,
            "fusion": {"algorithm": "rrf", "rank_constant": rank_constant} if retrieval == "hybrid" else None,
            "creation_recommended": creation_recommended,
            "guidance": (
                "No strong reusable capability matched. Create a narrowly scoped capability, test it, then reindex."
                if creation_recommended
                else "Activate the best matching capability before creating a duplicate."
            ),
        }

    def record_event(
        self,
        capability_id: str,
        event: str,
        *,
        success: bool | None = None,
        runtime_ms: float | None = None,
    ) -> bool:
        if event not in {"activate", "execute"}:
            raise ValueError(f"Unsupported capability event: {event}")
        self._ensure_index()
        now = _now()
        with self._lock, self._connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM capabilities WHERE id=? "
                "AND (scope != 'workspace' OR workspace_root = ?)",
                (capability_id, str(self.workspace)),
            ).fetchone()
            if not exists:
                return False
            if event == "activate":
                connection.execute(
                    "UPDATE capability_metrics SET activations=activations+1, last_used=? WHERE capability_id=?",
                    (now, capability_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE capability_metrics SET
                        successes=successes+?, failures=failures+?,
                        total_runtime_ms=total_runtime_ms+?, last_used=?,
                        last_success=CASE WHEN ? THEN ? ELSE last_success END
                    WHERE capability_id=?
                    """,
                    (int(success is True), int(success is False), float(runtime_ms or 0), now, int(success is True), now, capability_id),
                )
            connection.execute(
                "INSERT INTO capability_events(capability_id, event, success, runtime_ms, workspace_root, created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (capability_id, event, None if success is None else int(success), runtime_ms, str(self.workspace), now),
            )
        return True

    def record_path_execution(self, path: str | Path, *, success: bool, runtime_ms: float) -> bool:
        item = self.find_by_path(path)
        return bool(item and self.record_event(item["id"], "execute", success=success, runtime_ms=runtime_ms))

    def stats(self) -> dict[str, Any]:
        self._ensure_index()
        self._resolve_embedding_backend()
        workspace = str(self.workspace)
        with self._connection() as connection:
            kinds = {
                row["kind"]: row["count"]
                for row in connection.execute(
                    "SELECT kind, COUNT(DISTINCT lower(name)) AS count FROM capabilities "
                    "WHERE scope != 'workspace' OR workspace_root = ? GROUP BY kind",
                    (workspace,),
                )
            }
            source_count = connection.execute(
                "SELECT COUNT(*) AS count FROM capabilities "
                "WHERE scope != 'workspace' OR workspace_root = ?",
                (workspace,),
            ).fetchone()["count"]
            logical_count = connection.execute(
                "SELECT COUNT(*) AS count FROM (SELECT kind, lower(name) FROM capabilities "
                "WHERE scope != 'workspace' OR workspace_root = ? GROUP BY kind, lower(name))",
                (workspace,),
            ).fetchone()["count"]
            totals = dict(
                connection.execute(
                    """
                    SELECT COALESCE(SUM(impressions), 0) AS impressions,
                           COALESCE(SUM(activations), 0) AS activations,
                           COALESCE(SUM(successes), 0) AS successes,
                           COALESCE(SUM(failures), 0) AS failures
                    FROM capability_metrics m
                    JOIN capabilities c ON c.id = m.capability_id
                    WHERE c.scope != 'workspace' OR c.workspace_root = ?
                    """,
                    (workspace,),
                ).fetchone()
            )
            searches = connection.execute(
                "SELECT COUNT(*) AS count FROM search_events WHERE workspace_root = ?", (workspace,)
            ).fetchone()["count"]
            embedded = connection.execute(
                "SELECT COUNT(*) AS count FROM capability_embeddings e "
                "JOIN capabilities c ON c.id = e.capability_id "
                "WHERE c.scope != 'workspace' OR c.workspace_root = ?",
                (workspace,),
            ).fetchone()["count"]
            last_indexed = connection.execute("SELECT value FROM catalog_meta WHERE key='last_indexed'").fetchone()
        return {
            **totals,
            "capabilities": logical_count,
            "capability_sources": source_count,
            "searches": searches,
            "kinds": kinds,
            "workspace": str(self.workspace),
            "database": str(self.db_path),
            "fts5": self._fts_available,
            "embedding": {**self._embedding_status, "cached_vectors": embedded},
            "last_indexed": float(last_indexed["value"]) if last_indexed else None,
        }


def project_root_from_context(context: dict[str, Any] | None = None) -> Path:
    context = context or {}
    configured = context.get("project_root")
    return Path(str(configured)).resolve() if configured else Path(__file__).resolve().parent


def registry_from_context(context: dict[str, Any] | None = None) -> CapabilityRegistry:
    context = context or {}
    workspace = context.get("workspace")
    return CapabilityRegistry(project_root_from_context(context), workspace=workspace)
