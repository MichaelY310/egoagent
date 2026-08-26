"""Narrow verl compatibility shim for CUDA under WSL.

verl currently reports CUDA IPC support unconditionally. WSL can expose CUDA
while rejecting cross-process CUDA handles. When explicitly enabled by the
smoke script, make verl select its built-in POSIX shared-memory fallback.
This file is loaded through PYTHONPATH only for that experiment.
"""

from __future__ import annotations

import os


if os.getenv("EGOAGENT_VERL_FORCE_SHM") == "1":
    try:
        from verl.plugin.platform.platform_cuda import PlatformCUDA

        PlatformCUDA.is_ipc_supported = lambda self: False
    except Exception:
        # Some short-lived helper processes do not import verl. Never make
        # Python startup fail merely because the optional shim is unavailable.
        pass
