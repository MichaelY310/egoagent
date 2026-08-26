"""Workspace-safe implementation of the useful Codex apply_patch grammar."""

from __future__ import annotations

import json
import re
from pathlib import Path

from harness_editor.change_tracker import apply_text_change
from permissions import is_sensitive_path


class Section:
    def __init__(self, action: str, path: str):
        self.action = action
        self.path = path
        self.move_to = ""
        self.lines = []


def _parse(raw: str) -> list[Section]:
    lines = str(raw or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0].strip() != "*** Begin Patch":
        raise ValueError("patch must start with '*** Begin Patch'")
    sections: list[Section] = []
    current = None
    ended = False
    for line in lines[1:]:
        if line.strip() == "*** End Patch":
            if current is not None:
                sections.append(current)
            ended = True
            current = None
            break
        header = re.match(r"^\*\*\* (Add|Update|Delete) File: (.+)$", line)
        if header:
            if current is not None:
                sections.append(current)
            current = Section(header.group(1).lower(), header.group(2).strip())
            continue
        if current is None:
            if line.strip():
                raise ValueError(f"unexpected patch line outside a file section: {line[:120]}")
            continue
        move = re.match(r"^\*\*\* Move to: (.+)$", line)
        if move and current.action == "update":
            current.move_to = move.group(1).strip()
        else:
            current.lines.append(line)
    if not ended:
        raise ValueError("patch must end with '*** End Patch'")
    if not sections:
        raise ValueError("patch contains no file sections")
    paths = [item.path for item in sections]
    if len(paths) != len(set(paths)):
        raise ValueError("a file may appear only once in one patch")
    return sections


def _safe_path(workspace: Path, raw: str) -> Path:
    text = str(raw or "").strip().replace("\\", "/")
    if not text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise ValueError(f"patch path must be workspace-relative: {raw!r}")
    path = (workspace / text).resolve()
    try:
        path.relative_to(workspace)
    except ValueError as error:
        raise ValueError(f"patch path escapes workspace: {raw!r}") from error
    if ".git" in {part.lower() for part in path.relative_to(workspace).parts}:
        raise ValueError("patch may not modify .git internals")
    if is_sensitive_path(path):
        raise ValueError(f"patch may not modify a sensitive file: {raw!r}")
    return path


def _read_text(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            return stream.read()
    except UnicodeDecodeError as error:
        raise ValueError(f"cannot patch binary/non-UTF-8 file: {path}") from error


def _line_ending(content: str) -> str:
    crlf = content.count("\r\n")
    lf = content.count("\n") - crlf
    cr = content.count("\r") - crlf
    if crlf >= max(lf, cr) and crlf:
        return "\r\n"
    return "\r" if cr > lf else "\n"


def _apply_update(content: str, patch_lines: list[str], path: str) -> tuple[str, int]:
    newline = _line_ending(content)
    ended = content.endswith(("\n", "\r"))
    source = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if ended:
        source = source[:-1]
    hunks: list[tuple[str, list[str]]] = []
    header = "@@"
    body: list[str] = []
    for line in patch_lines:
        if line.startswith("@@"):
            if body:
                hunks.append((header, body))
            header, body = line, []
        elif line == "\\ No newline at end of file":
            continue
        else:
            body.append(line)
    if body:
        hunks.append((header, body))
    if not hunks:
        raise ValueError(f"Update File section has no hunks: {path}")
    applied = 0
    offset = 0
    for hunk_header, hunk in hunks:
        invalid = [line for line in hunk if not line or line[0] not in {" ", "+", "-"}]
        if invalid:
            raise ValueError(f"invalid hunk line in {path}: {invalid[0][:120]!r}")
        old = [line[1:] for line in hunk if line[0] in {" ", "-"}]
        new = [line[1:] for line in hunk if line[0] in {" ", "+"}]
        start_hint = None
        match = re.search(r"-(\d+)", hunk_header)
        if match:
            start_hint = max(0, int(match.group(1)) - 1 + offset)
        candidates = []
        if old:
            width = len(old)
            for index in range(0, len(source) - width + 1):
                if source[index:index + width] == old:
                    candidates.append(index)
        else:
            candidates = [min(len(source), start_hint if start_hint is not None else len(source))]
        if not candidates:
            preview = "\n".join(old[:8])
            raise ValueError(f"hunk context not found in {path}:\n{preview}")
        index = min(candidates, key=lambda value: abs(value - start_hint)) if start_hint is not None else candidates[0]
        source[index:index + len(old)] = new
        offset += len(new) - len(old)
        applied += 1
    result = newline.join(source)
    if ended:
        result += newline
    return result, applied


def _prepare(sections: list[Section], workspace: Path):
    prepared = []
    occupied = set()
    for section in sections:
        source = _safe_path(workspace, section.path)
        if source in occupied:
            raise ValueError(f"duplicate patch target: {section.path}")
        occupied.add(source)
        if section.action == "add":
            if source.exists():
                raise ValueError(f"Add File target already exists: {section.path}")
            invalid = [line for line in section.lines if line and not line.startswith("+")]
            if invalid:
                raise ValueError(f"Add File lines must start with '+': {invalid[0][:120]!r}")
            new = "\n".join(line[1:] if line.startswith("+") else "" for line in section.lines)
            # split() retains one sentinel empty line before End Patch.
            if section.lines and section.lines[-1] == "":
                new = new[:-1] if new.endswith("\n") else new
            prepared.append((source, None, new, section.path, 1))
        elif section.action == "delete":
            if not source.is_file():
                raise ValueError(f"Delete File target not found: {section.path}")
            prepared.append((source, _read_text(source), None, section.path, 1))
        else:
            if not source.is_file():
                raise ValueError(f"Update File target not found: {section.path}")
            old = _read_text(source)
            new, count = _apply_update(old, section.lines, section.path)
            if section.move_to:
                destination = _safe_path(workspace, section.move_to)
                if destination.exists() or destination in occupied:
                    raise ValueError(f"Move destination already exists: {section.move_to}")
                occupied.add(destination)
                prepared.append((destination, None, new, section.move_to, count))
                prepared.append((source, old, None, section.path, 0))
            else:
                prepared.append((source, old, new, section.path, count))
    return prepared


def apply_patch(patch: str, _context: dict = None):
    context = _context or {}
    workspace_value = context.get("workspace")
    if not workspace_value:
        return json.dumps({"ok": False, "error": "workspace is unavailable"})
    workspace = Path(str(workspace_value)).resolve()
    try:
        prepared = _prepare(_parse(patch), workspace)
        applied = []
        snapshots = []
        try:
            for path, old, new, display, hunk_count in prepared:
                apply_text_change(path, old, new, "apply_patch")
                snapshots.append((path, old))
                applied.append({"path": display, "action": "delete" if new is None else "write", "hunks": hunk_count})
        except Exception:
            # Best-effort rollback keeps a multi-file patch from leaving a
            # half-applied workspace if the filesystem changes mid-commit.
            for path, old in reversed(snapshots):
                if old is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("w", encoding="utf-8", newline="") as stream:
                        stream.write(old)
            raise
        return json.dumps({"ok": True, "status": "applied", "files": applied}, ensure_ascii=False)
    except (OSError, ValueError) as error:
        return json.dumps({"ok": False, "status": "rejected", "error": str(error)}, ensure_ascii=False)
