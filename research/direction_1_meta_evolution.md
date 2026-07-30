# 方向1: Meta-Evolution — 让自进化系统改进自己的进化过程

> 撰写日期: 2026-07-30
> 研究者: EgoAgent Research Team
> 关键词: Meta-Evolution, Recursive Self-Improvement, Self-Referential Agents, Meta-Learning

---

## 核心问题

**核心挑战：当一个系统能够改进自己时，它能否进一步改进"改进自己"的过程本身？**

在 EgoAgent 框架中，进化循环（Evolution Cycle）本身就是一个可编辑的 Harness——一个声明式 DAG。这意味着 Agent 不仅能改进自己解决任务的策略（object-level improvement），还能理论上修改自己的进化机制（meta-level improvement）。这种"进化的进化"即为 Meta-Evolution。

具体而言，核心问题包含以下层次：

1. **Object-Level Evolution**: Agent 改进自己的 prompt、工具使用策略、知识检索方式（已有工作较多）
2. **Meta-Level Evolution**: Agent 改进自己的进化策略——如何选择修改对象、如何评估修改效果、如何决定何时进化
3. **Meta-Meta-Level**: 改进"改进进化策略"的策略——理论上可以无限递归，但实际中需要收敛

这个方向的核心科学问题是：
- 递归自我改进是否会收敛到有意义的不动点？
- 如何在避免退化（misevolution）的同时实现开放式改进？
- meta-evolution 相比固定进化策略，在什么条件下具有可证明的优势？

---

## 相关论文综述

### 1. Gödel Agent: A Self-Referential Agent Framework for Recursive Self-Improvement

**作者/机构**: Xunjian Yin, Xinyi Wang, Liangming Pan, Xiaojun Wan, William Yang Wang（北京大学、UCSB）

**发表**: arXiv 2410.04444, 2024 (后续 2025 年 5 月更新)

**核心思想**: 受哥德尔机器（Gödel Machine）启发，Gödel Agent 允许 Agent 在不依赖预定义优化例程的情况下递归改进自身。核心理念是：Agent 的所有逻辑（包括元优化逻辑）都以可执行代码形式表达，LLM 可以动态修改任意部分。

**方法**:
- Agent 逻辑完全以 Python 代码表示
- 使用高能力 LLM（如 o3）作为元优化器，阅读当前代码并生成改进版本
- 通过 `exec()` 执行改进后的代码，在 benchmark 上评估效果
- 仅当新版本在统计上显著优于旧版本时才接受修改
- 支持完全的自指代——Agent 可以修改自己的修改逻辑

**局限性**:
- 安全风险极高（`exec()` 执行任意代码，无沙箱）
- 元优化器对 LLM 能力要求极高，成本巨大
- 代码改写失败率高，需要多次尝试
- 缺乏进化历史记忆，每次独立决策
- 理论证明不完整——收敛性无保障

---

### 2. Darwin Gödel Machine: Open-Ended Evolution of Self-Improving Agents

**作者/机构**: Sakana AI + Jeff Clune Lab (UBC)

**发表**: arXiv 2505.22954, 2025

**核心思想**: 将 Gödel Machine 的自指代思想与 Darwinian 进化和开放式研究（Open-Endedness）结合。DGM 维护一个 coding agent 的种群档案（archive），通过变异和选择实现持续改进。关键创新在于：由于改进自身也是一个编码任务，编码能力的提升可以级联提升自我改进的能力。

**方法**:
- 从单一 seed agent 出发，维护一个 agent archive
- 每轮从 archive 中采样一个 agent，使用 foundation model 生成变异版本
- 在 coding benchmark（SWE-bench、HumanEval 等）上评估新 agent
- 使用"有趣性"（interestingness）+ 性能作为选择标准
- Agent 的改进能力与被改进能力是同一能力（编码），实现了正反馈循环

**局限性**:
- 仅在编码领域验证——编码能力的提升恰好能提升自我改进能力，这个对齐在其他领域不成立
- 计算成本极高（需要大量评估）
- archive 管理策略仍然是人工设计的
- 开放式进化可能走向无意义的"新颖但无用"的方向

---

### 3. STOP: Self-Taught Optimizer — Recursively Self-Improving Code Generation

**作者/机构**: Eric Zelikman, Eliana Lorch, Lester Mackey, Adam Kalai（Stanford, Microsoft Research）

**发表**: NeurIPS 2024

**核心思想**: 设计脚手架（scaffolding）程序本身就是一个优化问题。STOP 用 LLM-infused scaffolding 程序来改进自身，实现递归自我优化。

**方法**:
- 起始于一个"种子改进器"（seed improver）——一个调用 LLM 生成改进方案的程序
- 将种子改进器应用于改进自身——用改进器来改进改进器
- 在下游任务集上评估改进后的改进器
- 迭代此过程，每轮用上一轮产生的更好的改进器来生成下一轮

**局限性**:
- 递归深度有限（通常 2-3 轮后收益递减）
- 改进器的搜索空间受限于 LLM 的 context window
- 缺乏理论保证——不清楚何时应停止递归
- 对 seed improver 的初始化敏感

---

### 4. ADAS: Automated Design of Agentic Systems

**作者/机构**: Shengran Hu, Cong Lu, Jeff Clune（UBC, Vector Institute）

**发表**: ICML 2025

**核心思想**: 提出"自动化代理系统设计"新研究方向。核心观察：Agent 可以用代码定义，而编程语言是图灵完备的，因此 meta-agent 理论上可以发现任意 agent 架构。

**方法**:
- Meta Agent 维护一个 archive 存储历史设计
- 每轮 Meta Agent 阅读 archive 中的历史设计及其性能
- 生成新的 agent 设计（完整 Python 代码）
- 在 benchmark 上评估，用 Bootstrap CI 判断是否显著提升
- 如果显著提升，加入 archive

**局限性**:
- 每次生成全新代码，无法增量改进
- Meta Agent 自身是固定的（不会进化）——这正是 meta-evolution 要解决的问题
- 计算成本极高（每个候选设计都需要完整评估）
- 上下文窗口瓶颈限制了可参考的历史设计数量

---

### 5. SICA: A Self-Improving Coding Agent

**作者/机构**: Yuntao Li et al.

**发表**: NeurIPS 2025

**核心思想**: 消除 meta-agent 和 target-agent 的区分——同一个 agent 既是被改进的对象，也是执行改进的主体。通过自我编辑代码库实现开放式自我改进。

**方法**:
- Agent 从最小可运行代码开始（Meta Agent Loop）
- 在 SWE-bench 等任务上运行，收集性能反馈
- Agent 自己编辑自己的代码库来改进性能
- 迭代此过程，性能从 17% 提升到 53%（SWE-bench Verified subset）
- 关键：agent scaffold 代码本身就是 agent 可以编辑的文件

**局限性**:
- 需要频繁运行完整评估（每次代码修改后）
- 改进的可解释性差——不清楚为什么某个修改有效
- 可能过拟合到特定 benchmark
- 稳定性问题——有时改进后反而退化

---

### 6. EvoX: Meta-Evolution for Automated Discovery

**作者/机构**: SkyDiscover AI Research

**发表**: arXiv 2602.23413, 2025

**核心思想**: 将 LLM-driven 优化框架化为元学习问题，搜索策略本身也是可进化的对象。提出双层进化过程：solution-evolution loop 和 meta-evolution loop。

**方法**:
- **Solution-Evolution Loop**: 在当前搜索策略下生成候选解
- **Meta-Evolution Loop**: 根据 solution-evolution 的进展，更新搜索策略本身
- 搜索策略决定如何选择历史候选解、如何构造 prompt context
- 策略通过其产生的 solution quality improvement 来评估
- 在近 200 个真实优化任务上超越 AlphaEvolve 和 OpenEvolve

**局限性**:
- 双层优化的计算开销大
- meta-evolution 的收敛性缺乏理论分析
- 策略空间的参数化方式影响结果
- 主要在算法发现/数学优化领域验证

---

### 7. MetaEvo: A Meta-Optimization Framework for Experience-Driven Agent Evolution

**作者/机构**: 未明确

**发表**: arXiv 2606.07603, 2026

**核心思想**: 现有经验驱动方法仅改进"学了什么"（what the model stores），而 MetaEvo 改进"如何学习"（how the model learns）。通过偏好优化增强模型从任务经验中抽象原则的能力。

**方法**:
- **Stage 1**: Preference-based optimization 增强模型的原则抽象能力
- **Stage 2**: 使模型能够利用抽象原则进行自主进化
- 两阶段设计避免了仅依赖记忆/启发式的早期平台期
- 关键区别：不是优化具体策略，而是优化"从经验中提取策略"的元能力

**局限性**:
- 需要 preference data 的初始训练
- 两阶段之间的衔接需要精心设计
- 原则抽象的质量依赖模型基础能力
- 在复杂多步推理任务上尚未充分验证

---

### 8. MemEvolve: Meta-Evolution of Agent Memory Systems

**作者/机构**: Guibin Zhang, Haotian Ren, Wangchunshu Zhou, Shuicheng Yan 等

**发表**: arXiv 2512.18746, 2025

**核心思想**: 不仅进化 agent 的经验知识，还进化底层的记忆架构本身。Level 1 是 agent 从经验中学习，Level 2 是记忆系统本身的进化——哪些记忆有用、哪种检索模式有效、哪种存储决策减少了干扰。

**方法**:
- 联合进化 agent 的经验知识和底层记忆架构
- 根据记忆实际帮助 agent 解决问题的效果来重新设计记忆系统
- 不是由工程师手动设计，而是通过优化自动发现
- 在 SmolAgent、FlashSearcher 等框架上实现最高 1x+ 的性能提升

**局限性**:
- 记忆架构的搜索空间定义不够清晰
- 进化过程的可解释性不足
- 计算开销大（需要完整运行才能评估记忆系统质量）
- 与特定框架耦合较紧

---

### 9. AlphaEvolve: A Coding Agent for Scientific and Algorithmic Discovery

**作者/机构**: Google DeepMind

**发表**: arXiv 2506.13131, 2025

**核心思想**: 用 LLM 驱动的进化框架发现和优化算法。AlphaEvolve 协调 LLM 的自主 pipeline，通过直接修改代码来改进算法，使用进化方法持续接收评估器反馈。

**方法**:
- 使用 Gemini Flash + Pro 的 ensemble
- 进化过程中 LLM 提出代码修改建议
- 多目标优化 + 丰富的历史 context
- 自动评估器验证每个变体的正确性和性能
- 在数据中心调度、芯片设计、矩阵乘法等问题上取得突破

**局限性**:
- 进化策略本身是固定的（非 meta-evolving）
- 需要人类设计评估函数
- 仅在有明确可验证目标的领域有效
- 计算资源需求极高（Google 内部集群）

---

### 10. Multi-Agent Evolve (MAE): LLM Self-Improve through Co-Evolution

**作者/机构**: 未明确

**发表**: NeurIPS 2025 (OpenReview)

**核心思想**: 通过多 Agent 共进化实现无标注数据的 LLM 自我改进。将单个 LLM 实例化为 Proposer、Solver、Judge 三个角色，通过 RL 联合优化。

**方法**:
- Proposer 生成挑战性问题
- Solver 解决问题
- Judge 评估答案质量
- 三者通过 RL 联合优化——Proposer 的奖励与 Solver 的失败率正相关
- 3B 模型从 55.33% 提升到 58.51%，无需人工标注

**局限性**:
- Judge 可能与 Solver 串通（给虚假高分）
- 需要 RL 训练基础设施
- 三角色设计是固定的——角色分工本身不会进化
- 在复杂推理任务上的提升有限

---

### 11. Agent0: Unleashing Self-Evolving Agents from Zero Data

**作者/机构**: AIMING Lab

**发表**: arXiv 2511.16043, 2025

**核心思想**: 通过 Curriculum Agent 和 Executor Agent 的共生竞争实现从零数据出发的自主进化。关键创新是自洽性过滤器——用来确定 agent 的"学习前沿"。

**方法**:
- Curriculum Agent 生成递增难度的前沿任务
- 自洽性过滤（0.3 < consistency < 0.8 标记为前沿任务）
- Executor Agent 在前沿任务上训练
- ADPO（Adaptive Advantage-based DPO）进行策略更新
- 双向反馈：Executor 的表现指导 Curriculum 调整难度

**局限性**:
- 依赖 RL 训练，不适用于纯推理时框架
- 自洽性度量在某些任务类型上不可靠
- Curriculum 的多样性可能不够（模式坍塌）
- 在开放域任务上的效果未验证

---

### 12. Polymath: A Self-Optimizing Agent with Dynamic Hierarchical Workflow

**作者/机构**: 未明确

**发表**: arXiv 2508.02959, 2025; ACM 2025

**核心思想**: 利用任务流图（task flow graph）的灵活性和代码表示工作流的表达力，结合多网格启发的图优化与自反思引导的进化算法，实现无标注数据的工作流自优化。

**方法**:
- 动态分层工作流：高层为任务流图（分治策略），低层为代码表示的子任务工作流
- 多网格图优化：用历史评估的代理分数（surrogate scores）指导工作流结构优化
- 自反思引导的进化算法优化工作流细节
- 在 coding、math、multi-turn QA 等 6 个 benchmark 上验证

**局限性**:
- 分层结构的层数需要人为设定
- 代理分数的准确性影响优化方向
- 工作流修改的搜索空间受限
- 初始工作流设计影响最终效果

---

### 13. SE-Agent: Self-Evolution Trajectory Optimization

**作者/机构**: 未明确

**发表**: arXiv 2508.02085, 2025

**核心思想**: 通过 revision（修订）、recombination（重组合）、refinement（精炼）三个进化操作，使 Agent 能够迭代优化自己的推理轨迹。

**方法**:
- 重新审视历史推理轨迹
- Revision: 修正错误步骤
- Recombination: 将成功轨迹的关键策略迁移到失败轨迹
- Refinement: 多维度评估函数选择精英轨迹
- 在 SWE-bench 上突破 Claude-4 的编程上限

**局限性**:
- 三个进化操作是固定设计的（不会 meta-evolve）
- 需要大量轨迹数据
- 精英选择可能导致多样性丧失
- 在非编码任务上的泛化性待验证

---

### 14. Self-Developing: Algorithm Discovery for Recursive Self-Improvement

**作者/机构**: 未明确

**发表**: arXiv 2410.15639, 2024

**核心思想**: 让 LLM 自主发现、实现和改进自己的改进算法。使用 DPO 训练 LLM 生成越来越好的改进策略代码。

**方法**:
- Seed model 生成改进算法候选（以可执行代码形式）
- 评估这些算法的有效性
- 使用 DPO 让模型偏好生成更好的改进策略
- 通过模型合并（model merging）这一实际技术来验证
- 迭代循环：发现改进算法→应用→评估→训练模型偏好更好的算法

**局限性**:
- 需要 DPO 训练（修改模型权重）
- 改进算法的搜索空间受限于 LLM 的生成能力
- 仅在模型合并场景验证
- 理论收敛性未证明

---

### 15. Inefficiencies of Meta Agents for Agent Design

**作者/机构**: 未明确

**发表**: arXiv 2510.06711, 2025

**核心思想**: 对 meta-agent 自动设计框架提出批判性分析，揭示了三个关键挑战：meta-agent 实际上未能有效从历史设计中学习、sample-evaluate-iterate 模式的效率问题、以及搜索策略的根本局限。

**方法**:
- 对 ADAS (Hu et al., 2024) 等框架进行实证分析
- 发现 meta-agent 的性能不如忽略历史设计的 baseline
- 分析了"学习"的假象——meta-agent 生成的改进往往与历史无关
- 提出了可能的改进方向

**局限性**:
- 仅分析了特定类型的 meta-agent 框架
- 未提出完整的替代方案
- 批判性视角可能不适用于更先进的 meta-evolution 方法
- 未考虑 meta-evolution（改进 meta-agent 自身）的可能性

---

## EgoAgent 的独特优势

基于上述论文调研，EgoAgent 在 Meta-Evolution 方向具有以下独特优势：

### 1. 声明式 DAG 作为可编辑的进化基因型

EgoAgent 的 Harness 是声明式的 pipeline DAG，而非命令式代码。这意味着：
- **进化搜索空间结构化**：图操作（add_node、remove_node、update_edge）比任意代码修改更可控
- **修改的语义清晰**：每个 DAG 修改都有明确的语义（添加推理步骤、修改数据流等）
- **天然支持渐进式修改**：不需要像 ADAS/DGM 那样每次重写全部代码
- **可回滚**：DAG 结构可以 snapshot → restore

### 2. 进化循环本身就是 Harness

**这是 EgoAgent 最核心的 meta-evolution 优势。** `evolution_cycle` harness 定义了进化如何发生，而 Agent 的 `modify_harness` 工具可以修改任意 harness——包括 `evolution_cycle` 本身。这意味着：
- 进化策略不是代码中的硬编码逻辑，而是声明式配置
- Agent 可以在运行时改变自己的进化方式
- meta-evolution 不需要额外的框架，是系统的自然能力

### 3. Identity 三层模型 + 环境分层

Identity 的 system rules、skills、knowledge 提供了清晰的进化作用域：
- **Prompt Evolution**: 修改 task_prompt、system rules
- **Skill Evolution**: 添加/修改 skills（工具）
- **Knowledge Evolution**: 更新知识库
- **Architecture Evolution**: 修改 Harness DAG 结构

### 4. 已有的自进化基础设施

EgoAgent 已经实现了 `self_evolution` 模块，包含：
- Principle Library（原则库）
- Evolution Archive（进化归档）
- Frontier Curriculum（前沿课程）
- TextGrad Optimizer（文本梯度优化）
- Gated Evolution Controller（门控进化控制器）

这为 meta-evolution 提供了可被"进化"的具体对象。

---

## 具体 Research Ideas

### Idea 1: Self-Referential Harness Evolution — 让进化循环改进自己

**Motivation**: 

现有自进化系统（包括 EgoAgent 当前实现）的进化策略是固定的——由人类设计的 evolution_cycle harness 决定。然而，进化策略的最优设计高度依赖于任务分布、agent 当前能力水平、和环境特征。一个固定的进化策略无法适应这些变化。

核心论文如 STOP、EvoX、DGM 都展示了"改进改进过程"的价值，但它们的 meta-level 要么是纯代码（难以控制）、要么需要修改模型权重。EgoAgent 的声明式 DAG 提供了一种结构化、可控、可回溯的 meta-evolution 机制。

**Method**:

1. **双层 Harness 架构**:
   - Inner Harness（被进化的对象）：task-solving 的 DAG
   - Outer Harness（进化循环）：`evolution_cycle` 的 DAG
   - Meta Harness（进化进化循环）：对 outer harness 的改进策略
   
2. **Meta-Evolution Operators**:
   - **Structure Mutation**: 在 evolution_cycle DAG 中添加/删除/重排节点
   - **Parameter Mutation**: 修改 evolution_cycle 中的参数（如评估阈值、搜索深度）
   - **Strategy Mutation**: 改变选择/变异/评估策略
   
3. **Progress-Based Meta-Fitness**:
   - Meta-fitness = inner evolution 的改进速率（不是绝对性能）
   - 用 evolution_cycle 执行 N 步后的性能增量来评估 meta-evolution 的效果
   - Bootstrap CI 确保统计显著性

4. **收敛检测与停止条件**:
   - 当 meta-evolution 的改进率低于阈值时停止
   - 检测到退化时自动回滚到上一个 meta 版本
   - 维护 meta-archive 记录不同进化策略的历史效果

**Experiment Plan**:

- **Benchmark**: SWE-bench Verified (subset), GPQA, MATH, HumanEval
- **Baseline 1**: 固定 evolution_cycle（当前 EgoAgent 实现）
- **Baseline 2**: 随机搜索 evolution_cycle 配置
- **Baseline 3**: Gödel Agent（纯代码 meta-improvement）
- **Evaluation Metrics**: 
  - 给定相同计算预算下的最终性能
  - 达到指定性能的进化步数（效率）
  - meta-evolution 轮数与收益的关系
  - 不同任务分布上的泛化能力
- **Ablation**: 
  - 移除 meta-evolution 的不同 operator
  - 不同 meta-fitness 定义的比较
  - 递归深度（meta / meta-meta / ...）的边际收益

**Expected Contribution**:
- 首个在声明式 DAG 框架中实现 meta-evolution 的工作
- 提出结构化、可控的 meta-evolution 机制（对比 DGM/STOP 的任意代码修改）
- 理论分析：在什么条件下 meta-evolution 收敛且优于固定策略
- 开源实现，可直接在 EgoAgent 上复现

---

### Idea 2: Adaptive Evolution Strategy Selection via Meta-Learning

**Motivation**:

论文 "Inefficiencies of Meta Agents for Agent Design" 揭示了一个核心问题：meta-agent 在 sample-evaluate-iterate 循环中实际上并未有效从历史中学习。这暗示了当前 meta-agent 的"学习"机制有根本缺陷。

同时，EvoX 展示了搜索策略可以与解同步进化，但其策略空间是连续参数化的。在 EgoAgent 的 DAG 空间中，我们需要一种离散结构上的 meta-learning 方法。

**Method**:

1. **Evolution Strategy Portfolio**:
   - 定义一组基础进化算子（如 TextGrad、Random Mutation、Crossover、Guided Refinement）
   - 每个算子在 DAG 上有不同的操作模式
   
2. **Context-Aware Strategy Selection**:
   - 根据当前 evolution context（任务类型、当前性能、历史趋势）选择最佳策略
   - 使用 bandit 算法（UCB1/Thompson Sampling）分配进化预算
   
3. **Strategy Performance Prediction**:
   - 训练轻量级预测器：给定 (current DAG state, task distribution, strategy) 预测改进量
   - 用历史 evolution archive 的数据训练
   - 预测器本身也可以被 meta-evolve

4. **Curriculum-Aware Adaptation**:
   - 在进化早期使用探索性策略（Random Mutation + 大步长修改）
   - 在进化后期使用精细化策略（TextGrad + 小步长优化）
   - 转折点由 meta-learner 自动决定

**Experiment Plan**:

- **Setup**: 多个不同领域的 benchmark suite（coding、math、QA、agent tasks）
- **独立变量**: 策略选择方法（固定单策略 vs. 随机选择 vs. bandit vs. learned predictor）
- **因变量**: 达到目标性能的总计算成本（LLM API calls）
- **Cross-domain Transfer**: 在 domain A 上学到的策略选择是否迁移到 domain B
- **Meta-learning Curve**: 随着 evolution archive 的增长，策略选择是否越来越准确

**Expected Contribution**:
- 回应 "Inefficiencies of Meta Agents" 的批评——证明在正确的 meta-learning 设计下，历史确实能指导未来
- 实用性强：直接减少 evolution 的计算成本
- 可扩展到其他 agent 框架（非 EgoAgent 特定）
- 提供策略选择的理论分析框架

---

### Idea 3: Safety-Aware Meta-Evolution with Provable Non-Degradation

**Motivation**:

"Your Agent May Misevolve: Emergent Risks in Self-evolving LLM Agents" (2025) 指出自进化系统的安全风险——进化可能导致 Agent 行为退化、产生有害输出、或过拟合到窄分布。Meta-evolution 放大了这一风险：如果进化策略本身被错误修改，可能导致灾难性退化。

当前方法要么忽视安全性（DGM、STOP），要么仅有粗粒度的门控（ADAS 的 Bootstrap CI）。我们需要一种在 meta-evolution 中提供形式化非退化保证的方法。

**Method**:

1. **Formal Non-Degradation Certificates**:
   - 定义 safety constraint set S（Agent 必须满足的硬性约束）
   - 每次 meta-evolution 前，证明修改后的 evolution_cycle 不会违反 S
   - 使用 LLM-as-verifier + 构造性证明（类似 Gödel Machine 的原始设想）
   
2. **Hierarchical Safety Gates**:
   - Level 0: Object-level 修改必须通过 task benchmark 门控
   - Level 1: Evolution strategy 修改必须通过"不劣于当前策略"的 meta-benchmark 门控
   - Level 2: Safety constraints 本身不可被进化修改（不可变层）
   
3. **Conservative Meta-Evolution**:
   - 使用 pessimistic evaluation（worst-case over task distribution）而非 average
   - Meta-evolution 只在 pessimistic 改进时才接受修改
   - 维护 "safe fallback" 进化策略——退化时立即切回
   
4. **Diversity Preservation**:
   - 进化 archive 中维护多样性指标
   - 防止 meta-evolution 导致进化策略单一化
   - 使用 Quality-Diversity 算法（MAP-Elites 思想）

**Experiment Plan**:

- **Safety Benchmarks**: 设计专门的退化检测测试集
- **Adversarial Testing**: 故意注入会导致退化的 meta-evolution 候选
- **Comparison**: 
  - 无安全门控的 meta-evolution（预期会退化）
  - 仅有 object-level 门控（可能在 meta-level 退化）
  - 完整的 hierarchical safety gates（预期安全且有效）
- **Long-horizon Evaluation**: 100+ 轮进化后的性能和安全性
- **Distribution Shift**: 任务分布变化时的鲁棒性

**Expected Contribution**:
- 首个在 meta-evolution 中提供形式化安全保证的框架
- 解决"进化可能退化"这一关键阻碍 meta-evolution 实际部署的问题
- Hierarchical safety gates 设计可被其他自进化系统采用
- 连接 AI Safety 和 self-improvement 两个社区

---

## 实验设计

### 总体实验框架

```
┌─────────────────────────────────────────────────────┐
│                  Meta-Evolution Layer                 │
│  ┌──────────────────────────────────────────────┐   │
│  │  Meta-Fitness: evolution improvement rate     │   │
│  │  Meta-Operators: DAG structure mutations      │   │
│  │  Meta-Archive: history of evolution strategies│   │
│  └──────────────────────────────────────────────┘   │
│                         │                            │
│                         ▼                            │
│  ┌──────────────────────────────────────────────┐   │
│  │         Evolution Cycle Harness (DAG)         │   │
│  │  ┌─────┐  ┌──────┐  ┌─────┐  ┌──────────┐  │   │
│  │  │Eval │→│Select│→│Mutate│→│Validate  │  │   │
│  │  └─────┘  └──────┘  └─────┘  └──────────┘  │   │
│  └──────────────────────────────────────────────┘   │
│                         │                            │
│                         ▼                            │
│  ┌──────────────────────────────────────────────┐   │
│  │         Task-Solving Harness (DAG)            │   │
│  │  (被进化的对象)                                │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### Benchmark 选择

| Benchmark | 领域 | 用途 | 指标 |
|-----------|------|------|------|
| SWE-bench Verified (100 subset) | 软件工程 | 主实验 | Resolve Rate |
| HumanEval+ | 代码生成 | 泛化测试 | pass@1 |
| MATH (Level 4-5) | 数学推理 | 跨域迁移 | Accuracy |
| GPQA Diamond | 科学推理 | 难度上限 | Accuracy |
| WebArena | Agent 任务 | 实际场景 | Task Success |
| Custom Meta-Bench | Meta-evaluation | meta-evolution 专用 | Improvement Rate |

### 消融实验

1. **递归深度消融**: 比较 0-level (固定) / 1-level (meta) / 2-level (meta-meta) 的收益
2. **计算预算控制**: 在相同总 LLM 调用次数下比较不同方法
3. **Archive 大小**: meta-archive 的大小对 meta-evolution 效果的影响
4. **安全门控消融**: 移除不同层级的安全机制观察退化程度
5. **策略空间大小**: DAG 修改操作集的丰富度 vs. 进化效率

### 评估指标

- **Primary**: Final performance after N evolution steps
- **Efficiency**: Steps-to-threshold (达到指定性能需要的进化步数)
- **Meta-improvement**: 进化速率随 meta-evolution 轮数的变化
- **Safety**: 退化概率、最大退化幅度、恢复时间
- **Diversity**: 探索的 DAG 结构数量、archive 的覆盖度
- **Generalization**: 跨任务迁移性能

---

## 目标会议与影响力评估

### 目标投稿会议

| 会议 | 截稿时间 | 匹配度 | 理由 |
|------|----------|--------|------|
| **ICML 2027** | Jan 2027 | ⭐⭐⭐⭐⭐ | Meta-learning + Self-improvement 是 ICML 核心话题，DGM/ADAS/EvoX 均投稿于此类会议 |
| **NeurIPS 2027** | May 2027 | ⭐⭐⭐⭐⭐ | Agent + Evolution 方向的最佳归属，STOP/MAE/SICA 均在 NeurIPS |
| **ICLR 2027** | Sep 2026 | ⭐⭐⭐⭐ | 偏向 representation learning，但 self-improvement 也受关注 |
| **AAAI 2027** | Aug 2026 | ⭐⭐⭐ | 更偏应用，如果有强实验结果适合投 |
| **COLM 2027** | TBD | ⭐⭐⭐⭐ | 专注于 Language Model，与 LLM-based evolution 高度匹配 |

### 影响力评估

**学术影响力**:
- 填补 meta-evolution 在 agent 框架中的理论和实验空白
- 连接 evolutionary computation、meta-learning、AI safety 三个社区
- 提供可复现的开源框架（基于 EgoAgent）

**实际影响力**:
- 减少 agent 系统的人工调优需求
- 提供"设置一次，持续改进"的自动化运维方案
- 安全 meta-evolution 为实际部署提供信心

**引用潜力**:
- 近期相关论文引用量：DGM (300+), ADAS (500+), STOP (400+), AlphaEvolve (1000+)
- 预估本工作因其独特角度（声明式 DAG + safety）可获得 100-300 citations in 2 years

### 时间规划

| 阶段 | 时间 | 内容 |
|------|------|------|
| 基础实现 | 2026 Q3 | 在 EgoAgent 上实现 meta-evolution 基础框架 |
| 初步实验 | 2026 Q4 | Idea 1 的主实验 + Idea 3 的安全机制 |
| 论文撰写 | 2027 Q1 | 瞄准 ICML 2027 投稿 |
| 扩展实验 | 2027 Q1-Q2 | Idea 2 的 meta-learning 策略选择 |
| 第二篇投稿 | 2027 Q2 | 瞄准 NeurIPS 2027 |

---

## 参考文献列表

1. Yin, X., Wang, X., Pan, L., Wan, X., & Wang, W. Y. (2024). **Gödel Agent: A Self-Referential Agent Framework for Recursive Self-Improvement**. arXiv:2410.04444.

2. Zhang, J., Lu, C., & Clune, J. (2025). **Darwin Gödel Machine: Open-Ended Evolution of Self-Improving Agents**. arXiv:2505.22954. Sakana AI.

3. Zelikman, E., Lorch, E., Mackey, L., & Kalai, A. (2024). **Self-Taught Optimizer (STOP): Recursively Self-Improving Code Generation**. NeurIPS 2024. Stanford & Microsoft Research.

4. Hu, S., Lu, C., & Clune, J. (2024). **Automated Design of Agentic Systems (ADAS)**. arXiv:2408.08435. ICML 2025. UBC & Vector Institute.

5. Li, Y. et al. (2025). **SICA: A Self-Improving Coding Agent**. NeurIPS 2025. arXiv:2504.15228.

6. SkyDiscover AI. (2025). **EvoX: Meta-Evolution for Automated Discovery**. arXiv:2602.23413.

7. (2026). **MetaEvo: A Meta-Optimization Framework for Experience-Driven Agent Evolution**. arXiv:2606.07603.

8. Zhang, G., Ren, H., Zhou, W., & Yan, S. (2025). **MemEvolve: Meta-Evolution of Agent Memory Systems**. arXiv:2512.18746.

9. Google DeepMind. (2025). **AlphaEvolve: A Coding Agent for Scientific and Algorithmic Discovery**. arXiv:2506.13131.

10. (2025). **Multi-Agent Evolve (MAE): LLM Self-Improve through Co-Evolution**. arXiv:2510.23595. NeurIPS 2025.

11. AIMING Lab. (2025). **Agent0: Unleashing Self-Evolving Agents from Zero Data via Tool-Integrated Reasoning**. arXiv:2511.16043.

12. Gong et al. (2025). **Polymath: A Self-Optimizing Agent with Dynamic Hierarchical Workflow**. arXiv:2508.02959.

13. (2025). **SE-Agent: Self-Evolution Trajectory Optimization in Multi-Step Reasoning with LLM-Based Agents**. arXiv:2508.02085.

14. (2024). **Self-Developing: Algorithm Discovery for Recursive Self-Improvement through Reinforcement Learning**. arXiv:2410.15639.

15. (2025). **Inefficiencies of Meta Agents for Agent Design**. arXiv:2510.06711.

16. (2025). **MetaAgent: Toward Self-Evolving Agent via Tool Meta-Learning**. arXiv:2508.00271.

17. Fang, J. et al. (2025). **A Comprehensive Survey of Self-Evolving AI Agents: A New Paradigm Bridging Foundation Models and Lifelong Agentic Systems**. arXiv:2508.07407.

18. Zhou et al. (2025). **A Survey of Self-Evolving Agents: On Path to Artificial Super Intelligence**. arXiv:2507.21046.

19. (2025). **Your Agent May Misevolve: Emergent Risks in Self-evolving LLM Agents**. arXiv:2509.26354.

20. LLaMEA. (2024). **LLaMEA: A Large Language Model Evolutionary Algorithm for Automatically Generating Metaheuristics**. IEEE.

21. (2025). **AgentSquare: Automatic LLM Agent Search in Modular Design Space**. arXiv:2410.06153.

22. Meta Superintelligence Labs. (2025). **Bootstrapping Task Spaces for Self-Improvement (Exploratory Iteration)**. arXiv:2509.04575.

---

*本文档基于 2024-2026 年间 22 篇核心论文的系统调研，结合 EgoAgent 框架的具体架构特点撰写。*
