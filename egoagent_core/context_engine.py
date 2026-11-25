"""Typed, inspectable codebase context catalog, index, retrieval, and planner.

The engine is intentionally useful without an API key.  It keeps all index and
feedback data inside the selected workspace and falls back to lexical retrieval
when an embedding/rerank role is unavailable.
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import html
import json
import math
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


INDEX_VERSION = 1
COMMON_IGNORES = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "node_modules", "dist", "build",
    "out", "target", "coverage", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".venv", "venv", "env", ".next", ".turbo", ".egoagent",
}
SENSITIVE_NAMES = {".env", ".env.local", "id_rsa", "id_ed25519", "credentials", "credentials.json"}
TEXT_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".java", ".kt",
    ".go", ".rs", ".c", ".h", ".cpp", ".hpp", ".cs", ".rb", ".php", ".swift",
    ".scala", ".sh", ".ps1", ".sql", ".html", ".css", ".scss", ".vue", ".svelte",
    ".md", ".rst", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".xml", ".graphql", ".proto",
}
_locks: Dict[str, threading.RLock] = {}
_locks_guard = threading.RLock()


@dataclass
class ContextItem:
    id: str
    kind: str
    title: str
    content: str
    path: str = ""
    uri: str = ""
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    provenance: str = "automatic"
    revision: str = ""
    captured_at: float = field(default_factory=time.time)
    freshness: float = 1.0
    score: float = 0.0
    token_count: int = 0
    explicit: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["token_count"] = self.token_count or estimate_tokens(self.content)
        return value


def estimate_tokens(text: Any) -> int:
    return max(1, math.ceil(len(str(text or "")) / 4))


def _hash(*parts: Any) -> str:
    value = "\x1f".join(str(part or "") for part in parts)
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _workspace(value: Any) -> Path:
    if not value:
        raise ValueError("workspace is required")
    root = Path(str(value)).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"workspace does not exist: {root}")
    return root


def _inside(root: Path, value: Any) -> Path:
    path = Path(str(value))
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"path escapes workspace: {value}") from error
    return resolved


def _state_dir(root: Path) -> Path:
    target = root / ".egoagent"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _index_path(root: Path) -> Path:
    return _state_dir(root) / "context_index.json"


def _feedback_path(root: Path) -> Path:
    return _state_dir(root) / "context_feedback.json"


def _lock(root: Path) -> threading.RLock:
    key = str(root).lower()
    with _locks_guard:
        return _locks.setdefault(key, threading.RLock())


def _atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


def _ignore_patterns(root: Path) -> List[str]:
    patterns: List[str] = []
    for name in (".gitignore", ".ignore", ".egoagentignore"):
        path = root / name
        try:
            for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
                value = raw.strip()
                if value and not value.startswith("#") and not value.startswith("!"):
                    patterns.append(value.lstrip("/"))
        except OSError:
            pass
    return patterns


def _ignored(relative: str, patterns: Iterable[str]) -> bool:
    normalized = relative.replace("\\", "/")
    parts = normalized.split("/")
    if any(part in COMMON_IGNORES for part in parts):
        return True
    if parts[-1].lower() in SENSITIVE_NAMES or parts[-1].lower().endswith((".pem", ".key", ".p12")):
        return True
    for pattern in patterns:
        candidate = pattern.rstrip("/")
        if fnmatch.fnmatch(normalized, candidate) or fnmatch.fnmatch(normalized, f"{candidate}/**"):
            return True
    return False


def _generated(relative: str, text: str) -> bool:
    name = relative.lower()
    head = text[:500].lower()
    return (
        name.endswith((".min.js", ".min.css", ".map", ".lock"))
        or "generated file" in head
        or "do not edit" in head
        or "@generated" in head
    )


def _language(path: Path) -> str:
    return {
        ".py": "python", ".pyi": "python", ".js": "javascript", ".jsx": "javascriptreact",
        ".ts": "typescript", ".tsx": "typescriptreact", ".rs": "rust", ".go": "go",
        ".java": "java", ".md": "markdown", ".json": "json", ".yml": "yaml", ".yaml": "yaml",
    }.get(path.suffix.lower(), path.suffix.lower().lstrip(".") or "text")


def _python_symbols(text: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    symbols: List[Dict[str, Any]] = []
    dependencies: List[str] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return symbols, dependencies
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append({
                "name": node.name,
                "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                "line": int(getattr(node, "lineno", 1)),
                "end_line": int(getattr(node, "end_lineno", getattr(node, "lineno", 1))),
            })
        elif isinstance(node, ast.Import):
            dependencies.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            dependencies.append(node.module)
    return sorted(symbols, key=lambda item: item["line"]), sorted(set(dependencies))


def _generic_symbols(text: str, language: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    symbols: List[Dict[str, Any]] = []
    dependencies: List[str] = []
    patterns = [
        ("class", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:class|interface|enum|type)\s+([A-Za-z_$][\w$]*)")),
        ("function", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)")),
        ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>")),
        ("heading", re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")),
    ]
    import_pattern = re.compile(r"(?:from\s+|require\s*\(\s*)['\"]([^'\"]+)['\"]")
    for line_number, line in enumerate(text.splitlines(), 1):
        for kind, pattern in patterns:
            match = pattern.search(line)
            if match:
                symbols.append({"name": match.group(1)[:160], "kind": kind, "line": line_number, "end_line": line_number})
                break
        dependencies.extend(import_pattern.findall(line))
    return symbols, sorted(set(dependencies))


def _analyze(text: str, language: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    return _python_symbols(text) if language == "python" else _generic_symbols(text, language)


def _chunks(relative: str, text: str, language: str, revision: str, modified: float) -> List[Dict[str, Any]]:
    lines = text.splitlines()
    symbols, dependencies = _analyze(text, language)
    starts = sorted({max(0, int(symbol["line"]) - 1) for symbol in symbols})
    boundaries: List[Tuple[int, int]] = []
    if starts:
        if starts[0] > 0:
            for chunk_start in range(0, starts[0], 120):
                boundaries.append((chunk_start, min(starts[0], chunk_start + 120)))
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(lines)
            for chunk_start in range(start, max(start + 1, end), 180):
                boundaries.append((chunk_start, min(max(start + 1, end), chunk_start + 180)))
    else:
        boundaries = [(start, min(len(lines), start + 120)) for start in range(0, max(1, len(lines)), 120)]
    output: List[Dict[str, Any]] = []
    for start, end in boundaries:
        content = "\n".join(lines[start:end])
        if not content.strip():
            continue
        names = [item["name"] for item in symbols if start < int(item["line"]) <= end]
        output.append({
            "id": _hash(relative, start, end, revision)[:24],
            "path": relative,
            "language": language,
            "start_line": start + 1,
            "end_line": max(start + 1, end),
            "content": content,
            "symbols": names,
            "dependencies": dependencies,
            "revision": revision,
            "modified": modified,
            "token_count": estimate_tokens(content),
        })
    return output


def build_index(workspace: Any, force: bool = False) -> Dict[str, Any]:
    root = _workspace(workspace)
    path = _index_path(root)
    patterns = _ignore_patterns(root)
    with _lock(root):
        previous = _load_json(path, {})
        previous_files = previous.get("files", {}) if isinstance(previous, dict) else {}
        files: Dict[str, Any] = {}
        indexed = skipped = reused = 0
        for current_root, directories, names in os.walk(root):
            current = Path(current_root)
            relative_root = current.relative_to(root).as_posix() if current != root else ""
            directories[:] = [name for name in directories if not _ignored(f"{relative_root}/{name}".strip("/"), patterns)]
            for name in names:
                absolute = current / name
                relative = absolute.relative_to(root).as_posix()
                if _ignored(relative, patterns) or (absolute.suffix.lower() not in TEXT_SUFFIXES and name not in {"Dockerfile", "Makefile"}):
                    skipped += 1
                    continue
                try:
                    absolute.resolve().relative_to(root)
                    stat = absolute.stat()
                    if stat.st_size > 1_000_000:
                        skipped += 1
                        continue
                    signature = f"{stat.st_mtime_ns}:{stat.st_size}"
                    old = previous_files.get(relative)
                    if not force and old and old.get("signature") == signature:
                        files[relative] = old
                        reused += 1
                        continue
                    raw = absolute.read_bytes()
                    if b"\0" in raw[:8192]:
                        skipped += 1
                        continue
                    text = raw.decode("utf-8", errors="replace")
                    if _generated(relative, text):
                        skipped += 1
                        continue
                    revision = hashlib.sha256(raw).hexdigest()
                    language = _language(absolute)
                    symbols, dependencies = _analyze(text, language)
                    files[relative] = {
                        "signature": signature,
                        "revision": revision,
                        "modified": stat.st_mtime,
                        "language": language,
                        "symbols": symbols,
                        "dependencies": dependencies,
                        "chunks": _chunks(relative, text, language, revision, stat.st_mtime),
                    }
                    indexed += 1
                except (OSError, UnicodeError, ValueError):
                    skipped += 1
        state = {
            "version": INDEX_VERSION,
            "workspace": str(root),
            "updated_at": time.time(),
            "files": files,
            "stats": {
                "files": len(files),
                "chunks": sum(len(item.get("chunks", [])) for item in files.values()),
                "symbols": sum(len(item.get("symbols", [])) for item in files.values()),
                "indexed": indexed,
                "reused": reused,
                "removed": len(set(previous_files) - set(files)),
                "skipped": skipped,
            },
        }
        _atomic_json(path, state)
        return {"ok": True, **state["stats"], "updated_at": state["updated_at"], "workspace": str(root)}


def index_status(workspace: Any) -> Dict[str, Any]:
    root = _workspace(workspace)
    state = _load_json(_index_path(root), {})
    return {
        "workspace": str(root),
        "available": bool(state.get("files")),
        "version": state.get("version"),
        "updated_at": state.get("updated_at"),
        **(state.get("stats") or {}),
    }


def _terms(value: Any) -> List[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or ""))
    return [item.lower() for item in re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,}|[\u4e00-\u9fff]{1,8}", text)]


def _local_embedding(value: Any, dimensions: int = 384) -> Dict[int, float]:
    """Build a private, dependency-free sparse embedding.

    Identifier tokens, subwords and CJK character windows make this more robust
    than exact BM25-style overlap while keeping source code on the workstation.
    It is intentionally deterministic so retrieval experiments are reproducible.
    """
    text = str(value or "").lower()
    features: List[str] = []
    for term in _terms(text):
        features.append("word:" + term)
        padded = f"^{term}$"
        features.extend("tri:" + padded[index:index + 3] for index in range(max(1, len(padded) - 2)))
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", text))
    features.extend("cjk:" + cjk[index:index + 2] for index in range(max(0, len(cjk) - 1)))
    vector: Dict[int, float] = {}
    for feature in features:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[bucket] = vector.get(bucket, 0.0) + sign
    norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
    return {key: value / norm for key, value in vector.items()}


def _cosine_sparse(left: Dict[int, float], right: Dict[int, float]) -> float:
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(key, 0.0) for key, value in left.items())


def _diverse_rerank(items: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """Deterministic MMR-like reranker that avoids one large file monopolising context."""
    pending = list(items)
    selected: List[Dict[str, Any]] = []
    path_counts: Dict[str, int] = {}
    while pending and len(selected) < limit:
        best_index = max(
            range(len(pending)),
            key=lambda index: (
                float(pending[index].get("score", 0)) - 0.35 * path_counts.get(str(pending[index].get("path", "")), 0),
                float(pending[index].get("metadata", {}).get("semantic_score", 0)),
                -int(pending[index].get("start_line") or 0),
            ),
        )
        item = pending.pop(best_index)
        selected.append(item)
        path = str(item.get("path", ""))
        path_counts[path] = path_counts.get(path, 0) + 1
    return selected


def _feedback(root: Path) -> Dict[str, Any]:
    value = _load_json(_feedback_path(root), {"items": {}})
    return value if isinstance(value, dict) else {"items": {}}


def retrieve(workspace: Any, query: str, limit: int = 16, mode: str = "auto", *, budget_seconds=None) -> Dict[str, Any]:
    root = _workspace(workspace)
    state = _load_json(_index_path(root), {})
    if not state.get("files"):
        build_index(root)
        state = _load_json(_index_path(root), {})
    query_terms = _terms(query)
    feedback = _feedback(root).get("items", {})
    results: List[Dict[str, Any]] = []
    deadline = time.monotonic() + float(budget_seconds) if budget_seconds is not None else float("inf")
    now = time.time()
    semantic_enabled = mode in {"auto", "embedding", "hybrid", "semantic-local"}
    query_embedding = _local_embedding(query) if semantic_enabled else {}
    for relative, file_info in state.get("files", {}).items():
        if time.monotonic() >= deadline:
            break
        path_terms = _terms(relative)
        for chunk in file_info.get("chunks", []):
            if time.monotonic() >= deadline:
                break
            content_terms = _terms(chunk.get("content", ""))
            if query_terms:
                term_counts = {term: content_terms.count(term) for term in set(query_terms)}
                overlap = sum((1 + math.log1p(count)) for count in term_counts.values() if count)
                path_overlap = sum(1.5 for term in query_terms if term in path_terms)
                symbol_overlap = sum(2.0 for term in query_terms for name in chunk.get("symbols", []) if term in name.lower())
                score = overlap + path_overlap + symbol_overlap
            else:
                score = 0.1
            semantic_score = max(0.0, _cosine_sparse(query_embedding, _local_embedding(
                " ".join([relative, *chunk.get("symbols", []), chunk.get("content", "")])
            ))) if semantic_enabled else 0.0
            if mode in {"embedding", "semantic-local"}:
                score = semantic_score * 8.0
            elif semantic_enabled:
                score += semantic_score * 3.0
            age_days = max(0.0, (now - float(chunk.get("modified", now))) / 86400)
            freshness = 1 / (1 + age_days / 30)
            score += freshness * 0.2
            learned = feedback.get(chunk.get("id"), {})
            score += float(learned.get("accepted", 0)) * 0.25 - float(learned.get("rejected", 0)) * 0.2
            if score <= 0:
                continue
            item = ContextItem(
                id=chunk["id"], kind="symbol" if chunk.get("symbols") else "file",
                title=f"{relative}:{chunk['start_line']}-{chunk['end_line']}", content=chunk["content"],
                path=relative, start_line=chunk["start_line"], end_line=chunk["end_line"],
                provenance="lexical-index", revision=chunk.get("revision", ""), freshness=freshness,
                score=score, token_count=chunk.get("token_count", 0), metadata={
                    "language": chunk.get("language"), "symbols": chunk.get("symbols", []),
                    "dependencies": chunk.get("dependencies", []),
                    "semantic_score": round(semantic_score, 6),
                },
            ).as_dict()
            results.append(item)
    results.sort(key=lambda item: (-item["score"], item["path"], item.get("start_line") or 0))
    result_limit = max(1, min(int(limit), 100))
    ranked = _diverse_rerank(results, result_limit) if semantic_enabled else results[:result_limit]
    return {
        "items": ranked,
        "retrieval": "hybrid-local" if semantic_enabled and mode not in {"embedding", "semantic-local"} else ("embedding-local" if semantic_enabled else "lexical"),
        "requested_mode": mode,
        "embedding": {"adapter": "private-hashed-subword", "dimensions": 384, "remote_source_sent": False} if semantic_enabled else None,
        "rerank": "diverse-local" if semantic_enabled else "score",
        "fallback_reason": None,
        "query_terms": query_terms,
        "index": index_status(root),
    }


def repo_map(workspace: Any, maximum_files: int = 120) -> ContextItem:
    root = _workspace(workspace)
    state = _load_json(_index_path(root), {})
    if not state.get("files"):
        build_index(root)
        state = _load_json(_index_path(root), {})
    lines: List[str] = []
    revisions: List[str] = []
    for relative, info in sorted(state.get("files", {}).items())[:maximum_files]:
        names = [item.get("name", "") for item in info.get("symbols", [])[:12]]
        deps = info.get("dependencies", [])[:8]
        detail = f" — symbols: {', '.join(names)}" if names else ""
        if deps:
            detail += f" — imports: {', '.join(deps)}"
        lines.append(relative + detail)
        revisions.append(info.get("revision", ""))
    content = "\n".join(lines)
    return ContextItem(
        id=_hash("repo-map", *revisions)[:24], kind="repo_map", title="Repository map",
        content=content, path=".", provenance="incremental-index", revision=_hash(*revisions),
        token_count=estimate_tokens(content), score=0.5,
        metadata={"files": len(state.get("files", {})), "truncated": len(state.get("files", {})) > maximum_files},
    )


def _payload_item(kind: str, value: Any, *, explicit: bool = False, index: int = 0) -> Optional[ContextItem]:
    if value is None:
        return None
    raw = value if isinstance(value, dict) else {"content": str(value)}
    content = raw.get("content")
    if content is None:
        content = json.dumps(raw, ensure_ascii=False)
    content = str(content)
    if not content.strip():
        return None
    path = str(raw.get("path") or "")
    start = raw.get("start_line")
    end = raw.get("end_line")
    return ContextItem(
        id=str(raw.get("id") or _hash(kind, path, start, end, content)[:24]),
        kind=kind,
        title=str(raw.get("title") or f"{kind} {path}" or kind),
        content=content[:50000], path=path, uri=str(raw.get("uri") or ""),
        start_line=int(start) if start is not None else None,
        end_line=int(end) if end is not None else None,
        provenance=str(raw.get("provenance") or ("explicit-user" if explicit else "editor-runtime")),
        revision=str(raw.get("revision") or ""), score=float(raw.get("score") or (100 if explicit else 1)),
        token_count=estimate_tokens(content[:50000]), explicit=explicit,
        metadata=dict(raw.get("metadata") or {}),
    )


def build_catalog(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    root = _workspace(payload.get("workspace"))
    query = str(payload.get("query") or "")
    items: List[ContextItem] = []
    for index, value in enumerate(payload.get("explicit", []) if isinstance(payload.get("explicit"), list) else []):
        kind = str(value.get("kind") or "file") if isinstance(value, dict) else "file"
        item = _payload_item(kind, value, explicit=True, index=index)
        if item:
            items.append(item)
    single_types = {
        "selection": payload.get("selection"), "file": payload.get("file"),
        "diff": payload.get("diff"), "terminal": payload.get("terminal"),
        "test": payload.get("test_result"),
    }
    for kind, value in single_types.items():
        item = _payload_item(kind, value)
        if item:
            items.append(item)
    for kind, key in (("diagnostic", "diagnostics"), ("recent", "recent"), ("reference", "references"), ("definition", "definitions")):
        values = payload.get(key, []) if isinstance(payload.get(key), list) else []
        for index, value in enumerate(values[:100]):
            item = _payload_item(kind, value, index=index)
            if item:
                items.append(item)
    # Sending a chat must not synchronously build an entire cold index. Tools
    # can still read/search the workspace; explicit indexing retains its API.
    index_ready = not payload.get("cached_only") or index_status(root).get("available")
    if index_ready and payload.get("include_repo_map", True):
        items.append(repo_map(root))
    retrieval = retrieve(root, query, limit=int(payload.get("retrieval_limit") or 18),
                         mode=str(payload.get("retrieval_mode") or "auto"),
                         budget_seconds=payload.get("retrieval_budget_seconds")) if index_ready else {"items": []}
    items.extend(ContextItem(**{
        key: value for key, value in raw.items() if key in ContextItem.__dataclass_fields__
    }) for raw in retrieval["items"])
    unique: Dict[str, ContextItem] = {}
    for item in items:
        existing = unique.get(item.id)
        if not existing or (item.explicit, item.score) > (existing.explicit, existing.score):
            unique[item.id] = item
    return [item.as_dict() for item in unique.values()]


def plan_context(payload: Dict[str, Any]) -> Dict[str, Any]:
    budget = max(128, min(int(payload.get("token_budget") or 12000), 200000))
    items = build_catalog(payload)
    items.sort(key=lambda item: (not item.get("explicit", False), -float(item.get("score", 0)), item.get("token_count", 0)))
    selected: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    used = 0
    seen_content: set[str] = set()
    for item in items:
        fingerprint = _hash(item.get("content", ""))
        if fingerprint in seen_content:
            excluded.append({"id": item["id"], "reason": "duplicate content", "token_count": item["token_count"]})
            continue
        cost = int(item.get("token_count") or 1)
        if used + cost > budget:
            excluded.append({"id": item["id"], "reason": "token budget", "token_count": cost, "score": item.get("score", 0)})
            continue
        selected.append(item)
        seen_content.add(fingerprint)
        used += cost
    prompt_parts = []
    for item in selected:
        location = item.get("path") or item.get("uri") or item.get("title")
        if item.get("start_line"):
            location += f":{item['start_line']}-{item.get('end_line') or item['start_line']}"
        reference = str((item.get("metadata") or {}).get("reference") or "")
        reference_attr = f' reference="{html.escape(reference, quote=True)}"' if reference else ""
        prompt_parts.append(
            f"<context kind=\"{html.escape(str(item['kind']), quote=True)}\" "
            f"source=\"{html.escape(str(item['provenance']), quote=True)}\" "
            f"location=\"{html.escape(str(location), quote=True)}\"{reference_attr} "
            f"revision=\"{html.escape(str(item.get('revision', '')), quote=True)}\">\n"
            f"{item['content']}\n</context>"
        )
    return {
        "selected": selected,
        "excluded": excluded,
        "token_budget": budget,
        "tokens_used": used,
        "tokens_remaining": budget - used,
        "prompt": "\n\n".join(prompt_parts),
        "explanation": {
            "policy": "explicit-first, then learned local hybrid retrieval and diverse reranking under a hard token budget",
            "selected": len(selected), "excluded": len(excluded),
            "privacy": "index and feedback remain inside the workspace",
        },
    }


def record_context_feedback(workspace: Any, item_ids: Iterable[str], decision: str) -> Dict[str, Any]:
    root = _workspace(workspace)
    decision = str(decision)
    if decision not in {"accepted", "rejected"}:
        raise ValueError("decision must be accepted or rejected")
    with _lock(root):
        path = _feedback_path(root)
        state = _load_json(path, {"version": 1, "items": {}})
        state.setdefault("items", {})
        count = 0
        for item_id in item_ids:
            key = str(item_id)
            if not key:
                continue
            entry = state["items"].setdefault(key, {"accepted": 0, "rejected": 0})
            entry[decision] = int(entry.get(decision, 0)) + 1
            entry["updated_at"] = time.time()
            count += 1
        _atomic_json(path, state)
    return {"ok": True, "recorded": count, "decision": decision}
