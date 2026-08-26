# Codex Harness → EgoAgent Flow Graph 实现报告

更新时间：2026-08-22

## 结论

EgoAgent 现在可以用 Flow Graph 组装一个**功能上接近 Codex 核心 turn loop** 的代码 Agent：它能读取分层项目规则、在同一轮中多次调用工具、并行执行独立工具、执行持久命令、应用原子 patch、请求高风险操作授权、创建检查点、在上下文压力下被动压缩、接收轮中 steering，并留下完整轨迹。

它不是、也不应被描述成 Codex 二进制或源码的“一模一样复刻”。无法完全相同的部分主要来自模型 API、终端/操作系统沙箱、MCP/插件生态和异步运行时不同。强行照搬这些部分会绕过 EgoAgent 的 Flow/Identity/Capability 抽象，并引入一套平行执行引擎。

## 阅读的上游版本

- 官方仓库：[openai/codex](https://github.com/openai/codex)
- 本地只读快照：`research/upstream/codex`
- 下载时解析到的 commit：`343074d4207d572809bd8cea15f4be1d09d98e0b`
- 重点阅读：
  - `codex-rs/core/src/session/turn.rs`
  - `codex-rs/core/src/tools/router.rs`
  - `codex-rs/core/src/tools/handlers/`
  - `codex-rs/core/src/context_manager/`
  - `codex-rs/core/src/project_doc.rs`
  - `codex-rs/protocol/src/protocol.rs`

上游快照只用于研究，没有被混入 EgoAgent 产品包；`.gitignore` 继续忽略 `research/`。

## Codex 的核心运行方式

从 `run_turn` 和 tool router 可以抽象出以下循环：

1. 组装开发者指令、项目规则、技能和当前对话。
2. 在请求模型前检查 token 压力，必要时压缩。
3. 流式请求模型并记录 reasoning、文本、tool call 与 usage。
4. 路由工具；独立工具可并发，有状态工具串行。
5. 工具完成后更新上下文、world state、turn diff 和事件。
6. 在下一次采样前吸收 pending user input。
7. 若模型继续调用工具，则保持在同一 turn；否则输出最终答复。
8. 危险命令、写入和越界访问受 approval/sandbox policy 约束。

这不是一个单纯的 ReAct prompt。关键能力位于模型外部的运行时。

## EgoAgent 中的映射

| Codex 能力 | EgoAgent 实现 | 复用方式 |
|---|---|---|
| turn loop | `Agent → 工具审查 → 工具 → compactor → steering poll → Agent` | 任意 Flow 可使用这些节点 |
| hierarchical `AGENTS.md` | `harness_editor/project_rules.py` + `Agent._refresh_scoped_workspace_instructions` | 所有文件型 Agent 自动获得路径作用域规则 |
| apply patch | `capability_packs/codex_runtime/skills/apply_patch` | 可激活 Capability，不依赖 Codex Flow |
| persistent command | `exec_command` + `write_stdin` + `process_sessions.py` | 任意 Identity/Flow 可挂载 |
| plan state | `update_plan` | 通用工具，强制最多一个 `in_progress` |
| approval | `工具审查` 节点 + `RuntimePolicy` | Flow 中显式配置，不写死在 Identity |
| parallel tool batch | `工具` 节点的 `parallel/max_workers` | Flow 参数 |
| checkpoints/diff | 工具节点 `checkpoint: true` + change tracker | IDE 可 Accept/Reject |
| passive compaction | `component_context_compactor` 子流程 | 压力触发，不依赖 Agent 主动想起 |
| mid-turn steering | `输入(mode=poll)` | 在工具批次间非阻塞吸收用户输入 |
| durable events | Session/trajectory event protocol | Studio/IDE 回放与训练导出共用 |

## 新增的通用组件

### `apply_patch`

支持 Codex 风格的 `*** Begin Patch` / `*** End Patch`：新增、修改、删除和移动文件；写入前整体校验，任一步失败则不留下半个 patch；路径受 workspace guard 约束；成功修改进入 change tracker，因此 IDE 可以逐块 Accept/Reject。

### `exec_command` 与 `write_stdin`

`exec_command` 可以启动短命令，也可以返回持久 session id。`write_stdin` 对该 session 继续写入、轮询或终止。它解决了“每个工具调用都是新 shell，无法继续交互进程”的缺口。

### `update_plan`

保存结构化步骤和 `pending / in_progress / completed` 状态，拒绝同时存在两个 `in_progress` 的不一致计划。

### 路径作用域规则

读取或编辑子目录文件后，下一次模型调用会附加从 workspace 根到目标路径之间最近的 `AGENTS.md` 规则。规则不会泄漏到另一个 workspace 或另一个 Agent。

### 轮中 steering

`输入` 节点新增 `mode: "poll"`。没有新消息时立刻走 `no_input`；有消息时把它标记为 steering 并送入下一次模型采样，不阻塞运行线程。

## `codex_flow` 图结构

入口文件：`harness/codex_flow/config.json`

```text
Input
  → passive pre-turn compaction
  → Agent(coder)
      ├─ final text → Output
      └─ tool calls
           → policy review
           → parallel tool batch + checkpoint
           → passive post-tool compaction
           → non-blocking steering poll
           → Agent(coder)
```

默认 Identity 是 `identity/codex_operator`。普通读取自动允许；patch、写文件和执行进程默认询问用户。测试 runner 只对受控临时 fixture 自动批准写入，产品设置没有因此被放宽。

## DeepSeek V4 Flash 实测

运行器：`experiments/codex_flow/run_deepseek_tasks.py`

| 任务 | 实际行为 | 独立验证 | 时间 | 模型/工具调用 |
|---|---|---:|---:|---:|
| `off_by_one` | 读取代码与测试，复现失败，patch 滑窗边界，再跑测试 | 3/3 通过 | 17.04s | 6 / 9 |
| `duration_parser` | 定位解析缺陷，使用 `apply_patch`，运行完整 unittest | 3/3 通过 | 17.58s | 6 / 7 |

证据：

- `experiments/codex_flow/results/1787399268-off_by_one-59663a.json`
- `experiments/codex_flow/results/1787399360-duration_parser-e49208.json`

这里的“通过”来自 runner 在 Agent 退出后重新运行测试，不是相信模型自述。

## 复现命令

先在 `.env.local` 配置 provider。密钥不得写入 Flow、Identity 或文档。

```powershell
.\.venv\Scripts\python.exe .\experiments\codex_flow\run_deepseek_tasks.py --task off_by_one
.\.venv\Scripts\python.exe .\experiments\codex_flow\run_deepseek_tasks.py --task duration_parser
```

产品中选择：

- Harness：`codex_flow`
- Identity：`codex_operator`
- Workspace：要修改的真实项目目录

第一次写入或运行命令时会显示授权请求。修改完成后在“改动”面板打开文件，可以逐块 Accept/Reject。

## 与 Codex 仍不相同的地方

1. **模型协议**：当前 DeepSeek 路径使用 OpenAI-compatible Chat Completions。Codex 的 Responses API reasoning items、服务端 compaction 和模型专用 item 语义无法逐项等同。
2. **终端**：EgoAgent 持久进程是 pipe-backed session，不是 Codex 的完整 PTY/Windows ConPTY；依赖真实 TTY 控制序列的程序可能表现不同。
3. **沙箱**：EgoAgent 提供 workspace guard、命令策略和可选 container backend，但没有逐平台复刻 Codex 的 Seatbelt/Landlock/Windows restricted-token 实现。
4. **扩展生态**：MCP、插件安装、远程 skill dependency 与 Codex 原生工具注册没有一比一复刻。EgoAgent 用 Capability Pack 和可搜索能力库表达相同的产品目标。
5. **并发与取消**：EgoAgent 能并行工具与运行子流程，但 subagent 生命周期、取消传播和 Codex Rust async task 的时序不是二进制级一致。
6. **提示词与模型**：`codex_operator` 是根据公开行为重写的 Identity，不复制私有模型提示或权重。

这些差异若强行抹平，需要引入第二套协议、终端和 sandbox runtime，破坏“所有行为由 Flow + Identity + Capability 组合”的设计。更合理的方向是继续提升对应组件，而不是在 Flow 外硬编码 Codex 特例。

## 回归测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

仓库新增 `pytest.ini`，只收集 EgoAgent 自己的 `tests/`，不会把 `research/upstream`、历史实验快照和生成任务误当作产品测试。

最终结果：`523 passed, 3 skipped, 132 subtests passed`。3 个 skip 是环境/可选依赖条件，不是失败。真实无头浏览器测试在允许启动 GUI 子进程的环境中通过。
