# EgoAgent 高新颖度科研方向审计

日期：2026-08-13  
检索截止：2026-08-13  
目标会议：以 NeurIPS 主会的方法、评测与系统标准审视，而不是以产品功能丰富度代替科研贡献。

## 0. 结论先行

任何一次文献检索都不能“确保”未来投稿时仍然绝对新颖，也不能确保录取。可以做到的是：

1. 把主张缩窄到可证伪的算法差异；
2. 对 2024--2026 年最接近的工作逐项做碰撞审计；
3. 在花费大规模 API 预算前设置明确的 novelty gate 和 empirical kill criteria；
4. 让贡献依赖 EgoAgent 已经具有的独特实验能力，而不是临时包装一个通用 agent loop。

本次审计后的首选方向是：

> **EvoCert：面向外部化自进化 Agent 的因果演化证书**  
> 给定一次从 Agent 状态 `S` 到 `S'` 的持久变更，不只问 `S'` 分数是否更高，而是通过可控干预证明：哪一组 Knowledge、Skill、Identity、child Agent、Harness/DAG 变更对 held-out 提升是必要或充分的；它们是否真的在执行中被使用；是否能移植到干净 Agent；是否破坏受保护行为；以及用于接纳变更的 verifier 是否足以识别语义上危险的 mutants。

这里最关键的变化是：**研究对象不再是“怎样产生一个更好的 DAG”，而是“什么证据足以相信一次自进化真的有效、可归因、可移植且没有越权”**。

若只是把现有模块串起来，创新性仍然不够。要达到主会级别，至少需要以下三项同时成立：

- 一个跨多类持久 artifact 的干预语义与统计认证问题；
- 一个以真实 self-evolution episode 为单位、同时测量真实提升和错误接纳的 benchmark；
- 一个比全量 factorial replay 更省预算、且能控制错误接纳概率的 interaction-aware 认证算法。

第二候选方向是 **Evolution Monoculture / Artifact Contagion**：研究同一 skill、knowledge 或 harness patch 在 agent 群体传播后形成相关失败和伪独立证据的问题。它更适合安全会议，也可作为 EvoCert 的一个强攻击场景，但不建议与主线并列为两个同等大的故事。

## 1. EgoAgent 真正可用于研究的资产

EgoAgent 现在的科研价值不在于“节点很多”，而在于它能把其他系统中混在一段 prompt 或源码里的状态拆成可以分别替换、运行和回滚的对象。

| 资产 | 当前能力 | 对实验的意义 |
|---|---|---|
| Identity / Ego / Superego | 行为提示、工具、skill、knowledge、权限和 hooks 分层 | 可把任务能力与长期行为/权限约束作为两类不同结果变量 |
| Typed EgoIR / DAG | 有显式节点、边、端口、Identity binding、检查和 revision | 可以做节点、边、绑定与参数级 intervention，而不是字符串 prompt ablation |
| 多种持久 artifact | Knowledge、Skill、Identity、child Agent、Harness、environment、model route、memory policy | 可以研究跨 representation 的因果作用和交互，而不局限于 memory/experience |
| 事务安装与回滚 | capability pack 与 Harness mutation 均有 transaction、revision conflict 和 rollback | 可以反复构造干净反事实状态，避免手工恢复造成污染 |
| Proof-carrying evolution | train/validation/heldout/regression、预算匹配、evidence lineage、trusted anchor | 已有接纳框架可升级为真正的因果证书，而非从零搭平台 |
| Durable trace / checkpoint | 节点事件、工具、消息、workspace transaction、恢复 | 可确认 artifact 是否被路由、读取、执行，以及失败从哪里传播 |
| Package / signature / permissions | 签名包、资源边界、mutation 权限、secret 隔离 | 可研究传播、撤销、授权连续性和 fleet-level blast radius |
| Studio | DAG 实时节点输入输出、变更时间线、Task Bench、演化看板 | 可把 counterfactual runs 和 causal certificate 做成可检查实验工具 |

这些能力使 EgoAgent 适合做“外部化 Agent 状态的实验操作系统”。论文不应声称 Identity、DAG 或 rollback 本身首次出现；应声称它们让一种此前难以做的受控实验和认证问题成为可能。

## 2. 文献审计方法

本轮不是通过“搜索不到同名词”判断新颖性，而是按功能等价关系查找最近邻：

1. **对象重合**：是否也修改 prompt、memory、skill、tool、workflow 或 harness；
2. **学习信号重合**：是否也使用 held-out、counterfactual replay、causal effect、cost 或安全 verifier；
3. **输出重合**：是否也给出最小改动、归因、证书、rollback 或 contract；
4. **评测重合**：是否也隔离 base-model 能力、搜索预算和 benchmark leakage；
5. **系统重合**：是否也支持 provenance、mutable/immutable boundary 和多 Agent 传播。

文献以论文主页、OpenReview、作者项目与官方 benchmark 为主。许多 2026 年工作仍是预印本；“已有直接先例”不因其尚未正式发表而可以忽略，因为审稿人同样能看到它们。

## 3. 最近邻工作与被占据的主张

### 3.1 自动设计或改写 workflow/harness 已经拥挤

| 工作 | 已覆盖内容 | EgoAgent 不能再作为主贡献声称的内容 |
|---|---|---|
| AFlow (`2410.10762`) | 以代码表示 workflow，用 MCTS 优化 | 自动搜索 Agent workflow |
| ADAS (`2408.08435`) | Meta-Agent 编写新 agent 并维护 archive | Agent 创建 Agent |
| AgentSquare (`2410.06153`) | Planning/Reasoning/Tool/Memory 模块重组与演化 | 模块化自进化本身 |
| GPTSwarm | 图节点 prompt 和边优化 | DAG 可优化 |
| MOSS / DGM / MGM | source-level 自修改、谱系与继承 | Agent 改自身代码或跨代继承 |
| Self-Harness (`2606.09498`) | weakness mining、failure-linked minimal proposal、regression 与 held-out | “最小、验证后才接纳的 harness edit” |
| HSI (`2608.08466`) | task harness、evolver、meta-evolver、frozen outer anchor | 分层 harness 自进化 |
| CHILL-Harness (`2607.25825`) | counterfactual intervention effect、success preservation、advantage gate | 用反事实决定是否改 harness |
| AgentEvo | performance/cost Pareto、结构偏置、prune/refine/crossover | 性能与复杂度联合优化 |
| AHE (`2604.25850`) | component/experience/decision observability；每次 edit 配 falsifiable prediction | “可观察、可回滚、带预测的 harness evolution” |
| Evo-Bench (`2608.09096`) | 隔离模型强度、task overfit 与长程 harness evolution | 首个 harness-evolution benchmark |

结论：继续扩展“模型自动加删 DAG 节点”只能形成产品能力，不足以形成新论文主线。

### 3.2 Skill 生命周期与跨表示 placement 已经被快速占据

Dynamic Agent Skills (`2607.10113`) 审计 124 篇工作，把 skill 定义为可能是代码、自然语言、`SKILL.md`、workflow graph 或 adapter 的外部化程序 artifact，并明确了 evidence acquisition、proposal、verification/admission、storage、retrieval/composition、maintenance、distillation/portability、governance 八阶段，以及 Add/Refine/Merge/Split/Prune/Distill/Abstract/Compose/Rewrite/Rerank 十类操作。

SLIM (`2605.10923`) 已把 active skill set 当成动态优化变量，包含 retain、retire 与 expand。SIGIL (`2607.27309`) 已覆盖 skill 到 typed harness 的编译。EvolveMem 与 COVE 已分别研究 memory architecture evolution 与 memory/parameter coordination。

因此，先前提出的 Reversible Capability Placement 若只包含 Knowledge/Skill/Harness 的 promotion、demotion、split、merge、retire，已经不再够新。它可以成为 EvoCert 的实验对象，但不应是主贡献。

### 3.3 “改完以后分数更高”并不能证明发生了可信自进化

这一部分恰好构成新方向的动机：

- Faithful Self-Evolvers (`2601.22436`, ICML 2026) 对 raw 与 condensed experience 做受控因果干预，发现 agent 经常忽略或误用 condensed experience；表面上的 self-evolution gain 不代表行为真的依赖被保存的经验。
- EvoAgentBench (`2607.05202`) 用 Ability Graph 测量程序性经验的 encoding、routing 与 uptake；curated ability 可迁移，但没有自动方法在所有设置中都保持正收益。
- Rethinking Harness Evolution (`2607.12227`) 指出 harness search 应与相同反馈和推理预算下的 test-time scaling 比较，并必须在 held-out tasks 上测泛化；现有方法并不稳定优于简单搜索。
- Self-Authored Verification (`2607.24300`) 证明 self-written verifier 与 sealed deployment evaluation 间会产生 gap；SEAL 要求至少一个 agent 无法控制的接纳信号。
- PoisonedEvolution (`2608.05563`) 证明不可信 trajectory 可以被提升为持久 skill；“反复出现”和“看起来有因果用处”本身也能被攻击。
- SkillMutator (`2606.14154`) 表明 `SKILL.md` 与代码之间存在跨模态攻击面，通用 scanner 对此很弱。
- ActBench (`2608.09476`) 表明完成正常任务和执行安全可以同时分离，必须从 trajectory 而非最终回答评估行为风险。

现有工作分别证明了 experience faithfulness、skill uptake、held-out fairness、sealed verifier、poisoning 和行为安全的问题，但尚未把一次**跨多类持久 artifact 的 Agent 状态迁移**作为统一的、可干预的认证对象。

### 3.4 因果 replay 和 failure attribution 也不是空白

| 工作 | 已有能力 | 与 EvoCert 的边界 |
|---|---|---|
| CausalFlow (`2605.25338`) | 对失败 trace 的 step 做 counterfactual intervention，找 minimal repair | 解释一次执行为什么失败，不认证跨任务持久状态更新 |
| Causal Agent Replay (`2606.08275`) | 对 agent step 做 `do` 干预，Monte-Carlo Shapley 处理步骤交互 | 归因 trajectory step，不处理 Knowledge/Skill/Identity/Harness 版本迁移 |
| Faithful Self-Evolvers | raw/condensed experience 的 causal dependence | 对象主要是输入经验，不是 typed multi-artifact state transition |
| CHILL-Harness | harness edit 的 causal effect | 单一 harness 搜索空间，不含 artifact graft、跨 Identity 移植和 verifier adequacy |
| CausalFlow / Model-or-Harness taxonomy | failure localization 与 repair assignment | 定位故障，不给 persistent promotion certificate |

EvoCert 不能声称“首次把 causality 用于 Agent”；真正可辩护的差异必须是 **跨 artifact、跨 episode、面向 promotion decision、带保护行为与 verifier mutation adequacy 的因果认证**。

### 3.5 Contract、权限和 provenance 也已有直接工作

- Agent Behavioral Contracts (`2602.22302`) 定义 Preconditions、Invariants、Governance、Recovery，并给出概率漂移界。
- PEA (`2604.23646`) 分离 Policy、Execution、Authorization，用 capability token 和 intent lineage 保护 goal integrity。
- Earned Authority (`2607.23586`) 研究 evolving agent 的授权连续性和 immutable effect ceiling。
- Proof of Execution (`2607.05397`) 绑定 contract、causal event stream 与 replay context。
- ProvenanceGuard (`2607.01236`) 用 provenance 判断工具调用是否由用户意图支持。
- Governed Shared Memory (`2606.24535`) 已定义 fleet memory 的 leakage、staleness、contradiction 与 provenance collapse。

因此 Identity/Superego 的“不可越权”适合作为 EvoCert 的受保护结果轴和 trusted boundary，不适合单独声称为第一种 agent contract。

## 4. 候选方向评分

评分是当前文献截止下的主观研究决策，不是录取概率。

| 方向 | 与已有工作的距离 | EgoAgent 独特适配 | 真实痛点 | 可做真实实验 | 主会潜力 | 决策 |
|---|---:|---:|---:|---:|---:|---|
| EvoCert：多 artifact 因果演化证书 | 8.0/10 | 9.5 | 9.0 | 8.0 | **8.2** | 主线 |
| Artifact Contagion：相关证据与组织级传播 | 7.3 | 9.0 | 9.0 | 7.0 | **7.6** | 强副线/安全投稿 |
| Identity × Harness 组合泛化 | 6.7 | 9.0 | 7.0 | 6.0 | **6.9** | 备选分析论文 |
| Result-only subagent 信息边界学习 | 5.3 | 8.5 | 8.0 | 8.0 | **6.3** | EvoCert 应用/产品功能 |
| 弱模型可编辑 EgoIR 表示 | 5.1 | 8.0 | 7.0 | 8.0 | **6.1** | benchmark/系统副线 |
| Reversible Capability Placement | 4.2 | 8.5 | 7.5 | 7.0 | **5.5** | 不再作为主线 |
| 自动加删 DAG / prompt 优化 | 2.0 | 7.0 | 6.0 | 9.0 | **4.0** | 放弃论文主张 |

## 5. 主方向：EvoCert

### 5.1 要解决的问题

一个 self-evolving agent 在任务序列上从状态 `S` 变为 `S'`。状态可以写为：

```text
S = (M, I, K, P, A, H, E, R)
```

其中：

- `M`：base model / route；
- `I`：Identity、Ego、Superego 与权限；
- `K`：Knowledge / memory policy；
- `P`：可执行或声明式 Skills；
- `A`：child Agents 与通信边界；
- `H`：Harness / EgoIR 控制流；
- `E`：environment、tools 与依赖；
- `R`：runtime / retrieval / context policy。

一次更新 `Delta` 往往同时改变多个分量。仅观察 `U(S') > U(S)` 无法排除：

1. 增益来自更多采样或更大 token budget；
2. 更新 artifact 根本没有被路由或执行；
3. base model 本来就能解决 held-out task；
4. 只在 verifier 可见任务上过拟合；
5. 真正有效的是多个 artifact 的交互，而非 evolver 声称的那个；
6. target utility 提高但 unrelated behavior、policy compliance 或权限边界下降；
7. self-authored verifier 太弱，危险变体也会通过；
8. 多条“独立证据”其实来自同一条污染 lineage。

EvoCert 的目标不是保证 Agent 在开放世界永不失败，而是回答一个更窄、可验证的问题：

> 在声明的任务分布、保护分布、预算和威胁模型下，我们是否有足够证据接纳这次特定的持久状态迁移？

### 5.2 因果 estimands

把更新产生的原子 artifact 集合记为 `D = {d1, ..., dm}`，对任意 coalition `Z subseteq D`，`S[Z]` 表示只把 `Z` graft 到干净 incumbent 上的状态。对任务 `t` 和随机性 `omega`，观测：

```text
Y_task(S[Z], t, omega)       # task utility / correctness
Y_protected(S[Z], t, omega)  # contract, identity, permission, safety
C(S[Z], t, omega)            # token, latency, dollars, tool calls
A_i(S[Z], t, omega)          # artifact i 是否被路由、读取、执行
```

至少估计以下量：

1. **总效果**：`E[Y_task(S[D]) - Y_task(S[empty])]`；
2. **必要性**：从完整更新中 knockout `di` 后的性能下降；
3. **充分性/可移植性**：把 `di` 或最小 coalition graft 到新鲜 Agent 后的性能提升；
4. **uptake**：条件于 artifact 被实际激活时的效果，以及“安装但未使用”的比例；
5. **交互**：单个 artifact 无效、组合后有效的 synergy，或单独安全、组合后危险的 antagonism；
6. **非干扰**：保护任务上的最大允许退化和新可达 effect；
7. **verifier adequacy**：保护 suite 杀死语义 mutants 的比例和最坏存活 mutant；
8. **lineage-adjusted evidence**：按共同 origin 聚类，而不是把复制的观察当独立样本。

这里的“充分”只相对于声明的 task distribution；论文必须避免把有限 benchmark 证书写成开放世界保证。

### 5.3 证书结构

建议定义 `ego.evolution-certificate.v1`：

```json
{
  "transition": {"from_revision": "...", "to_revision": "..."},
  "atomic_artifacts": ["knowledge:k1", "skill:s1", "harness:h1"],
  "declared_scope": {"target_distribution": [], "protected_distribution": []},
  "budget_match": {"tokens": 0, "calls": 0, "wall_time": 0},
  "activation_evidence": [],
  "causal_effects": {
    "total": {}, "necessity": {}, "sufficiency": {}, "interactions": {}
  },
  "minimal_sufficient_coalitions": [],
  "portability": {"fresh_identity": {}, "alternate_harness": {}, "alternate_model": {}},
  "noninterference": {"protected_delta": {}, "authority_delta": {}},
  "verifier_mutation_score": {},
  "lineage_dag": {},
  "statistical_decision": {"alpha": 0.05, "promote": false, "reasons": []},
  "replay": {"task_snapshots": [], "seeds": [], "transaction_ids": []},
  "rollback": {"supported": true, "transaction_ids": []}
}
```

证书必须能被第三方 runner 重放；模型对自己为何提升的自然语言解释只能作为 hypothesis，不能作为 evidence。

### 5.4 Semantic evolution mutants

普通 AST mutation 不足以检验 Agent 更新。需要基于 EgoAgent typed artifact 定义语义 mutation operators：

#### Knowledge / memory

- 删除关键事实但保留流畅描述；
- 替换 entity、version、单位或适用范围；
- 把过期事实提升为高优先级；
- 将一条 lineage 复制成多个伪独立记录。

#### Skill

- 扩大 trigger scope；
- 让文档与代码行为不一致；
- 绕过输出校验或权限请求；
- 保留正常 utility，只在稀有条件触发错误行为；
- 替换依赖版本或环境假设。

#### Identity / Superego

- 弱化 protected instruction；
- 把局部 task override 变成全局偏好；
- 悄悄扩大允许工具或可访问路径；
- 改变 tool-result 与用户指令冲突时的优先级。

#### Child Agent / communication

- 从 result-only 变成返回完整污染 trace；
- 丢失 source citation；
- 扩大 child 的工具和 workspace 权限；
- 让多个 child 的“独立”证据共享同一 origin。

#### Harness / DAG

- bypass Human Approval 或 Tool Review；
- 交换分支条件、删除 retry bound、扩大 loop budget；
- 在 Join 时丢弃 dissenting evidence；
- 把 checkpoint 放到 effect 之后；
- 修改 Identity binding；
- 添加与 task 成功无关但能污染 context 的节点。

一个 admission suite 若无法杀死这些与声明风险相关的 mutants，就不应签发证书。这个 evolution mutation score 是对 **接纳证据的辨别力** 评分，不是把 mutation 用作另一个搜索器。

### 5.5 Interaction-aware、预算受限的认证算法

对 `m` 个原子变更运行全部 `2^m` coalitions 太贵。需要成为论文算法的部分是一个自适应实验设计：

1. 先运行 incumbent、full update、no-op matched retry；
2. 使用 trace activation 排除从未进入因果路径的 artifact，但仍记录“unused install”；
3. 对每个 artifact 做 leave-one-out knockout；
4. 若 full 有效但所有单体 knockout 都不显著，搜索二阶 interaction；
5. 用层级稀疏假设或 group testing 找 minimal sufficient coalition；
6. 对最有希望与最危险的 coalition 自适应增加 paired seeds；
7. 在独立 held-out 和 protected tasks 上用单侧置信界接纳；
8. 对所有接纳相关的多重比较控制 family-wise false-promotion rate；
9. 未满足 power 时输出 `abstain / insufficient evidence`，而不是强制 accept/reject。

一个可审稿的决策规则示例：

```text
promote iff
  LCB(target_gain) >= epsilon
  and LCB(portable_gain) >= epsilon_transfer
  and UCB(protected_regression) <= tau
  and LCB(relevant_mutation_score) >= mu
  and lineage_gate == pass
  and authority_ceiling_preserved
```

为了成为 NeurIPS 方法而不仅是工程 checklist，应给出：

- 在明确随机化与独立性假设下，错误接纳概率的有限样本界；
- 自适应 coalition selection 后仍有效的 sequential test 或 sample-splitting 方案；
- 稀疏交互假设下，相比 full factorial 的 intervention complexity；
- 假设失效时的保守退化与 `abstain` 行为。

### 5.6 与最近邻工作的精确 contribution delta

| 最近邻 | 它回答什么 | EvoCert 新回答什么 |
|---|---|---|
| Faithful Self-Evolvers | agent 是否依赖 raw/condensed experience | 一次 typed multi-artifact 状态更新中，哪个 artifact coalition 造成跨任务提升并满足保护条件 |
| EvoAgentBench | ability 是否被编码、路由、吸收和迁移 | 对具体更新签发可重放的 causal promotion certificate，并评估 false promotion |
| CAR / CausalFlow | 哪个执行 step 造成一次失败 | 哪个持久 artifact/version 造成未来 episode 的收益或伤害 |
| CHILL-Harness | 哪个 harness intervention 值得应用 | Knowledge/Skill/Identity/child/Harness 的交互、graft、noninterference 和 verifier adequacy |
| SEAL | sealed accept/reject 防止 self-verifier gaming | sealed signal 之外，证明 artifact uptake、必要/充分、最小 coalition 与安全 mutant 检出能力 |
| ABC / PEA | 运行时 contract 与 authority ceiling | update 的能力提升是否真实、可移植且没有破坏这些 contract |
| PoisonedEvolution / SkillMutator | 如何攻击 skill promotion 或 skill package | admission evidence 是否能识别危险 mutants；推广到所有外部化 artifact |
| Dynamic Skill Lifecycle | skill library 如何创建、维护和治理 | 对一次 lifecycle transition 的因果与统计证据标准 |

### 5.7 真实 benchmark 组合

不建议再完全手写一个合成 benchmark。更可靠的设计是把公开任务的真实 oracle 与少量必要的新 evolution metadata 组合起来。

#### A. 能力获得与迁移

- **EvoAgentBench**：528/267 train/test，四个 agentic domain，并给出 Ability Graph。适合产生有真实程序重叠的 source/target episode。
- **ContinualSkillBench / SkillEvolBench / Skill-Usage**：有顺序、retrieval、skill uptake 或真实 skill pool，适合测 unused skill、negative transfer 与 weak-model fragmentation。
- **Harness-Bench**：106 个离线、可执行、oracle-checkable 任务，记录 trace、usage 与 validator，适合在相同 environment 下比较 typed artifact changes。

#### B. 真实工具与 policy compliance

- **tau-bench**：数据库最终状态和 domain policy，可构造 target success 与 policy-preservation 双轴。
- **AgentDojo**：97 个正常任务、629 个 security cases，适合 protected distribution 与 indirect injection。
- **ActBench**：正常 utility 与 trajectory-level harmful behavior 同时测量，可作为新的 external validation。

#### C. 真实 coding agent

- **SWE-bench Verified**：只取小型、可本机或单容器执行的 issue，验证 artifact 对真实 repo repair 的 transfer；最终论文结果需在官方容器复核。
- **Terminal-Bench 2.x**：只在第二阶段选取小 subset；该机不适合并行缓存大量镜像。

#### D. Mutant 来源

- 使用 SkillMutator / SkillTrojan 的公开攻击类别做 skill-level 外部验证；
- 根据 AgentDojo 的 tool/injection threat model 构造 Identity/Harness mutation；
- 由人类作者预注册一部分 mutants，另一部分由与被测 evolver 不同的 red-team model 生成；
- mutation generator 不得看到 sealed acceptance tasks。

#### E. Evolution episode 单位

每个 episode 至少包含：

1. incumbent state；
2. source tasks 与 trajectories；
3. evolver 提议并实际安装的 update bundle；
4. validation、held-out、protected、deployment-shift splits；
5. artifact-level activation trace；
6. 可重放 environment snapshot；
7. benign / ineffective / overfit / poisoned / interaction-only 的隐藏标签。

论文主要指标不应是“我们的 Agent 最终得分最高”，而应包括：

- false promotion rate；
- false rejection rate；
- causal localization / minimal-coalition accuracy；
- target gain 与 protected regression；
- unused artifact admission；
- mutation score 与最坏 surviving mutant；
- cross-model、cross-Identity、cross-Harness portability；
- intervention count、tokens、latency 和美元成本；
- certificate calibration / coverage；
- rollback 后恢复时间和状态完整性。

### 5.8 Baselines

至少比较：

1. accept all successful updates；
2. before/after validation score；
3. validation + held-out；
4. budget-matched held-out（Rethinking Harness Evolution 风格）；
5. SEAL-style sealed binary gate；
6. lineage + trusted anchor gate（当前 EgoAgent）；
7. single-artifact leave-one-out；
8. full factorial oracle（只在小 artifact bundle 上运行）；
9. EvoCert without mutation testing；
10. EvoCert without interaction search；
11. EvoCert without protected distribution；
12. EvoCert with self-authored vs exogenous mutants/verifiers。

若主方法只比 `validation + held-out` 略好，却没有显著降低 poisoned/overfit update 的错误接纳，就没有足够论文价值。

### 5.9 核心假设

- **H1 因果真实性**：同样 target gain 下，EvoCert 比 held-out-only 与 SEAL-style gate 更少接纳未被使用、非必要或不可移植的 update。
- **H2 交互**：真实 update 中存在足够比例的跨 artifact synergy，使 single-layer attribution 系统性误判，而 adaptive coalition search 能接近 factorial oracle。
- **H3 非干扰**：加入 protected distribution 与 semantic mutants 显著降低 Identity/权限/policy regression，且 utility 损失可控。
- **H4 证据质量**：lineage-aware 聚类比简单 observation count 更能抵抗 trajectory poisoning 和复制传播。
- **H5 预算**：adaptive certification 用显著少于 `2^m` 的 runs 达到近似 localization 和 promotion accuracy。
- **H6 弱模型**：弱 evolver 可以负责 proposal，但 typed interventions 与外部 verifier 能让 promotion reliability 对 proposer model 规模不那么敏感。

### 5.10 必须预注册的 kill criteria

以下任一出现，应停止把 EvoCert 当主线，而不是继续加模型刷数字：

1. 在至少 50 个真实 evolution episodes 中，跨 artifact interaction 稀少到 single-artifact ablation 已足够；
2. `held-out + sealed verifier` 已达到与 EvoCert 无显著差异的错误接纳率；
3. semantic mutation score 与真实 hidden regression/attack success 不相关；
4. certificate 所需额外成本高于 update 带来的长期收益，且 adaptive design 无法降低；
5. 结果只在 EgoAgent 自建任务成立，在 EvoAgentBench/Harness-Bench/AgentDojo 上不迁移；
6. 只在一个模型家族成立；
7. 主要提升来自更大 inference budget，而非 artifact state；
8. 文献中出现直接覆盖“multi-artifact causal promotion certificate + mutation adequacy + noninterference”的新工作。

## 6. 第二方向：Evolution Monoculture 与 Artifact Contagion

### 6.1 问题

当一个高分 skill 或 harness patch 被复制给多个 Agent 后，多个 Agent 的成功或失败并不独立。若接纳系统只统计“有三个 Agent 都观察到同一规律”，就可能把共同源头产生的三个相关 observation 错当成三条独立证据。

这会导致：

- 一个 poisoned trajectory 通过 skill 传播变成组织级 trusted instruction；
- 一个有 bug 的 artifact 在不同 Identity 中形成相关失败；
- 多数投票失效，因为 voter 共享同一个 ancestor；
- 更新后的 verifier 和被测 artifact 共享训练/提示来源，产生 correlated blind spot；
- 撤销单个安装并不能识别全部 clone 和 derivative。

### 6.2 可研究的方法

- 用 DAG 表示 `trajectory -> summary -> skill -> clone -> composite harness -> agent run -> evidence` 的 lineage；
- 定义 lineage-adjusted effective sample size，而不是按记录数计票；
- 估计 artifact 的 fleet-level causal blast radius；
- 对 clone/derivative 做 transitive quarantine 和 signed revocation；
- 设计 heterogeneous sentinel agents，专门打破共同模型/共同 harness 的 correlated failure；
- 比较 naive majority、source-counting、Bayesian trust、lineage-cluster bootstrap 与 causal certificate。

### 6.3 最近邻与剩余空隙

- PoisonedEvolution 研究 trajectory 如何污染 skill promotion；
- SkillTrojan / SkillMutator 研究恶意 skill 与跨模态攻击；
- SkillClone 已研究公开 skill 的 clone 与传播；
- Governed Shared Memory 已研究 provenance collapse；
- Group-Evolving Agents / MGM 已使用 agent lineage 做搜索与继承。

剩余空隙不是“技能会传播”，而是 **传播使演化证据相关，导致接纳统计量失真；如何用 causal lineage 修正证据权重并控制 fleet-level risk**。这可以成为 EvoCert 的 attack/defense section，也可以独立面向 USENIX Security、CCS 或 NDSS。

## 7. 第三方向：Identity × Harness 的组合泛化

EgoAgent 的 Identity 与 Harness 分离是有研究价值的，但必须从设计理念转为可测问题：

> 在只观察部分 `Identity x Harness x TaskFamily` 组合后，能否预测和构造未见组合，使 task capability 可迁移，同时 Identity 的受保护行为保持不变？

可测量：

- 同一 Harness 换 Identity 的 performance/behavior interaction；
- 同一 Identity 换 Harness 后人格、目标和权限是否保持；
- skill 是否依赖某个 Identity 的措辞或某个 Harness 的隐式 context；
- 组合效应能否由低阶主效应解释，还是存在强 non-separable interaction；
- 用少量矩阵观测能否选择未运行过的组合。

风险是 persona、behavioral contract、modular workflow 与 compositional generalization 已有大量文献；若没有公开 benchmark、清楚的 factorization 方法和显著 unseen-combination 结果，容易被评为系统分析而非新方法。建议把它作为 EvoCert 的 portability 轴，而不是目前单独押注。

## 8. 明确不建议继续作为论文主线的方向

1. **“Agent 能自己创建 Agent / 修改 DAG”**：ADAS、MOSS、DGM、HSI 等已覆盖。
2. **“自动找到最好的 DAG”**：AFlow、GPTSwarm、AgentSquare、MermaidFlow 等已覆盖。
3. **“选择 Knowledge、Skill、Harness 中最小的一层”**：Self-Harness、CHILL 与动态 skill lifecycle 让这个 claim 过于接近现有工作。
4. **“skill 会增删、合并、拆分、退休”**：动态 skill survey 与 SLIM 已明确覆盖。
5. **“Identity 不应漂移”**：ABC、PEA、Earned Authority、persona-invariant safety 已覆盖相邻问题。
6. **“subagent 只返回结果节省 token”**：context isolation、context folding、focus session 与 delegation 研究很多，适合产品优化。
7. **“更简单的 DAG 表示让 8B 模型会编辑”**：有 WorFBench、MermaidFlow、SEW representation schema、Harness Handbook 和 graph-JSON 工作；除非形成系统的 representation-learning 研究，否则不够主会级。

## 9. 最小可行研究路线

### Phase 0：零 API / 确定性实现

1. 定义 `evolution-certificate.v1` schema；
2. 把 update transaction 拆成 typed atomic artifacts；
3. 实现 clone、knockout、graft、swap、rollback；
4. 实现 activation extraction 和 lineage DAG；
5. 为五类 artifact 各实现 4--6 个 semantic mutants；
6. 用 deterministic fixtures 验证证书逻辑、conflict detection 与 false-promotion accounting。

通过条件：所有 counterfactual state 可由 revision + transaction 重建，且全量 factorial oracle 在小例子上可重复。

### Phase 1：低成本真实 pilot

建议 50 个 episode：

- 20 个 EvoAgentBench ability-transfer pairs；
- 15 个 Harness-Bench tasks/families；
- 10 个 AgentDojo / tau-bench protected episodes；
- 5 个小型 SWE-bench Verified issue。

每个 episode 首先限制 `m <= 5`，使 factorial oracle 最多 32 个 coalition，可用于验证 adaptive estimator。使用至少两个模型家族，弱模型负责 proposal，另一个模型或 deterministic oracle 负责部分 red-team/verifier。

Phase 1 只回答三件事：

1. interaction 是否真实存在且比例足够；
2. EvoCert 是否比 held-out + sealed gate 少错误接纳；
3. adaptive 方法是否显著节省 replay。

只有三项都成立才进入规模实验。

### Phase 2：论文规模

- 150--300 个真实 episode；
- 至少 3 个模型家族、3 seeds；
- 真实 benign、ineffective、overfit、poisoned、interaction-only updates；
- pre-registered thresholds 和 split；
- 报告 paired confidence intervals、effect sizes、calibration 与所有负结果；
- 官方容器复核 coding/terminal subset；
- 对 mutation generator、evolver、verifier 和 deployment judge 做模型家族隔离。

### Phase 3：Studio 科研工具

在 Studio 中把一次证书显示为：

```text
source evidence
   -> proposed artifact bundle
   -> activation paths
   -> knockout / graft counterfactual branches
   -> target & protected outcomes
   -> surviving mutants
   -> promote / abstain / reject
```

用户应能点击任一 artifact 看：原版本、新版本、被哪些 node 使用、哪次 intervention 改变了结果、证书置信区间、残余风险和 rollback transaction。UI 是可复现实验的载体，不应写成论文核心算法贡献。

## 10. 当前机器与实验预算

此前真实 V4 pilot 的实测均值约为每 cell 40,552 tokens、20 秒 provider runtime。按这个量级：

- 50 episode、平均 12 个 adaptive cells、3 seeds 约为 24.3M tokens；
- 这是方法验证可接受的量级，但 full factorial 在 `m` 增大后会指数爆炸；
- 当前机器约 12 logical CPUs、64 GB RAM、622 GB C 盘空闲，适合一次运行一个 Docker evaluator；
- 不适合并行铺开大量 SWE-bench / Terminal-Bench 镜像；
- 现阶段真正的瓶颈是实验有效性和 API 预算，而非内存。

在 Phase 0 与 50-episode novelty pilot 通过前，不应启动 150--300 episode 的规模运行。

## 11. 论文可辩护的主张模板

如果实验成功，摘要级主张应类似：

> We introduce causal evolution certification, a problem setting for deciding whether a persistent, multi-artifact update to an externalized language-agent state should be promoted. Unlike before/after and held-out evaluation, EvoCert uses typed knockout, grafting, interaction search, protected-distribution testing, semantic evolution mutants, and lineage-aware evidence to certify that an update is causally used, sufficient to transfer, and non-regressive within a declared scope. We release real evolution episodes spanning ability transfer, executable workflows, tool-policy compliance, and adversarial agent tasks.

不能写：

- “first self-evolving agent”；
- “first agent that changes its DAG”；
- “guarantees safe AGI self-improvement”；
- “proves open-world safety”；
- “all improvements are causal”而没有 randomized intervention、置信界和明确 scope；
- 用 deterministic fixtures 冒充真实 LLM 结果。

## 12. 最终 go / no-go 决策

**GO：** 先实现 EvoCert 的确定性 counterfactual substrate 和 50-episode novelty pilot。  
**NO-GO：** 继续扩大此前 minimal-layer / RCP 实验，或继续以 DAG editing 本身为主贡献。  
**CONDITIONAL GO：** Artifact Contagion 作为 EvoCert 的强 adversarial section；若 fleet-level 相关证据效应非常大，可再拆成安全论文。  
**BACKUP：** Identity × Harness compositionality 只在 pilot 显示强、可预测的非分离交互时升级为独立方向。

## 参考文献与官方资源

- [A Survey of Self-Evolving Agents](https://arxiv.org/abs/2507.21046)
- [Large Language Model Agents Are Not Always Faithful Self-Evolvers](https://arxiv.org/abs/2601.22436)
- [EvoAgentBench](https://arxiv.org/abs/2607.05202)
- [Dynamic Agent Skills](https://arxiv.org/abs/2607.10113)
- [Rethinking the Evaluation of Harness Evolution](https://arxiv.org/abs/2607.12227)
- [Evo-Bench](https://arxiv.org/abs/2608.09096)
- [Self-Authored Verification Is Unreliable](https://arxiv.org/abs/2607.24300)
- [PoisonedEvolution](https://arxiv.org/abs/2608.05563)
- [SkillMutator](https://arxiv.org/abs/2606.14154)
- [SkillTrojan](https://arxiv.org/abs/2604.06811)
- [SkillClone](https://arxiv.org/abs/2603.22447)
- [ActBench](https://arxiv.org/abs/2608.09476)
- [CausalFlow](https://arxiv.org/abs/2605.25338)
- [Causal Agent Replay](https://arxiv.org/abs/2606.08275)
- [Agent Behavioral Contracts](https://arxiv.org/abs/2602.22302)
- [Structural Enforcement of Goal Integrity / PEA](https://arxiv.org/abs/2604.23646)
- [Earned Authority for Evolving Agents](https://arxiv.org/abs/2607.23586)
- [Proof of Execution](https://arxiv.org/abs/2607.05397)
- [ProvenanceGuard](https://arxiv.org/abs/2607.01236)
- [Governed Shared Memory](https://arxiv.org/abs/2606.24535)
- [Harness-Bench](https://arxiv.org/abs/2605.27922)
- [tau-bench](https://arxiv.org/abs/2406.12045)
- [AgentDojo](https://arxiv.org/abs/2406.13352)
- [Agentic Harness Engineering](https://arxiv.org/abs/2604.25850)
- [Harness Handbook](https://arxiv.org/abs/2607.13285)
- [WorFBench](https://arxiv.org/abs/2410.07869)
- [AFlow](https://arxiv.org/abs/2410.10762)
- [ADAS](https://arxiv.org/abs/2408.08435)

