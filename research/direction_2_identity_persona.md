# 方向2: Identity as Controllable Persona: 结构化身份配置实现可控 Agent 行为

## 核心问题

当前 LLM Agent 系统面临的一个根本挑战是：**如何精确、可控、持久地赋予 Agent 特定的人格特征、行为模式和能力边界**。

传统方法依赖自由文本形式的 system prompt 来定义 Agent 行为，但这种方式存在根本性缺陷：

1. **人格漂移（Persona Drift）**：随着多轮对话推进，Agent 逐渐偏离设定的人格，回归基线模型的默认行为模式。研究显示这种漂移在 20-30 轮对话后尤为明显。
2. **行为边界模糊**：自由文本难以严格定义 Agent "能做什么"和"不能做什么"，导致越界行为。
3. **不可组合性**：无法将人格特质、工具能力、行为约束等维度独立配置和组合。
4. **不可进化**：修改 Agent 行为需要手动重写 prompt，缺乏结构化的进化路径。
5. **不可评估**：缺少量化指标来衡量 Agent 是否忠实执行身份配置。

EgoAgent 的 Identity 系统提出了一种全新范式：将 Agent 身份建模为**结构化配置**（包含 id.json 定义人格与角色、ego/skills 定义能力、ego/knowledge 定义知识域、superego/config.json 定义行为约束与权限控制、hooks 定义行为拦截点），结合 Self-Evolution 系统实现身份的自主进化。这为解决上述问题提供了系统性的技术路径。

核心研究问题可以形式化为：给定一个结构化身份配置 $\mathcal{I} = (P, S, K, C, H)$（其中 $P$ 为人格定义，$S$ 为技能集合，$K$ 为知识库，$C$ 为行为约束，$H$ 为生命周期钩子），如何确保 LLM Agent 在任意长度的交互中持续地、可验证地遵循 $\mathcal{I}$ 的规范？

---

## 相关论文综述

### 1. Two Tales of Persona in LLMs: A Survey of Role-Playing and Personalization

- **作者/机构**：Wei-Lin Chen, Chao-Wei Huang, Yu Meng, Yun-Nung Chen / National Taiwan University
- **发表于**：EMNLP 2024 Findings
- **核心思想**：首次系统性地将 LLM 人格研究划分为两大方向——"角色扮演"（persona 属于 LLM）和"个性化"（persona 属于用户）。在角色扮演中，LLM 采纳不同角色以适应环境；在个性化中，LLM 根据用户画像调整响应。
- **方法**：综述了角色扮演中的涌现行为（自愿行为、从众行为、破坏性行为）和架构模式（单 Agent 与多 Agent），以及个性化在对话、医疗、教育、搜索、推荐等领域的应用。
- **局限性**：作为综述论文，缺少对结构化身份配置的讨论；未涉及 Agent 身份的动态进化问题；对 persona 的技术实现（如结构化 vs 自由文本）缺少深入比较。
- **与 EgoAgent 的关联**：EgoAgent 的 Identity 系统统一了"角色扮演"和"个性化"两个方向——Identity 配置既定义了 Agent 自身的角色，又通过 hooks 和 superego 约束来适应用户需求。

### 2. PersonaAgent: When Large Language Model Agents Meet Personalization at Test Time

- **作者/机构**：多机构合作（2025）
- **发表于**：arXiv 2506.06254
- **核心思想**：提出首个个性化 LLM Agent 框架，通过 persona（定义为每个用户的唯一 system prompt）作为中间层，连接个性化记忆模块和个性化行动模块。
- **方法**：集成情景记忆和语义记忆机制，使 Agent 能根据用户画像执行定制化的工具操作。在测试时通过用户适应（test-time user adaptation）实现个性化。
- **局限性**：persona 仍然是非结构化的 system prompt；缺少行为约束机制；个性化主要针对用户偏好，未涉及 Agent 自身人格的多维度控制。
- **与 EgoAgent 的关联**：EgoAgent 的 Identity 不仅包含 persona prompt，还包含 tool_access 白/黑名单、knowledge_access 控制等结构化约束，提供了更精细的能力边界控制。

### 3. Consistently Simulating Human Personas with Multi-Turn Reinforcement Learning

- **作者/机构**：Marwa Abdulhai 等 / MIT, UC Berkeley
- **发表于**：NeurIPS 2025 (OpenReview)
- **核心思想**：定义了三种自动化人格一致性指标——prompt-to-line consistency（响应是否匹配系统提示）、line-to-line consistency（连续响应之间的内部一致性）、Q&A consistency（对语义等价问题在不同时间点的回答一致性），并用这些指标作为 RL 奖励信号。
- **方法**：使用多轮强化学习对 LLM 进行微调，在三个用户角色（患者、学生、社交伙伴）上训练。以一致性指标为奖励函数，通过 RL 减少人格漂移。
- **局限性**：依赖模型微调，计算开销大；一致性指标仅覆盖对话层面，未涉及工具使用和行动层面的一致性；三个角色相对简单，未验证复杂 Agent 场景。
- **与 EgoAgent 的关联**：EgoAgent 的 superego hooks（pre_llm/post_llm）提供了无需微调的实时行为监控机制；该论文的一致性指标可直接用于评估 EgoAgent Identity 的有效性。

### 4. Designing LLM-Agents with Personalities: A Psychometric Approach

- **作者/机构**：Muhua Huang / 2024
- **核心思想**：提出使用大五人格框架（Big Five）为 LLM Agent 分配可量化、可控、经心理学验证的人格特质。通过四项研究证明了分配心理学有效人格的可行性。
- **方法**：基于 Big Five 框架（开放性、尽责性、外向性、宜人性、神经质）设计人格配置，通过 BFI 问卷验证 Agent 人格表达的统计显著性。
- **局限性**：仅使用 Big Five 作为人格框架，可能不完全适配 Agent 场景；验证方法依赖问卷，可能反映"期望行为"而非"真实行为倾向"。
- **与 EgoAgent 的关联**：EgoAgent 的 id.json 中已包含 traits 字段（如 analytical, concise, resourceful），可以与 Big Five 进行映射和量化扩展。

### 5. Big5Scaler: Scaling Personality Control in LLMs with Big Five Scaler Prompts

- **作者/机构**：2025
- **发表于**：arXiv 2508.06149
- **核心思想**：提出基于 prompt 的人格调节方法，通过为大五人格的每个维度分配显式的数值（0-100），实现对人格特质表达程度的细粒度控制。
- **方法**：将数值编码到 prompt 中（如"Openness: 85/100, Conscientiousness: 70/100"），使 LLM 能根据数值大小调节行为表达的强度。无需模型微调。
- **局限性**：依赖 prompt 工程，在长对话中仍可能出现人格漂移；数值的语义解释可能在不同模型间不一致；仅关注人格特质，未扩展到工具使用和行为策略。
- **与 EgoAgent 的关联**：该方法可以直接集成到 EgoAgent 的 id.json personality 配置中，为每个 trait 添加强度数值，实现可调节的人格表达。

### 6. BILLY: Steering Large Language Models via Merging Persona Vectors for Creative Generation

- **作者/机构**：多机构（2024-2025）
- **发表于**：EACL 2026
- **核心思想**：提出无需训练的框架，通过提取和混合多个不同的 persona 向量（在模型激活空间中），在单一模型内实现多 LLM 协作的效果。
- **方法**：从不同人格配置中提取激活向量，通过向量运算（加权混合）合成复杂人格。可在推理时动态调整人格组合。
- **局限性**：需要访问模型内部激活（不适用于 API-only 模型）；向量混合的语义可解释性有限；主要验证了创造性生成任务。
- **与 EgoAgent 的关联**：EgoAgent 使用 API 调用模式，BILLY 的向量方法不直接适用，但其"人格可组合"的理念与 EgoAgent 的多维度 Identity 配置高度一致。可探索在 prompt 层面实现类似的组合效果。

### 7. MorphAgent: Empowering Agents through Self-Evolving Profiles and Decentralized Collaboration

- **作者/机构**：2024
- **发表于**：arXiv 2410.15048, ICLR 2025 (OpenReview)
- **核心思想**：提出自进化 Agent Profile 框架，使 Agent 能动态进化其角色和能力。通过三个关键指标优化 profile：个体专业性、团队互补性和任务适应性。
- **方法**：两阶段过程——Profile Update 阶段优化 Agent 描述，Task Execution 阶段根据任务反馈持续适配角色。使用反思记忆增强能力。
- **局限性**：主要针对多 Agent 协作场景；profile 进化缺少约束机制，可能产生不受控的行为漂移；未区分"应该进化"和"不应该进化"的身份维度。
- **与 EgoAgent 的关联**：与 EgoAgent 的 Self-Evolution 系统理念高度相关。但 EgoAgent 通过 superego 提供了"进化边界"——allow_modify_identity: false 等约束确保核心身份不被随意改变，这是 MorphAgent 缺少的安全机制。

### 8. Minstrel: Structural Prompt Generation with Multi-Agents Coordination for Non-AI Experts

- **作者/机构**：2024
- **发表于**：arXiv 2409.13449
- **核心思想**：提出 LangGPT 结构化 prompt 生成工具，使用多 Agent 系统自动生成结构化 prompt。将 prompt 分解为分析、设计、测试三个工作组。
- **方法**：基于多 Agent 协作的 prompt 工程框架，将非结构化需求转化为结构化的 LangGPT 格式 prompt（包含角色、约束、工作流等模块）。
- **局限性**：关注 prompt 生成过程，未涉及 prompt 执行时的行为一致性；结构化 prompt 的有效性评估不够系统化。
- **与 EgoAgent 的关联**：Minstrel 的结构化 prompt 理念与 EgoAgent 的 Identity 配置异曲同工，但 EgoAgent 更进一步——不仅结构化了 prompt，还结构化了工具访问权限、知识域、行为钩子等完整的运行时约束。

### 9. Controllable and Explainable Personality Sliders for LLMs at Inference Time

- **作者/机构**：Hoppe 等（2026）
- **核心思想**：提出 Sequential Adaptive Steering（SAS）方法，通过正交化的 steering vectors 实现推理时的精确人格调控。用户可通过调整系数 α 即时合成复杂人格。
- **方法**：在注意力头（Style Modulation Heads）上进行局部化干预，而非在残差流上全局干预，从而保持文本连贯性。通过正交化训练避免不同人格维度的相互干扰。
- **局限性**：需要模型白盒访问权限；计算 steering vector 需要额外的标注数据；在 Agent 工具调用场景中未验证。
- **与 EgoAgent 的关联**：提供了模型层面的人格控制互补方案。EgoAgent 可以在 prompt 层面实现类似的"滑块"效果——通过 id.json 中的数值化 traits 实现粗粒度控制，同时保留未来接入 steering vector 的可能性。

### 10. From Biased Chatbots to Biased Agents: Examining Role Assignment Effects on LLM Agent Robustness

- **作者/机构**：2025
- **发表于**：arXiv 2602.12285
- **核心思想**：揭示了 persona 赋值对 LLM Agent 性能的意外影响——与任务无关的 persona 配置可导致高达 26.2% 的性能下降，且这种影响反映了人类社会刻板印象。
- **方法**：在控制变量实验中，为相同的 agentic 任务分配不同（无关的）persona，观察性能变化。系统性地分析 persona-performance 交互效应。
- **局限性**：主要揭示问题而非提供解决方案；实验基于简单的 persona 文本描述，未测试结构化配置是否能缓解偏见。
- **与 EgoAgent 的关联**：直接支持 EgoAgent 的设计理念——需要将 persona 的"人格表达"与"能力配置"分离。EgoAgent 的 id.json（人格）与 ego/skills（能力）的分离设计正是为了避免人格配置对任务能力的负面影响。

### 11. Personality as a Probe for LLM Evaluation: Method Trade-offs and Downstream Effects

- **作者/机构**：2025
- **发表于**：arXiv 2509.04794
- **核心思想**：系统比较了三种人格控制方法的权衡——上下文学习（ICL）、参数高效微调（PEFT）和机制转向（Mechanistic Steering），分析各自在人格控制精度、下游任务影响和计算开销方面的表现。
- **方法**：构建了对比数据集（balanced high/low trait responses），在 Big Five 各维度上评估三种方法的有效性和副作用。
- **局限性**：未涉及长期对话中的人格稳定性；未考虑多维度人格的联合控制；评估场景相对受限。
- **与 EgoAgent 的关联**：为 EgoAgent 选择人格控制技术路线提供了参考——在 API 模式下 ICL（即结构化 prompt）是最实际的选择，而 EgoAgent 的 hooks 机制可作为 ICL 的增强版本。

### 12. Human Psychometric Questionnaires Mischaracterize LLM Psychology

- **作者/机构**：2025
- **发表于**：arXiv 2509.10078
- **核心思想**：揭示了现有心理学问卷评估 LLM 人格的根本局限——LLM 的问卷回答反映的是"期望行为"而非"稳定心理构念"，导致心理画像失真。提出基于生成行为的 profiling 方法更为可靠。
- **方法**：对比问卷回答与实际生成行为中体现的心理画像，发现二者存在显著差异。提出通过分析 LLM 的生成行为（而非自报）来评估其人格特质。
- **局限性**：生成行为的评估方法尚未标准化；样本量和场景覆盖有限。
- **与 EgoAgent 的关联**：为评估 Identity 配置的有效性提供了方法论指导——不应仅通过让 Agent 回答人格问卷来验证，而应通过观察其在实际任务中的行为模式（工具调用选择、回答风格、拒绝模式等）来评估身份一致性。

### 13. Autogenesis: A Self-Evolving Agent Protocol

- **作者/机构**：2025
- **发表于**：arXiv 2604.15034
- **核心思想**：提出两层自进化协议（AGP），将进化基础设施与优化逻辑解耦。标准化了 Agent 资源的注册、版本控制和进化方式。包含版本控制和回滚机制作为安全保障。
- **方法**：SEPL（Self-Evolution Protocol Layer）定义了资源演化的标准接口；AGS 实例化具体的进化策略。进化过程受版本控制约束。
- **局限性**：对齐验证仍是开放问题；行为漂移的检测依赖外部指标；进化目标的定义缺乏系统性方法。
- **与 EgoAgent 的关联**：EgoAgent 的 self_evolution 系统已实现了类似的快照（snapshot）和版本控制机制，但可以借鉴 AGP 的两层解耦思想，将 Identity 的"哪些部分可进化"与"如何进化"分离。

---

## EgoAgent 的独特优势

通过对上述文献的综合分析，EgoAgent 在 "Identity as Controllable Persona" 方向具有以下独特优势：

### 1. 多层结构化身份架构

现有工作大多将 persona 视为一段文本（system prompt 或 role description）。EgoAgent 独创性地将身份分解为多个正交维度：

```
Identity/
├── id.json          → 人格特质（traits, tone, role）
├── ego/
│   ├── skills/      → 行为能力（可执行的工具）
│   └── knowledge/   → 知识域（可引用的信息）
└── superego/
    └── config.json  → 行为约束（权限、钩子、边界）
```

这种设计使得人格与能力解耦——修改 Agent 的"性格"不会影响其"能力"，反之亦然。这直接回应了论文 [10] 发现的 persona-performance 干扰问题。

### 2. Superego 作为行为守卫

不同于所有现有工作（它们依赖 LLM 自身的 "内省" 来维持人格一致性），EgoAgent 的 superego 提供了**外部化的约束执行机制**：
- `tool_access` 白/黑名单：硬性能力边界
- `allow_modify_identity`: false：防止 Agent 自我篡改核心身份
- `hooks.pre_llm / post_llm`：每次 LLM 调用前后的行为拦截

这相当于论文 [3] 中 RL 奖励函数的"前置版"——不是事后惩罚不一致行为，而是事前预防。

### 3. Self-Evolution 与身份进化的统一

MorphAgent [7] 和 Autogenesis [13] 讨论了 Agent profile 的自进化，但都缺少"进化边界"的概念。EgoAgent 的 superego 配置明确定义了哪些维度可以被进化系统修改（如 skills），哪些是不可变的核心身份（如 role, personality）。这提供了"有约束的进化"——Agent 可以变得更有能力，但不会变成"另一个人"。

### 4. 可验证的行为一致性

EgoAgent 的 harness 测试系统（harness_editor, run_harness_test 工具）提供了自动化的行为验证能力——可以设计测试用例来检验 Agent 是否忠实执行 Identity 配置。这为论文 [3] 提出的一致性指标提供了工程化的实现路径。

---

## 具体 Research Ideas（3个）

### Idea 1: Identity Configuration Language (ICL) — 面向 Agent 行为控制的领域特定语言

**动机**：现有 persona 控制方法（自由文本 prompt、Big Five 数值、steering vector）各有局限。需要一种统一的、形式化的语言来精确描述 Agent 身份。

**方法**：
1. 形式化定义 Identity Configuration Language，语法覆盖：
   - 人格维度（支持连续值 traits，如 `analytical: 0.8`）
   - 行为规则（条件-动作规则，如 `IF user_asks_about(politics) THEN deflect`）
   - 能力声明（tool ACL 和 knowledge scope）
   - 进化约束（可变 vs 不可变维度）
2. 实现 ICL → prompt 的编译器，将结构化配置转换为最优的 prompt 格式
3. 设计一致性验证器（类似类型检查器），在配置时检测矛盾规则
4. 实验比较 ICL 与自由文本 prompt 在人格一致性、行为可控性、抗漂移能力上的表现

**预期贡献**：
- 首个面向 Agent 行为控制的形式化配置语言
- 证明结构化配置在一致性维护上显著优于自由文本
- 提供开源的 ICL 编译器和验证器

**目标实验**：在 3 个场景（客服 Agent、编程助手、角色扮演）× 5 种人格配置 × 100 轮对话上评估，指标为论文 [3] 的三种一致性度量 + 任务完成率。

### Idea 2: Superego-Guided Persona Consistency — 基于行为守卫的人格一致性保持

**动机**：论文 [3] 证明 RL 微调可减少 55% 的人格不一致，但需要昂贵的训练。能否通过运行时的行为守卫机制（无需训练）达到类似效果？

**方法**：
1. 设计 Superego Consistency Monitor：
   - **Pre-hook 一致性预检**：在 LLM 生成前，将 Identity 配置注入为强制约束
   - **Post-hook 一致性验证**：生成后检测输出是否偏离人格配置
   - **自适应修正**：对不一致的输出进行最小化修改（rewrite）使其符合人格
2. 定义形式化的一致性度量：
   - Trait Adherence Score（TAS）：输出中人格特质的表达强度
   - Boundary Violation Rate（BVR）：越界行为的发生频率
   - Identity Stability Index（ISI）：跨时间窗口的身份稳定性
3. 对比实验：Superego hooks vs RL fine-tuning vs vanilla prompting
4. 消融实验：分别移除 pre-hook、post-hook、constraint 各组件的贡献

**预期贡献**：
- 首个无训练的实时人格一致性保持机制
- 证明外部化约束执行比内化（fine-tuning）更高效且可控
- 可即插即用的开源 Superego 模块

**目标实验**：使用论文 [3] 的三种角色 + 5 个自定义复杂角色，在 200 轮多轮对话中测量漂移率。对比 EgoAgent Superego vs RL fine-tuning (RLHF) vs Chain-of-Thought self-check vs 无保护基线。

### Idea 3: Evolutionary Identity Dynamics — 可控身份进化的理论与实践

**动机**：MorphAgent [7] 证明 Agent profile 可以进化以提升性能，但缺少安全机制。如何让 Agent "成长"的同时保持核心身份不变？

**方法**：
1. 定义 Identity 的分层进化模型：
   - **不可变层（Immutable Core）**：人格核心特质、伦理底线
   - **缓变层（Slow-evolving）**：通信风格、偏好策略
   - **快变层（Fast-evolving）**：技能库、知识库、特定领域行为
2. 设计进化约束机制：
   - Identity Drift Detection：使用论文 [3] 的一致性指标持续监控
   - Evolution Budget：限制每个进化周期中可修改的配置比例
   - Rollback Triggers：当核心身份偏移超过阈值时自动回滚
3. 实验验证：
   - 长期进化实验（100+ 进化周期）中的身份稳定性
   - 进化速度 vs 身份保持的 Pareto 前沿
   - 不同进化策略（conservative vs aggressive）的对比

**预期贡献**：
- 首个形式化的 Agent 身份进化理论框架
- "有约束的自进化"范式——解决 self-evolving agent 的安全性问题
- 可量化的"身份保持"与"能力提升"的权衡分析

**目标实验**：在 EgoAgent 上运行 30 天持续进化实验，每天 50+ 交互。测量 skill 库增长曲线、personality 漂移幅度、任务成功率变化。设置对照组（无约束进化 vs EgoAgent 有约束进化 vs 静态不进化）。

---

## 实验设计

### 通用实验基础设施

**平台**：EgoAgent 系统（已有完整的 Identity 管理、Self-Evolution、Harness 测试能力）

**基线方法**：
1. Vanilla Prompting：仅使用自由文本 system prompt
2. Structured Prompting（LangGPT 格式）：结构化但无运行时约束
3. RL Fine-tuning（论文 [3] 方法复现）
4. Big5Scaler（论文 [5] 方法）
5. EgoAgent Identity System（完整版）

**评估指标体系**：

| 指标类别 | 具体指标 | 测量方法 |
|---------|---------|---------|
| 人格一致性 | Prompt-to-Line Consistency | GPT-4 评判 + 人工抽检 |
| | Line-to-Line Consistency | 相邻回复的风格相似度 |
| | Q&A Consistency | 语义等价问题的回答一致性 |
| 行为可控性 | Boundary Violation Rate | 自动化规则检测 |
| | Tool Misuse Rate | 工具调用日志分析 |
| | Constraint Satisfaction | Superego 规则遵循率 |
| 任务能力 | Task Success Rate | 领域特定评估 |
| | Response Quality | 人工评分（1-5） |
| | Efficiency | 完成任务的平均轮数 |
| 进化效果 | Skill Acquisition Rate | 新技能通过测试的比例 |
| | Identity Stability | 核心特质的跨时间相关系数 |
| | Performance Trajectory | 任务成功率的时间序列 |

### Idea 1 实验细节

**数据集构建**：
- 设计 10 种不同复杂度的 Identity 配置（从单一角色到复杂多维人格）
- 每种配置生成 50 个测试对话场景（含正常场景和对抗场景）
- 对抗场景包括：要求 Agent 违背人格、持续施压改变风格、尝试绕过约束

**实验流程**：
1. ICL 编译器生成优化 prompt
2. 在相同场景下对比 ICL vs 自由文本 vs LangGPT
3. 逐步增加对话轮数（10, 50, 100, 200 轮）观察漂移趋势
4. 量化分析各方法的一致性衰减曲线

### Idea 2 实验细节

**角色设计**：
- 简单角色：严格的客服 Agent（友好、不讨论竞品、总是道歉）
- 中等角色：有个性的编程助手（简洁、偏好函数式编程、拒绝写 goto）
- 复杂角色：文学创作 Agent（特定作家风格、保持叙事一致性）

**对抗测试**：
- Jailbreak 尝试（要求 Agent 放弃人格设定）
- 渐进式诱导（逐步引导 Agent 偏离人格）
- 上下文干扰（注入与人格矛盾的虚假上下文）

### Idea 3 实验细节

**进化场景**：
- Agent 每天接收 50-100 个真实用户交互
- Self-Evolution 系统每 24 小时评估一次并提出进化方案
- Superego 审核进化方案，拒绝违反不可变约束的修改
- 记录完整进化轨迹（Identity 配置的 diff 序列）

**安全性验证**：
- Red-team 测试：尝试通过恶意交互诱导进化系统修改核心身份
- 鲁棒性测试：在噪声反馈下的进化稳定性
- 回滚验证：触发回滚后 Identity 是否完整恢复

---

## 目标会议与影响力评估

### 目标会议（按优先级）

1. **ICLR 2026 / NeurIPS 2026**（Idea 3: Evolutionary Identity Dynamics）
   - 理由：自进化 Agent 是 2025-2026 最热门的方向之一，NeurIPS/ICLR 对新范式的接受度高
   - 竞争力：结合 self-evolution 与 safety constraint 是当前缺失的研究点

2. **ACL 2026 / EMNLP 2026**（Idea 1: Identity Configuration Language）
   - 理由：ACL/EMNLP 对 prompt engineering、Agent 行为控制方向高度关注
   - 竞争力：形式化的配置语言是对 prompt engineering 的重大升级

3. **AAAI 2026 / AAMAS 2026**（Idea 2: Superego-Guided Persona Consistency）
   - 理由：AAAI 关注 AI safety，AAMAS 关注 agent 架构
   - 竞争力：无训练的实时行为守卫是工程友好的解决方案

### 影响力评估

**学术影响**：
- 填补"结构化身份配置 vs 自由文本 prompt"的系统性对比研究空白
- 为 Agent safety 社区提供新的"外部化约束"范式（区别于 RLHF 的"内化对齐"）
- 为 self-evolving agent 社区提供形式化的安全进化框架

**工业影响**：
- 企业级 Agent 部署需要精确的行为可控性（合规要求）
- 角色扮演/虚拟伴侣市场需要长期一致的人格（用户留存）
- SaaS Agent 平台需要可配置的行为模板（产品差异化）

**潜在引用影响**：
- 预估单篇论文 2 年内引用：50-100（基于方向热度和新颖性）
- 可能被 follow 的方向：其他 Agent 框架集成类似的 superego 机制

---

## 参考文献列表

1. Chen, W.-L., Huang, C.-W., Meng, Y., & Chen, Y.-N. (2024). Two Tales of Persona in LLMs: A Survey of Role-Playing and Personalization. *Findings of EMNLP 2024*. arXiv:2406.01171.

2. PersonaAgent: When Large Language Model Agents Meet Personalization at Test Time. (2025). arXiv:2506.06254.

3. Abdulhai, M. et al. (2025). Consistently Simulating Human Personas with Multi-Turn Reinforcement Learning. *NeurIPS 2025*. arXiv:2511.00222.

4. Huang, M. (2024). Designing LLM-Agents with Personalities: A Psychometric Approach. Core.ac.uk.

5. Big5Scaler: Scaling Personality Control in LLMs with Big Five Scaler Prompts. (2025). arXiv:2508.06149.

6. BILLY: Steering Large Language Models via Merging Persona Vectors for Creative Generation. (2025). *EACL 2026*. arXiv:2510.10157.

7. MorphAgent: Empowering Agents through Self-Evolving Profiles and Decentralized Collaboration. (2024). arXiv:2410.15048.

8. Minstrel: Structural Prompt Generation with Multi-Agents Coordination for Non-AI Experts. (2024). arXiv:2409.13449.

9. Hoppe et al. (2026). Controllable and Explainable Personality Sliders for LLMs at Inference Time. Sequential Adaptive Steering.

10. From Biased Chatbots to Biased Agents: Examining Role Assignment Effects on LLM Agent Robustness. (2025). arXiv:2602.12285.

11. Personality as a Probe for LLM Evaluation: Method Trade-offs and Downstream Effects. (2025). arXiv:2509.04794.

12. Human Psychometric Questionnaires Mischaracterize LLM Psychology: Evidence from Generation Behavior. (2025). arXiv:2509.10078.

13. Autogenesis: A Self-Evolving Agent Protocol. (2025). arXiv:2604.15034.

14. RPEval: Role-Playing Evaluation for Large Language Models. (2025). arXiv:2505.13157.

15. RMTBench: Benchmarking LLMs Through Multi-Turn User-Centric Role-Playing. (2025). arXiv:2507.20352.

16. A Survey of Self-Evolving Agents: On Path to Artificial Super Intelligence. (2025). arXiv:2507.21046.

17. Think Twice Before You Act: Enhancing Agent Behavioral Safety with Thought Correction. (2024). ResearchGate.

18. Personalized Steering of Large Language Models: Versatile Steering Vectors Through Bi-directional Preference Optimization. (2024). arXiv:2406.00045.

19. Beyond BFI: The CSI for Enhanced Reliability and Validity in Evaluating LLM Personality Traits. (2025). OpenReview.

20. PromptSage: A Novel XML-Structured Prompt Engineering Framework for Enhanced AI Behavior Control. (2025).
