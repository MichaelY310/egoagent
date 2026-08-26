# EgoAgent

Runtime trajectory/replay design and training validation:

- [DeepSeek Harness runtime refactor plan](docs/DEEPSEEK_HARNESS_RUNTIME_REFACTOR_PLAN.md)
- [DeepSeek Harness Flow Graph replica](docs/DEEPSEEK_HARNESS_FLOW_REPLICATION.md)
- [Exact trajectory SFT/RL validation](docs/TRAJECTORY_TRAINING_VALIDATION.md)
- [Human feedback and curated training-data workflow](docs/TRAINING_DATA_COLLECTION_ZH.md)
- [Session fork and provenance-preserving merge](docs/SESSION_FORK_AND_MERGE.md)
- [Multi-project and multi-Session portfolio](docs/PROJECT_PORTFOLIO.md)
- [Optional Heart Flow / Flow Relay research demo](docs/HEART_FLOW_RESEARCH_AND_DESIGN.md)

> Start with the [repository guide](docs/REPOSITORY_GUIDE.md), then see the
> current [architecture contract](ARCHITECTURE.md),
> [Capability Library](docs/CAPABILITY_LIBRARY.md), [reversible context
> governance](docs/CONTEXT_GOVERNANCE.md), [self-evolution](docs/SELF_EVOLUTION_INTEGRATION.md),
> [evidence-driven Self-Evolution V2](docs/SELF_EVOLUTION_V2.md),
> [composable DAG components](docs/DAG_COMPONENT_ARCHITECTURE.md),
> and [verification guide](docs/RESEARCH_AND_PRODUCT_VERIFICATION.md).

A self-evolving DAG-based Agent system with browser-accessible IDE interface.

EgoAgent combines a code editor (Void, a VSCode fork) with a management panel for orchestrating AI agents through configurable DAG pipelines. Agents can self-evolve their own pipeline structure and reasoning strategies through built-in evolution mechanisms.

## Features

- **Typed DAG Pipeline Engine** — Explicit data ports, conditions, loops, Map/Join, approvals, retries, budgets, checkpoints and resumable execution; Subflow can also run persisted repeated/static port-event graphs
- **Source-aligned Coding Loops** — Native one-thought/one-action parsing, observation history elision, explicit submit/exit and budget-safe finalization without requiring Python nodes
- **Multi-Agent Orchestration** — Run multiple agents (e.g., creative brainstorm + critic) in a single pipeline
- **Durable Agent Collaboration** — Workspace-local role registry and leased, acknowledged, retryable cross-run messages without adding another DAG component
- **Self-Evolution** — Agents improve their own pipeline structure and principles over time
- **55 Built-in Harnesses** — 42 user-facing workflows/components by default, including 19 tested open-source replicas; 13 internal workers are available on demand
- **Identity System** — Each agent has configurable personality, tools, knowledge base, and LLM settings
- **Progressive Capability Library** — Workspace-first search and on-demand activation for Skills, Tools, Knowledge, Identities, and Harnesses, with real usage/success telemetry and no required search daemon
- **Reproducible Capability Snapshots** — Every model call references the exact content revisions of its Identity, Tools, Skills, and Knowledge for replay and training
- **Reversible Context Governance** — Periodic relevance curation and protocol-safe tool-output compression while retaining an inspectable full history
- **Composable SubDAG Library** — Typed input/output contracts, draggable reusable components, explicit shared-conversation effects, and ordinary Model nodes for summarization/evolution policy instead of hidden runtime calls
- **Identity-backed CoC Table** — Reusable character-card Identities, item-as-Tool ownership, bounded Keeper transactions, deterministic checks and a Workbench character desk
- **Browser IDE** — Integrated code editor + management panel accessible via single URL
- **Browser Agent Runtime** — Typed DOM/viewport observations, real coordinate and keyboard actions, screenshots, verified downloads, dialogs and CAPTCHA human handoff
- **SSE Streaming** — Real-time token-by-token output with multi-agent markers
- **Project & Session Portfolio** — Durable workspace attribution, several live
  Sessions per project, pinned projects/Sessions, project-scoped history, and
  provenance-preserving cross-project Summary/Dialogue merges
- **Optional Flow Relay Demo** — A removable attention router and editable
  ready-to-resume capsule for preserving human flow across parallel Projects

---

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 20+ (for frontend development)
- Optional: a running LLM service (vLLM or another OpenAI-compatible endpoint).
  The IDE's local Tab completion, inline edit, code review, code map, preview,
  commit-message draft and multi-hunk change review work without an API key.

### 1. Setup

```bash
git clone https://github.com/MichaelY310/egoagent.git
cd egoagent
python -m pip install -r requirements.txt
```

### 2. Configure LLM

Provider credentials are read from environment variables and never need to be
saved in an Identity or committed to Git. SiliconFlow example:

```bash
export SILICONFLOW_API_KEY="your-key"
export EGOAGENT_LLM_MODEL="Qwen/Qwen3-8B"
export EGOAGENT_LLM_ENABLE_THINKING="false"
```

PowerShell:

```powershell
$env:SILICONFLOW_API_KEY="your-key"
$env:EGOAGENT_LLM_MODEL="Qwen/Qwen3-8B"
$env:EGOAGENT_LLM_ENABLE_THINKING="false"
```

`SILICONFLOW_API_KEY` automatically selects
`https://api.siliconflow.cn/v1`. Generic OpenAI-compatible providers can use
`EGOAGENT_LLM_BASE_URL`, `EGOAGENT_LLM_MODEL`, and
`EGOAGENT_LLM_API_KEY`. These process-level values safely override the legacy
LLM address in every Identity, so single-Agent, multi-Agent, evolution, Tab
completion, inline edit, review, and commit-message features share one model.
`EGOAGENT_LLM_MAX_RETRIES`, `EGOAGENT_LLM_RETRY_BACKOFF`,
`EGOAGENT_LLM_TIMEOUT`, and `EGOAGENT_LLM_STREAM_RESUME` tune the shared
transport. Retryable status codes honor `Retry-After`; provider-reported token,
cache and request metadata is propagated into DAG run statistics and budgets.

### Contributor: start the backend API only

This is an API-development command, not a second user-facing application:

```bash
cd harness_editor
python server.py
# Starts on port 8765
```

Long-running DAGs can use the durable API instead of holding one HTTP request:

```text
POST /api/runs
GET  /api/runs/<run-id>
GET  /api/runs/<run-id>/events?after=<sequence>
POST /api/runs/<run-id>/cancel
```

The server persists queue state, results, cancellation, checkpoint pointers
and redacted ordered events in `.egoagent/runs.sqlite3`. Worker ownership uses
renewable leases, so an expired worker is safely retried up to `max_attempts`.

Process nodes may run locally or through an isolated Docker/Podman backend:

```json
{
  "op": "进程",
  "backend": "container",
  "container": {
    "engine": "docker",
    "image": "python:3.12-slim",
    "network": "none",
    "read_only_root": true,
    "workspace_access": "rw",
    "pids_limit": 256,
    "memory": "512m",
    "cpus": 1,
    "pull_policy": "never"
  },
  "command": "python",
  "args": ["experiment.py"]
}
```

`GET /api/runtime/container?engine=docker` reports daemon availability. Images
are never pulled implicitly by the secure default; prepare an approved image
before running the graph.

### 3. Start EgoAgent (one IDE)

```bash
# One command installs the native extension and starts Void, backend and proxy.
python start-all.py
# Access at:
# http://127.0.0.1:8880/?folder=/C%3A/Users/<you>/path/to/egoagent  (Windows)
# http://127.0.0.1:8880/?folder=/absolute/path/to/egoagent       (Linux/macOS)
```

Void and the proxy bind to `127.0.0.1`. The launcher disables Void's changing
remote connection token only on this localhost-only link so Chat Webviews and
the Extension Host survive restarts without exposing the IDE to the LAN. The
launcher deliberately rejects a non-local `EGOAGENT_HOST` in this mode.

### Contributor: Workbench frontend preview

The preview is only for frontend iteration. Product users open the Workbench
inside Void at port `8880`.

```bash
cd harness_editor
npm install
npm run dev
# Opens on http://localhost:5173
# Backend must be running on port 8765
```

After a frontend change, package the production assets into the native Void
extension with `npm run package:extension`.

---

## Architecture

```
Browser (localhost:8880)
+--------------------+-----------------------------+
|   Void Editor      |  EgoAgent native surfaces   |
|   Code + Diff      |  Chat + Agent Workbench     |
+--------------------+-----------------------------+
         |                         |
    Void Web (8869)         Backend API (8765)
         |                         |
         +-------- Proxy (8880) ---+
                       |
              LLM Service (vLLM/OpenAI)
```

### Port Layout

| Port | Service | Role |
|------|---------|------|
| 8880 | `start-all.py` | Unified proxy (user-facing) |
| 8869 | `void-web/node` | Void Editor web server |
| 8765 | `harness_editor/server.py` | EgoAgent backend API |

### Proxy Routing Rules (`start-all.py`)

- `/v1/*` and `/api/*` -> Backend (8765)
- `/ego/*` -> Serve custom JS files from `void-web/out/vs/code/browser/workbench/`
- `Upgrade: websocket` -> TCP tunnel to Void (8869)
- Everything else -> Void Editor (8869)
- HTML responses get 4 scripts injected before `</html>`:
  - `egoagent-panel.js` (Chat UI)
  - `egoagent-p1.js` (Identity/Env/Sessions/Evolve/Create tabs)
  - `egoagent-p2.js` (DAG/KB/CP/Rules/Mem/Models/Exp tabs)
  - `egoagent-editor.js` (Editor integration)

---

## Design Philosophy

### Core Idea: Identity as Filesystem

An agent's complete definition lives as a directory:

```
identity/{name}/
+-- id.json              # Personality, role, LLM config
+-- ego/
|   +-- system_prompt.txt  # System prompt
|   +-- skills/          # Tools (each: meta.json + scripts/*.py)
|   |   +-- read_file/
|   |   +-- write_file/
|   |   +-- patch_file/
|   +-- knowledge/       # Knowledge files injected into context
|       +-- python.md
+-- superego/            # (Optional) Constraints, hooks, permissions
    +-- config.json      # whitelist/blacklist rules
    +-- *_hook.py        # pre/post LLM/tool hooks
```

This means agents can **self-modify** — they write files to evolve their own identity.

### DAG Pipeline Engine

Every Agent workflow is a typed DAG. Identity + EGO controls behavior; normal
components control orchestration: Input, Agent/Model, Tool policy/execution,
If, Data (including durable Agent messages), Context, Memory, Loop, Parallel, Map, Join, Human approval, Subflow,
deterministic Process, recoverable Workspace, Checkpoint and Output. Python is
kept only as an advanced escape hatch.

Values move explicitly through `$ctx`, `$node`, `$last` and typed ports. A
Subflow can switch to port-event mode for repeated named outputs, reusable
static pins, dynamic fan-in, concurrent ready executions and port-level resume
without adding another component to the editor. Edges
can follow normal tags, safe expressions, errors or timeouts. The same runner
powers sync, streaming, WebSocket and OpenAI-compatible API paths.

Example — creative_roundtable (4-step multi-agent):
```
wait_input -> brainstorm(Creator) -> critique(Critic) -> refine(Creator) -> final_eval(Critic) -> wait_input
```

### Evolver/Solver Separation

The system separates two concerns:
- **Solver** — The agent that actually does tasks (e.g., coding, math)
- **Evolver** — The meta-agent that analyzes Solver's performance and proposes improvements

This separation prevents the evolving agent from accidentally breaking its own improvement mechanism.

---

## Panel System (12 Tabs)

| Tab | Function | Backend API |
|-----|----------|-------------|
| **Chat** | Interact with agents, select harness | `POST /v1/chat/completions` |
| **Identity** | CRUD agent identities | `GET/POST/PUT/DELETE /api/identities` |
| **Env** | Manage tool/knowledge assignments | `GET/PUT /api/environments` |
| **Sessions** | Browse/restore conversation history | `GET/DELETE /api/sessions` |
| **Evolve** | Run evolution, history, compare | `POST /api/evolve/run`, `GET /api/evolve/history` |
| **DAG** | Visual pipeline editor | `GET /api/harnesses/{name}` |
| **KB** | Knowledge base per identity | `GET/PUT /api/knowledge/{identity}` |
| **CP** | Checkpoints save/restore | `POST /api/checkpoints` |
| **Rules** | Project-wide agent rules | `GET/POST/PUT/DELETE /api/rules` |
| **Mem** | Agent memory search | `GET /api/memory` |
| **Models** | LLM model registry | `GET/POST/DELETE /api/models` |
| **Exp** | Experiments and benchmarks | `GET/POST /api/experiments` |

---

## Harness Library (49 Pipelines)

| Harness | Description | Nodes |
|---------|-------------|-------|
| `react_single` | Standard ReAct loop | inference -> tool_exec -> loop |
| `creative_roundtable` | Multi-agent brainstorm | 4 inference nodes (2 agents) |
| `coder_react` | Coding with 10 tools, 30 steps | inference -> tool_exec -> loop |
| `debate_with_moderator` | Structured debate | proposer -> opponent -> moderator |
| `guarded_react` | Safety-first agent | guardian_check -> inference -> tool_exec |
| `dual_guardian` | Double safety layer | pre_guard -> inference -> post_guard |
| `evolution_cycle` | Basic self-evolution | evaluate -> analyze -> propose -> gate |
| `meta_evolution_cycle` | Meta-level evolution | inner_cycle -> analyze -> meta_gradient -> meta_gate |
| `text_review_react` | Writing review | draft -> critique -> revise |
| `session_analyzer` | Analyze past sessions | load -> analyze -> report |
| `improver` | Generic improvement | evaluate -> propose -> validate |

The additional 32 replica/worker Harnesses reproduce the loop and stop
conditions of OpenHands, Aider, SWE-agent, Continue, AI Scientist, GPT
Researcher, Open Deep Research, Voyager, Generative Agents, MetaGPT, Browser
Use, Stagehand, OpenManus, AutoGPT and Devika. See
`docs/OPEN_SOURCE_HARNESS_REPLICATION.md` for pinned source revisions, the
source-to-DAG mapping, contract coverage and honest external-infrastructure
limits.

The current library passes schema validation for all 32 replica/worker graphs;
45 offline replication contracts cover their core transitions and stop
conditions. The complete Python suite contains 161 tests, and the Harness
editor passes its production TypeScript/Vite build.

---

## Self-Evolution System

### Overview

The evolution system implements 6 research directions for agent self-improvement:

```
                    +-----------------------------+
                    |  Meta-Evolution (Dir 1)     |
                    |  Optimize evolution itself  |
                    +--------------+--------------+
                                   | controls
                    +--------------v--------------+
                    |  Base Evolution Cycle       |
                    |  TextGrad + Gate + Snapshot |
                    +--------------+--------------+
                                   |
        +----------+---------------+---------------+----------+
        v          v               v               v          v
   Identity    Benchmark     Pipeline Search   Lifelong    Self-Play
   Persona     (Dir 3)      (Dir 4)           Learning    (Dir 6)
   (Dir 2)                                    (Dir 5)
```

### Base Evolution Cycle

```
1. Give Agent tasks, observe performance (score 0~1)
2. TextGrad analysis: "What went wrong? How should prompt change?"
3. LLM generates concrete prompt modifications
4. Save snapshot (safety net)
5. Apply modifications
6. Re-evaluate on same tasks
7. Gate decision:
   - improvement > 2% -> accept
   - decline > 2% -> rollback
   - marginal -> conditional accept
8. Record experience to archive
```

### Dir 1: Meta-Evolution

Optimizes the evolution process itself. Two nested loops:
- **Inner loop**: Uses current strategy params to evolve the agent
- **Outer loop**: Observes inner loop effectiveness, adjusts strategy params

Tunable parameters: `gradient_temperature`, `frontier_range`, `gate_threshold`, `distill_strategy`, `max_eval_tasks`, `loop_iterations`

### Dir 2: Identity Persona Preservation

Ensures agents don't lose their personality during evolution. Uses probe questions to measure personality drift before/after evolution.

### Dir 3: Evolution Benchmark

Standardized benchmark suites (coding, reasoning, writing, mixed) to measure evolution effectiveness across domains.

### Dir 4: Pipeline Architecture Search

Evolutionary search over DAG structures. Uses genetic algorithm (population, crossover, mutation) to discover optimal pipeline architectures.

### Dir 5: Lifelong Learning

Prevents catastrophic forgetting. Maintains an experience buffer and distills principles from past successes to guide future evolution.

### Dir 6: Multi-Agent Self-Play

Three-role self-play: Proposer (creates challenges), Solver (attempts them), Judge (evaluates). Elo rating tracks relative improvement.

---

## Experiment Results

### Full Suite Run (2026-07-31)

| Direction | Status | Key Metric |
|-----------|--------|------------|
| Dir 1: Meta-Evolution | PASS (rerun) | Score: 0.717 -> 0.917 (+28%) |
| Dir 2: Identity Persona | PASS | Controllability: 0.5, Drift: acceptable |
| Dir 3: Evolution Benchmark | PASS | Improvement: +3.3%, 2 suites, 40 metrics |
| Dir 4: Pipeline Search | PASS | Best fitness: 0.83, 2 generations, pop=5 |
| Dir 5: Lifelong Learning | PASS | 1 principle distilled, 0 conflicts |
| Dir 6: Self-Play | PASS | Avg score: 0.4, +3.3% improvement |

### E2E Data Verification (2026-08-02, final run)

| Direction | Status | Score |
|-----------|--------|-------|
| Dir 1: Meta-Evolution | PASS | avg=0.967, n=10 |
| Dir 2: Identity Persona | FAIL | avg=0.2 (personality probes too strict) |
| Dir 3: Evo Benchmark | PASS | avg=0.72 |
| Dir 4: Pipeline Search | PASS | fitness=0.81 |
| Dir 5: Lifelong Learning | PASS | 44 streams, buffer=15 |
| Dir 6: Self-Play | PASS | avg=0.5, 3 debates |

### Meta-Evolution Detailed (Dir 1 Rerun)

```
Inner Evolution Cycle:
  - Initial score: 0.717
  - Final score: 0.917
  - Accepted modifications: 2
  - Rejected: 0
  - Rollbacks: 1
  - Duration: 722s

Meta-Evolution Step:
  - Total attempts in history: 31
  - Accept rate: 38.7%
  - Avg improvement per attempt: 0.83%
  - Optimized strategy: {temperature: 0.7, frontier: [0.3, 0.8], gate: 3.0, adaptive distill}
  - Verification score: 0.867
```

### Pipeline Architecture Search Result

Best discovered pipeline: `meta_evolution_cycle` — a self-referential pipeline that runs inner evolution cycles and meta-adjusts its own parameters. This validates the hypothesis that evolution can discover useful pipeline structures automatically.

### Structural Evolution (Self-Repair V2, 2026-08-04)

GSM8K math reasoning tests with self-repairing pipelines:
- Multiple batch runs with format correction scripts
- Iterative repair: agent detects formatting errors -> generates fix script -> re-evaluates

---

## Principles Database

The evolution system maintains a database of learned principles (`self_evolution/data/principles.json`). Examples:

| Type | Principle | Score |
|------|-----------|-------|
| Guiding | "Proceed with main task despite initial errors" | 0.33 |
| Cautionary | "Avoid using tools not explicitly specified" | 0.33 |
| Guiding | "Directly modify task_prompts to enforce behavioral rules" | 0.33 |
| Cautionary | "Verify directory paths exist before operations" | 0.33 |
| Guiding | "Specify clear, actionable rules in task prompts" | 0.33 |

Scores reflect empirical success rate (usage_count vs success_count). Low scores (0.33) indicate newly learned principles with limited validation.

---

## IDE Integration Details

### Native Extension Flow

```
1. Browser requests http://localhost:8880/
2. Proxy fetches from Void (8869)
3. `start-all.py` installs the tracked `egoagent-dag-chat` extension into the local Void runtime
4. The proxy keeps Void's remote/WebSocket traffic on the unified port and serves local Webview resources
5. The extension contributes `EgoAgent DAG Chat` directly into Void's native Chat container
6. Agent chat, execution trace, context, and change review render as native IDE views; no overlay covers the editor
```

### Multi-Agent Streaming Protocol

```
SSE Response Format:
data: {"choices":[{"delta":{"content":"[AGENT_START:Creator]\n"}}]}
data: {"choices":[{"delta":{"content":"Here is my idea..."}}]}
data: {"choices":[{"delta":{"content":"[AGENT_END]\n"}}]}
data: {"choices":[{"delta":{"content":"[AGENT_START:Critic]\n"}}]}
data: {"choices":[{"delta":{"content":"I disagree because..."}}]}
data: {"choices":[{"delta":{"content":"[AGENT_END]\n"}}]}
data: [DONE]
```

Frontend parses these markers to render separate message bubbles per agent with distinct names and colors.

### WebSocket Tunneling

Void Editor uses WebSocket for real-time features (terminal, file watching). The proxy detects `Upgrade: websocket` headers and creates a bidirectional TCP tunnel to port 8869 using `socket.socket()` + `threading.Thread()` for each direction.

---

## Known Issues and Incomplete Features

### Issues

1. **Creative roundtable limited turns** — Sometimes only shows 2 of 4 expected agent turns. The `_on_token` callback has been simplified but needs verification with a live LLM.

2. **Streaming appears non-incremental** — In some cases, messages appear as complete bubbles rather than streaming token-by-token. May be a frontend buffering issue or SSE proxy timing.

3. **DAG panel blank display** — After selecting a harness, the DAG canvas sometimes shows empty. Error handling has been added but the root cause (possibly missing node position data) needs investigation.

4. **Identity Persona (Dir 2) failing** — The personality probe system is too strict. Needs calibration of probe questions and acceptance thresholds.

### Implemented in the native Void extension

- **Evolve panel user features** — The UI for multi-session harness evolution is built but backend integration for "user provides sessions -> evolver modifies harness" flow needs completion.

- **Exp panel research automation** — Dataset-based evolution benchmarking UI exists but lacks one-click experiment launching.

- **Per-hunk change review** — Real DAG writes and local mock edits are split into independently reviewable hunks with Accept/Reject, file-level actions, CodeLens controls, and native red/green Diff editors.

- **Editor context** — Current file, selection, symbols, workspace rules, `AGENTS.md`, checkpoints, memory, and sessions are available from the native Chat view. `@file` and `@selection` are attached to DAG input.

- **No-key local intelligence** — Multi-line Tab ghost text, `Ctrl+I` inline edits, deterministic multi-hunk mock Agent, Quick Review diagnostics, code map, preview, terminal approval, and commit-message drafts work without an AI API key.

- **Rules and memory injection** — `.egoagent/rules`, root `AGENTS.md`, and cross-session memory are now added to each workspace Agent's system context instead of only appearing in a dashboard.

### Not Started (Future)

- Mobile-responsive UI
- MCP tool marketplace integration
- Full next-edit prediction across files (current local provider covers inline/multi-line completion)
- Semantic repository indexing and remote repository indexing
- Background/cloud agents and automatic Git worktrees
- Production deployment hardening
- Agent evaluation reports (automated)
- MCP marketplace UI (the underlying Agent tool architecture remains available)

---

## Research Context and Related Work

### Surveyed Systems

| System | Key Idea | Difference from EgoAgent |
|--------|----------|-------------------------|
| ADAS (Hu et al.) | LLM-based architecture search | EgoAgent adds safety gates + identity preservation |
| AgentEvolver | Evolutionary prompt optimization | EgoAgent separates evolver/solver + adds structural evolution |
| Godel Agent | Self-referential improvement | EgoAgent uses DAG pipelines instead of monolithic prompts |
| EvolveR | Reward-guided evolution | EgoAgent is reward-free (uses TextGrad instead) |
| Agent0 | Minimal self-improving agent | EgoAgent adds multi-agent + pipeline structure |

### Key Design Decisions

1. **TextGrad over RL** — Chose text-gradient (natural language feedback -> prompt modification) over reinforcement learning because: (a) works with any LLM without fine-tuning, (b) modifications are interpretable, (c) doesn't require reward model training.

2. **Gate mechanism** — Every modification must pass a statistical gate before acceptance. This prevents "evolution drift" where many small bad changes accumulate.

3. **Filesystem-as-database** — All state (identities, sessions, principles, harnesses) lives as JSON/text files. No external database needed. Enables git-based version control of agent evolution history.

4. **Single-port proxy** — Rather than requiring users to manage multiple services, everything routes through one port. Simplifies deployment and avoids CORS issues.

5. **Stdlib-only proxy** — `start-all.py` uses only Python standard library (no Flask, no aiohttp). Reduces dependencies and deployment complexity.

---

## Development Log

### Phase 1: Core Engine (June 2026)

- Implemented `agent.py` with streaming LLM calls, tool parsing (XML format), session recording
- Built `pipeline_engine.py` for DAG traversal with conditional edges
- Created `harness.py` for loading/managing pipeline configurations
- Designed identity directory structure (id.json, ego/skills, ego/knowledge, superego)
- Built 6 initial harnesses (react_single, creative_roundtable, debate, evolution_cycle, etc.)
- Integrated Meilisearch for full-text code search (later deprecated in favor of simpler tools)

### Phase 2: Self-Evolution (July 2026)

- Implemented base evolution cycle (TextGrad + Gate + Snapshot)
- Built 6 research directions (meta-evolution, identity, benchmark, pipeline search, lifelong, self-play)
- Ran initial experiment suite (5/6 PASS, Dir1 initially failed due to timeout)
- Reran Dir1 with longer timeout: achieved 0.717 -> 0.917 score improvement
- Built pipeline architecture search using genetic algorithm
- Implemented principles distillation from evolution history
- Created E2E data verification pipeline (10+ verification runs)

### Phase 3: IDE Integration (August 2026)

- Evaluated IDE options: Void (archived VSCode fork, Apache 2.0) vs code-server
- Chose Void for its clean codebase and full VSCode compatibility
- Built single-port proxy with WebSocket tunneling
- Created 4-file panel system (panel.js, p1.js, p2.js, editor.js)
- Implemented 12-tab panel UI with full CRUD for all entities
- Solved multiple integration issues:
  - JS file corruption from overly broad regex replacement
  - WebSocket connectivity loss (added TCP tunnel)
  - Script injection ordering (panel -> p1 -> p2 -> editor)
  - Multi-agent streaming with `[AGENT_START/END]` markers
  - Think-tag double-filtering causing empty outputs
  - Tab switching state management (hiding typing area, context area)

### Current State (August 8, 2026)

The system is functional end-to-end as a native AI IDE: a user can open Void, run or inspect a DAG, attach editor context, work with local completions without a key, propose multi-location edits, review every hunk, run local diagnostics, and restore changes. The detailed competitor matrix and remaining product gaps are tracked in `docs/AI_IDE_PRODUCT_GAP_ANALYSIS.md`.

---

## Project Structure

```
egoagent/
+-- agent.py              # Core agent class (LLM streaming, tool execution)
+-- pipeline_engine.py    # DAG execution engine
+-- harness.py            # Harness loader/manager
+-- environment.py        # Tool/environment management
+-- config.py / config.yaml  # Global configuration
+-- start-all.py          # Single-port proxy server (stdlib only)
+-- chat.py / chat_react.py  # CLI interfaces
+-- harness/              # 18 pipeline configurations
|   +-- react_single/config.json
|   +-- creative_roundtable/config.json
|   +-- meta_evolution_cycle/config.json + scripts/
|   +-- ...
+-- harness_editor/       # Web editor
|   +-- server.py         # Backend API (HTTP server with SSE)
|   +-- api_extensions.py # Extended API endpoints
|   +-- agent_creator.py  # One-sentence agent creation
|   +-- checkpoint_manager.py
|   +-- project_rules.py
|   +-- model_router.py
|   +-- change_tracker.py
|   +-- src/              # React + TypeScript frontend
|   |   +-- App.tsx
|   |   +-- components/
|   |   |   +-- EvolutionPanel.tsx
|   |   |   +-- RightPanel.tsx
|   |   |   +-- Sidebar.tsx
|   |   +-- nodes/PipelineNode.tsx
|   |   +-- types.ts
|   +-- package.json
|   +-- vite.config.ts
+-- identity/             # Agent identity definitions
|   +-- dante/            # Default coding agent (10 tools)
|   +-- creative_brain/   # Creative agent
|   +-- sharp_critic/     # Critic agent
|   +-- coder/            # Coding specialist
|   +-- cat/, dog/, id1/  # Test identities
+-- self_evolution/       # Evolution engine
|   +-- engine.py         # Core evolution loop
|   +-- data/
|       +-- principles.json  # Learned principles database
+-- experiments/          # Experiment infrastructure
|   +-- evo_benchmark/    # Dir 3: benchmark suites
|   +-- pipeline_search/  # Dir 4: architecture search
|   +-- lifelong_learning/  # Dir 5
|   +-- self_play/        # Dir 6
|   +-- self_repair/      # Structural evolution experiments
|   +-- identity_control/ # Dir 2
|   +-- results/          # All experiment output JSONs
+-- scripts/              # Utility and experiment runner scripts
+-- docs/                 # Documentation
+-- ARCHITECTURE.md       # Detailed architecture document
+-- EGOAGENT_IDE_DESIGN.md  # IDE feature design spec
+-- PROGRESS.md           # Development progress tracker
```

## Harness research reproductions

- [Codex Harness → EgoAgent Flow implementation](docs/CODEX_FLOW_REPLICATION.md)
- [AVO / ARC-AGI-3 Flow and self-evolution experiments](docs/AVO_ARC_AGI3_REPLICATION.md)

## License

Apache-2.0
