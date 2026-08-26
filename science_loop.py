"""Evidence-bound autonomous science workflow.

The state machine accepts model output only as a proposal.  Completion requires
hashed artifacts, command-shaped experiment records, claim-level citations and
an independent reviewer.  This prevents a fluent self-report from becoming a
fake successful experiment.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


SCHEMA = "ego.science-project.v1"
STAGES = (
    "retrieve",
    "hypothesis",
    "plan",
    "implement",
    "execute",
    "analyze",
    "repair",
    "independent_review",
    "report",
)


class ScienceLoopError(ValueError):
    pass


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


class ScienceRepository:
    def __init__(self, workspace: str | Path, store: str | Path | None = None):
        self.workspace = Path(workspace).resolve()
        self.store = Path(store).resolve() if store else self.workspace / ".egoagent" / "science"
        self.store.mkdir(parents=True, exist_ok=True)

    def _project_dir(self, project_id: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", str(project_id)):
            raise ScienceLoopError("invalid project id")
        return self.store / project_id

    def _state_path(self, project_id: str) -> Path:
        return self._project_dir(project_id) / "state.json"

    def create(self, objective: str, *, creator: str, project_id: str | None = None) -> dict[str, Any]:
        objective = str(objective).strip()
        creator = str(creator).strip()
        if not objective or not creator:
            raise ScienceLoopError("objective and creator are required")
        identifier = project_id or f"science-{uuid.uuid4().hex[:12]}"
        state_path = self._state_path(identifier)
        if state_path.exists():
            raise ScienceLoopError(f"project already exists: {identifier}")
        state = {
            "schema": SCHEMA,
            "id": identifier,
            "objective": objective,
            "creator": creator,
            "status": "active",
            "current_stage": STAGES[0],
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
            "revision": 0,
            "evidence": {},
            "claims": {},
            "experiments": {},
            "stages": {},
            "events": [],
        }
        self._save(state, "project_created", {"creator": creator})
        return copy.deepcopy(state)

    def load(self, project_id: str, *, verify_artifacts: bool = True) -> dict[str, Any]:
        path = self._state_path(project_id)
        if not path.is_file():
            raise ScienceLoopError(f"project not found: {project_id}")
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("schema") != SCHEMA:
            raise ScienceLoopError("unsupported science project schema")
        if verify_artifacts:
            failures = self.verify_artifacts(state)
            if failures:
                raise ScienceLoopError("artifact integrity failure: " + "; ".join(failures))
        return state

    def list(self) -> list[dict[str, Any]]:
        result = []
        for path in sorted(self.store.glob("*/state.json")):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                result.append({key: state.get(key) for key in ("id", "objective", "status", "current_stage", "updated_at", "revision")})
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return sorted(result, key=lambda item: item.get("updated_at") or 0, reverse=True)

    def _save(self, state: dict[str, Any], event_type: str, detail: dict[str, Any]) -> None:
        state["revision"] = int(state.get("revision", 0)) + 1
        state["updated_at"] = int(time.time())
        state.setdefault("events", []).append({"sequence": len(state.get("events", [])) + 1, "type": event_type, "at": state["updated_at"], "detail": detail})
        _atomic_json(self._state_path(state["id"]), state)

    def add_artifact(self, project_id: str, source: str | Path, *, kind: str, actor: str) -> dict[str, Any]:
        state = self.load(project_id)
        source_path = Path(source).resolve()
        if not source_path.is_file() or not _under(source_path, self.workspace):
            raise ScienceLoopError("artifact must be a file inside the configured workspace")
        digest = _digest(source_path)
        artifact_id = f"artifact:{digest[:20]}"
        destination_dir = self._project_dir(project_id) / "artifacts"
        destination_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", source_path.name)[:120] or "artifact"
        destination = destination_dir / f"{digest[:16]}-{safe_name}"
        if not destination.exists():
            shutil.copy2(source_path, destination)
        state["evidence"][artifact_id] = {
            "id": artifact_id,
            "type": "artifact",
            "kind": str(kind),
            "path": str(destination.relative_to(self._project_dir(project_id))).replace("\\", "/"),
            "sha256": digest,
            "size": destination.stat().st_size,
            "actor": str(actor),
            "created_at": int(time.time()),
        }
        self._save(state, "artifact_added", {"artifact_id": artifact_id, "kind": kind, "actor": actor})
        return copy.deepcopy(state["evidence"][artifact_id])

    def add_source(self, project_id: str, url: str, *, title: str, actor: str, snapshot_artifact: str | None = None) -> dict[str, Any]:
        state = self.load(project_id)
        parsed = urlparse(str(url))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ScienceLoopError("source URL must be http(s)")
        if snapshot_artifact and snapshot_artifact not in state["evidence"]:
            raise ScienceLoopError(f"unknown snapshot artifact: {snapshot_artifact}")
        source_id = "source:" + hashlib.sha256(str(url).encode("utf-8")).hexdigest()[:20]
        state["evidence"][source_id] = {
            "id": source_id,
            "type": "source",
            "url": str(url),
            "title": str(title).strip() or str(url),
            "snapshot_artifact": snapshot_artifact,
            "actor": str(actor),
            "created_at": int(time.time()),
        }
        self._save(state, "source_added", {"source_id": source_id, "actor": actor})
        return copy.deepcopy(state["evidence"][source_id])

    def verify_artifacts(self, state_or_id: dict[str, Any] | str) -> list[str]:
        state = state_or_id if isinstance(state_or_id, dict) else self.load(state_or_id, verify_artifacts=False)
        base = self._project_dir(state["id"])
        failures: list[str] = []
        for evidence_id, evidence in state.get("evidence", {}).items():
            if evidence.get("type") != "artifact":
                continue
            path = (base / evidence.get("path", "")).resolve()
            if not _under(path, base) or not path.is_file():
                failures.append(f"{evidence_id}: missing or escaped path")
            elif _digest(path) != evidence.get("sha256"):
                failures.append(f"{evidence_id}: sha256 mismatch")
        return failures

    @staticmethod
    def _ids(value: Any) -> list[str]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ScienceLoopError("evidence references must be a list of ids")
        return value

    def _require_evidence(self, state: dict[str, Any], refs: Iterable[str], label: str) -> list[str]:
        values = list(refs)
        missing = [value for value in values if value not in state["evidence"]]
        if missing:
            raise ScienceLoopError(f"{label} references unknown evidence: {missing}")
        return values

    def _validate_stage(self, state: dict[str, Any], stage: str, actor: str, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise ScienceLoopError("stage payload must be an object")
        if stage == "retrieve":
            refs = self._require_evidence(state, self._ids(payload.get("evidence_refs", [])), "retrieve")
            if not refs:
                raise ScienceLoopError("retrieve requires at least one registered source or artifact")
        elif stage == "hypothesis":
            hypotheses = payload.get("hypotheses")
            if not isinstance(hypotheses, list) or not hypotheses:
                raise ScienceLoopError("hypothesis stage requires hypotheses")
            for item in hypotheses:
                if not all(str(item.get(key, "")).strip() for key in ("id", "statement", "falsification")):
                    raise ScienceLoopError("each hypothesis needs id, statement and falsification")
                refs = self._require_evidence(state, self._ids(item.get("evidence_refs", [])), f"hypothesis {item.get('id')}")
                if not refs:
                    raise ScienceLoopError("each hypothesis needs evidence")
        elif stage == "plan":
            experiments = payload.get("experiments")
            if not isinstance(experiments, list) or not experiments:
                raise ScienceLoopError("plan requires experiments")
            for item in experiments:
                command = item.get("command")
                if not str(item.get("id", "")).strip() or not isinstance(command, list) or not command or any(not isinstance(part, str) or not part for part in command):
                    raise ScienceLoopError("each experiment needs an id and non-shell command argv")
                if not str(item.get("expected_observation", "")).strip():
                    raise ScienceLoopError("each experiment needs an expected observation")
        elif stage == "implement":
            refs = self._require_evidence(state, self._ids(payload.get("artifact_refs", [])), "implement")
            if not refs or not str(payload.get("summary", "")).strip():
                raise ScienceLoopError("implement requires a summary and at least one hashed artifact")
        elif stage == "execute":
            planned = state["experiments"]
            results = payload.get("results")
            if not isinstance(results, list) or not results:
                raise ScienceLoopError("execute requires experiment results")
            seen = set()
            for result in results:
                experiment_id = str(result.get("experiment_id", ""))
                if experiment_id not in planned:
                    raise ScienceLoopError(f"unplanned experiment result: {experiment_id}")
                if result.get("command") != planned[experiment_id]["command"]:
                    raise ScienceLoopError(f"experiment command does not match plan: {experiment_id}")
                if not isinstance(result.get("exit_code"), int):
                    raise ScienceLoopError("experiment result needs an integer exit_code")
                refs = self._require_evidence(state, self._ids(result.get("artifact_refs", [])), f"experiment {experiment_id}")
                if not refs:
                    raise ScienceLoopError("experiment result needs captured output/artifact evidence")
                seen.add(experiment_id)
            if seen != set(planned):
                raise ScienceLoopError(f"missing experiment results: {sorted(set(planned) - seen)}")
        elif stage == "analyze":
            claims = payload.get("claims")
            if not isinstance(claims, list) or not claims:
                raise ScienceLoopError("analyze requires claims")
            for claim in claims:
                if not str(claim.get("id", "")).strip() or not str(claim.get("text", "")).strip():
                    raise ScienceLoopError("each claim needs id and text")
                refs = self._require_evidence(state, self._ids(claim.get("evidence_refs", [])), f"claim {claim.get('id')}")
                if not refs:
                    raise ScienceLoopError("every claim needs evidence")
        elif stage == "repair":
            decision = payload.get("decision")
            if decision not in {"not_needed", "repaired", "failed"}:
                raise ScienceLoopError("repair decision must be not_needed, repaired or failed")
            if decision == "repaired":
                refs = self._require_evidence(state, self._ids(payload.get("artifact_refs", [])), "repair")
                if not refs:
                    raise ScienceLoopError("a repair needs artifact evidence")
        elif stage == "independent_review":
            implement_actor = state["stages"].get("implement", {}).get("actor")
            if actor in {state["creator"], implement_actor}:
                raise ScienceLoopError("independent reviewer must differ from creator and implementer")
            if not isinstance(payload.get("approved"), bool):
                raise ScienceLoopError("review requires an explicit approved boolean")
            reviewed = set(self._ids(payload.get("claim_ids", [])))
            if reviewed != set(state["claims"]):
                raise ScienceLoopError("review must cover every analyzed claim")
            self._require_evidence(state, self._ids(payload.get("evidence_refs", [])), "review")
        elif stage == "report":
            review = state["stages"].get("independent_review", {}).get("payload", {})
            if not review.get("approved"):
                raise ScienceLoopError("final report requires an approved independent review")
            if set(self._ids(payload.get("claim_ids", []))) != set(state["claims"]):
                raise ScienceLoopError("report must include every reviewed claim")
            refs = self._require_evidence(state, self._ids(payload.get("artifact_refs", [])), "report")
            if not refs or not str(payload.get("summary", "")).strip():
                raise ScienceLoopError("report requires a summary and immutable report artifact")

    def submit_stage(
        self,
        project_id: str,
        stage: str,
        *,
        actor: str,
        payload: dict[str, Any],
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        state = self.load(project_id)
        if state["status"] != "active":
            raise ScienceLoopError("project is not active")
        if expected_revision is not None and state["revision"] != expected_revision:
            raise ScienceLoopError(f"revision conflict: expected {expected_revision}, found {state['revision']}")
        if stage != state["current_stage"]:
            raise ScienceLoopError(f"stage order violation: expected {state['current_stage']}, got {stage}")
        actor = str(actor).strip()
        if not actor:
            raise ScienceLoopError("actor is required")
        self._validate_stage(state, stage, actor, payload)
        record = {"stage": stage, "actor": actor, "at": int(time.time()), "payload": copy.deepcopy(payload)}
        state["stages"][stage] = record
        if stage == "plan":
            state["experiments"] = {item["id"]: copy.deepcopy(item) for item in payload["experiments"]}
        elif stage == "analyze":
            state["claims"] = {item["id"]: copy.deepcopy(item) for item in payload["claims"]}
        index = STAGES.index(stage)
        if stage == "report":
            state["status"] = "complete"
            state["current_stage"] = None
        else:
            state["current_stage"] = STAGES[index + 1]
        self._save(state, "stage_submitted", {"stage": stage, "actor": actor})
        return copy.deepcopy(state)

    def audit(self, project_id: str) -> dict[str, Any]:
        state = self.load(project_id, verify_artifacts=False)
        artifact_failures = self.verify_artifacts(state)
        claim_failures = []
        for claim_id, claim in state.get("claims", {}).items():
            missing = [ref for ref in claim.get("evidence_refs", []) if ref not in state.get("evidence", {})]
            if missing:
                claim_failures.append(f"{claim_id}: missing {missing}")
        reviewer = state.get("stages", {}).get("independent_review", {}).get("actor")
        independent = bool(reviewer and reviewer not in {state.get("creator"), state.get("stages", {}).get("implement", {}).get("actor")})
        passed = not artifact_failures and not claim_failures and (state["status"] != "complete" or independent)
        return {
            "project_id": project_id,
            "passed": passed,
            "status": state["status"],
            "artifact_failures": artifact_failures,
            "claim_failures": claim_failures,
            "independent_review": independent,
            "stage_coverage": {stage: stage in state.get("stages", {}) for stage in STAGES},
        }
