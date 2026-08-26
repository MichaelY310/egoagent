# DAG Components: composable context, capability search and evolution

EgoAgent now separates **runtime mechanisms** from **Agent policy**:

- The runtime exposes typed conversation metadata and validates effects.
- Ordinary `模型` nodes decide what to summarize, simplify, keep or elide.
- `条件` / `循环` / `数据.increment` nodes decide when a policy runs.
- A Harness with a `component` manifest is a reusable SubDAG and appears in Studio's component library.
- `子流程` maps typed inputs and outputs instead of relying on an implicit global variable contract.

The runtime does not automatically call a hidden context model when `context_management` is absent. Old Harnesses that explicitly declare `context_management.enabled: true`, `curate`, `compact` or `auto_compact` remain compatible, but new work should use the component pattern below.

## Conversation component pattern

```text
上下文(snapshot) -> 普通 模型 -> 上下文(apply)
   metadata          editable       validated effect
   no LLM call       prompt         full audit retained
```

### Conversation Input

Use an `上下文` node with `action: "snapshot"`. It returns:

- `working_messages` and immutable `full_messages`;
- stable conversation `turns` and a configurable `review_batch`;
- protocol-safe `blocks` that never split a tool call from its result;
- current task and context-governance state;
- optional token `pressure` computed from thresholds declared on the node;
- `model_payload`, a JSON string designed for a normal Model prompt.

It emits `conversation_ready`, `review_due|review_not_due`, and `pressure_due|pressure_ok`. It does not call a model or mutate the session.

### Ordinary Model

Use the existing `模型` node. Its prompt lives in the Harness and is fully editable. `parse_as: "json_object"` makes the model output a structured transformation plan. This is where summarization behavior belongs.

### Conversation Output

Use an `上下文` node with `action: "apply"`:

- `apply_mode: "turn_plan"` accepts `{decisions:[{turn_id, action, reason, summary}]}`;
- `apply_mode: "block_plan"` accepts `{blocks:[{block_id, action, reason, summary}]}` and a declared `target_tokens`;
- `apply_mode: "restore_full"` restores the audit transcript as the working view.

The output port validates the plan, keeps system messages and recent protected turns, prevents user requirements from being silently elided, preserves exact anchors, updates the working transcript atomically, and leaves the full UI/audit transcript available. Those are runtime safety invariants, not Agent policy.

## SubDAG component manifest

Add a top-level manifest to any Harness:

```json
{
  "component": {
    "name": "example_component",
    "display_name": "Example Component",
    "category": "Conversation",
    "description": "What this component does",
    "icon": "◫",
    "share_session": false,
    "inputs": {
      "interval": {
        "required": false,
        "default": 5,
        "schema": {"type": "integer", "minimum": 1}
      }
    },
    "outputs": {
      "stats": {"path": "result.stats", "default": {}}
    }
  }
}
```

`子流程.component_inputs` supplies values. Defaults and JSON Schemas are validated before the child runs. `子流程.component_outputs` maps declared child outputs into parent `$ctx` paths. A conversation/evolution component may declare `share_session: true`; other SubDAGs stay isolated.

Studio supports authoring this contract under **Harness 配置 → SubDAG 组件接口**. After saving, the Harness appears under **SubDAG 组件** in the left palette and can be dragged into another graph. The created node receives the component's defaults, output bindings, and shared-session declaration.

## Included reusable components

| Harness | Purpose | Hidden policy? |
|---|---|---|
| `component_context_curator` | Review a declared batch of old turns and apply keep/summarize/elide decisions | No; cadence and prompt are DAG fields |
| `component_context_compactor` | Trigger at a declared token watermark and compact protocol-safe blocks | No; threshold, target and prompt are DAG fields |
| `component_capability_discovery` | Bounded semantic capability search and activation | No; query and tool-round budget are inputs |
| `component_capability_evolver` | Judge repeated work, search before creation, and create a reusable artifact after approval | No keyword rules; ordinary Model + visible tools |
| `component_agent_designer` | Author an Agent Spec, request approval, search existing capabilities and create an Identity + Harness | No archetype selection in the DAG path; the full spec is a Model output |

`create_skill` is the first-class authoring tool used by the evolver. An
executable Skill is a reusable package under `identity/<name>/ego/skills`; its
bounded function is the Tool interface seen by the model. The older
`create_tool` name is a compatibility alias over the same validated writer.

## Included complete Agent examples

### `adaptive_code_agent`

The default primary Identity is `openmanus`, a composite of coder, researcher
and browser-operator EGO packs. Its preferred-tool contract keeps
`web_search`, `fetch_url`, `fetch_urls` and `browser` visible under the shared
tool-schema budget, while the capability catalog remains progressively
disclosed. Web evidence and interactive browser state therefore participate in
the same session, replay and permission stream as file and command tools.

- searches the local capability library for every new coding task;
- reviews relevance every 5 user turns;
- passively checks token pressure every turn, but calls the compactor model only when the threshold fires;
- reviews reusable Skill/Tool/Knowledge/Harness opportunities every 15 turns;
- requires approval before an evolution mutation;
- runs the normal workspace-aware tool loop for the actual code task.

Default slots: `openmanus` performs the code, research and browser task;
`dante` runs the isolated discovery/context/evolution components. This keeps
execution and governance authority separate. Either slot can be rebound in
Studio.

### `adaptive_research_agent`

- searches local papers, Knowledge and reusable research capabilities first;
- reviews context every 4 turns;
- uses a more aggressive 80% → 58% pressure-compaction policy;
- reviews durable knowledge/skill opportunities every 12 turns;
- keeps provenance and delegates verbose search when an isolated search Harness exists.

Default slots: `researcher` performs the research task and `dante` runs the
governance components.

### `agent_factory`

This user-facing Harness contains only Input → `component_agent_designer` →
End. The component's ordinary Model call emits a structured Agent Spec. Studio
shows that spec at a human-approval boundary; only after approval does a
bounded Agent search the catalog and call `create_agent_system`. The resulting
Identity and Harness are both visible and editable. The old keyword-template
REST form remains readable for compatibility, but none of the adaptive example
Agents use it.

### `conversation_component_demo`

This is the smallest visual example of the requested pattern. A `循环` node runs five real `输入 → Agent` interactions. At the loop boundary it invokes `component_context_curator`; inside that SubDAG, Conversation Input feeds metadata to an ordinary Model and Conversation Output applies the plan. Open it in Studio and use single-step mode to see the component boundary and every internal node event.

### Migrated `context_curator`

The older general-purpose context Agent no longer uses `action: curate` or the implicit pressure middleware. It now composes `component_context_curator` and `component_context_compactor` explicitly.

## Verification

```powershell
python scripts/audit_harness_catalog.py
python -m unittest discover -s tests -p test_capability_authoring.py
python -m unittest discover -s tests -p test_agent_creator.py
python -m unittest discover -s tests -p test_dag_components.py
python -m unittest discover -s tests -p test_pipeline_runtime.py
cd harness_editor
npm run build
```

The tests verify that snapshot is read-only, apply changes only the model-facing
view, the full audit record remains intact, typed SubDAG outputs map back to the
parent, a shared-session component changes its parent conversation, invalid
model JSON makes no context mutation, a graph without a declared policy makes
no implicit compactor call, a Skill is loadable after creation, unsafe names or
code are rejected, and a structured Agent Spec—not keyword matching—controls a
new Identity.
