"""Independently verify the Skill produced by the recording evolution Task."""

from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "task_bench" / "tasks" / "video_self_evolution_walkthrough.json"
DEFAULT_SKILLS = (
    "greenhouse_water_usage",
    "greenhouse_irrigation_calc",
    "greenhouse_irrigation_calculation",
    "greenhouse_water_usage_calculator",
    "compute_greenhouse_water_usage",
)


def find_script(skill_name: str | None) -> Path:
    names = (skill_name,) if skill_name else DEFAULT_SKILLS
    for name in names:
        if not name:
            continue
        path = ROOT / "identity" / "coder" / "ego" / "skills" / name / "scripts" / f"{name}.py"
        if path.is_file():
            return path
    raise FileNotFoundError(
        "No recording evolution Skill was found. Run video_self_evolution_walkthrough and approve it first."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", help="exact generated Skill name; auto-detected by default")
    args = parser.parse_args()
    script = find_script(args.skill)
    task = json.loads(TASK.read_text(encoding="utf-8"))
    files = task["workspace"]["files"]
    with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as directory:
        workspace = Path(directory)
        for relative, content in files.items():
            path = workspace / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("recording_evolution_skill", script)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load {script}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function = getattr(module, script.stem)
        context = {"workspace": str(workspace)}
        first = function("SM-20", "P-12", 5, _context=context)
        second = function("SM-30", "P-8", 3, _context=context)
        assert first["threshold_percent"] == 35 and first["water_ml"] == 60, first
        assert second["threshold_percent"] == 41 and second["water_ml"] == 24, second
        try:
            function("SM-99", "P-12", 5, _context=context)
        except ValueError as error:
            assert "SM-99" in str(error), error
        else:
            raise AssertionError("unknown sensor model was not rejected")
    print(f"PASS persisted Skill: {script.relative_to(ROOT)}")
    print("PASS SM-20/P-12/5 -> 35%, 60mL")
    print("PASS SM-30/P-8/3 -> 41%, 24mL")
    print("PASS unknown model -> ValueError")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
