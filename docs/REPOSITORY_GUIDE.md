# Repository Guide

This document is the map for maintainers. It distinguishes source code,
declarative assets, generated output, runtime state, experiments, and vendored
upstream code.

## Runtime layers

| Layer | Source of truth | Responsibility |
|---|---|---|
| Agent | `agent.py`, `environment.py`, `llm/` | Prompt assembly, progressive capability activation, model/tool loop |
| DAG runtime | `pipeline_engine.py`, `pipeline_schema.py`, `port_graph.py` | Typed nodes, routing, retries, checkpoints, streaming |
| Harness/session | `harness.py`, `run_harness.py`, `run_coordinator.py` | Harness loading, session history, durable runs |
| Evolution | `self_evolution/`, `ego_ir.py`, `harness_blueprint.py` | Reversible capability and structure evolution |
| Local product API | `harness_editor/server.py`, `harness_editor/api_extensions.py` | Workspace-scoped HTTP/SSE boundary |
| Workbench | `harness_editor/src/` | IDE-integrated visual product surface |
| Void integration | `void_extension/egoagent-dag-chat/` | Embeds Workbench and chat in the IDE |

Large compatibility modules are being reduced behind these boundaries. New
logic should go into a focused module and be called from the compatibility
entry point; do not further expand `pipeline_engine.py`, `server.py`, or the
main panel component unless the behavior truly belongs there.

## Declarative assets

- `harness/<name>/config.json`: executable DAG templates.
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

`meilisearch/` is an upstream source checkout retained for research/reference.
The product does not require its server or Python package. EgoAgent uses
`capability_registry.py`, a local SQLite catalog with workspace-aware ranking.
Do not mix changes to the upstream tree with EgoAgent changes.

## Dependency direction

```text
declarative assets -> loaders -> Agent/DAG runtime -> local API -> Workbench/Void
                           \-> evaluation and experiments
```

Runtime modules must not import the frontend, experiments, sessions, or the
vendored Meilisearch tree. UI code talks to the runtime only through the local
API.

