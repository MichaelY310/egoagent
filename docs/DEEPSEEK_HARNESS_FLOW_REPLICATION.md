# DeepSeek Harness Flow Graph 复现

## 结论

EgoAgent 现在提供可直接选择、查看和修改的 `deepseek_harness_replica`。它复现的是
DeepSeek Harness 的核心 agent runtime，而不是把 DeepSeek 的 TypeScript/Cordis 工程
复制进来：模型循环、工具审批与执行、checkpoint、可插入的新用户消息、重复调用提醒、
工具输出裁剪、被动上下文压缩、网页/能力搜索、子 Harness 和完整轨迹都由 EgoAgent 的
通用 Flow/Identity/Capability 抽象表达。

参考源码是仓库内的官方快照 `research/deepseek-harness-master`，版本
`@deepseek-ai/dsh-root 0.1.0-rc.5`，Git revision
`de738bdd9218f2f610982e679c3755be06756e2f`。重点对照了：

- `docs/architecture.md`、`docs/subsystems/core.md`
- `docs/subsystems/session.md`、`docs/subsystems/compaction.md`
- `docs/subsystems/subagent.md`、`docs/tool-execution-pipeline.md`
- `packages/guard/repeat-tool-reminder`
- `packages/compaction/compaction-tool-result-pruner`
- `packages/bundle/base/cordis.patch.yml`

## 可以直接使用的对象

| 对象 | 位置 | 用途 |
|---|---|---|
| 主 Flow | `harness/deepseek_harness_replica/config.json` | 完整的 DeepSeek 风格 turn/step loop |
| Identity | `identity/deepseek_operator` | 代码、终端、网页、能力搜索和子 Harness 能力 |
| 重复调用组件 | `harness/component_repeat_tool_guard` | 可拖入任意 Flow 的 advisory loop guard |
| 工具裁剪组件 | `harness/component_tool_result_pruner` | 可拖入任意 Flow 的无模型、可逆上下文裁剪 |
| 压缩组件 | `harness/component_context_compactor` | 已有普通 Model + Conversation I/O 被动压缩 Flow |
| 真实实验入口 | `experiments/deepseek_harness_flow/run_pilot.py` | 在隔离 fixture 上调用真实 DeepSeek API |

## 主 Flow

```text
用户输入
  -> 重置本轮重复调用链
  -> 裁剪旧的大型工具结果（只改 working surface）
  -> 80% token 压力检查 / 必要时压到 16%
  -> 模型请求前 checkpoint
  -> operator Model
       ├─ 无工具调用 -> 最终回答
       ├─ provider 截断 -> 显式输出 partial/truncated 状态
       └─ 有工具调用
            -> 权限审查
            -> 最多 8 个独立工具并发执行并按请求顺序回填
            -> 3/5/8 次完全相同调用的 advisory reminder
            -> 大工具结果 head/middle/tail 裁剪
            -> token 压力检查
            -> 接收 steering 消息
            -> 下一次模型请求前 checkpoint
            -> operator Model
```

用户在工具轮之间发送的新消息由 `steer_poll` 接收；它会重置“连续重复调用”计数，
然后进入同一个持久循环，不会另起一套隐式 agent loop。

## 与官方核心机制的映射

| DeepSeek Harness | EgoAgent 实现 | 语义 |
|---|---|---|
| turn/step core loop | `Agent -> Tool Review -> Tool -> loop` | 有工具就继续，无工具文本就结束 |
| append-only Session events/current surface | `trajectory.jsonl` + `messages/full_messages` | 精确请求、响应、工具和 surface replacement 均可回放 |
| checkpoint before request/tool dispatch | `检查点` + Tool `checkpoint` | 模型调用前和工具批次前保存恢复点 |
| tool middleware/policy | `工具审查` + runtime permission policy | allow/ask/deny 先于实际执行 |
| concurrent tool batch | `工具(parallel=true,max_workers=8)` | 并发执行，观察按原始调用顺序归并 |
| repeat-tool-reminder | `循环守卫` + `component_repeat_tool_guard` | 完全相同的规范化参数；3/5/8 提醒；永不否决调用 |
| deterministic tool-result pruner | `上下文(apply_mode=tool_prune)` | 默认 8192/4096/1024 字符和同一 marker；完整审计不丢失 |
| automatic basic compaction | `component_context_compactor` | 运行时判定 80% 水位；普通 Model 生成压缩计划；16% 目标 |
| Skills / tool catalog | `search_capabilities` + `activate_capability` | 按需检索，避免把所有能力正文塞进 prompt |
| todo | `update_plan` | 可验证的 pending/in_progress/completed 计划 |
| web | `web_search/fetch_url/fetch_urls/browser` | 搜索、抓取和交互浏览 |
| subagent spawn/fork | `create_harness(inherit_conversation=false/true)` | 独立或继承上下文的子 Flow，父上下文只接收返回结果 |
| repository instructions | Agent 的 scoped `AGENTS.md` 组装 | workspace 层级规则进入 system section |
| output limit | `output_truncated` edge | 不再把半句话伪装成完成结果 |

### 重复工具调用不是拦截器

旧的 EgoAgent `Agent` 节点默认会拒绝第二次完全相同的调用。为兼容既有 Flow，这个旧默认
仍保留；`deepseek_harness_replica` 明确设置
`reject_identical_tool_call: false`，然后在图上放置可见的 `循环守卫`。守卫：

1. 按工具名和完整规范化参数计数；
2. `exclude` 中的调用透明，不增加也不重置计数；
3. 第 3 次注入轻提醒，第 5/8 次注入包含工具名、次数和参数预览的强提醒；
4. 被拒绝或失败的调用同样可以进入计数；
5. 只注入带来源信息的 synthetic user context，不替换真实 tool result；
6. 状态只存在于当前 live Session 对象，恢复旧 session 不继承陈旧连续计数。

### 工具输出裁剪仍然是 lossless trajectory

当工具 observation 超过 8192 个 Python Unicode code point 时，模型下一轮看到：

- 前 4096 字符；
- `[... tool result middle pruned ...]` 固定标记；
- 后 1024 字符。

`full_messages` 和 `trajectory.jsonl` 仍保存原始输出；只替换模型的 working surface，并记录
`conversation.surface.replace` 和 context governance ledger。因此可恢复原文，也能用于训练
数据导出，不会把裁剪后的文本误当作真实工具返回。

## 在 IDE 中使用

1. 打开 EgoAgent IDE 的 Chat/Workbench。
2. Harness 选择 `deepseek_harness_replica`。
3. `operator` 和 `compactor` 均选择 `deepseek_operator`；默认绑定通常已自动完成。
4. 确保进程环境中存在 `DEEPSEEK_API_KEY`，不要把 key 写进 Identity JSON。
5. 发送代码或研究任务。写文件、运行命令、交互浏览器和创建子 Harness 会按正式策略询问。
6. 在“运行”页查看节点进入/退出、工具批次、checkpoint 和 Subflow；在轨迹回放页查看每次
   model request 当时真实收到的 working history。

若要把两个组件用于其他 Agent，在 Flow 编辑器中从组件库拖入
`Repeated Tool Call Guard` 或 `Tool Result Pruner`，用表单调整阈值即可，不需要编辑 JSON。

## 真实 DeepSeek 验证

命令：

```powershell
.\.venv\Scripts\python.exe .\experiments\deepseek_harness_flow\run_pilot.py off_by_one
```

2026-08-23 的隔离实测结果：

- 任务：定位并修复 sliding-window 的 off-by-one；
- 实际修改：`range(len(values) - window)` 改为
  `range(len(values) - window + 1)`；
- 独立测试：3/3 通过，exit code 0；
- 模型请求：7；工具调用：11；provider retry：0；
- 工具轨迹：`ls -> read_file -> ... -> exec_command -> apply_patch -> exec_command -> submit_result`；
- 轨迹：1434 个 append-only events，7/7 model request/response、11/11 tool
  request/result 全配对；
- 轨迹健康：`healthy`、`replayable=true`、`training_ready=true`、0 errors、0 warnings。

结果文件：
`experiments/deepseek_harness_flow/results/1787446847-off_by_one-cebfbf.json`。

第一次在受限测试沙箱内调用网络得到 WinError 10013；在获准联网后同一脚本成功。失败运行也
被保留为实验记录，不伪装成模型或 Flow 错误。

## 没有照抄的部分

以下差异是明确的工程边界，不应宣称“一模一样”：

1. **Cordis/npm 动态插件和 HMR**：没有复制。EgoAgent 用可视化 Flow、Subflow、Identity 和
   可搜索 Capability 表达可组合性；再嵌一套 Cordis 会形成第二个运行时。
2. **DeepSeek Code Mode 的受限 JavaScript workflow DSL**：没有逐 API 复制。EgoAgent 用
   Map/Join、并行 Tool、Subflow 和 Agent Bus 组合多 worker，图本身可编辑和回放。
3. **可继续的后台 subagent 细节**：`create_harness` 已支持 spawn/fork 语义、父子 lineage 和
   结果隔离，但模型侧默认是前台运行至完成；官方的后台通知/继续/中断工具接口没有一比一复制。
4. **平台 sandbox backend**：EgoAgent 使用 workspace guard、统一 permission policy 和可选
   container backend；没有复制 DeepSeek 项目各平台原生 sandbox 的内部实现。
5. **全部官方 UI 和插件生态**：本次目标是核心 harness 行为在 EgoAgent Flow 中可表达、可
   测试、可编辑，不是复刻 DeepSeek Web 产品。

这些差异不靠 prompt 隐藏。Flow 描述中只声明已经连接到真实组件的能力。

## 验证命令

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_deepseek_harness_replica -v
.\.venv\Scripts\python.exe -m unittest tests.test_context_policy tests.test_codex_runtime_capabilities tests.test_identity_composition tests.test_dag_contracts tests.test_agent_workspace_boundary tests.test_provider_conformance tests.test_permissions tests.test_checkpoint_recovery -v
```

第一组包含：配置/组件契约、Identity 能力暴露、重复调用边界、lossless 裁剪和正式 Flow 的
完整工具轮。第二组覆盖已有上下文策略、Codex Flow、provider 工具协议、权限、安全边界和
checkpoint 回归。

最终全仓回归在允许启动本地测试浏览器的环境中为：`Ran 525 tests ... OK
(skipped=3)`。三个 skip 是平台能力条件，不是失败；受限命令沙箱内唯一出现过的 CDP 启动
失败，在相同代码、允许本地浏览器进程后通过，随后完整套件也以 exit code 0 结束。
