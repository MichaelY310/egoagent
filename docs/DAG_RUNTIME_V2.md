# EgoAgent DAG Runtime v2

Runtime v2 keeps Identity, EGO and SEGO intact. Identity defines who an Agent
is; EGO contributes behavior, knowledge and tools; the Harness DAG controls
when work happens and how typed data moves. Assigning a different Identity/EGO
to the same Agent node therefore changes behavior without changing the graph.

## Small canonical vocabulary

Old Harness names remain aliases, so existing JSON does not need migration.

| Component | Purpose |
| --- | --- |
| `输入` | Consume a user/event input; later inputs can explicitly wait for a fresh answer |
| `Agent` | One Identity + EGO driven model step, optionally with temporary DAG instructions |
| `文本处理` | Let an Identity transform text, or deterministically parse a thought/action or Aider edit-block protocol |
| `模型` | One structured or text-only model call without an Agent tool loop |
| `工具审查` / `工具` | Apply deterministic permissions, then execute tool calls sequentially or concurrently |
| `进程` | Execute a fixed command without a shell and return typed stdout/stderr/status/artifacts |
| `工作区` | Apply safe typed edits, review transactions, create/copy/list/publish files and make recoverable snapshots/restores |
| `条件` | Safe If/Else expression |
| `数据` | Manipulate run/session/file data or perform durable Agent registration and message handoff |
| `上下文` / `记忆` | Select/compact message history, elide old observations and store/retrieve scored long-term memory |
| `循环` / `并行` / `映射` | Sequential loop, static branches and dynamic list fan-out |
| `合并` | Keep full branches or reduce to typed values, concatenated text, merged object, first or last |
| `人工审批` | Review and optionally edit typed data before approve/reject routing |
| `子流程` | Reuse another Harness, or run a typed event-driven port graph without adding another visible component |
| `检查点` | Save or restore run data, outputs and messages |
| `输出` / `结束` | Emit an intermediate or final typed value |
| `Python` | Advanced escape hatch when a normal component truly cannot express the operation |

Legacy `等待输入`, `推理`, `处理工具`, `处理文字`, `执行工具`, `脚本` and
`llm_call` map to the canonical operations above.

## Explicit typed data flow

- `$ctx.<path>` reads run data.
- `$node.<node-id>.<port>` reads a particular node result.
- `$last.<port>` reads the previous result.
- `$session.messages` and `$session.state` expose session state.
- `${ctx.path}` embeds a value into text; an exact `$ctx.path` reference keeps
  the original string/list/object/boolean type.

```json
{
  "op": "模型",
  "agent": "reviewer",
  "prompt": "review",
  "parse_as": "json",
  "outputs": {
    "structured.accepted": "review.accepted",
    "structured.feedback": "review.feedback"
  }
}
```

Subflows can return their last text, messages, exact final `result`, or complete
run `data`. `合并(strategy="values")` removes Map/Parallel bookkeeping while
preserving each branch result's JSON type.

A Subflow may also consume an in-memory graph from `$ctx`. Runtime-generated
graphs pass the same schema checks, have configurable node/depth limits, and
can bind roles to existing or newly instantiated Identity/EGO directories.
Python, Process and Workspace operations are rejected in generated graphs by
default; a trusted Harness author must explicitly enable them.

The same Subflow component has an optional `mode="port_graph"`. Its blocks have
stable IDs, typed/default/required inputs and named output ports. A block may
emit the same port repeatedly. Each dynamic event fills the earliest incomplete
downstream execution or creates a new one; a static link caches its latest value
and fills every current and later execution. Fan-in queues only after all
required inputs exist, while independent ready executions run concurrently.
Cycles are allowed because some Agent loops are naturally event-driven, but
`max_executions` and `max_events` make them bounded. Input/output schemas,
per-block editable approval, errors, cancellation and Identity/EGO slot mapping
remain ordinary runtime behavior.

Setting `state_path` makes this mode durable inside the node. Every created
execution and delivered output event is atomically snapshotted. A resumed graph
keeps execution IDs, does not rerun completed blocks, and verifies that a retried
in-flight block has not changed an output already delivered before interruption.
This is finer-grained than the surrounding node checkpoint and avoids replaying
completed side effects after a recoverable process interruption.

## Safe logic without Python

Conditions and conditional edges use a restricted AST evaluator rather than
`eval`. It supports boolean/arithmetic operators, comparisons, mapping/list
access, safe indexing/slicing and conditional expressions, JSON literals `true`,
`false`, `null`, and helpers including `exists`, `empty`, `len`, `contains`,
`starts_with`, `ends_with`, `lower`, `upper`, `strip`, `min`, `max`, `is_string`,
`is_number`, `is_list` and `is_object`.

The Data filter action evaluates the same expression once per list item:

```json
{
  "op": "数据",
  "action": "filter",
  "key": "selected",
  "source": "$ctx.candidates",
  "condition": "item.novel == true and item.score >= 6",
  "output_var": "selected"
}
```

`数据(action="aggregate_fields")` computes deterministic means for selected
numeric fields across a list of objects, optionally rejecting out-of-range
scores and rounding like an upstream review ensemble. This keeps aggregation
out of prompts and Python escape hatches.

The same Data component also supports `evaluate` for safe typed arithmetic and
projection, bounded integer `range` generation, `slice` for bounded string/list
windows, stable `unique` for JSON values, and `trim_words` for source-shaped
long-context caps that keep the most recent complete list entries. Map and Loop
`max_count` values may be typed references such as `$ctx.breadth`, so recursive
graphs can narrow work without a Python node. Join's `flatten` strategy unwraps
branch results and removes one list layer, which covers reflection and evidence
fan-in without a script.

Two Data actions remain useful for simple acyclic plans and visualization.
`topological_levels` validates stable IDs and dependency lists, rejects
duplicates, missing/self dependencies and cycles, then emits stable layers.
`validate_schema` checks any runtime value against a dynamically supplied JSON
Schema and routes through explicit `schema_valid` or `schema_invalid` tags while
preserving the value and structured error list. Repeated events, static pins,
cycles or port-level resume should use the Subflow port-graph mode instead of
turning dependency layers into a Loop/Map approximation.

Memory retains the small `add/search/list/delete/clear` surface while supporting
two explicit write policies: `add_unique` skips a matching field inside a
bounded recent window, and `upsert` replaces a same-type item by a stable dotted
key. These policies express event retention and executable skill upgrades while
remaining atomic under the existing per-file memory lock. Imported memories
with nullable numeric fields are normalized conservatively during ranking.

## Durable Agent roles and messages

Long-lived roles do not require a separate graph component. The existing
`数据` node exposes `agent_register`, `agent_heartbeat`, `agent_unregister` and
`agent_list`, plus `message_publish`, `message_receive`, `message_ack`,
`message_nack` and `message_list`. State is stored in a Workspace-confined
SQLite/WAL database (default `.egoagent/agent-bus.sqlite3`) and can be shared
by independently started DAG runs on the same host.

Publishing can target explicit recipients or every active Agent whose topic
subscription matches (wildcards are supported). An optional idempotency key
prevents duplicate messages after checkpoint replay. Receiving atomically
leases each delivery to one owner; the same owner may renew an unexpired lease
when resuming a checkpoint. Successful work acknowledges the receipt, while a
negative acknowledgement delays and retries it until `max_attempts`, after
which it becomes a visible dead letter.

```json
{
  "op": "数据",
  "action": "message_receive",
  "agent_id": "engineer:${ctx._run_id}",
  "owner": "engineer:${ctx._run_id}",
  "topics": ["project.${ctx._run_id}.task.*"],
  "lease_seconds": 300,
  "limit": 10,
  "output_var": "task_inbox"
}
```

The editor presents these as advanced actions inside the single Data
component. Identity/EGO still defines each registered role's behavior; the bus
only makes lifecycle and artifact delivery explicit and recoverable.

## Reliability and safety

Every node may declare timeout, retry/backoff, structured output schema,
checkpoint and an error route. A graph can cap elapsed time, model/tool calls,
tokens and cost. Estimated usage is always available; when a provider reports
usage, request IDs, cached input tokens and exact token counts are recorded and
the stricter of estimated/actual usage enforces the budget. Cancellation is
checked between nodes, during streaming, between tools and while retrying.

A graph may route budget, elapsed-time or node-step exhaustion through
`budget_exceeded_to` (or the legacy-compatible `limit_exceeded_to`) before it
returns. This finalizer is deliberately bounded by `limit_finalizer_max_steps`
and may use only Condition, Data, non-mutating/recovery Workspace actions,
Approval, Checkpoint and Output nodes. It can label the termination, expose
partial evidence, review or roll back pending edits and emit a typed result,
but it cannot spend more model/tool/process budget.

A `模型` node can use `parse_as="json_object"` when a provider may wrap a
structured verdict in prose or a Markdown fence. It extracts the object and
then applies the normal output schema. If invalid output must be treated
conservatively instead of retried, `json_fallback` supplies an explicit typed
value and emits `model_json_fallback`; no hidden model call is made.

For coding Harnesses that require exactly one environment action per turn, an
Agent node can set `max_tool_calls_per_turn`. `文本处理(mode="thought_action")`
implements the SWE-agent-style protocol without Python: it extracts the final
complete top-level fenced block, preserves everything outside as thought,
synthesizes one configured tool call, recognizes explicit submit/exit commands
and performs bounded format-error re-queries. A Tool node can use
`end_session_to` to pass an explicit tool-side submission through review and
output nodes instead of bypassing the rest of the graph.

A Tool node may also declare `exclusive_tools`; only the first same-name call in
one generated batch executes and later duplicates become explicit discarded
observations. Combined with sequential `interrupt_when` and
`truncate_after_tools`, this expresses RoleZero-style edit-command exclusivity,
stop-on-error and terminal-command ordering.

Tool nodes may set `max_observation_chars` to bound a single observation before
it is appended to model context. Truncation is deterministic, records the number
of omitted characters and emits `tool_observation_truncated`; custom Agent
implementations are bounded by the runner even if they do not implement the
optional native limit themselves.

`文本处理(mode="aider_search_replace")` parses filename-scoped
`SEARCH/REPLACE` blocks and shell-command suggestions without executing model
text. It supports Aider's repeated-filename convention, empty SEARCH for new
files, bounded format correction and typed edit/shell outputs. The matching
`工作区(action="apply_search_replace")` confines paths to the Workspace, tries
exact then consistent-leading-whitespace and paired-ellipsis matching, can
recover a misnamed target from an allow-list, and records the resulting file
diffs in the normal per-hunk review transaction. `atomic=false` preserves
Aider's partial-success repair loop; `atomic=true` makes a failed block prevent
all writes in that application step. Write failures roll back already-written
files in either mode.

Workspace also has bounded `read_text`/`read_json` and atomic
`write_text`/`write_json` actions. Reads expose typed existence, size and
truncation metadata. Writes reject accidental overwrite unless configured,
limit encoded bytes, prevent directory recursion during copies and record
their diffs in the same per-hunk review system used by Agent edits.

`上下文(action="last_n_observations")` preserves the initial instance
observation and the most recent N environment observations. Older observations
become line-count omission markers, matching the important semantics of
SWE-agent's history processor while retaining the surrounding assistant turns.

An Agent can filter the actual function definitions sent to the provider with
`visible_tools` and `hidden_tools` glob patterns. This differs from
post-generation review: an excluded tool is absent from the model request, and
a following `工具审查` node remains defense in depth against malformed or
injected calls. Tool policy evaluation defaults to EgoAgent's last-match
precedence, while `policy_match="first"` reproduces Continue's ordered rules.

`上下文(action="auto_compact")` estimates the complete working input and
compacts only after a configurable context/output/reserved-token threshold.
Its default buffer follows Continue's 20%/15K-cap policy. The summary replaces
the active session history when `persist_session=true`, while `full_messages`
retains the audit trail. If a just-compacted model turn tries to finish,
`Agent.auto_continue_when`, `auto_continue_prompt` and bounded
`max_auto_continuations` can inject a continuation and route through context
preparation again instead of creating an unlimited hidden retry.

The OpenAI-compatible provider adapter retries connection failures and
408/409/425/429/5xx responses with bounded exponential backoff, honoring
`Retry-After`. Broken SSE streams resume with `Last-Event-ID` when the provider
supplies event IDs, deduplicating replayed events. If output was already
emitted without an event ID, the adapter fails explicitly instead of silently
duplicating tokens or tool arguments.

Tool review supports allow/ask/deny/exclude rules. Tool execution records an
action/observation trajectory and detects identical repetition, repeated
errors and alternating cycles. A stuck route can return control to the Agent
with corrective feedback instead of silently spending the remaining budget.
`error_nudge_threshold` can emit one softer correction before
`error_stuck_threshold` hard-stops an identical failure streak. For tools such
as OpenHands `Finish`, `truncate_after_tools` discards later calls from the
same generated batch and writes synthetic discarded observations so provider
history stays well formed; `terminal_tools_to` then exits the inner Agent loop
through an explicit graph edge.
Tool nodes may opt into `attach_images`; when a tool returns a Workspace-local
image path, the runtime validates its MIME type and size, encodes it as a
multimodal user observation, and makes it available to a vision-capable model.
The option is off by default so text-only providers keep working unchanged.

Browser EGO observations now have stable IDs and typed page, viewport, element
box, active element, dialog, download and blocked fields. Element and viewport
actions use CDP mouse/keyboard events rather than injected JavaScript clicks;
downloads are verified as Workspace files, and JavaScript dialogs have explicit
accept/dismiss operations. CAPTCHA markers produce `requires_human` rather than
an attempted bypass. Tool results with that flag emit a `human_required` route,
which a DAG can connect to `人工审批` and resume after a fresh observation.

Run-scoped sessions such as browsers are closed automatically when the root
PipelineRunner ends or fails. A graph may explicitly set
`preserve_runtime_resources=true` only when another owner is responsible for
their lifecycle.

Streaming adapters assemble fragmented tool names/arguments into complete
snapshots before execution. An Agent response with neither visible content nor
a tool call is not treated as success: the runtime appends a bounded corrective
message and retries, then exposes an explicit error route if emptiness persists.

Process nodes keep the executable separate from its argument list, constrain
the working directory and artifact globs to the Workspace, terminate on
timeout/cancellation, and can share named capacity limits such as `gpu` or
`cpu` across concurrent branches. On Windows the child starts suspended, enters
a kill-on-close Job Object, and only then resumes, closing the spawn-vs-timeout
race; native enumeration/taskkill remain fallbacks when nested Jobs are denied.
POSIX uses a dedicated process group. Cancellation and timeout terminate all
descendants rather than only the direct child.

For untrusted or dependency-heavy commands, `backend="container"` selects the
Docker/Podman adapter. Its defaults are deny-network, read-only rootfs, all
capabilities dropped, `no-new-privileges`, bounded PID/memory/CPU, a temporary
`/tmp`, `--pull=never`, and one explicitly mounted Workspace (`rw` or `ro`).
Only declared environment-variable names enter the container, while their
values stay out of the launcher command line. Every container receives a
unique run/node name and is force-removed after success, failure, timeout or
cancellation. Container isolation depends on a running Docker/Podman daemon;
the local backend remains deterministic orchestration rather than a sandbox.

Workspace nodes confine every edit, source, target and archive member to the
current Workspace. Search/replace edits are parsed separately from application,
and shell suggestions remain inert until a graph explicitly routes them through
approval and an execution tool. Snapshots enforce file/byte limits and
restoration creates a backup of the current files by default. They provide
artifact isolation and recovery; they do not silently delete files that were
created after a snapshot.

Workspace edit transactions tag every write/patch/multi-edit made by an Agent
with the current run-local transaction. Void and the DAG read the same hunk
records, so accepting one green section and rejecting another rewrites exactly
that mixed result. Transactions are concurrency-safe, exact duplicate records
are collapsed, and unattended review rejects unresolved hunks by default.

Parallel branches receive copied run/session state. Declared reducers merge
only intended paths back using append, extend, unique, merge, concat, first or
last behavior. Persistent stores are locked. `contextvars` identifies the
current Harness, so concurrent Agents do not overwrite process-global state.

## One execution engine

`PipelineRunner` is the only graph interpreter. Terminal calls, synchronous
API calls, token/event streaming, the DAG Studio WebSocket and the
OpenAI-compatible endpoint adapt the same runtime. A feature added to the
runner therefore cannot silently work in sync mode while being absent from the
streaming UI.

Graphs can opt into `.jsonl` event persistence with an `event_log` path. Every
record has a monotonic per-file sequence, timestamp, run/node identity and a
redacted payload. `检查点(action="replay")` can read all events or filter by
sequence and event type. Checkpoints still own state restoration; event replay
is an audit/debug primitive rather than an implicit re-execution mechanism.

Version-2 checkpoints also persist the exact next node, last output, data,
messages, session state and cumulative statistics. `PipelineRunner` and both
public run wrappers accept `resume_from`; a fresh process continues with the
original run ID/event log and does not repeat the side effect that preceded the
checkpoint.

## Durable run coordination

`DurableRunQueue` is the persistent scheduling layer above `PipelineRunner`.
It stores runs and ordered redacted events in SQLite/WAL, atomically leases one
run to one worker, renews the lease with heartbeats, persists cancellation and
the newest checkpoint, and requeues work after an expired worker lease until
the attempt budget is exhausted. Idempotency keys prevent duplicate enqueue.
Multiple local worker processes may coordinate through the same database; a
network database/queue adapter is still required for true multi-host service.

The server starts a local `DurableRunWorker`. `POST /api/runs` enqueues a run,
`GET /api/runs/<id>` returns durable status/result, the `/events` child endpoint
supports sequence-based polling, and `POST /api/runs/<id>/cancel` cooperatively
cancels the leased PipelineRunner. Synchronous and streaming APIs remain direct
adapters to the same interpreter.
