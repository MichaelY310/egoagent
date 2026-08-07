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

### 3. Start the Backend API

```bash
cd harness_editor
python server.py
# Starts on port 8765
```

This provides the EgoAgent API server with:
- `/v1/chat/completions` — OpenAI-compatible chat (routes to DAG pipeline)
- `/api/harnesses` — List/get pipeline configurations
- `/api/identities` — CRUD agent identities
- `/api/sessions` — Session management
- `/api/evolve` — Trigger evolution runs
- And more (checkpoints, rules, models, experiments, knowledge)

### 4. Start with IDE (Full Mode)

To run the full IDE experience with Void Editor + EgoAgent Panel:

```bash
# First, download and extract void-web (Void Editor web build)
# Place it at ./void-web/ with the binary at ./void-web/node

# Start the Void Editor server
cd void-web && ./node out/server-main.js --port 8869 --host 0.0.0.0 &

# Start the unified proxy (combines editor + API on one port)
cd /path/to/egoagent
python start-all.py
# Access everything at http://localhost:8880
```

The proxy (`start-all.py`) handles:
- Void Editor on the left (code editing, terminal)
- EgoAgent Panel on the right (chat, identity management, DAG editor, evolution)
- WebSocket tunneling for editor connectivity
- SSE streaming passthrough for real-time agent output

### 5. Frontend-Only Development

If you only want to work on the harness editor frontend (React):

```bash
cd harness_editor
npm install
npm run dev
# Opens on http://localhost:5173 (Vite dev server)
# Make sure the backend (python server.py) is running on port 8765
```

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

## Panel Tabs

| Tab | Function |
|-----|----------|
| **Chat** | Interact with agents, select harness/pipeline |
| **Identity** | Create/edit agent identities (personality, tools, knowledge) |
| **Env** | Manage tool and knowledge assignments |
| **Sessions** | Browse conversation history, restore past sessions |
| **Evolve** | Run evolution, view history, compare results |
| **DAG** | Visual pipeline editor, inspect node connections |
| **KB** | Knowledge base management per identity |
| **CP** | Checkpoints - save/restore agent state |
| **Rules** | Project-wide rules that agents follow |
| **Mem** | Agent memory search and inspection |
| **Models** | LLM model registry and routing |
| **Exp** | Experiments - benchmark evolution effectiveness |

## Harness Examples

**react_single** — Standard ReAct loop (think -> act -> observe):
```json
{
  "pipeline": {
    "nodes": {
      "react_step": { "type": "inference", "slot": "solver", "edges": [...] }
    }
  }
}
```

**creative_roundtable** — Multi-agent brainstorm (4 turns):
```
wait_input -> brainstorm(Creator) -> critique(Critic) -> refine(Creator) -> final_eval(Critic) -> wait_input
```

## CLI Usage (Without IDE)

```bash
# Run a single harness directly
python chat.py --harness react_single --identity dante

# Run with a specific pipeline
python chat_react.py --identity coder
```

## Self-Evolution

EgoAgent can evolve its own pipeline structure:

```bash
# Run evolution experiment
cd experiments/evo_benchmark
python run_benchmark.py

# Or trigger via API
curl -X POST http://localhost:8765/api/evolve/run \
  -H "Content-Type: application/json" \
  -d '{"harness": "react_single", "sessions": ["session_id_1", "session_id_2"]}'
```

The evolution system:
1. Collects solving traces from multiple sessions
2. Analyzes patterns of success/failure
3. Proposes structural modifications to the DAG pipeline
4. Validates changes don't break existing capabilities

## Project Structure

```
egoagent/
├── agent.py              # Core agent class (LLM streaming, tool execution)
├── pipeline_engine.py    # DAG execution engine
├── harness.py            # Harness loader/manager
├── environment.py        # Tool/environment management
├── config.yaml           # Global configuration
├── start-all.py          # Single-port proxy server
├── harness/              # 18 pipeline configurations
├── harness_editor/       # Web editor (backend + React frontend)
│   ├── server.py         # API server
│   └── src/              # React + TypeScript source
├── identity/             # Agent identity definitions
├── self_evolution/       # Evolution engine
├── experiments/          # Benchmarks and experiment tracking
└── scripts/              # Utility scripts
```

## License

Apache-2.0
