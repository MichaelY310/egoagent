# Minimal-layer evolution benchmark

This benchmark asks a causal question that prompt-only evolution benchmarks do
not: **which persistent layer is the smallest intervention that fixes a repeated
failure?** It compares a prior-only selector, largest observed mutation,
empirical selection without provenance, EgoAgent's matched-shadow selector with
an evidence firewall, and an oracle.

Run:

```powershell
python experiments/minimal_layer_evolution/run_benchmark.py
```

The committed result is a deterministic mechanism test. It must not be reported
as real-model performance. Replace the synthetic paired measurements with Task
Bench records before using the protocol for a paper.
