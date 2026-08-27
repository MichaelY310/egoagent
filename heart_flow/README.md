# Heart Flow / Flow Relay（可选实验）

这是一个**可整块删除**的产品实验，不是 EgoAgent Project Portfolio 或 Session runtime
的依赖。目标不是再做一个番茄钟，而是把多 Project Agent 工作中的切换成本变成一个
可观察、可恢复的协议：

1. 一次只指定一个用户注意力前台；后台 Agent 可以继续运行。
2. 离开 Project 时从真实 Session 生成可编辑的 Ready-to-Resume Capsule。
3. token、thinking、普通工具步骤保持安静；只收集运行状态跃迁。
4. 非紧急后台结果在自然断点批量出现；权限审批立即出现。
5. 回到 Project 时先呈现目标、进展、阻塞、文件、测试状态和精确下一步。
6. 续接胶囊可直接 Fork 或 Merge Session；它不会另存一份不兼容的“Heart Flow 会话”。

## 用人话理解它

Heart Flow 不是让你少开 Agent，也不是强迫所有 Project 排队。Agent 可以在后台并行，
但人在任意时刻通常只能认真思考一个问题。因此它把“机器并行”和“人的单线程注意力”
分开管理：

- **Focus** 是你此刻亲自思考的 Project，不会暂停其他 Agent。
- **续接胶囊** 像离开工位前留给自己的便签：做到哪了、卡在哪、改了哪些文件、回来后
  第一件事做什么。它来自真实 Session，而且可以手动改。
- **Attention Router** 像一个安静的秘书。普通 token、思考和工具步骤不打断你；后台完成
  等消息先攒起来，权限审批这种需要人立即决定的事情才马上出现。
- **WIP** 只是“建议同时亲自操心几个 Project”的软限制，不会禁止后台并发。
- **Fork/Merge** 解决分支思考：Fork 把当前上下文复制成独立路线；Merge 把另一个路线的
  新信息带回来，并保留来源和血缘。

所以它解决的不是“怎样同时盯住十个窗口”，而是“切回来时不用花十分钟重新回忆”。

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
