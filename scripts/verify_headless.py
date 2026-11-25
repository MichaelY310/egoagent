"""Run the core acceptance suite from an exported tree with UI imports forbidden.

Requires requirements-dev.txt. No real model endpoint or API key is used.
"""
from __future__ import annotations

import argparse
import importlib.abc
import os
from pathlib import Path
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"harness_editor", "void_extension", "desktop", "heart_flow", "egoagent_server"}


class NoProductImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in FORBIDDEN:
            raise AssertionError(f"Core attempted to import optional product layer: {fullname}")
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests", action="store_true", help="Also run the exported deterministic core suite")
    args = parser.parse_args(argv)
    for name in FORBIDDEN | {"void-web"}:
        if (ROOT / name).exists():
            raise SystemExit(f"Run this in a pure-core export, not in the product checkout: {name} exists")
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    sys.meta_path.insert(0, NoProductImports())
    # Test runs must not inherit a developer's model credentials, runtime paths or proxy settings.
    for name in list(os.environ):
        if (name.startswith(("EGOAGENT_", "EGO_", "DEEPSEEK_", "OPENAI_", "SILICONFLOW_"))
                or name.endswith(("_API_KEY", "_TOKEN"))):
            os.environ.pop(name, None)
    scratch = ROOT / "tmp" / ("headless-" + uuid.uuid4().hex)
    scratch.mkdir(parents=True)
    os.environ["EGOAGENT_OBSERVATION_DIR"] = str(scratch / "observations")
    import egoagent_core
    for name in egoagent_core.__all__:
        getattr(egoagent_core, name)
    from run_harness import main as run_flow
    result = run_flow(["--harness-dir", str(ROOT / "examples/headless/hello_flow"),
                       "--workspace", str(scratch), "--no-capability-index"])
    assert result[-1]["content"] == "EgoAgent core is running without a frontend."
    print(result[-1]["content"])
    assert not FORBIDDEN.intersection(sys.modules), "Product layer imported during core smoke"
    print("PASS: all public core exports + actual Flow execution without frontend/server")
    if args.tests:
        import pytest
        from scripts.export_core import HEADLESS_TESTS
        return pytest.main([*[str(ROOT / "tests" / (name + ".py")) for name in HEADLESS_TESTS],
                            "-q", "-p", "no:cacheprovider", "--basetemp", str(scratch / "pytest")])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
