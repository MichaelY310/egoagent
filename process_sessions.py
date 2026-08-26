"""Persistent, cancellable process sessions for model-authored terminal work.

The module is deliberately independent from the Agent and Flow runtimes.  A
trusted caller supplies the per-Agent session registry and an already-approved
command.  This keeps process lifecycle mechanics reusable by tools, Tasks and
future terminal nodes without letting the process layer make policy decisions.
"""

from __future__ import annotations

import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, MutableMapping


def start_process_session(
    registry: MutableMapping[str, dict[str, Any]],
    *,
    command: str,
    cwd: str,
    env: dict[str, str],
    yield_time_ms: int = 10_000,
    shell: bool = True,
    argv: list[str] | None = None,
) -> dict[str, Any]:
    """Start a pipe-backed interactive process and return its first chunk."""

    session_id = uuid.uuid4().hex[:12]
    process = subprocess.Popen(
        argv if argv is not None else command,
        shell=False if argv is not None else bool(shell),
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    entry: dict[str, Any] = {
        "process": process,
        "command": command,
        "cwd": str(Path(cwd).resolve()),
        "output_lines": [],
        "reported_line_count": 0,
        "start_time": time.time(),
        "lock": threading.RLock(),
        "output_event": threading.Event(),
    }
    registry[session_id] = entry

    def collect() -> None:
        stream = process.stdout
        if stream is None:
            return
        try:
            for line in stream:
                with entry["lock"]:
                    entry["output_lines"].append(line)
                    entry["output_event"].set()
        finally:
            try:
                stream.close()
            except OSError:
                pass

    threading.Thread(target=collect, name=f"ego-process-{session_id}", daemon=True).start()
    return read_process_session(registry, session_id, yield_time_ms=yield_time_ms)


def read_process_session(
    registry: MutableMapping[str, dict[str, Any]],
    session_id: str,
    *,
    yield_time_ms: int = 0,
    max_output_chars: int = 50_000,
) -> dict[str, Any]:
    """Return only output produced since the last read of this session."""

    entry = registry.get(str(session_id))
    if entry is None:
        return {"ok": False, "status": "not_found", "error": f"Unknown process session: {session_id}"}
    process = entry["process"]
    wait_seconds = min(30_000, max(0, int(yield_time_ms))) / 1000.0
    with entry["lock"]:
        first_chunk_pending = not entry["output_lines"] and int(entry.get("reported_line_count", 0)) == 0
    # Process creation returned, but a heavily loaded Windows host may need a
    # little longer to schedule the child and collector.  A bounded first-read
    # grace prevents a misleading empty initial chunk without changing later
    # poll semantics or waiting indefinitely for silent commands.
    startup_grace = 0.5 if first_chunk_pending and wait_seconds > 0 else 0.0
    deadline = time.monotonic() + wait_seconds + startup_grace
    output_event = entry.get("output_event")
    while process.poll() is None and time.monotonic() < deadline:
        with entry["lock"]:
            if len(entry["output_lines"]) > int(entry.get("reported_line_count", 0)):
                break
        remaining = max(0.0, deadline - time.monotonic())
        if isinstance(output_event, threading.Event):
            output_event.wait(timeout=min(0.02, remaining))
        else:
            time.sleep(min(0.02, remaining))
    with entry["lock"]:
        produced_output = len(entry["output_lines"]) > int(entry.get("reported_line_count", 0))
    if produced_output and process.poll() is None:
        # A short-lived command often flushes its final line immediately
        # before exit.  Let its exit status settle so callers do not receive
        # "running" next to the complete final output and leak the cwd handle.
        try:
            process.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            pass
    # Give the collector a brief opportunity to drain final buffered output.
    if process.poll() is not None:
        time.sleep(0.03)
    with entry["lock"]:
        start = int(entry.get("reported_line_count", 0))
        lines = list(entry["output_lines"][start:])
        entry["reported_line_count"] = len(entry["output_lines"])
        if isinstance(output_event, threading.Event):
            output_event.clear()
    output = "".join(lines)
    truncated = len(output) > max(1, int(max_output_chars))
    if truncated:
        output = output[: max(1, int(max_output_chars))] + "\n...[output truncated]"
    exit_code = process.poll()
    return {
        "ok": exit_code in (None, 0),
        "status": "running" if exit_code is None else "done",
        "session_id": str(session_id),
        "exit_code": exit_code,
        "output": output,
        "truncated": truncated,
        "elapsed_seconds": round(time.time() - float(entry["start_time"]), 3),
    }


def write_process_session(
    registry: MutableMapping[str, dict[str, Any]],
    session_id: str,
    *,
    chars: str = "",
    yield_time_ms: int = 250,
    max_output_chars: int = 50_000,
) -> dict[str, Any]:
    """Write stdin (or just poll when empty), then return the next chunk."""

    entry = registry.get(str(session_id))
    if entry is None:
        return {"ok": False, "status": "not_found", "error": f"Unknown process session: {session_id}"}
    process = entry["process"]
    if chars:
        if process.poll() is not None or process.stdin is None:
            return {
                "ok": False,
                "status": "done",
                "session_id": str(session_id),
                "exit_code": process.poll(),
                "error": "Process stdin is no longer available",
            }
        try:
            process.stdin.write(str(chars))
            process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            return {
                "ok": False,
                "status": "done",
                "session_id": str(session_id),
                "exit_code": process.poll(),
                "error": str(error),
            }
    return read_process_session(
        registry,
        str(session_id),
        yield_time_ms=yield_time_ms,
        max_output_chars=max_output_chars,
    )


__all__ = ["read_process_session", "start_process_session", "write_process_session"]
