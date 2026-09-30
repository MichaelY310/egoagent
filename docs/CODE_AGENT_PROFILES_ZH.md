# EgoAgent 用户级 Code Agent

普通使用者只需要看四个入口。底层实验 Flow 与消融 Flow 仍可在 Task Bench 中复现，但不会继续挤满 Chat 的 Harness 下拉框。

## 1. Code Agent · Auto（默认推荐）

Flow 名称：`code_agent_auto`

每条用户请求先经过一次很小的私有路由调用，然后复用下列运行档位：

- **Fast**：只读解释、明确的小修改、约 1–3 个文件；使用有计划、检查点、事务化改动与证据判断的轻量执行循环。
- **Standard**：普通多文件开发；启用能力搜索、长期记忆、被动上下文压缩、工具结果裁剪与双重审查，不启用周期性进化和子 Agent。
- **Long**：跨多轮、超长上下文、创建复用能力或自进化任务；在 Standard 上增加受验证的 Skill 进化，但默认不做高频主动清理，也不启动子 Agent。
- **Team**：至少两个足够大、边界清晰且能独立测试的子系统；在 Standard 上增加有代价门控的隔离子 Agent，但不同时启动进化。

用户可以在请求开头写 `/fast`、`/standard`、`/long` 或 `/team` 覆盖自动判断。路由结果会写入运行轨迹中的 `route` 节点和最终运行结果，不会作为一条多余聊天回复污染对话历史。

## 2. Code Agent · Fast

Flow 名称：`code_agent_fast`

适合日常小任务：解释代码、修改一个函数、补一个单元测试、修一个明确错误。它不会为了展示能力而搜索 Skill、创建子 Agent 或自进化，因此延迟和 token 开销最低。

## 3. Code Agent · Long / Evolving

Flow 名称：`code_agent_long`

适合长时间自主任务、跨 Session 工作和重复工程模式。它启用能力发现与热加载、工作区长期记忆、被动上下文压缩、重复工具守卫、超长工具输出裁剪、周期性 Skill 进化、检查点、改动事务与独立质量/安全审查。

进化不是每条消息都强制发生：默认每 6 个已完成用户轮次检查一次，并且只有发现可复用、可验证的重复工作时才保存并热加载新能力。组合消融显示高频主动 curation 会破坏 provider prefix cache，而通用 delegation 在任务不够大时增加成本，因此二者不再是 Long 的默认开关。

## 4. Code Agent · Team

Flow 名称：`code_agent_team`

只在任务确实包含多个大而独立的修改范围时使用，例如两个互不依赖的 package 各自有 contract 和测试。主 Agent 保留完整任务，子 Agent 只得到被测量过的 bounded scope；最终答案、审查与完整训练轨迹会重新汇总到主 Session。它的价值是上下文隔离和并行组织，不承诺在小任务上更省 token。

## 推荐 Identity

四个入口均默认使用 `adaptive_deepseek_coder` 作为主工程师与 governor；质量、安全 reviewer 使用 `deepseek_operator`。用户仍可在 Agent 配置中分别替换每个 slot。

## 在前端使用

1. 打开 Chat 顶部的 **Agent 配置**。
2. 模式选择 **Agent · 执行任务**。
3. Harness 选择 `Code Agent · Auto (recommended) · code_agent_auto`；新 Session 默认已经选择它。
4. 普通任务直接发送。明确想省钱时写 `/fast`；重复模式和进化写 `/long`；多个独立大范围写 `/team`。
5. 打开 **Agent Workbench → Build**，从 Chat 点击“观察”可以看到 Auto 的 override/router、`is_fast/is_long/is_team` 与实际 `run_*` 子 Flow。
6. Chat 的 **改动** 页审阅事务化代码块；运行轨迹和 Task Bench 报告会保留实际 Flow 版本、Identity、节点、工具、模型用量和子 Agent 关系。

## 设计边界

这四个入口没有复制 Code Agent 实现。Fast 复用 `product_core_code_agent`；Standard、Long 与 Team 复用同一个 `product_adaptive_code_agent`，只通过组件输入开关高级机制。因此修复底层执行循环时，所有产品入口会同时获得修复，也不会产生多套逐渐漂移的代码。

## 为什么是这些默认组合

以下是此前少量合成任务的探索记录，不是本轮发布回归，也不是统计充分的公开 benchmark 结论。原始运行结果未随本次产品提交发布；这些数字仅说明默认组合的设计背景，不能据此承诺真实项目中同样省 token 或必然发生自进化。

- 跨 Session 记忆：无记忆对照只答对 1/2；开启后答对 2/2，同时实际 token 从 31,293 降到 20,311。
- 工具结果裁剪：约 55 KB observation 修复中保持正确，复现实验从 315,740 降到 109,133 token；2026-09-08 新四格实验为 293,041 → 81,714。
- 被动压缩：25 回合精确事实任务中保持 4/4 recall，旧实验从 80,657 降到 58,999；新实验从 82,332 降到 63,336。
- 高频主动清理：新四格实验中仅 curation 为 83,295，组合为 93,922，均差于 82,332 基线；不进入默认组合。
- 进化：第一次学习显著更贵，但 fresh transfer 从 94,087 降到 73,511 token，并由 14 次工具调用降到 3 次；只放在 Long。
- 委派：通过 12/12 测试并实现子上下文隔离，但旧对照显示总 token 增加约 29%；只放在 Team。
