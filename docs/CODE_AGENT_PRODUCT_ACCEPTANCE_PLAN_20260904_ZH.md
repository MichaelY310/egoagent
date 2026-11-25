# EgoAgent Code 产品验收计划（2026-09-04）

## 目标

本轮不追求论文结论。目标是确认 EgoAgent 能作为日常 Code Agent 使用，并找出“高级功能存在于代码中、但模型实际不会或不能使用”的产品缺口。

## 受测 Flow

1. `product_core_code_agent`：匹配的核心基线。保留规划、读写、测试、检查点、事务和证据判定；显式隐藏能力搜索、长期记忆、上下文治理、进化与子 Agent。
2. `product_adaptive_no_evolution`：与完整 Flow 共用同一个 SubFlow，只关闭进化。保留能力发现、长期记忆、上下文治理和隔离委派。
3. `product_adaptive_code_agent`：产品完整配置。增加按 session 证据进行的受治理进化。
4. `product_adaptive_pressure_lab`：仅用于低成本验证被动压缩；使用较小的“声明上下文窗口”，算法和提示词与产品 Flow 相同。

所有组使用相同的 DeepSeek V4 Flash 编码 Identity。对照组不是换弱模型，因此差异更容易归因于 Flow。

## 任务集

| Task | 目的 | 主要确定性判据 | 希望自然出现的能力 |
|---|---|---|---|
| `product_release_guard_long_horizon` | 连续维护同一 Python 项目 | 每轮新增测试通过 | 检索、记忆、第四轮精简、第六轮进化、独立问题委派 |
| `product_context_pressure_repair` | 大型失败输出后的代码修复 | 测试通过且输出归一化正确 | 工具结果裁剪、token 压力压缩、完整审计保留 |
| `product_recurring_release_manifest` | 七轮连续生成发布清单 | 每轮独立测试脚本通过 | 判断既有测试是否已足够复用，避免为了展示而进化 |
| `product_recurring_fictional_bundle` | 七轮相同契约、不同输入的 JSON 规范化 | 隐藏的精确 JSON evaluator | 在重复压力足够时创建、验证并持久化可执行 Skill |
| `product_recurring_telemetry_envelope` | 七轮不同输入、同一遥测契约 | 隐藏的精确 JSON evaluator | 使用真实累计成本决定进化，并验证同轮热加载 |
| `product_fictional_bundle_skill_reuse` | 新 Session 处理第八个同类输入 | 精确键集合与字段值 | 搜索、激活并调用上一 Session 产生的 Skill |
| `product_isolated_package_repairs` | 检验子 Agent 隔离范围 | 多包联合测试 | 只在独立子任务达到成本门槛时委派 |
| `video_code_agent_walkthrough` | 小型回归与成本下界 | 4 个单元测试通过 | 不应为了简单任务过度委派或进化 |
| 真实公共任务子集 | 非人为项目结构上的泛化 | 原仓库测试 | 发现工程兼容性问题；不以隐藏补丁提示模型 |

## 不作弊规则

- 任务 prompt 不要求“现在创建子 Agent”“现在进化”或指定要创建的 artifact 名称。
- 不向模型提供隐藏测试答案、gold patch 或 evaluator 正则。
- Flow 的 cadence 触发只算“系统触发”；只有 `should_evolve`、artifact 选择与持久化动作由模型给出证据时，才算“模型决定进化”。
- `create_harness` 必须有真实 `subagent_spawned` 和 `subagent_completed` 事件；口头声称委派不算。
- 能力复用必须出现 `search_capabilities`，并在强匹配时出现真实 activation/调用；仅复述搜索结果不算。
- 精简由固定轮次触发，但 keep/summarize/elide 是模型决定；压缩则必须先由确定性的 token 水位触发。
- 完成质量只由命令、文件和结构化 evaluator 判定，不接受模型自评。

## 指标

- 功能：测试分数、任务通过率、被修改文件、最终回复中的验证证据。
- 轨迹：节点访问、模型/工具调用、重复调用提醒、子 Agent 生命周期、能力检索/激活、上下文 apply、进化 mutation 与持久化验证。
- 效率：总模型调用、工具调用、token、墙钟时间；压缩前后估算 token 与裁剪字符数。
- 安全：越界/网络/危险命令拦截，是否泄露 key，是否为了通过单题写死答案。

## 执行顺序与污染控制

先运行核心基线，再运行无进化组，最后运行完整组。进化组会向能力库持久化 artifact，放在最后可避免新 artifact 污染基线。每个 Task 的代码工作区都隔离在 `.egoagent/task_runs/<run>/workspace`，但能力 mutation 单独审计。

## 停止条件

- API 连续认证或网络失败：停止花费并修复连接，不盲重试。
- 相同 Flow 连续两次结构性运行错误：先修 runtime/Flow，再继续矩阵。
- 模型明显循环：重复调用守卫仍无法改变策略时停止该 run，保留失败轨迹。
- 任务错误来自 fixture/evaluator：修复题目并废弃受影响 run，不把它算作模型失败。

## 实际实现

### 产品 Flow

- `product_core_code_agent`：小型、一次性编码任务的低开销默认项。
- `product_adaptive_no_evolution`：保留能力检索、记忆、上下文治理与受限委派，但禁止持久化修改 Identity/Flow。
- `product_adaptive_code_agent`：长程产品 Flow。包含能力发现与激活、持久记忆、工具输出裁剪、被动上下文压缩、周期性上下文精简、重复调用守卫、受成本门控的子 Agent、受治理进化、独立验证、事务化改动、检查点与评审。
- `product_adaptive_pressure_lab`：只用于稳定触发被动压缩的测试 Flow，不作为日常默认项。

三个产品 Flow 都使用 `adaptive_deepseek_coder`。该 Identity 使用 DeepSeek V4 Flash，并把职责分开：Identity 保存长期角色和编码偏好；Ego 保存可继承、可搜索的工具与 Skill；Superego 保存不可由普通任务绕过的进化边界；Flow 决定能力何时运行、如何分支和如何留下证据。

### 本轮修复的运行时缺陷

1. **节点工具白名单先于全局工具预算**：过去全局只保留前 20 个工具，导致 Evolver 节点声明了 `create_skill`，模型提示词里却看不到它。现在先按节点 `tools/hidden_tools` 过滤，再应用全局预算；节点声明的关键工具不会被无关工具挤掉。
2. **验证后的能力热加载**：进化产生的 Skill 必须经过独立验证。验证通过后，主 Agent 会重新索引能力库并从结构化 mutation evidence 激活新能力；失败或只有模型口头声明时不会加载。
3. **检索结果的确定性激活**：Capability Discovery 直接读取 `search_capabilities` 的结构化结果，不再依赖模型把路径复制进 JSON。对语义分数、query coverage、lexical score 都有明显优势的候选，可以确定性激活；模糊结果仍交给模型判断或不激活。
4. **进化结果显式进入主 Agent 上下文**：本轮检索加载与本轮进化加载使用两个独立字段，避免重复 `activate_capability`，也能在轨迹回放中说明工具从哪里来。
5. **子 Agent 成本门控**：模型只能提出候选范围；运行时会实测文件数和字节量。小范围任务即使模型建议委派也会被拒绝，避免“为了多 Agent 而多 Agent”。
6. **Evolver 使用真实轨迹成本**：Conversation Snapshot 可选择只暴露聚合 usage（模型调用、工具调用、输入/输出/cache token、按 Harness 聚合），不暴露消息和工具 payload。Evolver 不再拿单个工具输出长度猜整段 Session 成本。
7. **Skill 专用验证与失败隔离**：可执行 Skill 的验证分支只向模型暴露 `verify_identity_skill`；必须通过正常 Agent 能力激活与代表性 case。验证失败的已写入候选会移动到 Identity 的 `.quarantine`，保留审计但不再参与搜索。

## 实验结果

下表为 DeepSeek V4 Flash 的真实调用。`tokens` 是供应商返回的实际输入加输出 token；不同运行存在缓存差异，所以这里只用于产品诊断，不作统计显著性结论。

| Run | Flow / Task | 结果 | 模型 / 工具调用 | 实际 tokens | 时间 |
|---|---|---:|---:|---:|---:|
| `20260904_010533_long_core_retry` | core / long horizon | 6/6 | 64 / 63 | 746,160 | 175.255s |
| `20260904_012206_long_no_evolution_retry` | no-evolution / long horizon | 6/6 | 62 / 37 | 411,851 | 273.077s |
| `20260904_012802_long_full` | full / long horizon | 6/6 | 66 / 45 | 585,692 | 301.677s |
| `20260904_041746_verified_release_evolution_v3` | full / recurring release | 7/7 | 72 / 33 | 500,189 | 237.505s |
| `20260904_042759_verified_fictional_bundle_evolution_v1` | full / recurring bundle | 7/7 | 81 / 43 | 811,877 | 313.032s |
| `20260904_045142_fictional_bundle_core_baseline_v2` | core / recurring bundle | 7/7 | 43 / 25 | 312,585 | 102.785s |
| `20260904_050353_fresh_session_bundle_skill_reuse_v3` | full / fresh reuse | 1/1 | 8 / 5 | 30,455 | 25.796s |
| `20260904_050720_fresh_bundle_core_baseline` | core / fresh parity #1 | 0/1 | 12 / 14 | 98,534 | 27.075s |
| `20260904_050855_fresh_bundle_core_baseline_rep2` | core / fresh parity #2 | 1/1 | 14 / 16 | 75,406 | 34.557s |
| `20260904_055531_clean_verified_hotload` | full / telemetry evolution + hot-load | 7/7 | 77 / 32 | 559,847 | 260.750s |

### 观察到的高级行为

- **自然进化出现了，但不是逢触发必进化。** 在 recurring bundle 的前五轮中，Agent 每轮直接处理文件。第六轮 cadence 只触发“是否值得进化”的评审；Evolver 自己判断相同契约已反复出现，随后搜索现有能力、调用一次 `create_skill`，生成 `normalize_bundle_json`，第一次验证参数不匹配后根据真实失败证据修正，再次验证通过并 `mark_evolved`。题目没有要求创建 Skill，也没有给出 artifact 名称。
- **克制行为也出现了。** recurring release 的第六轮同样触发进化评审，但 Agent 判断仓库里已有独立、确定性的生成脚本和测试，直接逐文件处理仍很便宜，因此没有制造重复 Skill。重复日志任务也作出了相同拒绝。这说明 cadence 是检查点，不是强制 mutation。
- **跨 Session 搜索与复用已真实跑通。** 新 Session 的第八个 bundle 任务先执行一次 `search_capabilities`，Discovery 直接激活已有 Skill；主 Agent 随后调用 `normalize_bundle_json`，没有再次搜索、激活或创建同名能力，精确 evaluator 通过。
- **进化后的同轮热加载也已真实跑通。** clean telemetry 运行前五轮没有匹配能力；第六轮 Evolver 读取累计轨迹成本后自主选择创建 `normalize_telemetry_event`，调用一次 `verify_identity_skill` 运行两个代表性 case，独立 judge 批准后，主 Flow 在 `activate_evolved_primary` 为主 Agent 再激活一次。主 Agent 在第六轮和第七轮各真实调用一次该 Skill；七个隐藏精确 JSON evaluator 全部通过。
- **上下文压缩和精简是两个独立机制。** long-full 运行中，周期性 Curator 读取多轮 Session 元数据并决定保留/摘要/省略；被动 Compactor 仅在 token 水位越线时运行，将一次工作上下文估算从 24,096 token 压到 14,845，节省 9,251。工具调用前言裁剪单独工作；context-pressure 实测运行以 34,991 个实际 token 通过。
- **持久记忆跨轮次被召回。** long-full 六轮的 recall 命中数依次增长，后续轮次能消费先前决策和验证结果，而不是只依赖当前 prompt。
- **子 Agent 不再被当装饰。** `20260904_034727_measured_scope_gate_v7` 中模型提出委派后，运行时实测候选只有 4 个文件、1,523 bytes，未达到 12 次工具调用或 12,000 context chars 的门槛，因此留在主 Agent 执行并通过。此前大范围隔离用例已记录真实 `subagent_spawned/subagent_completed`，但成本较高，所以产品策略默认保守。

### Parity / Ablation 应如何解读

1. **简单的一次性工作优先 core。** 七轮 bundle 首次学习时，完整 Flow 需要为检索、治理、验证和持久化付出 811,877 token；core 只用 312,585 token 且同样 7/7。高级能力不是免费午餐。
2. **复用轮次开始回收成本。** 新 Session 中，完整 Flow 复用已验证 Skill，用 30,455 token 一次通过。core 两次独立复现实验为 1/2：失败轮用了 98,534 token，并把本应位于 `bundle` 下的字段写到了顶层；另一轮成功但仍用了 75,406 token。样本太小，不能声称统计优势，但足以证明复用链路能降低该实例的步骤、token 和输出方差。
3. **no-evolution 的 bundle 运行不能作纯净消融。** `20260904_044333_fictional_bundle_no_evolution_ablation` 开始前能力库里已经存在上一运行创建的 Skill，因此它证明“禁止继续进化时仍可复用”，不证明“从无能力开始关闭进化”的因果效应；同时该运行期间开发代码有更新，正式对比不采用它。
4. **长任务单次结果有随机性。** long horizon 三组都通过；no-evolution token 最低，core 墙钟更短，full 介于二者。应增加固定温度、多 seed 重复后再做默认策略自动路由。

## 产品建议

- 日常小修复、单文件解释、一次性测试失败：`product_core_code_agent + adaptive_deepseek_coder`。
- 重复格式转换、多轮维护、长上下文或预计会跨 Session 复用：`product_adaptive_code_agent + adaptive_deepseek_coder`。
- 需要记忆/检索/压缩，但组织策略不允许 Agent 写入能力库：`product_adaptive_no_evolution + adaptive_deepseek_coder`。
- 不建议为了展示功能强制创建子 Agent 或 Skill；正确行为包括“判断不值得并拒绝”。

## 诊断运行与剩余边界

- telemetry 验收不是第一次就成功：代理 502、含糊的 `service.id` 契约、Evolver 看不到累计 usage、验证节点选择了 `read_file`、以及清理测试 artifact 后残留空目录，分别导致无效或不完整运行。这些运行没有被算入成功指标；契约歧义被修正，usage 进入结构化快照，Skill 改走专用验证，失败候选增加 quarantine，空测试目录也已清除。最终采用的是 `20260904_055531_clean_verified_hotload`。
- 当前 parity 样本量只适合发现工程问题，不能用于胜率或成本优势宣传。
- 完整 Flow 对小任务的固定开销仍大；下一步应由轻量 Router 根据预估轮数、重复度、上下文压力和权限策略选择 core/no-evolution/full，而不是把 full 设为所有任务的默认值。

## 回归状态

2026-09-04 最新联合回归覆盖 Flow schema、节点注册、能力库、能力创作与验证、失败隔离、聚合 usage、上下文治理、子 Agent 生命周期、Task Bench、轨迹、进化证明、Identity 工具可见性、Session/Project API、检查点恢复、改动 accept/reject/undo 和真实浏览器自动化：`653 passed, 3 skipped`。Workbench 的 TypeScript/Vite 生产构建通过，18 集录制教程共 100 个引导步骤通过静态校验。

## 第二阶段：严格的 Product Campaign

机器可读汇总与所有原始报告位于：

- `experiments/product_code_agent_acceptance/results/CAMPAIGN_REPORT_20260904.json`
- `experiments/product_code_agent_acceptance/results/CAMPAIGN_REPORT_20260904.md`

这一阶段不再用不同任务或不同模型做模糊比较，而是优先采用相同任务、相同 DeepSeek V4 Flash、只切换一个 Flow 机制的 A/B。

### 1. 进化要拆成“学习成本”和“后续收益”

- 无进化 control 在 7 个 Quasar release 上 `7/7`，409,222 actual tokens、32 次工具调用。
- evolver treatment 同样 `7/7`，但学习期用了 1,020,834 tokens、56 次工具调用。第六轮模型自然判断重复契约值得固化，创建 `normalize_quasar_release_v3`；首次验证失败，基于真实失败修复后验证通过，并在同一 Session 热加载。
- 新 Session transfer 中，无已学能力的 control 为 `3/3`、94,087 tokens、14 次工具调用；直接复用 Skill 的 treatment 为 `3/3`、73,511 tokens、3 次工具调用，即总 token `-21.9%`、工具调用 `-78.6%`。

结论不是“进化立刻更便宜”，而是：学习轮次明显更贵；只有可移植 artifact 在后续任务中被真实搜索、激活和调用，才能回收成本。

### 2. 跨全新轨迹持久记忆的纯净消融

`product_cross_session_memory` 第一轮只把随机事实 `PROJECT_NEBULA -> Q7-EMBER-491` 告诉 Agent，明确禁止写项目文件；第二轮使用同一 Workspace、全新 Harness/Session，模型没有前一轮聊天历史。

- `product_adaptive_no_memory`：第一轮通过，第二轮正确承认仓库里没有该值，最终 `1/2`。
- `product_adaptive_code_agent`：第二轮的 `recall` 从 `.egoagent/memory/product_adaptive_code.json` 找到相关记录，精确返回随机值，最终 `2/2`。

同时修复了一个真实缺陷：旧 Memory search 即使 query 与条目零 token overlap，也会因 recency/importance 返回无关记忆。Memory 节点现在支持 `minimum_overlap`、`minimum_relevance`、`minimum_score`；产品 Flow 至少要求一个 lexical overlap。记忆也成为显式 `enable_memory` component input，可做纯净消融，不再是无法关闭的 hardcode。

### 3. Context curator 与 compactor 不是一回事

25 轮噪声 ledger 的最终问题要求精确召回四个 durable 值：

- 无治理：`25/25`，80,657 tokens，其中未缓存输入 44,221。
- 修复重复轨迹事件后重跑的仅被动压缩：`25/25`，58,999 tokens，其中未缓存输入 48,633；只在高水位触发一次，从估算 4,445 压至 576 tokens，四个 durable 值全部保留。此前原始 treatment 也为 `25/25`、61,516 tokens，但轨迹中的 SubFlow 事件被三重记录，因此不再作为机器证明的主证据。

相对未治理 control，总 token `-26.9%`，但本次供应商未缓存输入 `+10.0%`，延迟也更高。结论应限定为：被动压缩可靠控制 working context 并降低本组总 token；DeepSeek prefix-cache 命中存在跨运行方差，不能承诺每次未缓存输入都下降。

另一方面，15 轮中每 3 轮主动 curator 的 treatment 虽然也全对，但 token 从 36,147 增至 52,705，未缓存输入从 893 增至 41,637。原因是频繁重写历史破坏 DeepSeek prefix cache。产品 Flow 因此新增 `curation_minimum_tokens=12000` 和只读 `curation_probe`：达到轮次但上下文仍小时不调用 curator；compactor 仍只由硬水位被动触发。模型生成的压缩计划如果扩大上下文或不足最低节省，也会被拒绝并恢复原 working/audit view。

### 4. 子 Agent 的价值是隔离，不保证省钱

大规模双包修复包含两个互不相交、各约 15 个文件的 Python package 和 12 个测试：

- 关闭 delegation：`12/12`，115,890 tokens，49 次工具，83.642 秒。
- 开启 delegation：`12/12`，真实启动一个 `product_bounded_code_worker`；child 只修改 `slug_codec/`，parent 只修改 `quota_engine/`。共 149,501 tokens、53 次工具、84.319 秒。

主 Agent 输入 token 下降约 7.8%，但加上 child 后总 token 增加 29%。因此阈值被定义成“是否需要上下文隔离”，不宣传为通用成本优化。运行中还发现并修复了一个严重 fallback：模型已经把 parent task 缩成半个任务后，若确定性门控拒绝 delegate，主 Agent 会只做一半。现在拒绝后会显式恢复完整原始 request 和全路径范围。

### 5. 最新完整产品 Flow 的端到端验收

修复嵌套 SubFlow 轨迹事件重复后，`product_adaptive_code_agent@v000023-20260904-094320-31eb7c89` 在 `product_release_guard_long_horizon` 上重新完成 `6/6`：配置解析、密钥脱敏、事件聚合、无关插问、两个独立回归、三种供应商格式。干净轨迹记录 65 次模型调用、45 次工具调用、476,273 actual tokens、394.331 秒，并实际经过：

- capability discovery；
- 5 次被动 compaction check；
- 20 次 repeat guard；
- 20 次 tool-result prune；
- 5 次 recall、6 次 remember；
- 5 次 before checkpoint、6 次 after checkpoint；
- 6 组 edit transaction review；
- 并行 quality/safety review；
- 一次 evolution review（本任务没有满足创建新 artifact 的复用证据，因此正确选择不进化）。

这条 v23 轨迹还验证了所有模型角色均可区分：主 `agent`、`governor`、`searcher`、`quality_reviewer`、`safety_reviewer` 与 `evolver` 都带有各自的 Identity/模型调用归属。包装 Flow、产品 Flow、Component SubFlow 共享根 recorder 时，事件只由最初发生它的 child run 持久化一次，再以不重复写盘的方式转发到根 UI。

动态加载 Skill 直接写文件此前会绕过 IDE 改动事务，本阶段已修复：Skill 调用前后对 Workspace 做受限快照，文本/二进制差异统一进入 change tracker。对应回归覆盖“改动默认生效、逐 hunk accept/reject、accept/reject 后 Ctrl+Z 只撤销审阅决定、删除文件拒绝后恢复、新建文件删除需确认、进程重启后审阅日志仍存在”。

### 6. 仍然保留的负面结论

- 全功能 Flow 不是所有任务的最低成本选择。一轮新的 global Library reuse 复验中，Skill 将工具调用从 15 降到 8，但完整 Flow 的计划与双审查使 token 和延迟高于 Core。小型一次性任务仍应走 `product_core_code_agent`。
- 进化收益不能只报告成功案例；学习期成本、验证失败、修复次数、后续复用次数与 break-even 必须一起展示。
- 当前是工程验收 campaign，虽然所有原始轨迹和供应商 usage 都保存了，但每组重复次数不足以支持统计显著性宣传。

### 7. v24：可达的重复守卫与可恢复 Task

继续审计 v23 轨迹时发现：生产 Flow 虽然每轮都经过 `component_repeat_tool_guard`，但 Agent 节点的隐藏 `reject_identical_tool_call=true` 会在第二次相同调用执行前抢先拦截，而组件要到第 3 次才提醒。因此组件在该 Flow 中实际上不可达，属于重复逻辑互相架空。

`product_adaptive_code_agent@v000024-20260904-105645-4c35ff9d` 关闭该隐藏拦截，把策略归还给 Flow 中可见、可编辑、可回放的组件，并把生产阈值设为 2/3/5；`deepseek_harness_replica` 保持其 3/5/8 策略，也关闭隐藏拦截。故障注入让同一无副作用 `read_file` 连续执行三次，轨迹只在 count=3 产生一次 `loop_guard_reminder`，消息真实进入模型上下文，第四轮改变策略并结束。真实 DeepSeek V4 Flash 回归 `20260904_105818_v24_repeat_guard_regression_r1` 则没有误报，完成 `product_parallel_diagnostics` 的 5/5 检查：14 次模型调用、13 次工具调用、74,892 actual tokens。

同时补齐了 Task Bench 的产品级 checkpoint 恢复：已停止/失败/超时且存在安全 completed checkpoint 的历史运行显示 `↻`。恢复创建新 run、克隆原 workspace、继承已通过的多步骤评分，并从 checkpoint 的 `next_node` 继续，不修改原运行，也不重复执行已完成写入。workspace、Flow 和 Identity revision 不一致会中止恢复；in-flight 副作用默认拒绝；篡改 `run.json` 把 workspace 指向 Task 目录外也会被拒绝。离线集成回归与 repeat-guard 故障注入记录在 `experiments/product_code_agent_acceptance/results/RESILIENCE_JUNIT_20260904.xml`。

随后用 v24 重跑完整六阶段真实任务，结果保存于 `20260904_111926_full_v24_resilience_r1`：`6/6` 步骤通过，64 次模型调用、45 次工具调用、458,743 actual tokens、约 424.982 秒，共执行 588 个 Flow 图步骤。正常任务中 repeat guard 没有误触发；独立的确定性循环故障注入则证明同一工具调用达到阈值时，组件提醒确实进入模型可见上下文。这里应区分“正常运行无误报”和“故障条件可达”，不能把故障注入称为模型自然涌现。

当前机器证明为 `11/11`，见 `experiments/product_code_agent_acceptance/results/PROOF_REPORT_20260904.md`。完整复现命令和前端操作见 `experiments/product_code_agent_acceptance/README.md`。

最终工程级回归保存为 `experiments/product_code_agent_acceptance/results/FULL_SUITE_JUNIT_20260904.xml`：688 个测试通过、3 个可选环境测试跳过、164 个参数化子测试通过。Workbench 的 18 集/100 步录制教程校验、TypeScript、Vite 239 模块生产构建及 Void 扩展同步也全部通过。回归中还发现本机 Chrome/Edge 152 已更适合 browser-level CDP WebSocket；浏览器工具迁移为 `DevToolsActivePort` 自动端口 + flattened Target session 后，导航、观察、输入、点击、对话框、下载、截图和关闭的真实浏览器集成测试通过。没有为了测试通过而加入 `--no-sandbox` 或关闭 Chromium 安全边界。
