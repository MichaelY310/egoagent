"""Replay untouched upstream tests against subsets of actual production edits.

prepare: Windows/Linux with git; run: Linux with dependencies in a dedicated venv.
No model calls, no synthetic task generation, no tuning from outcomes.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import itertools
import json
import os
import re
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
REPO = ROOT / "cache" / "mini-swe-agent"
COMPONENTS = {"agents", "models", "environments", "run", "config", "utils", "core"}


def save(path: Path, value: object):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git_bytes(*args: str):
    return subprocess.check_output(["git", "-C", str(REPO), *args])


def comp(path: str):
    parts = path.split("/")
    return parts[2] if len(parts) > 3 else "core"


def adaptive_scope(sources: dict[str, str], seed: str):
    """Predeclared outcome-blind, edit-local import/protocol/template closure."""
    groups = {comp(p) for p in sources}
    edges: dict[tuple[str, str], set[str]] = {}
    definitions: dict[str, set[str]] = {"Model": {"models"}, "Agent": {"agents"}, "Environment": {"environments"}}
    parsed = {}
    for path, source in sources.items():
        if not path.endswith(".py"):
            continue
        try:
            parsed[path] = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(parsed[path]):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                definitions.setdefault(node.name, set()).add(comp(path))

    def link(a, b, why):
        if a != b and a in groups and b in groups:
            edges.setdefault(tuple(sorted((a, b))), set()).add(why)

    for path, tree in parsed.items():
        a = comp(path)
        for node in ast.walk(tree):
            module = node.module if isinstance(node, ast.ImportFrom) else ""
            if module and module.startswith("minisweagent."):
                b = module.split(".")[1]
                link(a, b if b in COMPONENTS else "core", "import:" + module)
            if isinstance(node, ast.Name):
                for b in definitions.get(node.id, set()):
                    link(a, b, "definition:" + node.id)
        tokens = set(re.findall(r"\b[A-Za-z_]\w*\b", sources[path]))
        for other, content in sources.items():
            if other.endswith((".yaml", ".yml", ".tcss")):
                # Named template variables, not all common English words.
                template_tokens = set(re.findall(r"\b[A-Za-z_]\w*\b", " ".join(re.findall(r"\{[%{](.*?)[%}]\}", content, re.S))))
                overlap = (tokens & template_tokens) - {"if", "else", "endif", "for", "endfor", "in", "not", "and", "or", "is", "defined", "true", "false", "none"}
                if overlap:
                    link(a, comp(other), "template:" + ",".join(sorted(overlap)))
    selected = {seed}
    while True:
        new = selected | {b for pair in edges for a in pair for b in pair if a in selected}
        if new == selected:
            break
        selected = new
    return sorted(selected), [{"components": list(pair), "reasons": sorted(reasons)} for pair, reasons in sorted(edges.items())]


def extract_archive(commit: str, target: Path):
    target.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(io.BytesIO(git_bytes("archive", "--format=zip", commit, "src", "tests", "pyproject.toml"))) as archive:
        for member in archive.infolist():
            out = (target / member.filename).resolve()
            if not out.is_relative_to(target.resolve()):
                raise ValueError("Unsafe archive path")
            if member.is_dir():
                out.mkdir(parents=True, exist_ok=True)
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(archive.read(member))


def prepare():
    sample = json.loads((ROOT / "results/mini_sample.json").read_text(encoding="utf-8"))
    manifest = []
    for index, case in enumerate(sample["cases"], 1):
        cid = case["commit"][:8]
        paths = [p for p in case["all_changed_paths"] if p.startswith("src/minisweagent/")]
        child_tree = set(git_bytes("ls-tree", "-r", "--name-only", case["commit"]).decode().splitlines())
        sources = {p: git_bytes("show", f'{case["commit"]}:{p}').decode("utf-8") if p in child_tree else "" for p in paths}
        groups = sorted({comp(p) for p in paths})
        adaptive, evidence = adaptive_scope(sources, case["seed"])
        fixed_groups = [{"agents", "models", "environments", "core"}, {"run", "config", "utils"}]
        strong_groups = [{"agents", "models", "environments", "core", "config"}, {"run", "utils"}]
        scopes = {"single": [case["seed"]], "fixed": sorted(next(g for g in fixed_groups if case["seed"] in g)), "fixed_interface": sorted(next(g for g in strong_groups if case["seed"] in g)), "adaptive_static": adaptive, "oracle": groups}
        record = case | {"index": index, "id": cid, "production_paths": paths, "components_all_production": groups, "scopes": scopes, "dependency_evidence": evidence, "cells": []}
        if len(groups) > 4:
            record["unsupported"] = "more than four changed components"
            manifest.append(record)
            continue
        # All child-version tests are shared by all variants, including new fixtures.
        test_paths = [p for p in case["all_changed_paths"] if p.startswith("tests/")]
        for count in range(len(groups) + 1):
            for subset in itertools.combinations(groups, count):
                label = "+".join(subset) or "parent"
                relative = f"work/{cid}/{label}"
                tree = ROOT / relative
                extract_archive(case["parent"], tree)
                applied = [p for p in paths if comp(p) in subset]
                for path in applied + test_paths:
                    dst = tree / path
                    if path in child_tree:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        dst.write_bytes(git_bytes("show", f'{case["commit"]}:{path}'))
                    elif dst.is_file():
                        # Only a file in this newly created, validated experiment variant.
                        assert dst.resolve().is_relative_to(tree.resolve())
                        dst.unlink()
                record["cells"].append({"label": label, "components": list(subset), "tree": relative, "applied_paths": applied, "test_hashes": {p: hashlib.sha256((tree / p).read_bytes()).hexdigest() for p in case["test_paths"]}})
        manifest.append(record)
        print(f"Prepared {index}: {cid}, {groups}, scopes={scopes}", flush=True)
    save(ROOT / "results/replay_manifest.json", {"amendment_sha256": hashlib.sha256((ROOT / "protocol_amendment_01.json").read_bytes()).hexdigest(), "cases": manifest})


def parse_junit(path: Path):
    if not path.exists():
        return {"tests": [], "counts": {}}
    tree = ET.parse(path)
    tests = []
    for t in tree.findall(".//testcase"):
        status = "passed"
        message = ""
        for name in ("failure", "error", "skipped"):
            node = t.find(name)
            if node is not None:
                status, message = name, node.attrib.get("message", "")
                break
        tests.append({"id": t.attrib.get("classname", "") + "::" + t.attrib["name"], "status": status, "message": message[:1500]})
    return {"tests": tests, "counts": {s: sum(t["status"] == s for t in tests) for s in ("passed", "failure", "error", "skipped")}}


def run(indices: list[int], timeout: int, batch: str):
    if sys.platform != "linux":
        raise RuntimeError("Use WSL Linux: upstream tests rely on POSIX shells/process groups")
    manifest_path = ROOT / "results/replay_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if not re.fullmatch(r"[a-z0-9_-]+", batch):
        raise ValueError("Invalid batch label")
    outcomes = ROOT / "results" / batch
    outcomes.mkdir(parents=True, exist_ok=True)
    for case in manifest["cases"]:
        if indices and case["index"] not in indices:
            continue
        for cell in case["cells"]:
            run_id = f'{case["id"]}__{cell["label"]}'
            result_file = outcomes / f"{run_id}.json"
            if result_file.exists():
                print("Already recorded", run_id, flush=True)
                continue
            tree = ROOT / cell["tree"]
            home = tree / (".test-home-" + batch)
            home.mkdir(exist_ok=True)
            # Linux-native temporary files: DrvFS does not implement all operations
            # pytest's FD capture/tempfile machinery relies on.
            temp = Path(sys.prefix).parent / "tmp" / batch / run_id
            temp.mkdir(parents=True, exist_ok=True)
            env = {"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(temp), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONPATH": str(ROOT / "safety") + ":" + str(tree / "src"), "MSWEA_GLOBAL_CONFIG_DIR": str(home / "config"), "MSWEA_SILENT_STARTUP": "1", "LITELLM_LOCAL_MODEL_COST_MAP": "True", "LITELLM_TELEMETRY": "False", "HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
            xml = outcomes / f"{run_id}.xml"
            # Only benchmark-runner slow tests require Docker/downloads. Inspector
            # slow tests are local headless UI and must not be accidentally omitted.
            markers = "not slow" if case["index"] in {4, 7} else "not fire"
            cmd = [sys.executable, "-m", "pytest", "-p", "pytest_asyncio.plugin", "--capture=sys", "--override-ini", "addopts=", "--override-ini", "asyncio_default_fixture_loop_scope=function", "-m", markers, "-q", "--tb=short", "--junitxml", str(xml), *case["test_paths"]]
            start = time.monotonic()
            with (outcomes / f"{run_id}.log").open("w") as log:
                p = subprocess.Popen(cmd, cwd=tree, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                expired = False
                try:
                    code = p.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    expired = True
                    os.killpg(p.pid, signal.SIGKILL)
                    code = p.wait()
            record = {"case": case["id"], "label": cell["label"], "components": cell["components"], "returncode": code, "timeout": expired, "seconds": round(time.monotonic() - start, 3), "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(), "test_hashes": cell["test_hashes"], **parse_junit(xml)}
            save(result_file, record)
            print(json.dumps({k: v for k, v in record.items() if k not in {"tests", "test_hashes", "manifest_sha256"}}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "run"])
    parser.add_argument("--indices", nargs="*", type=int, default=[])
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--batch", default="runs_v2")
    args = parser.parse_args()
    prepare() if args.action == "prepare" else run(args.indices, args.timeout, args.batch)
