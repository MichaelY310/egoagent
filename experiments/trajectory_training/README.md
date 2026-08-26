# Exact trajectory training smoke

This experiment verifies the training projections of EgoAgent's append-only
trajectory. It is deliberately deterministic and does not call a model API.

1. Generate a parent/child multi-Agent trace containing a context replacement:

   `python scripts/trajectory_training_smoke.py`

2. Validate that `smoke_result.json` reports three calls split across
   `planner` and `researcher`, and that the final planner request contains the
   compacted summary rather than the original full audit transcript.

3. In WSL, run the one-step LLaMA-Factory smoke with the isolated environment:

   `PYTHONPATH=/home/aa310/egoagent-training/llamafactory-venv/lib/python3.12/site-packages:/home/aa310/vllm-debug/.venv/lib/python3.12/site-packages /home/aa310/egoagent-training/llamafactory-venv/bin/python -m llamafactory.cli train /mnt/c/Users/aa310/Desktop/egoagent/experiments/trajectory_training/llamafactory_sft_smoke.yaml`

The canonical model-call and episode files retain Agent, Identity, run and
parent-run lineage. LLaMA-Factory receives each exact model call as one SFT
sample; it never receives a flattened multi-Agent conversation.

For verl, `verl_rollouts.jsonl` is the lossless interchange format. Convert
trusted-reward rows to the official Parquet prompt dataset inside WSL with:

`PYTHONPATH=/home/aa310/egoagent-training/verl-venv/lib/python3.12/site-packages:/home/aa310/egoagent-training/llamafactory-venv/lib/python3.12/site-packages:/home/aa310/vllm-debug/.venv/lib/python3.12/site-packages /home/aa310/egoagent-training/verl-venv/bin/python /mnt/c/Users/aa310/Desktop/egoagent/scripts/prepare_verl_trajectory.py /mnt/c/Users/aa310/Desktop/egoagent/.egoagent/research/trajectory_training_smoke_v5/export/verl_rollouts.jsonl /home/aa310/egoagent-training/data/egoagent-smoke-v5`

The exporter
also writes `verl_rollouts.parquet` when PyArrow is installed. Only the terminal
call of a run with an explicit `evaluation.completed` event receives a scalar
reward; other calls stay unlabelled and remain available in
`egoagent_episodes.jsonl` for explicit multi-Agent credit assignment.

4. Run the real one-step GRPO smoke from WSL:

   `bash /mnt/c/Users/aa310/Desktop/egoagent/experiments/trajectory_training/run_verl_grpo_smoke.sh`

The script uses vLLM, one AgentLoop worker, two rollouts and one optimizer step.
Under WSL it explicitly selects verl's shared-memory weight-transfer fallback;
the compatibility shim is scoped to this script and does not modify verl or the
normal EgoAgent runtime.

Verified on 2026-08-18: LLaMA-Factory loaded all three model calls and completed
one SFT update. verl's official dataset loader retained the compacted surface and
Agent/run/call metadata, and the GRPO smoke completed rollout, reward, advantage,
backward and weight update with `training/global_step=1`. See
`docs/TRAJECTORY_TRAINING_VALIDATION.md` for exact evidence and limitations.
