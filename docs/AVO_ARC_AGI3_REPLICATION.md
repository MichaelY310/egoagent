# AVO / ARC-AGI-3：EgoAgent Flow、自进化与真实实验报告

更新时间：2026-08-23

## 先说结论

EgoAgent 已能在官方 ARC-AGI-3 SDK 上运行真实未知环境，并用 Flow Graph 表达 AVO 风格的“主探索者 + 持久证据 + 上下文压缩 + 非行动监督器 + 变体生成 + 评测门控”。基础设施和可审计实验链路是跑通的。

但是，DeepSeek V4 Flash 在本次 `ls20`、`vc33` 小规模实验里**没有通过首关**。V2 scientific-search Flow 显著降低了 token 并能跑完整动作预算，自动生成的候选则没有带来官方主指标提升，因而没有候选被晋升。因此目前的准确表述是“实现并检验了 AVO-inspired 架构和证据驱动演化闭环”，不是“复现了 NVIDIA 的 100 分”。详见 [Self-Evolution V2](SELF_EVOLUTION_V2.md)。

## 原始资料与可复现边界

- NVIDIA 官方博客：[NVIDIA AVO Reaches 100% on ARC-AGI-3](https://developer.nvidia.com/blog/nvidia-avo-reaches-100-on-arc-agi-3-demonstrating-a-frontier-level-general-purpose-architecture-for-long-horizon-autonomous-agents/)
- AVO 论文：[Agentic Variation Operators for Autonomous Evolutionary Search](https://arxiv.org/abs/2603.24517)
- ARC 官方 SDK：[arcprize/ARC-AGI](https://github.com/arcprize/ARC-AGI)
- 官方 Agent 示例：[arcprize/ARC-AGI-3-Agents](https://github.com/arcprize/ARC-AGI-3-Agents)
- 官方 benchmarking：[arcprize/arc-agi-3-benchmarking](https://github.com/arcprize/arc-agi-3-benchmarking)

本地材料：

- `research/papers/AVO_2603.24517v1.pdf`
- `research/papers/ARC_AGI_3_Technical_Report.pdf`
- `research/upstream/arc-agi`
- `research/upstream/arc-agi-3-agents`
- `research/upstream/arc-agi-3-benchmarking`

重要限制：截至本次研究，论文描述的是 NVIDIA 内部开发 Agent，AVO 完整运行时源码并未随论文公开。因此能够复现的是论文/博客公开的算法结构和实验接口，不能声称逐行复刻其私有实现。

## NVIDIA 的方法是什么

### 论文中的 AVO

论文把传统写死的 variation operator 替换为一个自主 Agent：

```text
候选程序 P_t
  + 文档/知识 K
  + 正确性与性能评分 f
        ↓
自主 Agent 多轮读取、修改、编译、测试、profiling、修复
        ↓
只提交正确且 score 匹配或提升的 P_(t+1)
```

关键不是“一次让 LLM 生成更快代码”，而是让 Agent 自己决定下一步查什么、改什么、测什么，并把整个 lineage、测试结果、编译器/profiler 输出和失败尝试留在持久状态里。论文实验采用单 lineage 的长期演化搜索；只有通过 correctness gate 的候选才能进入下一代。

### ARC-AGI-3 扩展

官方博客强调两个外壳能力：

1. **Persistent memory**：上下文重置后保留过去假设、实现版本、评测反馈和失败路线，不从零再猜。
2. **Supervisor**：主 Agent 负责行动；监督器不行动，只监控整个轨迹，在停滞、重复和错误执念出现时提出不同策略。

ARC 观测使用精确的 64×64 文本网格而非图像 token。可迁移的是长期“假设 → 行动 → 反馈 → 保存证据 → 推翻/修正”循环，而不是 GPU 或某个游戏的领域知识。

## EgoAgent 新增实现

### 官方环境适配器

文件：`arc_agi3_runtime.py`

提供四个可搜索/可挂载工具：

- `arc_start`：启动官方游戏和 scorecard；同一 workspace/game 重复调用会恢复现有 session。
- `arc_act`：校验可用 action 和坐标，提交一步，并记录 prediction/reasoning。
- `arc_status`：获取当前精确状态，不消耗环境 action。
- `arc_finish`：关闭 scorecard 并返回官方 outcome。

每个 transition 保存：精确 `frame_text`、frame hash、changed-cell 数量、是否重访、模型行动前预测、行动后结果、官方 state。为了降低弱模型手工数 4096 个格子的负担，还添加了**确定性、无游戏知识**的：

- `scene_summary`：背景色、颜色计数、非背景连通组件及 bbox。
- `change_summary`：变化数量、bbox、颜色转移、变化连通区域和精确坐标。

它们是观测压缩，不包含关卡答案或隐藏规则。

### 三个求解 Flow

`arc_direct_baseline`：最薄的直接模型工具循环，用来观察单模型基线。

`arc_long_horizon`：

```text
Input
 → isolated persistent memory
 → pressure-triggered compactor
 → select bounded working context
 → Explorer (exactly one environment action)
 → tool policy / ARC tool
 → action counter
 ├─ ordinary step → loop
 └─ every 3 batches or stagnation/truncation
       → bounded supervisor context
       → Supervisor model (no action tools)
       → durable supervision memory
       → loop
```

配置：`harness/arc_long_horizon/config.json`

Identity：`identity/arc_explorer`、`identity/arc_supervisor`

运行间使用独立 `memory_namespace`，避免一个种子的规则猜测污染另一个种子。上下文压缩由 `component_context_compactor` 被动触发，不依赖 Explorer 主动想起。

`arc_scientific_search` 在长期 Flow 上增加了通用 `搜索控制` 组件：显式维护 hypothesis/evidence/experiment ledger，按信息增益与成本选择合法动作，在反例出现时降低或否定假设，并禁止没有新证据的旧假设复活。精确网格使用无损 row-RLE 文本压缩，同时在 trajectory 中保存原始 frame。

### 新增模型循环保护

最终 `vc33` 运行发现 V4 Flash 会在一个模型回复内部重复同一句假设，连续触发输出上限，却迟迟不行动。现新增通用、默认关闭、由 Flow 配置的 `Agent` 参数：

- `repetition_ngram_size`
- `repetition_ratio_threshold`
- `repetition_min_tokens`

达到阈值时运行时发出 `agent_stuck(reason=internal_ngram_repetition)`，并按图连线交给 Supervisor。`output_truncated` 也可作为普通 edge condition 路由。该能力不是 ARC 特例，任何长期研究/代码 Flow 都能使用。

## Flow 自进化

### 通用变体组件

`flow_variants.py` 与 `流程变体` 节点支持四种 typed operation：

- `set_field`
- `insert_node_on_edge`
- `remove_node_and_bypass`
- `redirect_edge`

操作受 allowlist 限制，采用 copy-on-write，生成前后 digest，写盘时原子替换，且必须通过 Flow schema/连通性验证。模型不能直接任意改 JSON 文件。

`component_flow_evolver` 接受：基础 Flow、真实 evaluation evidence、允许修改路径和字段语义；输出一组去重的隔离 candidates。每项 proposal 必须引用机器可验证的 evidence predicate。它**无权直接覆盖生产 Flow**。

### 门控规则

`paired_flow_promotion_decision` 先比较官方主指标：levels completed、score；只有主指标持平时才用 action、token、model calls 作为成本。默认要求至少 2 组 validation 和 2 组 held-out 配对；主指标持平时，两类 split 都必须获得至少 5% 的稳定成本改善。elapsed time 只作诊断。旧单 pair gate 只能返回 `needs_heldout`，不能正式 promote。

这避免了“模型说自己进化了”或只在训练 seed 上过拟合就覆盖原 Flow。

## 真实实验

官方 SDK 连通性证据：`experiments/arc_agi3/results/sdk_probe.json`。它获取了 25 个环境，启动 `ls20`，接收精确 64×64 网格，执行一个官方 action，再关闭 scorecard。

### 代表性结果

| Run | Flow / game | 官方 actions | Levels | Score | Model calls | 实际 tokens | 说明 |
|---|---|---:|---:|---:|---:|---:|---|
| `1787399534...` | direct / ls20 | 4 | 0 | 0 | 7 | 227,524 | 旧 token guard 提前终止 |
| `1787400966...` | long / ls20 | 12 | 0 | 0 | 19 | 429,220 | 完成预算；旧全局 memory，探索性结果 |
| `1787402449...` | evolved g002 / ls20 | 12 | 0 | 0 | 18 | 461,527 | 候选未提升，成本更高 |
| `1787403431...` | isolated long / ls20 | 22 | 0 | 0 | 43 | 1,050,347 | 30 步请求；发现 compactor 子图预算过小，已修 |
| `1787404501...` | isolated long / vc33 | 3 | 0 | 0 | 28 | 514,188 | 发现 session handle 丢失/重复 start，已修；排除 |
| `1787405231...` | fixed long / vc33 | 7 | 0 | 0 | 14 | 237,597 | 单 scorecard 连续运行，无重复 start |
| `1787409015...` | final long / vc33 seed 2 | 8 | 0 | 0 | 27 | 492,272 | 完整预算；暴露模型内部重复，促成通用 guard |
| `1787437842...` | scientific / vc33 seed 2 | 8 | 0 | 0 | 26 | 213,548 | 完整预算；输入 token 比 final long 低约 58.6% |
| `1787440539...` | scientific g008 c001 / vc33 seed 2 | 8 | 0 | 0 | 25 | 213,542 | 主指标持平，6-token 差异属噪声，不晋升 |

所有 JSON 位于 `experiments/arc_agi3/results/`。表中明确标出旧实现探索性 run；论文统计不应把它们混成同一实验条件。

### 自进化的真实结果

Generation 1：模型试图插入一个不符合节点 schema 的 validation 节点；修复后仍非法，静态验证拒绝，没有生成 candidate。

Generation 2：模型提出把 Supervisor cadence 从每 3 步改成每 4 步，并包含一个无效果字段写回。候选结构合法，随后在相同 seed/预算上真实执行：

- baseline：0 levels，0 score，12 actions，429,220 tokens
- candidate：0 levels，0 score，12 actions，461,527 tokens
- token 增长：7.5%
- 结论：主指标持平且成本回退超过 5%，自动拒绝；未写回生产 Flow。

完整证据：`experiments/arc_agi3/candidates/generation_002/evolution_report.json`

这证明了“生成 → 静态校验 → 隔离运行 → 官方指标门控 → 拒绝”链路；没有证明自进化带来性能提升。

Generation 3–8 将流程升级为 population + evidence grounding。模型真实产生过错误的网页搜索节点、不可能触发的 edge event、缺少表达式的 Condition、与轨迹相反的证据断言，以及对 `max_tokens` 字段的误读。这些问题分别被节点语义校验、evidence predicate 和字段语义 catalog 拦截。Generation 8 有两个候选通过静态门，但首个真实运行候选只减少 6 tokens、官方指标仍为 0；按新的配对 held-out 与 5% 成本门槛不能晋升。

## 为什么 V4 Flash 没有复现 AVO 成绩

轨迹显示的主要问题：

1. 手工解释 64×64 场景时投入大量 token，却没有形成可检验的最小假设表。
2. 观察反例后继续维护同一理论，行动的信息增益低。
3. 监督器能指出“停滞”，但 Explorer 未必执行建议。
4. 模型在 `vc33` 内部逐句重复同一个假设，输出截断后才继续。
5. 8/12/22 步小预算远小于 NVIDIA 报告的完整系统规模；驱动模型也不同。

因此，“只给弱模型加 memory 和 supervisor 就自然涌现满分”在本实验中被否定。

## 与 NVIDIA 100% 还缺什么

下列前三项和多 seed/held-out 门控已经作为通用 Component 实现。尚缺的关键能力是：

1. **state abstraction learner**：从 exact grid 学可复用对象/关系状态，而不是每轮重读原始格子。
2. **cross-level memory protocol**：明确哪些规则可继承、哪些布局细节必须清除。
3. **足够规模的配对实验**：基础设施已支持多 validation/held-out，但尚未用当前额度完成完整矩阵。
4. **更强驱动模型与同等预算**：要比较 NVIDIA 数字，必须使用接近的模型、25 环境/183 levels 和正式 action budget。

这些都适合继续做成 Flow Component，而不应写进 ARC 工具或 Identity 的隐藏规则。

## 如何运行

安装可选 SDK：

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements-arc.txt
```

只验证官方 SDK：

```powershell
.\.venv\Scripts\python.exe .\experiments\arc_agi3\probe_official_sdk.py --game ls20 --seed 0
```

运行基线、长期或 scientific Flow：

```powershell
.\.venv\Scripts\python.exe .\experiments\arc_agi3\run_deepseek_pilot.py --flow arc_direct_baseline --game ls20 --seed 0 --actions 12
.\.venv\Scripts\python.exe .\experiments\arc_agi3\run_deepseek_pilot.py --flow arc_long_horizon --game vc33 --seed 2 --actions 8
.\.venv\Scripts\python.exe .\experiments\arc_agi3\run_deepseek_pilot.py --flow arc_scientific_search --game vc33 --seed 2 --actions 8
```

生成变体与门控：

```powershell
.\.venv\Scripts\python.exe .\experiments\arc_agi3\evolve_flow.py --source-result .\experiments\arc_agi3\results\1787400966-arc_long_horizon-ls20-0f70c6.json --generation 3
.\.venv\Scripts\python.exe .\experiments\arc_agi3\gate_candidate.py --baseline .\experiments\arc_agi3\results\BASELINE.json --candidate .\experiments\arc_agi3\results\CANDIDATE.json --report .\experiments\arc_agi3\candidates\generation_003\evolution_report.json
```

真实网络实验会消耗模型额度；每次结果都使用新 memory namespace，且密钥只从本地环境读取。

## Leaderboard 解释

ARC 官方 leaderboard 与社区 harness research 的规则不同。这个项目研究的是 harness/Flow，因此结果应作为社区/研究实验报告，不能未经官方评审直接声称与官方认证榜同口径。
