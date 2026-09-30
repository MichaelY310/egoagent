"""Bounded file fingerprints for checkpoints, not backups of a whole disk.

Incomplete scans are explicitly marked; callers must not treat them as proof
that a workspace is unchanged when resuming a checkpoint.
"""
from __future__ import annotations

import hashlib
import os
import stat
import time
from pathlib import Path


def tree_revision(root, *, ignores=(), cache=None, candidates=None, cancelled=None,
                  max_seconds=3.0, max_bytes=32 * 1024 * 1024, max_files=5000):
    root = Path(root).resolve()
    if not root.exists():
        return {"root": str(root), "digest": "missing", "files": {}, "complete": True}
    cache = cache if cache is not None else {}
    files, skipped = {}, []
    deadline = time.monotonic() + max_seconds
    read_bytes = 0
    complete = True

    def check():
        if cancelled and cancelled():
            raise InterruptedError("Checkpoint revision scan cancelled")
        return time.monotonic() < deadline

    def walk():
        def on_error(error):
            nonlocal complete
            complete = False
            skipped.append(f"unreadable:{type(error).__name__}")
        # Prune BEFORE descending. rglob followed by filtering still traverses
        # every dependency/cache file, particularly expensive on WSL /mnt/c.
        for directory, dirs, names in os.walk(root, followlinks=False, onerror=on_error):
            dirs[:] = sorted(d for d in dirs if d not in ignores)
            for name in dirs[:]:
                path = Path(directory) / name
                if path.is_symlink():
                    dirs.remove(name)
                    yield path
            for name in sorted(names):
                yield Path(directory) / name
            if not check():
                return

    paths = candidates if candidates is not None else ([root] if root.is_file() else walk())
    for path in paths:
        path = Path(path)
        relative = path.relative_to(root).as_posix() if path != root else path.name
        if any(part in ignores for part in Path(relative).parts):
            continue
        if not check() or len(files) >= max_files:
            complete = False
            skipped.append("scan_budget")
            break
        try:
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                files[relative] = "symlink:" + str(path.resolve())
                continue
            if not stat.S_ISREG(info.st_mode):
                skipped.append(relative)
                complete = False  # Never open FIFOs, sockets or device files.
                continue
            marker = (info.st_mtime_ns, info.st_size)
            key = str(path)
            previous = cache.get(key)
            if previous and previous[:2] == marker:
                digest = previous[2]
            elif read_bytes + info.st_size > max_bytes:
                complete = False
                skipped.append(relative)
                continue
            else:
                hasher = hashlib.sha256()
                with path.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        read_bytes += len(chunk)
                        if not check() or read_bytes > max_bytes:
                            complete = False
                            break
                        hasher.update(chunk)
                if not complete and (time.monotonic() >= deadline or read_bytes > max_bytes):
                    skipped.append("scan_budget")
                    break
                after = path.stat()
                if (after.st_mtime_ns, after.st_size) != marker:
                    complete = False
                    skipped.append(relative)
                    continue
                digest = hasher.hexdigest()
                cache[key] = (*marker, digest)
            files[relative] = digest
        except InterruptedError:
            raise
        except OSError as error:
            files[relative] = f"unreadable:{type(error).__name__}"
            complete = False
    if time.monotonic() >= deadline:
        complete = False
    aggregate = hashlib.sha256()
    for name, digest in sorted(files.items()):
        aggregate.update(name.encode("utf-8", errors="replace") + b"\0")
        aggregate.update(digest.encode("ascii", errors="replace") + b"\0")
    return {"root": str(root), "digest": aggregate.hexdigest(), "files": files,
            "complete": complete, "skipped": skipped[:50], "bytes_read": read_bytes}
