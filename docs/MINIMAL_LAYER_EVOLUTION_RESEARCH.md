# Minimal-layer, provenance-safe self-evolution

Updated: 2026-08-12

> **2026-08-13 novelty gate:** A subsequent literature audit found substantial
> overlap with Self-Harness, HSI, CHILL-Harness, AgentEvo, SIGIL and VaG. A
> large-scale run of the current method was therefore stopped before additional
> API or Docker spend. See `docs/NOVELTY_AUDIT_AND_SCALE_GATE_20260813.md` for
> the no-go decision and the proposed Reversible Capability Placement pivot.

## Research thesis

Generic prompt optimization and unconstrained DAG search are no longer a
sufficient novelty claim. EgoAgent's stronger question is:

> When an agent repeatedly fails, what is the **smallest persistent control
> layer** that causally fixes the failure—Knowledge, Skill, Identity, child
> agent, or Harness—and what evidence is trustworthy enough to promote that
> change?

This produces two coupled research contributions:

1. **Causal evolution localization:** evaluate candidate layers on identical,
   budget-matched shadow tasks and choose the least intrusive layer within a
   simplicity margin of the best measured utility.
2. **Evolution evidence firewall:** repeated trajectories from one origin count
   as one lineage; permanent evolution requires an independent lineage and at
   least one trusted verifier/replay/human/signed artifact.

The mechanism can choose `none`. Evolution is therefore an observed decision,
not a prompt-forced behavior.

## Literature boundary and novelty risk

| Work | What it already covers | EgoAgent must not claim | Remaining gap used here |
|---|---|---|---|
| MOSS (`arXiv:2605.22794`) | source-level agent/harness rewriting | “agents can rewrite their harness” | selecting the minimal persistent layer and proving evidence lineage |
| MASS (OpenReview `uCKvHweh1g`) | multi-agent system search | generic topology optimization | cross-layer causal localization under equal budgets |
| MermaidFlow (`bhPaXhWVKG`) / TopoWeaver-R1 (`i6PCa45gBh`) | workflow/topology synthesis | graph mutation as novelty | no-change and least-intrusive selection with promotion safety |
| CHILL-Harness (`arXiv:2607.25825`) | counterfactual harness learning | counterfactual replay alone | compare interventions across Knowledge/Skill/Identity/Harness |
| SIGIL (`arXiv:2607.27309`) | compiling skills into typed harnesses | skill-to-harness compilation | decide whether compilation is warranted at all |
| PoisonedEvolution (`arXiv:2608.05563`) / TBA (`2608.08303`) | evolution/backdoor attacks | first identification of poisoning | lineage-aware promotion defense integrated with causal selection |
| Harness-Bench (`arXiv:2605.27922`), WorfBench (`vunPXOFmoi`) | harness/workflow evaluation | a complete new benchmark from scratch | extend evaluation with over-evolution and poison-promotion metrics |

The idea is plausibly differentiable, not proven novel enough for NeurIPS by
this implementation alone. A submission still needs a formal threat model,
pre-registration, competitive baselines, multiple model families, real task
outcomes, and statistical power.

## Implemented system

`self_evolution/proof_evolution.py` now provides:

- `assess_evolution_evidence`: trust normalization, content hashes, lineage
  deduplication, trusted-anchor and independent-lineage gates;
- `select_empirical_evolution_artifact`: identical paired task enforcement,
  validation/held-out/regression splits, bootstrap confidence intervals,
  matched budgets, risk/cost/token utility, and a least-intrusive near-best
  rule;
- strict default `GovernancePolicy` evidence integrity for persistent changes;
- proposal normalization that carries its evidence assessment into the audit
  record.

Studio's **Proof-carrying Evolution Lab** exposes both the old estimate-based
prior and the new matched-shadow selector. The result shows all ranked layers,
confidence intervals, ineligibility reasons, provenance assessment, and the
chosen layer before a proposal can enter experimental state.

The deterministic mechanism benchmark is at
`experiments/minimal_layer_evolution/run_benchmark.py`. Its committed report is
`experiments/results/minimal_layer_selection.json`.

## Current deterministic evidence

Seventeen causal fixtures cover paper/schema recall, reusable procedures,
identity drift, context-isolated child agents, structural approval/retry loops,
no-change cases, and three one-origin poisoning cases.

| Selector | Exact minimal layer | Over-evolution | Poison promotion |
|---|---:|---:|---:|
| prior only | 64.71% | 29.41% | 100% |
| largest observed mutation | 11.76% | 82.35% | 100% |
| empirical, no firewall | 82.35% | 11.76% | 100% |
| EgoAgent minimal + firewall | 100% | 0% | 0% |

These are **synthetic causal fixtures**, useful for regression-testing the
mechanism. They are not LLM benchmark results and must not appear in an abstract
as empirical agent performance.

## Paper hypotheses

- **H1 — localization:** matched-shadow selection improves exact minimal-layer
  accuracy over prompt-only priors and performance-maximizing mutation.
- **H2 — efficiency:** minimal sufficient evolution reduces parent-context
  tokens, persistent instruction size, and intervention maintenance without
  reducing held-out success.
- **H3 — safety:** lineage plus trusted-anchor gating lowers poison promotion
  and backdoor attack success under recurrent and cross-task poisoning.
- **H4 — lifelong stability:** choosing Knowledge/Skill before Identity/Harness
  when sufficient reduces negative transfer and catastrophic behavioral drift.
- **H5 — weak-model leverage:** a small model can propose candidates while
  deterministic replay and typed governance provide most selection reliability.

## Additional brainstormed directions

1. **Information-boundary evolution:** learn when a result-only child agent is
   worth its isolation cost, optimizing parent token pollution rather than only
   answer accuracy.
2. **Identity bifurcation tests:** before changing Identity, shadow-run a scoped
   role overlay against a permanent personality mutation and measure unrelated
   task drift.
3. **Evolution debt:** treat every persistent node/prompt/skill as carrying
   maintenance and regression debt; periodically compress or retire artifacts
   whose amortized reuse falls below zero.
4. **Bidirectional compilation:** compile recurring trajectories into typed
   Skills/Harnesses, but also decompile brittle Harness regions back into a
   simpler Skill when structural control is unnecessary.
5. **Counterfactual credit maps:** attribute success to individual changed DAG
   edges/nodes through replay interventions, then expose the causal map beside
   Studio's live node trace.
6. **Adversarial evolution immune system:** create red-team child agents that
   generate poisoned memories/skills/DAG proposals and train promotion policy
   against attack transfer across generations.

The first two implemented contributions should remain the primary paper spine;
the other ideas are ablations/extensions until real evidence shows otherwise.

## Required real evaluation

1. Build 150–300 tasks with oracle minimal layers, including legitimate
   no-change cases and ambiguous multi-layer cases.
2. Use at least one weak 7–9B model, one mid-tier model, and one frontier model;
   report three or more seeds.
3. Materialize every candidate layer and run identical validation, held-out and
   regression tasks under equal token/cost/time caps.
4. Baselines: static agent, prompt-only selection, largest-gain mutation,
   harness-only search, CHILL-style counterfactual harness learner, and oracle.
5. Attacks: repeated single-origin trace poisoning, cross-origin collusion,
   trusted-checker compromise, delayed trigger, and clean-label skill injection.
6. Metrics: task success, exact layer accuracy, over/under-evolution, parent and
   total tokens, amortized evolution cost, forgetting, negative transfer,
   poison-promotion rate, attack success, and recovery latency.
7. Pre-register thresholds and report confidence intervals; do not tune the
   simplicity margin on held-out tasks.

## Public real-task benchmark decision (2026-08-13)

The first real-model pilot uses the MIT-licensed Harness-Bench Fast registry.
Its current task set provides hundreds of fresh, mechanically verified offline
workspace tasks, including memory, skills, policy, adversarial execution and
unfamiliar CLI tools. The pilot reuses the original task setup callbacks and
Python verifiers rather than translating expected answers into EgoAgent checks.

Two CLI families are preregistered for the first low-cost run: `logq` tasks
372/373 and `cfgctl` tasks 378/379. The first task in each pair is validation;
the second is hidden from candidate authoring and used as held-out transfer.
Knowledge, executable Skill and typed Harness candidates are materialized as
real EgoAgent artifacts, then run through the same DeepSeek V4 Flash model,
fresh workspace, network policy and DAG budget.

This public substrate is suitable for measuring real outcome and transfer, but
it does not contain oracle labels for the smallest persistent EgoAgent layer.
The paper-scale benchmark therefore should not be generated entirely from
scratch. It should combine public task fixtures/verifiers with blinded human
annotation of `none`, Knowledge, Skill, Identity, child Agent and Harness. A
small number of new tasks is still necessary for Identity drift, information
boundary/child-Agent, and no-evolution cases that public task suites do not
separate cleanly. Report inter-annotator agreement and adjudication rather than
treating the authors' layer choice as unquestioned ground truth.

Implementation and reproduction notes are in
`experiments/real_layer_evolution/README.md`.

## Initial V4 real-task evidence (2026-08-13)

The first external-task smoke used one validation and one hidden held-out task
from each of two unfamiliar-CLI families. All static, Knowledge and Skill cells
passed their original external verifiers. The empirical selector chose
Knowledge for `logq` (44,670 → 27,918.5 mean actual tokens, about 37.5% less,
with 2/2 success) and chose `none` for `cfgctl` because its small token savings
did not repay persistence and intrusion costs. This is the desired qualitative
behavior: the method sometimes evolves and sometimes refuses to evolve.

A separate real-world smoke used SWE-bench Verified instance
`pallets__flask-5014`, a real GitHub issue at the benchmark base commit. The
agent received the issue and official reproduction test but not the gold
solution patch. DeepSeek V4 Flash produced the same three-line production fix
as the gold patch, passed the focused test and all 60 nearby Blueprint tests.
This establishes the repository-level execution and evaluation path, not the
paper hypothesis by itself.

### Benchmark portfolio

- **Mechanism/transfer pilot:** Harness-Bench Fast, cheap host execution,
  original verifiers, multiple persistent layers.
- **Real repository outcomes:** SWE-bench Verified or a fresher rolling
  successor, issue-specific tests and untouched regression tests.
- **Longitudinal reuse:** ContinualSkillBench / LifelongAgentBench-style ordered
  sequences to measure reuse, forgetting and evolution debt.
- **Safety:** a small authored extension is still required for lineage poison,
  identity drift and information-boundary/child-Agent cases because public
  suites do not provide minimal-layer oracle labels for these mechanisms.

SWE-bench's official evaluator uses Linux Docker images and warns that broad
runs can require roughly 120GB free storage, 16GB RAM and 8 CPU cores. On this
resource-limited Windows host, use a local pinned venv for integration smokes
and Docker only for one selected issue at a time (`max_workers=1`, instance
cache, explicit disk/memory monitoring). A paper result must eventually be
rechecked in the official container; the host-only Flask run must remain
labelled a low-resource smoke.

## Reproduction

```powershell
python experiments/minimal_layer_evolution/run_benchmark.py
python -m unittest discover -s tests -p 'test_proof_evolution.py'
```

In Studio, open **Research → Proof-carrying Evolution Lab**, run “Minimal
sufficient layer (matched shadow runs)”, inspect the ranked evidence, then
register/apply/gate a proposal. One-lineage evidence is intentionally blocked.
