# 方向6: Multi-Agent Self-Play Evolution

## 核心问题

在 LLM Agent 能力进化的研究前沿，一个根本性问题是：**如何在无需持续人类监督的情况下，让 Agent 系统实现自主、持续的能力提升？** 这个问题可以进一步分解为三个子问题：

1. **数据瓶颈问题**：高质量训练数据（尤其是人工标注的偏好数据）成本高昂且难以规模化，如何摆脱对外部数据的依赖？
2. **能力天花板问题**：单一模型自我改进会快速收敛到局部最优，如何突破 self-improvement 的 plateau？
3. **评估信号退化问题**：当 Agent 能力逐渐增强后，固定的评估器（Judge）能否持续提供有效的梯度信号？评估者自身如何保持校准？

EgoAgent 的三角色架构——Proposer（出题者）、Solver（解题者）、Judge（评审者）——本质上构成了一个多角色博弈系统。这与 AlphaGo 的自博弈训练范式高度类似，但应用场景从棋盘博弈拓展到了开放域 LLM Agent 能力进化。核心挑战在于：**开放域任务不具备棋类博弈的完美信息和确定性胜负判定**，因此需要全新的理论框架和实践方法。

---

## 相关论文综述

### 1. Multi-Agent Evolve (MAE): LLM Self-Improve through Co-evolution
- **作者/机构**: University of Illinois at Urbana-Champaign, Peking University, NVIDIA (2025)
- **发表**: arXiv 2510.23595
- **核心思想**: 提出与 EgoAgent 最为相似的三角色框架（Proposer, Solver, Judge），三者从单一 LLM 实例化，通过 RL 优化各自行为。Proposer 学习生成能挑战 Solver 的问题，Solver 学习解题，Judge 提供评估信号形成自奖励闭环。
- **关键结果**: 在 Qwen2.5-3B-Instruct 上实现平均 4.54% 的多基准提升，且无需人类标注或领域特定验证器。
- **与 EgoAgent 的关系**: MAE 是最直接的对标工作。EgoAgent 可在此基础上引入 TextGrad（符号梯度）替代 RL 进行优化，并扩展到更复杂的 Agent 任务（非纯 QA）。

### 2. PopuLoRA: Co-Evolving LLM Populations for Reasoning Self-Play
- **作者/机构**: Vmax (2026)
- **发表**: arXiv 2605.16727
- **核心思想**: 引入种群级别的协同进化框架，使用多个 LoRA 适配器维护一个进化种群。教师团队生成可验证任务，学生团队解答。基于 TrueSkill 评级的 Prioritized Fictitious Self-play 确保在实力匹配的对手间学习。
- **关键结果**: 在 HumanEval+、MBPP+、LiveCodeBench 等代码基准和 AIME 24/25、MATH 等数学基准上超越单 Agent 自博弈基线。展现了典型的"军备竞赛"特征——学生解题率振荡而非单调上升。
- **与 EgoAgent 的关系**: PopuLoRA 的种群多样性维护机制可以直接借鉴到 EgoAgent 的 Proposer 多样性设计中，防止 Proposer 退化到生成过于简单或重复的任务。

### 3. SOAR: Self-Optimization via Asymmetric RL
- **作者/机构**: 2026 (Teaching Models to Teach Themselves: Reasoning at the Edge of Learnability)
- **发表**: arXiv 2601.18778
- **核心思想**: 异构教师-学生元强化学习框架。教师模型生成合成问题，通过学生在目标难题上的进步作为教师的奖励信号。核心洞察：让模型学会出"刚好在可学习边缘"的题。
- **关键结果**: 在 MATH 和 HARP 的困难子集上，自生成问题带来 4× pass@1 和 2× pass@32 的提升。
- **与 EgoAgent 的关系**: SOAR 的"可学习边缘"概念可直接指导 EgoAgent Proposer 的难度控制策略——出题既不能太难（无信号）也不能太简单（无提升）。

### 4. SPAG: Self-Playing Adversarial Language Game Enhances LLM Reasoning
- **作者/机构**: Tencent AI Lab (2024)
- **发表**: NeurIPS 2024
- **核心思想**: 设计"Adversarial Taboo"对抗语言游戏，让 LLM 分别扮演攻击者（诱导对手说出目标词）和防守者，通过自博弈 RL 提升推理能力。
- **关键结果**: 在 LLaMA-2-7B 和 Baichuan-2-13B 上，游戏训练后在 BBH 等广泛推理基准上均匀提升。迭代自博弈可持续促进推理能力。
- **与 EgoAgent 的关系**: SPAG 证明了"通过对抗博弈训练可以涌现通用推理能力"这一关键假设，为 EgoAgent 的博弈驱动进化提供了实证支撑。

### 5. SAGE: Self-Play Adversarial Games Enhance LLM Reasoning Capabilities
- **作者/机构**: 2025
- **发表**: OpenReview (ICLR 2025 submission)
- **核心思想**: 两个模型实例进行非对称博弈——Setter 生成问题并预测答案，Opponent 独立解题。Setter 仅在自己答对且 Opponent 答错时获得正奖励，激励生成"可解但有挑战"的问题。
- **关键结果**: 在 Code-Game（Python 程序执行验证）和 Math-Game 两个领域验证有效性。自然地瞄准模型能力的前沿边界。
- **与 EgoAgent 的关系**: SAGE 的非对称奖励设计可以直接融入 EgoAgent 的 Proposer 奖励函数设计——Proposer 应生成"Solver 能学但当前做不对"的任务。

### 6. SPC: Evolving Self-Play Critic via Adversarial Games for LLM Reasoning
- **作者/机构**: 2025
- **发表**: OpenReview
- **核心思想**: Generator 和 Critic 进行对抗博弈——Generator 试图欺骗 Critic，Critic 试图识别 Generator 的错误。基于博弈结果的 RL 训练驱动双方持续自进化。
- **关键结果**: 在 ProcessBench、PRM800K、DeltaBench 三个推理过程基准上逐步提升错误检测能力。
- **与 EgoAgent 的关系**: SPC 的 Critic 进化机制直接对应 EgoAgent 的 Judge 进化问题——Judge 需要在 Solver 能力提升的过程中同步进化评估能力。

### 7. SPIN: Self-Play Fine-Tuning Converts Weak Language Models to Strong Language Models
- **作者/机构**: UCLA (2024)
- **发表**: ICML 2024
- **核心思想**: LLM 与自身前一迭代版本进行自博弈，当前版本作为主玩家学习区分自身生成与人类数据，前一版本作为对手。无需外部标注器。
- **关键结果**: SPIN 迭代 0 即可与使用 62k UltraFeedback 偏好对训练的 DPO 持平，迭代 1 在多数排行榜任务上超越 DPO。
- **与 EgoAgent 的关系**: SPIN 的迭代自博弈收敛性分析为 EgoAgent 的理论分析提供了基础——证明了自博弈微调可以逐步接近最优策略。

### 8. Self-RedTeam: Chasing Moving Targets with Online Self-Play RL for Safer Language Models
- **作者/机构**: 2025
- **发表**: arXiv 2506.07468
- **核心思想**: 单一模型交替扮演攻击者和防守者，通过完全在线的多 Agent RL 实现安全训练。攻击者将种子 prompt 转化为隐蔽对抗攻击，防守者学习抵抗。
- **关键结果**: 实现攻击者和防守者的协同进化，对应 Nash 均衡即为安全状态。
- **与 EgoAgent 的关系**: Self-RedTeam 的在线自博弈范式展示了"co-evolution 达到均衡即为期望状态"的博弈论分析框架，可迁移到 EgoAgent 的收敛性证明中。

### 9. DTE: Debate, Train, Evolve - Self-Evolution of Language Model Reasoning
- **作者/机构**: 2025
- **发表**: arXiv 2505.15734
- **核心思想**: 无需 ground-truth 的训练框架，使用多 Agent 辩论轨迹来进化单一语言模型。提出 REFLECT-CRITIQUE-REFINE 提示策略改善辩论质量。
- **关键结果**: 在七个推理基准、六个开源模型上实现显著改进。
- **与 EgoAgent 的关系**: DTE 的辩论轨迹可以视为一种丰富的"梯度信号"，启发 EgoAgent 的 Judge 不仅给分数，还应生成结构化的 critique 作为 TextGrad 的输入。

### 10. SALF: Symbolic Adversarial Learning Framework
- **作者/机构**: MBZUAI (2025)
- **发表**: EMNLP 2025
- **核心思想**: 通过 Agent 符号学习实现对抗训练范式，生成 Agent 和检测 Agent 通过符号梯度（非数值更新）迭代对抗进化。模拟反向传播但操作对象是自然语言表示的权重、损失和梯度。
- **关键结果**: 生成的假新闻可使 SOTA 检测器性能下降 53.4%（中文）和 34.2%（英文）；同时检测器也提升 7.7%。
- **与 EgoAgent 的关系**: SALF 是 TextGrad 在对抗设置中的直接应用案例，验证了"符号梯度+对抗博弈"的可行性，这正是 EgoAgent 的技术路线。

### 11. CORY: Coevolving with the Other You
- **作者/机构**: 2024
- **发表**: arXiv 2410.06101
- **核心思想**: 将 LLM 复制为 pioneer 和 observer 两个自主 Agent，构造为 Stackelberg 博弈。Pioneer 生成回答，Observer 基于 query 和 pioneer 回答再生成。两者协同训练。
- **关键结果**: 成功将单 Agent RL 微调转化为多 Agent RL 问题并实现协同进化。
- **与 EgoAgent 的关系**: Stackelberg 博弈形式化为 EgoAgent 的 Proposer-Solver 交互提供了博弈论建模工具。

### 12. SEC: Self-Evolving Curriculum for LLM Reasoning
- **作者/机构**: 2025
- **发表**: arXiv 2505.14970
- **核心思想**: 将课程选择形式化为非平稳多臂老虎机问题，在 RL 微调过程中并发学习课程策略。自动在不同难度/类别间分配训练资源。
- **关键结果**: 不依赖人工设计的课程启发式，自动发现最优训练课程。
- **与 EgoAgent 的关系**: SEC 的自适应课程机制可以指导 Proposer 如何动态调整出题难度和领域分布。

---

## 博弈论视角分析

### 三角色博弈的形式化建模

EgoAgent 的三角色系统可以形式化为一个**三人混合博弈**：

**定义**：设策略空间为 $\Pi_P$（Proposer）、$\Pi_S$（Solver）、$\Pi_J$（Judge），系统目标是找到策略组合 $(\pi_P^*, \pi_S^*, \pi_J^*)$ 使得：

- Proposer 最大化任务的"信息增益"：生成的任务恰好在 Solver 能力边缘
- Solver 最大化在 Proposer 生成任务上的表现
- Judge 最大化评估准确性（与真实质量信号的一致性）

这形成了一个**协作-竞争混合博弈**：
- Proposer vs Solver：零和成分（Proposer 出难题，Solver 解题）
- Judge vs (Proposer, Solver)：协作成分（Judge 提供准确信号帮助系统进化）
- Proposer vs Judge：潜在对抗（Proposer 可能生成难以评估的模糊任务）

### 均衡分析

参照 SPIN 的收敛性证明和 Self-RedTeam 的 Nash 均衡分析：

1. **理想均衡状态**：Proposer 生成的任务精确匹配 Solver 的学习前沿（solve rate ≈ 50%）；Solver 在所有生成任务上的表现接近最优；Judge 的评估与 ground-truth 高度一致。

2. **潜在退化模式**：
   - **Mode Collapse**（Proposer 退化为生成同质化简单任务）
   - **评估欺骗**（Solver 学会生成"看起来好但实际不好"的回答来欺骗 Judge）
   - **Judge 过拟合**（Judge 对特定模式过度奖励）

3. **军备竞赛动态**：参照 PopuLoRA 的发现，健康的协同进化表现为振荡而非单调收敛——这是"genuine co-evolutionary arms race"的标志。

### 与经典博弈论的联系

| 经典范式 | EgoAgent 对应 | 核心机制 |
|---------|-------------|---------|
| AlphaGo 自博弈 | Solver 自我挑战 | 通过历史版本对弈提升 |
| GAN 生成器-判别器 | Proposer-Judge 对抗 | 动态难度调节 |
| PAIRED (minimax regret) | Proposer 的出题策略 | 最大化 Solver 的后悔值 |
| Stackelberg 博弈 | Proposer→Solver 序贯决策 | 领导者-跟随者结构 |
| 协作博弈 | Judge 信号共享 | 整体系统进化目标对齐 |

---

## EgoAgent 三角色系统的独特优势

相比现有工作，EgoAgent 的三角色系统具有以下独特优势：

### 1. TextGrad 驱动的符号梯度优化

不同于 MAE、SPAG 等使用传统 RL（PPO/RLOO）进行策略优化，EgoAgent 采用 TextGrad 进行符号梯度下降。这意味着：
- **可解释性**：每次进化步骤都有自然语言形式的"梯度"解释为什么要做某种修改
- **高效性**：无需大规模 rollout 和采样，TextGrad 在少量样本上即可产生有效优化方向
- **灵活性**：可以优化任意文本形式的 Agent 组件（prompt、策略、工具使用模式等）

### 2. Agent 任务的开放域特性

MAE 聚焦于数学/推理 QA，SPAG 聚焦于特定语言游戏，而 EgoAgent 面向**通用 Agent 任务**：
- 工具使用（API 调用、代码执行）
- 多步规划与执行
- 环境交互与反馈处理
- 长链推理与回溯

这使得 Proposer 的任务空间远大于简单 QA，也使得 Judge 的评估维度更加丰富。

### 3. 三角色共进化的稳定性

相比两角色系统（如 GAN、SPIN），三角色系统引入了天然的"稳定器"：
- Judge 作为独立第三方提供校准信号，防止 Proposer-Solver 对进入退化均衡
- Proposer 的存在使 Solver 的训练信号始终具有新鲜度，避免数据耗尽
- 三角色的相互制约降低了任一角色过度支配的风险

### 4. 可扩展的层级化进化

EgoAgent 的进化可以自然地扩展为层级结构：
- Level 1: 基础能力进化（单步工具调用）
- Level 2: 组合能力进化（多步规划）
- Level 3: 元能力进化（学习如何学习新工具）

每个层级可以有独立的 Proposer-Solver-Judge 三元组，形成"进化的进化"。

---

## 具体 Research Ideas（3个）

### Idea 1: Adaptive Difficulty Frontier via TextGrad Proposer Evolution

**核心思想**：设计一个 TextGrad-optimized Proposer，使其自动学习在 Solver 的"可学习前沿"（Zone of Proximal Development, ZPD）生成任务。

**技术方案**：
1. **ZPD 估计**：维护 Solver 在不同任务维度（复杂度、工具数、步骤数）上的能力画像 $C_S$
2. **Proposer 目标函数**：
   ```
   L_P = -E[I(task) · 1{solve_rate(task) ∈ [0.3, 0.7]}]
   ```
   其中 $I(task)$ 是任务的信息增益（新颖性、多样性），约束 solve rate 在"既不太简单也不太难"的范围内。
3. **TextGrad 反馈循环**：
   - Judge 评估 Solver 在新任务上的表现
   - 基于评估结果，TextGrad 生成针对 Proposer 的 prompt 梯度
   - 梯度指示"应该增加什么维度的难度"或"应该引入什么新类型的挑战"
4. **多样性保持**：借鉴 PopuLoRA 的 TrueSkill 匹配和 Quality-Diversity 思想，维护任务 archive，确保 Proposer 覆盖能力空间的不同区域。

**与现有工作的差异**：
- SOAR 使用 meta-RL 训练教师，我们使用 TextGrad，更轻量且不需要大量 rollout
- SAGE 使用固定的非对称奖励，我们使用自适应的 ZPD 估计
- SEC 处理固定任务集上的选择问题，我们处理开放域任务的生成问题

### Idea 2: Judge Co-Evolution with Confidence Calibration

**核心思想**：解决"Judge 能力退化"问题——当 Solver 变强后，Judge 的区分能力会下降。设计 Judge 的协同进化机制，同时保持评估校准。

**技术方案**：
1. **对抗式 Judge 训练**：
   - Solver 生成多个候选回答（好/坏），Judge 需要正确排序
   - 引入"Judge Adversary"：专门生成容易误导 Judge 的 borderline cases
   - 通过 TextGrad 优化 Judge 的评估 prompt 和 rubric
2. **校准机制**：
   - 维护一组 anchor examples（有已知 ground-truth 的标定样本）
   - 定期检验 Judge 在 anchor 上的表现，发现校准偏移时触发 recalibration
   - 引入 "confidence-weighted evaluation"：Judge 对自己不确定的评估降权
3. **多 Judge 集成**：
   - 使用多个 Judge variant（不同 rubric、不同评估角度）
   - 通过 majority voting + disagreement detection 提升可靠性
   - 借鉴 LLM-as-Judge 文献中的 dual-model consensus 发现（76%→显著提升）

**与现有工作的差异**：
- SPC 只训练 Critic 检测错误，我们同时训练 Judge 的评估校准
- LLM-as-Judge 文献关注静态评估，我们关注评估者与被评估者的动态共进化
- Self-RedTeam 的攻防共进化可类比，但我们引入了第三方校准锚点

### Idea 3: Population-Based Tri-Role Tournament Evolution

**核心思想**：将三角色系统从单一实例扩展到种群级别，通过锦标赛选择和交叉实现更高效的进化搜索。

**技术方案**：
1. **种群初始化**：
   - 维护 N 个 Proposer variants（不同出题风格/领域/难度偏好）
   - 维护 M 个 Solver variants（不同策略/工具偏好/推理风格）
   - 维护 K 个 Judge variants（不同评估标准/关注维度）
   - 通过 LoRA 实现低成本的种群维护（参照 PopuLoRA）
2. **锦标赛机制**：
   - 每轮随机配对 (Proposer_i, Solver_j, Judge_k)
   - 评估三元组的整体"进化效率"（Solver 的改进速度）
   - 表现好的个体保留，差的被淘汰并由优秀个体变异产生
3. **交叉与变异**：
   - LoRA 参数的加权组合（策略交叉）
   - TextGrad 指导的 prompt 变异（有方向的搜索）
   - 基于 fitness landscape 的适应性变异率调节
4. **共生进化动态**：
   - 观察并利用"红皇后效应"：Solver 进化后 Proposer 必须跟上
   - 引入"生态位分化"：不同 Proposer 专注不同难度/领域，避免种群同质化

**与现有工作的差异**：
- PopuLoRA 只有教师-学生两角色，我们扩展为三角色种群
- 传统遗传算法缺乏梯度信号，我们结合 TextGrad 实现"有方向的进化"
- MAE 使用单一模型实例化三角色，我们使用种群提供更强的探索能力

---

## 实验设计

### 基准选择

1. **Agent 能力基准**：
   - WebArena / MiniWoB++（Web 交互任务）
   - SWE-bench（软件工程任务）
   - GAIA（通用 AI Agent 评估）
   - AgentBench（综合 Agent 能力）

2. **推理基准**（用于消融研究）：
   - MATH / GSM8K（数学推理）
   - HumanEval+ / MBPP+（代码生成）
   - BBH（Big-Bench Hard，广泛推理）

3. **自建动态基准**：
   - 使用进化后的 Proposer 生成持续更新的挑战任务集
   - 跟踪随时间变化的 difficulty frontier 移动

### 实验设置

**Baseline 对比**：
- 单一模型 self-improvement（SPIN 范式）
- 两角色系统（仅 Proposer-Solver，无 Judge 共进化）
- 固定 Proposer + 进化 Solver（消融 Proposer 进化的效果）
- 固定 Judge + 进化 Proposer/Solver（消融 Judge 共进化的效果）
- MAE 原始方法（RL 替代 TextGrad）

**关键指标**：
- 进化效率：达到目标性能所需的迭代次数
- 进化上限：最终稳定性能
- 任务多样性：Proposer 生成任务的覆盖度（使用 embedding 空间的 coverage 度量）
- Judge 校准度：Judge 评分与人类评估的 Spearman 相关系数
- 收敛稳定性：性能曲线的方差和振荡幅度

**计算预算**：
- 小规模验证：Qwen2.5-3B / LLaMA-3-8B，4×A100，100 进化轮次
- 中规模实验：Qwen2.5-7B / LLaMA-3-70B（作为 Judge），8×A100，500 进化轮次
- 大规模实验（如果资源允许）：种群 N=5, M=5, K=3 的完整锦标赛

---

## 收敛性分析方案

### 理论分析路径

1. **Fixed-Point Theorem 方法**（参照 SPIN）：
   - 定义三角色联合策略空间上的映射 $T: (\pi_P, \pi_S, \pi_J) \mapsto (\pi_P', \pi_S', \pi_J')$
   - 证明在合适条件下 $T$ 是压缩映射，存在唯一不动点
   - 条件：TextGrad 的学习率足够小、Judge 的校准误差有界

2. **Nash 均衡存在性**（参照 Self-RedTeam）：
   - 将系统建模为混合策略博弈
   - 利用 Kakutani 不动点定理证明 Nash 均衡存在
   - 分析均衡的性质：是否对应期望的"最优进化状态"

3. **Regret Bound 分析**（参照 PAIRED/minimax regret）：
   - 证明经过 T 轮进化后，Solver 的 regret 相对于 oracle 策略以 $O(\sqrt{T})$ 速度增长
   - Proposer 的 regret 相对于最优课程以类似速度有界

### 实证收敛性监控

1. **进化曲线追踪**：
   - 绘制 Solver 在固定测试集上的性能 vs 进化轮次
   - 绘制 Proposer 生成任务的平均难度 vs 进化轮次
   - 绘制 Judge 评估精度 vs 进化轮次

2. **退化检测指标**：
   - Proposer 多样性指标（生成任务的 pairwise similarity 不应过高）
   - Solver exploit detection（在 Judge 上的得分高但实际质量低的比例）
   - Judge calibration drift（anchor examples 上的周期性检验）

3. **早停与重启策略**：
   - 当检测到退化模式时，引入随机扰动（prompt 变异）
   - 借鉴 PopuLoRA 的种群重启机制

---

## 目标会议与影响力评估

### 目标会议（按优先级排序）

1. **ICML 2026 / NeurIPS 2026**（旗舰 ML 会议）
   - 投稿角度：Multi-agent co-evolution 的理论框架 + 大规模实证
   - 卖点：TextGrad + Self-Play 的首次结合；博弈论收敛保证

2. **ICLR 2026**
   - 投稿角度：Self-improving agents without human supervision
   - 卖点：开放域 Agent 任务的自博弈进化（超越纯 QA）

3. **ACL 2026 / EMNLP 2026**（NLP 顶会）
   - 投稿角度：TextGrad 在多角色协作系统中的应用
   - 卖点：符号梯度驱动的 Agent 能力涌现

4. **AAMAS 2026**（多 Agent 系统专业会议）
   - 投稿角度：Tri-role co-evolution game theory
   - 卖点：三角色混合博弈的均衡分析

### 影响力评估

**学术影响**：
- 建立"TextGrad + Self-Play"这一新范式，填补符号优化与博弈进化的交叉空白
- 为 Agent 系统的自主进化提供理论框架（收敛性保证）
- 推动 LLM-as-Judge 从静态评估到动态共进化的研究方向

**工业影响**：
- 大幅降低 Agent 训练对人类标注数据的依赖
- 提供可持续的 Agent 能力提升方案（自我进化闭环）
- Judge 校准技术可直接应用于 LLM 产品的自动化质量监控

**预期被引数据**：
- 鉴于 MAE（2025.10）已获得广泛关注，SPAG（NeurIPS 2024）被引快速增长
- 预期本方向论文发表后 1 年内达到 50-100 次引用

---

## 参考文献列表

1. **[MAE]** Multi-Agent Evolve: LLM Self-Improve through Co-evolution. arXiv:2510.23595, 2025. (UIUC, Peking University, NVIDIA)

2. **[PopuLoRA]** PopuLoRA: Co-Evolving LLM Populations for Reasoning Self-Play. arXiv:2605.16727, 2026. (Vmax)

3. **[SOAR]** Teaching Models to Teach Themselves: Reasoning at the Edge of Learnability. arXiv:2601.18778, 2026.

4. **[SPAG]** Self-playing Adversarial Language Game Enhances LLM Reasoning. NeurIPS 2024. (Tencent AI Lab)

5. **[SAGE]** SAGE: Self-Play Adversarial Games Enhance Large Language Model Reasoning Capabilities. OpenReview, 2025.

6. **[SPC]** SPC: Evolving Self-Play Critic via Adversarial Games for LLM Reasoning. OpenReview, 2025.

7. **[SPIN]** Self-Play Fine-Tuning Converts Weak Language Models to Strong Language Models. ICML 2024. (UCLA)

8. **[Self-RedTeam]** Chasing Moving Targets with Online Self-Play Reinforcement Learning for Safer Language Models. arXiv:2506.07468, 2025.

9. **[DTE]** Debate, Train, Evolve: Self-Evolution of Language Model Reasoning. arXiv:2505.15734, 2025.

10. **[SALF]** A Symbolic Adversarial Learning Framework for Evolving Fake News Generation and Detection. EMNLP 2025. (MBZUAI)

11. **[CORY]** Coevolving with the Other You: Fine-Tuning LLM with Sequential Cooperative Multi-Agent Reinforcement Learning. arXiv:2410.06101, 2024.

12. **[SEC]** Self-Evolving Curriculum for LLM Reasoning. arXiv:2505.14970, 2025.

13. **[TextGrad]** TextGrad: Automatic "Differentiation" via Text. Stanford HAI / ICML 2024. (Stanford University)

14. **[GPT-Red]** GPT-Red: Unlocking Self-Improvement for Robustness. OpenAI, 2025.

15. **[Constitutional AI]** Constitutional AI: Harmlessness from AI Feedback. Anthropic, 2022.

16. **[PAIRED]** Emergent Complexity and Zero-shot Transfer via Unsupervised Environment Design. NeurIPS 2020.

17. **[SPELL]** SPELL: Self-Play Reinforcement Learning for Evolving Long-Context Language Models. 2025.

18. **[DebateQD]** Optimizing for Persuasion Improves LLM Generalization: Evidence from Quality-Diversity Evolution of Debate Strategies. arXiv:2510.05909, 2025.
