"""Collect immutable public evidence without executing downloaded agent code."""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
MINI = ROOT / "cache" / "mini-swe-agent"
DGM_URL = "https://drive.usercontent.google.com/download?id=1QzSJkIpYYOtv_kNrC-fEvpW-M3rMm8tk&export=download&confirm=t"
DGM_SIZE = 1010489591


def save_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class RangeReader(io.RawIOBase):
    """Seekable public ZIP; reject servers that ignore Range rather than downloading GBs."""

    def __init__(self, url: str, size: int, budget: int = 512 * 1024**2):
        self.url, self.size, self.budget = url, size, budget
        self.position = 0
        self.bytes_received = 0
        self.session = requests.Session()
        self.cache: dict[tuple[int, int], bytes] = {}

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset: int, whence: int = 0):
        self.position = offset + (self.position if whence == 1 else self.size if whence == 2 else 0)
        if self.position < 0:
            raise ValueError("Negative archive offset")
        return self.position

    def read(self, size: int = -1):
        size = min(self.size - self.position, size if size >= 0 else self.size)
        if size <= 0:
            return b""
        for (start, length), data in self.cache.items():
            if start <= self.position and self.position + size <= start + length:
                offset = self.position - start
                self.position += size
                return data[offset:offset + size]
        wanted = size
        size = min(max(size, 65536), self.size - self.position)
        key = self.position, size
        if key not in self.cache:
            if self.bytes_received + size > self.budget:
                raise RuntimeError("Public-artifact download budget exceeded")
            end = self.position + size - 1
            with self.session.get(self.url, headers={"Range": f"bytes={self.position}-{end}"}, stream=True, timeout=45) as response:
                if response.status_code != 206:
                    raise RuntimeError(f"Expected partial content, received {response.status_code}")
                if response.headers.get("Content-Range") != f"bytes {self.position}-{end}/{self.size}":
                    raise RuntimeError(f"Unexpected range: {response.headers.get('Content-Range')}")
                data = response.raw.read(size + 1)
                if len(data) != size:
                    raise RuntimeError("Truncated or overlong range")
            self.bytes_received += len(data)
            self.cache[key] = data
        self.position += wanted
        return self.cache[key][:wanted]


def catalog_dgm():
    reader = RangeReader(DGM_URL, DGM_SIZE)
    with zipfile.ZipFile(reader) as archive:
        entries = [{"path": i.filename, "size": i.file_size, "compressed": i.compress_size, "crc": i.CRC} for i in archive.infolist()]
    save_json(ROOT / "results" / "dgm_archive_index.json", {"url": DGM_URL, "size": DGM_SIZE, "downloaded_bytes": reader.bytes_received, "entries": entries})
    roots = sorted({e["path"].split("/")[0] for e in entries})
    interesting = [e for e in entries if e["path"].endswith(("metadata.json", ".patch", ".diff", "coding_agent.py", "archive.json"))]
    print(json.dumps({"entries": len(entries), "roots": roots, "downloaded_bytes": reader.bytes_received, "examples": interesting[:35]}, indent=2))


def fetch_dgm(paths: list[str]):
    previous = ROOT / "results" / "dgm_last_fetch.json"
    if previous.exists():
        digest = hashlib.sha256(previous.read_bytes()).hexdigest()[:12]
        save_json(ROOT / "results" / "dgm_fetches" / f"{digest}.json", json.loads(previous.read_text(encoding="utf-8")))
    reader = RangeReader(DGM_URL, DGM_SIZE)
    records = []
    with zipfile.ZipFile(reader) as archive:
        for name in paths:
            destination = (ROOT / "cache" / "dgm" / name).resolve()
            if not destination.is_relative_to((ROOT / "cache" / "dgm").resolve()):
                raise ValueError("Unsafe ZIP path")
            destination.parent.mkdir(parents=True, exist_ok=True)
            data = archive.read(name)
            destination.write_bytes(data)
            records.append({"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    value = {"downloaded_bytes": reader.bytes_received, "files": records}
    save_json(ROOT / "results" / "dgm_last_fetch.json", value)
    digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:12]
    save_json(ROOT / "results" / "dgm_fetches" / f"{digest}.json", value)
    print(json.dumps({"downloaded_bytes": reader.bytes_received, "files": records}, indent=2))


def sample_dgm():
    index = json.loads((ROOT / "results" / "dgm_archive_index.json").read_text(encoding="utf-8"))
    names = {entry["path"] for entry in index["entries"]}
    metas = sorted(n for n in names if n.startswith("swe_dgm/") and n.count("/") == 2 and n.endswith("/metadata.json"))[:40]
    paths = []
    for name in metas:
        paths.append(name)
        patch = name.rsplit("/", 1)[0] + "/model_patch.diff"
        if patch in names:
            paths.append(patch)
    save_json(ROOT / "results" / "dgm_sample_manifest.json", {"selection": "first 40 sorted metadata directories, before reading outcomes", "protocol_sha256": hashlib.sha256((ROOT / "protocol.json").read_bytes()).hexdigest(), "metadata": metas, "paths": paths})
    fetch_dgm(paths)


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(MINI), *args], encoding="utf-8")


def source_at(commit: str, path: str) -> str:
    result = subprocess.run(["git", "-C", str(MINI), "show", f"{commit}:{path}"], capture_output=True, encoding="utf-8")
    return result.stdout if result.returncode == 0 else ""


def component(path: str) -> str:
    parts = path.split("/")
    return parts[2] if len(parts) > 3 else "core"


def normalized_source(source: str) -> str:
    try:
        return ast.dump(ast.parse(source), include_attributes=False)
    except SyntaxError:
        return source


def sample_mini():
    protocol = json.loads((ROOT / "protocol.json").read_text(encoding="utf-8"))
    head = protocol["upstream_regression_sample"]["head"]
    commits = git("log", "--first-parent", "-120", "--format=%H", head).splitlines()
    selected, exclusions = [], []
    for commit in commits:
        parents = git("show", "-s", "--format=%P", commit).split()
        if len(parents) != 1:
            exclusions.append({"commit": commit, "reason": "not single parent"})
            continue
        parent = parents[0]
        paths = git("diff", "--name-only", parent, commit).splitlines()
        source_paths = [p for p in paths if p.startswith("src/minisweagent/") and p.endswith(".py")]
        test_paths = [p for p in paths if p.startswith("tests/") and p.endswith(".py") and not p.endswith("conftest.py")]
        if not source_paths or not test_paths:
            exclusions.append({"commit": commit, "reason": "no changed Python source and test pair"})
            continue
        changes = {}
        for path in source_paths:
            old, new = source_at(parent, path), source_at(commit, path)
            if normalized_source(old) != normalized_source(new):
                changes[path] = len(git("diff", "--unified=0", parent, commit, "--", path).splitlines())
        if not changes:
            exclusions.append({"commit": commit, "reason": "AST unchanged"})
            continue
        groups = sorted({component(p) for p in changes})
        sizes = {g: sum(n for p, n in changes.items() if component(p) == g) for g in groups}
        selected.append({"commit": commit, "parent": parent, "subject": git("show", "-s", "--format=%s", commit).strip(), "date": git("show", "-s", "--format=%cI", commit).strip(), "source_paths": sorted(changes), "test_paths": test_paths, "all_changed_paths": paths, "components": groups, "seed": sorted(groups, key=lambda g: (-sizes[g], g))[0]})
        if len(selected) == protocol["upstream_regression_sample"]["limit"]:
            break
    save_json(ROOT / "results" / "mini_sample.json", {"protocol_sha256": hashlib.sha256((ROOT / "protocol.json").read_bytes()).hexdigest(), "head": head, "cases": selected, "exclusions": exclusions})
    print(json.dumps(selected, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["catalog-dgm", "fetch-dgm", "sample-mini", "sample-dgm"])
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    if args.action == "catalog-dgm":
        catalog_dgm()
    elif args.action == "fetch-dgm":
        fetch_dgm(args.paths)
    elif args.action == "sample-dgm":
        sample_dgm()
    else:
        sample_mini()
