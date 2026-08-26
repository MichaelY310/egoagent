# Heart Flow / Flow Relay（可选实验）

这是一个**可整块删除**的产品实验，不是 EgoAgent Project Portfolio 或 Session runtime
的依赖。目标不是再做一个番茄钟，而是把多 Project Agent 工作中的切换成本变成一个
可观察、可恢复的协议：

1. 一次只指定一个用户注意力前台；后台 Agent 可以继续运行。
2. 离开 Project 时从真实 Session 生成可编辑的 Ready-to-Resume Capsule。
3. token、thinking、普通工具步骤保持安静；只收集运行状态跃迁。
4. 非紧急后台结果在自然断点批量出现；权限审批立即出现。
5. 回到 Project 时先呈现目标、进展、阻塞、文件、测试状态和精确下一步。

默认启用本地演示；设置 `EGOAGENT_HEART_FLOW_ENABLED=0` 可关闭后端 mutation API。
运行状态保存在 `.egoagent/heart_flow.json`，不进入 Git。

## 删除方式

Heart Flow 会作为一个独立提交交付；最干净的删除方式是 `git revert <heart-flow-commit>`。
手工删除时：

1. 删除 `heart_flow/` 与 `harness_editor/src/heartflow/`。
2. 删除 `harness_editor/server.py` 中标记 `HEART_FLOW_DEMO_HOOK` 的 import 与两个 route hook。
3. 删除 `harness_editor/src/App.tsx` 中同名标记、`flow` tab 和 render block。
4. 从 `harness_editor/src/workbenchSession.ts` 和 Void extension 的 `WORKBENCH_TABS` 删除 `flow`。
5. 删除 `harness_editor/src/api/client.ts` 中 Optional Heart Flow API block；重新运行
   `npm run package:extension`。

完成上述操作后，多项目列表、同项目多 Session、fork/merge、Project 置顶与轨迹回放
全部保留。
