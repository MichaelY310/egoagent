"""Restore the recording fixture from its canonical Task Bench definition.

Only known fixture files are overwritten. Extra files are deliberately kept so
the reset cannot erase unrelated recording notes or user work.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "task_bench" / "tasks" / "video_code_agent_walkthrough.json"
TARGET = ROOT / "tutorial_assets" / "video_demo_repo"
CHANGE_LEDGER = ROOT / ".egoagent" / "change-transactions.json"
EVOLUTION_ARTIFACTS = (
    ROOT / "identity" / "coder" / "ego" / "skills" / "compute_greenhouse_water_usage",
    ROOT / "identity" / "dante" / "ego" / "skills" / "compute_greenhouse_water_usage",
    ROOT / "identity" / "coder" / "ego" / "skills" / "greenhouse_irrigation_calc",
    ROOT / "identity" / "dante" / "ego" / "skills" / "greenhouse_irrigation_calc",
    ROOT / "identity" / "coder" / "ego" / "skills" / "greenhouse_irrigation_calculation",
    ROOT / "identity" / "dante" / "ego" / "skills" / "greenhouse_irrigation_calculation",
    ROOT / "identity" / "coder" / "ego" / "skills" / "greenhouse_water_usage_calculator",
    ROOT / "identity" / "dante" / "ego" / "skills" / "greenhouse_water_usage_calculator",
    ROOT / "identity" / "coder" / "ego" / "skills" / "greenhouse_water_usage",
    ROOT / "identity" / "dante" / "ego" / "skills" / "greenhouse_water_usage",
)
RECORDING_CREATED_ARTIFACTS = (
    TARGET / "VIDEO_TEMP_NOTE.md",
    ROOT / "identity" / "video_coder",
    ROOT / "harness" / "video_basic_agent",
    ROOT / "identity" / "video_incident_triage_agent",
    ROOT / "harness" / "video_incident_triage_agent",
    ROOT / ".environment" / "tools" / "workspace_policy_lookup",
)
FLOW_DEMO_BASELINES = {
    "demo_fragile_release_flow": ROOT / "tutorial_assets" / "evolution_demo_baselines" / "demo_fragile_release_flow.json",
    "demo_noisy_research_flow": ROOT / "tutorial_assets" / "evolution_demo_baselines" / "demo_noisy_research_flow.json",
}


def load_files() -> dict[str, str]:
    payload = json.loads(TASK.read_text(encoding="utf-8"))
    return payload["workspace"]["files"]


def changed_files() -> list[str]:
    changed = []
    for relative, expected in load_files().items():
        path = TARGET / relative
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current != expected:
            changed.append(relative)
    return changed


def changed_flow_demos() -> list[str]:
    changed = []
    for name, baseline in FLOW_DEMO_BASELINES.items():
        target = ROOT / "harness" / name / "config.json"
        expected = json.loads(baseline.read_text(encoding="utf-8"))
        try:
            current = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else None
        except (OSError, ValueError):
            current = None
        if current != expected:
            changed.append(name)
    return changed


def purge_recording_change_transactions() -> int:
    """Remove only review records whose target lives inside the demo fixture.

    A previous take may stop with pending, rejected, or conflicted hunks.  Those
    records are useful for the recorded Session, but they must not leak into the
    next take's Agent Changes panel after the fixture files have been restored.
    The global ledger and every unrelated workspace record remain untouched.
    """

    if not CHANGE_LEDGER.is_file():
        return 0
    payload = json.loads(CHANGE_LEDGER.read_text(encoding="utf-8"))
    changes = payload.get("changes") if isinstance(payload, dict) else None
    if not isinstance(changes, list):
        return 0
    target_root = TARGET.resolve(strict=False)

    def belongs_to_fixture(change: object) -> bool:
        if not isinstance(change, dict) or not change.get("file_path"):
            return False
        try:
            Path(str(change["file_path"])).resolve(strict=False).relative_to(target_root)
            return True
        except (OSError, ValueError):
            return False

    retained = [change for change in changes if not belongs_to_fixture(change)]
    removed = len(changes) - len(retained)
    if removed:
        payload["changes"] = retained
        payload["updated_at"] = time.time()
        CHANGE_LEDGER.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return removed


def clear_running_backend_transactions() -> int:
    """Keep a running 8765 backend's in-memory journal in sync with the reset."""

    request = urllib.request.Request(
        "http://127.0.0.1:8765/api/session/changes/clear-workspace",
        data=json.dumps({"workspace": str(TARGET)}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = json.load(response)
            return int(payload.get("removed") or 0)
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report drift without writing")
    parser.add_argument(
        "--reset-evolution-artifact",
        action="store_true",
        help="also remove only the known Skill created by the self-evolution recording task",
    )
    parser.add_argument(
        "--reset-created-artifacts",
        action="store_true",
        help="also remove only the exact video_coder/video_basic_agent/tutorial Tool/temp-note artifacts",
    )
    args = parser.parse_args()
    drift = changed_files()
    flow_drift = changed_flow_demos()
    if args.check:
        if drift or flow_drift:
            print("Fixture needs reset: " + ", ".join(drift + flow_drift))
            return 1
        print(f"Fixture ready: {TARGET}")
        return 0

    for relative, content in load_files().items():
        path = TARGET / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")
    for name, baseline in FLOW_DEMO_BASELINES.items():
        target = ROOT / "harness" / name / "config.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(baseline.read_text(encoding="utf-8"), encoding="utf-8", newline="")
    print(f"Reset {len(load_files())} known files in {TARGET}")
    if drift:
        print("Restored: " + ", ".join(drift))
    else:
        print("No drift was present.")
    print(
        "Restored Flow evolution fixtures: "
        + (", ".join(flow_drift) if flow_drift else "already canonical")
    )
    removed_transactions = clear_running_backend_transactions()
    removed_transactions += purge_recording_change_transactions()
    print(f"Removed {removed_transactions} stale review transaction(s) for the recording fixture.")
    if args.reset_evolution_artifact:
        removed = []
        for artifact in EVOLUTION_ARTIFACTS:
            if artifact.is_dir():
                shutil.rmtree(artifact)
                removed.append(str(artifact.relative_to(ROOT)))
        print("Removed tutorial evolution artifact: " + (", ".join(removed) if removed else "none present"))
    if args.reset_created_artifacts:
        removed = []
        for artifact in RECORDING_CREATED_ARTIFACTS:
            if artifact.is_dir():
                shutil.rmtree(artifact)
                removed.append(str(artifact.relative_to(ROOT)))
            elif artifact.is_file():
                artifact.unlink()
                removed.append(str(artifact.relative_to(ROOT)))
        print("Removed tutorial-created artifacts: " + (", ".join(removed) if removed else "none present"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
