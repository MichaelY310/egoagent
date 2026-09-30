"""Durable, concurrency-safe, per-hunk transactions for Agent file edits.

Agent edits are applied before they are recorded.  This module therefore acts
as a review journal, not a staging area: accepting a hunk only records the
decision, while rejecting it materializes the corresponding base text.  Every
mutation is written atomically so review state survives backend/IDE restarts.
"""

from __future__ import annotations

import contextvars
import base64
import difflib
import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_STORE = _ROOT / ".egoagent" / "change-transactions.json"
_STORE_VERSION = 2
_changes: list[dict] = []
_next_index = 0
_loaded = False
_store_path = Path(os.environ.get("EGOAGENT_CHANGE_STORE", str(_DEFAULT_STORE))).resolve()
_lock = threading.RLock()
_active_transaction: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "egoagent_change_transaction", default=None
)
_last_operation_error: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "egoagent_change_error", default=None
)


def begin_transaction(transaction_id=None):
    """Start a change transaction in the current execution context."""
    identifier = str(transaction_id or uuid.uuid4().hex)
    _active_transaction.set(identifier)
    return identifier


def end_transaction(transaction_id=None):
    """Clear the current transaction if it matches the requested ID."""
    current = _active_transaction.get()
    if transaction_id is None or current == str(transaction_id):
        _active_transaction.set(None)
        return True
    return False


def get_active_transaction():
    return _active_transaction.get()


@contextmanager
def transaction_scope(transaction_id):
    """Bind a transaction and restore the exact outer transaction on exit."""
    identifier = str(transaction_id or uuid.uuid4().hex)
    token = _active_transaction.set(identifier)
    try:
        yield identifier
    finally:
        _active_transaction.reset(token)


def configure_store(path=None, *, load=True):
    """Select a journal path (primarily useful for isolated tests).

    Passing ``None`` restores the environment/default path. Existing in-memory
    entries are discarded and the selected journal is loaded on demand.
    """
    global _store_path, _loaded, _next_index
    with _lock:
        configured = path or os.environ.get("EGOAGENT_CHANGE_STORE") or _DEFAULT_STORE
        _store_path = Path(configured).resolve()
        _changes.clear()
        _next_index = 0
        _loaded = False
        if load:
            _ensure_loaded_locked()
    return str(_store_path)


def reload_store():
    """Reload review state from disk, simulating a fresh backend process."""
    global _loaded, _next_index
    with _lock:
        _changes.clear()
        _next_index = 0
        _loaded = False
        _ensure_loaded_locked()
        return len(_changes)


def get_last_operation_error():
    """Return the structured reason for the latest failed operation."""
    value = _last_operation_error.get()
    return dict(value) if isinstance(value, dict) else value


def record_change(file_path, old_content, new_content, tool_name, transaction_id=None):
    """Record one independently reviewable text edit that is already live."""
    global _next_index
    transaction_id = str(transaction_id or _active_transaction.get() or "unscoped")
    normalized_path = str(Path(file_path).resolve())
    with _lock:
        _ensure_loaded_locked()
        _clear_error()
        # Localized edit tools must not silently rewrite every line ending.
        # Enforce this at the central review boundary as imported third-party
        # skills may use platform-default text mode even when built-in tools do
        # not. Full-file write_file remains free to intentionally change style.
        if (
            tool_name in {"patch_file", "multi_edit"}
            and old_content is not None
            and new_content is not None
        ):
            new_content = _preserve_line_endings(old_content, new_content)

        # On Windows, text-mode writers may materialize ``\n`` as ``\r\n``.
        # Journal the exact live representation when it respects the expected
        # line-ending style; otherwise normalize the live file before review.
        if new_content is not None and Path(normalized_path).is_file():
            try:
                live_content = _read_text_exact(Path(normalized_path))
            except (OSError, UnicodeError):
                live_content = new_content
            if _normalized_newlines(live_content) == _normalized_newlines(new_content):
                if tool_name in {"patch_file", "multi_edit"} and live_content != new_content:
                    try:
                        _write_text_exact(Path(normalized_path), new_content)
                        live_content = new_content
                    except (OSError, UnicodeError):
                        pass
                if live_content == new_content or tool_name not in {"patch_file", "multi_edit"}:
                    new_content = live_content

        # Several tools record internally while Agent.execute_tool_call records
        # around the same call. Collapse that exact duplicate.
        if _changes:
            previous = _changes[-1]
            if (
                previous["transaction_id"] == transaction_id
                and previous["file_path"] == normalized_path
                and previous.get("old_content") == old_content
                and previous.get("new_content") == new_content
                and previous["status"] in {"pending", "partial"}
            ):
                return previous["index"]

        # Consecutive edits to the same file in one run are shown as one clean
        # base -> final proposal. This avoids stale intermediate transactions
        # fighting over the same materialized file.
        previous = next(
            (
                item
                for item in reversed(_changes)
                if item["transaction_id"] == transaction_id
                and item["file_path"] == normalized_path
            ),
            None,
        )
        if (
            previous
            and _normalized_newlines(previous.get("last_materialized_content")) == _normalized_newlines(old_content)
            and all(hunk.get("status") == "pending" for hunk in previous.get("hunks", []))
        ):
            previous["new_content"] = new_content
            previous["last_materialized_content"] = new_content
            previous["materialized_revision"] = _content_revision(new_content)
            previous["proposed_revision"] = _content_revision(new_content)
            previous["is_deleted_file"] = new_content is None and previous.get("old_content") is not None
            previous["tool_name"] = tool_name
            previous["updated_at"] = time.time()
            previous["hunks"] = _compute_hunks(
                previous.get("old_content"), new_content, previous["id"],
                preserve_line_endings=tool_name in {"patch_file", "multi_edit"},
            )
            previous["status"] = "pending"
            previous["conflict"] = None
            _save_locked()
            return previous["index"]

        change_id = uuid.uuid4().hex
        now = time.time()
        entry = {
            "id": change_id,
            "index": _next_index,
            "transaction_id": transaction_id,
            "file_path": normalized_path,
            "change_type": "text",
            "old_content": old_content,
            "new_content": new_content,
            "is_new_file": old_content is None,
            "is_deleted_file": new_content is None and old_content is not None,
            "last_materialized_content": new_content,
            "base_revision": _content_revision(old_content),
            "proposed_revision": _content_revision(new_content),
            "materialized_revision": _content_revision(new_content),
            "timestamp": now,
            "updated_at": now,
            "tool_name": tool_name,
            "status": "pending",
            "reject_reason": None,
            "conflict": None,
            "hunks": _compute_hunks(
                old_content, new_content, change_id,
                preserve_line_endings=tool_name in {"patch_file", "multi_edit"},
            ),
        }
        _next_index += 1
        _changes.append(entry)
        _save_locked()
        return entry["index"]


def apply_text_change(file_path, expected_content, new_content, tool_name, transaction_id=None):
    """Revision-check, atomically materialize, and journal one text edit.

    This is the product-facing entry point for IDE edits.  The caller provides
    the exact text it observed; a newer manual edit turns into a structured
    conflict instead of being overwritten.
    """
    path = Path(file_path).resolve()
    if expected_content is not None and not isinstance(expected_content, str):
        _fail("invalid_content", "expected_content must be text or null")
        return None
    if new_content is not None and not isinstance(new_content, str):
        _fail("invalid_content", "new_content must be text or null")
        return None

    with _lock:
        _ensure_loaded_locked()
        _clear_error()
        try:
            current = _read_text_exact(path) if path.is_file() else None
        except (OSError, UnicodeError) as exc:
            _fail("read_failed", f"Could not inspect the current file: {exc}", file_path=str(path))
            return None
        if current != expected_content:
            if _normalized_newlines(current) == _normalized_newlines(expected_content):
                # Python/VS Code may materialize the document's configured EOL
                # while the request transports canonical ``\n``.  Preserve the
                # exact on-disk base without treating that representation-only
                # difference as a user edit.
                expected_content = current
            else:
                _fail(
                    "revision_conflict",
                    "The file changed after the edit request was created",
                    file_path=str(path),
                    expected_revision=_content_revision(expected_content),
                    current_revision=_content_revision(current),
                )
                return None

        temporary = path.with_name(f".{path.name}.egoagent-{uuid.uuid4().hex}.tmp")
        try:
            if new_content is None:
                if path.exists():
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                _write_text_exact(temporary, new_content)
                os.replace(temporary, path)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            _fail("write_failed", f"Could not apply the text edit: {exc}", file_path=str(path))
            return None

        return record_change(
            path,
            expected_content,
            new_content,
            tool_name,
            transaction_id=transaction_id,
        )


def record_binary_change(file_path, old_bytes, new_bytes, tool_name, transaction_id=None):
    """Record an already-applied binary create/update/delete as one whole-file hunk."""
    global _next_index
    if old_bytes is not None and not isinstance(old_bytes, bytes):
        old_bytes = bytes(old_bytes)
    if new_bytes is not None and not isinstance(new_bytes, bytes):
        new_bytes = bytes(new_bytes)
    transaction_id = str(transaction_id or _active_transaction.get() or "unscoped")
    normalized_path = str(Path(file_path).resolve())
    with _lock:
        _ensure_loaded_locked()
        _clear_error()
        change_id = uuid.uuid4().hex
        now = time.time()
        entry = {
            "id": change_id,
            "index": _next_index,
            "transaction_id": transaction_id,
            "file_path": normalized_path,
            "change_type": "binary",
            "old_content": None,
            "new_content": None,
            "old_binary": _encode_binary(old_bytes),
            "new_binary": _encode_binary(new_bytes),
            "last_materialized_binary": _encode_binary(new_bytes),
            "is_new_file": old_bytes is None,
            "is_deleted_file": new_bytes is None and old_bytes is not None,
            "base_revision": _content_revision(old_bytes),
            "proposed_revision": _content_revision(new_bytes),
            "materialized_revision": _content_revision(new_bytes),
            "timestamp": now,
            "updated_at": now,
            "tool_name": tool_name,
            "status": "pending",
            "reject_reason": None,
            "conflict": None,
            "hunks": [_whole_file_hunk(change_id, "binary")],
        }
        _next_index += 1
        _changes.append(entry)
        _save_locked()
        return entry["index"]


def record_move(source_path, target_path, tool_name="move", transaction_id=None):
    """Record an already-completed same-workspace file move/rename."""
    global _next_index
    source = Path(source_path).resolve()
    target = Path(target_path).resolve()
    if source == target:
        raise ValueError("move source and target must differ")
    if source.exists() or not target.is_file():
        raise ValueError("record_move expects the source to be absent and target file to exist")
    try:
        payload = target.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot inspect moved file: {exc}") from exc
    transaction_id = str(transaction_id or _active_transaction.get() or "unscoped")
    with _lock:
        _ensure_loaded_locked()
        _clear_error()
        change_id = uuid.uuid4().hex
        now = time.time()
        entry = {
            "id": change_id,
            "index": _next_index,
            "transaction_id": transaction_id,
            "file_path": str(target),
            "source_path": str(source),
            "change_type": "move",
            "old_content": None,
            "new_content": None,
            "is_new_file": False,
            "is_deleted_file": False,
            "base_revision": _content_revision(payload),
            "proposed_revision": _content_revision(payload),
            "materialized_revision": _content_revision(payload),
            "last_materialized_state": "target",
            "timestamp": now,
            "updated_at": now,
            "tool_name": tool_name,
            "status": "pending",
            "reject_reason": None,
            "conflict": None,
            "hunks": [_whole_file_hunk(change_id, "move")],
        }
        _next_index += 1
        _changes.append(entry)
        _save_locked()
        return entry["index"]


def get_changes(
    transaction_id=None,
    workspace=None,
    *,
    live_only=False,
    exclude_internal=False,
):
    """Return serializable summaries, optionally scoped before expensive diff work.

    ``live_only`` hides journal entries whose materialized file no longer
    exists (usually an already-removed test/background artifact).  A tracked
    file deletion is the exception: its missing target is the proposed state
    and remains reviewable while its containing directory exists.
    ``exclude_internal`` keeps child Task Bench sandboxes out of a parent
    workspace's interactive review list.  Both switches are presentation
    filters only; the durable audit journal is never deleted.
    """
    expected = None if transaction_id is None else str(transaction_id)
    workspace_root = None
    if workspace:
        try:
            workspace_root = os.path.normcase(os.path.abspath(str(workspace)))
        except (OSError, ValueError):
            workspace_root = None

    def belongs_to_workspace(change):
        if workspace_root is None:
            return True
        for candidate in (change.get("file_path"), change.get("source_path")):
            if not candidate:
                continue
            try:
                candidate_path = os.path.normcase(os.path.abspath(candidate))
                if os.path.commonpath((workspace_root, candidate_path)) == workspace_root:
                    return True
            except (OSError, ValueError):
                continue
        return False

    def is_live_change(change):
        if not live_only:
            return True
        is_tracked_deletion = bool(change.get("is_deleted_file")) or change.get("change_type") == "delete"
        for candidate in (change.get("file_path"), change.get("source_path")):
            if not candidate:
                continue
            try:
                path = Path(candidate).resolve()
                if path.is_file() or (is_tracked_deletion and path.parent.is_dir()):
                    return True
            except (OSError, ValueError):
                continue
        return False

    def is_internal_child_run(change):
        if not exclude_internal or workspace_root is None:
            return False
        internal_root = os.path.normcase(
            os.path.abspath(os.path.join(workspace_root, ".egoagent", "task_runs"))
        )
        for candidate in (change.get("file_path"), change.get("source_path")):
            if not candidate:
                continue
            try:
                candidate_path = os.path.normcase(os.path.abspath(candidate))
                if os.path.commonpath((internal_root, candidate_path)) == internal_root:
                    return True
            except (OSError, ValueError):
                continue
        return False

    with _lock:
        _ensure_loaded_locked()
        result = []
        for change in _changes:
            if expected is not None and change["transaction_id"] != expected:
                continue
            if not belongs_to_workspace(change):
                continue
            if not is_live_change(change) or is_internal_child_run(change):
                continue
            result.append(
                {
                    "id": change["id"],
                    "index": change["index"],
                    "transaction_id": change["transaction_id"],
                    "file_path": change["file_path"],
                    "source_path": change.get("source_path"),
                    "change_type": change.get("change_type", "text"),
                    "timestamp": change["timestamp"],
                    "updated_at": change.get("updated_at", change["timestamp"]),
                    "tool_name": change["tool_name"],
                    "status": change["status"],
                    "reject_reason": change.get("reject_reason"),
                    "conflict": change.get("conflict"),
                    "is_new_file": bool(change.get("is_new_file")),
                    "is_deleted_file": bool(change.get("is_deleted_file")),
                    "file_exists": Path(change["file_path"]).is_file(),
                    "materialized_path": _materialized_path(change),
                    "base_revision": change.get("base_revision"),
                    "proposed_revision": change.get("proposed_revision"),
                    "materialized_revision": change.get("materialized_revision"),
                    "diff": compute_diff(
                        change.get("old_content") or "", change.get("new_content") or "",
                        preserve_line_endings=change.get("tool_name") in {"patch_file", "multi_edit"},
                    ) if change.get("change_type", "text") == "text" else [],
                    "old_size": _entry_payload_size(change, "old"),
                    "new_size": _entry_payload_size(change, "new"),
                    "hunks": [
                        {
                            **{
                                key: value
                                for key, value in hunk.items()
                                if key != "decision_history"
                            },
                            "can_undo": bool(hunk.get("decision_history")),
                            "decision_count": len(hunk.get("decision_history", [])),
                        }
                        for hunk in change.get("hunks", [])
                    ],
                }
            )
        return result


def get_change_content(selector):
    """Return the exact immutable before/after payload for one review entry.

    The list API intentionally omits full files. Native diff editors request
    this detail lazily so historical transactions never have to reconstruct a
    base from whatever happens to be on disk today.
    """
    with _lock:
        _ensure_loaded_locked()
        entry = _entry(selector)
        if entry is None:
            return None
        if entry.get("change_type", "text") != "text":
            return {
                "id": entry.get("id"),
                "index": entry.get("index"),
                "transaction_id": entry.get("transaction_id"),
                "change_type": entry.get("change_type"),
                "file_path": entry.get("file_path"),
                "old_content": None,
                "new_content": None,
            }
        return {
            "id": entry.get("id"),
            "index": entry.get("index"),
            "transaction_id": entry.get("transaction_id"),
            "change_type": "text",
            "file_path": entry.get("file_path"),
            "old_content": entry.get("old_content"),
            "new_content": entry.get("new_content"),
            "base_revision": entry.get("base_revision"),
            "proposed_revision": entry.get("proposed_revision"),
        }


def get_transaction_summary(transaction_id):
    changes = get_changes(transaction_id)
    hunks = [hunk for change in changes for hunk in change.get("hunks", [])]
    counts = {
        "pending": sum(hunk["status"] == "pending" for hunk in hunks),
        "accepted": sum(hunk["status"] == "accepted" for hunk in hunks),
        "rejected": sum(hunk["status"] == "rejected" for hunk in hunks),
    }
    if any(change.get("status") == "conflict" for change in changes):
        status = "conflict"
    elif counts["pending"]:
        status = "pending"
    elif counts["rejected"] and counts["accepted"]:
        status = "partial"
    elif counts["rejected"]:
        status = "rejected"
    else:
        status = "accepted"
    return {
        "transaction_id": str(transaction_id),
        "status": status,
        "files": len(changes),
        "hunks": len(hunks),
        **counts,
        "changes": changes,
    }


def accept_change(selector, hunk_id=None):
    with _lock:
        _ensure_loaded_locked()
        _clear_error()
        entry = _entry(selector)
        if entry is None:
            return _fail("not_found", "Change transaction was not found")
        if not _verify_materialized(entry):
            return False
        if hunk_id is None:
            targets = [h for h in entry.get("hunks", []) if h["status"] == "pending"]
        else:
            hunk = _get_hunk(entry, hunk_id)
            targets = [hunk] if hunk is not None and hunk["status"] == "pending" else []
        if not targets:
            return _fail("not_pending", "The selected hunk is not pending")
        for hunk in targets:
            _remember_decision(hunk, "accept")
            hunk["status"] = "accepted"
            hunk["reject_reason"] = None
        entry["conflict"] = None
        _refresh_entry_status(entry)
        _save_locked()
        return True


def reject_change(selector, reason=None, hunk_id=None, *, confirm_delete=False):
    with _lock:
        _ensure_loaded_locked()
        _clear_error()
        entry = _entry(selector)
        if entry is None:
            return _fail("not_found", "Change transaction was not found")
        if hunk_id is None:
            targets = [h for h in entry.get("hunks", []) if h["status"] in {"pending", "accepted"}]
        else:
            hunk = _get_hunk(entry, hunk_id)
            targets = [hunk] if hunk is not None and hunk["status"] == "pending" else []
        if not targets:
            return _fail("not_pending", "The selected hunk cannot be rejected")
        if not _verify_materialized(entry):
            return False

        previous = [(h, h["status"], h.get("reject_reason"), len(h.get("decision_history", []))) for h in targets]
        for hunk, *_ in previous:
            _remember_decision(hunk, "reject")
            hunk["status"] = "rejected"
            hunk["reject_reason"] = reason
        desired = _desired_entry_content(entry)
        if desired is None and entry.get("is_new_file") and not confirm_delete:
            _restore_hunk_mutations(previous)
            return _fail(
                "delete_confirmation_required",
                "Rejecting this new-file change would delete the file",
                file_path=entry["file_path"],
            )
        entry["reject_reason"] = reason
        if not _materialize_entry(entry, desired=desired):
            _restore_hunk_mutations(previous)
            return False
        entry["conflict"] = None
        _refresh_entry_status(entry)
        _save_locked()
        return True


def undo_change(selector, hunk_id=None):
    """Undo review decisions without undoing the Agent's original edit."""
    with _lock:
        _ensure_loaded_locked()
        _clear_error()
        entry = _entry(selector)
        if entry is None:
            return _fail("not_found", "Change transaction was not found")
        if hunk_id is None:
            targets = [h for h in entry.get("hunks", []) if h.get("decision_history")]
        else:
            hunk = _get_hunk(entry, hunk_id)
            targets = [hunk] if hunk is not None and hunk.get("decision_history") else []
        if not targets:
            return _fail("nothing_to_undo", "No review decision can be undone")
        if not _verify_materialized(entry):
            return False

        previous = [(h, h["status"], h.get("reject_reason")) for h in targets]
        decisions = [h["decision_history"][-1] for h in targets]
        for hunk, decision in zip(targets, decisions):
            hunk["status"] = decision.get("status", "pending")
            hunk["reject_reason"] = decision.get("reject_reason")
        if not _materialize_entry(entry):
            for hunk, status, old_reason in previous:
                hunk["status"] = status
                hunk["reject_reason"] = old_reason
            return False
        for hunk in targets:
            hunk["decision_history"].pop()
        entry["conflict"] = None
        _refresh_entry_status(entry)
        _save_locked()
        return True


def resolve_transaction(transaction_id, decision, reason=None, *, confirm_delete=False):
    """Resolve only still-pending hunks in one transaction."""
    decision = str(decision).lower()
    if decision not in {"accept", "accepted", "reject", "rejected"}:
        raise ValueError("decision must be accept or reject")
    accepted = decision.startswith("accept")
    resolved = 0
    for change in get_changes(transaction_id):
        for hunk in change.get("hunks", []):
            if hunk["status"] != "pending":
                continue
            if accepted:
                ok = accept_change(change["id"], hunk["id"])
            else:
                ok = reject_change(
                    change["id"], reason, hunk["id"], confirm_delete=confirm_delete
                )
            resolved += int(ok)
    return resolved


def revert_all(transaction_id=None, *, confirm_delete=False):
    expected = None if transaction_id is None else str(transaction_id)
    count = 0
    with _lock:
        _ensure_loaded_locked()
        selectors = [
            entry["id"]
            for entry in reversed(_changes)
            if (expected is None or entry["transaction_id"] == expected)
            and entry["status"] in {"pending", "partial", "accepted"}
        ]
    for selector in selectors:
        if reject_change(selector, "revert_all", confirm_delete=confirm_delete):
            count += 1
    return count


def clear_changes(transaction_id=None):
    global _next_index
    expected = None if transaction_id is None else str(transaction_id)
    with _lock:
        _ensure_loaded_locked()
        if expected is None:
            _changes.clear()
            _next_index = 0
        else:
            _changes[:] = [c for c in _changes if c["transaction_id"] != expected]
        _save_locked()


def clear_workspace_changes(workspace):
    """Forget review records inside one workspace without touching its files."""

    workspace_root = os.path.normcase(os.path.abspath(str(Path(workspace).resolve())))

    def belongs_to_workspace(change):
        for candidate in (change.get("file_path"), change.get("source_path")):
            if not candidate:
                continue
            try:
                candidate_path = os.path.normcase(os.path.abspath(candidate))
                if os.path.commonpath((workspace_root, candidate_path)) == workspace_root:
                    return True
            except (OSError, ValueError):
                continue
        return False

    with _lock:
        _ensure_loaded_locked()
        before = len(_changes)
        _changes[:] = [change for change in _changes if not belongs_to_workspace(change)]
        removed = before - len(_changes)
        if removed:
            _save_locked()
        return removed


def compute_diff(old_content, new_content, *, preserve_line_endings=False):
    if preserve_line_endings and old_content is not None and new_content is not None:
        new_content = _preserve_line_endings(old_content, new_content)
    old_lines = (old_content or "").splitlines(keepends=True)
    new_lines = (new_content or "").splitlines(keepends=True)
    return list(difflib.unified_diff(old_lines, new_lines, fromfile="before", tofile="after", lineterm=""))


def _compute_hunks(old_content, new_content, change_id, *, preserve_line_endings=False):
    if preserve_line_endings and old_content is not None and new_content is not None:
        new_content = _preserve_line_endings(old_content, new_content)
    old_lines = (old_content or "").splitlines(keepends=True)
    new_lines = (new_content or "").splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    hunks = []
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        fingerprint = "\0".join(
            [tag, str(old_start), str(old_end), str(new_start), str(new_end), *old_lines[old_start:old_end], *new_lines[new_start:new_end]]
        )
        hunks.append(
            {
                "id": uuid.uuid5(uuid.NAMESPACE_URL, f"egoagent:{change_id}:{fingerprint}").hex,
                "ordinal": len(hunks),
                "tag": tag,
                "old_start": old_start,
                "old_count": old_end - old_start,
                "new_start": new_start,
                "new_count": new_end - new_start,
                "old_lines": old_lines[old_start:old_end],
                "new_lines": new_lines[new_start:new_end],
                "status": "pending",
                "reject_reason": None,
                "decision_history": [],
            }
        )
    # File existence is itself reviewable even when both contents are empty.
    if not hunks and (old_content is None) != (new_content is None):
        hunks.append(
            {
                "id": uuid.uuid5(uuid.NAMESPACE_URL, f"egoagent:{change_id}:file-state").hex,
                "ordinal": 0,
                "tag": "file_state",
                "old_start": 0,
                "old_count": 0,
                "new_start": 0,
                "new_count": 0,
                "old_lines": [],
                "new_lines": [],
                "status": "pending",
                "reject_reason": None,
                "decision_history": [],
            }
        )
    return hunks


def _whole_file_hunk(change_id, tag):
    return {
        "id": uuid.uuid5(uuid.NAMESPACE_URL, f"egoagent:{change_id}:{tag}").hex,
        "ordinal": 0,
        "tag": tag,
        "old_start": 0,
        "old_count": 0,
        "new_start": 0,
        "new_count": 0,
        "old_lines": [],
        "new_lines": [],
        "status": "pending",
        "reject_reason": None,
        "decision_history": [],
    }


def _entry(selector):
    if selector is None:
        return None
    text = str(selector)
    for change in _changes:
        if change.get("id") == text:
            return change
    try:
        expected = int(selector)
    except (TypeError, ValueError):
        return None
    return next((change for change in _changes if change["index"] == expected), None)


def _get_hunk(entry, hunk_id):
    if hunk_id is None:
        return None
    text = str(hunk_id)
    for hunk in entry.get("hunks", []):
        if str(hunk.get("id")) == text:
            return hunk
    try:
        ordinal = int(hunk_id)
    except (TypeError, ValueError):
        return None
    return next((h for h in entry.get("hunks", []) if h.get("ordinal") == ordinal), None)


def _refresh_entry_status(entry):
    statuses = [hunk["status"] for hunk in entry.get("hunks", [])]
    if not statuses or all(status == "accepted" for status in statuses):
        entry["status"] = "accepted"
    elif all(status == "rejected" for status in statuses):
        entry["status"] = "rejected"
    elif all(status == "pending" for status in statuses):
        entry["status"] = "pending"
    else:
        entry["status"] = "partial"
    entry["updated_at"] = time.time()


def _remember_decision(hunk, action):
    hunk.setdefault("decision_history", []).append(
        {
            "status": hunk.get("status", "pending"),
            "reject_reason": hunk.get("reject_reason"),
            "action": action,
            "timestamp": time.time(),
        }
    )


def _desired_entry_content(entry):
    change_type = entry.get("change_type", "text")
    if change_type == "move":
        return "source" if all(h["status"] == "rejected" for h in entry.get("hunks", [])) else "target"
    if change_type == "binary":
        rejected = all(h["status"] == "rejected" for h in entry.get("hunks", []))
        return _decode_binary(entry.get("old_binary") if rejected else entry.get("new_binary"))
    old_lines = (entry.get("old_content") or "").splitlines(keepends=True)
    output = []
    cursor = 0
    for hunk in entry.get("hunks", []):
        start = hunk["old_start"]
        end = start + hunk["old_count"]
        output.extend(old_lines[cursor:start])
        output.extend(hunk["old_lines"] if hunk["status"] == "rejected" else hunk["new_lines"])
        cursor = end
    output.extend(old_lines[cursor:])
    if entry.get("is_new_file") and all(h["status"] == "rejected" for h in entry.get("hunks", [])):
        return None
    if entry.get("is_deleted_file") and not any(h["status"] == "rejected" for h in entry.get("hunks", [])):
        return None
    return "".join(output)


def _read_current(entry):
    path = Path(entry["file_path"])
    try:
        if entry.get("change_type") == "binary":
            return path.read_bytes() if path.is_file() else None
        return _read_text_exact(path) if path.is_file() else None
    except (OSError, UnicodeError) as exc:
        _fail("read_failed", f"Could not read the file under review: {exc}", file_path=str(path))
        return _READ_FAILED


def _verify_materialized(entry):
    if entry.get("change_type") == "move":
        return _verify_move(entry)
    current = _read_current(entry)
    if current is _READ_FAILED:
        return False
    expected = (
        _decode_binary(entry.get("last_materialized_binary"))
        if entry.get("change_type") == "binary"
        else entry.get("last_materialized_content")
    )
    if current != expected:
        conflict = {
            "code": "revision_conflict",
            "message": "文件在本次 Agent 改动后又被其他操作修改；为保护较新的内容，本次审阅不会自动覆盖文件",
            "file_path": entry["file_path"],
            "expected_revision": _content_revision(expected),
            "current_revision": _content_revision(current),
            "detected_at": time.time(),
        }
        entry["conflict"] = conflict
        entry["status"] = "conflict"
        entry["updated_at"] = time.time()
        _last_operation_error.set(conflict)
        _save_locked()
        return False
    return True


def _materialize_entry(entry, *, desired=None):
    if entry.get("change_type") == "move":
        return _materialize_move(entry, desired or _desired_entry_content(entry))
    if desired is None and not (
        entry.get("is_new_file") or entry.get("is_deleted_file")
    ):
        desired = _desired_entry_content(entry)
    elif desired is None:
        desired = _desired_entry_content(entry)
    last_materialized = (
        _decode_binary(entry.get("last_materialized_binary"))
        if entry.get("change_type") == "binary"
        else entry.get("last_materialized_content")
    )
    if desired == last_materialized:
        return True
    if not _verify_materialized(entry):
        return False
    path = Path(entry["file_path"])
    try:
        if desired is None:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            if entry.get("change_type") == "binary":
                path.write_bytes(desired)
            else:
                _write_text_exact(path, desired)
    except (OSError, UnicodeError) as exc:
        return _fail("write_failed", f"Could not materialize review decision: {exc}", file_path=str(path))
    if entry.get("change_type") == "binary":
        entry["last_materialized_binary"] = _encode_binary(desired)
    else:
        entry["last_materialized_content"] = desired
    entry["materialized_revision"] = _content_revision(desired)
    entry["updated_at"] = time.time()
    return True


def _restore_hunk_mutations(previous):
    for hunk, status, reason, history_length in previous:
        hunk["status"] = status
        hunk["reject_reason"] = reason
        del hunk.setdefault("decision_history", [])[history_length:]


def _content_revision(content):
    if content is None:
        return "missing"
    encoded = content if isinstance(content, bytes) else str(content).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _normalized_newlines(content):
    if content is None:
        return None
    return str(content).replace("\r\n", "\n").replace("\r", "\n")


def _preserve_line_endings(before, after):
    if not before or not after:
        return after
    crlf = before.count("\r\n")
    bare_lf = before.count("\n") - crlf
    bare_cr = before.count("\r") - crlf
    if crlf == bare_lf == bare_cr == 0:
        return after
    newline = "\r\n" if crlf >= max(bare_lf, bare_cr) and crlf > 0 else ("\r" if bare_cr > bare_lf else "\n")
    logical = _normalized_newlines(after)
    return logical if newline == "\n" else logical.replace("\n", newline)


def _read_text_exact(path):
    with path.open("r", encoding="utf-8", newline="") as stream:
        return stream.read()


def _write_text_exact(path, content):
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write(content)


def _encode_binary(content):
    return None if content is None else base64.b64encode(content).decode("ascii")


def _decode_binary(content):
    return None if content is None else base64.b64decode(content.encode("ascii"))


def _entry_payload_size(entry, side):
    if entry.get("change_type") == "binary":
        value = _decode_binary(entry.get(f"{side}_binary"))
        return None if value is None else len(value)
    if entry.get("change_type") == "move":
        return None
    value = entry.get(f"{side}_content")
    return None if value is None else len(value.encode("utf-8"))


def _materialized_path(entry):
    if entry.get("change_type") == "move" and entry.get("last_materialized_state") == "source":
        return entry.get("source_path")
    return entry.get("file_path")


def _verify_move(entry):
    source = Path(entry["source_path"])
    target = Path(entry["file_path"])
    expected_side = entry.get("last_materialized_state", "target")
    expected = target if expected_side == "target" else source
    unexpected = source if expected_side == "target" else target
    try:
        valid = expected.is_file() and not unexpected.exists()
        current_revision = _content_revision(expected.read_bytes()) if expected.is_file() else "missing"
        valid = valid and current_revision == entry.get("materialized_revision")
    except OSError:
        valid = False
        current_revision = "unreadable"
    if valid:
        return True
    conflict = {
        "code": "revision_conflict",
        "message": "移动操作完成后源路径或目标路径又发生了变化；为保护较新的内容，本次审阅不会自动覆盖文件",
        "file_path": entry["file_path"],
        "source_path": entry["source_path"],
        "expected_side": expected_side,
        "current_revision": current_revision,
        "detected_at": time.time(),
    }
    entry["conflict"] = conflict
    entry["status"] = "conflict"
    entry["updated_at"] = time.time()
    _last_operation_error.set(conflict)
    _save_locked()
    return False


def _materialize_move(entry, desired_side):
    if desired_side == entry.get("last_materialized_state", "target"):
        return True
    if not _verify_move(entry):
        return False
    source = Path(entry["source_path"])
    target = Path(entry["file_path"])
    current = target if entry.get("last_materialized_state", "target") == "target" else source
    desired = source if desired_side == "source" else target
    if desired.exists():
        return _fail("revision_conflict", "Move destination now exists", file_path=str(desired))
    try:
        desired.parent.mkdir(parents=True, exist_ok=True)
        current.replace(desired)
    except OSError as exc:
        return _fail("write_failed", f"Could not materialize move review decision: {exc}")
    entry["last_materialized_state"] = desired_side
    entry["updated_at"] = time.time()
    return True


def _clear_error():
    _last_operation_error.set(None)


def _fail(code, message, **details):
    _last_operation_error.set({"code": code, "message": message, **details})
    return False


def _ensure_loaded_locked():
    global _loaded, _next_index
    if _loaded:
        return
    _loaded = True
    if not _store_path.is_file():
        return
    try:
        payload = json.loads(_store_path.read_text(encoding="utf-8"))
        raw_changes = payload.get("changes", []) if isinstance(payload, dict) else []
        for raw in raw_changes:
            if not isinstance(raw, dict):
                continue
            entry = _normalize_entry(raw)
            _changes.append(entry)
        _next_index = max((int(c.get("index", -1)) for c in _changes), default=-1) + 1
    except (OSError, ValueError, TypeError):
        # A corrupt runtime journal must never prevent the server from starting.
        _changes.clear()
        _next_index = 0


def _normalize_entry(raw):
    entry = dict(raw)
    entry.setdefault("id", uuid.uuid4().hex)
    entry.setdefault("transaction_id", "unscoped")
    entry.setdefault("change_type", "text")
    entry.setdefault("is_new_file", entry.get("old_content") is None)
    entry.setdefault("is_deleted_file", entry.get("new_content") is None and entry.get("old_content") is not None)
    entry.setdefault("last_materialized_content", entry.get("new_content"))
    if entry.get("change_type") == "binary":
        entry.setdefault("last_materialized_binary", entry.get("new_binary"))
        if not entry.get("base_revision"):
            entry["base_revision"] = _content_revision(_decode_binary(entry.get("old_binary")))
        if not entry.get("proposed_revision"):
            entry["proposed_revision"] = _content_revision(_decode_binary(entry.get("new_binary")))
        if not entry.get("materialized_revision"):
            entry["materialized_revision"] = _content_revision(_decode_binary(entry.get("last_materialized_binary")))
    elif entry.get("change_type") == "move":
        entry.setdefault("last_materialized_state", "target")
    else:
        entry.setdefault("base_revision", _content_revision(entry.get("old_content")))
        entry.setdefault("proposed_revision", _content_revision(entry.get("new_content")))
    entry.setdefault("materialized_revision", _content_revision(entry.get("last_materialized_content")))
    entry.setdefault("timestamp", time.time())
    entry.setdefault("updated_at", entry["timestamp"])
    entry.setdefault("tool_name", "unknown")
    entry.setdefault("status", "pending")
    entry.setdefault("reject_reason", None)
    entry.setdefault("conflict", None)
    hunks = entry.get("hunks")
    if not isinstance(hunks, list):
        hunks = _compute_hunks(
            entry.get("old_content"), entry.get("new_content"), entry["id"],
            preserve_line_endings=entry.get("tool_name") in {"patch_file", "multi_edit"},
        )
    for ordinal, hunk in enumerate(hunks):
        hunk.setdefault("ordinal", ordinal)
        # Migrate pre-v2 integer IDs while keeping old API selectors working.
        if not isinstance(hunk.get("id"), str):
            hunk["id"] = uuid.uuid5(uuid.NAMESPACE_URL, f"egoagent:{entry['id']}:legacy:{ordinal}").hex
        hunk.setdefault("status", "pending")
        hunk.setdefault("reject_reason", None)
        hunk.setdefault("decision_history", [])
    entry["hunks"] = hunks
    return entry


def _save_locked():
    payload = {
        "version": _STORE_VERSION,
        "updated_at": time.time(),
        "next_index": _next_index,
        "changes": _changes,
    }
    _store_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _store_path.with_name(f".{_store_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, _store_path)
    finally:
        temporary.unlink(missing_ok=True)


_READ_FAILED = object()
