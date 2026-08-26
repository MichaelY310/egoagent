"""Offline-first package catalog, trust store, dependency resolver, and ratings."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from agent_package import PackageError, inspect_package, install_package


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(value))
    if not match:
        raise PackageError(f"invalid semantic version: {value}")
    return tuple(int(part) for part in match.groups())


def version_satisfies(version: str, constraint: str) -> bool:
    current = _version_tuple(version)
    constraint = str(constraint).strip()
    if constraint in {"*", "latest"}:
        return True
    if constraint.startswith("^"):
        base = _version_tuple(constraint[1:])
        upper = (base[0] + 1, 0, 0) if base[0] else (0, base[1] + 1, 0)
        return base <= current < upper
    for operator in (">=", "<=", ">", "<", "="):
        if constraint.startswith(operator):
            target = _version_tuple(constraint[len(operator):].strip())
            return {">=": current >= target, "<=": current <= target, ">": current > target, "<": current < target, "=": current == target}[operator]
    return current == _version_tuple(constraint)


class LocalPackageRegistry:
    def __init__(self, root: Any):
        self.root = Path(str(root)).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir(exist_ok=True)
        self.database = self.root / "registry.sqlite3"
        self.signing_key_path = self.root / "signing.key"
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        connection = self._connect()
        try:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS packages(
                    name TEXT NOT NULL, version TEXT NOT NULL, description TEXT NOT NULL,
                    archive TEXT NOT NULL, sha256 TEXT NOT NULL, manifest TEXT NOT NULL,
                    signature_status TEXT NOT NULL, trust TEXT NOT NULL DEFAULT 'untrusted',
                    verified INTEGER NOT NULL DEFAULT 0, added_at REAL NOT NULL,
                    install_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(name, version)
                );
                CREATE TABLE IF NOT EXISTS ratings(
                    name TEXT NOT NULL, version TEXT NOT NULL, reviewer TEXT NOT NULL,
                    score INTEGER NOT NULL, note TEXT NOT NULL, created_at REAL NOT NULL,
                    PRIMARY KEY(name, version, reviewer)
                );
            """)
            connection.commit()
        finally:
            connection.close()

    def signing_key(self, create: bool = False) -> Optional[bytes]:
        if self.signing_key_path.is_file():
            return self.signing_key_path.read_bytes()
        if not create:
            return None
        key = os.urandom(32)
        temporary = self.signing_key_path.with_suffix(".tmp")
        temporary.write_bytes(key)
        os.replace(temporary, self.signing_key_path)
        return key

    def add(self, archive: Any, *, trust: str = "untrusted", verify_signature: bool = True) -> dict[str, Any]:
        if trust not in {"untrusted", "local", "verified"}:
            raise PackageError("trust must be untrusted, local or verified")
        key = self.signing_key(False) if verify_signature else None
        inspected = inspect_package(archive, signing_key=key)
        manifest = inspected["manifest"]
        name, version = manifest["package"]["name"], manifest["package"]["version"]
        destination = self.artifacts / name / version / f"{name}-{version}.egoagentpkg"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        shutil.copy2(inspected["path"], temporary)
        os.replace(temporary, destination)
        connection = self._connect()
        try:
            connection.execute(
                "INSERT OR REPLACE INTO packages(name,version,description,archive,sha256,manifest,signature_status,trust,verified,added_at,install_count) VALUES(?,?,?,?,?,?,?,?,?,?,COALESCE((SELECT install_count FROM packages WHERE name=? AND version=?),0))",
                (name, version, manifest["package"].get("description", ""), str(destination), inspected["sha256"], json.dumps(manifest, ensure_ascii=False), inspected["signature_status"], trust, int(inspected["signature_status"] == "verified"), time.time(), name, version),
            )
            connection.commit()
        finally:
            connection.close()
        return self.get(name, version)

    def get(self, name: str, version: Optional[str] = None) -> Optional[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute("SELECT * FROM packages WHERE name = ?", (str(name),)).fetchall()
            candidates = [dict(row) for row in rows]
        finally:
            connection.close()
        if version is not None:
            candidates = [item for item in candidates if item["version"] == version]
        if not candidates:
            return None
        selected = max(candidates, key=lambda item: _version_tuple(item["version"]))
        selected["manifest"] = json.loads(selected["manifest"])
        selected["rating"] = self.rating(selected["name"], selected["version"])
        return selected

    def search(self, query: str = "", *, component: Optional[str] = None, trust: Optional[str] = None) -> list[dict[str, Any]]:
        query = str(query).lower().strip()
        connection = self._connect()
        try:
            rows = [dict(row) for row in connection.execute("SELECT * FROM packages ORDER BY added_at DESC").fetchall()]
        finally:
            connection.close()
        result = []
        for item in rows:
            manifest = json.loads(item["manifest"])
            haystack = " ".join([item["name"], item["description"], json.dumps(manifest.get("components", [])), json.dumps(manifest.get("examples", []))]).lower()
            if query and query not in haystack:
                continue
            if trust and item["trust"] != trust:
                continue
            if component and not any(value.get("kind") == component for value in manifest.get("components", [])):
                continue
            item["manifest"] = manifest
            item["rating"] = self.rating(item["name"], item["version"])
            result.append(item)
        return result

    def set_trust(self, name: str, version: str, trust: str) -> dict[str, Any]:
        if trust not in {"untrusted", "local", "verified"}:
            raise PackageError("invalid trust level")
        connection = self._connect()
        try:
            cursor = connection.execute("UPDATE packages SET trust = ? WHERE name = ? AND version = ?", (trust, name, version))
            connection.commit()
        finally:
            connection.close()
        if not cursor.rowcount:
            raise PackageError("package not found")
        return self.get(name, version)

    def rate(self, name: str, version: str, reviewer: str, score: int, note: str = "") -> dict[str, Any]:
        score = int(score)
        if not 1 <= score <= 5:
            raise PackageError("rating must be from 1 to 5")
        if self.get(name, version) is None:
            raise PackageError("package not found")
        connection = self._connect()
        try:
            connection.execute("INSERT OR REPLACE INTO ratings(name,version,reviewer,score,note,created_at) VALUES(?,?,?,?,?,?)", (name, version, str(reviewer)[:100], score, str(note)[:2000], time.time()))
            connection.commit()
        finally:
            connection.close()
        return self.rating(name, version)

    def rating(self, name: str, version: str) -> dict[str, Any]:
        connection = self._connect()
        try:
            row = connection.execute("SELECT COUNT(*) AS count, AVG(score) AS average FROM ratings WHERE name=? AND version=?", (name, version)).fetchone()
        finally:
            connection.close()
        return {"count": int(row["count"] or 0), "average": round(float(row["average"] or 0), 2)}

    def resolve(self, name: str, constraint: str = "*") -> dict[str, Any]:
        candidates = [item for item in self.search() if item["name"] == name and version_satisfies(item["version"], constraint)]
        if not candidates:
            raise PackageError(f"no registry version satisfies {name} {constraint}")
        return max(candidates, key=lambda item: _version_tuple(item["version"]))

    def dependency_order(self, name: str, version: Optional[str] = None) -> list[dict[str, Any]]:
        ordered, visiting, visited = [], set(), set()

        def visit(item):
            identity = (item["name"], item["version"])
            if identity in visited:
                return
            if identity in visiting:
                raise PackageError(f"dependency cycle at {item['name']}")
            visiting.add(identity)
            for dependency, constraint in item["manifest"].get("dependencies", {}).items():
                visit(self.resolve(dependency, constraint))
            visiting.remove(identity)
            visited.add(identity)
            ordered.append(item)

        selected = self.get(name, version)
        if selected is None:
            raise PackageError("package not found")
        visit(selected)
        return ordered

    def install(self, name: str, repository_root: Any, *, version: Optional[str] = None, allow_update: bool = False, allow_untrusted: bool = False) -> dict[str, Any]:
        installed = []
        for package in self.dependency_order(name, version):
            if package["trust"] == "untrusted" and not allow_untrusted:
                raise PackageError(f"package is untrusted: {package['name']}@{package['version']}")
            result = install_package(package["archive"], repository_root, allow_update=allow_update, signing_key=self.signing_key(False), require_signature=package["trust"] == "verified")
            installed.append({"name": package["name"], "version": package["version"], "state": result["state"]})
            connection = self._connect()
            try:
                connection.execute("UPDATE packages SET install_count = install_count + 1 WHERE name=? AND version=?", (package["name"], package["version"]))
                connection.commit()
            finally:
                connection.close()
        return {"ok": True, "installed": installed}
