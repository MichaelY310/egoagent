"""Browser-origin boundary shared by EgoAgent's loopback servers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


LOCAL_ORIGIN_HOSTS = {"localhost", "127.0.0.1", "::1"}


class UnsafeResourcePath(ValueError):
    """Raised when a public resource identifier can escape its storage root."""


def validate_resource_segment(value: object, *, label: str = "resource") -> str:
    """Validate one URL/API supplied filesystem segment.

    Public API identifiers are deliberately *leaf names*, not paths.  Keeping
    that rule in one place prevents GET, PUT and DELETE handlers from drifting
    into different path-traversal behaviour.  Callers must URL-decode the
    segment before passing it here.
    """

    segment = str(value or "")
    if not segment:
        raise UnsafeResourcePath(f"Invalid {label}: name is empty")
    if segment in {".", ".."}:
        raise UnsafeResourcePath(f"Invalid {label}: relative path segments are not allowed")
    if any(character in segment for character in ("/", "\\", "\x00")):
        raise UnsafeResourcePath(f"Invalid {label}: path separators are not allowed")
    if any(ord(character) < 32 for character in segment):
        raise UnsafeResourcePath(f"Invalid {label}: control characters are not allowed")
    # A colon is a drive/alternate-stream separator on Windows.  EgoAgent's
    # resource ids have never needed it, so rejecting it keeps behaviour safe
    # and portable on every host OS.
    if ":" in segment:
        raise UnsafeResourcePath(f"Invalid {label}: ':' is not allowed")
    return segment


def resolve_resource_path(root: Path | str, *segments: object, label: str = "resource") -> Path:
    """Resolve leaf identifiers below ``root`` and prove containment."""

    resolved_root = Path(root).resolve()
    safe_segments = [validate_resource_segment(item, label=label) for item in segments]
    candidate = resolved_root.joinpath(*safe_segments).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as error:
        raise UnsafeResourcePath(f"Invalid {label}: path escapes its storage root") from error
    return candidate


def resolve_registered_root(candidate: Path | str, allowed_roots: Iterable[Path | str], *, label: str = "resource") -> Path:
    """Resolve an opaque path only when it exactly names a registered root.

    Environment APIs historically expose a base64-encoded absolute path for
    compatibility with workspace-local and legacy environments.  Encoding is
    not authorization: the decoded path must match the current registry.
    """

    resolved = Path(candidate).resolve()
    allowed = {Path(item).resolve() for item in allowed_roots}
    if resolved not in allowed:
        raise UnsafeResourcePath(f"Unknown or unregistered {label}")
    return resolved


def is_trusted_local_origin(origin: object) -> bool:
    """Return whether a browser Origin belongs to a loopback EgoAgent page.

    Origin-less requests remain available to local CLI clients. Browsers attach
    Origin to cross-origin fetches and WebSocket handshakes, which lets the
    server reject arbitrary websites without introducing a user-managed token.
    """
    value = str(origin or "").strip()
    if not value:
        return True
    configured = {
        item.strip()
        for item in os.environ.get("EGOAGENT_ALLOWED_ORIGINS", "").split(",")
        if item.strip()
    }
    if value in configured:
        return True
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    if parsed.scheme == "vscode-webview":
        return bool(parsed.hostname)
    if parsed.scheme not in {"http", "https"}:
        return False
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return hostname in LOCAL_ORIGIN_HOSTS or hostname.endswith(".localhost")


__all__ = [
    "UnsafeResourcePath",
    "is_trusted_local_origin",
    "resolve_registered_root",
    "resolve_resource_path",
    "validate_resource_segment",
]
