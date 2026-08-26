"""Official ARC-AGI-3 environment adapter with exact text observations.

The adapter contains no game rules and no solver policy.  It only translates
the official SDK's action/observation contract into auditable tool payloads and
persists every transition for replay and harness research.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_LOCK = threading.RLock()
_SESSIONS: dict[str, "ArcSession"] = {}


def _resolve_session(session_id: str | None) -> tuple["ArcSession" | None, str | None]:
    """Resolve a durable environment handle without making the model memorize it.

    Exact IDs remain accepted and recorded.  When this process owns exactly one
    active ARC session, an omitted or stale conversational ID safely resolves
    to that sole runtime resource.
    """

    requested = str(session_id or "").strip()
    with _LOCK:
        if requested in _SESSIONS:
            return _SESSIONS[requested], None
        if len(_SESSIONS) == 1:
            return next(iter(_SESSIONS.values())), requested or "omitted"
    return None, None


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(child) for child in value]
    if hasattr(value, "name"):
        return value.name
    return value


def _grids(frame: Any) -> list[list[list[int]]]:
    result = []
    for grid in list(getattr(frame, "frame", []) or []):
        if hasattr(grid, "tolist"):
            grid = grid.tolist()
        result.append([[int(cell) for cell in row] for row in grid])
    return result


def _grid_text(grid: list[list[int]]) -> str:
    return "\n".join("[" + " ".join(str(cell) for cell in row) + "]" for row in grid)


def _grid_rle_text(grid: list[list[int]]) -> str:
    """Encode a grid exactly while collapsing repeated cells and rows.

    ``r2-r5: 0*3 7`` means rows 2 through 5 each contain ``0, 0, 0,
    7``.  This is deliberately a transparent textual representation rather
    than a learned/image codec: a model can reason about it, a human can audit
    it, and the persisted trace still contains the raw integer grid.
    """

    encoded_rows: list[str] = []
    for row in grid:
        runs: list[str] = []
        for value in row:
            if runs and runs[-1].split("*", 1)[0] == str(value):
                previous = runs.pop()
                count = int(previous.split("*", 1)[1]) + 1 if "*" in previous else 2
                runs.append(f"{value}*{count}")
            else:
                runs.append(str(value))
        encoded_rows.append(" ".join(runs))

    lines: list[str] = []
    start = 0
    while start < len(encoded_rows):
        end = start
        while end + 1 < len(encoded_rows) and encoded_rows[end + 1] == encoded_rows[start]:
            end += 1
        label = f"r{start}" if start == end else f"r{start}-r{end}"
        lines.append(f"{label}: {encoded_rows[start]}")
        start = end + 1
    return "\n".join(lines)


def _encoded_grid_text(grid: list[list[int]]) -> tuple[str, str]:
    """Return the shorter of the legacy matrix and exact row-RLE views."""

    matrix = _grid_text(grid)
    row_rle = _grid_rle_text(grid)
    if row_rle and len(row_rle) < len(matrix):
        return "row_rle_v1", row_rle
    return "matrix_v1", matrix


def _state_name(frame: Any) -> str:
    state = getattr(frame, "state", None)
    return str(getattr(state, "name", state or "UNKNOWN"))


def _connected_regions(cells: set[tuple[int, int]]) -> list[dict[str, Any]]:
    remaining = set(cells)
    regions = []
    while remaining:
        start = remaining.pop()
        queue = deque([start])
        region = [start]
        while queue:
            row, column = queue.popleft()
            for neighbor in ((row - 1, column), (row + 1, column), (row, column - 1), (row, column + 1)):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    queue.append(neighbor)
                    region.append(neighbor)
        rows = [cell[0] for cell in region]
        columns = [cell[1] for cell in region]
        regions.append({
            "size": len(region),
            "bbox": [min(rows), min(columns), max(rows), max(columns)],
        })
    return sorted(regions, key=lambda item: (-item["size"], item["bbox"]))


def _scene_summary(grid: list[list[int]], *, max_components: int = 48) -> dict[str, Any]:
    positions: dict[int, set[tuple[int, int]]] = {}
    counts = Counter()
    for row_index, row in enumerate(grid):
        for column_index, value in enumerate(row):
            counts[value] += 1
            positions.setdefault(value, set()).add((row_index, column_index))
    background = counts.most_common(1)[0][0] if counts else None
    components = []
    for color, cells in positions.items():
        if color == background:
            continue
        for region in _connected_regions(cells):
            components.append({"color": color, **region})
    components.sort(key=lambda item: (-item["size"], item["color"], item["bbox"]))
    return {
        "background_color": background,
        "color_counts": {str(color): count for color, count in sorted(counts.items())},
        "non_background_components": components[:max(1, int(max_components))],
        "components_truncated": max(0, len(components) - max(1, int(max_components))),
    }


def _change_summary(previous: list[list[int]], current: list[list[int]]) -> dict[str, Any] | None:
    if not previous or not current:
        return None
    changes = []
    transitions = Counter()
    positions: set[tuple[int, int]] = set()
    for row_index, row in enumerate(current):
        for column_index, value in enumerate(row):
            before = previous[row_index][column_index] if row_index < len(previous) and column_index < len(previous[row_index]) else None
            if before != value:
                changes.append({"row": row_index, "column": column_index, "from": before, "to": value})
                transitions[f"{before}->{value}"] += 1
                positions.add((row_index, column_index))
    if not changes:
        return {"count": 0, "bbox": None, "transitions": {}, "regions": [], "cells": []}
    rows = [item["row"] for item in changes]
    columns = [item["column"] for item in changes]
    return {
        "count": len(changes),
        "bbox": [min(rows), min(columns), max(rows), max(columns)],
        "transitions": dict(sorted(transitions.items())),
        "regions": _connected_regions(positions),
        "cells": changes[:256],
        "cells_truncated": max(0, len(changes) - 256),
    }


@dataclass
class ArcSession:
    session_id: str
    workspace: Path
    game_id: str
    arcade: Any
    environment: Any
    run_dir: Path
    created_at: float = field(default_factory=time.time)
    step_count: int = 0
    last_grid: list[list[int]] = field(default_factory=list)
    last_hash: str = ""
    no_change_streak: int = 0
    repeated_state_count: int = 0
    state_visits: dict[str, int] = field(default_factory=dict)

    @property
    def trace_path(self) -> Path:
        return self.run_dir / "transitions.jsonl"

    def record(self, payload: dict[str, Any]) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with self.trace_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _observation(session: ArcSession, frame: Any, *, event: str, action: dict[str, Any] | None = None) -> dict[str, Any]:
    grids = _grids(frame)
    grid = grids[-1] if grids else []
    digest = hashlib.sha256(json.dumps(grid, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
    previous_grid = session.last_grid
    change_summary = _change_summary(previous_grid, grid)
    changed_cells = None
    if session.last_grid and grid and len(session.last_grid) == len(grid):
        changed_cells = sum(
            1
            for row_index, row in enumerate(grid)
            for column_index, value in enumerate(row)
            if row_index >= len(session.last_grid)
            or column_index >= len(session.last_grid[row_index])
            or session.last_grid[row_index][column_index] != value
        )
    if session.last_hash:
        session.no_change_streak = session.no_change_streak + 1 if digest == session.last_hash else 0
    session.last_hash = digest
    session.last_grid = grid
    session.state_visits[digest] = session.state_visits.get(digest, 0) + 1
    session.repeated_state_count = session.state_visits[digest]
    available = [int(value) for value in list(getattr(frame, "available_actions", []) or [])]
    frame_encoding, frame_text = _encoded_grid_text(grid)
    payload = {
        "ok": True,
        "event": event,
        "session_id": session.session_id,
        "game_id": session.game_id,
        "step": session.step_count,
        "state": _state_name(frame),
        "levels_completed": int(getattr(frame, "levels_completed", 0) or 0),
        "win_levels": int(getattr(frame, "win_levels", 0) or 0),
        "available_actions": [f"ACTION{value}" if value else "RESET" for value in available],
        "grid_shape": [len(grid), len(grid[0]) if grid else 0],
        "grid_hash": digest,
        "changed_cells": changed_cells,
        "no_change_streak": session.no_change_streak,
        "state_visit_count": session.repeated_state_count,
        "progress": bool(changed_cells or event == "start"),
        "scene_summary": _scene_summary(grid),
        "change_summary": change_summary,
        "frame_encoding": frame_encoding,
        "frame_text": frame_text,
        "animation_frames": len(grids),
        "action": action,
    }
    session.record({"timestamp": time.time(), **payload, "raw_frame": _jsonable(frame), "grids": grids})
    return payload


def start_arc_session(
    workspace: str | Path,
    game_id: str,
    *,
    seed: int = 0,
    save_recording: bool = True,
) -> dict[str, Any]:
    try:
        import arc_agi
    except ImportError as error:
        return {"ok": False, "error": "arc-agi is not installed; install arc-agi==0.9.9", "detail": str(error)}
    root = Path(workspace).resolve()
    with _LOCK:
        existing = next(
            (
                session for session in _SESSIONS.values()
                if session.workspace == root and session.game_id == str(game_id)
            ),
            None,
        )
    if existing is not None:
        resumed = arc_session_status(existing.session_id)
        resumed.update({"event": "resume", "resumed": True})
        return resumed
    session_id = f"arc-{uuid.uuid4().hex[:12]}"
    base = root / ".egoagent" / "arc_agi3"
    run_dir = base / "runs" / session_id
    try:
        arcade = arc_agi.Arcade(
            environments_dir=str(base / "environment_files"),
            recordings_dir=str(run_dir / "sdk_recordings"),
        )
        environment = arcade.make(str(game_id), seed=int(seed), save_recording=bool(save_recording))
        if environment is None:
            return {"ok": False, "error": f"official SDK could not create environment {game_id!r}"}
        frame = environment.observation_space
        if frame is None:
            frame = environment.reset()
        if frame is None:
            return {"ok": False, "error": "environment returned no initial observation"}
        session = ArcSession(session_id, root, str(game_id), arcade, environment, run_dir)
        with _LOCK:
            _SESSIONS[session_id] = session
        return _observation(session, frame, event="start")
    except Exception as error:
        return {"ok": False, "error": f"ARC environment start failed: {type(error).__name__}: {error}"}


def step_arc_session(
    session_id: str | None,
    action_name: str,
    *,
    x: int | None = None,
    y: int | None = None,
    prediction: str = "",
    reasoning: str = "",
) -> dict[str, Any]:
    try:
        from arcengine import GameAction
    except ImportError as error:
        return {"ok": False, "error": str(error)}
    session, resolved_from = _resolve_session(session_id)
    if session is None:
        return {"ok": False, "error": f"unknown ARC session: {session_id}"}
    try:
        action = GameAction.from_name(str(action_name))
        available = [
            int(getattr(value, "value", value))
            for value in list(session.environment.action_space or [])
        ]
        if action.value != 0 and int(action.value) not in available:
            return {"ok": False, "error": f"{action.name} is unavailable", "available_actions": available}
        data = {}
        if action.is_complex():
            if x is None or y is None or not (0 <= int(x) <= 63 and 0 <= int(y) <= 63):
                return {"ok": False, "error": f"{action.name} requires x and y integers in [0, 63]"}
            data = {"x": int(x), "y": int(y)}
        rationale = {"prediction": str(prediction or ""), "reasoning": str(reasoning or "")}
        frame = session.environment.step(action, data=data, reasoning=rationale)
        if frame is None:
            return {"ok": False, "error": "official environment returned no observation"}
        session.step_count += 1
        result = _observation(
            session,
            frame,
            event="action",
            action={"name": action.name, **data, **rationale},
        )
        if resolved_from is not None:
            result["resolved_session_id_from"] = resolved_from
        return result
    except Exception as error:
        return {"ok": False, "error": f"ARC action failed: {type(error).__name__}: {error}"}


def arc_session_status(session_id: str | None = None) -> dict[str, Any]:
    session, resolved_from = _resolve_session(session_id)
    if session is None:
        return {"ok": False, "error": f"unknown ARC session: {session_id}"}
    frame = session.environment.observation_space
    if frame is None:
        return {"ok": False, "error": "environment has no current observation"}
    # Status is read-only and must not mutate stagnation counters.
    grid = (_grids(frame) or [[]])[-1]
    frame_encoding, frame_text = _encoded_grid_text(grid)
    result = {
        "ok": True,
        "session_id": session.session_id,
        "game_id": session.game_id,
        "step": session.step_count,
        "state": _state_name(frame),
        "levels_completed": int(getattr(frame, "levels_completed", 0) or 0),
        "win_levels": int(getattr(frame, "win_levels", 0) or 0),
        "available_actions": [
            f"ACTION{int(value)}" if int(value) else "RESET"
            for value in list(getattr(frame, "available_actions", []) or [])
        ],
        "no_change_streak": session.no_change_streak,
        "state_visit_count": session.repeated_state_count,
        "scene_summary": _scene_summary(grid),
        "frame_encoding": frame_encoding,
        "frame_text": frame_text,
        "trace_path": str(session.trace_path.relative_to(session.workspace)),
    }
    if resolved_from is not None:
        result["resolved_session_id_from"] = resolved_from
    return result


def finish_arc_session(session_id: str | None = None) -> dict[str, Any]:
    session, resolved_from = _resolve_session(session_id)
    if session is None:
        return {"ok": False, "error": f"unknown ARC session: {session_id}"}
    frame = session.environment.observation_space
    result = {
        "ok": True,
        "session_id": session.session_id,
        "game_id": session.game_id,
        "steps": session.step_count,
        "state": _state_name(frame),
        "levels_completed": int(getattr(frame, "levels_completed", 0) or 0),
        "win_levels": int(getattr(frame, "win_levels", 0) or 0),
        "trace_path": str(session.trace_path.relative_to(session.workspace)),
        "scorecard": None,
    }
    if resolved_from is not None:
        result["resolved_session_id_from"] = resolved_from
    try:
        scorecard = session.arcade.close_scorecard()
        result["scorecard"] = _jsonable(scorecard) if scorecard is not None else None
    except Exception as error:
        result["scorecard_error"] = f"{type(error).__name__}: {error}"
    session.record({"timestamp": time.time(), "event": "finish", **result})
    with _LOCK:
        _SESSIONS.pop(session.session_id, None)
    return result


__all__ = ["arc_session_status", "finish_arc_session", "start_arc_session", "step_arc_session"]
