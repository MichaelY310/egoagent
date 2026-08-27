# Heart Flow：多 Project Agent 工作的注意力续接设计

日期：2026-08-27  
实现名：**Flow Relay**  
状态：可删除产品实验，未并入核心 runtime

## 问题不是“Project 太多”，而是恢复成本不可见

AI Agent 让多个 Project 并行推进成为可能，但人的工作记忆没有因此并行。典型失败链是：

```text
后台 Agent 有新进展 → 用户立即切换 → 原任务注意残留
→ 重新寻找目标/文件/测试状态 → 处理新结果 → 再次切换
→ 每个 Project 都在动，但没有一个进入持续、清晰、可控的深工作
```

这不是单纯的效率焦虑。Leroy 的实验把未完成任务造成的后续任务性能下降称为
attention residue；后续研究表明，在切换前形成一个具体的 ready-to-resume plan 可以
缓解这种残留。中断研究则反复观察到：人在中断前为恢复做准备、以及在返回时拥有与
原任务相关的线索，都会缩短 resumption lag。

软件开发场景尤其敏感：理解代码、未验证假设、当前文件和运行状态共同构成一个很大的
心理工作集。开发者中断研究显示，任务类型、时点和恢复策略都会影响恢复成本，因此
“每个 Agent 完成时立刻通知”并不是中立策略。

## 调研依据

- Sophie Leroy, 2009，Attention residue：
  https://doi.org/10.1016/j.obhdp.2009.04.002
- Leroy & Glomb, 2018，Ready-to-resume plan：
  https://doi.org/10.1287/orsc.2017.1184
- Trafton et al.，中断前准备降低恢复时间：
  https://www.sciencedirect.com/science/article/pii/S1071581903000235
- Altmann & Trafton，恢复线索降低 resumption lag：
  https://interruptions.net/literature/Altmann-CogSci04.pdf
- Parnin / Rugaber 等软件开发中断实证任务与问卷：
  https://arxiv.org/abs/1805.05508
  https://arxiv.org/abs/1805.05504
- Fitz et al.，237 人随机对照实验：批量通知相较持续通知改善部分注意、压力与幸福感指标；
  完全关闭通知会提高错失焦虑：
  https://www.sciencedirect.com/science/article/pii/S0747563219302596
- Microsoft Research：在 meaningful breakpoints 给出 task/break 建议；用户对 task 和
  break 建议的接受率分别达到 85.7% 与 77%：
  https://www.microsoft.com/en-us/research/?p=647556
- Flow 的常见前因包括清晰目标、控制感、挑战-技能匹配和即时反馈：
  https://www.tandfonline.com/doi/full/10.1080/17439760.2014.967799
  https://pmc.ncbi.nlm.nih.gov/articles/PMC7751419/

产品参照不是照抄 UI：Codex app 已采用 Project 下的独立线程、并行 Agent、worktree 和
持久历史；VS Code multi-root workspace 说明资源可以跨 root 组织；Claude Code 提供
session resume。它们解决了“东西放在哪里”，但仍给 EgoAgent 留下一个问题：**系统何时
应该请求人的注意，以及人回来时到底看到什么？**

- Codex app：https://openai.com/index/introducing-the-codex-app/
- OpenAI 内部的 Codex task queue：https://openai.com/business/guides-and-resources/how-openai-uses-codex/
- VS Code multi-root：https://code.visualstudio.com/docs/editing/workspaces/multi-root-workspaces
- Claude Code session resume：https://docs.anthropic.com/en/docs/claude-code/cli-usage

## 评估过但没有采用的方案

### 1. 只做一个 All Projects Dashboard

能改善可发现性，不能减少切换；实时数字越多，越容易变成注意力老虎机。Project
Portfolio 已经负责“找得到”，Heart Flow 不再复制一套管理看板。

### 2. 只加番茄钟或强制锁定

计时能形成边界，却不知道 Agent 是否正等待审批、用户是否已到自然断点，也不能帮助
恢复复杂的代码工作集。强制锁定还会损害控制感。

### 3. 每次切换都调用 LLM 总结

速度、价格、离线可用性和事实漂移都不理想。更糟的是，为了降低切换成本又制造一次
需要等待的 Agent 调用。原型先从真实 Session 确定性提取，用户可编辑；后续可把 Model
摘要作为可插拔增强，而不是正确性的依赖。

### 4. Agent 完成就自动切换 Project

这把调度权从用户手里拿走，会在不合适的认知阶段打断。系统应路由注意力，而不是遥控
注意力。

### 5. 完全关闭通知

研究中的完全关闭会带来错失焦虑，权限审批也可能让后台任务永久阻塞。因此采用分级：
审批立即；普通完成、失败和等待输入进入批量 inbox；当前前台 Project 的事件可即时显示。

## 最终方案：Flow Relay

### A. Focus Contract

用户明确选择一个前台 Project 和一个时间边界。WIP 是软限制，不禁止后台并行；它只提醒
有多少 Project 正在消耗“需要用户亲自思考”的注意预算。这样保留控制感，也不给用户
制造惩罚式流程。

### B. Ready-to-Resume Capsule

切换前保存七类字段：目标、已知进展、精确下一动作、阻塞/未决、相关文件、测试状态、
来源 Session。胶囊来自 Session 的真实审计记录，不替换轨迹、不篡改模型上下文；用户可以
修改目标和下一步。它是恢复界面，不是新的“真相数据库”。

### C. Attention Router

只观察 run 的语义状态跃迁：

- `approval`：立即；
- 当前 Project 的 `waiting/completed/failed`：立即但不抢焦点；
- 后台 Project 的 `waiting/completed/failed`：批量；
- `running`、token、thinking、普通 tool event：不生成通知。

默认投递点是自然断点，也可选择专注结束或全部立即。

### D. Re-entry Briefing

进入 Project 时第一屏只回答三个问题：我在做什么、已经知道什么、现在第一步是什么。
文件/测试/阻塞证据仍可展开。进入不是一次自动总结调用，也不会把全部后台历史塞进当前
Agent 上下文。

## 为什么这是当前最可接受的方案

- **低摩擦**：不强制用户采用新工作法；未开启 Focus 时 Portfolio 照常使用。
- **可信**：默认确定性提取、字段可编辑、保留 Session 来源。
- **不制造新噪声**：状态跃迁去重，运行中和 token 流保持安静。
- **符合 Agent 特性**：后台可以真正并行，但人的注意力仍串行调度。
- **可验证**：不是“感觉更专注”的抽象承诺，可测恢复时间、切换次数和错误率。
- **可退出**：独立包、独立 UI、单一状态文件、独立 Git 提交。

## Demo 操作

1. 启动 EgoAgent，在 Void 中点 `Open Agent Workbench`。
2. 点 `More → Heart Flow`。
3. 在 Project 列表给当前 Project 点 `专注`。
4. 如果它已有 Session，胶囊会提取最近目标、助手进展、文件、测试和阻塞；修改“恢复后
   第一步”并保存。
5. 给第二个 Project 点 `专注`：系统先为前一个 Project 更新胶囊，再切换 Focus。
6. 后台 Agent 到达等待输入/完成时刷新页面：非当前 Project 进入 batched inbox；审批进入
   `现在处理`。
7. 回到原 Project，顶部和 Capsule 面板直接显示离开前的落点；点 `查看 Session` 进入真实
   Session/轨迹，点 `在 IDE 打开` 会在新窗口打开 workspace。
8. 如果想沿着这个落点尝试两个方向，直接点胶囊右上角 `Fork`；如果另一个 Session
   已经完成了相关探索，点 `Merge`。这里复用 Sessions 页面完全相同的血缘与合并实现。

## 建议的用户实验

采用 within-subject 交叉设计，让同一用户分别使用普通 Portfolio 与 Flow Relay 完成三个
交错代码任务。记录：

- 从切换回来至第一次有效 edit/test 的 resumption latency；
- 每小时人工 Project switch 数；
- 重复 read/search/test 次数；
- 权限审批等待时间；
- 任务错误率与完成时间；
- 7 分量表的心流、控制感、打断感和信任；
- 胶囊被编辑的比例（用于判断确定性提取是否真正有用）。

小样本先验证 resumption latency 与重复工具调用；若无明显改善，不应把它升级成核心产品
功能。若有效，再比较确定性胶囊、LLM 胶囊和人工胶囊，而不是一开始就把模型质量与交互
机制混为一个变量。
