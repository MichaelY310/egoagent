# 真实轨迹与训练兼容性验证报告

日期：2026-08-18

## 结论

EgoAgent 的 append-only 轨迹已经能够无歧义地表达并回放：

- 父 Agent `planner` 的两次真实模型调用；
- 子 Agent `researcher` 的一次独立模型调用；
- compactor 用摘要替换 working history；
- 替换后 `planner` 的下一次 request 只看见摘要后的历史；
- 三次调用共享 trace，但拥有独立 session/run/agent/model-call ID；
- 只有带确定性 `evaluation.completed` 的最终 run terminal call 获得 RL reward。

## 确定性数据生成

运行：

```powershell
python scripts/trajectory_training_smoke.py
```

当前验证数据位于
`.egoagent/research/trajectory_training_smoke_v5/export`。该脚本不访问模型 API，
因此不会消耗 API 费用，也不会把随机模型行为误当成轨迹正确性的证据。

生成的主要文件：

- `model_calls.jsonl`：每行一个精确模型调用；
- `llamafactory_sharegpt.jsonl` 与 `dataset_info.json`；
- `verl_rollouts.jsonl` 与可选 `verl_rollouts.parquet`；
- `egoagent_episodes.jsonl`：完整多 Agent episode 与 credit lineage；
- `manifest.json`：源文件 hash、过滤统计和投影说明。

## LLaMA-Factory SFT

环境：LLaMA-Factory `f28afaf6355af515454dfb16c97d728307c93897`，
tiny random Llama（1,062,992 parameters），RTX 4050 Laptop 6 GB。

最终结果：

- ShareGPT 3/3 samples 成功转换与 tokenize；
- `Num examples = 3`；
- `Total optimization steps = 1`；
- `train_loss = 10.3772`；
- checkpoint 写入 `/home/aa310/egoagent-training/results/llamafactory-sft-smoke`；
- exit code 0。

这三个 sample 是三个独立 model call，不是把 `planner` 和 `researcher` 拼成一个
虚假说话人。LLaMA-Factory 的官方 dataset 格式说明：
https://github.com/hiyouga/LlamaFactory/blob/main/data/README.md

## verl GRPO

环境：verl `d4701e4eb50feeabc2781499c02f64793ed55461`，同一 tiny model。

官方 `RLHFDataset` 验证：

- dataset/filter length 均为 1；
- prompt roles 为 `system, user`；
- system 中保留 `[context_summary]`；
- `agent=planner`、`run_id=run_final` 和唯一 `model_call_id` 均保留；
- exact ground truth 保留；
- 未标注的 parent/child 中间调用没有混入 RL reward 数据。

实际 1-step GRPO：

- 2 rollouts；
- response length 32，prompt length 64；
- reward mean 0.2025785；
- advantage 在两个 rollout 间正确归一化；
- PPO backward 与 optimizer step 完成，`grad_norm=0.5432`；
- `training/global_step=1`；
- 单步约 37.8 秒，exit code 0。

verl 官方数据准备与 quickstart：

- https://verl.readthedocs.io/en/latest/preparation/prepare_data.html
- https://verl.readthedocs.io/en/latest/start/quickstart.html

## WSL 兼容性说明

当前 verl 主分支保留 `HFRollout` 文件和 `hf` 配置说明，但 rollout registry 只注册
async vLLM/SGLang/TRTLLM；直接使用 HF 会失败。vLLM 在 WSL 上又会把 CUDA IPC
误判为可用。实验脚本通过一个仅在显式环境变量开启时加载的 `sitecustomize`
shim，让 verl 使用其已有的 POSIX shared-memory fallback，并把 bucket 限制为 16 MB。
它不修改 verl 仓库，也不影响 EgoAgent 正常运行。

训练完成的退出清理阶段打印过一次 DataLoader worker 被系统回收的警告，但最终
exit code 为 0，且日志已经包含 rollout、reward、advantage、backward、weight update
和 global step。正式大规模训练仍建议使用原生 Linux 和官方建议的 >=24 GB HBM。

## 不能从本实验得出的结论

- 不能证明 tiny random 模型质量提高；
- 不能证明当前 imitation reward 适合作为论文中的最终 reward；
- 不能把 terminal reward 自动归因给所有子 Agent；
- 不能把被回滚或无 checker 的进化轨迹自动标为正样本。

本实验验证的是：真实 session surface、multi-Agent lineage、SFT 投影与 RL 输入没有
混乱，且两条训练框架链路都能实际执行到一次参数更新。
