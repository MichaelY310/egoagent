# EgoAgent product and research verification

Last verified: 2026-08-11

This is the shortest reproducible route through the completed product and research features. API
keys stay in the ignored `.env.local`; none of the commands below print or embed a key.

## Open the product

- Void IDE: `http://127.0.0.1:8880/?folder=/C:/Users/aa310/Desktop/egoagent`
- Studio: `http://127.0.0.1:8765/`

The verified live Studio top bar contains Harness, EgoIR, Task Bench, Research, Background,
Packages, Agent Changes, Checkpoints, Identity, Environment, Sessions, Evolution, and Settings.
Void's native right-side Chat contains Chat/Plan/Agent/Debug/Evolve/Evaluate modes, Harness and
Identity selection, DAG/run/change/context views, and the configured provider status.

## Deterministic release gates

Run from the repository root:

```powershell
C:\Users\aa310\miniconda3\envs\3d\python.exe -m unittest discover -s tests
```

Expected on the verified Windows host: `Ran 312 tests ... OK (skipped=3)`. The skips are explicit
environment boundaries such as Docker/symlink privileges, not silent feature passes.

Build Studio:

```powershell
cd harness_editor
& 'C:\Program Files\nodejs\npm.cmd' run build
```

Expected: TypeScript succeeds and Vite writes `dist/`. The current bundle transformed 210 modules.

## Verify the product UI

### Task Bench and live DAG cards

1. Open Studio → **Task Bench**.
2. Choose **离线 DAG / Tool Trace 自检** for a no-key smoke test.
3. Enable **首节点前暂停** if desired, then start.
4. Use step/auto/pause and click an active node. The adjacent activity card and lower timeline show
   model text, tool calls, input/output, retries, artifacts, duration and token/cost statistics.
5. Inspect **评分**, **产物**, and **进化**. The run is isolated and persists in recent runs.

The live browser verification loaded 9 tasks, 49 Harnesses, 25 Identities, recent-run history, and
the three-node `react_single` graph. `aider_replica` is available in both Studio and Void.

### EgoIR

1. Open Studio → **EgoIR**.
2. Select a Harness and press **Validate**.
3. Edit the compact line format or use constrained operations such as:

```json
[{"op":"set_limits","max_steps":100}]
```

4. **Dry run** first; then commit. Revision checks, structural validation, checks and transaction
   undo protect the change. Common graph edits do not require Python.

### Transactional code review

1. Let an Agent edit a file in Void; the edit is applied immediately.
2. Open the changed file. Green additions and red deletions appear in Monaco with per-hunk Accept,
   Reject and Undo actions.
3. Accept keeps the materialized edit. Reject restores only that hunk. Undo reverses the review
   decision—not the whole Agent transaction.
4. Rejecting a newly created file asks before deletion. The same transaction is visible in Studio
   → **Agent 改动**; request/file checkpoints are under **检查点**.

### Evolution

Studio → **Evolution** exposes two related paths:

- **Artifact selector** compares no-change, Knowledge, Skill, Identity/sub-Agent and Harness using
  reuse benefit, token saving, confidence, implementation/maintenance cost and regression risk.
- **Proof-carrying proposal** requires evidence, scope, revision-checked change, train/validation/
  held-out/regression splits, budget, rollback and confidence. Changes remain quarantined until all
  gates pass.

The same selector is a real Dante tool named `select_evolution_artifact`, so a weak model can make
and log the decision inside Task Bench rather than only through the UI.

## Reproduce the research results

### Harness conformance

Open Studio → **Research** → **Harness Conformance** and press **运行全部行为契约**, or run:

```powershell
C:\Users\aa310\miniconda3\envs\3d\python.exe harness_conformance.py --run-behavior
```

Verified result: all 15 pinned open-source contracts pass the Ego replica core; all 45 offline
behavioral tests pass. External account/browser/SaaS boundaries are reported separately and are not
misrepresented as reproduced.

### Weak-model representation benchmark

The real 25-call DeepSeek V4 Flash report is:

`./.egoagent/research/ir-benchmark-20260811-084602.json`

All five formats produced valid Harnesses. High-level structural operations achieved 1.0 exact,
edit and held-out generalization accuracy with the lowest observed latency and only 358 output
tokens. EgoIR was the strongest inspectable textual format (0.79786 edit accuracy). This is why the
product uses high-level operations for weak-model mutation and EgoIR as the canonical review form.

### Non-cheating self-evolution probe

The valid real-provider run is:

`./experiments/self_evolution_emergence/_runs/20260811_093319/report.json`

Task: `latent_semantic_delegate`. The prompt describes a recurring open-ended local research queue,
5–20 noisy searches and a required parent-context isolation boundary. It does not name a mutation
tool, expected artifact, evaluator check, or desired Identity/Harness.

Observed behavior:

1. DeepSeek read the local evidence and answered the three questions.
2. It called `select_evolution_artifact`; Identity ranked first at utility 0.59 while static
   Knowledge/Skill were rejected for this changing semantic workload.
3. It called `create_identity` and installed `archive_researcher` with inherited read-only search
   capabilities.
4. It called `create_harness` with the existing `bounded_action_worker` in `return_mode=last`, proving
   result-only child-context isolation, including an intentionally missing Project VEGA case.
5. The mutation manifest recorded the new Identity/capabilities and the event stream recorded
   `identity_evolution`.

The original run scored 0.7778 and passed. Its only missed check demanded creation of a duplicate
Harness even though reuse of a verified existing result-only Harness is the smaller, safer design.
The task contract now accepts a successful `create_harness` delegation call; deterministic rescoring
of the preserved trace is 1.0 (all 7 checks). This change removes an incentive to manufacture
unnecessary components.

Earlier runs at `20260811_090552`, `20260811_091335`, and `20260811_092638` are retained as negative
infrastructure evidence. They exposed, respectively, model non-installation, empty provider turns,
and a permission bug that treated artifact categories as object names. They are not counted as
model-capability failures. The fix is covered by permission, Task Bench and pipeline trace tests.

To spend API credit on a new independent run:

```powershell
C:\Users\aa310\miniconda3\envs\3d\python.exe `
  .\experiments\self_evolution_emergence\run_deepseek_emergence.py latent_semantic_delegate
```

### Reproducible science loop

Open Studio → **Research** → **证据科学循环**. Create a falsifiable project and advance the fixed
retrieve → hypothesis → plan → implement → execute → analyze → repair → independent review → report
pipeline. Every claim must point to a SHA-256-verified local artifact or source; the reviewer must be
independent, the executed command must match the plan, and integrity re-audit detects tampering.

## External-only verification boundaries

- A real Docker/Harbor image smoke requires a running Docker daemon.
- Native installer smoke for macOS/Linux requires those hosts.
- Remote PR publication and public marketplace publishing require their respective accounts/tokens.

All local product paths, deterministic substitutes, provider-agnostic runtime behavior and the
configured DeepSeek live path are implemented and verified without those optional dependencies.
