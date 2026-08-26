# EgoAgent Architecture

This document describes the current implementation. It is an engineering
contract: new behavior should enter through the owning interface instead of
being copied into an Identity, API route, or visual node.

## 1. Product shape

EgoAgent is one local product with three processes:

```text
Browser :8880
    |
    +-- Void IDE: editor, terminal, diffs and native chat
    |
    +-- Agent Workbench: Build / Evaluate / Library / Improve
                    |
             localhost API :8765
                    |
       Runtime + repositories + trajectories
                    |
          OpenAI-compatible model provider
```

`start-all.py` owns product startup and the localhost-only proxy. Port 8880 is
the user entry point; ports 8765 and 8869 are implementation details.

The Workbench is not a separate Studio product. Its primary path is:

1. **Build** an Agent from Identity + EGO + typed DAG.
2. **Evaluate** it on tasks or a dataset while inspecting node execution.
3. **Improve** it from failures or human feedback.
4. **Publish/reuse** the resulting Identity, Tool, Skill, Knowledge, or DAG.

Secondary workbenches remain under advanced navigation and are lazy-loaded so
they do not slow the code-editing path.

## 2. Dependency direction

```text
UI / local HTTP adapters
          |
Application services
          |
Runtime contracts and orchestration
          |
Domain repositories and immutable events
          |
Filesystem / SQLite / provider transports
```

Dependencies should point downward:

- HTTP translates requests; it does not own a debugger state machine.
- DAG nodes call runtime contracts; they do not construct providers/tools in
  operation-specific branches.
- Identity and Harness files describe behavior; they do not reimplement core
  permissions, tracing, or context safety.
- UI node metadata comes from the backend registry; the frontend does not keep
  a second operation list.

## 3. Runtime assembly

### AgentFactory

`agent_factory.py` is the composition root. It validates Identity locations,
creates a model through `ModelGateway`, attaches workspace and Environment
inputs, and exposes `RuntimeServices`.

Do not instantiate Agent, custom provider and tool execution separately inside
an API feature. Add construction policy to the factory instead.

### ModelGateway

`model_gateway.py` validates the provider contract used by the runtime.
Provider-specific HTTP, retry, streaming resume, metadata, and DNS/proxy logic
remain in `llm/`. DAG and product code depend on the gateway contract.

### ToolPipeline

`tool_pipeline.py` adapts permission-aware Agent execution to typed
`ToolExecutionRequest` / `ToolExecutionResult` contracts. Agent loops and Tool
nodes therefore share workspace guards, approvals, events and outcomes.

## 4. Identity, EGO and capabilities

Identity and EGO remain distinct concepts:

```text
identity/<name>/
  id.json                  stable role, state and personality
  ego/
    system_prompt.txt      behavioral instructions
    skills/                executable or instructional skills
    knowledge/             on-demand knowledge tools
  superego/
    config.json            constraints, permissions and hooks
```

Agents can also load project, Environment, capability-pack and workspace-local
capabilities. `environment.py` and `Agent` own loading; discovery is separate.

### Progressive discovery

`capability_registry.py` uses local SQLite, FTS5 when available,
deterministic CJK-aware lexical ranking, and an optional embedding backend.
Meilisearch is not required. Search returns compact cards for Tools, Skills,
Knowledge, Identities and Harness/SubDAGs. Executable bodies enter context only
after explicit activation.

Workspace-local results receive priority and never leak to another workspace.
Usage, success rate, runtime, impressions and activations are transactional
metrics rather than seeded demo values.

### Reproducible references

`capability_reference.py` separates a stable catalog ID from an immutable
content revision:

```text
CapabilityRef = id + kind + version + source digest
CapabilitySnapshot = Identity revision + visible Tool/Knowledge/Skill refs
```

Each model request references a content-addressed snapshot. The full snapshot
is written once per root trajectory, and again only if activation or Identity
reload changes it. Future file edits cannot silently change an old trajectory.

## 5. DAG definition and execution

### NodeDefinition is the single source of truth

`node_registry.py` defines every visual/runtime node once:

- canonical operation and backward-compatible aliases;
- runtime handler and call style;
- input/output/event contracts;
- side-effect classification;
- editor category, label, icon, color and defaults.

`pipeline_schema.py`, `dag_contracts.py`, `pipeline_engine.py` and the Workbench
all consume this registry. Adding a node requires one definition, one handler
and tests—not several hard-coded frontend lists.

### Explicit data flow

Nodes exchange values through `$ctx`, `$node`, `$last`, declared ports and
event ports. The runtime supports:

- Model/Agent and policy-reviewed Tool execution;
- If, Data, Memory and Context application;
- Loop, Map, Parallel and Join;
- Human approval and permission scopes;
- Process/container execution and workspace transactions;
- Checkpoint, event-log and Output;
- persisted or inline SubDAG/Subflow components;
- Python only as an advanced escape hatch.

`port_graph.py` and `pipeline_schema.py` validate structure. `PipelineRunner`
and `RunContext` own execution. Sync and streaming entry points use the same
runner rather than duplicate loops.

### Run isolation

`interactive_runs.py` owns one `InteractiveRun` per run ID and workspace. Each
has its own input queue, approval nonce, debugger condition, node directive,
outputs and thread. `interactive_execution_service.py` owns pause, step, skip,
input override, retry, stop and approval transitions independently of HTTP.

The HTTP server resolves a run and maps `InteractiveExecutionError` to a status
code. Two browser tabs or workspaces cannot share interactive state.

Long-running background work uses `run_coordinator.py`, its durable SQLite
queue, worker leases, checkpoints, cancellation and event cursor.

## 6. Context and messages

`message_protocol.py` produces one coherent system prefix containing labeled
Identity, policy and compacted-context sections, followed by protocol-valid
user/assistant/tool messages. It does not duplicate a user turn as both system
instruction and user message.

Context has two independent DAG-controlled operations:

- **Compaction** is passively triggered by measured pressure. A normal Model
  node creates a block plan; a Context apply node changes the working surface.
- **Curation** periodically removes or summarizes irrelevant conversation,
  failed calls and oversized observations according to the graph policy.

Both are reversible. `Session.messages` is the working prompt; full audit
messages and immutable trajectory events remain available. Parsing failure
defaults to keeping information.

## 7. Permissions and side effects

`permissions.py`, `security_settings.py`, `secure_command.py` and
`process_backends.py` implement the security boundary.

- Workspace guard confines direct file tools to the selected workspace.
- Tool and Process requests use an allow/ask/deny policy.
- Approval uses a one-time nonce scoped to one interactive run.
- Evolve mode requires explicit mutation targets.
- Container Process nodes run commands in Docker/Podman while model calls stay
  on the host. Workspace mounts decide whether host files can change.
- Secrets are injected at the trusted boundary and redacted from events.

String command filtering is defense in depth, not a sandbox. Untrusted commands
need a container with network disabled, read-only root, resource limits and the
narrowest practical workspace mount.

## 8. Events, replay and training

`event_protocol.py` defines versioned event categories and required payloads.
Unknown extension events remain forward-compatible; core model, tool,
conversation and capability events are validated.

`trajectory.py` writes one ordered, secret-redacted root JSONL stream for the
parent and all descendants. Invariants:

- every `model.request` contains the exact post-compaction messages and tools;
- responses/errors pair by model-call ID;
- tools pair by tool-call ID;
- Agent, Identity, Harness, node and run/parent-run IDs are explicit;
- context replacements and capability snapshots are first-class events;
- payload hashes detect later modification.

Session health is `healthy`, `degraded`, `incomplete` or `invalid`, with
separate replayable and training-ready flags. LLaMA-Factory and VERL exporters
consume validated model-call projections rather than UI chat cards.

`session_branching.py` preserves fork/merge lineage. `training_data.py` stores
ratings, important flags, tags and inclusion decisions against a source hash so
feedback cannot silently move to changed content.

## 9. API and frontend ownership

`harness_editor/server.py` is a localhost adapter. New domain behavior belongs
in a service module called by the route; do not add another state machine to
`do_GET` or `do_POST`. Public resource names pass through
`local_api_security.py` before filesystem access.

Frontend ownership:

- `App.tsx`: Workbench composition and Builder screen;
- `components/DagFormEditors.tsx`: contract-driven DAG fields;
- `components/NodeFieldEditors.tsx`: reusable primitive/script fields;
- `executionProjection.ts`: pure event-to-view projections;
- lazy workbench components: secondary product pages;
- `api/client.ts`: typed transport only.

Vite splits React, XYFlow and generic vendors into stable chunks. Data-heavy
pages load only when opened. Stream tokens are batched before React updates so
the graph is not rendered for every provider delta.

## 10. Repository map

| Area | Owner |
|---|---|
| `agent.py`, `agent_factory.py` | Agent behavior and composition |
| `pipeline_engine.py`, `node_registry.py` | DAG runtime and nodes |
| `harness.py`, `trajectory.py`, `event_protocol.py` | sessions/events/replay |
| `capability_registry.py`, `capability_reference.py` | discovery and versions |
| `permissions.py`, `process_backends.py` | side-effect safety |
| `harness/` | declarative DAGs and components |
| `identity/`, `capability_packs/`, `environment/` | behavior assets |
| `task_bench/`, `experiments/` | evaluation and research |
| `harness_editor/` | local API and Workbench UI |
| `void_extension/`, `void-web/` | IDE integration and packaged runtime |
| `docs/` | user, research and subsystem documentation |

Runtime state belongs under `.egoagent/`, `sessions/`, logs or configured
collection directories and is ignored by Git. Experiments keep code and small
summaries in `experiments/`; cloned repos, models, sandboxes and raw runs do not
belong in product modules.

## 11. Change checklist

1. Identify the owning interface/service.
2. Avoid a second node list, provider constructor, tool executor, path resolver,
   event schema or run-state dictionary.
3. Add a focused regression for the invariant.
4. Run relevant runtime tests and `npm run build` for UI changes.
5. Verify error, cancellation, approval and restart—not only success.
6. Keep provider keys in environment variables; never commit `.env.local`.

See `CONTRIBUTING.md` for commands and `docs/REPOSITORY_GUIDE.md` for the
feature-oriented reading order.
