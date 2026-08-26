#!/usr/bin/env python3
"""Portable EgoAgent product command line."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from product_runtime import (  # noqa: E402
    apply_local_update,
    configure_provider,
    create_diagnostics_bundle,
    list_rollbacks,
    product_diagnostics,
    rollback_update,
    save_product_settings,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="egoagent", description="EgoAgent local product manager")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check dependencies, paths, runtime and ports")
    sub.add_parser("diagnostics", help="Create a redacted diagnostics ZIP")
    sub.add_parser("start", help="Start Void, Studio, and the unified localhost proxy")
    setup = sub.add_parser("configure-provider", help="Configure a provider without storing its key in JSON")
    setup.add_argument("--provider", choices=["deepseek", "siliconflow", "openai", "ollama", "openai_compatible"], required=True)
    setup.add_argument("--model")
    setup.add_argument("--base-url")
    setup.add_argument("--api-key")
    setup.add_argument("--api-key-env")
    network = sub.add_parser("network", help="Configure offline mode, proxy and package mirrors")
    network.add_argument("--offline", choices=["on", "off"])
    network.add_argument("--http-proxy")
    network.add_argument("--https-proxy")
    network.add_argument("--pip-index")
    network.add_argument("--npm-registry")
    update = sub.add_parser("update", help="Apply an explicit local ego.update.v1 archive")
    update.add_argument("archive")
    sub.add_parser("rollbacks", help="List local update rollback snapshots")
    rollback = sub.add_parser("rollback", help="Restore an update rollback snapshot")
    rollback.add_argument("id")
    args = parser.parse_args()

    if args.command == "doctor":
        result = product_diagnostics(ROOT)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["healthy"] else 1
    if args.command == "diagnostics":
        print(create_diagnostics_bundle(ROOT))
        return 0
    if args.command == "start":
        return subprocess.call([sys.executable, str(ROOT / "start-all.py")], cwd=str(ROOT))
    if args.command == "configure-provider":
        result = configure_provider(ROOT, {
            "provider": args.provider, "model": args.model, "base_url": args.base_url,
            "api_key": args.api_key, "api_key_env": args.api_key_env,
        })
    elif args.command == "network":
        changes = {
            "proxy": {key: value for key, value in {"http": args.http_proxy, "https": args.https_proxy}.items() if value is not None},
            "mirrors": {key: value for key, value in {"pip_index_url": args.pip_index, "npm_registry": args.npm_registry}.items() if value is not None},
        }
        if args.offline:
            changes["offline_mode"] = args.offline == "on"
        result = save_product_settings(ROOT, changes)
    elif args.command == "update":
        result = apply_local_update(ROOT, args.archive)
    elif args.command == "rollbacks":
        result = list_rollbacks(ROOT)
    else:
        result = rollback_update(ROOT, args.id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
