# EgoAgent / Void AI IDE product gap analysis

Last updated: 2026-08-08

## Goal and research basis

This document compares the repository's 26-feature IDE design with current
public capabilities from Cursor, TRAE, Windsurf, and VS Code. Primary sources:

- [Cursor Agent overview](https://docs.cursor.com/en/agent/overview)
- [Cursor Tab / quickstart](https://docs.cursor.com/en/get-started/quickstart)
- [Cursor Diffs & Review](https://docs.cursor.com/en/agent/review)
- [Cursor Checkpoints](https://docs.cursor.com/en/agent/chat/checkpoints)
- [Cursor Rules](https://docs.cursor.com/context/rules)
- [TRAE product and CUE](https://www.trae.ai/)
- [TRAE Agent 2.0 architecture, tools, retrieval, and memory](https://www.trae.ai/blog/product_thought_0617)
- [TRAE custom Agents, Rules, Tools, and MCP](https://www.trae.ai/blog/product_thought_0428)
- [Windsurf official documentation index](https://docs.windsurf.com/llms.txt)
- [VS Code AI-powered suggestions](https://code.visualstudio.com/docs/editing/ai-powered-suggestions)
- [VS Code reviewing and controlling Agent changes](https://code.visualstudio.com/learn/foundations/reviewing-and-controlling-agent-changes)

Status: **done** means an end-to-end path exists; **partial** means a useful
local implementation exists but does not yet match a model-backed commercial
version; **backlog** is not claimed as implemented.

## Product matrix

| Capability | Cursor / TRAE / Windsurf pattern | EgoAgent status | Implementation or next boundary |
|---|---|---|---|
| Native Agent chat | Chat/Agent integrated into the IDE | **done** | DAG Chat lives in Void's native Chat container |
| Multi-Agent orchestration | Custom Agents, tools, Agent modes | **done / differentiated** | Harness slots, live DAG execution, sub-Harness events, identities |
| Tab inline completion | Single/multi-line ghost text, FIM | **done (local)** | Deterministic multi-line provider; no key required |
| Next-edit prediction | Jump to the next edit, repository-level edit sequences | **partial** | Inline and symbol continuation exist; cross-file prediction remains model/index dependent |
| Inline natural-language edit | Cmd/Ctrl+K or Ctrl+I | **done (local)** | `Ctrl+I`; changes enter review before being committed |
| Multi-file Agent edits | Agent writes multiple locations/files | **done in DAG tools** | Existing write/patch/multi-edit tools are tracked |
| Per-hunk Accept/Reject | Red/green diff, Keep/Undo each change | **done** | Real Agent and local proposal hunks; file actions and CodeLens |
| Native diff editor | Side-by-side and inline red/green review | **done** | Virtual before/proposed documents opened with `vscode.diff` |
| Checkpoint / rollback | Automatic local snapshots separate from Git | **done / partial automation** | Existing checkpoint API plus safe local proposal rollback |
| Edit conflict protection | Avoid overwriting manual edits during review | **done** | Proposal applies only if the document still matches its tracked state |
| `@file` / `@selection` | Explicit code context | **done** | Active file, selection, symbols, and line are attached to DAG input |
| `@folder` / workspace tree | Project structure in context | **partial** | Workspace and symbol map exist; semantic retrieval is backlog |
| `@web` / `@docs` | Live web and documentation retrieval | **backlog** | Requires an approved network retrieval tool/provider |
| Project rules | Scoped, versioned instructions | **done** | `.egoagent/rules/*.md` is injected into Agent system context |
| `AGENTS.md` | Directory/workspace-scoped instructions | **done at root** | Root `AGENTS.md` is injected; nested scope precedence is backlog |
| Cross-session memory | Auto memories shared across sessions | **done (deterministic)** | Session facts are saved and injected without an LLM summarizer |
| Terminal commands | Agent sees output; edit/approve/deny/turbo | **partial** | `/run` requires a native modal approval and uses Void terminal; output feedback and policies remain |
| Linter/diagnostic loop | Agent reacts to diagnostics | **partial** | Local Quick Review publishes VS Code diagnostics; auto-fix loop remains |
| Code review | Agentic review with inline findings | **done (rule-based local)** | Secrets, dynamic execution, bare except, logs, TODO/FIXME |
| Code map / symbol graph | Navigable code relationships | **done (symbol map)** | Local workspace symbol map; call-graph edges are backlog |
| App preview | In-IDE browser, element/error handoff | **partial** | Configurable local preview; DOM-to-Agent handoff remains |
| AI commit message | Generate from local changes | **done (deterministic)** | Conventional Commit draft from Git change set, no key |
| Rules/memory dashboard | Inspect and manage persistent context | **done** | Native Context tab uses existing backend APIs |
| Session history | Persistent chat/Agent sessions | **done** | History endpoint and Context view |
| Tool cards / live trace | Visible commands, tools, results, blocked calls | **done** | Run tab and event cards |
| Plan / Ask / Agent modes | Different autonomy profiles | **done through Harnesses** | Harness selection replaces a fixed three-mode switch |
| Task queue / steer while running | Queue, stop, redirect active Agent | **partial** | Stop and new DAG input exist; explicit queued tasks are backlog |
| Background/cloud agents | Isolated remote execution | **backlog** | Requires execution infrastructure and auth |
| Git worktrees | Parallel isolated Agent tasks | **backlog** | Should be paired with background task orchestration |
| Parallel solution arena | Multiple Agents explore approaches | **done at DAG level** | Debate/roundtable/multi-Agent harnesses; Git isolation remains |
| Workflows / slash commands | Reusable task recipes | **partial** | `/mock`, `/review`, `/edit`, `/run`, `/map`, `/preview`, `/commit`; file-defined recipes remain |
| Skills / custom Agents | Reusable rules + tools | **done / differentiated** | Identity + Ego/SEGO + Environment + Harness architecture |
| MCP marketplace | Install and govern external MCP servers | **backlog** | Underlying tool model exists; marketplace, transports, and permissions remain |
| Multi-model routing | Select or automatically route models | **done at backend config level** | Model endpoint router exists; per-node/adaptive quality routing needs product polish |
| Usage analytics | Suggested/accepted lines and Agent metrics | **done (local minimum)** | Tab offered/accepted, proposals, accepted/rejected hunks, reviews |
| Voice input | Voice-driven Agent | **backlog** | Requires a speech provider or browser speech policy |
| Remote repository indexing | Server-side repository context | **backlog** | Local-first privacy is currently preferred |
| Enterprise governance | RBAC, SSO, audit, policies | **backlog** | Out of current local research prototype scope |

## Product positioning

EgoAgent should not copy Cursor feature-for-feature at the architecture level.
Its defensible advantage is that **Agent behavior itself is a visible,
editable DAG** with replaceable identities, environments, experiments, and
self-evolution. The Cursor-replacement editing loop must still be excellent:
context → Agent action → native diff → per-hunk decision → checkpoint → test.

The current delivery makes that loop usable without an API key. Model quality,
semantic indexing, background infrastructure, worktree isolation, MCP
governance, and production packaging remain separate product programs rather
than UI checkboxes.
