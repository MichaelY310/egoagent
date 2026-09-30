# 原生代码补全与 Tab

2026-09-29。适用于 EgoAgent 当前 Void 网页运行时及复用该运行时的桌面壳。

## 怎么用

1. 更新后在 IDE 按 `Ctrl+Shift+P`，执行 `Developer: Reload Window`（网页版也可刷新）。
2. 打开代码文件，在函数或表达式后输入代码，然后停一下。右下角 `EgoAgent 补全中` 表示正在请求；建议以灰色文字显示，文件尚未改变。
3. 按 `Tab` 接受整段；按 `Esc` 隐藏；`Ctrl+Right` 只接受下一词；`Ctrl+Alt+Right` 接受下一行。`Ctrl+Z` 使用编辑器正常撤销，不是 Agent 的 hunk 审阅。
4. 没自动出现时按 `Alt+\`，或从命令面板执行 `EgoAgent: Trigger AI Tab Completion`。
5. 点击右下角 `EgoAgent Tab` 暂停/恢复补全。没有建议时 Tab 保持原本的缩进功能；语言服务候选框、snippet 跳转与 Tab 移动焦点优先，不抢按键。

例子：在一个临时 Python 文件输入以下两行，把光标放到 `return ` 后（保留末尾空格）：

```python
def add(a, b):
    return
```

触发补全后，模型通常会建议 `a + b`。这是实际模型输出，不是针对例子的硬编码；其他上下文下建议可能不同，也可能不提供建议。

## 设置

`Ctrl+,` 打开编辑器设置，搜索 `egoagent completion`。若当前 Void 的设置页面出现自身服务错误，可用命令面板 `Preferences: Open Workspace Settings (JSON)` 配置相同选项。

| 设置 | 默认 | 用途 |
|---|---|---|
| `egoagent.localCompletion.enabled` | true | 启用灰色补全 |
| `egoagent.ai.enabled` | true | 使用后端配置的模型（关闭也会影响其他 IDE AI 操作） |
| `egoagent.ai.completionDelayMs` | 280 | 停止输入多久后发请求 |
| `egoagent.ai.completionTimeoutMs` | 8000 | 客户端总等待上限，含模型状态检查 |
| `egoagent.localCompletion.localWordFallback` | true | 无模型时仅复用当前文件已有标识符 |
| `egoagent.localCompletion.includeOpenFiles` | false | 是否附带同工作区最多两个可见文件节选 |
| `egoagent.localCompletion.exclude` | [] | 额外排除 glob，例如 `["**/private/**"]` |
| `editor.inlineSuggest.enabled` | true | 编辑器原生 inline 建议开关 |

模型使用后端已有的 `autocomplete` 角色，未单独指定时沿用模型路由的 edit/chat 回退。无需在扩展或文档里填写 API Key。补全与 Chat 使用不同请求：不会启动整个 Flow，也不会传入聊天历史。

## 请求、可靠性与隐私边界

- 防抖在网络请求之前；继续输入、移动光标、换文件、暂停时取消等待，丢弃旧文档版本的结果。
- 60 秒、最多 64 项的内存缓存；撤销/退格回到相同内容不因文档版本号变化而失效，手动输入建议的开头可复用余下部分。
- 当前文件最大 500,000 字符；发送光标前最多 6,000、后最多 2,000 字符，以及有限 import 信息。其他打开文件默认不发送；开启后只取同工作区、非敏感文件的有限节选。
- 排除 `.env*`、私钥、凭据/secret 路径、依赖/构建目录等，并启发式检测内容中的私钥和常见凭据。这不是完美的 DLP；敏感项目应关闭云补全或添加排除规则。排除和信任检查也适用于本地词补全。
- 超时/不可用在状态栏提示，不阻塞键盘，不弹出连续错误对话框。不再插入 TODO 的伪实现、`NotImplementedError` 或“status: ok”占位代码。
- 模型返回空字符串表示不建议补全，不会强行替换成模板。
- 客户端取消不保证云端停止计费/生成。服务端最多容纳两个补全调用；专用客户端禁用推理和重试、使用 12 秒网络超时，避免继承长任务的数分钟重试预算。网络超时不是整个远端服务的绝对墙钟截止时间。
- 灰色预览、接受、部分接受和撤销复用 VS Code 原生 inline completion，不创建另一套浮层或文件写入协议。

## 与其他编辑能力的区别

- Tab：光标位置插入代码，不改其他文件。
- `Ctrl+I` / `EgoAgent: Inline Edit`：按指令编辑选区或文件，走现有可审阅改动流程。
- `EgoAgent: Predict Next Edit`：预测下一处相关编辑，仍需预览并确认；不是 Tab 自动应用全项目修改。
- 语言服务 IntelliSense（通常 `Ctrl+Space`）：类型、成员和符号候选，与 AI 灰色建议共存。

## 验证与参考

自动测试：`node --test tests/autocomplete.test.cjs tests/chat_*.test.cjs tests/workspace_window.test.cjs`；后端集成：`python -m pytest tests/test_ai_service.py tests/test_model_router.py tests/test_void_workbench_integration.py`。

2026-09-29 实测：前端/交互 71 项通过，后端集成 47 项通过；前端生产构建通过。真实 DeepSeek 补全调用返回 `value * value`（一次约 2.3 秒，不代表速度承诺）。浏览器中验证了灰色预览、自动/手动触发、Tab 接受、Ctrl+Z 撤销、Ctrl+Right 部分接受、Ctrl+Alt+Right 逐行接受和 Esc 取消。实测发现并修复首行重复缩进；修复后接受并保存了模型生成的 `partition_numbers` 函数，空列表、正数、负数含零的 3 个行为用例均通过。测试只使用合成示例，没有修改正在使用的演示项目。未把单元测试等同于所有系统/语言/远程模式的实机覆盖。

设计参考 [Continue 的防抖、缓存与结果过滤](https://docs.continue.dev/ide-extensions/autocomplete/how-it-works)，交互沿用 [VS Code 原生 inline suggestions](https://code.visualstudio.com/docs/editing/ai-powered-suggestions)。本次为独立实现，没有复制第三方源码。

## 移除的教程

已移除录制教程目录组件、Chat 教程按钮、遮罩/高亮、强制步骤事件拦截、预设输入、教程桥接和构建校验脚本。保留手动视频文档、正在使用的 `tutorial_assets/video_demo_repo`、可运行示例 Flow/Task 与历史记录；这些不是交互教程运行代码。旧教程专用文件此前没有加入 Git，本次删除不自带 Git 恢复点；其他文件原有修改未回退。
