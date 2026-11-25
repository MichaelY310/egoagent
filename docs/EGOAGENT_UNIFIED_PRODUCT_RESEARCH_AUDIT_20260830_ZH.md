# EgoAgent 一体化产品、科研与工程审计（2026-08-30）

## 0. 结论先行

EgoAgent 最有价值的定位不是“又一个 Code Agent”，而是一个 **可构造、可观察、可评测、可进化、可导出训练数据的 Agent Runtime IDE**。Code IDE 是用户日常工作的入口，Flow Graph 是 Agent 行为的可执行结构，Identity 是可复用的行为与能力身份，Evaluate 是证据入口，Trajectory 是重放与训练数据底座，Evolution 则只能在证据与版本边界内改变前述对象。

仓库已经拥有这条闭环的大部分基础设施，但此前存在三个根本问题：

1. 功能很多，产品主路径却没有形成同一个闭环；Build、Chat、Task Bench、训练导出和 Evolution 更像相邻工具。
2. 配置层权威不清楚；Identity/Superego、Flow prompt、RuntimePolicy、工作区安全设置都能表达“约束”，但谁能覆盖谁没有统一展示，而且部分 Superego 开关此前只有 UI、没有运行时强制执行。
3. 实验与自进化的宣传大于产品化程度；有任务、轨迹、候选变异和回放基础，但缺少通用数据适配、原始基线适配、矩阵实验、因果回放，以及面向普通用户的安全晋级流程。

本轮已经补上：自定义数据集适配与预览、精确 Flow 版本实验、原版 Codex CLI 基线、运行对比、Task 回放到 Build、Superego 真正运行时强制、统一治理检查器、OpenTelemetry GenAI 导出。它们不是所有缺口的终点，但已经把“Build → Run → Compare → Replay → Export”从概念连成了可执行路径。

---

## 1. 不超过十项的核心能力

下面九项足够描述 EgoAgent。再继续增加顶层 Feature，只会把实现组件误写成产品定位。

| # | 核心能力 | 精确定义 | 当前状态 |
|---|---|---|---|
| 1 | AI 原生 Code IDE | 文件、终端、代码上下文、Agent 对话、结构化改动审阅、权限审批在同一工作区 | 部分成熟；核心可用，代码改动审阅和浏览器 E2E 仍易回归 |
| 2 | Flow Runtime 与可视化 Build | 允许循环、条件、并发、等待输入、Subflow、模型和工具节点的可版本化执行图 | 已有坚实基础；不应继续叫 DAG |
| 3 | Identity Runtime | `ID` 描述人格/偏好，`EGO` 提供可用能力，`Superego` 给出不可突破的身份级行为与变更上限 | 已实现；本轮补齐 Superego 运行时强制与权限解释 |
| 4 | 能力市场与按需发现 | Tool、Skill、Knowledge、Identity、Flow 的注册、语义检索、复用、使用统计和缺失时创建 | 核心已存在；质量、信任和版本兼容性还不完整 |
| 5 | Agent 构建、观察、封装与交付 | Build 中编辑/调试，Link Session 只读观察，封装不可变 Flow+Identity+模型+环境配置 | 构建/观察较完整；“部署”主要是打包与本地安装，不等于托管服务 |
| 6 | Evaluation Lab | 自定义数据集、Task/Environment、Runner、预算、评分、可比实验与逐轨迹分析 | 本轮显著增强；矩阵调度、分布式隔离和统计显著性仍缺 |
| 7 | 证据门控的 Evolution | 从失败轨迹生成候选 Flow/Identity/Skill/Knowledge 变更，经保留集评测、审批、晋级、回滚 | 研究骨架存在；还不是默认可放心使用的个人自适应产品 |
| 8 | 轨迹与数据飞轮 | 记录每次模型真实输入输出、工具、图节点、压缩后上下文、版本和反馈，可回放并导出 SFT/RL 数据 | 基础强；本轮加入 OTel；仍缺因果反事实回放与数据集治理 UI |
| 9 | 安全、互操作与多环境运行 | 工作区边界、审批、容器、模式权限、Flow RuntimePolicy，以及未来 MCP/A2A/浏览器/OS 环境 | 本地安全已有多层；数据流来源标记和标准协议适配仍不足 |

### 1.1 哪些不是独立顶层 Feature

- Context summarize/curation 是 Flow Runtime 和轨迹数据治理能力，不应单独变成产品孤岛。
- 多 Agent、Subagent 和“Agent 自己创建 Agent”是 Flow/Subflow + 能力发现 + Evolution 的组合结果。
- 浏览器、搜索、Python、Terminal 都是 Environment/EGO 暴露的能力实现，不是新的 Agent 类型。
- CoC、Codex replica、DeepSeek replica 是模板和验证样例，不是架构层。
- Fork/Merge Session 属于 IDE/Session 数据管理与轨迹分支，不应另建一套历史模型。

---

## 2. 名词与权威边界：消除重复和冲突

### 2.1 推荐定义

**Flow**：可循环的执行图。定义控制流、数据流、模型调用、工具调用、等待输入、检查点和 Subflow。它不是 DAG。

**Flow Version**：一次不可变保存快照。运行、实验、重放和训练记录必须指向精确版本，不能只写 `latest`。

**Identity**：可复用的 Agent 身份包：

- `ID`：稳定人格、领域角色、沟通偏好和长期身份元数据；
- `EGO`：身份可调用的 Tool/Skill/Knowledge/Flow 能力集合；
- `Superego`：身份不可突破的行为、数据访问和自修改上限。

**Agent Configuration**：`Flow Version + 节点槽位到 Identity 的绑定 + Model Profile + Environment + 有效 Policy`。

**Runtime Agent**：Agent Configuration 在某个 Session Context 中运行出来的实例。Agent 不是单独一个 Flow，也不是单独一个 Identity。

**Environment**：Agent 能看到和操作的资源边界，如 workspace、容器、网络、浏览器、数据集和 secrets；它不定义人格。

**Session**：连续的人机交互与配置变更时间线。每条消息和运行都要记录当时的 Agent Configuration/Flow Version，而不是假设整个 Session 永远使用同一配置。

**Run / Trajectory**：一次可重放的执行实例和其有序事件；Task Run 是带固定输入、预算和评分器的 Run。

### 2.2 Superego 和 Flow 是否重复

会表达相似内容，但不应该拥有同样的权力。

| 层 | 应负责 | 不应负责 | 权威 |
|---|---|---|---|
| ID | “我是怎样的角色、如何沟通” | 文件/网络权限 | 软行为偏好 |
| EGO | “我拥有哪些能力实现” | 决定何时循环或晋级 | 能力供给 |
| Superego | “这个 Identity 永远不能做什么；何种自修改被允许” | 详细步骤编排 | 可复用身份级上限 |
| Flow | “先做什么、何时分支/循环/等待/压缩/调用谁” | 放宽 Superego 或工作区限制 | 运行编排，只能收窄权限 |
| Model 节点 Prompt | 当前节点的局部策略 | 全局安全宪法 | 局部策略 |
| Mode | Chat/Plan/Agent/Evolve/Evaluate 的场景级默认能力 | 人格 | 硬上限 |
| Workspace Security | 文件、进程、网络、容器和审批边界 | 业务风格 | 最终硬边界 |

有效权限必须是交集：

```text
effective = Superego ∩ Mode ∩ WorkspaceSecurity ∩ FlowRuntimePolicy
```

Prompt 不是安全边界；Flow 中画一个 Approval 节点也不能替代后端工具执行前的策略检查。反过来，Flow 的可视审批节点依然有价值，因为它使用户能看懂“为什么停住”，只是它属于可解释工作流，而后端检查属于不可绕过的防线。

本轮新增的 Governance Inspector 会把上述交集和冲突显示出来。此前 `allow_create_agent`、`allow_modify_agent` 等 Superego 字段并未在所有变更工具上强制，本轮已经修复。为了不静默破坏旧 Identity，没有任何 mutation 字段的旧 Superego 暂按 legacy 行为迁移；用户应逐步保存为显式策略。

### 2.3 仍然存在的重复

1. 部分 Python hook 在 Flow 外做生命周期逻辑，Build 无法完整显示，长期应迁移为通用事件/策略组件。
2. 旧 `/api/experiments` 与 Task Bench 有重复且包含内存态/占位逻辑，应最终合并到一个 Experiment service。
3. 某些模板把人格约束同时写进 Superego 和模型节点 prompt。前者应保留不变量，后者只保留任务策略。
4. README 和部分旧文档仍使用 “DAG/harness/agent” 混合术语，需要渐进迁移，API 兼容名可以保留但 UI 应只展示新名词。

---

## 3. 产品与工程实现审计

### 3.1 关键问题逐项回答

#### 数据集能不能自定义格式并可视化

**现在可以完成基础版，但不是任意 Schema Studio。** 本轮加入 `ego.dataset.v1` 适配器：支持 JSON、JSONL、CSV；用户可配置 ID、标题、Prompt、Expected、workspace files、metadata 的 dotted path/JSON Pointer 映射，先预览再保存，并物化为现有 `ego.task.v1`。前端 Task Bench 已加入导入、映射、预览、保存和筛选。

仍缺：拖拽式嵌套 schema builder、Parquet/Arrow、大型二进制 artifact 流式浏览、图像/音频列渲染、用户编写安全 evaluator 的隔离运行。因此“任意数据集”目前应表述为“常见表格/JSON 任务集可适配”。

#### 实验配置和记录是否做好

已有预算、Harness/Identity/Environment、事件、节点轨迹、评分和 Evolution 记录。本轮把实验使用的 Flow 从模糊 `latest` 改为 **精确不可变版本**，最近 Run 可以选择 2–8 个对比。

仍缺：真正的 Experiment Manifest（一次声明 model × Flow × Identity × dataset × seed 矩阵）、并发/分布式调度、失败重试策略、随机种子与 provider 快照、置信区间、成本上限和批量 artifact retention。当前适合小规模验证，不应称为完整实验平台。

#### 能否从同一入口比较 EgoAgent Codex 与原版 Codex

**现在可以做最小但真实的比较。** Task Bench 新增两个 Runner：

- `ego_flow`：运行 EgoAgent 的 `codex_flow` 或其他 Flow；
- `codex_cli`：调用机器上安装的上游 `codex exec --json`，保留原始 JSONL，再投影到统一 trace schema。

两者使用相同 Task、workspace fixture 和确定性 evaluator，可在 UI 选择 Run 并比较 score、时长、token、tool、step、错误和轨迹分歧。原版 Codex 的认证、模型可用性和 CLI 安装仍是外部前提；它不会被伪装为 Ego Flow，也不会继承 EgoAgent 的容器/节点审批语义。

#### 每条轨迹能否可视化并比较

Task Bench 现在有 runner-aware trace lane，比较会按有序 node/tool/model invocation 对齐，并标记首次分歧；保留 raw events 供进一步分析。当前是结构对齐，不是语义等价或因果归因；两个轨迹步骤编号相同不代表决策含义相同。

#### 能否在 Build 重放

- Ego Flow Task Run：可以加载该 Run 的精确历史 Flow Version、节点事件和 mutation，Build 被锁定为 `HISTORICAL TASK REPLAY`；退出锁后只是以历史图创建草稿，保存会生成新版本。
- 原版 Codex CLI：没有 Ego Flow 图，因此只能在 Evaluate 中显示由原始 JSONL 投影出的事件图；不能虚构成可编辑 Flow。

#### 自进化是否足够 general

类型层面已经覆盖 Flow、Identity、Skill、Knowledge、能力安装和候选晋级，且可以用 Subflow 组合；但产品层面仍不够 general。主要缺口不是“能不能改 JSON”，而是：

1. 如何从长期 Session 中提取稳定偏好而不把一次性要求固化；
2. 如何选择代表性失败/困难轨迹，避免只优化最近一个例子；
3. 如何在保留集和安全测试上证明候选没有回归；
4. 如何解释候选改变了哪条行为和为何值得晋级；
5. 如何在多次 evolution 后控制版本树、成本和可回滚性。

因此当前 Evolution 更接近研究/专家功能，还不是“普通用户打开即可放心让它自改”的成品。

#### 是否应该热修改正在运行的 Agent

不应该在一个模型/工具调用进行到一半时替换 Flow。那会让轨迹无法复现，也会导致旧节点状态与新图不兼容。推荐的“产品级热更新”语义是：

1. 当前 turn 继续绑定旧的不可变 Flow Version；
2. Evolver 在独立候选分支修改；
3. 运行回归、安全和偏好评测，生成 Promotion Certificate；
4. 用户批准或符合预设自动晋级规则；
5. **下一 turn** 切换新版本，并记录 `runtime.configuration.changed` 事件；
6. 失败时一键回滚，后续 turn 再绑定旧版本。

这对用户看起来接近实时，但不会牺牲可复现性。当前已经有不可变版本和 mutation 事件，尚未完成上述面向个人用户的 Preference Learner + 自动证书 + 下一 turn adoption 全链路。

#### 回放能否显示 Harness/Flow 如何变化

目前可以显示 mutation 事件并加载最终精确版本，但还不是完整的 **双时态回放**：

- valid time：变更在运行逻辑上从何时生效；
- transaction time：系统何时记录、审批和晋级它。

完整版本应允许时间轴停在任意事件，看到“该时刻模型实际收到的上下文”和“该时刻有效的 Flow/Identity/Skill/Policy”，并对任一步做反事实分叉。它是下一阶段最具 EgoAgent 差异化的方向之一。

### 3.2 成熟度总表

| 子系统 | 评级 | 优点 | 重大缺口/风险 |
|---|---|---|---|
| Code IDE | B | 工作区、Chat、Terminal、改动审阅已融合 | Accept/Reject 历史上多次回归；缺稳定的真实浏览器 E2E 套件 |
| Flow Build/Runtime | B+ | 循环、Subflow、版本、事件和观察能力有辨识度 | 图外 hook、复杂边布局和节点契约迁移仍需清理 |
| Identity | B | ID/EGO/Superego 的产品思想独特 | 旧配置迁移、重复 prompt、能力信任/签名不足 |
| Governance/Sandbox | B- → B | 多层策略、审批、workspace/container；本轮补齐 Superego enforcement/Inspector | 未实现 CaMeL 式细粒度数据 provenance/taint；host 模式不是 OS 级沙箱 |
| Capability Library | B | 语义搜索、统计、按 workspace 排序、缺失时创建 | 质量评分、兼容约束、供应链信任和去重还弱 |
| Session/Project | B- | 多 Session、fork/merge、逐消息配置基础 | 跨项目 portfolio 与分支可视化仍不统一 |
| Evaluation Lab | C+ → B- | Task schema、轨迹、评分；本轮加入 dataset adapter、版本、baseline、比较、Build replay | 没有矩阵实验、隔离 worker pool、显著性、通用 benchmark adapters |
| Evolution | C+ | typed mutation、候选/晋级思想和事件基础 | 缺生产级 preference evolution、held-out gate、自动证书和 bitemporal replay |
| Trajectory/Data | B | 精确请求、工具、压缩后上下文、多 Agent 区分、SFT/RL export | 缺 dataset lineage、PII review workflow、step credit assignment 和 causal replay |
| Deploy/Interop | C | Flow package/安装可用 | 不是托管 deployment；无完整 AgentCard/A2A endpoint，MCP 也未成为统一边界 |

---

## 4. 最近 Agent 研究与 EgoAgent 的关系

调研优先采用论文、官方规范和项目官方文档，而不是二手热点文章。

1. **Agent Lightning / Harnessed Agentic RL**：将 Agent execution 与 training 解耦，把动态/多 Agent 轨迹统一成可训练 transition，并做 credit assignment。EgoAgent 的 event + exact context + version 已是合适底座，但不能只导出拼接 messages，需要明确 observation/action/reward/next-state 与责任归属。\
   来源：<https://arxiv.org/abs/2508.03680>、<https://arxiv.org/abs/2608.17528>
2. **Darwin Gödel Machine**：保留开放式 Agent 版本树，从 archive 选择父代并用经验评测决定后代，而不是反复覆盖一个“最佳 prompt”。EgoAgent 应把 Flow/Identity/Skill 版本共同看作 genotype，并保留多样性。\
   来源：<https://arxiv.org/abs/2505.22954>
3. **Retrospective Harness Optimization (RHO)**：从历史轨迹抽取多样、困难 coreset，重新 rollout，以 self-consistency/self-preference 选 harness 改进。它非常契合 EgoAgent 的日常使用数据飞轮，但必须防止自评偏差并保留人工/确定性 grader。\
   来源：<https://arxiv.org/abs/2606.05922>
4. **Causal Agent Replay**：通过对某一步做 `do` intervention 并向前重跑，区分“发生错误的步骤”和“真正导致错误的决策”。Flow 的结构和不可变版本使 EgoAgent 比纯聊天记录更适合做因果回放。\
   来源：<https://arxiv.org/abs/2606.08275>
5. **CaMeL**：把可信 control flow 与不可信 data flow 分开，并用 capability 阻断隐私数据流向未授权工具。EgoAgent 目前有工具权限，但缺少“这段值来自网页/secret/用户文件”的 provenance 标签和跨节点 taint propagation。\
   来源：<https://arxiv.org/abs/2503.18813>
6. **Prime Agent / Continual Harness**：持久 REPL、跨轨迹 histories/memories/skills/subagent specs、递归 subagent 让长程任务不完全依赖当前 context。EgoAgent 应吸收“持久可验证 artifact”，但不应默认开放一个长期存活、可执行任意 Python 的进程。\
   来源：<https://arxiv.org/abs/2608.23552>
7. **LongHorizon-Harness**：把任务状态放在上下文外，由 manager 管理、fresh executor 执行、read-only auditor 验证环境事实。它支持把 EgoAgent 的 planner/executor/verifier 做成三个可替换 Subflow，并把“事实状态”作为特殊 typed state，而不是总结文本。\
   来源：<https://arxiv.org/abs/2608.01964>
8. **BrowserGym / OSWorld**：统一 observation/action/evaluator 比单独增加 browser tool 更重要；真实网页/桌面任务要求可复现环境和 execution-based grader。EgoAgent 应增加 Environment Adapter，而非为每个 benchmark 硬编码页面。\
   来源：<https://arxiv.org/abs/2412.05467>、<https://arxiv.org/abs/2404.07972>
9. **Holistic Agent Leaderboard**：同时比较 model、scaffold 和 benchmark，并保留成本与日志，揭示“更高 reasoning effort 不一定更好”等系统级现象。这证明 EgoAgent 的实验对象必须拆开 Model/Flow/Identity，而不是只显示总分。\
   来源：<https://arxiv.org/abs/2510.11977>
10. **MCP / A2A / OpenTelemetry**：MCP 解决 Host 与 Tool/Resource/Prompt server 的能力协商；A2A 用 Agent Card、Task、Message、Artifact 和 streaming 连接独立 Agent；OTel GenAI 用标准 span 表达 model/tool/agent 操作。它们分别对应 EgoAgent 的能力接口、Agent 部署接口和可观测导出，不应被一个“万能插件协议”混为一谈。\
    来源：<https://modelcontextprotocol.io/specification/2025-06-18/basic/index>、<https://github.com/a2aproject/A2A/blob/main/docs/specification.md>、<https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md>

---

## 5. 十二轮技术方案打磨

这里的“轮”不是列十二个热点，而是记录方案如何被否定、收窄和组合。

| 轮次 | 候选方案 | 判断 | 对最终方案的影响 |
|---|---|---|---|
| 1 | 再增加更多内置工具/Agent 模板 | 否决为主方向；只会扩大 UI 和维护面 | Tool 继续作为 EGO/Environment 能力，不升格为核心 |
| 2 | 把所有能力改成 MCP | 部分采纳；MCP 适合外部 Tool/Resource，不适合内部控制流与 Identity | Flow 保持内部 IR，增加 MCP adapter 而非重写 Runtime |
| 3 | 用 A2A 取代 Subflow | 否决替代，采纳边界 | 同进程可观察组合用 Subflow；跨服务 opaque agent 用 A2A |
| 4 | 只做漂亮的 trajectory viewer | 不足；只能回答“发生了什么” | viewer 必须绑定 exact config、state delta 和 evaluator |
| 5 | 直接把整段聊天导出 RL | 否决；多 Agent/工具/压缩会导致 credit 混乱 | 采用 transition/role/version-aware 数据模型，准备 Agent Lightning adapter |
| 6 | 每次 Evolution 覆盖最新 Flow | 否决；不可复现、容易退化 | 不可变版本树、候选分支、晋级与回滚成为硬约束 |
| 7 | 使用 DGM 式开放 archive | 采纳研究层；但产品不应无限无门槛扩张 | archive 保留多样候选，受预算、sandbox、held-out gate 约束 |
| 8 | 每 N 轮自动凭最近对话改自己 | 否决；会把偶发指令当偏好且存在投毒 | 用 RHO 式 diverse coreset + preference evidence + 用户确认 |
| 9 | 让 LLM judge 决定哪一步错 | 否决作为唯一证据 | 增加 causal replay：干预后向前重跑并报告置信区间 |
| 10 | 只在工具入口做 allow/deny | 不够；不可信网页数据仍能影响后续 control flow | 引入 provenance/taint/capability data-flow，Flow edge 需携带信任标签 |
| 11 | 为每个 benchmark 写一个页面 | 否决；不可扩展 | Dataset Adapter + Environment Adapter + Evaluator Adapter 三层协议 |
| 12 | 最终组合 | 采纳 | **Evidence-Gated Flow Evolution + Bitemporal/Causal Replay + Protocol Adapters** |

### 5.1 最终技术主线

最终主线不是单个新 Agent，而是一个闭环：

```text
Build immutable Flow/Identity
        ↓
Run in typed Environment ──→ exact event/state/config trajectory
        ↓                              ↓
Evaluate against deterministic/user/model graders
        ↓                              ↓
Mine diverse failure/preference coreset ← feedback/data selection
        ↓
Generate diverse candidate Flow/Identity/Skill changes
        ↓
Sandbox + held-out + security + cost evaluation
        ↓
Promotion Certificate + human/automatic policy gate
        ↓
Adopt at next turn, never mid-step; retain branch and rollback
        ↓
Bitemporal replay / causal intervention / SFT-RL export
```

它同时服务产品与科研：普通用户得到可解释、安全的个性化适应；研究者得到 model × Flow × Identity × data 的受控实验与因果轨迹；开发者得到可部署版本和标准协议边界。

### 5.2 研究 Novelty 的现实判断

单独做“自改 prompt”“自动创建工具”“轨迹回放”“Flow 图”都不再足够新。更有潜力的贡献是：

1. **结构化 genotype**：Flow + Identity + Capability + Policy 的联合但分权搜索空间；
2. **证据门控晋级**：把真实用户偏好、确定性 evaluator、安全数据流检查和成本共同纳入 Promotion Certificate；
3. **双时态因果回放**：对历史 Agent Configuration、上下文压缩和 Flow mutation 做可复现 intervention；
4. **同一平台分离三种变量**：Model、Flow、Identity 可独立对照，避免把模型升级误当 harness 改进；
5. **从产品数据到研究训练**：用户反馈 → 可审计数据选择 → multi-agent credit → SFT/RL，而不是事后拼聊天 JSON。

这条组合有研究潜力，但“能投 NeurIPS”必须由真实 benchmark、消融、跨模型泛化、安全回归和统计显著性证明，不能从架构图直接得出。

---

## 6. 本轮已实施内容

### 6.1 自定义数据集与实验入口

- 新增 `task_bench/datasets.py`：JSON/JSONL/CSV、字段映射、预览、保存、物化为 Task、大小/行数/路径安全检查。
- 新增 API：dataset list/detail/preview/save。
- Task Bench UI 新增数据内容、格式、映射、evaluation template、预览与保存。
- 长名称用可读前缀 + 内容 hash，避免路径/ID 超长碰撞。

### 6.2 精确版本、原始基线和对比

- Task Run 必须解析并记录不可变 `harness_version`。
- 新增真实 `codex_cli` runner，调用上游 `codex exec --json`，保留原始 JSONL 并映射到共同轨迹。
- 新增 2–8 Run comparison：指标、调用序列对齐、首次分歧、Evolution 事件。
- Task Bench UI 可以选择 runner、Flow version、历史 Run 和对比。
- Ego Flow Run 可送到 Build 做锁定历史回放；外部 Codex 只显示外部事件图，不伪造 Flow。

### 6.3 Superego 与统一治理

- 在实际 Tool 入口强制 `knowledge_access` 和 create/modify Agent/Identity/Skill/Tool/Knowledge 权限。
- 只读的 list/analyze/inspect 不被变更开关错误阻断；install/apply 才要求变更权限。
- 新增 `governance.py` 与 `/api/governance/inspect`，展示 Superego、Mode、Workspace Security、Flow RuntimePolicy 的有效交集和冲突。
- Identity Manager 的 Superego 页面可以选择 Flow/Mode 检查权限矩阵。

### 6.4 训练与观测互操作

- `trajectory.py` 新增 OTLP/JSON GenAI trace 导出：`invoke_agent`、`chat`、`execute_tool` 和 Flow node spans。
- 保留 Ego 原始事件 JSONL 为 canonical source；OTel 是可选互操作视图，不反向替代精确轨迹。
- 原有 LLaMAFactory、VERL、Ego episode 导出保持兼容。

### 6.5 涉及的主要文件

- `task_bench/datasets.py`
- `task_bench/engine.py`
- `governance.py`
- `agent.py`
- `trajectory.py`
- `harness_editor/api_extensions.py`
- `harness_editor/src/components/TaskBench.tsx`
- `harness_editor/src/components/IdentityManager.tsx`
- `harness_editor/src/App.tsx`
- `harness_editor/src/executionProjection.ts`
- 对应的 `tests/test_task_datasets.py`、`tests/test_task_bench.py`、`tests/test_governance_inspector.py`、`tests/test_superego_governance.py`、`tests/test_trajectory.py`

### 6.6 二次产品验收（不是只跑单元测试）

第一轮构建通过后又做了完整的 Void 内真实 UI/HTTP 验收，并发现第一轮结论确实过快。具体发现并修复了：

1. `harness_editor/dist` 虽然已构建，但正在运行的 Void 使用的是扩展内复制产物；新增页面实际没有进入产品。现在 `package:extension` 会构建并同步 `void_extension` 与活动 `void-web` 扩展。
2. 8765 上一度同时存在两个旧/新 Python 监听进程，导致页面随机命中不同后端。已停止两个重复进程并只启动一个最新后端。
3. 数据集覆盖保存不是事务性的，失败时可能留下部分 Task，覆盖时也会残留旧物化任务。现在采用 staging、替换、回滚，并清理该数据集拥有的陈旧 Task。
4. Governance Inspector 之前展示了 Superego 配置，但工具白/黑名单并未真正进入每一行有效权限计算；现在工具和 Knowledge 都进入 fail-closed 交集，并检测白黑名单冲突。
5. 原版 Codex runner 的多轮 token 统计会覆盖而不是累加，外部 command item 也未计入 tool calls；现在统一累计。
6. OTLP 属性中的数组/对象被编码成 JSON 字符串；现在使用 OTLP `arrayValue` / `kvlistValue` 类型。
7. 历史 Task 输出使用旧消息 schema 时缺少 `tools` / `blocked`，点击“在 Build 回放”会触发 React `.map()` 白屏。现在所有 Session/Task 回放入口先做兼容归一化。

真实前端验收路径已经走通：

- 在 Evaluate 中用 `offline_trace_smoke + aider_review_worker@v000001-… + test_bot` 运行离线题，得到 100/100、3 次模型步骤、2 次工具步骤和 7 条节点轨迹；该题使用 scripted DummyLLM，不消耗 API。
- 运行记录保存精确 Flow Version；点击“在 Build 回放”进入 `HISTORICAL TASK REPLAY`，显示当时版本和七步输入/模型/工具/输出，再点击退出回放恢复可编辑草稿。
- 在 Evaluate 选择新旧两个同题 Run，前端能并排显示版本、score、duration、model/tool counts 和七行轨迹。
- 自定义 JSON/JSONL/CSV 数据集映射可预览真实 case；后端会再次验证，不依赖前端信任。
- Identity → Superego → 统一治理预览能显示工具、Knowledge、变更能力的 Superego/Runtime/最终交集。

验证结果：核心回归集 `204 passed, 1 skipped, 2 subtests passed`；完整 `tests/` 在受限沙箱内为 `630 passed, 3 skipped, 148 subtests passed`，唯一失败是无头 Chromium 被沙箱阻止监听 CDP；对该项按要求在允许启动本机浏览器的边界下单独重跑后通过。因此代码测试没有遗留失败，但这不等价于下方尚未完成的产品/科研能力已经完成。

---

## 7. 后续实施优先级

### P0：安全与可信数据流

1. 给 Flow port/value 增加 `provenance`, `trust`, `sensitivity`, `capabilities` 标签。
2. 从网页、MCP、workspace secret、用户输入进入时自动标记；Subflow/模型/工具传播标签。
3. 在执行副作用工具前做 data-flow policy check，并在 Build 用 edge badge 可视化。
4. 建 prompt injection、安全泄露和 policy bypass benchmark。

### P1：统一 Experiment Matrix

1. 新建不可变 Experiment Manifest：dataset × runner × model × Flow version × Identity version × seed。
2. 使用隔离 worker、预算、恢复、retry 和 artifact retention。
3. 统计 success/cost/latency/variance，支持 paired comparison 与显著性。
4. 增加 SWE-bench/Terminal-Bench/BrowserGym/OSWorld adapter，但本机默认运行小 subset。

### P1：面向用户的 Preference Evolution

1. 从点赞/点踩/重要标记和接受/拒绝改动中提取候选偏好，区分项目局部与全局。
2. 用多样性 coreset 生成多个候选，禁止直接修改 live version。
3. 生成 Promotion Certificate：改变内容、证据、保留集结果、安全/成本回归、适用 scope。
4. 用户可选择一次采用、项目采用、Identity 永久采用；下一 turn 生效。

### P1：双时态与因果回放

1. 给 config/context/mutation/state delta 建 valid/transaction time 索引。
2. 时间轴任意停点恢复真实 model input 和有效 Flow/Identity。
3. 支持替换 prompt/tool result/branch/Flow version 后向前重跑。
4. 输出 effect size、置信区间和多步 Shapley（预算受限）。

### P2：标准协议与真实环境

1. MCP client/server adapter 只处理 Tool/Resource/Prompt，保持 host 权限隔离。
2. A2A Agent Card 从发布的 Agent Configuration 生成，映射 Task/Artifact/stream。
3. BrowserGym/OSWorld Environment Adapter 提供统一 observation/action/evaluator。
4. OTel exporter 对接 collector；默认不捕获敏感 prompt/result，需用户显式开启。

---

## 8. 明确尚未完成的事项

- 没有声称已经完成通用、生产级自进化；目前缺 Preference Evolution 和完整 Promotion Certificate 流程。
- 没有把保存后下一 turn 切版本误称为 mid-run hot swap；真正的 mid-step 替换被有意禁止。
- 没有完成分布式/大规模 Experiment Matrix；当前是单机 Task Bench 与对比基础。
- 没有实现 CaMeL 级 typed provenance/taint，这仍是安全 P0。
- 没有实现完整 A2A/MCP 产品入口；当前仅完成内部能力体系和 OTel 导出的一部分互操作。
- 没有证明研究方案达到顶会标准；必须用真实 benchmark、跨模型消融和因果/安全实验验证。
- 原版 Codex baseline 依赖本机 CLI 与认证；自动化测试验证事件投影，不等于已经在本机消耗模型额度跑完大规模对照。
- 外部 Codex 没有 Ego Flow，因此只能重放其事件，不能在 Build 中虚构可编辑节点图。

这份边界说明应保留在后续产品文档和论文中：EgoAgent 的可信度来自“每个能力都能指出证据、版本和限制”，而不是功能数量。
