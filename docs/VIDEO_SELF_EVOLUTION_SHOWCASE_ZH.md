# EgoAgent 自进化与实时 Agent 架构录屏手册

更新时间：2026-08-30

这组演示不是播放预制动画。右上角 `LIVE ARCHITECTURE` 直接消费真实运行事件：根 Run、子 Run 的 `run_id / parent_run_id`，SubFlow 生命周期，模型和工具调用，人工审批，Harness mutation transaction 与 revision。刷新 Task Bench 的历史运行后，拓扑仍可由保存的事件重建。

## 当前真正可展示的自进化能力

| 能力层 | Agent 可以做什么 | 写入边界 | 录屏证据 |
|---|---|---|---|
| Knowledge | 保存可验证、长期复用的事实 | Identity transaction + 审批 | `identity_evolution`、新增 Knowledge、usage |
| Skill / Tool | 把重复确定性操作封成可搜索能力 | 查重、dry-run、审批、测试 | `search_capabilities`、Skill 文件、验收运行 |
| Identity | 修改角色的 Skill、Knowledge、Tool 或受控字段 | revision + rollback | Identity 变化事件和能力快照 |
| 可复用 Agent | 创建 Identity + 可视 Harness，而非手写 Python Agent | Agent Spec 审批 | 子 `component_agent_designer` Run、`agent_system_created` |
| Flow Graph | 添加/删除/更新节点，重连边，插入审批/检查点 | `manage_harness` inspect → expected revision → patch | before/after、transaction id、绿色新节点 |
| SubFlow | 搜索已有 Harness，把长过程隔离成 result-only 子 Run | `share_session=false`、typed ports | 父子 Run 树、Identity slot、只返回紧凑结果 |
| 候选进化 | 在隔离副本上提出 typed variant | validator，不自动晋升 | proposal、validation/held-out、promotion/rollback |
| 上下文进化 | Curator、Compactor、Tool result pruner 作为普通组件复用 | working history 变换，audit history 不丢 | 压缩前后 model request 与真实 trajectory |

需要诚实说明：`flow_evolution_showcase` 是一个可靠展示“Agent 如何操作结构”的受控 Harness；题目给了真实故障证据和目标约束，但具体节点 ID、patch operations、revision 都由模型在运行时产生。`video_self_evolution_walkthrough` 则是不强制产物类型的开放实验，模型可以选择不进化，不能为了视频硬说它必然会创建 Skill。

## 新实时可视化如何读

在 `Workbench → Build` 查看右上角实时结构，或在 `Workbench → Evaluate` 运行带 evolution 的题目。该面板默认打开，所以正常情况下按钮显示 `隐藏实时结构`；被手动隐藏后，点 `显示实时结构` 恢复。面板分三层：

1. `LIVE ARCHITECTURE`：根 Flow 在最上方；每个隔离 SubFlow 按 `parent_run_id` 缩进。卡片显示 Harness、slot→Identity、当前节点、node/model/tool 次数和最后活动。
2. `事件故事线`：用人话按顺序显示“创建子 Agent”“等待审批”“审批通过”“Flow 结构已改变”“子 Agent 完成”。
3. `Flow 版本变化`：显示目标 Harness、revision/transaction，以及 `＋新增节点 / −删除节点 / ~更新节点 / 连线 +/−`。结构变更保存后必须产生新的不可变 Flow Version；当前运行继续使用启动时锁定的旧版本，Chat 会提示是否从下一条消息起切到最新版。如果结构变化发生时当前画布正显示目标 Flow，画布会原位刷新：新节点绿色进入，修改节点黄色标记。任务结束后才重新打开目标 Flow 时，动画不会伪造重播，应查看保存的 diff 卡、版本 ID 和最终结构。

模型思考和长 Tool 结果仍在节点详情/过程页，不会全铺到画布上。双击节点才展开完整配置；单击运行中的节点看真实输入、模型响应和工具结果。

录屏时必须把“revision”和“Flow Version”都讲出来：revision/transaction 证明一次 mutation 是带并发检查的可逆事务；不可变 Flow Version 证明后续 Session、Task、比较和训练轨迹能精确复现当时运行的结构。它们不是两个重复编号。

## 每次录制前重置

在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe scripts\reset_video_demo.py --reset-evolution-artifact --reset-created-artifacts
.\.venv\Scripts\python.exe scripts\verify_recording_setup.py --live
```

reset 只恢复已知教学文件、两个专用缺陷 Flow、已知录屏产物 `video_incident_triage_agent` 和温室演化 Skill，不会清理其他 Harness/Identity。看到 `RECORDING_SETUP_OK` 再录。

打开主仓库：

```text
http://127.0.0.1:8880/?folder=/C:/Users/aa310/Desktop/egoagent
```

### 推荐成片顺序

先录最容易理解的“创建一个新 Agent”，再录“修改已有 Flow”，然后录“组合已有 SubFlow”。前三条组成完整叙事：

```text
从零创建可复用 Agent
→ 根据真实失败修改控制流
→ 不重复造轮子，搜索并组合隔离 SubFlow
→ 开放式选择是否值得进化
→ 用 held-out 与 rollback 决定候选能否晋升
```

每条开头先拍 3 秒题目卡和当前目标 Flow，结尾固定拍 `评分`、`进化`、最终 Build 三处证据。这样剪辑时即使模型中间输出较长，观众也能看懂“为什么变、改了什么、是否真的生效”。

## Demo 1：Agent 创建一个可复用 Agent

目标：同时展示 Agent Spec、人工审批、隔离 SubFlow、能力查重、Identity + Flow 创建。

1. 右侧 Chat 点 `Workbench`。
2. 中间顶部点 `Evaluate`。
3. 左侧题目选择 `录屏：Agent 自己创建可复用 Agent`。
4. 确认配置自动为 `agent_factory + dante`，Environment 显示“隔离工作区 · 网络工具禁用”。
5. 可勾 `首节点前暂停`，点 `▶ 开始做题`；先点一次 `单步`，再点 `自动`。
6. 看右上角根卡 `agent_factory` 下出现子卡 `component_agent_designer`。这不是 UI 猜测，而是独立 child run。
7. 到 `approve` 后，底部输入框输入 `approved` 并发送。不要在模型设计前预先批准。
8. 故事线依次应出现审批、创建可复用 Agent；`进化` 页出现 `agent_system_created`；`评分` 页检查 Harness、Identity、事件和 capability search。
9. 任务结束后进入 `Build`，Harness 下拉选 `video_incident_triage_agent`，确认它是可编辑、可运行的 Flow；再到 `More → Identity` 搜索同名 Identity。
10. 在 Chat 切到刚创建的 Harness + Identity，输入：

```text
请读取 tutorial_assets/evolution_demo_logs/app-log.txt 和 worker-log.txt，按 blocker、warning、noise 分类，引用文件与行号。不要联网，不要修改日志。
```

画面必须证明产物能独立运行，不能只展示“创建成功”文字。

## Demo 2：根据失败轨迹给 Flow 添加安全边界

目标：展示控制流缺陷不是 prompt 问题，以及真实 before→after 结构 mutation。

1. `Evaluate` 选择 `录屏：运行证据驱动 Flow 结构进化`。
2. 确认 `flow_evolution_showcase + dante`，点开始。
3. `inspect` 会读取 `demo_fragile_release_flow` 的紧凑 Blueprint 和 revision；`propose` 输出结构 patch，不能直接写文件。
4. 到审批时展开数据，口述三个重点：目标 Harness、`expected_revision`、operations。底部输入 `approved`。
5. 等 `apply → verify → report`。右上角应出现 `Flow 结构已改变`，变化卡显示新增审批节点/重连边与 transaction/revision。
6. 进入 `Build`，下拉选 `demo_fragile_release_flow`。确认 `plan` 与 `execute` 之间已经出现人工审批节点。绿色/黄色动画只在实时 mutation 当下出现；此处晚打开画布时用最终节点、连线和上一步保存的 revision diff 作证。
7. 点上锁按钮进入试跑，从 Build 启动，输入一个虚拟发布计划。到审批节点拒绝，证明 `execute` 不会运行。

评价成功只证明结构变更、审批和事务证据都发生；它不等于已经量化“发布事故下降”。最终报告必须明确还需要 paired validation。

## Demo 3：把重复搜索抽成隔离、可复用 SubFlow

目标：展示 Agent 不复制内部节点，而是搜索并组合现有 Flow；运行时再展示父子拓扑。

1. 先 reset，避免上次结构残留。
2. `Evaluate` 选择 `录屏：把重复搜索进化成隔离 SubFlow`，配置仍为 `flow_evolution_showcase + dante`。
3. 题目证据是 10 次重复能力搜索、平均 7,800 字符工具轨迹、主 Agent 只使用 3 个候选。
4. 到审批时确认 proposal 复用 `component_capability_discovery`，配置 `share_session=false`，而不是把其 7 个内部节点复制进父图；输入 `approved`。
5. 结束后进 `Build` 加载 `demo_noisy_research_flow`，看到新增的 `子流程` 节点和重新连接的主线。
6. 上锁后试跑，输入：

```text
找一个能压缩长对话上下文的现有可复用能力，只返回最合适的三个候选及理由。
```

7. 实时架构中根 Flow 下应出现 `component_capability_discovery` 子 Run；子卡内发生搜索/激活，父卡只收到紧凑输出。点子卡对应节点查看完整子过程，再点父节点证明父输入没有整段搜索噪声。

这是 EgoAgent 与“把所有 Skill 文本一次塞进 system prompt”的关键区别：检索能力本身是可插拔 Tool/SubFlow，完整过程在轨迹里可审计，但主上下文只接收接口输出。

## Demo 4：不指定产物类型的开放自进化

1. reset 后在 `Evaluate` 选 `录屏：重复工作触发受控自进化`。
2. 配置 `component_capability_evolver + coder`。
3. 题目只给 12 个温室分区、80% 重复轨迹和后续需求，不说“必须创建 Skill”。
4. 展示 `judge` 比较 no-change、Knowledge、Skill、Identity/Sub-Agent、Harness，再查能力库。
5. 如果模型选择写入，输入 `approved`；结束后运行：

```powershell
.\.venv\Scripts\python.exe scripts\verify_video_evolution_artifact.py
```

如果模型选择不进化或验证失败，保留真实结果并解释证据不足；不要补剪一个伪造的 mutation。

## Demo 5：候选 Flow 进化与科学门控

打开 Build 的 `component_flow_evolver`：它只产生隔离 candidate，不直接晋升。再展示 `arc_scientific_search` / ARC 实验中的 measured failure、typed mutation、paired validation、held-out、promotion/rollback。

这一段的卖点不是“EgoAgent 已复现 NVIDIA 100%”，而是结构本身可以作为实验变量，并且 Agent 的修改仍受证据、类型、评测和回滚控制。当前结果必须按仓库实际实验报告陈述。

## 录屏验收清单

- 子 Agent 必须在父卡下缩进，不是平铺成聊天角色。
- 子卡必须显示自己的 Harness、Identity slot、当前节点与 model/tool 次数。
- 每个 mutation 必须有目标、operation、revision 或 transaction；只有一段“我优化了”不算。
- 审批前文件不变，审批后才出现绿色新增节点。
- Task Bench `评分` 使用真实事件/文件 diff，不使用 Agent 自述。
- `进化` 页保留原始 payload；故事线只是人类可读投影。
- 刷新一个已结束的 Task run 后，父子拓扑和 mutation 仍能重建。
- 失败、拒绝、revision conflict 必须明确显示，不能卡在永久 spinner。

## 现场失败分支怎么讲

| 现象 | 说明与处理 |
|---|---|
| 没出现子 Run | 先确认任务使用的是 `agent_factory` 或包含真实 SubFlow 的 Flow；普通单 Agent Flow 不会为了画面伪造子卡 |
| 审批后 revision conflict | 说明目标 Flow 在 inspect 后被其他操作修改；重新 reset 并重跑，不能绕过 expected revision |
| 模型选择不进化 | 在开放式 Demo 中是合法结果；展示 judge 证据。确定性结构 Demo 才要求完成指定安全约束 |
| 任务已结束但没有绿色动画 | 动画只标记实时变化，不是历史回放；展示 `Flow 版本变化`、评分事件和最终结构 |
| SubFlow 出现但主上下文仍很长 | 展开配置确认 `share_session=false`，并比较子 Run 完整轨迹与父 Run 收到的紧凑输出 |
| Task 评分失败 | 切到 `评分` 查看缺少的是事件、产物还是结构检查；保留失败 take，reset 后再录，不要手动补造文件 |
