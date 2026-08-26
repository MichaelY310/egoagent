"""Bounded local paper retrieval with a persistent, workspace-local cache."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


SUPPORTED = {".pdf", ".txt", ".md", ".markdown"}


def _safe_root(workspace: Path, requested: str) -> Path:
    candidate = Path(requested or "papers")
    resolved = candidate.resolve() if candidate.is_absolute() else (workspace / candidate).resolve()
    if resolved != workspace and workspace not in resolved.parents:
        raise ValueError(f"paper root escapes workspace: {requested}")
    if not resolved.is_dir():
        raise ValueError(f"paper directory not found: {resolved}")
    return resolved


def _pdf_pages(path: Path):
    reader = None
    errors = []
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = __import__(module_name)
            reader = module.PdfReader(str(path))
            break
        except (ImportError, OSError, ValueError) as error:
            errors.append(f"{module_name}: {error}")
    if reader is None:
        raise RuntimeError("PDF extraction requires pypdf or PyPDF2; " + "; ".join(errors))
    pages = []
    for index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception as error:
            text = f"[page extraction failed: {error}]"
        pages.append({"page": index + 1, "text": text})
    return pages


def _read_pages(path: Path):
    if path.suffix.lower() == ".pdf":
        return _pdf_pages(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    # Text files are chunked into pseudo-pages so citations stay compact.
    size = 6000
    return [
        {"page": index // size + 1, "text": text[index:index + size]}
        for index in range(0, max(len(text), 1), size)
    ]


def _cache_path(workspace: Path, path: Path) -> Path:
    stat = path.stat()
    key = hashlib.sha256(f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()
    return workspace / ".egoagent" / "paper_index" / f"{key}.json"


def _load_document(workspace: Path, path: Path):
    cache = _cache_path(workspace, path)
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    pages = _read_pages(path)
    value = {"path": str(path), "title": path.stem, "pages": pages}
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(cache)
    return value


def _terms(query: str):
    ascii_words = re.findall(r"[a-z0-9][a-z0-9_-]+", query.lower())
    chinese = re.findall(r"[\u4e00-\u9fff]{2,}", query)
    grams = []
    for phrase in chinese:
        grams.append(phrase)
        grams.extend(phrase[index:index + 2] for index in range(len(phrase) - 1))
    return list(dict.fromkeys(ascii_words + grams))


def _snippets(document, terms):
    candidates = []
    for page in document["pages"]:
        text = re.sub(r"\s+", " ", page.get("text", "")).strip()
        if not text:
            continue
        lower = text.lower()
        title = document["title"].lower()
        hits = sum(lower.count(term.lower()) for term in terms)
        title_hits = sum(title.count(term.lower()) for term in terms)
        if terms and hits + title_hits == 0:
            continue
        positions = [lower.find(term.lower()) for term in terms if lower.find(term.lower()) >= 0]
        start = max(0, (min(positions) if positions else 0) - 300)
        snippet = text[start:start + 1400]
        candidates.append({
            "score": hits + title_hits * 5,
            "path": document["path"],
            "title": document["title"],
            "page": page.get("page"),
            "snippet": snippet,
        })
    return candidates


def local_paper_search(query: str, root: str = "papers", paper: str = "",
                       top_k: int = 5, max_chars: int = 12000, _context=None):
    context = _context or {}
    workspace_raw = context.get("workspace")
    if not workspace_raw:
        return json.dumps({"ok": False, "error": "This tool requires an Agent workspace."}, ensure_ascii=False)
    workspace = Path(workspace_raw).resolve()
    try:
        papers_root = _safe_root(workspace, root)
        files = sorted(
            path for path in papers_root.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED
            and (not paper or paper.lower() in path.name.lower())
        )
        if not files:
            return json.dumps({"ok": True, "query": query, "papers": [], "matches": [], "note": "No supported papers found."}, ensure_ascii=False)
        if not query.strip():
            return json.dumps({
                "ok": True,
                "root": str(papers_root.relative_to(workspace)),
                "papers": [{"title": path.stem, "path": str(path.relative_to(workspace))} for path in files[:200]],
                "truncated": len(files) > 200,
            }, ensure_ascii=False, indent=2)
        terms = _terms(query)
        matches = []
        failures = []
        for path in files:
            try:
                matches.extend(_snippets(_load_document(workspace, path), terms))
            except Exception as error:
                failures.append({"path": str(path.relative_to(workspace)), "error": str(error)})
        matches.sort(key=lambda item: (-item["score"], item["path"], item["page"] or 0))
        selected = matches[:max(1, min(int(top_k), 20))]
        budget = max(500, min(int(max_chars), 30000))
        rendered = []
        used = 0
        for item in selected:
            snippet = item["snippet"][:max(0, budget - used)]
            if not snippet:
                break
            copy = dict(item)
            copy["path"] = Path(copy["path"]).resolve().relative_to(workspace).as_posix()
            copy["snippet"] = snippet
            rendered.append(copy)
            used += len(snippet)
        return json.dumps({
            "ok": True,
            "query": query,
            "terms": terms,
            "papers_scanned": len(files),
            "matches": rendered,
            "failures": failures[:10],
            "instruction": "Answer from these local snippets and cite path + page. Use the web only if local evidence is insufficient.",
        }, ensure_ascii=False, indent=2)
    except Exception as error:
        return json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False)
