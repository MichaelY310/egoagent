"""Source-backed tool catalog and portable Identity startup selections.

This module is headless. Listing/editing metadata never imports tool code.
Selections configure startup composition, not authorization: normal Superego,
Flow and workspace policies still apply, including to later dynamic activation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import threading
from types import SimpleNamespace

from capability_registry import CapabilityRegistry
from environment import load_tool_from_dir

_SAVE_LOCK = threading.Lock()
_SKILL_ROOTS = (".agents/skills", ".codex/skills")


def _approved(relative: Path, workspace: bool) -> bool:
    p = relative.parts
    if len(p) == 3 and p[:2] in ((".environment", "tools"), ("environment", "tools")):
        return True
    if len(p) == 3 and "/".join(p[:2]) in _SKILL_ROOTS:
        return True
    if workspace:
        return False
    return ((len(p) == 5 and p[0] == "identity" and p[2:4] == ("ego", "skills"))
            or (len(p) == 4 and p[0] == "capability_packs" and p[2] == "skills")
            or (len(p) == 4 and p[0] == "environment" and p[2] == "tools"))


def source_ref(path: Path, root: Path, workspace: Path) -> str:
    path, root, workspace = path.resolve(), root.resolve(), workspace.resolve()
    for prefix, base in (("repo", root), ("workspace", workspace)):
        if path.is_relative_to(base) and _approved(path.relative_to(base), prefix == "workspace"):
            return f"{prefix}:{path.relative_to(base).as_posix()}"
    raise ValueError("Tool source is outside the supported capability directories")


def resolve_source(ref: str, root: Path, workspace: Path) -> Path:
    if not isinstance(ref, str) or ":" not in ref:
        raise ValueError("Invalid capability source reference")
    scope, relative = ref.split(":", 1)
    parts = PurePosixPath(relative)
    if scope not in {"repo", "workspace"} or not relative or "\\" in relative or ":" in relative or parts.is_absolute() or ".." in parts.parts:
        raise ValueError("Invalid capability source reference")
    base = (root if scope == "repo" else workspace).resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base) or not _approved(target.relative_to(base), scope == "workspace"):
        raise ValueError("Capability source escapes an allowed tool directory")
    if not target.is_dir():
        raise ValueError(f"Capability source is missing: {ref}")
    return target


def describe_source(path: Path, root: Path, workspace: Path) -> dict:
    ref = source_ref(path, root, workspace)
    path = resolve_source(ref, root, workspace)
    meta_file = next((p for p in (path / "meta.json", path / "description.json") if p.is_file()), None)
    if meta_file and not meta_file.resolve().is_relative_to(path):
        raise ValueError("Tool metadata escapes its source directory")
    meta = json.loads(meta_file.read_text(encoding="utf-8-sig")) if meta_file else {}
    function = meta.get("function") or meta
    name = str(function.get("name") or path.name)
    script = path / "scripts" / f"{name}.py"
    instructions = path / "SKILL.md"
    has_instructions = instructions.is_file() and instructions.resolve().is_relative_to(path)
    files = []
    candidates = [meta_file, instructions, *sorted((path / "scripts").glob("*"))]
    for file in candidates:
        if file and file.is_file() and file.resolve().is_relative_to(path) and file.suffix.lower() in {".json", ".md", ".py", ".sh", ".js", ".ts"}:
            files.append({"path": str(file.resolve()), "name": file.relative_to(path).as_posix()})
    executable = script.is_file() and script.resolve().is_relative_to(path) and load_tool_from_dir(path) is not None
    usable = executable or has_instructions
    entry = script if executable else instructions if has_instructions else meta_file
    relative = path.relative_to(root) if path.is_relative_to(root) else path.relative_to(workspace)
    p = relative.parts
    source = f"Identity · {p[1]}" if p[0] == "identity" else f"公共能力包 · {p[1]}" if p[0] == "capability_packs" else "当前项目" if ref.startswith("workspace:") else "共享 Environment"
    kind = "skill" if path.parent.name == "skills" else "tool"
    identifier = f"{kind}:" + hashlib.sha256(f"{kind}\0{path}".encode("utf-8")).hexdigest()[:24]
    return {"id": identifier, "kind": kind, "ref": ref, "name": name, "description": str(function.get("description") or ""),
            "type": "tool" if executable else "skill", "source": source,
            "path": str(path), "entry_file": str(entry.resolve()) if entry else None,
            "files": files, "parameters": function.get("parameters", {}), "usable": usable,
            "problem": "" if usable else "缺少可调用的 Python 函数或 SKILL.md，仅可查看源码"}


def catalog(root: Path, workspace: Path, refresh: bool = False) -> list[dict]:
    registry = CapabilityRegistry(root, workspace=workspace)
    if refresh:
        registry.reindex()
    result = []
    for item in registry.list(limit=5000, _deduplicate=False):
        if item["kind"] not in {"tool", "skill"}:
            continue
        try:
            detail = describe_source(Path(item["path"]), root, workspace)
            result.append({**detail, "description": detail["description"] or item["description"],
                           "id": item["id"], "usage_count": item["usage_count"]})
        except (OSError, ValueError, TypeError, KeyError):
            # Do not turn arbitrary registry paths into an editor/file-read API.
            continue
    return sorted(result, key=lambda item: (not item["ref"].startswith("workspace:"), item["name"].casefold(), item["ref"]))


def selection_items(value: object, root: Path, workspace: Path) -> list[dict] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("tools"), list):
        raise ValueError("capability_selection must contain version=1 and a tools list")
    if len(value["tools"]) > 500:
        raise ValueError("At most 500 startup capabilities may be selected")
    items, names = [], set()
    for ref in value["tools"]:
        item = describe_source(resolve_source(ref, root, workspace), root, workspace)
        if not item["usable"]:
            raise ValueError(f"{item['name']}: {item['problem']}")
        if item["name"] in names:
            raise ValueError(f"同名能力只能选择一个来源: {item['name']}")
        names.add(item["name"])
        items.append(item)
    return items


def _identity_file(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or name in {".", ".."} or any(c in name for c in "/\\:"):
        raise ValueError("Invalid Identity name")
    folder = (root / "identity" / name).resolve()
    if not folder.is_relative_to((root / "identity").resolve()) or not (folder / "id.json").is_file():
        raise ValueError("Identity does not exist")
    file = folder / "id.json"
    if not file.resolve().is_relative_to(folder):
        raise ValueError("Identity file escapes its directory")
    return file


def identity_selection(root: Path, workspace: Path, name: str) -> dict:
    file = _identity_file(root, name)
    raw = file.read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    # Mirror Agent's default composition without instantiating an LLM or hooks.
    sources = []
    for inherited in data.get("ego_inherits", []):
        base = root / "capability_packs" / inherited[6:] if inherited.startswith("@pack/") else root / "identity" / inherited / "ego"
        sources.append((base / "skills", False))
    sources.extend([(file.parent / "ego" / "skills", True), (root / ".environment" / "tools", True),
                    (workspace / ".environment" / "tools", True)])
    defaults = {}
    for directory, override in sources:
        if not directory.is_dir():
            continue
        for child in sorted(directory.iterdir()):
            if not child.is_dir():
                continue
            try:
                item = describe_source(child, root, workspace)
                if item["type"] == "tool" and item["usable"] and (override or item["name"] not in defaults):
                    defaults[item["name"]] = item["ref"]
            except (ValueError, OSError, TypeError, KeyError):
                continue
    selection = data.get("capability_selection")
    return {"identity": name, "selection": selection, "defaults": list(defaults.values()),
            "revision": hashlib.sha256(raw).hexdigest()}


def save_identity_selection(root: Path, workspace: Path, name: str, selection: object, revision: str) -> dict:
    selection_items(selection, root, workspace)  # Validate before any write; [] means no tools.
    file = _identity_file(root, name)
    with _SAVE_LOCK:
        raw = file.read_bytes()
        if not revision or hashlib.sha256(raw).hexdigest() != revision:
            raise ValueError("Identity 已被其他编辑器修改，请重新加载后再保存")
        data = json.loads(raw.decode("utf-8-sig"))
        if selection is None:
            data.pop("capability_selection", None)
        else:
            data["capability_selection"] = selection
        fd, temporary = tempfile.mkstemp(prefix=".capabilities-", suffix=".tmp", dir=file.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, file)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return identity_selection(root, workspace, name)


def apply_identity_selection(agent) -> None:
    """Use the same activation path as discovered skills, but with portable refs."""
    root = Path(__file__).resolve().parents[1]
    workspace = Path(agent.workspace or root).resolve()
    items = selection_items(agent.identity.ID.get("capability_selection"), root, workspace)
    if items is None:
        return
    # Validate the complete set before replacing defaults (including workspace
    # pins). This is an explicit startup list, not a security allowlist.
    agent.tools.clear()
    agent._activated_skill_instructions.clear()
    agent._activated_capability_refs.clear()
    agent._capability_snapshot_cache = None
    from capability_reference import digest_capability_source
    for item in items:
        entry = {**item, "scope": "identity-selection",
                 "content_hash": digest_capability_source(Path(item["path"]))}
        source = SimpleNamespace(get=lambda identifier: entry if identifier == entry["id"] else None)
        result = agent.activate_capability(entry["id"], registry=source)
        if not result.get("ok"):
            raise ValueError(result.get("error", "Could not activate selected capability"))
