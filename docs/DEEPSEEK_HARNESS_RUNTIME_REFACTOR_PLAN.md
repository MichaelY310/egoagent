# EgoAgent Runtime、真实轨迹与自进化重构计划

状态：核心设计已实施并完成 SFT/RL 冒烟验证；Session fork/merge 已追加完成；可选远程 Provider 与长期存储后端未启用  
日期：2026-08-18  
范围：Agent Runtime、Session、SubDAG、多 Agent、模型调用、工具调用、上下文治理、轨迹回放、训练数据导出、采集镜像、自进化证据链

## 1. 目标

这次重构的首要目标不是制作一个更漂亮的聊天记录，而是建立一份能够回答以下问题的事实记录：

1. 在任意一次模型调用中，某个具体 Agent 实际看到了哪些 system/user/assistant/tool 消息和工具定义？
2. Context Curator 或 Compactor 修改历史后，后续模型实际看到的是否确实是修改后的 surface？
3. 多 Agent、SubDAG、子 Harness、并行节点和模型角色之间是否能够被无歧义地区分？
4. 一个 Tool Call 的请求、审批、执行结果和文件副作用是否可以关联到同一个 call ID？
5. Harness、Identity、Skill、Knowledge 或 DAG 发生进化时，提案、批准、临时版本、验证、晋升和回滚能否形成完整 lineage？
6. 轨迹能否直接投影成 LLaMA-Factory SFT 数据或 verl rollout 数据，而不是从 UI 文本猜测模型历史？
7. Runtime 崩溃后，能否判断一个副作用操作是未开始、已完成还是结果未知？

产品目标是提供三种视图，但只维护一份事实：

- 人类会话视图：完整、可读、保留被压缩或精简的原始内容。
- 模型 Surface：每次模型调用真正使用的完整输入快照。
- Runtime 轨迹：节点、模型、工具、审批、上下文变更、子 Agent、自进化和错误的有序事件。

## 2. 当前实现的批判性审计

### 2.1 已经做得好的部分

- `RunContext` 已有稳定 `run_id`、`parent_run_id`、节点 ID、取消传播和子 Run 树。
- Pipeline 已发出 `node_input`、`node_enter`、`model_request`、`model_response`、`tool`、`node_output`、`node_exit`、审批、压缩和进化事件。
- `Session` 已区分 working `messages` 和审计用 `full_messages`。
- Context Component 已将 snapshot、普通 Model、apply 拆成可复用 SubDAG。
- SubDAG Component Manifest 已有输入 JSON Schema、输出路径、Agent Slot 和 `share_session`。
- Checkpoint v3 已保存消息、运行数据、节点输出、权限、审批、事务、子 Run 和代码/Identity/Harness revision。
- Capability Registry 已支持 workspace-first 的 lexical/semantic/hybrid 搜索及复用契约。
- RuntimePolicy、Container Backend 和文件变更事务已形成安全与可撤销基础。
- Studio 已有节点轨迹、模型请求/响应、工具、token、重试和子 Harness UI 雏形。

### 2.2 阻碍真实回放与训练的核心问题

#### 事件不是默认事实来源

`pipeline.event_log` 需要 Harness 显式开启。未开启时，大多数运行事件只通过 WebSocket 和进程内状态存在。Studio 为性能只保留最近 500 个 node trace，不能作为训练或审计数据。

#### `model_request` 不是模型的真实请求

Pipeline 在调用 `Agent.step()` 前发出 `model_request`，但 `Agent.step()` 随后还会：

- 转换历史工具协议；
- 插入 Identity/SEGO/Skill/workspace system prompt；
- 执行 pre-LLM hook；
- 由 Provider 添加 model、thinking、temperature、max_tokens 等 envelope。

因此现有事件只能用于调试，不能证明模型实际看到了什么。

#### 调试事件会截断

现有 `_debug_value(..., limit=...)` 会截断 message、tool schema、参数和结果。UI 合理，但训练和严格回放不能以截断值为事实。

#### `llm_io.jsonl` 无法可靠关联

它保存较真实的 LLM 输入输出，但缺少：

- event/call ID；
- 时间和全局顺序；
- run、parent run、session、Harness、SubDAG、node；
- Agent Slot、Identity revision；
- request/response 配对；
- reasoning、finish reason、usage、错误、重试；
- context mutation lineage。

并发或多 Agent 时，单靠相邻两行无法保证正确配对。

#### 子 Harness 轨迹分散

独立子 Session 会写入自己的 session 目录；共享 Session 的 SubDAG 又混在父 Session 中。当前没有一个 root trace 将整个多 Agent 树的事件按全局 sequence 合并。

#### Context 替换缺少可重建事件

Curator/Compactor 会直接替换 `session.messages`，治理 ledger 放在 `session.state`。虽然 `full_messages` 仍在，但无法仅根据有序事件重建每个时间点的 working surface。

#### Tool 执行没有单一权威管线

审批、权限、工具执行、变更追踪、结果截断和 Session 写入分布于 Tool Review、Pipeline Tool Node 和 `Agent.execute_tool_call()`。这增加了重复记录、参数漂移和遗漏 call ID 的风险。

#### Session 兼容缓存与事实混合

`messages.json`、`full_messages.json`、`state.json` 是完整快照，适合快速加载，但覆盖写不能表达变化历史。它们应成为事件投影缓存，而不是唯一证据。

## 3. 从 DeepSeek Harness 吸收什么

### 3.1 必须吸收

1. 追加式事件流是唯一事实来源，UI、模型 Surface、回放、恢复和训练数据均为投影。
2. “模型可见内容必须可从日志解释”，并额外保存每次模型请求的精确快照。
3. Turn/Step/Run/Node/Tool/Model 有显式生命周期和终态。
4. Raw audit log 与 model surface 分离；压缩采用显式 replace 事件，不删除事实。
5. Tool 管线统一，参数冻结，审批与执行看到同一参数。
6. Capability Contract 与 Provider/Consumer 分离，运行实现通过稳定接口替换。
7. 子 Agent 有明确 parent/child lineage，内部轨迹不隐式塞入父模型上下文。
8. 工具输出 Schema 与 UI render intent 属于工具契约，而不是前端按工具名硬编码。
9. 沙箱报告实际 enforcement 范围，不能把路径检查宣传成 OS 沙箱。
10. 崩溃时区分 not-started 与 outcome-unknown，避免盲目重放副作用。

### 3.2 选择性吸收

- Code Mode：作为受限、临时、强类型 Tool orchestration Component，而不是扩大普通 Python 节点权限。
- Host Plane / Agent Plane：采用权限与能力的单向收紧原则，但保持 EgoAgent 的 Environment/Identity/Harness 语言。
- Queue/Steer：纳入运行中消息控制，但不作为轨迹重构的阻塞依赖。
- MCP/远程 Provider：通过接口预留，不在第一阶段增加所有传输。

### 3.3 不照搬

- 不采用“所有东西都是独立 npm package”的极端颗粒度。
- 不用 Cordis Plugin Tree 替代 DAG；DAG 对弱模型、人类可视化和结构进化更合适。
- 不把动态 JavaScript 当作 Agent 创建结构的主要语言。
- 不把完整 Skill Catalog 注入上下文；保留 EgoAgent 的检索优先能力市场。
- 不将进程内动态修改当作持久进化；EgoAgent 继续要求验证、晋升、证书和回滚。

## 4. 目标架构

```text
                    +-----------------------+
                    | Harness / Identity DAG|
                    +-----------+-----------+
                                |
                    +-----------v-----------+
                    |    Runtime Services   |
                    | Model / Tool / Process|
                    | Session / Subagent    |
                    +-----------+-----------+
                                |
                    +-----------v-----------+
                    |  Trajectory Recorder  |
                    | append-only root trace|
                    +-----------+-----------+
                                |
       +------------------------+-------------------------+
       |                        |                         |
+------v------+       +---------v---------+      +--------v---------+
| UI Replay   |       | Session Projection|      | Training Export  |
| timeline    |       | working/audit     |      | canonical/SFT/RL |
+-------------+       +-------------------+      +------------------+
```

### 4.1 事件 Envelope

每一行 JSONL 是一个不可变事件：

```json
{
  "schema": "ego.trajectory.event.v1",
  "event_id": "evt_...",
  "sequence": 42,
  "timestamp": 1786900000.125,
  "trace_id": "trace_...",
  "session_id": "session_...",
  "run_id": "run_...",
  "parent_run_id": "run_parent",
  "harness": "adaptive_code_agent",
  "node_id": "infer",
  "node_op": "Agent",
  "agent": "agent",
  "identity": "coder",
  "model_call_id": "call_...",
  "tool_call_id": null,
  "type": "model.request",
  "data": {},
  "integrity": {"payload_sha256": "..."}
}
```

Sequence 由 root recorder 在锁内分配，因此多个子 Run/并行 Agent 共享一个严格全局顺序。时间只用于展示，不能代替 sequence。

### 4.2 核心事件族

- `trace.started` / `trace.completed`
- `run.started` / `run.completed` / `run.failed` / `run.cancelled`
- `runtime.event`：兼容保存现有 Pipeline 事件及原 event name
- `conversation.working.append`
- `conversation.audit.append`
- `conversation.surface.replace`
- `model.request`
- `model.response`
- `model.error`
- `tool.request`
- `tool.approval`
- `tool.result`
- `checkpoint.saved`
- `subagent.spawned` / `subagent.completed`
- `evolution.proposed` / `evolution.activated` / `evolution.evaluated` / `evolution.promoted` / `evolution.rolled_back`
- `artifact.created`

### 4.3 精确模型视图

每一个 `model.request` 必须保存传给 LLM Adapter 的完整值：

- 已完成协议转换的 messages；
- 已插入的 system prompt；
- 压缩/精简后的 working history；
- 当前可见工具完整 Schema；
- max_tokens、temperature、response format、thinking 等参数；
- Agent Slot、Identity、模型与 Provider；
- request hash 和 context generation。

`model.response` 保存：

- 可见文本；
- reasoning（可配置训练时是否使用，UI 默认折叠）；
- tool calls 及 Provider call ID；
- finish reason；
- usage/cache/cost/latency/retries；
- output truncation 和错误分类。

这样 Context Compactor 之后的下一条 `model.request.messages` 自身就是该 Agent 的真实历史，不需要从最终 `messages.json` 反推。

### 4.4 Session 投影

为兼容旧代码，`Session.messages`、`full_messages` 和 `state` 暂时保留为内存投影，并继续保存 JSON 快照。

新 Session 同时写入事件：

- `record()` -> working append；
- `record_full()` -> audit append；
- `apply_context_result()` -> surface replace，包含 after surface、ledger 和前后 hash；
- `load()` 优先从事件恢复，无法恢复时读取旧快照。

快照损坏时，事件仍可重建；事件损坏时 fail loudly，不静默拼接错误训练数据。

### 4.5 多 Agent 与 SubDAG

- Root Harness 创建 root `TrajectoryRecorder`。
- 子 Harness 拥有独立 Session surface，但 attach 到同一个 root recorder。
- `share_session=true` 的组件共享 Session 与 recorder。
- 每个 Run、Session、Harness、Agent 和 Identity 均为独立维度。
- `agent_map` 与 `identity_map` 的绑定结果写入 `run.started`。
- 同一个 Identity 在多个子 Run 中仍以不同 run/agent instance 区分。

### 4.6 自进化证据链

轨迹记录不只保存“调用了 modify_harness”，还要投影为结构化 evolution lineage：

```text
trigger evidence
 -> proposal
 -> immutable candidate revision
 -> approval
 -> temporary activation
 -> evaluation task runs
 -> verifier result
 -> promotion or rollback
 -> Evolution Certificate
```

训练导出默认排除未经验证的进化建议和被回滚的恶化轨迹；研究导出可以显式包含，并带 outcome 标签。

## 5. 训练数据设计

### 5.1 Canonical Model Call Dataset

`model_calls.jsonl` 一行对应一次真实模型调用：

```json
{
  "schema": "ego.model-call.v1",
  "messages": [],
  "tools": [],
  "response": {"content": "", "reasoning": "", "tool_calls": []},
  "metadata": {
    "trace_id": "...",
    "run_id": "...",
    "parent_run_id": "...",
    "harness": "...",
    "node": "...",
    "agent": "...",
    "identity": "...",
    "model": "..."
  }
}
```

这是最可信的中间格式。其他框架格式全部从它转换。

### 5.2 LLaMA-Factory SFT

生成：

- `llamafactory_sharegpt.jsonl`
- `dataset_info.json`

每次模型调用是独立样本，输入严格使用该次 `model.request`，目标使用对应 `model.response`。多 Agent 不会拼成一个虚假的单 Agent 会话，Agent/Identity 信息保留在额外 metadata 中。

默认过滤：

- 没有配对 response 的调用；
- 明确取消/传输失败的调用；
- 被 secret redaction 标记为不安全的样本；
- 纯空回复；
- 可选排除 reasoning；
- 可选只导出成功 Task/Evolution Certificate 对应轨迹。

### 5.3 verl Rollout

生成 `verl_rollouts.jsonl`，环境允许时额外生成 Parquet：

- `prompt`：精确模型 request messages；
- `response`：该 Agent 的 response；
- `reward`：来自 TaskBench checker、独立 verifier 或 Evolution Certificate；没有可信 reward 时保持 null，不伪造；
- `data_source`、`ability`、`agent`、`identity`、`run lineage`；
- `extra_info` 包含 tool/effect/evolution 标签。

轨迹采集本身不能创造 RL reward。短程 smoke test 可以使用带确定性 checker 的 EgoAgent 测试任务，但必须标明该 reward 来源。

## 6. 用户采集镜像

原生轨迹始终写入 Session 自己的 `trajectory.jsonl`。

设置中的“训练数据采集”开关只控制第二份镜像：

- 用户选择目标目录；
- 每个 root trace 写入独立 JSONL；
- 使用锁和 append，不覆盖已有数据；
- 写入失败不应破坏 Agent 主任务，但必须在 UI 显示失败；
- Secret 始终在写盘前脱敏；
- 不允许目标为磁盘根目录；
- 可选择按日期/项目分区；
- UI 显示路径、事件数、最近错误和可用空间提示。

## 7. 能力接口与工程结构

优先定义轻量 Python Protocol，而不是复制 Cordis：

- `ModelProvider`
- `ToolExecutor`
- `ProcessProvider`
- `SessionStore`
- `SubagentRuntime`
- `TrajectorySink`

第一轮只抽取协议和现有 Adapter，不大规模移动业务文件。后续 Consumer 只依赖协议，具体实现由 Runtime Registry 选择。

`子流程` 节点和 `create_harness` Tool 应最终调用同一个 `SubagentRuntime.invoke()`；现阶段先让二者共享 lineage/recorder，再迁移执行逻辑，避免一次性破坏现有 Harness。

## 8. 实施阶段

### Phase A：事件与轨迹基础

- 新增 thread-safe `TrajectoryRecorder` 和 Reader。
- Session 默认创建/连接 recorder。
- RunContext 所有 emit 自动写入 root trace。
- 子 Run 共享 root recorder。
- Session append/replace 写入事实事件。
- 精确记录 Agent 与普通 Model Node 的 request/response。

### Phase B：回放与一致性

- Model call 配对、哈希和 schema 校验。
- Replay Projector 生成 timeline、agent lanes、model views、context mutations、evolution lineage。
- Session API 增加 trajectory summary/events/model calls/validation。
- Studio 增加播放、暂停、逐步、速度、Agent/事件过滤和精确模型上下文检查器。

### Phase C：采集与导出

- 增加训练采集设置及镜像 Sink。
- Canonical、LLaMA-Factory、verl 导出器。
- 导出清单包含 schema、过滤统计、哈希和 lineage。

### Phase D：Runtime 接口

- 新增 Protocol 与能力描述。
- Model Provider 适配现有实现。
- Tool 执行入口逐步统一。
- SubDAG/child Harness 调用统一。
- Process Backend 迁移到 Provider 接口。

### Phase E：自进化轨迹

- 统一现有 mutation/evolution 事件。
- 候选 revision、TaskBench run、verifier、promotion/rollback 关联。
- Evolution Certificate 可以引用 trace/model/tool/event IDs。

### Phase F：验证

- 单 Agent 精确 model view。
- Compactor 前后 model view 差异。
- 独立子 Session 与 shared-session SubDAG。
- 并行 Agent 全局 sequence。
- Tool call 配对与审批。
- 断点恢复和 outcome unknown。
- Secret redaction。
- 镜像目录错误与断盘容错。
- 大轨迹读取和 UI 虚拟化性能。
- LLaMA-Factory dataset loader + 小模型 1-2 step SFT。
- verl dataset/worker + 小模型短程 RL smoke；资源不允许时至少完成 loader、batch 和 loss/reward 前向验证并报告阻塞。

## 9. 验收标准

1. 任意 `model.response` 能通过 `model_call_id` 找到唯一 `model.request`。
2. 任意 request 均含 run/harness/node/agent/identity/model 标识。
3. 压缩后的下一次 request 与回放 UI 显示完全一致。
4. 多 Agent 轨迹不存在跨 Agent 配错 response 的情况。
5. JSONL 中 sequence 严格递增且 event ID 唯一。
6. 事件 payload hash 可验证。
7. 默认 Session 始终产生原生轨迹。
8. 镜像开关关闭不写外部目录，开启后与原生 trace 的 event IDs 一致。
9. LLaMA-Factory/verl 导出不从 UI 文本或最终聊天历史反推训练输入。
10. 旧 Harness 无需迁移即可继续运行。
11. 新增逻辑在无 API Key 的确定性测试中可覆盖；真实模型训练测试单独标记。

## 10. 风险与边界

- 完整模型输入和工具结果会增加磁盘使用，应后续支持压缩、保留策略和内容寻址 blob，但第一阶段优先真实性。
- Secret redaction 会让轨迹与 Provider 原始字节不完全相同，这是安全边界，必须在 manifest 标明。
- Provider 可能在网络层隐式规范化 JSON；我们保证记录交给 Adapter 的语义请求，并额外记录 Provider envelope，不承诺 HTTP 库最终字节序。
- 外部 Tool 的真实世界副作用无法通过回放自动撤销；Replay 默认只播放记录，不重新执行。
- 没有 verifier 的普通对话没有可信 RL reward，不能为了跑通 verl 而伪造为成功样本。
- Event Store 在过渡期与 JSON 快照双写，必须通过一致性测试避免漂移。

## 11. 官方实现核对与取舍依据

本设计只以 DeepSeek 官方仓库为工程参考，不使用非官方复刻。官方
`AGENTS.md` 明确要求：模型可见的内容必须能够从 session log 重建；事件
应为 typed、merge-extensible，注册应区分 Definition/Provider/Consumer。
官方 core 文档把 append-only `SessionEvent` log 定义为唯一事实，并由其
投影消息历史；session package 另外提供 JSONL/SQLite persistence 与 projection
seam。EgoAgent 吸收的是这些可验证原则，而不是复制 Cordis 或 npm 包结构。

- 官方仓库：https://github.com/deepseek-ai/deepseek-harness
- 工程规则：https://github.com/deepseek-ai/deepseek-harness/blob/master/AGENTS.md
- Core 事件模型：https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/core.md
- Session package：https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/session

EgoAgent 保留的独特设计包括 DAG/SubDAG 作为组合与结构进化语言、Identity/Ego
行为层、可搜索能力市场、Evolution Certificate、TaskBench 以及事务式代码改动。
因此这次重构不是 DeepSeek Harness 的 Python 翻译版。

## 12. 实施结果（2026-08-18）

已完成：

- 默认原生 `trajectory.jsonl`、严格全局 sequence、稳定 event/call/run/session lineage；
- 写盘前 secret redaction 与 payload/message/tool hash 校验；
- 精确模型 request/response/error、tool request/result、工作历史与审计历史事件；
- `conversation.surface.replace`，可以重建 compaction/curation 后的真实模型 surface；
- 父/子 Harness 共用 root recorder，但保留各自 session/agent/model 身份；
- 统一子 Agent lifecycle，创建工具和 SubDAG 使用同一种 lineage 语义；
- replay API 与 Studio 播放、暂停、逐事件、速度、Agent lane、精确 model view；
- 原生采集永远开启，设置中的开关仅控制用户目录第二份镜像；
- canonical、LLaMA-Factory ShareGPT、verl JSONL/Parquet、完整 episode 导出；
- TaskBench `evaluation.completed` 只把可信评分赋给对应 run 的 terminal call；
- 轻量 structural Protocol：Model、Tool、Process、Session、Subagent、Trajectory；
- 事件日志单独存在时仍可恢复原 session/trace/sequence，不依赖可损坏快照。

验证结果：

- 后端全量：454 tests passed，3 conditional skips（其中 7 个为 fork/merge 专项/API 测试；
  无头浏览器用例在受限沙箱外单独复测通过）；
- 轨迹专项：10 tests passed；
- 前端：TypeScript + Vite production build，219 modules；
- LLaMA-Factory：最终 v5 多 Agent 导出加载 3/3 model-call samples，并完成 1 step SFT；
- verl：官方 `RLHFDataset` 保留 agent/run/model_call metadata、压缩摘要和 ground truth；
  WSL 下通过共享内存兼容层完成 2 rollouts、reward、advantage、PPO backward、
  weight update，`training/global_step=1`。

完整实验记录与复现命令见
`experiments/trajectory_training/README.md`。这些 smoke test 证明数据语义和训练
管线成立，不代表 tiny random 模型的任务质量提升。

## 13. 明确未照搬或保持可选的部分

- Cordis 插件树：不引入；DAG 是 EgoAgent 的主要组合面。
- npm 多包拆分：不引入；当前 Python Protocol 已提供替换缝隙，避免过度工程化。
- SQLite Event Store：暂不设为默认；JSONL 便于审计、搬运和训练。Reader/Store
  接口允许未来在百万级事件或多进程写入需求出现时添加 SQLite/Parquet 后端。
- MCP/远程进程 Provider：只保留接口；没有为了“功能数量”增加未经使用的服务。
- DeepSeek 插件系统：不复制；EgoAgent 已用可搜索 Tool/Skill/Knowledge/DAG 与
  SubDAG 覆盖同一问题，并支持结构进化。
- 自动重放副作用：刻意不实现；回放只读取事实，不能再次执行 shell/tool。
- 未验证轨迹自动成为 RL 正样本：刻意禁止；没有 checker/certificate 的 reward
  保持 null，避免多 Agent credit assignment 被伪造。

## 14. Session 分支与合并扩展（2026-08-18）

在上述事件基础上追加了不可变来源的 Session fork，以及 `direct`、`summary`、
`dialogue` 和长度自适应 `auto` merge。每个结果拥有独立 session/trace，父项、共同
消息前缀、来源 hash、模式和合并模型 call IDs 记录在 `lineage.json`；Summary 与
Dialogue 的 A/B/synthesizer 使用不同 Agent 标识并进入同一精确轨迹。实现和教程见
`docs/SESSION_FORK_AND_MERGE.md`。
