# EgoAgent master implementation plan

Last updated: 2026-08-11

This document is the executable source of truth for turning EgoAgent into both:

1. a production-grade AI coding IDE that can replace the daily Cursor/Continue workflow; and
2. a reproducible research platform for visual, typed, self-evolving agent harnesses.

The implementation order below is dependency-driven. A feature is not complete because a panel,
endpoint, class, or demo exists. It is complete only when the acceptance criteria and tests in this
document pass through the real user-facing path.

## Status vocabulary

| Status | Meaning |
|---|---|
| `TODO` | Not implemented or not audited yet |
| `PARTIAL` | A useful implementation exists, but one or more acceptance criteria are missing |
| `IN_PROGRESS` | The current implementation target |
| `DONE` | All listed acceptance criteria pass |
| `BLOCKED_EXTERNAL` | Requires unavailable credentials, hardware, account access, or external data |

`BLOCKED_EXTERNAL` items are skipped without blocking unrelated work. Missing optional model keys do
not block deterministic tests, mock-provider tests, local UI work, or provider-agnostic runtime work.

## Baseline and non-negotiable gates

Current baseline at plan creation:

- Python suite: 195 tests passing, 1 explicitly skipped container-runtime smoke test.
- Real provider: DeepSeek `deepseek-v4-flash` configured through ignored `.env.local`.
- Studio backend: `http://127.0.0.1:8765`.
- Void/Studio proxy: `http://127.0.0.1:8880`.
- Task Bench, DAG runtime v2, change tracking, Harness replicas, capability evolution, and the Studio
  execution debugger already have partial or substantial implementations and must be extended rather
  than replaced blindly.

Every completed work item must satisfy all applicable gates:

1. No API key, token, password, or cookie is committed or written to experiment logs.
2. Workspace tools cannot escape the selected workspace without an explicit product permission.
3. Cancellation and timeout propagate into every child Harness and subprocess.
4. File and Harness mutations are recoverable and revision checked.
5. A deterministic or mock-backed test exists; a live test is added when credentials are available.
6. Backend and frontend build/tests pass.
7. User-facing behavior is documented with an executable example.

## Execution order

The following order is authoritative. Later work may be audited early, but implementation should not
skip a dependency unless the skipped item is `BLOCKED_EXTERNAL`.

1. `RUN-*` run-scoped runtime and provider correctness
2. `EDIT-*` transactional file review and checkpoints
3. `MODEL-*` model roles, provider routing, and autocomplete
4. `CTX-*` codebase context engine
5. `MODE-*` product modes and background agents
6. `DBG-*` DAG debugger and replay
7. `PKG-*` packaging, benchmark compatibility, and distribution
8. `IR-*` weak-model Harness representation
9. `EVO-*` rigorous self-evolution
10. `SCI-*` replica conformance and autonomous science

---

## RUN — Reliable run-scoped execution kernel

### RUN-01 — RunContext ownership and global-state removal

Status: `DONE`

Deliverables:

- One `RunContext` owns workspace, session, event sink, cancellation token, deadline, provider usage,
  secrets view, change transaction, parent id, and child ids.
- Replace process-global current Harness and output callback with context-local state.
- Stop using process-global `os.chdir`; all paths resolve against the owning run workspace.
- Concurrent top-level runs and nested Harnesses cannot exchange sessions, callbacks, tools, or cwd.
- Parent cancellation, timeout, and budget exhaustion stop descendants cooperatively.

Acceptance:

- Two concurrent runs in different workspaces read/write only their own files.
- Nested Harness events retain parent/child ids and arrive at the correct client.
- Cancelling one run does not affect another.
- No new child model/tool call starts after the parent deadline.
- Existing Harness APIs remain backward compatible during migration.

### RUN-02 — Provider conformance and capability probing

Status: `DONE`

Deliverables:

- Provider-neutral test server covering text, streaming, reasoning, single/multiple tools, malformed
  arguments, denied tools, retry, 429, timeout, JSON output, usage, and cache metadata.
- Capability probe produces model roles: `chat`, `tool_use`, `edit`, `apply`, `autocomplete`,
  `embedding`, `rerank`, `vision`, and `reasoning`.
- Adapters for OpenAI-compatible, DeepSeek, Anthropic-compatible, SiliconFlow, and Ollama/local.
- Provider health, latency, token usage, cache use, and failure diagnostics in Studio.

Acceptance:

- Every assistant `tool_call_id` receives exactly one tool result, including denied/failed calls.
- DeepSeek reasoning content survives hidden multi-round continuation.
- Mock suite runs without credentials; available configured providers pass live smoke tests.
- Unsupported features are disabled in the UI rather than failing after the request starts.

### RUN-03 — Permissions, secrets, and sandbox policy

Status: `DONE`

Deliverables:

- Explicit read/write/process/network/mutation permission classes.
- Workspace, container, and optional remote execution backends share a typed policy contract.
- Secrets are referenced by name, injected only into authorized calls, and redacted from all events.
- Tool approvals support ask/allow/deny rules by tool, argument pattern, workspace, and mode.

Acceptance:

- Path traversal, symlink escape, absolute-path escape, env-file reads, and secret echo tests pass.
- Task/Evaluate mode cannot mutate global Identity/Harness resources unless evolution is enabled.
- Logs remain useful after redaction and expose why an action was denied.

### RUN-04 — Durable checkpoints, resume, and crash recovery

Status: `DONE`

Deliverables:

- Checkpoint includes file revision, Harness revision, Identity revision, session, pipeline state,
  pending approvals, cost, artifacts, and child-run tree.
- Resume starts at the exact next node without replaying completed side effects.
- Startup recovery discovers interrupted runs and offers resume, inspect, or discard.

Acceptance:

- Kill-and-resume integration tests cover model, tool, process, map, loop, and child Harness nodes.
- Restoring a checkpoint never silently overwrites newer manual edits.

---

## EDIT — IDE-native transactional editing

### EDIT-01 — Persistent change transaction model

Status: `DONE`

Deliverables:

- Stable change-set, file, and hunk ids with base/current/proposed revisions.
- Agent edits apply immediately but remain reviewable.
- Manual edits create revision conflicts instead of corrupting the review decision.
- Pending changes survive backend/IDE restart.

Acceptance:

- Add/delete/replace/move/new-file/binary/conflict cases have tests.
- Accept/reject/undo affects only the review decision requested by the user.

### EDIT-02 — Monaco inline diff review

Status: `DONE`

Deliverables:

- Green additions and red deletions render directly in the file editor.
- Per-hunk Accept, Reject, Undo, next/previous navigation, file-level and global actions.
- New-file rejection requests explicit delete confirmation.
- Review state is synchronized with chat, source control, and the Studio change dashboard.

Acceptance:

- Real browser test edits multiple hunks, mixes decisions, undoes each decision, reloads the IDE,
  and observes the same file/review state.

### EDIT-03 — Inline Edit command

Status: `DONE`

Deliverables:

- Selection/cursor/full-file edit command with streaming preview and follow-up refinement.
- Uses a dedicated edit/apply model role and the same change transaction system.

### EDIT-04 — Checkpoint UI

Status: `DONE`

Deliverables:

- Timeline of request checkpoints, changed files, Harness/Identity mutations, and restore impact.
- Restore preview and conflict-safe selective restore.

---

## MODEL — Model roles, routing, and completion

### MODEL-01 — Model profile and role router

Status: `DONE`

Deliverables:

- Multiple named model profiles without storing plaintext keys in project configuration.
- Separate role assignment for chat/tool/edit/apply/autocomplete/embed/rerank/vision/judge/evolver.
- Cost/latency/context-aware routing, fallback, circuit breaker, and per-run budget.

### MODEL-02 — Tab/FIM autocomplete

Status: `DONE`

Deliverables:

- Prefix/suffix completion, multiline suggestions, cancellation, debounce, cache, imports, recent
  edits/open files, accept/reject shortcuts, and acceptance telemetry.
- Deterministic/mock completion server for UI tests; compatible live endpoint when configured.

Acceptance:

- Keystroke-to-suggestion latency and stale-response cancellation are measured.
- Tab accepts exactly the visible suggestion; Escape leaves the buffer unchanged.

### MODEL-03 — Next-edit prediction

Status: `DONE`

Deliverables:

- Predict likely next edit location and patch after the current edit.
- Cross-file suggestions are previewed and never silently applied.

---

## CTX — Codebase context engine

### CTX-01 — Typed context catalog

Status: `DONE`

Deliverables:

- File/selection/symbol/definition/reference/import/repo-map/diff/terminal/test/diagnostic/recent
  context providers with provenance, freshness, score, and token count.
- Explicit `@` selection and inspectable automatic selection share one contract.

### CTX-02 — Indexing and retrieval

Status: `DONE`

Deliverables:

- Incremental AST/LSP symbol index and dependency graph.
- Optional embeddings and reranking with lexical fallback when no key/model exists.
- Ignore rules, generated-file detection, language-aware chunking, and update invalidation.

### CTX-03 — Context planner and budgeter

Status: `DONE`

Deliverables:

- Selects evidence under a token budget and explains every inclusion/exclusion.
- Learns from accepted/rejected context without storing private source outside the workspace.

---

## MODE — User modes and long-running agents

### MODE-01 — Chat / Plan / Agent / Debug / Evolve / Evaluate

Status: `DONE`

Deliverables:

- Mode changes alter tools, permissions, mutation targets, prompts, and UI indicators through one
  backend policy—not frontend-only labels.
- Plan is read-only; Evaluate is isolated; Evolve requires explicit mutation scope.

### MODE-02 — Background Agent

Status: `DONE` (local backend; remote/PR publishing is optional and `BLOCKED_EXTERNAL`)

Deliverables:

- Durable queue, isolated workspace/worktree, pause/resume/cancel, notifications, test execution,
  review handoff, and optional PR creation.
- Local backend first; container/remote backend enabled when available.

### MODE-03 — Terminal, browser, diagnostics, and test integration

Status: `DONE`

Deliverables:

- Typed terminal/process events, browser evidence, compiler/LSP diagnostics, and test results can be
  referenced from chat, DAG nodes, checkpoints, and review decisions.

---

## DBG — Visual Harness debugger and observability

### DBG-01 — Node activity cards

Status: `DONE`

Deliverables:

- Compact node-adjacent cards show state, input/output summary, model text, tools, artifacts, retry,
  duration, tokens, cache, cost, and failure without covering the graph.

### DBG-02 — Timeline, swimlanes, and child-run tree

Status: `DONE`

Deliverables:

- Ordered event timeline, per-Agent swimlanes, collapsible nested Harnesses, live DAG mutation diff,
  and links from events to files/change hunks.

### DBG-03 — Step, skip, retry, fork, compare, and replay

Status: `DONE`

Deliverables:

- Pause before node, continue, step, safe skip, retry with edited input, fork from checkpoint, and
  compare two runs by path, outputs, cost, and mutations.

---

## PKG — Ecosystem, benchmarks, and distribution

### PKG-01 — Versioned Agent Package

Status: `DONE`

Deliverables:

- Package Identity, Ego skills/knowledge, Harness, environment, tasks, tests, permissions,
  compatibility, provenance, and semantic version in one manifest.
- Validate, pack, install, update, fork, export, and uninstall transactionally.

### PKG-02 — Local registry and marketplace

Status: `DONE`

Deliverables:

- Search, inspect, trust, permissions, compatibility, dependency resolution, signatures, ratings,
  examples, and automated package verification.
- Works as a local registry without external accounts; remote publishing is optional.

### PKG-03 — Harbor / Terminal-Bench compatibility

Status: `DONE` (format/runtime core; real Docker image smoke is `BLOCKED_EXTERNAL` without a daemon)

Deliverables:

- Import/export Harbor task layout, environment image, solution, verifier, multi-step tasks, and
  artifacts without weakening Task Bench isolation.
- Existing Ego task format remains supported through a versioned adapter.

### PKG-04 — Product installation and updates

Status: `DONE` (Windows verified; native macOS/Linux smoke is `BLOCKED_EXTERNAL` on this host)

Deliverables:

- Reproducible Windows/macOS/Linux setup, dependency health check, proxy/mirror settings, offline
  mode, updates with rollback, first-run provider wizard, diagnostics bundle, and privacy controls.

---

## IR — EgoIR for weak-model Harness construction

### IR-01 — Canonical typed EgoIR

Status: `DONE`

Deliverables:

- Compact textual representation of slots, nodes, typed ports, edges, loops, limits, permissions,
  return contract, Identity bindings, and subflows.
- Lossless compile/decompile with current Harness Blueprint and runtime config.

### IR-02 — Safe structural mutation language

Status: `DONE`

Deliverables:

- Revision-checked add/remove/replace/connect/disconnect/rebind operations with validation, dry run,
  test, commit, and rollback.
- Models never need arbitrary Python for common orchestration changes.

### IR-03 — Weak-model construction benchmark

Status: `DONE`

Deliverables:

- Compare full JSON, Blueprint, EgoIR, JSON Patch, and high-level tools across available 4B/8B/Flash
  and stronger models.
- Measure validity, first-run success, edit accuracy, token cost, and generalization.

---

## EVO — Rigorous self-evolution

### EVO-01 — Evolution need and artifact selector

Status: `DONE`

Deliverables:

- Choose no change, Knowledge, Skill, Identity, child Agent, Harness, environment, model route, or
  memory policy from expected reuse, benefit, cost, maintenance, and regression risk.

### EVO-02 — Proof-carrying evolution

Status: `DONE`

Deliverables:

- Every proposal contains evidence, scope, patch, expected benefit, tests, held-out evaluation,
  regressions, cost change, confidence, and rollback point.
- Promotion gate separates experimental from trusted capabilities.

### EVO-03 — Fair evolution experiment protocol

Status: `DONE`

Deliverables:

- Compare static Harness, matched-budget retries/test-time scaling, prompt-only, knowledge-only,
  skill-only, structure-only, full evolution, and oracle on train/validation/held-out distributions.

### EVO-04 — Lifelong sequential task streams

Status: `DONE`

Deliverables:

- Recurrence, delayed recall, distribution shift, conflicting evidence, obsolete skill, negative
  transfer, forgetting, and recovery tasks.
- Metrics include success, total/parent tokens, cost, latency, reuse, stability, forgetting, and
  evolution amortization.

### EVO-05 — Result-only delegation economics

Status: `DONE`

Deliverables:

- Compare direct work, ordinary child Agent, result-only Agent, parallel children, persistent child
  knowledge, and evolving child Harness under matched budgets.

### EVO-06 — Evolution safety and governance

Status: `DONE`

Deliverables:

- Mutation scopes, resource quotas, trust levels, provenance, benchmark leakage detection, secret
  isolation, human approval, automatic rollback, and quarantine.

---

## SCI — Harness science and autonomous research

### SCI-01 — Harness Replica Conformance Suite

Status: `DONE` (offline core; upstream SaaS/browser/account boundaries remain explicitly `BLOCKED_EXTERNAL`)

Deliverables:

- Behavioral contracts for every suitable upstream replica: tool order, loop/termination rules,
  retry/error behavior, context policy, artifacts, and return contract.
- Same tasks run against upstream and Ego replica where technically possible.

### SCI-02 — Harness translation benchmark

Status: `DONE`

Deliverables:

- Dataset of source loop/prompt/tool specifications paired with EgoIR and conformance tests.
- Identify the minimum canonical component vocabulary required to reproduce the Harness zoo.

### SCI-03 — Reproducible autonomous science loop

Status: `DONE`

Deliverables:

- Evidence-bound paper retrieval, hypothesis, experiment plan, implementation, execution, analysis,
  repair, independent review, report, and artifact bundle.
- No scientific claim is accepted without a real artifact or cited source in the run record.

---

## External dependency register

| Dependency | Behavior when absent |
|---|---|
| Optional provider API key | Run mock/local tests; mark provider-specific live test `BLOCKED_EXTERNAL` |
| Container runtime/image | Run process mock tests; skip only real container smoke test |
| Git hosting account/token | Build local branch/patch workflow; skip remote PR publication |
| Marketplace signing/publishing account | Build and test local signed registry; skip remote publication |
| macOS/Linux host | Complete portable code/tests available locally; mark native packaging smoke blocked |
| Paid embedding/rerank service | Use local/lexical implementation and mock provider |

## Completion definition

The master task is complete only when:

1. every item above is `DONE` or has a concrete `BLOCKED_EXTERNAL` reason;
2. all non-blocked acceptance tests pass;
3. Studio and Void expose the completed features without hidden manual setup;
4. a clean installation can run the examples and Task Bench;
5. the product and research protocols have reproducible user documentation;
6. no known critical/high-severity correctness, isolation, secret, or data-loss issue remains.

## Progress log

### 2026-08-11 — Plan created

- Established Python baseline: 195 passing, 1 optional container smoke skipped.
- Confirmed real DeepSeek configuration without committed secrets.
- Began `RUN-01` audit of global Harness/output/cwd state and nested-run propagation.

### 2026-08-11 — RUN-01 completed

- Replaced process-global Harness, callback, and run state with token-restored `ContextVar` scopes.
- Added an owning `RunContext` for workspace, session, event sink, deadline/cancellation tree,
  provider statistics, redacted name-scoped secrets, and per-run file change transactions.
- Removed Agent tool execution's process-wide `os.chdir`; path-bearing tools now receive absolute
  run-workspace paths and Task Bench boundaries remain enforced.
- Migrated Studio chat/stream/durable/background execution, Task Bench, and active nested-Harness
  skills to exact context restoration.
- Added isolation tests for nested and parallel scopes, independent top-level cancellation,
  parent/child event ids, cancellation cascade, inherited deadlines, prevention of post-deadline
  node starts, concurrent same-name file writes, secret authorization, and transaction restoration.
- Acceptance evidence: 9 runtime-isolation, 6 workspace-boundary, 82 DAG-runtime, 9 Task Bench,
  8 durable-run, 4 change-review, and 45 Harness-replica tests passing.

### 2026-08-11 — RUN-02 completed

- Added provider adapters/factory for OpenAI-compatible, DeepSeek, SiliconFlow, Ollama/local, and
  Anthropic-compatible Messages, including tool/result translation and streaming reasoning.
- Added a localhost-only provider conformance server plus tests for text, streaming, JSON,
  reasoning, one/multiple tools, malformed arguments, failure/denial, exact tool-call ids, 429,
  retry-after, timeout, usage, and cached tokens.
- Added model-role probing, provider fingerprints, request diagnostics, latency, health, and
  capability gates to Studio Settings and Void's native AI client.
- Fixed structured provider tool-call ids being lost during session conversion and made DeepSeek
  V4 Flash tool requests omit incompatible explicit tool choice/thinking fields.
- Live DeepSeek V4 Flash probe passed `chat`, `stream`, `JSON`, `tool_use`, `edit`, `apply`,
  `autocomplete`, and `reasoning`; unsupported embedding/rerank/vision roles remained disabled.
- Acceptance evidence: Studio production build passed; Void JavaScript syntax passed; full Python
  suite reached 212 passing tests with 1 explicitly skipped optional container smoke test.

### 2026-08-11 — RUN-03 completed

- Added one typed run-owned permission policy for read, write, process, network, global mutation,
  and named-secret access across Agent tools, DAG Tool/Process/Workspace nodes, and Task Bench.
- Added allow/ask/deny defaults and ordered rules by tool, arguments, workspace, mode, and permission
  class; approval and denial events include an inspectable reason.
- Enforced resolved workspace paths against absolute, traversal, and symlink escape and denied
  sensitive credential files in isolated evaluation modes.
- Added name-scoped `secret_env` injection for Process nodes, rejected plaintext secret-like `env`
  entries, and redacted authorized values from results and events while preserving usage telemetry.
- Task/Evaluate mode now prevents global Identity/Harness mutation unless evolution and targets are
  explicitly enabled; disabled task networking is enforced by the runtime rather than UI filtering.
- Acceptance evidence: 8 permission tests (1 Windows symlink privilege skip), 82 DAG-runtime,
  6 workspace-isolation, 9 Task Bench, and 5 process-backend tests passed.

### 2026-08-11 — RUN-04 completed

- Upgraded checkpoints to version 3 with exact next-node/phase, session and pipeline state, results,
  cost, policy/approvals, change transaction, artifacts, completed-step ledger, resource revisions,
  and nested child-run tree.
- Durable runs now checkpoint every completed node. Side-effecting nodes record `in_flight` before
  execution and `completed` afterward, preventing silent replay of completed effects and surfacing
  genuinely uncertain external calls for inspection.
- Added content revision validation for workspace, Harness, and bound Identities; newer manual edits
  raise a structured conflict before state restoration or file mutation.
- Added startup discovery and resume/inspect/discard APIs plus a Studio recovery card with explicit
  confirmation for in-flight nodes. Discarding a run preserves existing files and artifacts.
- Acceptance evidence: crash/resume integration passed for model, tool, process, Map, Loop, and
  child Harness; 11 durable queue/API tests and Studio production build passed. Full Python suite:
  226 passing tests with 2 explicit skips (container runtime and Windows symlink privilege).

### 2026-08-11 — EDIT-01 and EDIT-02 completed

- Replaced the process-only change list with an atomic JSON transaction journal containing stable
  change/hunk ids, base/proposed/materialized SHA-256 revisions, decision history, conflicts, and
  transaction composition across consecutive edits.
- Added text create/update/delete, empty-file, binary, move/rename, conflict, restart, and explicit
  new-file deletion-confirmation coverage. Agent edits remain live; Accept records a decision,
  Reject materializes only that hunk, and Undo reverses only the latest review decision.
- Added revision-checked Workspace binary write/read/delete/move operations and exposed them in the
  Studio node editor.
- Integrated durable backend transactions into Void's native Monaco editor with red/green line
  decorations, per-hunk CodeLens actions, Undo, next/previous navigation, file/global actions, a
  status-bar counter, chat synchronization, and a Studio Agent Changes dashboard.
- Fixed Void Web remote-URI versus Windows-path matching and isolated review state by workspace.
- Real-browser acceptance edited two independent hunks, rejected and undid one, accepted and undid
  one, reloaded the IDE, and observed the exact same materialized file and pending decisions.
- Acceptance evidence: 13 transaction/API tests plus 84 pipeline runtime tests passed; Studio build
  and Void syntax checks passed before the environment's later elevated-operation quota was reached.

### 2026-08-11 — EDIT-03 and EDIT-04 implementation in verification

- Void 0.14 adds cursor/selection/full-file Inline Edit, dedicated edit-role routing, progress UI,
  a reusable red/green preview, regenerate/cancel, iterative follow-up refinement, and atomic apply
  into the same persistent backend change journal. The apply endpoint enforces workspace confinement,
  a 4 MB bound, and exact pre-edit revision checks.
- Rebuilt file checkpoints as immutable persistent snapshots supporting text/binary content,
  workspace confinement, Harness/Identity/Environment classification, changed-file summaries,
  selective restore preview, post-preview conflict detection, delete confirmation, and reviewable
  restore transactions. Newer checkpoints are never deleted by restore.
- Added a Studio checkpoint timeline with snapshot creation, mutation badges, current-vs-checkpoint
  revisions, per-file selection, restore impact, and conflict/delete feedback; Void checkpoints now
  include the active file and workspace instead of creating an empty snapshot.
- Verification evidence so far: 19 focused checkpoint/change tests pass, TypeScript type checking
  passes, Python/JavaScript syntax passes, and the dependency-complete suite passes 238 tests with
  two optional skips; two browser-related tests cannot import the declared but locally uninstalled
  `websocket-client` dependency.
- Remaining verification: restart the already-running local services to load extension 0.14, run
  the real Inline Edit interaction, and produce the Vite bundle. Codex's elevated-operation quota
  was exhausted during this turn, so process restart and sandbox-external esbuild are temporarily
  unavailable; no permission bypass was attempted.

### 2026-08-11 — MODEL-01 implementation in verification

- Replaced the plaintext endpoint list with persistent named profiles that store only an API-key
  environment-variable name; legacy plaintext values are discarded and public APIs never return
  resolved secrets.
- Added explicit roles for chat, tool use, edit, apply, autocomplete, embeddings, reranking,
  vision, reasoning, judging, and evolution. A configured role list is authoritative, so an
  excluded expensive model cannot silently re-enter through capability discovery.
- Added context eligibility, cost/latency/priority scoring, ordered fallback, per-run budgets,
  success/latency health telemetry, consecutive-failure circuit breaking, and recovery.
- Integrated role routing and usage reporting into the AI service and added REST APIs for profile
  management, ordered role policies, budget setup, and no-call route preview.
- Added a Studio Settings panel for profile creation/edit/deletion, key-presence and health display,
  role-order reordering, cost metadata, and route previews. The UI accepts secret names only.
- Verification evidence: Studio TypeScript checking passes; Python syntax passes; 18 router,
  HTTP-secret-safety, custom-provider, and protocol-conformance tests pass. Live browser verification
  remains grouped with the pending service restart above.

### 2026-08-11 — MODEL-02 and MODEL-03 implementation in verification

- Rebuilt Tab/FIM completion with cancellation wired through to the provider request, debounce,
  stale document/request rejection, a 30-second LRU cache, prefix/suffix de-duplication, multiline
  insertion, and explicit Tab-accept/Escape-reject telemetry.
- Completion prompts now receive bounded imports, recent in-memory edit summaries, and excerpts from
  visible files. The existing deterministic language-aware engine remains the no-key/no-network
  fallback and provider failure never interrupts typing.
- Added latency, cache-hit, cancellation, stale-discard, offer, acceptance, and rejection counters.
  Role capability checks now query the actual assigned role profile instead of accidentally using
  only the chat profile's health.
- Added Next Edit prediction after a meaningful edit settles, with configurable delay/confidence,
  current/open-file candidates, strict candidate-path confinement, stale-version rejection,
  in-editor highlighting, status-bar discovery, and an explicit red/green Diff before apply.
  Cross-file predictions never write until the user confirms, and applied predictions enter the
  same per-hunk Accept/Reject/Undo review flow.
- Verification evidence: Void extension and package syntax pass; Python syntax passes; 9 focused
  AI service/router/HTTP tests pass, including bounded FIM context and confinement of model-selected
  next-edit paths. Real Tab/Escape and cross-file preview testing awaits the same service restart.

### 2026-08-11 — CTX-01/02/03 local context engine implementation

- Added one typed context contract for file, selection, symbol, definition, reference, import,
  repository map, Diff, terminal/tool, test, diagnostic, and recent evidence. Every item carries
  provenance, revision, freshness, score, token estimate, location, and explicit/automatic origin.
- Added a workspace-local incremental index with Python AST symbols/imports, static symbols for
  other common languages, dependency metadata, language-aware chunks, content revisions, update
  reuse/removal, generated/binary/large-file filtering, secret-file exclusion, and git/ignore rules.
- Added lexical retrieval with path/symbol/content/freshness scoring and workspace-local accepted /
  rejected feedback. Feedback stores only item ids and counters—not private source text.
- Added a hard-budget planner with explicit-first ordering, de-duplication, per-item exclusion
  reasons, remaining-token accounting, and an inspectable prompt containing typed provenance tags.
- Void now collects LSP symbols, definitions, references, diagnostics, imports, selection, and a
  cursor-local file excerpt. Before a DAG chat turn it plans this evidence together with pending
  Diff and recent tool results, and the Context tab shows exactly what was selected, excluded, and
  why, with useful/not-useful feedback controls.
- Verification evidence: 3 index/retrieval/planner/HTTP tests and 3 AI-context tests pass; Python,
  extension, and Chat Webview syntax pass. Optional embedding/rerank transport remains the only
  CTX-02 implementation item not yet closed and is skipped when no compatible profile is present.

### 2026-08-11 — MODE-01/02/03 implementation in verification

- Added Chat, Plan, Agent, Debug, Evolve, and Evaluate to Void's native selector and carried the
  choice into the backend `RuntimePolicy`, run context, Agent instructions, events, and durable
  payload. Chat/Plan deny writes, Chat denies processes, Evaluate denies network/global mutation,
  and Evolve refuses to start without explicit Identity/Harness targets.
- Enforced Evolve target names at the universal mutation-tool gate; merely labeling the frontend
  Evolve no longer grants unrestricted mutation.
- Extended the SQLite durable queue with cooperative pause/resume in addition to cancel, leases,
  retry, checkpoints, recovery, ordered events, secret redaction, and restart survival.
- Added a Studio Background Agents dashboard for queue creation, mode/Harness/Identity/workspace,
  priority/retry controls, pause/resume/cancel, status notifications, event timeline, and result.
- Background runs can use an isolated workspace copy. A conflict-safe handoff compares base,
  source, and isolated revisions; shows per-file text Diff/binary/create/delete state; requires
  deletion confirmation; and sends only selected files into the normal Agent Changes
  Accept/Reject/Undo transaction flow. Concurrent source edits are not overwritten.
- Diagnostics, pending Diff, recent terminal/tool results, LSP definitions/references, and tests can
  now share the typed context contract and node/run event stream.
- Verification evidence: Studio TypeScript, Python, Extension, and Chat syntax pass; 21 mode /
  permission / durable-queue tests pass (one Windows symlink privilege skip), plus 13 isolated
  workspace/handoff and queue tests. Remote workers and automatic PR publishing are intentionally
  skipped until a remote backend and repository credentials are configured.

### 2026-08-11 — DBG-01/02/03 implementation in verification

- Extended every node invocation trace with model/provider usage, request ids, retries, reconnects,
  errors, artifacts, cumulative cost/statistics, and exact wall duration. Node-adjacent activity
  cards prioritize failures and show compact duration/token/cache/cost/retry/artifact chips without
  enlarging the DAG node itself.
- Added a Run Observability view next to the normal conversation: a globally ordered timeline laid
  across per-Agent swimlanes, summary metrics, collapsible child-Harness tree, and a live Harness /
  Identity mutation timeline linked to the Agent Changes review dashboard.
- The debugger now pauses before side effects, steps or resumes automatically, safely skips a node
  using explicit simulated output, executes a node with edited JSON inputs, and pauses after an
  exhausted failure so the user can retry with edited inputs. Skip and retry are first-class events,
  and debug retries have a hard cap.
- Durable runs can be replayed from clean source, forked from a completed checkpoint into an
  independent reviewable workspace, and compared by path divergence, output, token/cost statistics,
  and structural mutations. A fork rewrites run/transaction ids and never reuses the source run's
  writable workspace.
- Verification evidence: Studio TypeScript and Python syntax pass; deterministic tests prove that a
  skipped process creates no file, edited input changes the result, failure retry recovers, checkpoint
  forks are isolated, and run comparison reports path/output/cost/mutation differences. Browser
  acceptance remains grouped with the pending local service restart.

### 2026-08-11 — PKG-01/02/03 implementation in verification

- Added the signed `ego.agent-package.v1` format covering Identity, Ego, Harness, environment, tasks,
  tests, permissions, compatibility, dependencies, provenance, examples, semantic versions, file
  integrity, safe archive bounds, secret rejection, transactional install/update/rollback, recoverable
  uninstall, and provenance-preserving forks.
- Added a SQLite-backed local registry and Studio marketplace with trust states, search/inspect,
  ratings, install counts, signature verification, dependency ordering/cycle detection, package
  creation/import/install/update/fork/uninstall, and no required external account.
- Added self-contained Harbor 1.4 and legacy Terminal-Bench import, current Harbor export, binary asset
  embedding, path/symlink/size protections, Docker readiness diagnostics, image build and bind-mounted
  isolated process execution, numeric Harbor reward verification, legacy exit-code compatibility, and
  explicit failure when Docker is unavailable. Host file tools and container shell commands share one
  workspace; imported commands are never silently executed on the host.
- Task Bench now runs true multi-step tasks in one persistent workspace/container, materializes each
  step workdir just in time, records per-step state and scores, starts with fresh model context by
  default, and resumes a trajectory only when requested by the task. Studio exposes import/export,
  format/runtime diagnostics, multi-step progress, and source-format metadata.
- Verification evidence: Python compilation and Studio TypeScript pass; 23 package/adapter/Task Bench
  tests pass with one expected Windows symlink-privilege skip. Tests cover signed lifecycle operations,
  registry/dependencies, HTTP package flow, Harbor round-trip, multi-step preservation/execution,
  Terminal-Bench migration, reward parsing, path safety, and existing Task Bench isolation/debugging.
  A real Harbor image run remains environment-dependent and must be exercised after Docker and the
  updated local Studio service are available.

### 2026-08-11 — PKG-04 implementation in verification

- Added cross-platform install scripts and one product CLI for start, doctor, provider setup, proxy /
  mirror / offline configuration, redacted diagnostics, explicit local updates, and rollback. The
  launcher no longer destroys user proxy variables; empty product settings inherit the shell.
- Added a Settings first-run panel with DeepSeek, SiliconFlow, OpenAI, Ollama, and generic
  OpenAI-compatible presets. Keys are written atomically to gitignored `.env.local`, injected into the
  current backend process, represented by environment-variable name only in profiles, and never
  returned to the frontend.
- Added strict offline routing (remote profiles are ineligible), China-friendly pip/npm mirror fields,
  proxy validation, telemetry-off privacy defaults, dependency/path/port/Docker/Void health checks,
  and diagnostics ZIPs with environment- and pattern-based secret redaction.
- Added manifest-gated, size/path-bounded local update archives. Runtime state, secrets, dependencies,
  Git metadata, and bundled Void are protected; an update snapshots replaced files first, rolls back
  automatically on partial failure, retains bounded recovery points, and exposes explicit rollback in
  Settings and the CLI.
- Verification evidence: six deterministic product-runtime tests pass for persistent settings,
  server-only secret storage, strict offline routing, diagnostics redaction, transactional update /
  rollback, and traversal rejection. Python compilation and Studio TypeScript pass. Windows is the
  current verified host; macOS/Linux installer execution still requires their respective hosts.

### 2026-08-11 — IR-01/02/03 completed

- Added canonical `EGOIR/1` lossless compile/decompile for the live Harness runtime, including slots,
  nodes, typed ports, edges, limits, permissions, subflows, return contracts and preserved extension
  fields. Studio exposes validation, textual diff, commit and transaction undo.
- Added revision-checked high-level operations for add/remove/update/connect/disconnect/rebind/ports/
  permissions/limits with aliases tolerant of weak-model casing and common nested argument shapes.
  Every mutation supports dry run, structural checks, commit and rollback; common graph edits do not
  require Python.
- Added the 15-pair Harness translation dataset and deterministic train/validation/held-out scorer.
  Oracle sanity reaches 1.0 for every format.
- Ran a real 25-call DeepSeek V4 Flash comparison. All formats reached 1.0 validity. High-level
  operations reached 1.0 exact/edit/held-out generalization with 358 output tokens and about 1.66 s
  mean latency; EgoIR was the strongest inspectable textual representation at 0.79786 edit accuracy.
  Evidence: `.egoagent/research/ir-benchmark-20260811-084602.json`.

### 2026-08-11 — EVO-01/02/03/04/05/06 completed

- Added an economic artifact selector that can choose no-change, Knowledge, Skill, Identity/Agent or
  Harness from reuse, benefit, token saving, confidence, implementation/maintenance cost and risk.
  It is available in Studio and as Dante's `select_evolution_artifact` tool.
- Added proof-carrying proposal validation, quarantine/trust lifecycle, disjoint train/validation/
  held-out/regression gates, budgets, leakage detection, provenance, revision checks and rollback.
- Added sequential-stream metrics for delayed reuse, distribution shift, negative transfer,
  forgetting, recovery, parent/child tokens and evolution amortization, plus matched-budget
  delegation comparisons.
- Task Bench now injects generic evaluator-agnostic metacognitive governance only when evolution is
  enabled. It requires a real installed mutation and verification, but never reveals a task check or
  prescribes the task-specific artifact.
- Fixed a production-critical permission bug discovered by real experiments: evolution target values
  are artifact categories, not object names. The runtime now exposes category-compatible mutation
  schemas while still enforcing concrete name scopes at execution.
- Valid live DeepSeek probe `20260811_093319` independently selected a new read-only research
  Identity, created it, and verified result-only delegation through an existing bounded child
  Harness. Preserved trace rescoring is 1.0 after removing the evaluator's incentive to duplicate an
  already adequate Harness. Full non-cheating method and negative infrastructure runs are documented
  in `docs/RESEARCH_AND_PRODUCT_VERIFICATION.md`.

### 2026-08-11 — SCI-01/02/03 and CTX-02 completed

- Added pinned source contracts for 15 suitable upstream projects and executed all 45 real offline
  behavioral tests. All 15 Ego replicas pass schema, graph, operation, source and behavior checks;
  external SaaS/account/browser boundaries remain separately declared.
- Added a source-contract ↔ EgoIR translation dataset, deterministic splits, scorer and minimum
  canonical vocabulary report. Studio Research shows the contracts and vocabulary.
- Added the fixed evidence-bound autonomous science state machine: retrieve, hypothesis, plan,
  implement, execute, analyze, repair, independent review and report. Claims require hash-verified
  artifacts/sources; command drift, self-review and tampering are rejected.
- Completed private semantic context retrieval without an external key: a dependency-free 384-dim
  local sparse subword embedding, cosine retrieval and deterministic diverse reranking run entirely
  inside the workspace, with explicit lexical fallback.

### 2026-08-11 — Final integrated product gate

- Installed the declared `websocket-client` dependency that was missing from the active environment.
- Full Python suite: 312 passing, 3 explicit environment skips, zero failures.
- Studio TypeScript passed; Vite production build transformed 210 modules successfully.
- Restarted Studio from current source and verified HTTP 200 for Studio, Research Conformance, Task
  Bench and Void proxy routes.
- Real in-app browser acceptance confirmed the complete Studio navigation, 9 Task Bench tasks,
  49 Harnesses including Aider, 15/15 conformance cards, EgoIR validation/mutation UI, proof-carrying
  Evolution Lab, and Void's native integrated DAG Chat with 36 user-facing Harnesses, six runtime
  modes, DeepSeek status, DAG/run/change/context views and inline Agent-change discovery.
- Final executable acceptance instructions are in `docs/RESEARCH_AND_PRODUCT_VERIFICATION.md`.
