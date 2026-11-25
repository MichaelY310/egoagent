# EvoCert 四族真实任务 Pilot：结果、有效性审计与研究决策

日期：2026-09-02\
结论状态：**有研究信号，但当前方法和实验尚不足以投稿；停止扩大原协议，先重构。**

## 1. 我们真正测了什么

本实验不是证明“Agent 会修改自己”。它检验一个更窄的问题：一次持久化自进化同时修改
Identity (`I`)、Knowledge (`K`) 与 Flow (`F`) 时，能否从真实执行证据判断应该提交整个
bundle、其中一个最小子集，还是全部拒绝。

实验严格执行预注册文件
[`EVOCERT_REAL_PILOT_PREREGISTRATION_20260902.md`](./EVOCERT_REAL_PILOT_PREREGISTRATION_20260902.md)：

- Harness-Bench Fast 固定在 commit
  `e63712131fbb9cbd584df5e2012e06618a88de5e`；
- 4 个工具族，每族 1 个可见 validation、1 个 sealed held-out、2 个 protected task；
- 每个 task 完整执行 `none/I/K/F/IK/IF/KF/IKF` 八个 coalition；
- 总计 128 个 counted cells，每个 cell 使用全新 workspace 和原 benchmark verifier；
- 模型为本地 `Qwen2.5-Coder-14B-Instruct`，temperature 0，一张 L40S；
- 原始 workspace、Flow trace、工具结果和 verifier 结果均保留。

远端 counted run：
`/scr/yuanyang/egoagent-evocert/repo/experiments/evocert_real_pilot/_runs/20260902_qwen14b_pilot`

本地不可变汇总：
[`experiments/evocert_real_pilot/results/20260902_qwen14b_pilot`](../experiments/evocert_real_pilot/results/20260902_qwen14b_pilot)

## 2. 基础设施验证与排除记录

Counted run 前的失败没有混入结果：

| Run | 机械原因 | 处理 |
|---|---|---|
| `20260902_qwen14b_smoke` | 远端最小副本缺 `config.yaml` | 排除 |
| `20260902_qwen14b_smoke2` | 缺 capability packs | 排除 |
| `20260902_qwen14b_smoke3` | 缺 `harness_editor` runtime | 排除 |
| `integration_20260902_023103` | 模型把工具调用写成 fenced JSON，没有实际执行 | 排除 |
| `integration_20260902_024258` | compatibility fallback 只覆盖 non-streaming | 排除 |
| `integration_20260902_024912` | task fixture 丢失 Unix executable bit | 排除 |

随后修复了两个通用工程问题：

1. TaskBench fixture schema 增加显式 `executable` 位，导入、materialize 与 Harbor export
   均保留权限；
2. 对不完全兼容 OpenAI tool-calling 的本地模型增加 opt-in 严格 fallback：只接受一个完整、
   schema 中已知、无额外字段的 JSON tool call；多 block 或夹杂任意 prose 时拒绝解析。

修复后的非计数集成检查 `integration_20260902_030330` 完整通过：真实模型调用 `logq`、
生成 `report.json`，原始 verifier 通过，耗时 64.054 秒，10,224 tokens。

## 3. Counted 结果

### 3.1 Held-out 成功矩阵

单元格是原始 deterministic verifier 的二值结果，不是 LLM judge。

| Family | none | I | K | F | IK | IF | KF | IKF | 最小可行 coalition |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| logq | 0 | 1 | 0 | 1 | 0 | 1 | 1 | 1 | `I` |
| pktool | 0 | 0 | 0 | 1 | 0 | 1 | 1 | 1 | `F` |
| xtab | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | `IKF` |
| cfgctl | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | `none`（无有效候选） |

聚合观察：

- 32 个 held-out cells 中 10 个成功；4 个 `none` 全部失败；
- `IKF` 在 4 个 family 中通过 3 个，但其中 logq 和 pktool 是不必要的完整 bundle；
- logq 最小 coalition 是 `I`，pktool 是 `F`；简单 held-out/SEAL-style gate 都会多提交
  无必要 artifact；
- xtab 只有 `IKF` 成功，是本 pilot 最清晰的高阶非组合信号；
- cfgctl 整族为零，说明该 policy model 对这个 family 低于可用区间。

### 3.2 交互、错误与资源

- 冻结分析器发现 8 个绝对值至少 0.25 的二/三阶 held-out finite differences；
- logq 的三阶 `IKF` interaction 为 `+1`，同时 `IK=-1`；
- xtab 的 `IKF` interaction 为 `+1`，并且所有 proper subsets 均失败；
- 2/128 cells 因模型连续空响应进入 error，runtime error rate 为 1.5625%；
- counted run 目录 114MB，远低于 20GB ceiling；`/scr` 结束时仍有 4.8TB；
- 实验完成后已 SIGTERM 本次启动的 vLLM，GPU0 已释放。

`status="passed"` 只表示 Flow 正常结束；论文 outcome 必须看 `success` 和原 verifier，不能把
正常结束但产物错误的 cell 算成功。

## 4. 轨迹揭示的真实机制

结果不是“给模型更多 prompt 就一定更好”。例如 xtab held-out：

- `F` 与 `KF` 把真实列名幻觉成俄语，工具明确返回 `no such column`；
- `IF` 最终读到 header 并修正命令，但没有把输出写入要求的 `mean.json`；
- `IKF` 使用正确列名、成功调用 `xtab`、写入 `mean.json`，原 verifier 才通过。

这证明同一模型、同一预算、同一任务下，不同 artifact coalition 会改变工具反馈后的控制行为。
但一次轨迹不能证明稳定因果效应，第二重复原本是必要步骤。

## 5. Post-hoc 有效性审计

冻结 `analysis.json` 保留不变。独立的
[`posthoc_audit.json`](../experiments/evocert_real_pilot/results/20260902_qwen14b_pilot/posthoc_audit.json)
发现两个阻止我们立即扩大实验的问题。

### 5.1 Knowledge “activation”定义过宽

冻结指标把 K 的名称或标题出现在 trace 中算 activation。真实含义只是 Knowledge 被注册进
tool schema（advertised）：

| Family | K cells | advertised | invoked |
|---|---:|---:|---:|
| logq | 16 | 16 | 0 |
| pktool | 16 | 16 | 1 |
| xtab | 16 | 16 | 0 |
| cfgctl | 16 | 16 | 0 |

唯一一次调用发生在 pktool validation/K，Knowledge 结果随后确实被送入下一次模型调用，但该
cell 仍未通过。其余行为变化只能称为 **capability-advertisement context effect**，不能称为
Knowledge retrieval/consumption gain。

后续必须记录至少四级事件：`registered -> advertised -> invoked -> delivered/consumed`。

### 5.2 Protected gate 处于 metric floor

4 个 family 的两个 protected incumbent 全部失败，所有 protected coalition 也全部失败。
所以“IKF 没有比 none 更差”只是 `0 >= 0`，没有检测回归的统计能力。冻结分析中
`seal_style_promotes_IKF` 是机械结果，**不能解释为安全证书**。

后续 protected anchors 必须在冻结前通过独立 baseline screening，确保 incumbent 有非零成功率，
并使用 paired non-inferiority test，而不是单个二值 floor。

### 5.3 Proposer 过拟合 validation

14B proposer 常把 validation 的文件名、过滤条件和命令参数原样写进所谓“通用”协议。它没有
看到 held-out/protected 信息，也没有人工塞答案，因此不是数据泄漏；但它是典型的
proposal overfitting，说明 proposal 本身不可信，恰好是 admission layer 要解决的问题。

## 6. Novelty 审计：哪些不能再声称是贡献

以下均为 2026 年原始论文/preprint；正式写作前仍需检查版本和同行评审状态。

| 已有工作 | 已覆盖内容 | 对 EgoAgent claim 的限制 |
|---|---|---|
| [AHE](https://arxiv.org/abs/2604.25850) | 可逆组件、经验与决策可观测性、自动 harness evolution | “组件可编辑/可回滚/有轨迹”不新 |
| [Autogenesis](https://arxiv.org/abs/2604.15034) | 异构资源、版本、lineage、rollback、闭环 evolution protocol | “异构资源事务与版本”不新 |
| [HarnessCompass](https://arxiv.org/abs/2608.01918) | 受约束、component-wise harness evolution 与 interference/synergy | “组件化演化/干扰”不新 |
| [SHE](https://arxiv.org/abs/2608.09885) | System Prompt、Rule Bank、Safety Memory、Tool Policy 的归因式安全演化 | “Superego/规则分层后演化”不新 |
| [SEAL](https://arxiv.org/abs/2607.24300) | agent 外部 sealed acceptance | “sealed gate”不新 |
| [PACE](https://arxiv.org/abs/2606.08106) | anytime-valid repeated commit test | “统计 commit gate”不新 |
| [VaG](https://arxiv.org/abs/2608.05810) | Skill contamination、pre-commit critics、marginal subset selection | “最小子集/污染防护”不新 |
| [ABC II](https://arxiv.org/abs/2608.12895) | 相关失败下的 compositional reliability certificate | “不假设独立的可靠性证书”不新 |
| [HarnessOpt-Bench](https://arxiv.org/abs/2608.06301) | sealed budget 下的 harness optimization benchmark | “held-out harness 优化 benchmark”不新 |
| [EvoAgentBench](https://arxiv.org/abs/2607.05202) | 跨任务 procedural Ability transfer 与 uptake 诊断 | “经验变 Skill/Ability 并迁移”不新 |

因此，当前 EvoCert 的“全 factorial + 最小 coalition”本身最多是有用的 diagnostic，不足以作为
NeurIPS 主贡献。

## 7. 值得继续的重构方向

建议把主问题改成：

> **Persistent self-evolution 中，不同语义 artifact 通过隐式上下文、调用与控制流形成高阶耦合；
> 如何在不穷举所有组合的情况下，发现这些交互并只原子提交有证据的最小更新事务？**

方法暂名 **EvoCert-ATG (Artifact Transaction Graph)**：

1. **语义化 mutation transaction**：节点是 Identity、Knowledge、Flow、Tool Policy 等 typed
   delta；边明确声明“谁暴露谁、谁调用谁、谁消费谁”；
2. **runtime activation ledger**：记录 registered/advertised/invoked/delivered/consumed，避免把
   tool schema 出现误报成能力使用；
3. **稀疏交互发现**：先测 incumbent/full/singles，再根据失败模式自适应展开 leave-one-out 和
   suspected interaction groups；目标从 `2^k` 降到稀疏依赖图上的子指数/近线性查询；
4. **双证书**：utility 使用 paired anytime-valid evidence；Superego/Identity protected contracts
   使用有非零 baseline 的 non-inferiority evidence；
5. **原子 commit/rollback**：只提交最小已认证 connected subgraph，连同 Flow version、Identity
   version、轨迹和证书；失败时整笔回滚；
6. **counterfactual replay**：利用 EgoAgent 的真实 model envelope/node trace，在 mutation 首个
   影响点 fork replay，减少完整任务重跑成本；不能重放的外部副作用必须重新 sandbox 执行。

这个方向和已有工作的区分不在“也会 evolve”，而在：**高阶跨类型运行时耦合的可观测定义、
可扩展发现算法、以及面向原子持久化更新的统计认证。** 仍需新的算法与实验才能确认 novelty。

## 8. 下一轮实验必须先修什么

在任何更大实验前：

1. 用独立 screening pool 选择 incumbent 成功率非零的 protected anchors；screening 结果与正式
   test 隔离；
2. 把 activation ledger 接入 trajectory，而不是从 JSON 文本 marker 推断；
3. 给 proposer 增加 task-agnostic constraint checker，并把复制 validation 常量列为可拒绝证据；
4. 实现 adaptive interaction discovery，与 full factorial oracle 对照 query cost 和 selection error；
5. 至少 2 个模型、3 个随机种子、多个 task/family；报告 paired confidence/e-process，而非单次 0/1；
6. baseline 至少包括 whole-bundle、single/leave-one-out、SEAL、PACE、VaG-style marginal gate；
7. 只有当关键 interaction 在重复实验中符号稳定、protected gate 有统计功效、且 adaptive 方法以
   更少评测恢复 factorial oracle 时，才扩大到 50+ episodes 或形成论文 claim。

## 9. 当前最终判断

- **产品价值成立**：EgoAgent 已具备真实 typed artifact、版本、Flow 运行、轨迹、原 verifier 和
  可回滚实验基础；
- **科学问题真实存在**：logq 与 xtab 都出现了单 artifact 结论不足以解释的 coalition 行为；
- **当前论文方法不够**：与最新工作重叠较多，protected/activation 测量还有明显缺陷；
- **不应现在跑“大规模榜单”**：那只会更精确地重复一个测量有缺陷的协议；
- **应该先实现 EvoCert-ATG v2，再做新的预注册确认实验。**
