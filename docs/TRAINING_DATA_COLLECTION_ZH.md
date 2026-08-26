# EgoAgent 人工反馈与训练数据收集

## 设计目标

EgoAgent 把“发生了什么”和“用户如何评价”分开保存：

- `sessions/<session>/trajectory.jsonl` 是不可变的真实运行轨迹，记录每个 Agent、Identity、Harness、DAG 节点、模型输入输出、工具调用与上下文替换。
- `.egoagent/training/annotations.json` 是可修改的人工标注侧车。点赞、点踩、重要、加入数据集、标签和备注都写在这里，不会破坏轨迹回放的完整性哈希。
- `.egoagent/exports/training/<时间>/` 是一次可复现的数据集快照；`manifest.json` 记录源 Session、源哈希、标注文件哈希、筛选规则、样本数和文件位置。

这样可以反复修改标签、用不同规则重新导出，也能证明训练样本来自哪次真实运行。

## 可以标注什么

| 粒度 | 在哪里标注 | 最适合表达的信号 |
| --- | --- | --- |
| 整个 Session | Sessions 页顶部或“训练数据”页 | 整个任务是否成功、轨迹是否重要、是否整段入库 |
| 单条聊天消息 | “审计聊天”中每条消息右上角 | 最终回答/某轮回复是否好，适合对话 SFT |
| 单次模型调用 | “精确回放”中选择 `model.request` 或 `model.response` | 某个 Agent 在当时真实上下文下的输出是否好，适合 Agent SFT、KTO、DPO |

每个目标都有四个快速动作：

- `👍`：正向样本。可进入 SFT，也会成为 KTO 的 `label=true`。
- `👎`：负向样本。**不会**进入正向 SFT；会成为 KTO 的 `label=false`，或和同 prompt 的点赞结果组成 DPO 对。
- `★`：重要样本。适合保留关键成功、罕见失败、涌现行为和论文案例。
- `+ 数据集`：不评价好坏，只明确要求“仅标注内容”导出时包含它。

点“标注…”还能添加标签和备注，例如 `bugfix`、`tool-use`、`good-delegation`、`unsafe-command`、`context-loss`，并记录为什么好或坏。

## 使用方法

1. 在 IDE 中打开 Agent Workbench，进入 `Sessions`。
2. 选择一个 Session：
   - 在顶部评价整个 Session；
   - 在“审计聊天”评价一条消息；
   - 在“精确回放”选择模型事件，评价具体模型调用。
3. 打开“训练数据”标签页。
4. 选择范围：
   - `当前 Session`；或
   - `所有 Session`，用于把不同日期积累的标注一次导出。
5. 选择筛选规则：
   - `仅标注内容（推荐）`：只取点赞、点踩、重要或显式入库的内容；
   - `整个 Session`：显式导出所选 Session 的全部可用内容。
6. 选择训练投影、保存目录，然后点“生成训练数据”。留空目录时保存到 `.egoagent/exports/training/<时间>/`。

页面会显示每种格式的实际样本数。DPO 数量为 0 通常不是错误，而是尚未出现“相同 prompt 下一个点赞、一个点踩”的严格偏好对。

## 导出文件与训练用途

| 文件 | 内容与规则 | 适用训练 |
| --- | --- | --- |
| `conversations_openai.jsonl` | 被选中的完整对话；每行只有标准 `messages` | OpenAI chat SFT、TRL SFT、LLaMAFactory OpenAI 格式 |
| `message_sft_openai.jsonl` | 到某条被选中 assistant 消息为止的对话 | 只学习优质最终回复，减少无关长轨迹 |
| `model_calls.jsonl` | 每次模型调用的真实 messages/tools/response，加 Agent/Identity/Harness/节点元数据 | Harness-aware SFT、自定义训练管线、角色专用 LoRA |
| `llamafactory_sharegpt.jsonl` + `dataset_info.json` | 精确模型调用投影为 ShareGPT | LLaMAFactory SFT，包含 tool/function/observation 角色 |
| `kto_trl.jsonl` | `prompt`、`completion`、布尔 `label`、tools | Hugging Face TRL KTO；天然适合单独点赞/点踩 |
| `preferences_trl.jsonl` | 同一语义 prompt 的 `chosen` / `rejected` / tools | TRL DPO、ORPO、RewardTrainer；不伪造不成对数据 |
| `unary_feedback.jsonl` | 原始目标与全部标注、标签、备注 | 数据清洗、错误分类、奖励模型/KTO 转换、主动学习 |
| `trajectories.jsonl` | Session 的完整有序事件，保留所有 Agent 与上下文替换 | 长轨迹模仿、过程监督、Harness/工具策略研究、回放分析 |
| `verl_rollouts.jsonl` | 精确 prompt/response；点赞为 `+1`、点踩为 `-1`、无评价为 `null` | 转换为 Parquet 后接 verl、自定义离线 RL/奖励分析 |

当前 TRL 官方文档把 KTO 定义为 `prompt/completion/label` 的单边偏好数据；DPO 则要求 `prompt/chosen/rejected` 的成对偏好。因此 EgoAgent 不会把两个不同 prompt 的赞踩强行配对：[TRL 数据格式](https://huggingface.co/docs/trl/en/dataset_formats)、[KTOTrainer](https://huggingface.co/docs/trl/main/kto_trainer)、[DPOTrainer](https://huggingface.co/docs/trl/dpo_trainer)。

LLaMAFactory 官方支持 ShareGPT、OpenAI messages、偏好与 KTO 数据；本项目生成配套的 `dataset_info.json`：[LLaMAFactory Data Preparation](https://llamafactory.readthedocs.io/en/latest/getting_started/data_preparation.html)。

verl 的标准数据通常需要 Parquet，并包含 `data_source`、`prompt`、`ability`、`reward_model`、`extra_info`。EgoAgent 先保存无损 JSONL，便于在实际训练环境中校验后再转 Parquet：[verl Prepare Data](https://verl.readthedocs.io/en/v0.4.x/preparation/prepare_data.html)、[verl Reward Function](https://verl.readthedocs.io/en/latest/preparation/reward_function.html)。

## 推荐的数据闭环

### 个人 Code Agent SFT

优先点赞真正完成任务且测试通过的具体模型调用，标签使用 `code-change`、`tests-pass`、语言与项目类型。导出 `model_call_sft`，不要只按回答看起来流畅就点赞。

### 对齐个人偏好

对好/坏回答分别点赞和点踩。没有相同 prompt 的替代回答时使用 KTO；可通过 fork Session 后让不同 Harness/模型重做同一请求，再对两次对应模型调用赞踩，自动得到 DPO 对。

### Harness 与多 Agent 研究

标记整个成功或失败 Session，并导出完整 trajectory。轨迹内的 `agent`、`identity`、`harness`、`node_id`、`model_call_id` 不会被合并成一个虚构说话者。训练前根据任务 checker 或人工标注设计 credit assignment，不能把终局分数盲目赋给每一步。

### 失败挖掘与评测集

对失败 Session 点踩并添加原因标签，例如 `wrong-tool`、`context-loss`、`unsafe`、`timeout`。这些数据适合错误分类、奖励建模和回归评测，不应直接混入正向 SFT。重要失败可加 `★` 进入人工复盘队列。

## 数据质量与隐私

- 轨迹写盘时已经过滤常见 API key、Bearer token、password 等；导出时再次过滤，但仍应在训练前人工抽查。
- `reasoning` 默认不导出。只有确认模型许可、隐私和训练权利时才开启。
- 不要把点踩当作“事实错误”的唯一含义；使用标签/备注区分错误、风格不符、安全问题和任务失败。
- 按任务或 prompt 哈希划分 train/validation/test，避免同一次 fork 的近重复样本泄漏到不同 split。
- 保留 `manifest.json`，训练记录应引用其源哈希，而不是只保存后来被手工复制过的 JSONL。
- 点赞 Session 会把其未被单独点踩的调用视为可用正样本；对混合质量的长 Session，优先标注具体消息或模型调用。

## API

- `GET /api/training/annotations?session=<name>`：列出标注与总体统计。
- `POST /api/training/annotations`：创建或更新一个稳定目标的标注；内容已变化时返回 `409`，防止标错。
- `POST /api/training/export`：按 Session、筛选规则和格式生成数据集与 manifest。

实现与格式转换位于 `training_data.py`；HTTP 接口位于 `harness_editor/server.py`；前端控件位于 `harness_editor/src/components/TrainingDataControls.tsx`。
