# 方向5: Lifelong Learning & Principle-Based Memory

> 撰写日期: 2026-07-30  
> 研究方向: 基于原则蒸馏的持续学习  
> 目标: 为 EgoAgent 的 Principle Library 机制寻找学术基础与突破方向

---

## 核心问题

LLM Agent 在实际部署中面临一个根本性矛盾：**模型参数固定，但任务环境持续变化**。传统深度学习的持续学习（Continual Learning）通过梯度更新来适应新任务，但这在 LLM Agent 的推理时框架中不可行——我们不能每次遇到新经验就微调一个数十亿参数的模型。

核心挑战可以分解为：

1. **经验保留 vs 遗忘**：如何在不更新权重的情况下，让 Agent 从历史交互中持续积累有用知识？
2. **抽象泛化 vs 具体记忆**：原始轨迹太长无法全部存储，但过度抽象又会丢失关键细节，如何在信息压缩与保真之间取得平衡？
3. **知识冲突 vs 一致性**：当新经验与旧原则矛盾时，如何优雅地进行知识更新而不破坏已有的有效策略？
4. **跨任务迁移 vs 领域特异性**：从任务 A 中学到的原则如何有效迁移到任务 B，同时避免负迁移？
5. **记忆增长 vs 检索效率**：随着经验不断积累，如何防止记忆库膨胀导致检索噪音增大、响应延迟升高？

EgoAgent 的 Principle Library 提出了一种独特的解决范式：不记忆原始轨迹，而是蒸馏出可重用的行为准则（procedural memory），配合 Laplace 平滑动态评分来管理原则质量。这种方法本质上是一种**无梯度的持续学习**——通过自然语言层面的知识提炼来实现经验积累。

---

## 相关论文综述

### 1. Reflexion: Language Agents with Verbal Reinforcement Learning (NeurIPS 2023)

**作者**: Shinn et al.  
**核心思想**: 提出"语言强化学习"范式，Agent 不通过权重更新学习，而是通过自然语言反思来积累经验。Reflexion Agent 在任务失败后生成文本形式的反思（verbal feedback），存储在 episodic memory buffer 中，用于指导后续决策。

**关键机制**:
- Actor-Evaluator-Self-Reflection 三组件架构
- 反思文本作为情景记忆注入到后续 trial 的上下文中
- 支持标量反馈和自由文本反馈两种信号源

**与 EgoAgent 的关系**: Reflexion 的反思是针对单个任务的情景记忆（"上次我犯了什么错"），而 EgoAgent 的 Principle Library 更进一步将反思抽象为跨任务的程序性记忆（"遇到这类情况应该怎么做"）。Reflexion 是原则蒸馏的前驱——从"记住错误"到"提炼规则"的自然演进。

---

### 2. ExpeL: LLM Agents Are Experiential Learners (AAAI 2024)

**作者**: Zhao, Huang, Xu, Lin, Liu, Huang  
**核心思想**: Agent 自主从训练任务中收集经验，通过比较成功与失败轨迹提取自然语言 insights（洞察），存入经验池供推理时检索使用。

**关键机制**:
- 双层经验存储：具体轨迹 + 抽象 insights
- 成功/失败对比分析提取通用规则
- 经验在推理时作为 few-shot 示例或 insight 提示注入
- 无需微调，纯推理时学习

**与 EgoAgent 的关系**: ExpeL 的 insight extraction 与 EgoAgent 的 principle distillation 高度相似——都是从轨迹中蒸馏出可复用的自然语言知识。EgoAgent 的优势在于引入了 Laplace 平滑评分机制对原则进行动态质量管理，而 ExpeL 缺乏原则质量的量化评估和淘汰机制。

---

### 3. ICAL: Continual Learning of Multimodal Agents by Transforming Trajectories into Actionable Insights (2024)

**作者**: CMU & Google DeepMind  
**核心思想**: In-Context Abstraction Learning (ICAL) 让 VLM Agent 将次优轨迹迭代改进，生成包含优化动作和认知抽象（因果关系、任务分解、常见陷阱等）的高质量记忆条目。

**关键机制**:
- 从次优演示中提取四类认知抽象：因果关系、任务原则、常见陷阱、行动模式
- 人类反馈引导的轨迹优化循环
- 记忆集 M 持续扩展，新例子的加入带来单调性能提升
- 跨任务迁移：在一个领域学到的抽象可应用于相似领域

**与 EgoAgent 的关系**: ICAL 证明了"从轨迹中蒸馏抽象知识"的有效性，其四类认知抽象可以丰富 EgoAgent 的原则类型体系。目前 EgoAgent 仅区分 guiding/cautionary 两类原则，可以扩展为更细粒度的认知维度。

---

### 4. MemGPT: Towards LLMs as Operating Systems (2023, Letta Framework 2024)

**作者**: UC Berkeley Sky Lab  
**核心思想**: 借鉴操作系统的虚拟内存管理，将 LLM 的上下文窗口视为"主存"，外部存储视为"磁盘"，通过 paging 机制实现无限长上下文的错觉。

**关键机制**:
- 分层存储：Main Context (工作记忆) → External Storage (长期记忆)
- Agent 自主决定何时将信息写入/读取外部存储
- 事件驱动的内存管理函数调用
- 支持跨会话的持久化状态

**与 EgoAgent 的关系**: MemGPT 关注的是**信息管理的机制层**（何时存、何时取），而 EgoAgent 的 Principle Library 关注的是**知识表示层**（存什么形式的信息）。两者互补：可以用 MemGPT 的分层管理思想来组织 Principle Library 的存储架构——高频原则放入 working memory，低频原则放入冷存储。

---

### 5. AdMem: Advanced Memory for Task-solving Agents (2026)

**作者**: arxiv 2606.06787  
**核心思想**: 提出三类记忆系统的完整实现：情景记忆（过去事件摘要）、语义记忆（一般性知识和事实）、程序性记忆（决策指导），三者协同支撑 Agent 的任务解决。

**关键机制**:
- 程序性记忆：从每次行动和结果观察中提取决策指导，编码为结构化条目
- 情景记忆：事件摘要存储，提供历史上下文
- 语义记忆：领域知识和事实，作为决策的背景知识
- 三类记忆的动态交互和互相促进

**与 EgoAgent 的关系**: AdMem 的程序性记忆定义与 EgoAgent 的 Principle Library 高度一致——都是"从过去行为中提取的决策指导"。AdMem 提供了理论框架来理解 Principle Library 在认知架构中的定位：它是三种记忆中最具泛化能力的一种。

---

### 6. AutoGuide: Automated Generation and Selection of Context-Aware Guidelines (2024)

**作者**: KAIST  
**核心思想**: 从离线经验中自动生成条件化的指导原则（"在 X 情况下，应该做 Y"），每条原则有明确的适用上下文描述，推理时根据当前状态选择相关原则注入。

**关键机制**:
- 条件化结构：每条 guideline 包含"适用上下文"和"建议行动"
- 状态摘要模块：将复杂环境状态压缩为可匹配的描述
- 指南抽取模块：从成功/失败轨迹中提取适用规则
- 指南选择模块：根据当前任务上下文检索最相关的规则

**与 EgoAgent 的关系**: AutoGuide 的条件化结构是 EgoAgent Principle Library 可以直接借鉴的设计——当前 EgoAgent 的原则是无条件的（"做 X"），可以增强为条件化的（"当遇到 Y 情况时，做 X"），提高检索精确度和适用性。

---

### 7. AutoRefine: From Trajectories to Reusable Expertise for Continual LLM Agent Refinement (2025)

**作者**: arxiv 2601.22758  
**核心思想**: 受批量强化学习启发，从轨迹批次中（而非单条轨迹）提取可泛化的策略模式，通过交叉轨迹分析识别通用策略。

**关键机制**:
- 批量提取策略：每 K 个任务执行一次批量原则蒸馏（默认 K=10）
- 交叉轨迹分析：从多条轨迹的共同模式中提取更稳健的原则
- 持续精炼：已有原则随新经验不断更新和精炼
- 区分"决策点"与"执行模式"的分层抽取

**与 EgoAgent 的关系**: AutoRefine 的批量提取策略解决了 EgoAgent 当前逐条蒸馏可能产生过拟合原则的问题。可以引入"批量蒸馏"机制——不是每条轨迹都独立蒸馏，而是积累一批轨迹后统一分析，提取更具泛化性的原则。

---

### 8. MACLA: Learning Hierarchical Procedural Memory for LLM Agents through Bayesian Selection and Contrastive Refinement (2025)

**作者**: Forouzandeh, Peng et al.  
**核心思想**: 通过贝叶斯后验追踪程序可靠性，期望效用评分选择行动，对比成功/失败精炼程序。构建分层的程序性记忆，从具体步骤到抽象策略。

**关键机制**:
- 贝叶斯可靠性追踪：用 Beta 分布的后验概率评估每条程序的可靠性
- 期望效用评分：结合可靠性和相关性进行行动选择
- 对比精炼：通过成功/失败的对比来迭代改进程序描述
- 分层组织：具体过程 → 元过程 → 高层策略
- 多因子效用评分用于记忆修剪：U(Proc_i) = λ_r · α_i/(α_i+β_i) + λ_f · n_i/N_total + λ_t · e^(-(t_current-t_last)/τ)

**与 EgoAgent 的关系**: MACLA 的贝叶斯评分与 EgoAgent 的 Laplace 平滑在思想上高度一致——都是通过统计方式评估原则可靠性。MACLA 更进一步引入了分层结构和时间衰减因子，这些都可以增强 EgoAgent 的评分机制。

---

### 9. ReMe: Remember Me, Refine Me — A Dynamic Procedural Memory Framework (2024)

**作者**: arxiv 2512.10696  
**核心思想**: 针对"经验驱动的 Agent 进化"提出完整的程序性记忆生命周期管理：多面蒸馏 → 任务导向复用 → 效用驱动精炼。

**关键机制**:
- 多面蒸馏策略：从成功模式识别、失败分析、对比洞察生成三个角度提取经验
- 场景化索引：为每条经验标注适用场景，支持精准检索
- 重排序与自适应重写：将历史经验改写为适配当前任务约束的指导
- 效用驱动精炼：根据实际使用效果持续更新经验质量

**与 EgoAgent 的关系**: ReMe 的"自适应重写"机制是一个重要创新——原则不是静态文本，而是在注入时根据当前任务动态改写。这可以解决 EgoAgent 原则过于通用化的问题：存储时保持抽象，使用时动态具体化。

---

### 10. NEMORI: What Deserves Memory — Adaptive Memory Distillation for LLM Agents (ACL 2026)

**作者**: ACL 2026 Long Paper  
**核心思想**: 基于预测编码理论（Predictive Coding），将"什么值得记忆"建模为"Agent 基于现有知识无法预测的观察"。只有意外事件才值得记忆。

**关键机制**:
- 预测编码框架：Agent 基于当前记忆生成对下一步的预测
- 预测误差驱动：只有预测失败的经验才被纳入记忆
- 自适应蒸馏：记忆内容根据预测误差的性质进行不同粒度的蒸馏
- 无需训练（training-free）：完全在推理时运作

**与 EgoAgent 的关系**: NEMORI 提供了一个优雅的"记忆选择"机制——不是所有经验都蒸馏成原则，而是只蒸馏那些"出乎意料"的经验。这可以大幅减少 Principle Library 的冗余，提高知识密度。

---

### 11. H-MEM: Hierarchical Memory for High-Efficiency Long-Term Reasoning (2025)

**作者**: arxiv 2507.22925  
**核心思想**: 多层级记忆架构，按语义抽象程度组织记忆向量（Domain → Category → Memory Trace → Episode），通过位置索引编码实现高效的逐层检索。

**关键机制**:
- 四层语义抽象：从具体事件到高层领域知识
- 位置索引编码：每个记忆向量嵌入指向子记忆的位置索引
- 索引路由检索：无需穷举相似度计算，通过索引逐层导航
- 动态更新：新记忆的加入自动触发层级重组

**与 EgoAgent 的关系**: H-MEM 的分层架构启示我们可以将 Principle Library 组织为层次结构：高层元原则（如"总是先确认需求"）→ 领域原则（如"代码生成时先写测试"）→ 具体操作指导。

---

### 12. MAEL: Cross-Task Experiential Learning on LLM-based Multi-Agent Collaboration (2025)

**作者**: arxiv 2505.23187  
**核心思想**: 在多 Agent 协作框架中引入跨任务经验学习阶段，通过奖励引导的经验检索机制实现自适应协作。

**关键机制**:
- 经验学习阶段：专门用于跨任务经验积累的学习周期
- 奖励引导检索：根据任务奖励信号指导经验检索策略
- 无向图通信：Agent 在图结构上交换消息进行协作
- 跨任务泛化：从已完成任务中提取可迁移的协作模式

**与 EgoAgent 的关系**: MAEL 展示了原则知识在多 Agent 场景下的共享和迁移可能性。EgoAgent 作为多 Agent 框架（通过 Harness 编排），可以让多个 Agent 共享和协同进化 Principle Library。

---

### 13. MDL-Guided Rule Learning for Tool-Using Agents (2025)

**作者**: OpenReview  
**核心思想**: 从失败轨迹中蒸馏紧凑、可解释的规则，使用最小描述长度（MDL）目标优化规则的通用性和简洁性，以自然语言+结构化符号双形式存储。

**关键机制**:
- MDL 目标函数：偏好更通用、更简洁的规则（奥卡姆剃刀）
- 双重表示：自然语言描述 + 结构化符号形式
- LLM 自主提出规则候选，MDL 进行筛选和合并
- 不修改模型权重，规则在推理时通过 prompt 注入

**与 EgoAgent 的关系**: MDL 原则为 EgoAgent 的原则合并和精简提供了理论基础——当两条原则可以用一条更通用的规则替代时，根据 MDL 准则应该合并它们。这可以有效控制 Principle Library 的膨胀。

---

### 14. FLUXMEM: Choosing How to Remember — Adaptive Memory Structures for LLM Agents (2025)

**作者**: arxiv 2602.14038  
**核心思想**: 统一框架，让 Agent 自适应选择不同的记忆结构。通过离线监督学习基于交互特征选择最优记忆组织方式，引入三级记忆层次和 Beta 混合模型概率门控。

**关键机制**:
- 多互补记忆结构：Agent 配备多种记忆组织方式
- 结构选择学习：基于交互特征自动选择最优记忆结构
- Beta 混合模型门控：替代脆弱的相似度阈值，实现分布感知的记忆融合
- 三级记忆层次：支持长horizon记忆演化

**与 EgoAgent 的关系**: FLUXMEM 的自适应选择思想启示我们：不同类型的任务可能需要不同形式的原则表示。EgoAgent 可以根据任务类型动态选择是使用抽象原则、具体示例还是程序化规则。

---

## 三种记忆范式对比（episodic / semantic / procedural）

| 维度 | 情景记忆 (Episodic) | 语义记忆 (Semantic) | 程序性记忆 (Procedural) |
|------|---------------------|---------------------|-------------------------|
| **认知对应** | "我记得上次发生了什么" | "我知道这个事实/概念" | "我知道该怎么做" |
| **内容形式** | 具体事件的时序记录 | 抽象的事实和概念关系 | 可执行的行为准则/规则 |
| **典型实现** | Reflexion 的反思buffer、trajectory replay | 知识图谱、RAG 文档库 | EgoAgent Principle Library、AutoGuide |
| **泛化能力** | 低（绑定特定情境） | 中（事实可跨任务复用） | 高（规则适用于类似情境） |
| **存储效率** | 低（需保留完整上下文） | 中（结构化压缩） | 高（自然语言规则简洁） |
| **更新方式** | 追加新事件 | 事实修正/覆盖 | 评分更新/规则精炼 |
| **检索方式** | 相似情境匹配 | 关键词/实体匹配 | 条件触发/场景匹配 |
| **冲突处理** | 时间序标注，以最新为准 | 版本控制，可回溯 | 评分机制自然淘汰劣质规则 |
| **代表系统** | Reflexion, MemGPT | RAG, Knowledge Graph | ExpeL, AutoGuide, MACLA, EgoAgent |
| **适用场景** | 短期任务改进、单次任务重试 | 知识密集型任务 | 跨任务持续改进、行为优化 |

### 关键洞察

认知科学研究表明，人类的专家能力主要依赖程序性记忆——医生不需要回忆每个病例（情景），也不需要每次查教科书（语义），而是凭借内化的诊断规则快速决策。类似地，一个成熟的 AI Agent 应该以程序性记忆为核心，以情景和语义记忆为辅助：

- **情景记忆**作为原则蒸馏的**原料**——记录发生了什么
- **语义记忆**提供原则应用的**背景知识**——提供领域事实
- **程序性记忆**（原则库）是最终的**行为指导**——告诉 Agent 该怎么做

这种"轨迹 → 蒸馏 → 原则"的流水线，正是 EgoAgent 的核心设计哲学。

---

## EgoAgent Principle Library 的独特优势

基于对上述论文的系统分析，EgoAgent 的 Principle Library 在以下方面具有独特的设计优势：

### 1. Laplace 平滑的动态评分

```
metric_score = (success_count + 1) / (usage_count + 2)
```

这一简洁的公式具有深刻的统计学意义：
- **冷启动友好**：新原则初始分数为 0.5（中性），不会因缺乏数据而被错误淘汰
- **逐步收敛**：随着使用次数增加，分数逐渐逼近真实成功率
- **自然淘汰**：持续失败的原则分数会稳定下降至 < 0.3 的清理阈值
- **对比 MACLA 的 Beta 分布后验**：本质上是同一思想的简化实现（Laplace 平滑等价于 Beta(1,1) 先验下的后验均值）

### 2. 双类型原则体系 (Guiding + Cautionary)

不同于大多数系统只关注"该做什么"，EgoAgent 同时维护：
- **指导性原则 (Guiding)**："当用户给出模糊需求时，先提出具体方案再确认"
- **警示性原则 (Cautionary)**："不要在未确认用户意图前直接执行可能破坏性的操作"

这种正负双向建模比单纯的正面规则更鲁棒——认知科学表明，"知道什么不能做"与"知道什么该做"同样重要。

### 3. 结构化三元组表示

每条原则同时包含自然语言描述和 (S, P, O) 结构化三元组：
- **自然语言描述**：支持语义检索和人类可读
- **结构化三元组**：支持精确逻辑推理和去重

这种双重表示结合了 MDL-Guided Rule Learning 的"双表示"思想，同时服务于检索效率和推理精确性。

### 4. 图算法去重（连通分量合并）

通过语义相似度构建原则关系图，使用连通分量算法自动合并语义重复的原则。这比简单的阈值去重更鲁棒——能够处理传递性重复（A 与 B 相似，B 与 C 相似，因此 A 和 C 应合并，即使 A 和 C 直接相似度不高）。

### 5. 经验即工具（search_experience as action）

EgoAgent 将经验检索暴露为一个显式的工具调用，而非自动注入。这意味着：
- Agent 自主决定**何时**查询经验（避免不必要的检索开销）
- Agent 可以**选择性**地使用检索到的原则（避免过度依赖可能过时的原则）
- 与 MemGPT 的"Agent 自主管理记忆"理念一致

### 6. 与进化系统的深度集成

Principle Library 不是一个独立的记忆模块，而是与 EgoAgent 的自进化引擎（TextGrad 优化、门控回滚、前沿课程）深度集成。原则可以：
- 影响 system prompt 的进化方向
- 作为 TextGrad 的"文本梯度"来源
- 在进化门控中作为评估因子

---

## 具体 Research Ideas

### Idea 1: Predictive Principle Distillation — 基于预测编码的选择性原则蒸馏

**动机**: 当前 EgoAgent 从每条轨迹中均匀蒸馏原则，导致大量冗余和低价值原则。NEMORI 的预测编码理论提供了优雅的解决方案。

**核心思想**: 只有当 Agent 的行为与 Principle Library 现有知识的预测不一致时，才触发原则蒸馏。"意外"事件才值得学习。

**技术方案**:
1. **预测阶段**: 给定任务描述和当前 Principle Library，让 LLM 预测 Agent 应该采取的策略
2. **执行阶段**: Agent 实际执行任务，记录轨迹
3. **对比阶段**: 比较预测策略与实际轨迹的偏差
4. **选择性蒸馏**: 仅对偏差显著的部分进行原则蒸馏
   - 如果预测正确且执行成功 → 不蒸馏（已有知识足够）
   - 如果预测错误且执行成功 → 蒸馏新的 guiding 原则
   - 如果预测正确但执行失败 → 蒸馏 cautionary 原则（原则需要修正）
   - 如果预测错误且执行失败 → 蒸馏高优先级原则（盲区）

**预期贡献**:
- 减少 50%+ 的冗余原则蒸馏
- 提高原则库的信息密度
- 将认知科学的预测编码理论形式化为 Agent 学习机制

---

### Idea 2: Hierarchical Principle Consolidation with MDL — 基于最小描述长度的分层原则整合

**动机**: 随着 Principle Library 增长，原则之间存在大量重叠和层次关系。例如"确认需求"和"在代码任务中确认需求"是一般和特殊的关系。需要自动构建原则层次结构。

**核心思想**: 引入 MDL 准则自动发现可合并的原则，构建"元原则 → 领域原则 → 操作原则"的三层结构，并在检索时实现自顶向下的导航。

**技术方案**:
1. **MDL 合并判定**: 对于原则集 {P1, P2, ..., Pk}，如果存在更通用的 P_general 使得 DL(P_general) + Σ DL(Pi | P_general) < Σ DL(Pi)，则合并
2. **层次构建**: 
   - Level 0（元原则）：如"总是确认用户意图后再行动"
   - Level 1（领域原则）：如"代码生成时先确认需求规格"
   - Level 2（操作原则）：如"修改文件前先问用户是否备份"
3. **层次化检索**: 先匹配 Level 0 确定大方向，再逐层细化
4. **评分传播**: 元原则的分数由子原则分数聚合得到；子原则分数变化会影响父原则

**预期贡献**:
- 将 Principle Library 大小压缩 40-60%（通过合并）
- 检索效率提升（分层导航 vs 扁平搜索）
- 为"原则库何时饱和"提供信息论基础（MDL 不再减小时）

---

### Idea 3: Cross-Task Principle Transfer via Contextual Adaptation — 条件化原则的跨任务迁移与动态改写

**动机**: 从 Task A 蒸馏的原则可能对 Task B 有参考价值，但直接套用会导致负迁移。需要一种机制在迁移时进行适应性改写。

**核心思想**: 结合 AutoGuide 的条件化结构和 ReMe 的自适应重写，为每条原则学习"迁移适配规则"：原则在不同上下文中应如何变形才能适用。

**技术方案**:
1. **条件化原则表示**: 扩展原则格式为 `<context_condition, principle_body, adaptation_history>`
2. **迁移检测**: 当原则被检索到但其 context_condition 与当前任务不完全匹配时，触发适配
3. **动态改写**: LLM 根据原则原文 + 当前上下文 + 适配历史，生成适配版本
4. **适配效果追踪**: 改写后的原则独立评分，成功的适配模式被记录为"迁移规则"
5. **元学习**: 积累足够的迁移规则后，Agent 能学会"如何迁移原则"的元策略

**预期贡献**:
- 首次系统性地研究 Agent 程序性记忆的跨任务迁移
- 解决负迁移问题（通过条件化适配而非直接复用）
- "迁移规则"作为二阶知识的积累，实现学习如何学习（meta-learning without gradient）

---

## 实验设计

### 基准测试选择

| 基准 | 类型 | 为什么选择 |
|------|------|-----------|
| ALFWorld | 具身任务 | 多步骤、需要策略积累 |
| WebArena | Web 交互 | 复杂、领域多样 |
| SWE-bench | 软件工程 | 需要长期经验积累 |
| InterCodeSQL | 代码生成 | 跨任务迁移验证 |
| TravelPlanner | 规划任务 | 约束推理、需要领域知识 |
| GAIA | 多领域通用 | 泛化能力验证 |

### 实验 1: Predictive Distillation 有效性验证

**设置**:
- 基线: (a) 全量蒸馏 (b) 随机采样蒸馏 (c) ExpeL insight extraction (d) Reflexion
- 指标: 在相同记忆容量下，task success rate、原则精确度 (precision@k)、蒸馏效率 (有效原则数/总蒸馏原则数)
- 任务序列: 50 个 ALFWorld 任务顺序执行，观察学习曲线

**关键假设**: 预测编码驱动的选择性蒸馏应在更少的原则数量下达到更高的性能。

### 实验 2: MDL 层次整合效果

**设置**:
- 让 Agent 在 WebArena 上积累 200+ 原则后，应用 MDL 整合
- 对比: (a) 无整合（扁平库）(b) 简单聚类合并 (c) MDL 层次整合
- 指标: 库大小压缩率、检索精度、下游任务性能、检索延迟

**关键假设**: MDL 整合应在不损失性能的前提下显著压缩库大小。

### 实验 3: 跨任务迁移效果

**设置**:
- 训练阶段: 在 ALFWorld + WebShop 上积累原则
- 测试阶段: 在 TravelPlanner + InterCodeSQL 上评估
- 对比: (a) 不使用原则 (b) 直接使用原始原则 (c) 条件化适配后使用
- 指标: 零样本迁移成功率、负迁移率、适配成功率

**关键假设**: 条件化适配应显著减少负迁移，同时保持正迁移效果。

### 实验 4: 持续学习曲线分析

**设置**:
- 在 100+ 任务的序列上运行，每 10 个任务记录一次性能
- 对比有无 Principle Library 的长期学习曲线
- 分析: 性能单调性、饱和点、原则库大小变化

**关键假设**: 配备完整 Principle Library 的 Agent 应展示单调递增的学习曲线，且存在明确的饱和转折点。

### 消融研究

- Laplace 平滑 vs 无平滑 vs Beta 分布后验
- 条件化原则 vs 无条件原则
- 批量蒸馏 vs 逐条蒸馏
- 预测编码选择 vs 全量蒸馏
- 分层检索 vs 扁平检索
- 双类型原则 vs 单类型原则

---

## 目标会议与影响力评估

### 目标会议

| 优先级 | 会议 | 理由 |
|--------|------|------|
| 1 | ICLR 2027 | Agent Learning + Memory 是 ICLR 的核心话题 |
| 2 | NeurIPS 2026 (Late) | 系统性贡献适合 NeurIPS 的大论文传统 |
| 3 | ICML 2027 | 理论贡献（MDL, 预测编码形式化）适合 ICML |
| 4 | ACL 2027 | NLP 社区对 Agent 记忆系统有很高兴趣 |
| 5 | AAAI 2027 | 与 ExpeL (AAAI 2024) 同会议，有延续性 |

### 影响力评估

**学术影响力**:
- 将认知科学三种记忆范式系统性引入 LLM Agent 领域
- 提供原则蒸馏的信息论基础（MDL + 预测编码）
- 首次研究程序性记忆的跨任务迁移机制

**工程影响力**:
- 直接可集成到 EgoAgent 系统中
- 不需要 GPU 训练基础设施（纯推理时方法）
- 可与任何 LLM backbone 配合使用

**竞争优势**:
- 与 ExpeL/Reflexion 比：动态评分 + 层次结构 + 条件化适配是本质升级
- 与 MACLA 比：预测编码的选择性蒸馏是新颖贡献
- 与 AutoGuide 比：MDL 驱动的自动层次整合和跨任务迁移是差异化

**潜在风险**:
- 蒸馏质量依赖 LLM 的反思能力，小模型上效果可能有限
- 跨任务迁移的效果可能因任务差异过大而受限
- MDL 计算可能引入额外延迟

---

## 参考文献列表

1. Shinn, N., Cassano, F., Gopinath, A., et al. (2023). "Reflexion: Language Agents with Verbal Reinforcement Learning." *NeurIPS 2023*. arXiv:2303.11366.

2. Zhao, A., Huang, D., Xu, Q., et al. (2023). "ExpeL: LLM Agents Are Experiential Learners." *AAAI 2024*. arXiv:2308.10144.

3. Nottingham, K., et al. (2024). "ICAL: Continual Learning of Multimodal Agents by Transforming Trajectories into Actionable Insights." *ICML 2024*. arXiv:2406.14596.

4. Packer, C., Wooders, S., Lin, K., et al. (2023). "MemGPT: Towards LLMs as Operating Systems." arXiv:2310.08560. (Letta Framework 2024).

5. AdMem Team. (2026). "AdMem: Advanced Memory for Task-solving Agents." arXiv:2606.06787.

6. Zhu, S., et al. (2024). "AutoGuide: Automated Generation and Selection of Context-Aware Guidelines for Large Language Model Agents." *AAAI 2024*. arXiv:2403.08978.

7. AutoRefine Team. (2025). "AutoRefine: From Trajectories to Reusable Expertise for Continual LLM Agent Refinement." arXiv:2601.22758.

8. Forouzandeh, S., Peng, W., et al. (2025). "MACLA: Learning Hierarchical Procedural Memory for LLM Agents through Bayesian Selection and Contrastive Refinement." arXiv:2512.18950.

9. ReMe Team. (2024). "Remember Me, Refine Me: A Dynamic Procedural Memory Framework for Experience-Driven Agent Evolution." arXiv:2512.10696.

10. NEMORI Team. (2026). "What Deserves Memory: Adaptive Memory Distillation for LLM Agents." *ACL 2026 Long*. aclanthology.org/2026.acl-long.1607.

11. H-MEM Team. (2025). "H-MEM: Hierarchical Memory for High-Efficiency Long-Term Reasoning in LLM Agents." arXiv:2507.22925.

12. MAEL Team. (2025). "Cross-Task Experiential Learning on LLM-based Multi-Agent Collaboration." arXiv:2505.23187.

13. MDL Rule Learning Team. (2025). "Improving Tool-Using Language Agents via MDL-Guided Rule Learning." OpenReview (under review).

14. FLUXMEM Team. (2025). "Choosing How to Remember: Adaptive Memory Structures for LLM Agents." arXiv:2602.14038.

15. O3D Team. (2024). "O3D: Offline Data-driven Discovery and Distillation for Sequential Decision-Making with Large Language Models." *ICLR 2024*. OpenReview:bkY8zEDdH9.

16. Trajectory-Informed Memory Team. (2025). "Trajectory-Informed Memory Generation for Self-Improving Agent Systems." arXiv:2603.10600.

17. Memp Team. (2025). "Memp: A Task-Agnostic Framework that Elevates Procedural Memory to a Core Optimization Target in LLM-based Agent." *NeurIPS 2025*.

18. KILO Team. (2025). "Tackling Distribution Shift in LLM via KILO: Knowledge-Instructed Learning for Continual Adaptation." arXiv:2508.03571.

19. AgentFly Team. (2025). "AgentFly: Continual Learning through Memory and Experience without Fine-tuning LLM." *ACL 2025*.

20. AGENT KB Team. (2025). "AGENT KB: Leveraging Cross-Domain Experience for Agentic Problem Solving." arXiv preprint.

---

*本文档基于 2024-2026 年 20+ 篇前沿论文的系统调研，结合 EgoAgent 系统的 Principle Library 实际实现撰写。*
