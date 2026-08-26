# Self-Evolution Integration

This document records which research experiments were integrated into the product, the unified evolution protocol, and reproducible cases.

## 1. Repository research audit

| Exploration | Useful result | Product integration | Important correction |
| --- | --- | --- | --- |
| `self_evolution/engine.py` | baseline → change → re-evaluate → accept/rollback gate | The gate now also covers installed capability packs | The old loop treated evolution as prompt editing only |
| `experiments/self_repair` | structural repair and failure-driven changes | Structural candidates commit through Blueprint transactions | The old Studio V2 route wrote `config.json` directly and used a simulated failure summary |
| `experiments/pipeline_search` | graph search space, reachability and cycle checks | Blueprint compilation reuses the production runtime schema and adds reachability warnings | The experiment had a second, drifting node-type registry |
| `experiments/lifelong_learning` | principle value, conflict detection, pruning and replay | Capability diagnosis distinguishes durable Knowledge from executable Skill | Principles must not be stored as facts until the cause is reproduced |
| `experiments/self_play` | proposer/solver/judge and ZPD curriculum | Still usable as an evaluation-task generator | It is an evaluator, not a safe mutation protocol by itself |
| `experiments/evo_benchmark` | before/after metrics and rollback evidence | Evolution reports retain before/after scores and transaction IDs | A successful file write is not evidence of improvement |
| Identity-control experiments | behavior belongs to ID + SEGO + EGO | Identity and Ego remain first-class; nothing was removed | Previously generated `system_prompt.txt`, `tools.json`, and flat `.md` knowledge were not loaded by the runtime |

## 2. One unified model of evolution

Choose the smallest layer that fixes the observed failure:

1. **Knowledge** — verified durable facts or a short rule describing when to use an existing capability.
2. **Skill** — a deterministic, repeated operation that should not consume model reasoning every time.
3. **Isolated sub-Agent** — a long or failure-prone trajectory whose internal messages should not enter the parent Agent context.
4. **Harness** — control-flow, routing, retry, approval, context, parallelism or termination behavior.
5. **ID / SEGO prompt** — personality or behavioral instruction, only when the failure is genuinely behavioral.

Every mutation follows: inspect → diagnose → dry run → transaction → repeat the same evaluation → accept or rollback.

## 3. Harness Blueprint: the weak-model format

Small models should not edit the full runtime configuration. They use this compact representation:

```json
{
  "version": 1,
  "name": "tiny_researcher",
  "description": "Search, inspect evidence, and answer once",
  "roles": {"worker": "evidence researcher"},
  "start": "input",
  "steps": [
    {"id": "input", "type": "input", "next": "think"},
    {
      "id": "think",
      "type": "agent",
      "role": "worker",
      "on": {"tools": "act", "text": "finish"},
      "config": {"tools": "auto"}
    },
    {"id": "act", "type": "tool", "role": "worker", "next": "think"},
    {"id": "finish", "type": "end", "inputs": {"value": "$last.text"}}
  ]
}
```

The stable step vocabulary is:

`input`, `agent`, `tool_review`, `text`, `tool`, `process`, `workspace`, `model`, `context`, `memory`, `if`, `data`, `set`, `get`, `loop`, `parallel`, `map`, `join`, `approval`, `subflow`, `checkpoint`, `output`, `end`, and the last-resort `python` escape hatch.

`manage_harness` provides `guide`, `inspect`, `validate`, `create`, `patch`, and `rollback`. A patch uses small operations such as `add_step`, `remove_step`, `update_step`, `connect`, and `disconnect`. It must include the revision returned by `inspect`; stale model actions are rejected instead of overwriting a newer graph.

## 4. Implemented evolution cases

### Case A — downloaded paper collection

Signal: PDF/paper/论文 references, especially when the user expects previously supplied papers to be remembered.

Evolution: install the `paper_library` pack. It adds:

- `local_paper_search`: workspace-confined PDF/TXT/Markdown extraction, persistent cache, bounded keyword snippets, and path/page citations;
- `local_papers_first`: a Knowledge policy telling the Agent to retrieve local evidence before web search.

The full paper is never injected into context. PDF support uses `pypdf` or `PyPDF2`; text and Markdown need no optional dependency.

### Case B — repeated searches pollute the parent context

Signal: repeated search/browser attempts, failures, timeouts, or duplicated search steps.

Evolution: install the `delegated_search` pack. It creates:

- an isolated `<identity>_search_worker` Identity with read/search/browser capabilities when available;
- a visual `<identity>_result_only_search` Harness;
- one parent `delegate_search(query)` Skill;
- a Knowledge rule describing when to delegate.

The worker's search attempts stay in its child Session. The parent receives only the final evidence result. Studio still shows the nested sub-Session so a human can audit it.

### Case C — context grows until important state is lost

Signal: context/token/compaction pressure.

Recommended Harness evolution: insert the reusable
`component_context_compactor` SubDAG. Its Conversation Input port calculates
pressure, an ordinary editable Model node writes the block plan, and its
Conversation Output port validates and commits the model-facing view while
preserving the full audit transcript. Do not add the legacy `auto_compact`
action to new Harnesses.

### Case D — repeated deterministic tool sequence

Signal: the same action appears at least three times.

Recommended Ego evolution: extract the bounded sequence into a Skill, then add a short Knowledge rule describing when to call it. Do not store transient tool output as durable Knowledge.

### Case E — destructive or publish/deploy action

Signal: delete, deploy, publish, overwrite or similar hard-to-recover effects.

Recommended Harness evolution: snapshot/checkpoint → human approval → effect → verification, with a rollback edge.

### Case F — repeated failures become a false “principle”

Signal: three or more failures.

Recommended evaluation evolution: reproduce the cause first. Only then distill a cautionary Knowledge item. This prevents the lifelong-learning store from accumulating guesses.

### Case G — a new role needs its own Agent

Use `create_agent_system(description, name?)`. It creates a current-format ID and SEGO, copies real executable Skills, creates loadable Knowledge directories, compiles a dedicated visual Harness, and returns the Blueprint. The previous creator produced files that the runtime did not load.

## 5. Studio execution debugger

Studio execution now supports:

- **First-node pause** before starting;
- **Pause** at the next node boundary;
- **Step** exactly one node without turning the pause into a retry;
- **Auto** continuous execution;
- per-node status and invocation count directly on the graph;
- click a node to inspect every invocation in a loop;
- redacted node inputs, previous output, full node output, model request/response, requested tools, executed arguments/results, and blocked tools;
- live graph reload and transaction diff when a model creates or patches a Harness.

The gate sits immediately before node side effects. Pausing cannot duplicate a model request, tool call, process, file write, or retry counter.

## 6. Reproducible checks

Automated:

```powershell
python -m unittest discover -s tests -p "test_harness_blueprint.py" -v
python -m unittest discover -s tests -p "test_capability_evolution.py" -v
python -m unittest discover -s tests -p "test_agent_creator.py" -v
python -m unittest discover -s tests -p "test_pipeline_runtime.py" -v
cd harness_editor
npm run build
```

Manual weak-model creation prompt:

> Create a code-review Agent system named `review_bot`. It should inspect Python patches, use tools when evidence is needed, and return risks plus verification steps. Do not write Agent code; use the visual Harness system.

Expected: the Agent calls `create_agent_system`, and `review_bot_harness` appears in Studio with `input → think → act → think` and `think → finish` routes.

Manual structural mutation prompt:

> Inspect `review_bot_harness`. Add a human approval node before the final output, using the smallest Blueprint patch. Dry-run it first, then apply it with the inspected revision.

Expected: `manage_harness` returns a transaction ID and diff; Studio refreshes the graph as the patch lands. A stale revision is rejected.

Manual paper test:

1. Put several PDF/TXT papers in `<workspace>/papers`.
2. In Evolution → Identity capability diagnosis, paste: “The user supplied local PDF papers, but the Agent later ignored them and searched the web.”
3. Preview and install `paper_library` for the target Identity.
4. Ask a question containing a paper title or a distinctive concept.

Expected: the Agent calls `local_paper_search` first and cites a local path/page. If the evidence is missing, it may then use the web and should say why.

Manual context-isolation test:

1. Diagnose and install `delegated_search`.
2. Ask for a comparison that requires at least three searches.
3. Inspect the parent Session and the nested sub-Session in Studio.

Expected: the child contains the search trajectory; the parent contains one `delegate_search` call and the final evidence summary, not every failed search message.
