# Harness catalog and validation matrix

Updated: 2026-08-12

## Outcome

The user-facing catalog now contains **43 runnable harnesses**:

- 19 open-source replicas
- 13 internal workers required by parent DAGs
- 7 reusable templates
- 4 evolution harnesses

Six development leftovers were removed: `new_harness`, `quick_test`,
`verify_test`, `research_loop`, `self_improve`, and the invalid/duplicated
`turn_based` harness. `debate_with_moderator` remains as the maintained
turn-based template.

## What “tested” means

Testing is layered; schema validity alone is not treated as functional proof.

| Layer | Scope | Result | Reproduce |
|---|---:|---:|---|
| Catalog/schema/dependency audit | all 43 | 43 passed, 0 failed | `python scripts/audit_harness_catalog.py` |
| Harness unit and replica contracts | all harness tests | 60 passed | `python -m unittest discover -s tests -p 'test_harness*.py'` |
| Pinned upstream conformance | 15 source contracts | 15 passed | `python harness_conformance.py --behavioral --output experiments/results/harness_conformance.json` |
| Unified DAG runtime | all node/runtime paths touched here | 94 passed | `python -m unittest discover -s tests -p 'test_pipeline_runtime.py'` |
| Change review | hunk/file transaction semantics | 13 + 3 API tests passed | `test_change_tracker.py`, `test_change_review_api.py` |
| Real DeepSeek code edit | `coder_react` + `identity/coder` | passed | `python scripts/test_live_native_execution.py` |
| Real DeepSeek multi-agent | `creative_roundtable` | 4 turns passed | same script |
| Real repository edit | `aider_replica` on isolated OpenHands checkout | passed | task described below |

The final conformance report is
`experiments/results/harness_conformance.json`. “Core verified, external
blocked” means the local source-pinned behavior contract passed, while exact
parity still depends on the upstream project's browser, sandbox, OAuth,
benchmark image, or hosted provider. It is not a claim that those unavailable
external systems were simulated.

## Retained catalog

### Replicas

`ai_scientist_replica`, `aider_replica`, `autogpt_platform_replica`,
`browser_use_replica`, `continue_agent_replica`, `continue_plan_replica`,
`devika_replica`, `generative_agent_replica`, `gpt_researcher_deep_replica`,
`gpt_researcher_replica`, `metagpt_mgx_replica`,
`metagpt_software_company_replica`, `open_deep_research_replica`,
`openhands_replica`, `openmanus_planning_replica`, `openmanus_replica`,
`stagehand_replica`, `swe_agent_replica`, `voyager_replica`.

### Internal workers

`ai_scientist_experiment_run_worker`, `ai_scientist_idea_worker`,
`ai_scientist_novelty_worker`, `aider_review_worker`,
`bounded_action_worker`, `bounded_coder_worker`,
`generative_reflection_worker`, `gpt_researcher_deep_query_worker`,
`gpt_researcher_deep_worker`, `gpt_researcher_query_worker`,
`metagpt_rolezero_worker`, `open_deep_research_worker`,
`voyager_action_worker`.

### Templates and evolution

Templates: `coder_react`, `creative_roundtable`, `debate_with_moderator`,
`dual_guardian`, `guarded_react`, `react_single`, `text_review_react`.

Evolution: `evolution_cycle`, `improver`, `meta_evolution_cycle`,
`session_analyzer`.

## Real tasks and discovered failures

### Coder ReAct, two independent code edits

The real model received an absolute Python fixture and was asked to replace
`return 1` and `return 2` in one `multi_edit` call. The test observed:

1. DeepSeek initially sometimes returned `NATIVE_EDIT_OK` without a tool call.
2. The runtime now detects mutation requests and refuses completion until a
   successful configured edit tool was actually executed.
3. Windows newline translation originally converted every line and collapsed
   two edits into one hunk. Patch tools and the central change journal now
   preserve the existing line-ending convention.
4. Tool-local and runtime-level journals originally duplicated the same edit.
   The runtime is now the single transaction-aware recorder.
5. The final live run produced one change with two hunks. Reject → undo →
   reject worked on hunk 1; accept → undo → accept worked on hunk 2; file-level
   reject restored the original.

New-file reject remains confirmation-gated and undo restores the file; this is
covered by `test_new_file_is_marked_then_delete_can_be_undone`.

### Aider Replica, isolated OpenHands checkout

The task added a single README comment in `tmp/harness-e2e/OpenHands-test`.
Initial runs exposed oversized project rules, unbounded reader rounds, CRLF
SEARCH/REPLACE mismatches, Unix-only reviewer commands on Windows, and a false
negative judge for documentation-only changes. After fixes, the real run:

- completed in about 24 seconds;
- used bounded editor/reviewer tool rounds;
- produced exactly one line and one review hunk;
- reached `review_changes` with `accepted: true`;
- was restored through the product Reject action, leaving tracked source clean.

### Creative Roundtable

Two different identities completed four real DeepSeek turns. The runtime
returned to `wait_input`, both identities appeared twice, and Chinese output
contained no mojibake.

## Product behavior added while testing

- Agent-node `max_tool_rounds` with a forced factual final response after the
  read/action budget is exhausted.
- Per-user-turn counters; limits no longer leak into the next chat message.
- `require_tool_for_mutations` and `required_tool_patterns`, configurable in
  Studio, prevent a coding agent from claiming a file change it did not make.
- Workspace-filtered change queries and 4-second, visibility-aware polling
  prevent Studio from recalculating historical changes from unrelated/deleted
  workspaces every 1.5 seconds.
- DeepSeek V4 Flash uses non-thinking tool mode by default, with bounded node
  token/temperature controls.

