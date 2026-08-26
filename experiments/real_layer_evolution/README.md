# Real-task minimal-layer evolution

This experiment replaces the synthetic gains in
`experiments/minimal_layer_evolution` with executions of an external,
mechanically graded benchmark. The initial adapter targets the MIT-licensed
`ai-forever/harness-bench-fast` task registry.

The first preregistered pilot is deliberately narrow and cheap. It uses two
pairs of tasks backed by unfamiliar CLI tools:

- `logq`: task 372 is validation; task 373 is held out.
- `cfgctl`: task 378 is validation; task 379 is held out.

For each family the same DeepSeek V4 Flash model and EgoAgent DAG runtime run
four conditions on fresh workspaces:

1. `static`: no persistent intervention.
2. `knowledge`: a callable Knowledge artifact containing only evidence learned
   from the validation task's public tool help and trajectory.
3. `skill`: an actual executable Identity Skill which reads the target tool's
   own `--help`; it does not contain answers, fixtures, verifier code, or gold
   artifacts.
4. `harness`: a real DAG variant with a deterministic preflight node which
   runs the unfamiliar tool's public `--help` through a typed Process node
   before the normal coding loop. The Process node does not inject an orphaned
   `role=tool` message into strict OpenAI-compatible providers.

`none` is included as an explicit selector candidate. A layer must therefore
beat doing nothing after success, token/cost, maintenance and intrusion are
combined; equal task accuracy never forces an unnecessary mutation.

The candidate artifact is authored from validation evidence only. The held-out
task is never sent to the authoring model. Every condition is evaluated by the
benchmark's original Python verifier. Independent runs use fresh workspaces.

## Reproduction

Clone the external benchmark (ignored by EgoAgent's Git repository):

```powershell
git clone --depth 1 https://github.com/ai-forever/harness-bench-fast.git `
  experiments/external/harness-bench-fast
```

Run a single-family smoke pilot first:

```powershell
python experiments/real_layer_evolution/run_harnessbench_pilot.py `
  --families logq --repetitions 1
```

Run both preregistered families:

```powershell
python experiments/real_layer_evolution/run_harnessbench_pilot.py `
  --families logq cfgctl --repetitions 3
```

Use `--skip-authoring` to reuse an already saved validation-derived protocol.
Use `--resume` to reuse completed cells from `partial.json`; add
`--rerun-layers harness` (or another layer) to replace only selected cells.
Raw runs and generated identities/harnesses live below this experiment's
`_runs` directory, which is ignored by Git.

## DeepSeek V4 Flash smoke results (2026-08-13)

These are one-repetition integration smokes, not leaderboard estimates or
statistically powered claims. Every reported pass used the external task's
original verifier and the relocated `.hb_tool_calls` invocation log.

| Family | Static success / mean tokens | Knowledge | Skill | Harness | Selected |
|---|---:|---:|---:|---:|---|
| `logq` | 2/2 / 44,670 | 2/2 / 27,918.5 | 2/2 / 29,667.5 | 1/2 / n/a¹ | Knowledge |
| `cfgctl` | 2/2 / 38,490 | 2/2 / 36,803.5 | 2/2 / 36,032.5 | 2/2 / 47,973.5 | none |

¹ The failed `logq` Harness cell did not persist aggregate provider usage, so
its two-cell token mean is intentionally not reported.

For `logq`, Knowledge retained all task passes while reducing mean actual
tokens by about 37.5% and wall time from 21.0s to 15.1s. For `cfgctl`, the
small efficiency changes did not repay artifact maintenance/intrusion, so the
selector correctly retained `none`. The `logq` Harness failed one cell by
repeating post-completion checks until the model-call budget was reached; a
correct output from an errored runtime is scored as failure.

The pilot exposed and fixed six evaluation-validity issues: Windows CLI launch
fallback, external tool-call log relocation, actual-token field selection,
explicit no-op comparison, preservation of TaskBench's structured workspace
context, and strict provider message sequencing for deterministic preflight.

## Interpretation limits

This pilot provides real model calls, real tool use, real file changes and the
original benchmark verifier. It does **not** yet provide an oracle across all
EgoAgent layers. Harness-Bench Fast supplies task outcome labels, not labels for
the smallest persistent layer. The broad paper benchmark should therefore use
public tasks as the substrate and add blinded human annotations for `none`,
Knowledge, Skill, Identity, child Agent and Harness, with inter-annotator
agreement reported.
