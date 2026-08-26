#!/usr/bin/env bash
set -euo pipefail

# One real, deliberately tiny GRPO update over an EgoAgent trajectory export.
# This is a plumbing/integrity smoke test, not evidence of model improvement.

PYTHON_BASE=/home/aa310/vllm-debug/.venv
VERL_ROOT=/home/aa310/egoagent-training/externals/verl
VERL_SITE=/home/aa310/egoagent-training/verl-venv/lib/python3.12/site-packages
LLAMAFACTORY_SITE=/home/aa310/egoagent-training/llamafactory-venv/lib/python3.12/site-packages
WSL_COMPAT=/mnt/c/Users/aa310/Desktop/egoagent/experiments/trajectory_training/wsl_compat
MODEL_PATH=/home/aa310/.cache/huggingface/hub/models--hmellor--tiny-random-LlamaForCausalLM/snapshots/9408c553e5c189a7dcdc5a5dbd2feb476b061759
TRAIN_FILE=/home/aa310/egoagent-training/data/egoagent-smoke-v5/train.parquet
VAL_FILE=/home/aa310/egoagent-training/data/egoagent-smoke-v5/val.parquet
REWARD_FILE=/mnt/c/Users/aa310/Desktop/egoagent/experiments/trajectory_training/verl_reward.py
RESULTS_DIR=/home/aa310/egoagent-training/results/verl-grpo-smoke

export PYTHONPATH="${WSL_COMPAT}:${VERL_ROOT}:${VERL_SITE}:${LLAMAFACTORY_SITE}:${PYTHON_BASE}/lib/python3.12/site-packages"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export RAY_TMPDIR=/home/aa310/egoagent-training/ray-tmp
# WSL's CUDA driver does not expose the UVA capability required by vLLM's V2
# runner. vLLM provides this compatibility switch for its V1 runner.
export VLLM_USE_V2_MODEL_RUNNER=0
export EGOAGENT_VERL_FORCE_SHM=1

mkdir -p "${RAY_TMPDIR}" "${RESULTS_DIR}"
cd "${VERL_ROOT}"

"${PYTHON_BASE}/bin/python" -m verl.trainer.main_ppo \
  algorithm.adv_estimator=grpo \
  algorithm.use_kl_in_reward=false \
  data.train_files="${TRAIN_FILE}" \
  data.val_files="${VAL_FILE}" \
  data.train_batch_size=1 \
  data.max_prompt_length=256 \
  data.max_response_length=32 \
  data.filter_overlong_prompts=true \
  data.filter_overlong_prompts_workers=1 \
  data.truncation=error \
  data.shuffle=false \
  actor_rollout_ref.model.path="${MODEL_PATH}" \
  actor_rollout_ref.model.use_remove_padding=false \
  +actor_rollout_ref.model.override_config.attn_implementation=sdpa \
  actor_rollout_ref.actor.optim.lr=1.0e-5 \
  actor_rollout_ref.actor.ppo_mini_batch_size=1 \
  actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu=1 \
  actor_rollout_ref.actor.use_dynamic_bsz=false \
  actor_rollout_ref.actor.use_kl_loss=false \
  actor_rollout_ref.actor.entropy_coeff=0 \
  actor_rollout_ref.actor.use_torch_compile=false \
  actor_rollout_ref.actor.strategy=fsdp \
  actor_rollout_ref.rollout.name=vllm \
  actor_rollout_ref.rollout.mode=async \
  actor_rollout_ref.rollout.n=2 \
  actor_rollout_ref.rollout.top_k=-1 \
  actor_rollout_ref.rollout.tensor_model_parallel_size=1 \
  actor_rollout_ref.rollout.gpu_memory_utilization=0.2 \
  actor_rollout_ref.rollout.enforce_eager=true \
  actor_rollout_ref.rollout.enable_chunked_prefill=false \
  actor_rollout_ref.rollout.enable_prefix_caching=false \
  actor_rollout_ref.rollout.max_num_batched_tokens=512 \
  actor_rollout_ref.rollout.max_num_seqs=8 \
  actor_rollout_ref.rollout.checkpoint_engine.update_weights_bucket_megabytes=16 \
  actor_rollout_ref.rollout.agent.num_workers=1 \
  actor_rollout_ref.rollout.do_sample=true \
  actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=1 \
  reward.custom_reward_function.path="${REWARD_FILE}" \
  reward.custom_reward_function.name=compute_score \
  trainer.logger='["console"]' \
  trainer.project_name=egoagent \
  trainer.experiment_name=trajectory-smoke \
  trainer.n_gpus_per_node=1 \
  trainer.nnodes=1 \
  trainer.total_epochs=1 \
  trainer.total_training_steps=1 \
  trainer.val_before_train=false \
  trainer.test_freq=-1 \
  trainer.save_freq=-1 \
  trainer.resume_mode=disable \
  trainer.default_local_dir="${RESULTS_DIR}" \
  trainer.device=cuda \
  trainer.use_v1=false \
  +ray_kwargs.ray_init.include_dashboard=false \
  2>&1 | grep --line-buffered -E 'configuration checks|dataset len|Total training|Loading weights|parameters|memory|vLLM|rollout|Traceback|Error|Exception|ValueError|AssertionError|ImportError|RuntimeError|step|reward|loss|timing'
