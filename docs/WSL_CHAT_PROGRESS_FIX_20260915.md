# WSL 大项目无反馈与 Chat 实时过程修复

## 现场证据

项目：`/mnt/c/Users/aa310/Desktop/FastVideo-main`。
Session：`code_agent_auto_20260915_121844_e8f0aa20`。
问题并非简单的 API 不通：路由和规划已经调用成功，但前置检查点用时
305,816 ms，后置检查点用时 293,684 ms。旧实现先 `rglob` 整棵目录树再过滤，
还会全量读取每个文件计算 SHA256；WSL 的 Windows 挂载路径对此尤其慢。

另一个实测问题：Auto 委派的子 Flow 有 `_non_interactive=True`，原实现据此
直接拒绝安全审批。卡片虽然被发出，却立即变成拒绝，用户没有决策机会。
这轮原始记录的两次 `run_command` 均因此没有实际执行。

## 改动

- `workspace_revisions.py`：先剪枝，再增量读取；每次扫描默认 3 秒、32 MiB、
  5,000 个文件预算；跳过设备、FIFO 等特殊文件，支持取消、缓存和文件变化检测。
- 扫描不完整会保留 `complete=false` 和省略信息，不伪造一致性。检查点仍保存
  会话/流程状态，但严格恢复会将不完整校验视为冲突，需显式确认；不是备份所有文件。
- Chat 准备上下文最多等待 4 秒，检索最多计算约 2 秒；冷索引不会在提交路径上全量建立。
  选区/附件保留，未建立索引时 Agent 仍可通过工具按需读文件，显式索引 API 不变。
- 安全审批和子 Flow 的对话输入分离：审批回到拥有它的根 Session 输入通道；
  子 Flow 不获得自己的交互循环。无人值守根流程默认仍拒绝，没有自动允许高风险操作。
- 发送后同步创建“Agent · 执行过程”气泡；显示阶段、模型等待/回答、命令参数、
  工具执行中/完成/失败和审批等待。结束后过程可展开；用户手动折叠不会被每个 token 重置。
- 提供 `tool_start` / `tool_end`、`reasoning` 事件及可恢复的 `chat_progress` 状态，
  WebSocket 实时显示，HTTP 轮询可补齐。不同 Session 仍用原有作用域隔离。
- thinking 仅展示提供商实际返回的内容，不生成假思考。设置了 Superego 输出脱敏时，
  先完整过滤再显示，防止拆成多个 token 的秘密泄漏。非流式 Model 节点只能在返回时显示。
- 工作区自动记忆不再把 `[System] Working directory` 当成上次用户请求；历史记忆明确
  标为参考，不能替代新消息。

## 验证

自动化最终结果：169 项 Python 测试、9 个 subtests、16 项 Node 测试通过。
覆盖检查点恢复/冲突、扫描预算、子 Flow 审批转发、无人值守拒绝、thinking 流和跨 token
脱敏、工具开始/结束顺序、跨 Session 隔离、上下文超时及即时气泡。

真实浏览器 + WSL + 已配置 DeepSeek Flash：

- 合成目录 `/tmp/egoagent-progress-7sa644`，只有 `.vscode/launch.json` 和 `main.py`。
  不含真实项目源码、密钥或个人数据。
- 默认 `code_agent_auto`，发送“只读 .vscode/launch.json，简要解释，不改文件、不运行命令”。
  观察到即时气泡、`read_file` 和正确解释：Debug application 启动 main.py + --demo，
  Debug unit tests 运行 unittest discover -v。没有运行命令或修改文件。
- 该小目录前/后检查点分别约 19 ms / 13 ms。另在原 FastVideo 路径做只读校验扫描，
  约 3 秒按预算退出，明确标为不完整；二者是不同规模的测量，不是同一任务的加速比。
- thinking 使用确定性模型适配器验证流式、归属和脱敏；真实 Flash 测试未强制开启思考模式。
- 真实命令测试：保持审批等待，点击“允许一次”，气泡立即显示 `exec_command · 执行中`
  以及 `python3 main.py` 命令。脚本有意等待 8 秒，实测约 8.06 秒后输出
  `Demo application ready`，退出码 0，Agent 正确报告了观测结果。审批不是自动放行。

测试脚本：`tests/test_chat_progress_runtime.py`、`tests/chat_progress.test.cjs`，以及
`tests/test_pipeline_runtime.py` 新增的 reasoning / tool_running 测试。

## 使用

网页刷新一次；桌面窗口执行“视图 → 重新加载界面”。服务重连后请从本机的
“SSH / WSL → 打开远程项目”重新进入，以更新连接凭证。原 Session 保留，可在历史中打开。
如果命令需要批准，气泡会停在等待审批，点击卡片的“允许一次”才执行；拒绝则报告未执行。
