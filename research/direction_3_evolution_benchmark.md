# 方向3: Self-Evolution Benchmark

> Agent 自进化的系统化评估——设计一套全面的评估协议来回答：进化是否真的有效？各组件贡献多大？进化是否单调？跨任务迁移效果如何？

---

## 核心问题

EgoAgent 拥有完整的 Evolution Cycle（原则蒸馏 + TextGrad 优化 + 门控回滚 + Frontier Curriculum），能够在部署后持续自进化。然而，当前缺乏一套系统化的评估协议来严格量化以下关键问题：

1. **进化有效性（Effectiveness）**：经过 N 轮进化后，Agent 在目标任务上的性能是否显著提升？提升幅度有多大？
2. **组件贡献度（Component Contribution）**：进化循环中各组件（原则蒸馏、TextGrad、门控回滚、课程选择）各自贡献了多少？去掉某个组件后性能变化如何？
3. **进化单调性（Monotonicity）**：进化过程是否单调递增？还是存在振荡、退化、甚至灾难性遗忘？
4. **跨任务迁移（Cross-task Transfer）**：在任务 A 上获得的进化经验是否能迁移到任务 B？正迁移和负迁移的边界在哪？
5. **收敛性（Convergence）**：进化过程是否会收敛？收敛速度如何？是否存在过拟合风险？
6. **可持续性（Sustainability）**：长期进化是否会导致能力退化？如何保证稳定性？

这些问题的答案直接决定了 Agent 自进化框架在实际部署中的可信度和可靠性。

---

## 相关论文综述

### 1. SEA-Eval: A Benchmark for Evaluating Self-Evolving Agents Beyond Episodic Assessment

- **作者/机构**：2025，arXiv 预印本
- **发表于**：arXiv:2604.08988
- **核心思想**：首个超越单轮评估的自进化 Agent 基准。提出"进化飞轮"（Evolutionary Flywheel）框架，从两个维度评估 Agent：(1) 任务内执行可靠性（intra-task execution reliability），使用 SR（成功率）和 T（完成时间）作为核心指标；(2) 长期进化性能（long-term evolutionary performance），评估进化增益（evolutionary gain）、进化稳定性（evolutionary stability）和隐式对齐收敛（implicit alignment convergence）。设计了 30 个原子任务，组织为相关序列流和正交序列流，首次实现了对进化增益和结构稳定性的独立量化。
- **评估维度**：跨任务进化动态、执行可靠性、进化增益、稳定性、对齐收敛
- **局限性**：任务规模较小（仅30个原子任务）；仅评估 digital embodiment 场景；缺乏对组件级消融的支持；未考虑进化速度与计算效率的权衡

### 2. EvoAgentBench: Benchmarking Agent Self-Evolution via Ability Transfer

- **作者/机构**：2025，arXiv:2607.05202
- **发表于**：arXiv 预印本
- **核心思想**：提出通过"能力迁移"（Ability Transfer）来评估 Agent 自进化。从 Agent 执行轨迹中提取 trace-grounded Abilities，将其规范化为操作单元，构建领域特定的 Ability Graph 来链接共享程序重叠的任务。覆盖四个 Agent 领域：web 研究、算法推理、软件工程和知识工作。提供 528/267 的训练/测试划分，并确保每个测试任务都有验证过的训练侧 Ability 支持。
- **评估维度**：能力迁移率、跨领域泛化、Ability Graph 覆盖度、多 Agent 支持
- **局限性**：侧重于能力迁移评估，对进化过程本身（如收敛性、稳定性）关注不足；缺乏对进化循环中各组件的消融分析；未考虑灾难性遗忘问题

### 3. Gödel Agent: A Self-Referential Framework for Agents Recursively Self-Improvement

- **作者/机构**：Yin et al., 2024
- **发表于**：arXiv:2410.04444，ICLR 2025 相关审稿
- **核心思想**：受哥德尔机启发，提出自引用框架使 Agent 能递归自我改进，无需依赖预定义的优化算法。利用 LLM 动态修改自身逻辑和行为，仅通过高级目标引导。通过"monkey patching"技术在运行时修改代码，实现真正的自我感知和自适应。在数学推理和复杂 Agent 任务上展现持续自我改进能力。消融研究发现 thinking 工具是最关键组件。
- **评估维度**：跨域递归改进（MGSM、MMLU、DROP、GPQA）、消融组件贡献、收敛曲线
- **局限性**：评估以单次任务性能为主；缺乏对长期稳定性和灾难性遗忘的系统评估；自修改缺乏安全保证；缺乏跨任务迁移的形式化定义

### 4. EvoTest: Evolutionary Test-Time Learning for Self-Improving Agentic Systems

- **作者/机构**：2025，arXiv:2510.13220
- **发表于**：arXiv 预印本
- **核心思想**：提出测试时进化学习框架，让 Agent 系统在推理阶段通过进化策略自我改进。包含 prompt evolution、UCB 探索-利用平衡等组件。通过 AUC 分数量化整体影响，消融实验揭示：移除 prompt evolution 导致最大性能下降（证实高层策略进化是战略适应的主要驱动力）；移除 UCB 导致不稳定性而非简单性能下降。
- **评估维度**：AUC 曲线分析、组件消融（prompt evolution、UCB、memory）、学习动态曲线
- **局限性**：仅关注测试时学习；缺乏长期持续进化的评估；未考虑计算开销与性能提升的权衡

### 5. Experiential Reflective Learning (ERL) for Self-Improving LLM Agents

- **作者/机构**：2026，ICLR 2026 MemAgents Workshop
- **发表于**：OpenReview / ICLR 2026 Workshop
- **核心思想**：通过累积经验实现 LLM Agent 自我改进。将轨迹蒸馏为可复用的启发式规则（heuristics），在测试时检索相关指导。在 Gaia2 上超越先前经验学习方法。关键发现：(1) 启发式规则比原始轨迹迁移更好；(2) pass@3 与 pass^3 对比揭示可靠性提升。
- **评估维度**：pass@k 能力边界、pass^k 可靠性、heuristics vs. raw trajectory 对比
- **局限性**：主要关注经验积累的单一机制；缺乏对多组件协同进化的评估；未研究经验之间的冲突和退化问题

### 6. TRACE: Towards Self-Evolving Agent Benchmarks via Test-Time Exploration

- **作者/机构**：2025，arXiv:2510.00415
- **发表于**：arXiv 预印本
- **核心思想**：提出从静态基准到动态自进化评估系统的范式转换。TRACE 框架三阶段：(1) 进化提案挖掘（通过初步探索和发散思维生成任务进化提案）；(2) 自由探索构建问题；(3) Validate-by-Reproduce 验证。在 GAIA 基准上验证能持续增强任务复杂性同时提升正确性可靠性。
- **评估维度**：任务复杂度进化、解答可复现性、基准自适应难度
- **局限性**：侧重于基准本身的进化而非 Agent 能力的进化评估；不直接评估 Agent 进化过程的质量

### 7. SE-Agent: Self-Evolution Trajectory Optimization in Multi-Step Reasoning

- **作者/机构**：2025，NeurIPS 2025 Oral
- **发表于**：NeurIPS 2025
- **核心思想**：通过自进化轨迹优化改进 LLM Agent 的多步推理。在 SWE-bench Verified 上进行消融研究，分析三个变体的贡献。使用 Pass@1 和 Pass@5 评估首次和多次尝试的成功率。证明自进化轨迹能显著提升代码修复能力。
- **评估维度**：Pass@1/Pass@5、消融三变体、候选轨迹数量影响、API 成本上限影响
- **局限性**：仅关注 SWE-bench 单一领域；轨迹优化与 prompt 优化的关系未深入探讨

### 8. Revolve: Optimizing AI Systems by Tracking Response Evolution in Textual Optimization

- **作者/机构**：2025，ICML 2025
- **发表于**：ICML 2025
- **核心思想**：通过追踪响应演变实现二阶文本优化。指出 TextGrad 的关键局限：一阶优化仅依赖即时反馈，不考虑曲率信息，可能导致性能恶化（在 MMLU 上观察到 TextGrad 性能退化）。Revolve 通过历史上下文实现更稳定的优化，避免局部最优陷阱。
- **评估维度**：优化稳定性、收敛速度、过拟合检测、中间状态 vs 最终状态性能
- **局限性**：主要针对 prompt 优化任务；未扩展到完整 Agent 系统的进化评估

### 9. REMO: Reflection-Enhanced Meta-Optimization with TextGrad-style Prompt Optimization

- **作者/机构**：Wu & Qu, 2025，arXiv:2508.18749
- **发表于**：arXiv 预印本
- **核心思想**：集成 TextGrad 风格的 prompt 优化与记忆驱动的自进化。发现 TextGrad 存在严重的过拟合问题：验证准确率高（96.0%）但测试准确率低（69.0%），gap 达 -27%。REMO 通过 RAG 模块作为"错误笔记本"，隐式近似逆 Hessian，提供历史结构智慧。
- **评估维度**：泛化差距（validation vs test）、过拟合检测、epoch-level 反思、memory 检索效果
- **局限性**：依赖输入语义相似性进行检索，跨域泛化受限；未系统评估长期进化的稳定性

### 10. MemGen: Weaving Generative Latent Memory for Self-Evolving Agents

- **作者/机构**：2025，arXiv:2509.24704
- **发表于**：arXiv 预印本
- **核心思想**：提出生成式潜在记忆框架解决 Agent 自进化中的灾难性遗忘问题。在 ALFWorld 上性能提升 44.64%，有效缓解灾难性遗忘，促进类人记忆层次（规划记忆和程序记忆）的涌现。指出现有参数记忆在适应新数据时会擦除先前知识，而检索式记忆虽避免遗忘但缺乏与推理的流畅集成。
- **评估维度**：灾难性遗忘率、新任务性能、旧任务保持率、记忆层次涌现
- **局限性**：仅在 ALFWorld 单一环境验证；记忆层次的涌现缺乏可解释性分析

### 11. Actor-Curator: Co-adaptive Curriculum Learning via Policy-Improvement Bandits

- **作者/机构**：2025，arXiv:2602.20532
- **发表于**：arXiv 预印本
- **核心思想**：提出协同自适应课程学习框架，通过 Policy-Improvement Bandits 实现可扩展的 RL 后训练。在 AIME2024 上相对提升 28.6%，ARC-1D 上提升 30.5%，训练效率加速达 80%。证明协同自适应的课程选择显著优于均匀采样和固定课程。
- **评估维度**：训练稳定性、效率加速、跨基准泛化、与均匀采样/固定基线对比
- **局限性**：主要针对 RL 后训练阶段；未考虑在线部署后的持续自适应；课程难度评估依赖人工定义

### 12. GA-Rollback: Generator-Assistant Stepwise Rollback Framework for LLM Agent

- **作者/机构**：2025，arXiv:2503.02519
- **发表于**：arXiv 预印本
- **核心思想**：提出步级回滚框架缓解错误传播问题。引入独立 assistant 支持 generator 决策，利用回滚操作消除潜在错误动作。实现基于概率的反馈评估提升 assistant 可信度，引入 Wait-Info 策略处理具身任务。在三个基准上超越多个强 baseline。
- **评估维度**：错误传播率、回滚触发准确性、步级决策质量、整体任务完成率
- **局限性**：仅关注单次推理中的回滚，未扩展到跨时间的进化回滚；回滚粒度固定

### 13. A Comprehensive Survey of Self-Evolving AI Agents

- **作者/机构**：2025，arXiv:2508.07407
- **发表于**：arXiv 综述
- **核心思想**：首次系统性综述自进化 AI Agent 领域。围绕三个维度组织：what to evolve（模型、记忆、工具、架构）、when to evolve（intra-test-time、inter-test-time）、how to evolve（标量奖励、文本反馈、单/多 Agent）。讨论了评估、安全性和伦理考量。指出评估自进化 Agent 是开放挑战。
- **评估维度**：综述视角的分类学、评估方法论讨论
- **局限性**：综述性质，未提出具体评估方案；对进化过程的量化评估方法讨论有限

---

## 现有 Benchmark 的不足

通过对上述文献的系统分析，我们识别出现有评估体系的以下关键不足：

### 1. 评估粒度不足
- 现有 Benchmark（如 SEA-Eval）仅评估整体进化效果（before vs after），**缺乏对进化过程中间态的精细观测**。无法回答"第 3 轮进化为何退步？第 5 轮为何突然跃升？"
- 缺乏组件级归因：无法区分性能提升来自 prompt 优化、memory 积累还是 tool 改进

### 2. 时间维度缺失
- 大多数评估是"快照式"的：进化前一次、进化后一次。**缺乏连续的时间序列分析**
- 未追踪进化曲线的形状：是线性增长？对数收敛？还是锯齿形振荡？
- 未定义"收敛"的操作化标准

### 3. 稳定性评估薄弱
- 现有工作虽提到灾难性遗忘（MemGen），但**缺乏标准化的稳定性指标**
- 未区分"局部不稳定"（某轮退步后恢复）和"全局退化"（持续下降无法恢复）
- 回滚机制的有效性缺乏系统验证

### 4. 跨任务迁移评估缺失
- EvoAgentBench 评估了能力迁移，但**未评估进化经验的迁移**
- 缺乏"正迁移 vs 负迁移"的量化框架
- 未考虑任务间的相似度对迁移效果的影响

### 5. 计算效率无标准
- 进化需要大量计算（多轮评估、LLM 调用）。现有 Benchmark **未考虑效率-效果权衡**
- 缺乏"每 API 调用提升"或"每计算小时提升"等归一化指标

### 6. 缺乏对照实验标准
- 不同进化方法之间难以公平对比
- 缺乏标准化的初始状态、任务分布、评估协议
- 缺乏可复现的进化环境

---

## EgoAgent 的独特优势

EgoAgent 的架构设计使其成为研究 Agent 自进化评估的理想平台：

### 1. 完整的进化循环
EgoAgent 已实现完整的 Evolution Cycle（`self_evolution/engine.py`），包含：
- **原则蒸馏（Principle Library）**：从轨迹中提炼策略原则，使用贝叶斯打分更新
- **TextGrad 优化器**：计算文本梯度并应用到 identity 字段
- **门控回滚（Gated Evolution Controller）**：快照 → 评估 → 门控决策 → 接受/回滚
- **前沿课程（Frontier Curriculum）**：自动生成前沿难度任务（成功率 0.3-0.8）

### 2. 天然的快照机制
EgoAgent 的 Identity-as-Directory 设计使得**每个进化状态都可完整快照**：
```
self_evolution/data/snapshots/{identity}_{timestamp}_{uuid}/
├── ego/skills/...
├── superego/...
└── id.json
```
这为时间序列分析提供了天然的数据基础。

### 3. 可组合的模块化架构
进化循环的每个组件都是独立函数，可自由组合/禁用：
- `distill_principles()` — 可单独启用/禁用
- `compute_text_gradient()` — 可替换为其他优化器
- `gate_decision()` — 门控阈值可调
- `generate_frontier_tasks()` — 课程策略可替换

### 4. 多层评估基础设施
- **SWE-bench 评估**：真实软件工程任务的标准化评估
- **Harness 多类型**：react_single、coder_react、guarded_react 等多种编排模式
- **任务池管理**：`task_pool.json` 支持任务难度动态评估

### 5. 文件系统驱动的可追踪性
所有进化历史保存在 `archive.json`，每条记录包含：
- target、action、diff、score_before、score_after、accepted
- 完整的时间戳和唯一 ID

---

## 具体 Research Ideas

### Idea 1: EvoGauge — Agent 自进化的多维评估协议

**核心贡献**：设计首个系统化、标准化的 Agent 自进化评估协议，覆盖有效性、单调性、稳定性、迁移性和效率五个维度。

**技术方案**：

1. **进化曲线分析框架**
   - 定义进化曲线 $E(t) = \{s_1, s_2, ..., s_T\}$，其中 $s_t$ 是第 $t$ 轮进化后的性能
   - 单调性指标：$M = \frac{|\{t: s_{t+1} > s_t\}|}{T-1}$（递增轮次占比）
   - 收敛指标：最小 $T^*$ 使得 $\forall t > T^*, |s_t - s_{T^*}| < \epsilon$
   - 振荡指标：$O = \text{std}(\Delta s_t) / \text{mean}(|\Delta s_t|)$

2. **组件归因方法**
   - 完全消融：逐一移除组件测量性能变化
   - Shapley 值：计算每个组件的边际贡献
   - 交互效应：检测组件间的协同/冲突

3. **稳定性评估协议**
   - 前向稳定性：新学到的能力是否在后续进化中保持？
   - 后向稳定性：原有能力是否因新进化而退化？
   - 回滚有效性：回滚后是否真的恢复到之前的性能？

4. **跨任务迁移矩阵**
   - 定义任务对 $(A, B)$ 的迁移系数：$\tau_{A \to B} = \frac{s_B^{after\_evolving\_A} - s_B^{before}}{s_B^{oracle} - s_B^{before}}$
   - 构建 $N \times N$ 迁移矩阵，分析哪些任务族具有正迁移

**EgoAgent 实现**：
- 在 `self_evolution/engine.py` 的 `run_evolution_cycle()` 中插入精细化度量收集
- 每轮进化后在所有任务（而非仅前沿任务）上评估，构建完整曲线
- 利用快照机制实现精确的消融实验

---

### Idea 2: EvoCert — 带收敛保证的门控进化框架

**核心贡献**：将 EgoAgent 的门控回滚机制形式化，证明在一定条件下进化过程满足单调改进保证，并设计"进化证书"（Evolution Certificate）机制验证收敛。

**技术方案**：

1. **门控条件的理论分析**
   - 将门控决策形式化为：$\text{accept if } s_{t+1} - s_t \geq \delta$
   - 证明：在 TextGrad 满足 Lipschitz 连续条件下，门控机制保证 $\mathbb{E}[s_T] \geq s_0$
   - 分析不同门控阈值 $\delta$ 对收敛速度和稳定性的影响

2. **进化证书机制**
   - 每 K 轮进化后生成"证书"：在留出集上验证当前性能不低于历史最优的 $(1-\alpha)$ 倍
   - 若证书验证失败，自动回滚到最后一个有效证书状态
   - 证书可作为部署信心度量

3. **自适应门控策略**
   - 早期进化：宽松阈值（鼓励探索）$\delta_t = \delta_0 \cdot e^{-\beta t}$
   - 后期进化：严格阈值（保护已有能力）
   - 基于历史振荡频率动态调整

4. **多任务门控**
   - 联合门控：修改需要在所有任务上不退步才接受
   - Pareto 门控：只要在 Pareto 前沿上前进就接受
   - 加权门控：核心任务权重更高

**EgoAgent 实现**：
- 扩展 `gate_decision()` 函数，支持多种门控策略
- 实现证书验证模块
- 在 `evaluate()` 中支持多任务集评估

---

### Idea 3: EvoTransfer — 进化经验的跨任务迁移图谱

**核心贡献**：研究 Agent 进化经验（原则、梯度、策略改进）如何在不同任务和领域间迁移，构建"进化迁移图谱"指导高效进化。

**技术方案**：

1. **进化经验表征**
   - 原则向量：将 Principle Library 中的原则编码为语义向量
   - 梯度方向：将 TextGrad 产生的修改方向作为特征
   - 策略指纹：Agent identity 文件的语义 hash

2. **迁移图谱构建**
   - 在 M 个任务上独立运行进化循环，收集每个任务的进化经验
   - 将任务 A 的进化经验注入任务 B，测量性能变化
   - 构建带权有向图：节点=任务，边=迁移效果

3. **选择性迁移策略**
   - 根据迁移图谱，自动选择最可能正迁移的经验进行注入
   - 避免负迁移：使用门控机制验证迁移效果
   - 多源融合：从多个相关任务融合经验

4. **课程规划优化**
   - 基于迁移图谱优化任务序列：先在迁移效果好的任务上进化
   - 证明最优任务序列问题的 NP-hardness，设计贪心近似算法
   - 实验对比不同序列策略（随机、难度递增、迁移优先）

**EgoAgent 实现**：
- 扩展 `retrieve_principles()` 支持跨任务检索
- 在 `generate_frontier_tasks()` 中整合迁移图谱信息
- 实现任务间 principle 迁移的评估管道

---

## 评估维度设计（详细）

基于上述 Research Ideas，我们设计以下系统化评估维度体系：

### 维度 1: 进化有效性（Evolution Effectiveness）

| 指标 | 定义 | 计算方法 |
|------|------|---------|
| 绝对提升（Absolute Gain） | 进化后 vs 进化前的性能差 | $\Delta = s_T - s_0$ |
| 相对提升（Relative Gain） | 相对于初始性能的提升比 | $\Delta_{rel} = (s_T - s_0) / s_0$ |
| 上界利用率（Ceiling Utilization）| 相对于理论最优的利用率 | $CU = (s_T - s_0) / (s^* - s_0)$ |
| 效率提升（Efficiency Gain） | 每单位计算成本的提升 | $EG = \Delta / C_{total}$ |

### 维度 2: 进化动态（Evolution Dynamics）

| 指标 | 定义 | 计算方法 |
|------|------|---------|
| 单调性（Monotonicity） | 性能递增轮次占比 | $M = |\{t: s_{t+1} > s_t\}| / (T-1)$ |
| 收敛速度（Convergence Rate） | 达到 90% 最终性能的轮次数 | $T_{90} = \min\{t: s_t \geq 0.9 \cdot s_T\}$ |
| 振荡度（Oscillation） | 性能变化的标准差 | $O = \text{std}(\{s_{t+1} - s_t\})$ |
| 最大回撤（Max Drawdown） | 从历史峰值的最大下降 | $MD = \max_t(s_{peak\_before\_t} - s_t)$ |

### 维度 3: 稳定性（Stability）

| 指标 | 定义 | 计算方法 |
|------|------|---------|
| 前向保持率（Forward Retention） | 新能力在后续轮次中的保持比例 | $FR_t = s_{t+K}^{task\_learned\_at\_t} / s_t^{task\_learned\_at\_t}$ |
| 后向遗忘率（Backward Forgetting） | 原有能力的退化比例 | $BF = (s_0^{old\_tasks} - s_T^{old\_tasks}) / s_0^{old\_tasks}$ |
| 回滚精度（Rollback Accuracy） | 回滚后性能恢复的精度 | $RA = |s_{rollback} - s_{snapshot}| / s_{snapshot}$ |
| 门控召回率（Gate Recall） | 应该拒绝的修改中被门控拦截的比例 | $GR = TP_{reject} / (TP_{reject} + FN_{reject})$ |

### 维度 4: 跨任务迁移（Cross-task Transfer）

| 指标 | 定义 | 计算方法 |
|------|------|---------|
| 正迁移率（Positive Transfer Rate） | 产生正迁移的任务对比例 | $PTR = |\{(A,B): \tau_{A→B} > 0\}| / |pairs|$ |
| 平均迁移系数（Mean Transfer） | 所有任务对的平均迁移效果 | $\bar{\tau} = \text{mean}(\tau_{A→B})$ |
| 迁移不对称性（Transfer Asymmetry） | A→B 与 B→A 迁移的差异 | $TA = |\tau_{A→B} - \tau_{B→A}|$ |
| 领域内/跨域迁移比（In/Cross Domain） | 域内迁移 vs 跨域迁移的效果比 | $R_{domain} = \bar{\tau}_{in} / \bar{\tau}_{cross}$ |

### 维度 5: 组件贡献（Component Attribution）

| 指标 | 定义 | 计算方法 |
|------|------|---------|
| 消融影响（Ablation Impact） | 移除组件 C 后的性能变化 | $AI_C = s_T^{full} - s_T^{-C}$ |
| Shapley 值（Shapley Value） | 组件的边际贡献期望 | $\phi_C = \frac{1}{|N|!}\sum_{\pi} [v(S_\pi \cup C) - v(S_\pi)]$ |
| 交互效应（Interaction Effect） | 两组件共存 vs 分别存在的增益差 | $IE_{AB} = s^{AB} - s^A - s^B + s^{\emptyset}$ |
| 必要性（Necessity） | 去掉组件后任务不可完成的比例 | $N_C = |\{task: s_{-C} < threshold\}| / |tasks|$ |

### 维度 6: 计算效率（Computational Efficiency）

| 指标 | 定义 | 计算方法 |
|------|------|---------|
| 每轮 API 调用数 | 单轮进化消耗的 LLM API 次数 | 直接计数 |
| 样本效率（Sample Efficiency） | 达到目标性能所需最少训练样本 | $SE = \min |D| : s(D) \geq s_{target}$ |
| 成本收益比（Cost-Benefit Ratio） | 性能提升 / 计算成本 | $CBR = \Delta s / cost$ |
| 加速比（Speedup vs. Random） | 相对于随机探索的加速 | $SP = T_{random} / T_{curriculum}$ |

---

## 实验设计

### 实验 1: 进化有效性与动态分析

**目标**：验证 EgoAgent 进化循环的整体有效性，刻画进化曲线形态。

**数据集**：
- SWE-bench Lite（300 个 Python 代码修复任务）
- HumanEval+（164 个代码生成任务）
- GAIA Lv1-3（综合 Agent 任务，166 个问题）

**进化配置**：
- 进化轮次：T = 20 轮
- 每轮评估任务数：全集的 20% 随机抽样
- 重复实验：3 次不同种子

**对比 baseline**：
- Static Agent：不进化的原始 Agent
- Random Evolution：随机修改 prompt，无门控
- TextGrad Only：仅用 TextGrad 优化，无门控回滚
- Gödel Agent：自引用递归自改进
- ERL：经验反思学习

**预期输出**：
- 20 轮进化曲线（每条 baseline 一条线）
- 单调性、收敛速度、振荡度等指标对比表
- 最终性能对比（Absolute Gain + Relative Gain）

### 实验 2: 组件消融研究

**目标**：量化进化循环中每个组件的贡献。

**消融变体（共 16 种组合）**：
| 变体 | 原则蒸馏 | TextGrad | 门控回滚 | 前沿课程 |
|------|---------|----------|---------|---------|
| Full | ✓ | ✓ | ✓ | ✓ |
| -Principle | ✗ | ✓ | ✓ | ✓ |
| -TextGrad | ✓ | ✗ | ✓ | ✓ |
| -Gate | ✓ | ✓ | ✗ | ✓ |
| -Curriculum | ✓ | ✓ | ✓ | ✗ |
| -Principle-TextGrad | ✗ | ✗ | ✓ | ✓ |
| -Gate-Curriculum | ✓ | ✓ | ✗ | ✗ |
| None（Random） | ✗ | ✗ | ✗ | ✗ |

**每种变体运行**：10 轮进化 × 3 种子 = 30 次实验

**分析**：
- 单因素消融影响排序
- Shapley 值计算
- 两两交互效应热力图

### 实验 3: 稳定性与灾难性遗忘评估

**目标**：验证进化过程是否引入灾难性遗忘，门控回滚是否有效保护已有能力。

**实验设计**：
- 阶段 1（轮次 1-5）：在 Task Set A（代码修复）上进化
- 阶段 2（轮次 6-10）：在 Task Set B（数据分析）上进化
- 阶段 3（轮次 11-15）：在 Task Set C（API 集成）上进化

**评估时机**：每轮进化后在 A+B+C 全集上评估

**关键度量**：
- 后向遗忘率：在 B/C 上进化时，A 的性能变化
- 前向保持率：在 A 上学到的能力在后续轮次中的保持
- 门控拦截率：门控机制拦截有害修改的比例

**对比**：
- 有门控 vs 无门控（量化回滚机制的保护价值）
- 不同门控阈值 δ = {0, 2, 5, 10} 的影响

### 实验 4: 跨任务迁移矩阵

**目标**：构建进化经验的跨任务迁移图谱。

**任务族**：
- A: 代码修复（SWE-bench 子集，50 任务）
- B: 代码生成（HumanEval 子集，50 任务）
- C: Web 交互（WebArena 子集，30 任务）
- D: 数学推理（MATH 子集，50 任务）
- E: 工具使用（ToolBench 子集，30 任务）

**实验流程**：
1. 在每个任务族上独立进化 10 轮
2. 将任务 X 的进化经验（原则库 + prompt 改进）迁移到任务 Y
3. 评估迁移后的性能变化

**输出**：5×5 迁移矩阵 + 可视化热力图

### 实验 5: 门控策略对比

**目标**：验证不同门控策略对进化质量的影响。

**门控策略**：
- Fixed Threshold: $\delta = 5$（当前 EgoAgent 默认）
- Decaying Threshold: $\delta_t = 10 \cdot e^{-0.1t}$
- Adaptive Threshold: 基于历史振荡动态调整
- No Gate: 接受所有修改
- Certificate-based: 每 5 轮验证证书

**评估**：
- 最终性能 vs 计算成本 Pareto 曲线
- 稳定性指标对比
- "假阳性"拦截率（拦截了其实有益的修改）

---

## 目标会议与影响力评估

### 首选目标会议

| 会议 | 投稿截止 | 适配方向 | 预期接受概率 |
|------|---------|---------|------------|
| **ICLR 2027** | 2026年9月 | Idea 1 (EvoGauge) — Benchmark track | 高 |
| **NeurIPS 2026 Datasets & Benchmarks** | 2026年5月 | Idea 1 — 标准化评估协议 | 高 |
| **ICML 2027** | 2027年1月 | Idea 2 (EvoCert) — 理论+实验 | 中高 |
| **ACL 2027** | 2026年10月 | Idea 3 (EvoTransfer) — Agent NLP 交叉 | 中高 |

### 影响力评估

**学术影响**：
- 填补 Agent 自进化评估的空白——目前该方向仅有 SEA-Eval 和 EvoAgentBench 两个初步工作
- 提供标准化评估协议，可成为后续自进化工作的通用评估基准
- 组件归因方法论可推广到其他迭代优化系统

**工程影响**：
- 评估协议可直接集成到 EgoAgent 框架，作为"进化健康度"监控
- 门控策略的理论保证增强部署信心
- 迁移图谱可指导实际部署中的进化策略选择

**社区影响**：
- 开源评估工具包，降低自进化研究的入门门槛
- 标准化指标使不同方法可公平对比
- Leaderboard 促进社区竞争

---

## 参考文献列表

1. SEA-Eval: A Benchmark for Evaluating Self-Evolving Agents Beyond Episodic Assessment. arXiv:2604.08988, 2025.

2. EvoAgentBench: Benchmarking Agent Self-Evolution via Ability Transfer. arXiv:2607.05202, 2025.

3. Yin et al. Gödel Agent: A Self-Referential Framework for Agents Recursively Self-Improvement. arXiv:2410.04444, 2024.

4. EvoTest: Evolutionary Test-Time Learning for Self-Improving Agentic Systems. arXiv:2510.13220, 2025.

5. Experiential Reflective Learning for Self-Improving LLM Agents. ICLR 2026 MemAgents Workshop, 2026.

6. TRACE: Towards Self-Evolving Agent Benchmarks via Test-Time Exploration. arXiv:2510.00415, 2025.

7. SE-Agent: Self-Evolution Trajectory Optimization in Multi-Step Reasoning with LLM-Based Agents. NeurIPS 2025 Oral.

8. Revolve: Optimizing AI Systems by Tracking Response Evolution in Textual Optimization. ICML 2025.

9. Wu & Qu. REMO: Reflection-Enhanced Meta-Optimization Integrating TextGrad-style Prompt Optimization with Memory-Driven Self-Evolution. arXiv:2508.18749, 2025.

10. MemGen: Weaving Generative Latent Memory for Self-Evolving Agents. arXiv:2509.24704, 2025.

11. Actor-Curator: Co-adaptive Curriculum Learning via Policy-Improvement Bandits for Scalable RL Post-Training. arXiv:2602.20532, 2025.

12. GA-Rollback: Generator-Assistant Stepwise Rollback Framework for Large Language Model Agent. arXiv:2503.02519, 2025.

13. A Comprehensive Survey of Self-Evolving AI Agents: A New Paradigm Bridging Foundation Models and Lifelong Agentic Systems. arXiv:2508.07407, 2025.

14. A Survey of Self-Evolving Agents: On Path to Artificial Super Intelligence. arXiv:2507.21046, 2025.

15. Self-Evolving LLMs via Continual Instruction Tuning. arXiv:2509.18133, 2025.

16. SeeUPO: Sequence-Level Agentic-RL with Convergence Guarantees. arXiv:2602.06554, 2025.

17. TextGrad: Automatic "Differentiation" via Text. Nature, 2025.

18. TextBFGS: Quasi-Newton Optimization for Discrete Executable Text via Gradient-Operator Retrieval. arXiv:2602.00059, 2025.

19. The Lighthouse of Language: Enhancing LLM Agents via Critique-Guided Improvement. NeurIPS 2025.

20. CRAFT-GUI: Curriculum-Reinforced Agent For GUI Tasks. arXiv:2508.11360, 2025.

21. DSMentor: Enhancing Data Science Agents with Curriculum Learning and Online Knowledge Accumulation. arXiv:2505.14163, 2025.

22. UI-Genie: A Self-Improving Approach for Iteratively Boosting MLLM-based Mobile GUI Agents. OpenReview, 2025.

23. Catastrophic Forgetting in LLMs: A Comparative Analysis Across Language Tasks. arXiv:2504.01241, 2025.
