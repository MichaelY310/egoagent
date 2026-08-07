# EgoAgent V2 - Development Progress

## Overview

EgoAgent V2 is a self-evolving DAG-based Agent system with a browser-accessible IDE interface. It combines a Void Editor (VSCode fork) with a custom EgoAgent panel for managing identities, harnesses, DAG pipelines, knowledge bases, and self-evolution capabilities.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Browser (localhost:8880)                            │
│  ┌─────────────────┬───────────────────────────┐    │
│  │  Void Editor    │  EgoAgent Panel            │    │
│  │  (Code IDE)     │  Chat / Identity / Env /   │    │
│  │                 │  Sessions / Evolve / DAG / │    │
│  │                 │  KB / CP / Rules / Mem /   │    │
│  │                 │  Models / Exp              │    │
│  └─────────────────┴───────────────────────────┘    │
└─────────────────────────────────────────────────────┘
         │                        │
         ▼                        ▼
┌─────────────────┐    ┌─────────────────────┐
│  Void Web       │    │  EgoAgent Backend   │
│  (port 8869)    │    │  (port 8765)        │
└─────────────────┘    └─────────────────────┘
         │                        │
         └────────┬───────────────┘
                  ▼
       ┌─────────────────────┐
       │  Proxy (port 8880)  │
       │  start-all.py       │
       │  HTTP + WebSocket   │
       └─────────────────────┘
                  │
                  ▼
       ┌─────────────────────┐
       │  vLLM Model Service │
       │  Qwen3-8B-yangyuan  │
       └─────────────────────┘
```

## Core Components

### 1. Agent Core (`agent.py`)
- LLM streaming with think-tag filtering (Qwen3 `<think>...</think>`)
- Tool call parsing (XML format with fallback)
- Session auto-recording
- Multi-identity support

### 2. Pipeline Engine (`pipeline_engine.py`)
- DAG-based execution flow
- Conditional edge routing (has_tool_calls / has_text / default)
- Multi-agent orchestration (e.g., creative_roundtable: 4-node brainstorm→critique→refine→evaluate)

### 3. Harness System (`harness/`)
- `react_single` - Standard ReAct loop
- `creative_roundtable` - Multi-agent brainstorm with creator + critic
- `coder_react` - Coding-focused ReAct (30 steps, 10 tools)
- `debate_with_moderator` - Debate format
- `evolution_cycle` / `meta_evolution_cycle` - Self-evolution pipelines
- `guarded_react` / `dual_guardian` - Safety-aware agents
- And more (18 harnesses total)

### 4. Self-Evolution (`self_evolution/`)
- Evolver/Solver separated architecture
- Structural self-evolution (modify DAG pipelines)
- Principles-based evolution
- Experiment tracking and evaluation

### 5. Harness Editor (`harness_editor/`)
- **Backend** (`server.py`): FastAPI-style HTTP server with SSE streaming
  - `/v1/chat/completions` - OpenAI-compatible chat endpoint with DAG routing
  - `/api/harnesses` - List/get harness configs
  - `/api/identities` - CRUD for agent identities
  - `/api/sessions` - Session management
  - `/api/checkpoints` - Checkpoint save/restore
  - `/api/rules` - Project rules management
  - `/api/models` - Model registry
  - `/api/knowledge` - Knowledge base per identity
  - `/api/evolve` - Evolution trigger and history
  - `/api/experiments` - Experiment management
- **Frontend** (`src/`): React + TypeScript + Vite
  - DAG visual editor (React Flow)
  - Evolution panel with history/compare
  - Full CRUD panels for all entities

### 6. IDE Integration (`start-all.py`)
- Single-port reverse proxy (8880) combining Void + EgoAgent
- WebSocket tunnel for editor connectivity
- Script injection (panel.js, p1.js, p2.js, editor.js)
- SSE streaming passthrough

## Current Status

### Completed ✅
- [x] Agent core with streaming, think-tag filter, tool execution
- [x] Pipeline engine with DAG traversal and conditional edges
- [x] 18 harness configurations
- [x] Multi-agent streaming protocol (`[AGENT_START:name]` / `[AGENT_END]`)
- [x] Void Editor integration with single-port proxy
- [x] WebSocket tunnel for editor connectivity
- [x] Identity CRUD (list/detail/edit/clone/delete)
- [x] Environment management (tools/knowledge assignment)
- [x] Session history (list/view/restore/delete)
- [x] Evolution panel (new run/history/compare/principles)
- [x] DAG visual editor (load harness, display nodes/edges)
- [x] Knowledge Base panel
- [x] Checkpoints panel (save/restore/clear)
- [x] Rules panel (add/edit/delete)
- [x] Memory panel (list/search)
- [x] Models panel (list/add/remove)
- [x] Experiments panel (list/create/detail/stats)
- [x] `_on_token` callback simplified (removed redundant think-tag filter)
- [x] BrokenPipe error handling
- [x] Script injection for all 4 frontend JS files
- [x] Tab switching with proper UI state management

### Known Issues / In Progress ⚠️
- [ ] Creative roundtable shows only 2 of 4 expected agent turns (needs verification after _on_token fix)
- [ ] Streaming appears non-incremental in some cases (full bubble appears at once)
- [ ] DAG panel may show blank after harness selection (error handling added, needs testing)
- [ ] Some panel backend endpoints return mock/placeholder data
- [ ] Evolve panel user-facing features (multi-session harness evolution) partially implemented

### Not Started / Future 🔮
- [ ] Exp panel: research-oriented evolution with dataset evaluation
- [ ] Full streaming verification for multi-agent DAG
- [ ] Production-grade error recovery
- [ ] Mobile-responsive UI

## File Structure (Key Files)

```
egoagent/
├── agent.py                    # Core agent class
├── pipeline_engine.py          # DAG execution engine
├── harness.py                  # Harness loader/manager
├── environment.py              # Tool/environment management
├── config.py / config.yaml     # Global configuration
├── start-all.py                # Single-port proxy server
├── harness/                    # 18 harness configurations
│   ├── react_single/config.json
│   ├── creative_roundtable/config.json
│   └── ...
├── harness_editor/             # Web-based editor
│   ├── server.py               # Backend API
│   ├── src/                    # React frontend source
│   └── dist/                   # Built frontend
├── identity/                   # Agent identities
│   ├── dante/                  # Default coding agent
│   ├── creative_brain/         # Creative agent
│   ├── sharp_critic/           # Critic agent
│   └── ...
├── self_evolution/             # Evolution engine
│   ├── engine.py
│   └── data/
├── experiments/                # Experiment tracking
└── scripts/                    # Utility scripts
```

## Running

```bash
# Start all services (proxy on 8880)
python start-all.py

# Or start individually:
# Backend API
cd harness_editor && python server.py  # port 8765

# Void Editor (requires void-server binary)
void-server --port 8869

# Access in browser
open http://localhost:8880
```

## Model Configuration

Default LLM: `Qwen3-8B-yangyuan` via vLLM
- Endpoint: configurable per identity in `id.json`
- Supports streaming with think-tag filtering
- Temperature/max_tokens configurable per identity
