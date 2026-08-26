"""Run an EgoAgent Harness from the command line.

Capabilities are indexed locally with SQLite and progressively disclosed to
Agents through ``search_capabilities`` / ``activate_capability``.  No search
daemon or platform-specific binary is required.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from agent_factory import AgentFactory
from capability_registry import CapabilityRegistry
from harness import Harness
from llm.env_config import load_local_env


def _agent_spec(value: str) -> tuple[str, Path]:
    if ":" in value:
        slot, identity_path = value.split(":", 1)
    else:
        identity_path = value
        slot = Path(identity_path).name
    if not slot.strip() or not identity_path.strip():
        raise argparse.ArgumentTypeError("Agent must use slot:identity_path")
    return slot.strip(), Path(identity_path.strip())


def _prompt_spec(value: str) -> tuple[str, str]:
    if ":" not in value:
        raise argparse.ArgumentTypeError("Prompt override must use name:value")
    name, content = value.split(":", 1)
    if not name.strip():
        raise argparse.ArgumentTypeError("Prompt name cannot be empty")
    return name.strip(), content


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an EgoAgent Harness")
    parser.add_argument("--harness-dir", "--harness_dir", dest="harness_dir", type=Path, required=True)
    parser.add_argument("--agents", nargs="+", type=_agent_spec, required=True, metavar="SLOT:IDENTITY")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--prompts", nargs="*", type=_prompt_spec, default=[])
    parser.add_argument(
        "--no-capability-index",
        action="store_true",
        help="Skip the initial catalog refresh (Agents can still refresh it when searching).",
    )
    parser.add_argument(
        "--no-meilisearch",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    workspace = args.workspace.expanduser().resolve()
    project_root = Path(__file__).resolve().parent
    load_local_env(project_root)
    if not args.no_capability_index and not args.no_meilisearch:
        report = CapabilityRegistry(project_root, workspace=workspace).reindex()
        print(
            f"[Capability Library] {report['count']} items · SQLite FTS5={report['fts5']} "
            f"· {report['database']}"
        )

    agent_factory = AgentFactory()
    agents = {
        slot: agent_factory.create(identity_path.expanduser().resolve(), name=slot, workspace=workspace)
        for slot, identity_path in args.agents
    }
    prompts = dict(args.prompts)
    harness = Harness(
        args.harness_dir.expanduser(),
        agents,
        workspace=workspace,
        prompts=prompts or None,
    )
    print(f"[Harness] {harness.name} | slots: {list(agents)}")
    print(f"[Workspace] {workspace}")
    print(f"[Session] {harness.session.save_dir}")
    if prompts:
        print(f"[Prompts] {list(prompts)}")
    try:
        return harness.run()
    except KeyboardInterrupt:
        print("\n[Interrupted] User stopped the run")
        return None


if __name__ == "__main__":
    main()
