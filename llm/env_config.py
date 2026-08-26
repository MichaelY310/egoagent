"""Small, dependency-free loader for local runtime secrets.

The project deliberately keeps provider credentials out of Identity JSON and
tracked configuration.  Entry points call :func:`load_local_env` so a local
``.env.local`` survives restarts while process environment variables retain
the highest precedence.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Mapping


class SecretView:
    """A name-scoped, non-enumerating view over runtime secrets.

    The view deliberately never exposes values through ``repr`` or a
    serializable mapping. Callers must request an explicitly authorized name.
    """

    def __init__(self, allowed_names: Iterable[str] = (), source: Mapping[str, str] | None = None):
        self._allowed_names = frozenset(str(name) for name in allowed_names if str(name))
        self._source = source if source is not None else os.environ

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(name for name in self._allowed_names if name in self._source))

    def resolve(self, name: str) -> str:
        requested = str(name)
        if requested not in self._allowed_names:
            raise PermissionError(f"secret is not authorized for this run: {requested}")
        if requested not in self._source:
            raise KeyError(f"secret is not configured: {requested}")
        return self._source[requested]

    def redacted(self) -> dict[str, str]:
        return {name: "[REDACTED]" for name in self.names()}

    def redact_text(self, value: str) -> str:
        result = str(value)
        for name in self.names():
            secret = str(self._source[name])
            if secret:
                result = result.replace(secret, "[REDACTED]")
        return result

    def redact_value(self, value):
        if isinstance(value, dict):
            return {str(key): self.redact_value(child) for key, child in value.items()}
        if isinstance(value, list):
            return [self.redact_value(child) for child in value]
        if isinstance(value, tuple):
            return tuple(self.redact_value(child) for child in value)
        if isinstance(value, str):
            return self.redact_text(value)
        return value

    def __repr__(self) -> str:
        return f"SecretView(names={list(self.names())!r})"


def _parse_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_local_env(project_root: Path | str | None = None) -> list[str]:
    """Load ignored local env files without overriding the parent process.

    ``.env`` is read first and ``.env.local`` second.  Because existing
    variables are never replaced, an explicit shell/CI setting always wins.
    The return value contains variable names only and is safe to log.
    """

    root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[1]
    loaded: list[str] = []
    for path in (root / ".env", root / ".env.local"):
        if not path.is_file():
            continue
        try:
            lines: Iterable[str] = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            name, raw_value = line.split("=", 1)
            name = name.strip()
            if not name or not name.replace("_", "a").isalnum() or name[0].isdigit():
                continue
            if name not in os.environ:
                os.environ[name] = _parse_value(raw_value)
                loaded.append(name)
    return loaded
