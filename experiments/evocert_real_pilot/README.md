# EvoCert real-task pilot

This directory implements the frozen protocol in
`docs/EVOCERT_REAL_PILOT_PREREGISTRATION_20260902.md`.

The runner uses Harness-Bench Fast's original task setup and deterministic
verifier. It authors a reusable protocol from a validation task only, then
evaluates all coalitions of three typed artifacts: Identity (`I`), Knowledge
(`K`) and Flow (`F`). Held-out and protected prompts are never supplied to the
authoring model.

Smoke run:

```powershell
python -m experiments.evocert_real_pilot.run --families logq --repetitions 1
```

Frozen four-family pilot:

```powershell
python -m experiments.evocert_real_pilot.run `
  --families logq pktool xtab cfgctl --repetitions 1
```

Analyze a run without making model calls:

```powershell
python -m experiments.evocert_real_pilot.analyze `
  experiments/evocert_real_pilot/_runs/<stamp>/report.json
```

Use `--resume --stamp <stamp>` after an infrastructure interruption. Raw
workspaces, trajectories and reports are ignored by Git.
