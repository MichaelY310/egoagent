# EgoAgent 全功能清单与 parity 覆盖审计

> 审计日期：2026-09-08\
> 范围：当前仓库的产品 UI、Flow Runtime、Identity/Capability、上下文治理、自进化、Task Bench、轨迹与训练数据、安全、研究与演示资产。\
> 重要口径：**实现存在、自动化测试通过、真实模型跑通、真实模型匹配对照**是四种不同证据；本文不把它们混在一起。

## 1. 证据等级

| 等级 | 含义 |
|---|---|
| **P** | 使用同一真实模型、同一任务和确定性评分器的 matched parity / ablation；只改变目标机制。 |
| **R** | 用真实 DeepSeek V4 Flash 跑通过，但没有匹配对照组。 |
| **T** | 有自动化单元、集成、契约或 UI 静态测试；不能说明真实模型使用该能力后更好。 |
| **I** | 有实现或实验入口，但本轮没有找到足够直接的专项验证。 |
| **C** | 条件可用：依赖浏览器、Container、embedding 模型、外部服务或主机权限；失败时可能降级。 |

## 2. 完整功能清单

### A. Code IDE 与原生 Chat

1. 在 Void 中打开多文件、编辑代码、文件树、标签页和集成 Terminal。
2. Chat / Plan / Agent / Debug / Evolve / Evaluate 六种模式；模式改变实际权限策略，不只是提示词标签。
3. 一个 Session 内可切换 Flow、Flow Version、Identity、模型配置和模式；每条消息记录当时的说话者和配置版本。
4. 运行状态、当前节点、模型输出、工具调用、审批、等待输入、错误、截断与结束状态实时显示。
5. 思考与常规工具过程默认折叠，最终 Markdown 输出单独渲染。
6. Agent 运行时可发送 steering / 后续输入；等待输入与运行中输入走持久化队列。
7. `@file`、`@selection`、`@workspace`、`@terminal` 结构化上下文。
8. 编辑器选区、文件/文件夹拖放、Clipboard 文本/图片、Terminal 选区可作为结构化附件；保留来源、文件与行号。
9. 代码库增量索引、符号/依赖图、文件检索、代码地图、上下文计划与检索反馈。
10. FIM / Tab 自动补全、补全接受统计。
11. Next Edit 预测，在候选文件和坐标范围内提出下一处修改。
12. 选区内联编辑、完整文件编辑、AI code review、commit message 生成。
13. Agent 写文件后默认立即落盘，同时创建可审阅 change transaction。
14. 编辑器内红色删除、绿色新增、逐 hunk Accept / Refuse；已决策 hunk 可用 Ctrl+Z 恢复为待审状态。
15. 新建、删除、移动、二进制文件与 CRLF/LF 的差异追踪；新文件拒绝时要求显式删除确认。
16. Checkpoint 创建、预览、选择文件恢复、冲突检测、运行前后自动快照。
17. 后台隔离 workspace，可预览并选择性 handoff 回主工作区。

### B. Project、Session 与长期工作

18. 注册、创建、打开多个 Project；每个 Project 保存自己的 Session、规则、记忆和 workspace 绑定。
19. 一个 Project 内创建多个 Session；重命名、置顶、归档、移入回收站、恢复和删除。
20. 每个 Session 独立保存 Agent Configuration，并记录逐消息配置历史。
21. Fork Session：复制自包含历史与 lineage，再从分叉点独立继续。
22. Merge Session：直接追加增量、长历史分别总结后合并、两个 Agent 对话归并；支持多 Session 去重合并。
23. 跨 Project merge 默认拒绝，避免把不同 workspace 的状态混入。
24. Session/Run lineage、cached report、评分、历史配置和 exact Flow Version 查询。
25. Background Run、持久队列、lease、重试、幂等、暂停、恢复、取消、discard、fork、replay、handoff 和崩溃恢复。
26. 可选 Heart Flow：跨项目 focus、park、恢复 capsule、后台通知 inbox；它是可独立删除的实验模块。

### C. Flow Graph 语言、Builder 与 Runtime

27. Flow 允许环，不限于 DAG；节点、端口、边、条件和绑定都有声明式 schema。
28. 当前注册的 28 类节点：`输入`、`Agent`、`工具审查`、`文本处理`、`工具`、`进程`、`工作区`、`Python`、`模型`、`上下文`、`记忆`、`能力`、`条件`、`数据`、`保存数据`、`读取数据`、`循环`、`并行`、`映射`、`合并`、`人工审批`、`子流程`、`检查点`、`流程变体`、`搜索控制`、`循环守卫`、`输出`、`结束`。
29. Typed input/output sockets、多输入端口、边条件、循环次数/预算和 JSON-friendly 表单配置。
30. 普通 Model 节点、持久 Agent 工具循环、进程节点、受限 Python 节点和文件/数据操作。
31. Condition、Loop、Map、Parallel、Join、Wait Input、Approval、Checkpoint 等控制流。
32. SubFlow/SubDAG 复用：输入映射、输出映射、可选择共享 Session；Flow 搜索结果能作为 typed subflow contract 使用。
33. Agent slot 绑定 Identity；同一 Flow 可绑定不同角色实现。
34. Flow Blueprint 与 EgoIR：弱模型可读的文本表示、结构化 patch、校验、事务提交与回滚。
35. Flow immutable version：每次保存产生版本；Session/trajectory 锁定实际使用版本，历史可复现。
36. Builder 独立编辑/试跑；锁定后只运行；Link Session 后只读观察该 Session 的精确 Flow 与节点事件。
37. 节点级输入/输出、模型话语、工具参数/结果、子 Agent、mutation 和 context replacement 可视化。
38. Pause / Resume / Step / Stop、断点、人工审批、等待输入和节点调试输入覆盖。
39. directed edge、typed socket、自动布局、节点/边多选、撤销、删除与画布缩放。

### D. Identity、EGO、Superego 与 Environment

40. Identity 的 ID 层描述角色、人格、长期状态和领域定位。
41. EGO 组合 Tool、Skill、Knowledge 和可复用 Flow；支持多个 EGO pack 继承/组合。
42. Superego 保存不可由普通提示覆盖的行为约束、工具权限和 pre/post hook。
43. Environment 保存 workspace/tool/knowledge 和执行环境信息；Identity 能跨环境复用。
44. Governance Inspector 展示 Superego、模式、Workspace Security、Flow Runtime Policy 的权限交集和冲突。
45. 自然语言或结构化 Agent Spec 创建可加载 Identity + 可视化 Flow。
46. Identity 克隆、编辑、删除；Skill/Knowledge 增删改；KP 等受限角色可事务化修改 Identity 状态。

### E. Capability Library：搜索、复用与创建

47. 统一索引五类能力：Tool、Skill、Knowledge、Identity、Harness/Flow。
48. 扫描项目内 capability pack、Identity EGO、Environment、workspace `.environment`、`.agents/skills`、`.codex/skills` 和 Flow。
49. 关键词、语义和 Hybrid 搜索；Hybrid 使用 lexical + embedding 的 RRF 融合。
50. 中文/英文同义词、精确名称、标签、路径、任务意图和成功证据参与排序。
51. 当前 workspace 私有结果隔离并优先；project/global/identity 作用域有明确排序。
52. 只把能力摘要/contract 放入选择上下文，选中后才激活完整实现，避免把所有 Skill 塞入 prompt。
53. 记录曝光、激活、成功率、耗时、使用量、评分、置顶和搜索事件；UI 类似能力市场展示。
54. 搜索不到强匹配时返回 `creation_recommended`，Agent 可转入受治理的创建流程。
55. 本地 FastEmbed 或 OpenAI-compatible embeddings；不可用时保留 lexical fallback。
56. Meilisearch **不是运行时依赖**；`meilisearch_manager` 只是旧调用兼容适配器，当前主体是本地 SQLite + Hybrid retrieval。

### F. 上下文、记忆与长时程机制

57. Working context 与 lossless trajectory 分离：模型可见历史能压缩，真实历史不丢失。
58. Durable workspace memory：`remember` / `recall`，可跨全新 trajectory 恢复未写入项目文件的事实。
59. Conversation Input 暴露消息、turn、token、工具块、来源和 anchor 等元数据。
60. Context Curator：普通 Model 生成 delete/summarize/replace-tool-result 计划，Conversation Output 校验后应用；适合离题删除、失败工具精简和隐私清理。
61. Passive Compactor / summarize：到 token 高水位被动触发，由普通 Model 对块级上下文做摘要，保留系统约束、最近消息、未完成工具对和 durable anchors。
62. Tool Result Pruner：超长 observation 在模型上下文保留 head/tail，完整结果仍在 lossless trajectory。
63. Repeat Tool Guard：跟踪规范化工具名与参数，在第 2/3/5 次精确重复时提醒，避免循环；不伪造硬阻断。
64. Context restore 与审计：可查看被删除/摘要/替换的原块和压缩后的下一次真实模型输入。
65. 周期行为不硬编码在 Chat：Loop/Condition/SubFlow 决定每隔多少 turn 运行 curator/evolver。

### G. 自进化、自创建与多 Agent

66. Governed Skill evolution：发现重复工作 → 先搜索 → 提议 → 创建/修复 → 验证 → 激活；失败项隔离。
67. Knowledge evolution：把稳定事实/资料组织为可检索 Knowledge，并保留来源与版本。
68. Identity evolution：事务化修改人格、状态、Skill/Knowledge/Tool 绑定，受 Superego 和审批约束。
69. Flow structural evolution：对节点、边、绑定和治理规则做 typed mutation；候选在隔离版本验证后才 promotion。
70. Agent Factory：模型用 Agent Spec 选择/创建 Identity 和 Flow，生成可视化、可复用 Agent Configuration。
71. Sub-Agent delegation：动态选择/搜索子 Flow，分配隔离路径与目标，保留独立 child trajectory，只向父 Agent返回契约化结果。
72. Agent Bus：跨角色消息、订阅、幂等消费、lease/redelivery/dead-letter，支持多 Agent 协作。
73. EvoCert / proof evolution：held-out、poison、回归、预算、必要性、可迁移性、无干扰和组合交互证书；失败可 rollback。
74. Flow Variant 与 factorial analyzer：生成消融组合、分析 main effect/interaction，并保留 lineage。
75. Evolution UI：proposal、artifact selection、empirical gate、certificate、apply、rollback 和实时结构变化。

### H. Web、Browser 与外部行动

76. Web Search、URL fetch、批量抓取、freshness、域名包含/排除、去重、引用与截断标记。
77. SSRF 防护：阻止私网解析、URL credential，redirect 每跳重新校验。
78. CDP Browser：导航、观察页面/viewport/元素、点击、输入、键鼠、拖放、对话框、下载、截图和关闭。
79. 浏览器证据、navigation 后 stale action batch 中断、CAPTCHA/human handoff 和 final judge。
80. Tool/skill 可扩展接入其他能力；模型接口与能力实现通过 manifest/contract 分离。

### I. Model Provider、路由与兼容性

81. OpenAI-compatible Chat API，DeepSeek tool calls/stream/non-stream/JSON/reasoning 兼容。
82. 模型 profile、endpoint、密钥存储、角色分配（chat/tool/edit/reasoning/judge/evolver 等）、预算和上下文窗口。
83. 按角色、任务、预计上下文/输出进行 model route preview；circuit breaker、fallback 和离线 Ollama 路由。
84. 429/Retry-After、timeout、provider usage、cached token、事件 ID 恢复和不可安全重放保护。
85. 输出达到上限时保存 partial output、显示截断原因，并丢弃不完整 tool call。
86. DeepSeek Windows DNS/10013 scoped proxy 恢复；只代理指定 provider，不全局修改系统网络。

### J. 安全、审批与隔离

87. Workspace Guard：路径规范化、绝对路径/`..`/symlink escape 防护，写入限定当前 workspace。
88. Tool gate：allow / ask / deny、参数模式、高风险命令审批、一次允许和持久策略。
89. 六种模式的工具可见性和执行权限；只读模式在请求前隐藏写工具，执行时仍有第二道策略。
90. Container 模式：模型调用在 host，命令在硬化 container；workspace 以受控 mount 映射，配置失败时 fail closed，不偷偷回退 host。
91. Host 模式明确提示不具备 OS/container sandbox；高风险动作必须审批。
92. Python 节点要求强 sandbox；没有安全 backend 时拒绝执行。
93. Secret 按变量名授权、持久化前和导出边界再次脱敏；诊断包也做 redaction。
94. Local API 的 Origin/CORS/host 检查；网络、全局 mutation 和未知工具不能被 Flow 静默放开。

### K. Task Bench、实验与科研工作流

95. 标准 Task schema：题目、步骤、workspace fixture、环境、预算、评分器、期望产物、兼容 Flow/Identity。
96. JSON / JSONL / CSV 数据集导入，字段映射、preview、保存和 materialize；当前不是任意 Parquet/多模态 schema designer。
97. 单步与多步题、fresh trajectory、交互输入、暂停副作用、resume/recover 和隔离 workspace。
98. 文件、文本、进程、单元测试、数值 reward 等确定性评分。
99. 同一 Task/fixture/evaluator 下比较 EgoAgent Flow、不同消融 Flow 和 Codex CLI runner。
100. Run 对比：分数、token、耗时、工具数、节点 trace、错误、evolution event 和 aligned trajectory。
101. Task 历史回放到 Build，锁定当时 Flow Version，并显示当时节点/模型/工具/上下文变化。
102. Harbor / TerminalBench 风格任务导入和 Harbor 导出。
103. Research Lab：harness conformance、translation benchmark、Science Project/source/artifact/stage/audit。
104. Experiment CRUD、scenario、统计、结果保存；这是 legacy 实验入口，与 Task Bench 有部分重叠。

### L. 轨迹、回放、反馈与训练数据

105. append-only typed trajectory：用户消息、模型请求/响应、工具调用/结果、节点输入/输出、审批、错误、mutation、checkpoint 和 context replacement。
106. 每次 model call 保存**真实送给模型的 messages/tools**；summarize 后的后续调用只看到压缩后历史，原始块仍可审计。
107. 多 Agent 共享 root trace 但保留 agent/identity/flow/node/model-call 标识，避免训练时混淆。
108. capability snapshot、Flow Version、source hash、event sequence、完整性 hash 和 incomplete/training-readiness 检查。
109. Session replay、模型调用列表、context timeline、summary、重构对话和 OTel trace 导出。
110. 可选 collection mirror：永远写默认 trajectory；开启后再复制一份到用户指定目录。
111. Session/message/model-call 点赞、点踩、重要、加入训练集、标签和备注；annotation sidecar 不修改原始轨迹。
112. 导出粒度：完整会话、单条 message SFT、精确 model-call SFT、unary feedback、pairwise preference、完整 trajectory。
113. 格式：OpenAI conversation JSONL、message/model-call JSONL、LLaMA-Factory ShareGPT + `dataset_info.json`、TRL preference、VERL rollout JSONL，以及依赖可用时的 Parquet。
114. VERL reward 只在可信 checker/certificate 提供时写入；不会把任意 Agent 自评当真 reward。

### M. 打包、模板、娱乐与教学

115. Agent package：pack/inspect/install/update/uninstall/fork、semver dependency、签名、信任、评分和事务回滚。
116. 防 archive traversal 和明文 secret；安装不可信包要求显式 override。
117. 108 个当前 Flow 资产（其中包含本轮 18 个 internal experiment Flow），覆盖产品 Agent、可复用 component、消融、研究 Flow、娱乐 Flow 和开源 harness replica。
118. 主要开源复刻：Aider、Codex、DeepSeek Harness、Continue、OpenHands、OpenManus、SWE-agent、Browser Use、Stagehand、GPT Researcher、Open Deep Research、MetaGPT/MGX、AutoGPT Platform、Devika、Voyager、Generative Agents、AI Scientist。
119. ARC-AGI-3：官方文本/动作适配、精确网格/RLE/变化摘要、持久假设记忆、stagnation supervisor 和 scientific search controller。
120. CoC 7e：可复用人物卡 Identity、HP/SAN/物品 Tool、KP 受限事务、隐藏信息、可回放骰子和用户参与。
121. Creative Roundtable、带裁判辩论、双 Guardian 等多 Agent 示例。
122. 18 集/100 步录制教程、严格高亮/限制步骤、演示 repo、reset/verify/preflight 资产。
123. Workbench light/dark theme、Home、Build、Evaluate、Evolution、Research、Capabilities、Packages、Changes、Checkpoints、Identity、Environment、Sessions、CoC、Heart Flow、Settings 页面。

## 3. 当前预制 Flow 的分组

为避免把“功能”和“108 个配置文件”混为一谈，这里只按用途列入口；完整目录是 `harness/`。

- **默认产品入口**：`code_agent_auto`、`code_agent_fast`、`code_agent_long`、`code_agent_team`。
- **产品内核/工作单元**：`product_core_code_agent`、`product_adaptive_code_agent`、`product_bounded_code_worker`、`adaptive_code_agent`、`bounded_coder_worker`、`coder_react`、`react_single`。
- **可复用组件**：`component_agent_designer`、`component_capability_discovery`、`component_capability_evolver`、`component_context_compactor`、`component_context_curator`、`component_flow_evolver`、`component_repeat_tool_guard`、`component_scientific_search_controller`、`component_tool_result_pruner`。
- **自进化/研究**：`agent_factory`、`evolution_cycle`、`meta_evolution_cycle`、`improver`、`flow_evolution_showcase`、`session_analyzer`、`adaptive_research_agent`、`context_curator`。
- **Harness replica**：上节列出的开源项目及其 worker Flow。
- **ARC/娱乐**：`arc_direct_baseline`、`arc_long_horizon`、`arc_scientific_search`、`coc_lightless_beacon`、`coc_the_haunting`、`creative_roundtable`、`debate_with_moderator`、`dual_guardian`。
- **实验/消融**：`product_adaptive_no_*`、`product_adaptive_*only`、`product_context_endurance_*`、`demo_fragile_release_flow`、`demo_noisy_research_flow`。

## 4. parity 实验实际覆盖了什么

### 4.1 有真实 DeepSeek matched parity 的机制

| # | 机制 | 对照与结果 | 判定 |
|---:|---|---|---|
| 1 | Core vs Full/Standard 路由 | 小型修复均 5/5；Full token +14.9%、耗时 +101.6%。 | **P**：证明小任务不应总开高级能力。 |
| 2 | Durable memory | fresh trajectory：off 1/2、31,293 token；on 2/2、20,311 token。 | **P**：直接因果证据。 |
| 3 | Passive compaction / summarize | 25 回合均 25/25；80,657 → 58,999 token（-26.9%）。复现实验 82,332 → 63,336（-23.1%）。 | **P**：长对话有效。 |
| 4 | Proactive context curation | 两组均正确；36,147 → 52,705（+45.8%）。复现实验单开 +1.2%，与 compaction 组合 +14.1%。 | **P**：负结果，默认关闭。 |
| 5 | Tool-result pruning | 大文件修复均通过；315,740 → 109,133（-65.4%），复现为 293,041 → 81,714（-72.1%）。 | **P**：强正结果。 |
| 6 | Skill evolution 的学习阶段 | 7 次 release 均 7/7；evolution 创建、修复、验证并热加载 Skill，但学习轮成本 +149.5%。 | **P**：证明能学，不证明即时省钱。 |
| 7 | Evolved Skill fresh-session transfer | 3/3 vs 3/3；94,087 → 73,511 token，工具 14 → 3。 | **P**：证明跨 Session 复用收益。 |
| 8 | Capability Library 的全局 Skill 发现 | 任意兼容 Identity 可发现已发布 Skill；工具 15 → 8，但全面 Flow token 更高。 | **P（局部）**：覆盖 Skill 搜索/激活，不覆盖五种类型全部。 |
| 9 | Isolated sub-Agent delegation | 均 12/12；115,890 → 149,501 token；child context/path 隔离成立。 | **P**：价值是隔离，不是本题省钱。 |
| 10 | Tool pruning × compaction | 四格 factorial 均成功；pruning 解除压力后 compaction 自动不触发。 | **P**：安全共存/条件互斥，不是严格 `1+1>1`。 |
| 11 | Curation × compaction | 四格均成功；组合最贵，curation 让 compaction 无需触发并破坏 cache locality。 | **P**：负交互。 |

这里是 **11 个实验问题**，不是 123 项产品功能中的 11 项完整验收。第 6/7 是同一 evolution 机制的学习与迁移两个阶段；第 10/11 是交互实验。

### 4.2 有真实模型单组验收、但不是 parity 的内容

- `Code Agent · Fast`、`Auto`、`Long`、`Team` 均有真实 DeepSeek 任务通过记录。
- Team 真实创建一个 `product_bounded_code_worker`；Long 真实执行 recall/remember、compaction、pruning 和一次“证据不足，因此不进化”的 evolver 判断。
- 完整六阶段 release task 跑通 planning、工具循环、checkpoint、transactional review、quality/safety review、memory、compaction、pruning 和 evolution review。
- Codex/Aider/Creative Roundtable 等有历史真实调用验收，但不是本轮产品 parity matrix。

### 4.3 没有被当前 parity 覆盖的主要功能

以下功能即使有自动化测试，也**不能**宣称已被目前 parity 证明“提升模型效果”：

1. IDE 的 Tab completion、Next Edit、inline edit、Markdown/折叠/运行状态 UI。
2. 编辑器红绿 diff、逐 hunk Accept/Refuse/Ctrl+Z、Checkpoint 和后台 workspace。
3. Project/Session 重命名、fork、三种 merge、trash、lineage 和 per-message config history。
4. Flow Builder 易用性、typed sockets、edge/auto-layout、pause/step/breakpoint、linked replay。
5. Identity 的 ID/EGO/Superego 行为控制；尚无 matched identity/ego/superego 消融。
6. Tool、Knowledge、Identity、Flow 搜索；现有真实 parity 只直接覆盖 Skill 发现/复用。
7. Lexical vs semantic vs hybrid retrieval 的真实任务质量/成本对照。
8. Knowledge evolution、Identity evolution、Flow structural evolution、Agent Factory。
9. Repeat Tool Guard；目前有 reachability/fault-injection 与正常运行证据，没有真实 A/B。
10. Web Search、Browser/CDP、下载/引用和 CAPTCHA handoff。
11. 模型路由、fallback、DNS proxy、输出截断和多 provider 成本/质量对照。
12. Workspace Guard、审批、Container sandbox、secret redaction 的 adversarial model parity；这些主要靠安全测试。
13. Task/Dataset 自定义、Codex CLI 对比、轨迹 aligned replay；Task Bench 是本次实验载体，不是被消融对象。
14. 轨迹完整性、标注、LLaMA-Factory/TRL/VERL/OTel 导出和真实训练回灌。
15. Package Registry、安装/更新/回滚、部署工作流。
16. Harness replicas、ARC、CoC、Heart Flow、Research Lab 和 18 集教程。

## 5. 覆盖结论

**答案：没有涵盖所有。** 当前 parity matrix 的目标很窄但合理：它回答“默认 code agent 应开启哪些长时程机制、哪些机制昂贵、哪些机制会互相干扰”。它没有、也不应该被描述成整个 EgoAgent 产品的全面对比实验。

可以分成三层理解当前证据：

1. **产品机制因果证据（P）**：memory、compaction、curation、tool pruning、Skill evolution/reuse、delegation、Core/Full routing 和两个组合交互。
2. **真实 Agent 可运行证据（R）**：Fast/Auto/Long/Team、完整 release task、真实 child Agent 和正确 abstain 的 evolver。
3. **工程正确性（T）**：仓库完整 JUnit 记录为 855 collected、0 failures、3 conditional skips；本次审计又重跑 capability/context/training/session/task/parity 定义相关测试，结果为 `69 passed, 2 subtests passed`。

## 6. 本轮补测计划（现已完成）

为了验证“EgoAgent 作为可用 code 产品”的核心差异，本轮没有机械地给 123 项功能各跑一次模型，而是执行了下面 6 组高价值实验；结果见第 8、9 节：

1. **Identity control factorial**：同 Flow/模型/任务，比较无 Identity、ID、ID+EGO、ID+EGO+Superego；测合规率、任务成功率、越权率和 token。
2. **Capability retrieval matrix**：none / lexical / semantic / hybrid，分别覆盖 Tool、Skill、Knowledge、Identity、Flow；测 top-k recall、错误复用、创建重复率、token 和成功率。
3. **Structural self-evolution transfer**：静态 Flow vs 允许 Flow evolution；学习任务与 held-out transfer 分开，检查是否真的修改结构、能否 rollback、后续是否摊薄学习成本。
4. **Context full factorial**：memory × pruning × compaction × repeat guard，在长程真实 repo task 上测成功、遗忘、循环、token 和 prefix cache；curation 只作为按需处理臂。
5. **Single vs Team threshold curve**：按文件数/模块耦合度/上下文长度分层，找 delegation 从“只隔离”变成“提高成功率”的真实阈值。
6. **Product end-to-end study**：同一批 repo tasks 比较 EgoAgent recommended profile、EgoAgent core、原版 Codex/其他 CLI；统一 fixture/checker，另测人工审阅耗时、错误接受率、恢复能力和轨迹可训练性。

P1–P6 完成后，可以较诚实地说 parity 已覆盖 EgoAgent 的核心 code-agent 产品主张；UI、打包和娱乐模板仍应主要用可用性测试、E2E 与安全测试，而不是硬套模型消融。

## 7. 证据入口

- 产品消融总报告：`experiments/product_code_agent_acceptance/results/CAMPAIGN_REPORT_20260904.md`
- 组合消融报告：`experiments/product_code_agent_acceptance/results/COMBINATION_ABLATION_REPORT_20260908.md`
- 推荐 Agent 实测：`experiments/product_code_agent_acceptance/results/USER_AGENT_VALIDATION_20260904.md`
- 预注册：`experiments/product_code_agent_acceptance/COMBINATION_ABLATION_PLAN_20260908.md`
- Flow authoring：`docs/DAG_AUTHORING_MODEL.md`
- Task Bench：`docs/TASK_BENCH.md`
- Capability Library：`docs/CAPABILITY_LIBRARY.md`
- 产品/科研统一审计：`docs/EGOAGENT_UNIFIED_PRODUCT_RESEARCH_AUDIT_20260830_ZH.md`
- 全量工程测试记录：`experiments/product_code_agent_acceptance/results/FULL_SUITE_JUNIT_20260904.xml`

## 8. 同日补测进展（P1–P4）

本节是第 4.3 节缺口的增量结果；凡与前文“尚未覆盖”冲突，以这里的更新为准。

### P1 — Identity control factorial 与硬边界

- 同一 `product_core_code_agent`、同一 DeepSeek V4 Flash、同一代码修复与合成机密诱导题，比较 neutral / ID / ID+EGO / Full 四层。
- 第一轮四个 soft/prompt treatment 都完成代码，却都复述了诱导 marker。这是负结果：**人格或 prompt 不能冒充安全边界**。
- 随后把 Superego 的 `output_policy.redactions` 实现为确定性 post-model enforcement；它是 declarative Identity 配置，不是该题写死的字符串。Full treatment 在第二轮得到 1.0，且专项测试覆盖配置合成、治理检查与输出过滤。
- 结论：ID/EGO 适合表达行为偏好；不可覆盖的 confidentiality 规则必须由 Superego 对应的运行时执行器强制。
- 证据：`results/20260908_103315_identity_neutral_pilot_r1`、`20260908_103903_identity_layers_pilot_r1`、`20260908_104923_identity_full_hard_boundary_r2`。

### P2 — 五类能力检索矩阵

- 冻结 15 个 query，Tool / Skill / Knowledge / Identity / Flow 各 3 个；比较 none / lexical / semantic / hybrid。
- Hit@1：none 0、lexical 0.9333、semantic 0.8667、hybrid 1.0；Hybrid 的 Hit@3 与 MRR 也都是 1.0。
- 本地 FastEmbed 语义基础设施有效；不是把 lexical 结果伪装为 semantic。一次性 workspace override probe 同时通过“当前 workspace 优先”和“跨 workspace 隔离”。
- 结论：第 4.3 节第 6、7 项已补直接 retrieval 证据；真实 Agent 的 reuse/重复创建率仍应继续扩大任务样本。
- 证据：`results/20260908_110913_capability_retrieval_matrix_r1/report.json`。

### P3 — 结构进化与 held-out transfer

- 基线 Flow 的结构缺陷是 `Agent.has_tool_calls -> done`，即模型会请求工具但没有工具执行回路。
- Evolver 只收到失败轨迹与通用 typed mutation vocabulary，自主提出插入 `工具` 节点并将输出回连 `Agent`；它没有看到 held-out task 的答案或 task-specific 修补指令。
- paired gate：2 个 validation 中 baseline 0/2、candidate 2/2；2 个 held-out 中 baseline 0/2、candidate 2/2；只读 poison 两者都通过且 candidate 0 tool calls、0 mutation。
- candidate 仅晋升为 internal experiment，没有静默替换推荐产品 Flow。它显著增加 token，因此证据是“结构修复带来能力”，不是“结构进化省钱”。
- 结论：第 4.3 节第 8 项中的 Flow structural evolution 已补因果与 transfer 证据；Knowledge/Identity evolution 和通用 Agent Factory 仍未被这一实验覆盖。
- 证据：`results/20260908_112523_structural_evolution_paired_transfer_r1/promotion_gate.json`。

### P4 — Memory × pruning × compaction × repeat guard

- 完整 2×2×2×2 共 16 个 frozen cells，使用约 50KB 的真实代码 observation 压力夹具；每格一个 replicate。
- Memory-on 8/8 在 fresh trajectory 恢复 `ORBIT-CEDAR-842`；Memory-off 0/8，只能给出 `NO_MEMORY`。
- Tool pruning 不改变分数，平均实际 token 从 316,634 降到 136,181（约 -57.0%）；模型可见 observation 减少 50,006 chars，lossless trajectory 仍保留原文。
- Passive compaction 在这个单一夹具中分数不变，实际 token 仅小幅降低，不能据此夸大为普遍质量提升。
- Repeat guard 在没有精确重复调用的任务中分数不变、平均实际 token 从 200,921 增到 251,894；说明它应由风险/轨迹触发，而不是每轮无条件付费。
- 证据：`results/20260908_120418_context_four_factor_r3/report.json` 与同目录 `factorial_analysis.json`。

### P5 — Single vs Team threshold

- 三档 fresh fixture 的 Long/Team 共 6 格全部通过 checker；小型与中型均 0 child，大型 Team 才启动 1 个 `product_bounded_code_worker`。
- 大型 P5 格：Long 146,960 actual tokens / 91.1s；Team 117,128 / 67.4s。child 只处理一个 package，parent 处理另一个 package 并执行完整套件，路径/上下文隔离成立。
- 小型与中型没有达到单 child scope 的 `12 files OR 12000 bytes` 门槛，Team 正确不为展示功能而委派。
- 这是一次 size-ladder 产品验收。每格只有一个 replicate、所有分数都已到 1.0 ceiling，因此它证明“门槛和隔离工作”，不能证明 Team 普遍提高模型质量。
- 证据：`results/20260908_131107_team_threshold_p5_r1/team_threshold_analysis.json`。

### P6 — EgoAgent profiles 与 Original Codex

- 两道可再分发 fixture × Fast/Auto/Long/Team/Core/Original Codex，共 12/12 lane 通过确定性测试。
- 小题：Ego Core 的 provider-reported token 最低（24,551），Fast wall time 最短（22.4s）。
- 大题：Ego Fast 在 EgoAgent lanes 中 token 最低（98,347）且最快（55.9s）；Team 启动 1 child，但由于所有 lane 都满分，不能宣称质量提升。
- Original Codex CLI 0.152.0 两题都通过并保留原始 JSONL；wall time 分别约 467.8s 与 814.6s。其模型/provider 与 DeepSeek 不同，token 口径也不保证等价，所以这是异构产品 smoke comparison，不是“EgoAgent 模型优于 Codex”的证据。
- 实验发现并修复 Codex adapter 遗漏 `elapsed_seconds` 的问题；旧记录由 durable `started_at/completed_at` 回算，原始报告未被改写。
- 12/12 lanes 的 EgoAgent lossless trajectory 或 upstream Codex JSONL 都通过完整性检查。
- 证据：`results/20260908_132026_product_comparison_p6_r1/PRODUCT_COMPARISON_RESULT.md`。

## 9. 最终覆盖判定

P1–P6 补齐了核心 Agent 主张的关键证据：Identity/Superego 边界、五类 Capability retrieval、Flow structural evolution、上下文四因素、Team size gate、产品 profile 与外部 runner 对照。

它仍然**没有覆盖 123 项功能的每一项，也不应该全部用 LLM parity 覆盖**：

- UI、编辑器 diff、Session 管理、Builder 交互、教程和主题应由浏览器 E2E/可用性测试验收；模型消融回答不了按钮是否可点。
- Workspace Guard、审批、Container、secret redaction 应由 adversarial deterministic security tests 验收；不能用平均分替代安全不变量。
- Package、部署、数据导出、Harbor adapter 应由 schema/round-trip/integration tests 验收。
- Web/Browser 的线上稳定性需要独立的有网 E2E matrix，不能混入离线代码修复任务。
- Knowledge/Identity evolution、训练回灌、ARC、CoC、Research Lab 仍只有专项实现/测试/历史运行证据，未进入这批 P1–P6 matched campaign。

因此可以诚实宣称的是：**核心 code-agent 机制的高价值 parity 缺口已补；整个产品的每个功能并未、也不能由同一种 parity 实验证明。**
