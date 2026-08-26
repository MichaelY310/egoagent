# Reversible Context Governance

EgoAgent separates the conversation a user can inspect from the compact working
context sent to a model.

## Two views

- `full_messages.json` is the audit view. It keeps original messages and marks
  entries as kept, summarized, compressed, or elided.
- `messages.json` is the working view supplied to the next model call.

The UI continues to show elided messages with a status badge. Restoring full
context reconstructs the working view from the audit copy; it does not require
regenerating a summary.

## Two independent mechanisms

EgoAgent deliberately does not conflate relevance pruning with token-pressure
compression.

### 1. Periodic relevance pruning (精简)

The `component_context_curator` SubDAG uses Conversation Input → ordinary Model
→ Conversation Output. A parent graph decides the cadence with Loop,
Condition, and Data nodes. The included `context_curator` parent reviews old
turns in five-turn batches and protects the latest two turns. This pass is
allowed to:

- keep project decisions, constraints, unresolved work, paths, and errors;
- elide clearly unrelated small talk or redundant resolved exchanges;
- keep all project-relevant turns unchanged.

Its editable prompt distinguishes keep, summarize and elide. `max_tool_chars`
is a typed component input and defaults to zero, so deterministic tool-result
truncation is opt-in.

### 2. Passive token-pressure compaction (压缩)

When a parent graph invokes `component_context_compactor`, its read-only
Conversation Input port estimates rendered messages and emits `pressure_due`
only after the declared high watermark (default 82%). A Condition edge skips
the Model otherwise. The target working watermark (default 62%), output reserve
and protected turns are all component inputs; no implicit middleware call is
required.

After runtime triggers, the model authors a structured plan over protocol-safe
blocks:

- `system`;
- `user_requirement`;
- `assistant_reasoning`;
- `tool_exchange` / `tool_result`;
- `assistant_answer`;
- prior summaries and runtime messages.

Tool calls stay paired with results. The compactor may keep, summarize, elide,
or simplify hidden reasoning. Its prompt explicitly permits boilerplate,
repeated dead ends, and pre-aha exploration to become one sentence while
requiring the decisive post-pivot insight to survive. Large repeated tool
traces can be summarized, but tool names, state-changing arguments, paths,
errors, outcomes, user decisions, ports, backticked identifiers, and acronym
algorithm names are runtime-anchored back into summaries.

Failed judgment, malformed JSON, unavailable models, or plans that save no
tokens default to **keep** and emit `context_compaction_failed`. Successful
runs emit `context_pressure`, `context_compaction_started`, and
`context_compacted`; the DAG node inspector displays the threshold and before /
after token estimate. The newest user request and system messages remain
protected. The legacy explicit `auto_compact` Context action remains for old
Harnesses, but it is not the product default.

## DAG components and ports

Drag `Context Curator` into a parent graph and configure its typed inputs:

```json
{
  "op": "子流程",
  "harness": "component_context_curator",
  "share_session": true,
  "component_inputs": {
    "review_interval": 5,
    "protect_recent_turns": 2,
    "max_tool_chars": 0
  }
}
```

Drag `Context Compactor` into the same parent graph:

```json
{
  "op": "子流程",
  "harness": "component_context_compactor",
  "share_session": true,
  "component_inputs": {
    "context_limit_tokens": 128000,
    "high_watermark": 0.82,
    "target_ratio": 0.62,
    "reserved_output_tokens": 4096,
    "protect_recent_turns": 2
  }
}
```

Internally, both components use only neutral `snapshot` and `apply` Context
ports around a normal Model node. Use `apply_mode: "restore_full"` on a
Conversation Output port to make the audit copy active again. Legacy `curate`,
`compact`, `auto_compact`, and pipeline `context_management` remain executable
only so existing replicas continue to load; Studio no longer offers them for
new nodes.

## Safety invariants

1. Curation is reversible and never overwrites the audit source.
2. System constraints and the latest task survive every reduction.
3. Errors, paths, ports, identifiers, tool arguments, algorithm acronyms, and
   pending decisions survive summaries as exact anchors, including anchors
   found only in hidden reasoning.
4. Tool-call/tool-result pairs remain protocol-safe.
5. Model or parser uncertainty keeps content.
6. Repeated curation merges prior decisions instead of losing originals.

These invariants are covered by `tests/test_context_policy.py` and the Pipeline
middleware test in `tests/test_pipeline_runtime.py`. Long-running
experiments should measure input-token reduction, task success, recovery after
restoration, and missing-fact rate—not reduction alone.

## Research references

EgoAgent's policy is deliberately reversible and conversation-aware rather
than token-deletion only. Relevant compression baselines include
[LLMLingua](https://arxiv.org/abs/2310.05736),
[LongLLMLingua](https://arxiv.org/abs/2310.06839), and
[LLMLingua-2](https://arxiv.org/abs/2403.12968). These works motivate measuring
retained task performance together with compression; EgoAgent additionally
keeps an unchanged audit view and protocol-aware Tool messages for interactive
agent recovery.

Production patterns informing the lifecycle design:

- [OpenAI compaction](https://developers.openai.com/api/docs/guides/compaction):
  server-side compaction is triggered when rendered tokens cross a configured
  threshold and carries forward state for the next window.
- [LangChain context engineering](https://docs.langchain.com/oss/javascript/langchain/context-engineering):
  lifecycle middleware triggers LLM summarization after a token limit and keeps
  recent messages intact.
- [Deep Agents context engineering](https://docs.langchain.com/oss/python/deepagents/context-engineering):
  large tool results are offloaded first and history summarization occurs near
  the model window, while the complete record is preserved separately.
