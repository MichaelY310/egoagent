# Self-Evolution V2：证据驱动的 Flow 演化

更新时间：2026-08-23

## 目标

EgoAgent 的自进化不再等同于“让模型重写一份 Flow JSON”。V2 把演化定义为一个可审计的闭环：

```text
真实运行轨迹
  → 提取机器可检查的失败证据
  → 生成多个、互不重复的最小变体
  → 验证证据引用、字段路径、节点语义和图结构
  → 隔离运行 validation 与 held-out 任务
  → 只按实测主指标和成本决定晋升或拒绝
```

模型可以提出假设，但不能自己宣布假设成立，也不能直接覆盖生产 Flow。

## 主要能力

### 1. 科学搜索控制器

`self_evolution/search_control.py` 实现了通用的结构化搜索状态：

- hypothesis：假设、置信度、支持证据、反例和状态；
- evidence：动作前预测、动作后观察、状态变化和来源；
- experiment：要区分的假设、预期信息增益、成本和精确动作；
- selector：优先选择信息增益/成本更高且合法的实验；
- counterexample enforcer：预测失败会降低或否定假设；没有新支持证据时，已否定假设不能被重新激活；
- action validation：在送入环境前检查动作、坐标和当前 action space。

它通过普通 Flow 节点 `搜索控制` 暴露，因此 ARC、代码优化、数据实验或浏览器探索可以复用同一机制。组件模板是 `component_scientific_search_controller`。

### 2. ARC scientific-search Flow

`arc_scientific_search` 把下列部分组装成一个可编辑 Flow：

- Explorer：提出假设和候选实验；
- Scientist：维护 belief/evidence ledger；
- Search Controller：确定性筛选下一条合法、高信息增益动作；
- ARC Tool：每轮只执行一个环境动作；
- Supervisor：停滞、无合法动作、重复输出或周期检查时介入，但不直接行动；
- Persistent Memory 与被动 Context Compactor：跨上下文窗口保留有效证据。

ARC frame 同时保留原始精确网格与无损 row-RLE 文本。连续重复行/单元格会写成如 `r0-r23: 3*32 0*32`，不会注入游戏规则，也不会牺牲可回放性。

### 3. 有证据约束的变体生成

`component_flow_evolver` 获得的是测量结果、允许修改的真实叶子路径、字段语义和可引用证据路径。模型输出的每项变更必须包含 `evidence_refs`，例如：

```json
{
  "operation": {
    "op": "set_field",
    "path": "nodes.act.inputs.max_tokens",
    "value": 2048
  },
  "evidence_refs": [
    {"path": "failure.output_truncated", "op": "eq", "value": true}
  ]
}
```

运行时会对引用执行 `eq/ne/gt/gte/lt/lte/in` 谓词。路径不存在、断言为假、修改无效果或重复 proposal 都会被拒绝。提示词不是信任边界，确定性校验器才是。

### 4. Typed mutation 与节点语义验证

目前支持：

- `set_field`
- `insert_node_on_edge`
- `remove_node_and_bypass`
- `redirect_edge`

每个变体 copy-on-write 到隔离目录，并检查：

- 修改路径在 allowlist 内；
- 修改前后 digest 不同；
- Flow schema、端口和连通性合法；
- Condition 节点具有条件表达式；
- Tool 节点具有显式调用来源；
- 新 edge 的 event 确实可能由源节点产生。

这会拦截“JSON 能解析但永远不会运行”的伪变体。

### 5. 多候选与严格晋升

每代可以生成一个去重 population，而不是把第一次采样当答案。晋升采用配对测试：

- 默认至少 2 个 validation pair；
- 默认至少 2 个 held-out pair；
- 任一主指标（例如 level/score）下降即拒绝；
- 主指标提升才算能力提升；
- 主指标完全持平时，validation 和 held-out 两边都必须至少降低 5% 成本才允许晋升；
- elapsed time 只作诊断，token、model calls、environment actions 才用于稳定成本门控。

旧的单 baseline/candidate 比较只会返回 `needs_heldout`，不能正式晋升。

## 非作弊边界

- ARC 工具只暴露官方 action/state 与确定性网格摘要，不包含 game id 对应规则。
- 搜索控制器只处理假设、证据、预算和合法动作，不知道具体游戏答案。
- Evolver 看得到真实轨迹统计，但不能写入生产 Flow，也不能伪造 evaluator 指标。
- 候选必须在未用于提案的 held-out game/seed 上再次通过。
- 每个拒绝原因、输入证据、candidate digest 和实测 result 都保存在 evolution report。

## 真实 DeepSeek V4 Flash 试验

同一 `vc33 / seed 2 / 8 actions` 条件下：

| Flow | Levels / score | Actions | Model calls | 实际 tokens | 耗时 |
|---|---:|---:|---:|---:|---:|
| `arc_long_horizon` | 0 / 0 | 8 | 27 | 492,272 | 280.6 s |
| `arc_scientific_search` | 0 / 0 | 8 | 26 | 213,548 | 182.6 s |
| generation 8 candidate 1 | 0 / 0 | 8 | 25 | 213,542 | 170.5 s |

Scientific Flow 将输入 token 降低约 58.6%，并解决旧版本在完整动作预算前卡住的问题，但没有解出首关。generation 8 候选只少了 6 tokens，属于噪声；按 V2 的 5% validation + held-out 门槛不能晋升。

generation 3–8 的自动演化还暴露并推动修复了几类真实失败：

- 把 scientific search 错解成网页搜索；
- 创建源节点不可能发出的 edge event；
- 创建没有 condition 的 Condition 节点；
- 提出与运行证据相反的因果解释；
- 把 `max_tokens`（单次模型输出上限）误解成上下文长度或调用次数。

这些候选均由模型真实生成；系统没有为了得到“进化成功”而强行接受它们。

证据文件：

- `experiments/arc_agi3/results/1787409015-arc_long_horizon-vc33-bebc54.json`
- `experiments/arc_agi3/results/1787437842-arc_scientific_search-vc33-50001d.json`
- `experiments/arc_agi3/results/1787440539-arc_scientific_search_candidate_g008_c001-vc33-85991b.json`
- `experiments/arc_agi3/candidates/generation_003/` 至 `generation_008/`

## 使用方法

运行 scientific Flow：

```powershell
.\.venv\Scripts\python.exe .\experiments\arc_agi3\run_deepseek_pilot.py `
  --flow arc_scientific_search --game vc33 --seed 2 --actions 8
```

从真实结果提出一代多候选：

```powershell
.\.venv\Scripts\python.exe .\experiments\arc_agi3\evolve_flow.py `
  --source-result .\experiments\arc_agi3\results\RESULT.json `
  --generation 9 --population 4
```

对 baseline/candidates 运行配对矩阵：

```powershell
.\.venv\Scripts\python.exe .\experiments\arc_agi3\run_evolution_matrix.py `
  --report .\experiments\arc_agi3\candidates\generation_009\evolution_report.json `
  --validation vc33:2 --validation ls20:0 `
  --heldout ft09:1 --heldout as66:3 --actions 8
```

执行 population gate：

```powershell
.\.venv\Scripts\python.exe .\experiments\arc_agi3\gate_population.py `
  --matrix .\experiments\arc_agi3\candidates\generation_009\evaluation_matrix.json `
  --report .\experiments\arc_agi3\candidates\generation_009\evolution_report.json `
  --candidate-id g009_c001
```

真实网络实验会消耗 API 额度。密钥只从环境变量读取，不写入 Flow、报告或仓库。

## 当前尚未证明的部分

V2 证明了更可靠、更节省 token 的控制与严格的反伪进化门控；它尚未证明弱模型能在 ARC-AGI-3 上产生正向能力演化。下一步真正有研究价值的工作是：

1. 从精确网格学习跨帧对象/关系抽象，而不依赖人工游戏规则；
2. 将 hypothesis ledger 跨 level 迁移，同时自动清除布局特例；
3. 在足够多的 game/seed 上运行完整 paired population study；
4. 比较单 lineage、population、supervisor 与 structured search 的消融；
5. 用更强模型重复实验，区分控制器瓶颈与基础模型瓶颈。

在这些实验完成前，不应声称复现 NVIDIA AVO 的 ARC-AGI-3 100% 结果。
