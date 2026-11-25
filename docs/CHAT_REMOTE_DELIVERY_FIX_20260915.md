# Chat 消息与 WSL 网页打开修复（2026-09-15）

## 原因与修复

1. **模型有回复，Chat 丢弃了事件。** Chat 用 Flow 版本号识别当前会话，但服务端 `notify_output` 的 scope 漏了 `harness_version`。现在流式事件、HTTP 输出和配置归属使用相同字段，保留不同 Session/Workspace/Builder 的隔离。旧远程服务缺字段时只允许精确匹配当前 run，显式版本冲突仍拒绝。
2. **正常 WebSocket 没有漏消息的恢复路径。** 原实现 socket 一连接就完全禁止 HTTP 补收。现在连接恢复、回到页面及每 15 秒低频补收当前 run。轮询有 10 秒超时，不会永远占住恢复锁；旧 Session 的迟到 404 不影响刚切换的新 Session。Chat 投影在深拷贝前排除 node traces，Build 默认仍能获取完整轨迹。
3. **守护进程可能误杀存活服务。** 原实现一次 TCP 探测超时就停止已拥有的后台，日志出现多次 recovery。现在以子进程是否退出为重启依据，不将短暂繁忙当成退出；已退出进程仍自动恢复。
4. **连接成功不等于页面已打开。** 原 SSH/WSL 扩展等待异步连接后调用 `openExternal`，不检查结果就提示成功。网页改用顶层 renderer 的显式打开对话框，让点击保有浏览器用户激活；支持新页面、当前页面、取消、可复制地址。新页面被拦截时保留对话框。桌面保留 WebView2 原生新窗口处理；旧版运行时有明确回退提示，不再声称已打开。

## 实测证据

| 项目 | 实际结果 |
| --- | --- |
| 本机网页版 Chat | 在 `video_demo_repo` 发送最小测试；模型回答“网页版回复正常”，在聊天正文中可见；使用 `adaptive_code_agent`，Session `adaptive_code_agent_20260915_112454_9eee075c` |
| 网页 WSL 新页面 | 从 SSH / WSL → 已连接项目 → 打开远程项目 → 在新页面打开，出现 WSL IDE 标签页、FastVideo 文件树和 WSL 状态栏 |
| 网页 WSL 当前页面 | 同一路径选择在当前页面打开，当前地址切换至端口 19140 的 Linux 项目，未更改项目文件 |
| WSL Chat | 在新建空目录 `/tmp/egoagent-chat-delivery-skWgvQ` 使用 `code_agent_auto`，实际看到“WSL回复正常”，后续 governor 输出及最终完成状态；run `interactive_539dcf708af94cecbeffbce678085107`。未修改或上传 FastVideo 文件，未放宽工作区信任 |
| 部署后连接 | 原有两个 WSL 连接均恢复 connected；本机 12 次 API 请求全部 200；本机及两个 WSL 实例的 Chat 轻量投影均不含 node traces |
| 自动回归 | 90 项 Python 测试、3 个子测试、10 项 Node 测试通过；覆盖桌面生命周期、运行状态隔离、版本事件、消息补收、404 竞态、弹窗拦截、URL 限制、后台守护和远程连接 |

桌面与网页共享修复后的 Chat 代码，桌面原生打开分支有单元测试。本次桌面自动点击被前台窗口/自动化工具阻挡，未把它记为“完成了桌面端逐按钮实测”。网页和 WSL 的模型回复、导航则为实际 UI 操作观察，不是 Mock 结果。

最终已部署本机和两个已连接 WSL 实例。保留原 Session、连接配置、API 配置和项目内容。临时空测试目录与测试 Session 保留，测试标签页已关闭。

## 用户操作

- 本机桌面窗口：**视图 → 重新加载界面**；网页：刷新一次，再发送消息。
- WSL：从本机 **SSH / WSL → 已连接项目 → 打开远程项目** 重新进入。网页在新对话框选择打开位置。
- 服务重连后旧远程窗口可能持有过期连接凭证。通过上面的本机入口重新打开即可，不要直接重复刷新一个 401 页面。
- 被旧后台重启打断且未完成的那一轮需要重新发送；不会伪装成模型已经完成。

## 重跑回归

```powershell
.venv\Scripts\python.exe -m pytest tests/test_desktop_launcher.py tests/test_interactive_runs.py tests/test_interactive_execution_service.py tests/test_interactive_output_projection.py tests/test_interactive_runtime_startup.py tests/test_backend_supervisor.py tests/test_remote_workspaces.py tests/test_void_workbench_integration.py -q -p no:cacheprovider
node --test tests/chat_delivery.test.cjs tests/workspace_window.test.cjs
```

若本机旧 pytest 临时目录不可写，给 `--basetemp` 指定 `.runtime/` 下一个新的专用目录；不需修改系统目录权限。
