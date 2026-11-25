# EgoAgent 组合消融预注册（2026-09-08）

本轮实验回答两个不同问题，而不是笼统比较“功能越多是否越强”。所有组使用同一个底层组件、同一 Identity、同一题目与同一评测器，仅改变声明的布尔开关。

## Study A：工具结果裁剪 × 被动上下文压缩

- 任务：`product_large_observation_repair`
- 因子 A：`enable_tool_pruning`
- 因子 B：`enable_compaction`
- 固定关闭：主动 curation、memory、evolution、delegation
- 固定压力参数：16,384 token 声明窗口、0.60 高水位、0.40 压缩目标、256 token 最小净收益
- 四组：00 无治理、10 仅裁剪、01 仅压缩、11 两者组合

任务要求完整读取约 55 KB 的源文件，权威 contract 位于头部，缺陷实现位于尾部。确定性测试同时检查功能正确性和文件内容。lossless trajectory 必须保存完整 observation；裁剪只允许改变下一次模型调用看到的 working context。

## Study B：主动 curation × 被动上下文压缩

- 任务：`product_context_endurance_ledger`
- 因子 A：周期性 model-authored curation
- 因子 B：达到水位后触发的被动 compaction
- 四组：00 无治理、10 仅 curation、01 仅 compaction、11 两者组合

任务包含 25 个连续回合、四个必须逐字保留的 durable facts 和大量可删除 TRACE 噪声。最终回合要求精确恢复四个事实。

## 固定判据

正确性优先：只有 `status=passed`、`score=1.0` 的处理才有资格进入推荐配置。主要成本指标为 provider 返回的 `tokens_actual`，其次为 `elapsed_seconds`、`model_calls` 和未缓存输入 token。

对越低越好的指标 `T`，组合交互定义为：

`interaction = T(10) + T(01) - T(00) - T(11)`

- `interaction > 0`：存在正的 difference-of-differences 交互；只有两个单功能都优于 00、11 又优于两个单功能，并且两个机制在 11 的 trace 中均实际触发时，才称为成本上的 `1+1>1`。
- `interaction ≈ 0`：近似可加。
- `interaction < 0`：机制重叠、互相干扰或额外开销；不能宣称协同。

同时要求 trace 中出现与开关一致的 `tool_prune`、`block_plan` 或 `turn_plan` 事件，防止把“开关已打开但功能没有触发”误算成有效实验。

> 2026-09-08 pilot 勘误：最初只用 interaction 的符号判定“协同”，会在某个单功能本身有负收益时产生反直觉结论。上述 dominance 与共同触发条件在读取 R1 数值后、运行后续确认实验前补入；R1 原始轨迹与旧输出均保留，不覆盖历史证据。

## 产品化规则

1. 通过率下降的组合不进入系统推荐 Agent。
2. 只在长上下文才有收益的功能不进入 Fast profile。
3. 增加 token/延迟但提供隔离、审计或迁移价值的功能单独标注，不伪装成效率优化。
4. 默认 Agent 使用经实验支持的最小功能集；昂贵的 evolution/delegation 由路由或显式指令选择。
