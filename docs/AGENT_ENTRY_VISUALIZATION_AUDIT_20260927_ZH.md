# 两个 Agent 入口与运行可视化核验（2026-09-27）

> 这是修复前的历史审计，保留失败事实。2026-09-28 的修复、统一观察/录制实现和最新验收见 [统一 Flow 观测与运行相簿](UNIFIED_FLOW_OBSERVATION_ZH.md)。下文“当前”指审计当天，不代表最新安装状态。

## 结论

功能骨架已存在，但当前安装不能认定为端到端可用。Chat 与 Task Bench 都调用 PipelineRunner，能生成节点事件；运行管理、事件投影和展示入口仍然分开。复用了执行引擎，不等于所有入口自动接入同一个可视化看板。

本次以代码检查、隔离自动化测试、真实浏览器操作和离线 DummyLLM 做验证。未调用 DeepSeek/OpenAI，未修改业务代码、教学项目源码或权限策略。

## 两个入口现在是什么

| 入口 | 输入及环境 | 可视化入口 | 核验结果 |
| --- | --- | --- | --- |
| IDE Chat | 用户消息；扩展提供当前 workspace 路径；按所选 Flow、版本、Identity、模式运行 | Session 旁的“观察” → Build；底部“运行观测” | 当前项目路径正确，模型/工具时间线有真实事件；观察画布空白，尚未通过图形验收 |
| Workbench → Evaluate → Task Bench | 选择题目；运行器新建 `.egoagent/task_runs/<run_id>/workspace`，写入题目 fixtures | Evaluate 中的 DAG 运行面板；“过程/评分/产物/进化”；“在 Build 回放” | 后端离线做题成功；当前前端被历史列表加载拖住，显示题库 0，最后 Failed to fetch；未通过前端启动/回放验收 |

注意：Chat 模式下拉框的 `Evaluate · 隔离评测` 不是 Task Bench。该选项改变权限策略，仍把当前 workspace 传给交互执行接口；不会自动选题、生成新工作区或启动 Docker。要自动准备题目环境，必须使用 Workbench 顶部的 Evaluate 看板。

## 题目及环境协议

- 原生格式：`ego.task.v1`，schema 在 `task_bench/schema.json`。
- 已有 Harbor 1.4 / 旧 Terminal-Bench 导入路径。
- 可把 JSON、JSONL、CSV 映射为题目、期望答案、工作区文件等字段。
- `environment.backend: local`：创建独立目录并写入 fixtures。并不自动提供独立 Python 环境或安装任意依赖，也不是 OS 级沙箱。
- `environment.backend: container`：按题目 Dockerfile/build context 构建镜像，初始化容器工作目录，绑定题目 workspace，命令工具在容器中执行；模型调用仍在宿主后端。容器文件修改通过挂载同步到独立题目 workspace。
- Environment 勾选项是额外工具/知识包，不等于 Docker/Python 运行环境选择。执行后端由题目定义决定。
- 本机检测到 Docker CLI，但 Docker Desktop Linux engine 管道不存在；本次未启动引擎、拉镜像、构建或实跑容器，不能声称 Docker 链路通过验收。

任务 prompt 会被写入 Session 的 user 消息，也提供给 runner 的 task 数据。交互 Flow 的输入节点可以消费这条消息；没有输入节点的自动 Flow 也可读取任务数据。Chat 则把手动 prompt 预置进 Session 和初始数据。两者不需要两套模型循环。

## 实际测试记录

### 离线 Task

- Task：`offline_trace_smoke`
- Flow：`aider_review_worker`
- 精确版本：`v000001-20260830-070738-54c39506`
- Identity：`test_bot`（scripted DummyLLM，不是真实模型）
- Run：`run_20260927_110618_fe0c668b`
- 首节点暂停在 `input`；单步后暂停在 `review`；恢复自动执行后结束。
- 7 次节点调用；3 次离线模型步骤；实际调用 `glob_search`、`read_file`。
- 4/4 确定性评分通过，score=1.0。
- 自动建立了独立 workspace；准备阶段约 101.84 秒，启动 HTTP 请求因此超过 30 秒等待。未重复提交启动请求。
- 当前 UI 无法正常加载题库，因此这次通过的是后端执行/控制/评分链路，不是前端“开始做题”按钮全链路。

记录：`.egoagent/task_runs/run_20260927_110618_fe0c668b/run.json`。

### Chat 与观察

- 在教学项目 `tutorial_assets/video_demo_repo` 中建立 `react_single + test_bot`，只读 Chat 模式。
- 因配置选择重置，建立初始离线 Session 使用了同一后端接口；之后在真实 Chat 中选中该 Session、发送消息、点击“观察”，均使用前端操作。
- Run：`interactive_993c35cac66141a8898f00d9e1823995`
- Session：`react_single_20260927_110929_e1823995`
- 显示了 LINKED TO SESSION，时间线记录输入 → 模型 → glob_search → 模型 → read_file → 模型 → 等待输入，共 7 次节点调用。
- glob_search 的实际路径位于当前教学项目，没有切回 EgoAgent 仓库根。
- test_bot 的固定脚本尝试读取 `agent.py`；教学项目没有此文件，轨迹正确保留 File not found。这仅验证工具/事件传输，脚本随后“完成”的固定文本不是正确解题能力的证据。
- Build 底部显示 3 节点、4 连线，但实际画布没有节点元素。适应视图、隐藏浮层后仍空白；时间线可见。图形布局/渲染原因还需要进一步定位。
- 测试结束后已停止这条 Chat 运行，保留历史；没有让离线脚本持续运行。

### 自动化测试

运行以下九个测试文件：

```text
tests/test_task_bench.py
tests/test_harbor_adapter.py
tests/test_task_datasets.py
tests/test_interactive_execution_service.py
tests/test_interactive_runtime_startup.py
tests/test_void_workbench_integration.py
tests/test_interactive_output_projection.py
tests/test_pipeline_runtime.py
tests/test_task_bench_executable_fixture.py
```

结果：194 passed，1 skipped，2 subtests passed。跳过的是 Windows 无法创建 symlink 的测试。此结果不包含真实 Docker 或真实外部模型的验收，也不能替代浏览器验收。

## 确认的问题及修复优先级

1. **题库加载被历史记录绑住。** TaskBench.tsx 初始化把 tasks/options/runs/compatibility/datasets 放进一个 Promise.all。tasks 接口约 0.55 秒返回 45 道题，但 runs 请求超过 20 秒，浏览器最终 Failed to fetch，导致题库一直显示 0。历史实现读取所有 run.json、检查各自 checkpoint 后才截取最近列表；当时 206 个 run.json 合计约 1.02 GB。应独立加载题库与历史，为历史使用摘要索引/分页，局部错误不要清空整个入口。
2. **题目启动准备过慢。** TaskRun.prepare 同步计算所有 Harness/Identity 文件 manifest，即使该题禁止进化。当前库规模下离线任务准备阶段也超过 100 秒。需要异步准备状态及有边界的快照策略，不能让用户把它误判为模型不回答。
3. **Chat 配置选择被重绘覆盖。** change handler 先调用 markConfigurationChange（内部 renderSelectors），之后才读取 event.target.value。浏览器实测 Harness/Identity 回到了旧值。应先捕获选择值，再更新状态与重绘，并加真实 DOM 交互回归。
4. **观察画布空白。** 有真实轨迹但没有图中节点，是本次明确未通过的验收项，不能用“时间线有数据”代替“运行图可见”。
5. **入口没有统一观测地址。** Chat/Build、Task Bench、直接 Harness.run()/CLI、OpenAI-compatible SSE、durable run 分别使用不同管理器/回调；terminal adapter 主要打印终端，SSE adapter 主要投影文本。并不是所有入口天然拥有可在 Build 直接订阅的 run handle。
6. **Task 可视化仍有功能边界。** TaskBench.graphFor 用规则网格生成主图，没有复用 Build 保存的节点位置/端口/边路由；主图通常加载所选不可变 Flow 版本，进化事件列表不等于当前主图已跟随结构变更。Build Task replay 是载入轨迹快照，不是与 Task live run 相同的持续订阅。
7. **容易混淆的文案。** Chat Evaluate 与 Task Bench 的区别不明显；观察面板仍声称“Chat 改配置会创建新的 Session”，与同 Session 重配置实现不一致。

## 建议的最终产品契约

保留用户提出的两个业务入口：当前项目消息、标准化 Task。Build 的独立试跑是调试工具，不作为第三套业务语义。

两个入口均创建统一 Run 记录：entry_type、workspace/environment、Flow/version、Identity/slot bindings、parent_run_id、status。运行准备（含 Docker build）也作为可观察阶段；模型节点前后、工具、审批、子 Flow、结构进化都携带该 Run 标识。统一“观察”面板按 Run 订阅，并从相同事件记录回放。

验收必须包括：前端直接启动两种任务；当前项目无串目录；标准 Task 自动准备本地/容器环境；首次观察就能看到全部节点；暂停/单步/停止可用；多 Agent 与进化可见；历史增长后题库仍迅速可用；刷新后能重新关联同一 Run。当前尚未满足这些完整验收条件。
