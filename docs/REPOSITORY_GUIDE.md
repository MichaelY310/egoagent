# Repository Guide

This document is the map for maintainers. It distinguishes source code,
declarative assets, generated output, runtime state, experiments, and vendored
upstream code.

## Runtime layers

| Layer | Source of truth | Responsibility |
|---|---|---|
| Agent | `agent.py`, `environment.py`, `llm/` | Prompt assembly, progressive capability activation, model/tool loop |
| Shared core services | `egoagent_core/` | Headless SDK, model routing, context, tools, review transactions, checkpoints |
| Flow runtime | `pipeline_engine.py`, `pipeline_schema.py`, `port_graph.py` | Typed nodes, cyclic routing, retries, checkpoints, streaming |
| Harness/session | `harness.py`, `run_harness.py`, `run_coordinator.py` | Harness loading, session history, durable runs |
| Evolution | `self_evolution/`, `ego_ir.py`, `harness_blueprint.py` | Reversible capability and structure evolution |
| Optional product API | `egoagent_server/` | Workspace-scoped HTTP/SSE/WebSocket boundary |
| Workbench | `harness_editor/src/` | IDE-integrated visual product surface |
| Void integration | `void_extension/egoagent-dag-chat/` | Embeds Workbench and chat in the IDE |

Large compatibility modules are being reduced behind these boundaries. New
logic should go into a focused module and be called from the compatibility
entry point; do not further expand `pipeline_engine.py`, `server.py`, or the
main panel component unless the behavior truly belongs there.

The Python modules under `harness_editor/` are compatibility entry points or
aliases, not a second implementation. Edit `egoagent_core/` or `egoagent_server/`
for backend behavior. Use `python -m egoagent_core` without a UI, or
`python -m egoagent_server` for the optional API and Workbench. See
[headless usage and export](HEADLESS_CORE_ZH.md).

## Declarative assets

- `harness/<name>/config.json`: executable Flow templates (cycles are supported).
- `harness/cookbook_*/`: 24 incremental recipes; their short instructions live
  in `harness_editor/src/cookbookCatalog.json`. Supporting subflows are named
  `component_cookbook_*`.
- `identity/<name>/id.json`: persona, inherited capability packs, and model
  policy. Local `ego/skills`, `ego/tools`, and `ego/knowledge` override inherited
  assets only when an Identity genuinely needs specialization.
- `capability_packs/`: canonical reusable Skills shared by Identities.
- `.environment/`: repository workspace capabilities.
- `task_bench/`: versioned tasks, environments, and evaluators.
- `tabletop/`: deterministic tabletop state and transaction rules.

## State and generated output

The following are not source code: `.egoagent/`, `sessions/`, frontend
`node_modules/`, `harness_editor/dist/`, caches, logs, and local provider
configuration. They must stay ignored or be produced by documented build
commands.

`.runtime-logs/`, Flow `.versions/`, experiment `results/` and task-specific
generated Skills are also local state. Keeping them out of Git does not delete
the local evidence. Use explicit, reviewed exports to publish research data.

The bundled Workbench files under the Void extension are build artifacts. The
only hand-edited integration code there is the extension bridge; regenerate
the web bundle with `npm run package:extension`.

## Experiments and historical artifacts

Executable research belongs in `experiments/<study>/`. Small, reviewable result
summaries belong in `experiments/results/`; bulk checkpoints and self-evolution
snapshots are historical data and should be archived outside the runtime path
before removal. Legacy one-off scripts live in `experiments/archive/legacy_scripts/`
and are not imported by product code.

## Vendored upstream code

`meilisearch/` may be present as an ignored local upstream reference checkout;
it is no longer distributed in EgoAgent's tracked source tree.
The product does not require its server or Python package. EgoAgent uses
`capability_registry.py`, a local SQLite catalog with workspace-aware ranking.
Do not mix changes to the upstream tree with EgoAgent changes. Obtain upstream
source separately from https://github.com/meilisearch/meilisearch if needed.

## Dependency direction

```text
declarative assets -> loaders -> Agent/DAG runtime -> local API -> Workbench/Void
                           \-> evaluation and experiments
```

Runtime modules must not import the frontend, experiments, sessions, or the
vendored Meilisearch tree. UI code talks to the runtime only through the local
API.

## Development history

[PROGRESS.md](../PROGRESS.md) is the maintained chronological log. Dated release
checks remain in `docs/DEVELOPMENT_STATUS_*.md`; they describe their own test
scope and must not be read as a guarantee that all features or model behaviors
are production-ready.

