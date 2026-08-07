# EgoAgent

A self-evolving DAG-based Agent system with browser-accessible IDE interface.

EgoAgent combines a code editor (Void, a VSCode fork) with a management panel for orchestrating AI agents through configurable DAG pipelines. Agents can self-evolve their own pipeline structure and reasoning strategies through built-in evolution mechanisms.

## Features

- **DAG Pipeline Engine** — Define agent workflows as directed acyclic graphs with conditional routing
- **Multi-Agent Orchestration** — Run multiple agents (e.g., creative brainstorm + critic) in a single pipeline
- **Self-Evolution** — Agents improve their own pipeline structure and principles over time
- **18 Built-in Harnesses** — ReAct, creative roundtable, debate, evolution cycles, and more
- **Identity System** — Each agent has configurable personality, tools, knowledge base, and LLM settings
- **Browser IDE** — Integrated code editor + management panel accessible via single URL
- **SSE Streaming** — Real-time token-by-token output with multi-agent markers

---

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 20+ (for frontend development)
- A running LLM service (vLLM recommended, OpenAI-compatible endpoint)

### 1. Setup

```bash
git clone https://github.com/MichaelY310/egoagent.git
cd egoagent
pip install pyyaml requests
```

### 2. Configure LLM

Edit identity configs to point to your LLM endpoint. Example (`identity/dante/id.json`):

```json
{
  "llm": {
    "type": "openai",
    "base_url": "http://your-llm-server:8000/v1",
    "model": "your-model-name",
    "api_key": "your-key",
    "temperature": 0.7,
    "max_tokens": 8192
  }
}
```

### 3. Start the Backend API Only

```bash
cd harness_editor
python server.py
# Starts on port 8765
```

### 4. Start with IDE (Full Mode)

```bash
# Terminal 1: Start Void Editor
cd void-web && ./node out/server-main.js --port 8869 --host 0.0.0.0

# Terminal 2: Start unified proxy
python start-all.py
# Access at http://localhost:8880
```

### 5. Frontend-Only Development (React)

```bash
cd harness_editor
npm install
npm run dev
# Opens on http://localhost:5173
# Backend must be running on port 8765
```

---

## Architecture

```
Browser (localhost:8880)
+--------------------+-----------------------------+
|   Void Editor      |     EgoAgent Panel          |
|   (Code IDE)       |  Chat | Identity | DAG |... |
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

Every agent workflow is a DAG (Directed Acyclic Graph). Each node is either:
- **wait_input** — Pauses for user message
- **inference** — Calls an LLM agent (specified by slot name)
- **tool_execution** — Runs tools from a previous inference
- **script** — Executes a Python script

Edges have conditions: `has_tool_calls`, `has_text`, `default`.

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

## Harness Library (18 Pipelines)

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
| `research_loop` | Literature search | search -> read -> synthesize -> loop |
| `text_review_react` | Writing review | draft -> critique -> revise |
| `session_analyzer` | Analyze past sessions | load -> analyze -> report |
| `self_improve` | Prompt self-improvement | evaluate -> improve -> verify |
| `turn_based` | Multi-turn with state | inference with state tracking |
| `improver` | Generic improvement | evaluate -> propose -> validate |
| `new_harness` | Template for new ones | minimal single node |
| `quick_test` | Fast testing | single inference, no tools |
| `verify_test` | Verification pipeline | solve -> verify -> report |
| `test_react` | Testing ReAct | inference with test tools |

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

### Script Injection Flow

```
1. Browser requests http://localhost:8880/
2. Proxy fetches from Void (8869)
3. Proxy detects HTML response with 'workbench' keyword
4. Replaces remoteAuthority: 127.0.0.1:8869 -> 127.0.0.1:8880
5. Injects 4 scripts before </html>
6. Returns modified HTML to browser
7. Scripts create the right-side panel overlay
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

### Partially Implemented

- **Evolve panel user features** — The UI for multi-session harness evolution is built but backend integration for "user provides sessions -> evolver modifies harness" flow needs completion.

- **Exp panel research automation** — Dataset-based evolution benchmarking UI exists but lacks one-click experiment launching.

- **File diff view** — The design exists in EGOAGENT_IDE_DESIGN.md but is not yet implemented in the panel.

- **@ context references** — Designed but not implemented (requires deeper Void Editor integration).

- **Tab completion / inline edit (Cmd+K)** — Requires Void extension API access, not started.

### Not Started (Future)

- Mobile-responsive UI
- MCP tool marketplace integration
- Multi-model routing per node
- Production deployment hardening
- Agent evaluation reports (automated)
- Cross-session memory system

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

### Current State (August 7, 2026)

All core infrastructure is in place. The system is functional end-to-end: a user can open the browser, select a harness, chat with multi-agent pipelines, manage identities, view DAG configurations, trigger evolution, and browse session history. Remaining work is primarily polish, verification, and completing partially-implemented features.

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

## License

Apache-2.0
