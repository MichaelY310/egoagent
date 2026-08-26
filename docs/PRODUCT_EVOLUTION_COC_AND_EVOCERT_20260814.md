# EgoAgent product workflow, CoC table, and EvoCert status

Date: 2026-08-14

## Product workflow

Studio now presents one primary path:

1. **Build** an Identity + EGO + DAG.
2. **Evaluate** on a task or dataset with replayable traces and deterministic checks.
3. **Improve** only after a real failure is observed. The default action is to diagnose the smallest useful layer: Knowledge, Skill, child Agent, Harness, Identity, or runtime.
4. **Deploy** a versioned capability package only after held-out and regression evidence passes. Every install remains reviewable and reversible.

Home shows real recent runs and turns a selected failure into an Improve observation. Advanced workbenches remain available under **More**, but do not occupy the first-run navigation. Improve keeps capability diagnosis and the normal evolution cycle visible; certificate protocols, principles, and archives are collapsed until requested.

## CoC multi-Agent table

Two structured adapters are available:

- `coc_lightless_beacon`
- `coc_the_haunting`

They require the official free Chaosium material for full prose and handouts. Repository adapters contain only structured state, short summaries, and source links.

Roles:

- **KP**: atmosphere, NPCs, and narration. It cannot override a deterministic resolution.
- **Rules judge**: converts natural-language proposals to a bounded JSON action vocabulary. It does not roll dice or mutate state.
- **AI investigator A/B**: propose one action per round from public state only.
- **Human investigator**: the Studio chat input is a real human seat in the DAG.

Authoritative state includes per-actor location, HP, SAN, inventory ownership, ammunition, discovered clues, scene-bound ground items, entities, rounds, and an append-only resolution log. A generic `Data/state_transition` node checks expected revision, preconditions, operations, and JSON Schema before committing atomically. A rejected transition changes nothing.

## How to try the table

1. Open Studio at `http://127.0.0.1:8765/`.
2. On Home, choose **The Lightless Beacon** or **The Haunting**.
3. Press **Execute**. The graph highlights the current node and shows a compact live card beside it.
4. When `human_turn` appears, enter one investigator action in the chat panel.
5. Use **Run observability** to inspect the model request/response, normalized action, deterministic resolution, state transaction, token usage, and timing for any invocation.
6. Use Pause / Step / Auto to inspect one node at a time.

Useful consistency probes:

- Drop the revolver, then try to fire it. The second action must be rejected with `firearm_not_carried`; ammunition and target HP must not change.
- Let one AI investigator move while the human remains behind. Only that actor's location may change.
- Drop an item, separate the party, and ask a remote actor to pick it up. It must be rejected until that actor reaches the item's location.

## EvoCert research gate

EvoCert is implemented as a deterministic certificate over a declared multi-artifact update. It records:

- activation of every changed artifact;
- validation and sealed-heldout paired effects separately;
- artifact knockout necessity;
- low-order interaction terms;
- protected-task non-interference;
- fresh Identity/model/Harness graft portability;
- semantic verifier mutation score;
- evidence lineage, matched budgets, and a SHA-256 certificate ID.

It accepts, rejects, or abstains. Missing portability or verifier-mutation evidence causes abstention; validation-only improvement cannot pass the sealed-heldout gate.

### Real pilot result (not a paper claim)

Harness-Bench Fast `logq` was run with DeepSeek V4 Flash on one validation task and one unseen held-out task, three repetitions each, fresh workspace per run, using the benchmark's original verifier:

| Variant | Runs | Success | Mean tokens | Mean seconds |
|---|---:|---:|---:|---:|
| Static | 6 | 100% | 41,834 | 19.31 |
| Knowledge | 6 | 100% | 28,220 | 14.94 |
| Skill | 6 | 100% | 37,407 | 17.42 |
| Harness | 6 | 50% | 23,738 | 30.50 |

The selector chose **Knowledge**, saving 32.1% tokens with unchanged success. The more invasive Harness mutation failed half the runs and was ineligible. This is evidence for minimum-layer selection on one task family, not evidence for EvoCert's full causal-certificate thesis.

`experiments/real_layer_evolution/issue_evocert.py` converts a real pilot report into a certificate preflight. It currently refuses to issue a publishable certificate because this run lacks protected-task executions, fresh graft executions, and semantic verifier mutants. Those missing fields are written explicitly; no synthetic substitute is generated.

## Novelty boundary

The 2026 literature already contains harness self-evolution, source-level self-rewriting with deterministic verification, and joint Skill/Harness evolution. Therefore those are product capabilities and baselines, not EgoAgent's main novelty claim. The narrower research hypothesis is:

> Can a self-evolving Agent promote a heterogeneous update only when a portable, lineage-aware causal certificate establishes which artifacts activated, which were necessary, how they interacted, whether the effect survives a fresh graft, and whether protected behavior remains unchanged?

Targeted literature search found no direct match for that complete multi-artifact promotion certificate, but this is not a guarantee of novelty. The next research gate is a manually audited benchmark of real evolution episodes with protected tasks, graft targets, and verifier mutants. Large-scale API spending is justified only after the first 50-episode pilot shows materially better false-promotion and rollback outcomes than heldout-only and gated-harness baselines.
