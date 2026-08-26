# Novelty audit and scale-experiment gate

Date: 2026-08-13

> **Superseded research direction:** A broader same-day audit found that
> Dynamic Agent Skills (`arXiv:2607.10113`) and SLIM (`arXiv:2605.10923`)
> substantially occupy lifecycle-managed promotion, demotion, pruning and
> retirement. RCP remains useful engineering but is no longer the recommended
> paper spine. The current primary direction is multi-artifact causal evolution
> certification; see `docs/EGOAGENT_HIGH_NOVELTY_RESEARCH_DIRECTIONS_20260813.md`.

## Decision

**NO-GO for a large-scale experiment on the current method.**

The current prototype is useful engineering and its pilot behavior is
encouraging, but the paper claim is no longer sufficiently isolated for a
NeurIPS submission.  In particular, "an agent can change its DAG/harness",
"choose a small validated harness edit", "optimize accuracy and token cost",
and "gate contaminated evolution before admission" are now each directly
covered by recent work.  Scaling the existing experiment would produce more
evidence for an under-differentiated method, not stronger novelty.

No new API batch or Docker benchmark was started after this audit.

## Collision matrix

| EgoAgent claim | Closest prior work | Collision |
|---|---|---|
| Optimize prompts and graph edges/nodes | GPTSwarm, AFlow, ADAS, AgentSquare | Direct: automatic graph/workflow/module search is established. |
| Self-modify the executable harness | Self-Harness, HSI | Direct: self-rewriting harnesses, held-out validation and hierarchical meta-evolution are established. |
| Prefer a minimal validated harness change | Self-Harness | Strong: its proposal stage explicitly produces minimal failure-linked edits and admits them after regression tests. |
| Use counterfactual evidence to avoid unnecessary orchestration | CHILL-Harness | Strong: causal intervention effects, success preservation and advantage-margin authorization are central contributions. |
| Balance performance, tokens and structural complexity | AgentEvo | Direct: cost-aware Pareto evolution, refinement and structural pruning are established. |
| Turn repeated procedures into executable harnesses | SIGIL | Direct for the one-way Skill -> Harness transition. |
| Gate persistent evolution using trusted evidence | VaG / PoisonedEvolution | Strong: pre-commit admission and contamination chains are explicitly studied. EgoAgent's lineage deduplication is a useful defense detail, but is too narrow alone. |
| Evolve memory infrastructure and revert regressions | EvolveMem | Direct within the memory layer. |
| Decide among Knowledge, Skill and Harness | Self-evolution survey + externalization survey | The taxonomy is established conceptually; merely implementing a router over the taxonomy is not enough. |

## What remains scientifically promising

The defensible pivot is not **how to evolve a layer**, but:

> **Where should an acquired capability live over its lifetime, and when
> should it be promoted, demoted, split, merged, or retired?**

Call this **Reversible Capability Placement (RCP)**.  It treats externalized
capabilities as a lifecycle rather than an append-only library or a one-shot
workflow search:

```text
transient trace <-> Knowledge <-> Skill <-> child Agent <-> typed Harness
                         |                         |
                         +------ retire/split -----+
```

Identity/Ego should remain in EgoAgent, but should not be presented as the next
rung on this complexity ladder.  Identity is a protected behavioral/governance
axis.  A capability placement decision may request a scoped Identity overlay,
but permanent Identity mutation must be evaluated separately for unrelated-task
behavioral drift.

For a horizon of future tasks, RCP should minimize:

```text
task loss
+ invocation tokens and latency
+ one-time authoring/migration cost
+ maintenance and retrieval cost
+ negative-transfer and behavioral-drift risk
+ provenance/security risk
```

subject to verifier-backed task success and regression constraints.  The
important new actions are bidirectional migration and retirement, rather than
only adding a skill or rewriting a workflow.  A task family with low recurrence
should remain transient; repeated prose procedures can become Skills; strict
control-flow requirements can compile into a Harness; declining reuse or a
distribution shift can demote or retire the artifact.

This direction appears less directly occupied than the current method, but is
still only a **candidate novelty claim**, not a certified one.  SIGIL covers
one-way compilation and several systems expose skill cleanup; the paper must
show that online cross-representation placement and demotion are a distinct
learning problem with measurable benefit.

## Required cheap novelty gate before scale

Do not run a large model experiment until all of these pass:

1. Define RCP as a sequential decision problem and state identifiability
   assumptions for reuse frequency, verifier noise and migration cost.
2. Demonstrate in a deterministic simulator that an append-only skill learner,
   a harness-only optimizer and a one-shot layer selector are each suboptimal
   under at least three non-trivial regimes.
3. Build 8-12 public task families with temporal order and at least five tasks
   per family.  Required phenomena are promotion, no-op, demotion/retirement,
   and a distribution shift that makes a formerly useful artifact harmful.
4. Pre-register utility weights or report a Pareto surface; do not tune the
   placement threshold on held-out tasks.
5. Confirm that no newer work performs online bidirectional placement over
   memory/knowledge, executable skills, subagents and harnesses under lifecycle
   cost.  If one does, stop or narrow the claim again.

## Resource estimate for the experiment that was stopped

The estimate below uses the completed DeepSeek V4 Flash pilot rather than a
theoretical token count:

- 15 complete cells: 608,275 actual tokens and 300.268 seconds of provider
  runtime.
- Mean per cell: 40,552 tokens and 20.0 seconds.
- Of the measured input, 456,704 tokens were cache hits and 127,201 were cache
  misses; output was 24,370 tokens.
- At the API prices visible on 2026-08-13, the measured 15 cells cost about
  USD 0.026.  A 50-task x 4-candidate x 3-seed design projects to about 24.3M
  tokens, 3.34 provider-hours if serial, and USD 1.04 if the same cache ratio
  holds.  Candidate authoring, retries, failed loops and official repository
  setup are not included, so a practical budget should be 2-4x higher.
- DeepSeek documents a price change effective 2026-08-16.  Under the announced
  rates, the same 600-cell projection is approximately USD 1.89 off-peak or
  USD 3.78 peak before the 2-4x safety factor.

Host resources at the audit were 12 logical CPUs, about 64 GB RAM with about
50 GB free, and 622 GB free on C:.  This is enough for one Docker evaluator at
a time.  Docker Desktop's Linux engine was not running.  The bottleneck for a
small 30-50 task study is therefore experimental validity and API budget, not
RAM; broad SWE-bench image caching and parallel evaluation would still put
substantial pressure on disk and memory.

## Resume condition

The next model spend is authorized only after RCP clears the five-item novelty
gate.  The first empirical run should then be a 10-family, 5-task-per-family,
three-seed pilot with explicit append-only, harness-only, one-shot selector,
RCP and oracle baselines.  Until then, the current real-task pilot remains an
engineering validation and must not be presented as evidence of a new
self-evolution algorithm.
