# EvoCert real-task pilot preregistration (2026-09-02)

Status: **preregistered before any run in this experiment directory**.

## Decision being tested

EgoAgent can persistently evolve three separable external artifacts:

1. `I` — Identity/Ego behavioral guidance;
2. `K` — reusable Knowledge distilled from experience;
3. `F` — executable Flow structure.

The paper question is not whether an LLM can edit those artifacts. Recent work
already covers harness and skill evolution. The question is whether a proposed
multi-artifact state transition can be admitted using evidence that establishes
which artifacts were used, which coalition caused the gain, whether the gain
transfers to a sealed task, and whether an Identity/Superego-protected behavior
regresses.

This pilot is a **go/no-go test**, not a leaderboard claim.

## Updated novelty boundary

The experiment must not claim any of the following as novel:

- harness self-evolution (Evo-Bench, HarnessCompass, SHE and related work);
- a held-out or sealed acceptance test (SEAL);
- behavioral contracts or runtime invariants (Agent Behavioral Contracts);
- component-wise harness attribution (SHE/HarnessCompass);
- reliability certification under dependent multi-agent failures (ABC II).

The remaining claim under test is narrower: **interaction-aware causal
admission of a persistent update spanning typed Identity, Knowledge and Flow
artifacts, with activation, protected-distribution and lineage evidence**.

## Benchmark and frozen split

Benchmark: the MIT-licensed `ai-forever/harness-bench-fast` repository at
commit `e63712131fbb9cbd584df5e2012e06618a88de5e`.

The evolver may see only each validation task, its own validation trajectory,
and the corresponding tool's public `--help`. It may not read the held-out
prompt, held-out fixture, verifier implementation, protected task prompt, or
any result from those splits while authoring artifacts.

| Family | Validation (visible) | Held-out (sealed from authoring) |
|---|---|---|
| `logq` | `task_372_cli_logq_percentile_window` | `task_373_cli_logq_mean_by_component` |
| `pktool` | `task_374_cli_pktool_filter_decode` | `task_375_cli_pktool_stats_corrupt` |
| `xtab` | `task_376_cli_xtab_column_share` | `task_377_cli_xtab_mean_pivot` |
| `cfgctl` | `task_378_cli_cfgctl_layered_merge` | `task_379_cli_cfgctl_diff_changed` |

Protected distribution for every family:

- `task_385_cli_sort_multikey`
- `task_388_cli_grep_uniq_ranking`

These tasks do not contain the family-specific executable. The Flow preflight
must therefore degrade to a no-op rather than fail the run.

## Frozen interventions

For each family, author exactly one answer-free protocol from validation
evidence. Materialize all eight coalitions of `{I, K, F}`:

`none`, `I`, `K`, `F`, `IK`, `IF`, `KF`, `IKF`.

- `I` appends the reusable procedure to the coder Identity description. It
  does not change the Superego, permissions, model, tools, or task prompt.
- `K` installs a typed Knowledge artifact with source-task and tool-help
  lineage. It is useful only if the runtime actually routes or retrieves it.
- `F` adds a typed preflight Process node that reads public tool help before
  the unchanged coding loop. It contains no fixture values or verifier code.

Each cell gets a fresh workspace and the original benchmark verifier. Every
coalition receives the same model/tool/token/time budget.

## Model and resource budget

Initial policy model: the already cached
`Qwen/Qwen2.5-Coder-14B-Instruct`, served locally with vLLM on one NVIDIA L40S.
No model is fine-tuned. No benchmark result is used as model training data.

Pre-counted integration check note: this vLLM/model pair exposed tools in the
request but emitted one intended call as a canonical fenced JSON object instead
of native `tool_calls`. The frozen base adapter therefore enables
`EGOAGENT_LLM_TEXT_TOOL_FALLBACK=1` for every coalition. It accepts exactly one
`{"name": ..., "arguments": {...}}` object, rejects unknown tools, extra fields
and multiple blocks, and validates the name against the request's tool schema.
This provider-compatibility adapter is fixed across all conditions and is not
an evolved artifact or measured contribution. The failed integration run is
excluded because no tool was executed and no counted pilot had started.

Resource ceilings:

- one GPU only; GPU memory utilization at most 0.85;
- experiment data only under `/scr/yuanyang/egoagent-evocert`;
- hard experiment-directory ceiling: 20 GB;
- one run at a time inside each EgoAgent worker;
- smoke: one family, one repetition;
- pilot: four families, one repetition;
- second repetition only if the smoke/pilot quality gates pass.

The root filesystem was observed at 98% usage with 19 GB free. No experiment
artifact, environment, benchmark clone, or model copy may be written there.

## Outcomes and baselines

Primary cell outcome is binary pass/fail from the benchmark's original
deterministic verifier. Secondary outcomes are tokens, wall time, runtime
terminal state, artifact activation and tool trace.

Compare admission policies:

1. validation-only before/after acceptance of `IKF`;
2. validation + sealed held-out acceptance of `IKF`;
3. SEAL-style incumbent-vs-`IKF` gate with protected tasks;
4. single-artifact/leave-one-out attribution;
5. full `2^3` factorial oracle (available only because this pilot has three
   artifacts);
6. EvoCert's typed factorial report, including interaction and activation.

The factorial oracle chooses the smallest coalition with maximal held-out
success subject to no protected success regression. Token count breaks ties.
It is an analysis oracle, not information available to the evolver.

Report:

- held-out gain over `none`;
- protected-distribution delta;
- all first-, second- and third-order finite-difference interactions;
- unnecessary full-bundle admission relative to the minimal oracle coalition;
- unused Knowledge admission;
- runtime error rate and matched-budget violations;
- disagreement among admission baselines.

## Quality and stopping rules

Stop immediately and repair infrastructure (do not count the run) if:

- the original verifier cannot execute;
- more than 20% of completed cells end in runtime error/timeout;
- a candidate contains held-out/protected prompt text, fixtures or verifier
  implementation;
- workspaces are reused across coalitions;
- the vLLM endpoint or GPU process becomes unhealthy;
- `/scr` free space falls below 3 TB or the experiment exceeds 20 GB.

Stop the research direction after the four-family, one-repetition pilot if any
of these hold:

1. `none` and all evolved coalitions have zero held-out success, so the policy
   model is below the benchmark's useful regime;
2. no family has an absolute second/third-order held-out interaction of at
   least 0.25;
3. held-out + protected gating always agrees with the minimal factorial oracle;
4. Knowledge is never activated and removing it never changes behavior;
5. improvements come only from more model calls/tokens beyond the matched
   budget.

Proceed to a second repetition only if at least one interaction or admission
disagreement is observed and the runtime-error rate is at most 10%. Proceed to
a larger 50-episode study only if the second repetition preserves the sign of
the key interaction/admission result.

## Anti-cheating rules

- Task IDs and splits above are frozen before execution.
- The authoring process never receives sealed prompts or outcomes.
- No task-specific output, gold value or expected filename may be manually
  inserted into an artifact.
- Failed tasks remain failed; a plausible final message cannot override the
  original verifier.
- Infrastructure failures are retained in a separate exclusion log with the
  mechanical reason and rerun ID.
- Negative results and stopped directions are reported.
- Any post-hoc analysis is labelled exploratory and cannot replace the frozen
  primary analysis.
