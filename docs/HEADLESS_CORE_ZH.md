# EgoAgent 纯核心使用与代码边界

EgoAgent 可以不安装前端、不启动 HTTP 服务而运行。纯核心保留 Flow 执行、
Identity / Ego / Superego、工具与能力库、子 Agent、上下文处理、进化、Task、
Session、版本和轨迹；可视化界面只是这些功能的一个客户端。

## 三层结构

| 层 | 代码 | 职责 |
| --- | --- | --- |
| Agent 核心 | `egoagent_core/`、根目录运行时 Python 模块、`llm/`、`self_evolution/`、`task_bench/`、`tabletop/` | 执行与领域服务；不导入前端或服务器 |
| 可选 API | `egoagent_server/` | HTTP / WebSocket、请求与运行控制适配；可无前端独立启动 |
| 可选界面 | `harness_editor/`、`void_extension/`、`desktop/`、外部运行时 `void-web/` | React 工作台、IDE 集成、桌面窗口 |

依赖方向：**界面 → API → 核心**。Python 脚本 / 实验直接调用核心，无需经过 API。
`egoagent_core` 提供 SDK 入口和可复用服务；历史根目录模块仍是核心实现的一部分，
不是复制品。**不要只拷贝 `egoagent_core/` 一个目录**；目前交付的是源码发行目录，
不是已经验证的独立 wheel。

以下资源也是核心，不能当成前端删除：

- `harness/`：Flow 定义、内部子 Flow、提示词和脚本。
- `identity/`：身份与行为配置、继承能力。
- `.environment/`、`environment/`、`capability_packs/`：工具、知识、Skill。
- `config.yaml`、根目录 Python 模块和 `requirements-core.txt`。
- 你要保留的私人状态：`sessions/`、`.egoagent/`、`.egoagent_checkpoints/`、
  Flow `.versions/`、模型配置及 `.env.local`。这些不是 UI，也不应随 UI 删除。

原 `harness_editor/*.py` 后端实现已迁走，现在只提供旧导入路径 / 启动命令的兼容转发。
改动事务、检查点、规则和记忆、模型路由、代码上下文、Agent 创建等在核心层；
API 路由在服务器层。**整个 `harness_editor/` 都可以移除**，而不丢失这些后端能力。
`heart_flow/` 是可选实验；`start-all.py` 是完整产品启动器，不是纯核心入口。

## 推荐：导出独立目录，不动现有 UI

在完整 Git 仓库根目录执行（目标必须尚不存在）：

```powershell
python scripts/export_core.py --output ../egoagent-core --with-tests
```

导出使用源文件允许列表：包含 Git 跟踪的核心代码和能力资源，不包含前端、API、
Node 依赖、Void、实验记录、Session、`.env.local`、运行数据库或未跟踪的私人能力。
`core-manifest.json` 记录每个源文件的 SHA-256。它不是备份命令；你自建且未跟踪的
Identity / Flow、模型密钥和历史需要按需**单独**迁移，不会被静默打包。
目标已存在时命令拒绝覆盖，也不会删除任何原目录。

要保留 API 但不要 UI：额外加 `--with-server`。本命令从 Git 源码 checkout 导出，
不支持在没有 Git 元数据的导出目录中再次运行；导出目录本身可以直接使用。

## 安装与运行

在纯核心目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-core.txt
.\.venv\Scripts\python.exe -m egoagent_core --harness-dir examples/headless/hello_flow --no-capability-index
```

这个 Flow 不调用模型，只执行输出节点并保存 Session。没有 Node.js、浏览器或 API
Key 也能运行。Linux/macOS 将 Python 路径替换为 `.venv/bin/python`。

实际 Code Agent（需要配置自己的模型和一个可信工作区）：

```powershell
.\.venv\Scripts\python.exe -m egoagent_core --harness-dir harness/code_agent_fast --workspace C:\path\to\project --agents agent:identity/adaptive_deepseek_coder governor:identity/adaptive_deepseek_coder
```

终端中出现 `>>>` 后输入任务；所选 Flow 负责何时读取输入、何时结束。
`Ctrl+C` 中止。`run_harness.py` 的旧启动方式仍兼容。
只运行无 Agent 插槽的 Flow 时不用传 `--agents`；必填插槽缺失仍会报错，
不会为了无界面运行而跳过 Identity 校验。

模型通过环境变量或本地 `.env.local` 配置，参见随源码提供的 `.env.example`。
**无 UI 不等于取消审批或隔离**：终端仍使用工作区安全策略；无人值守任务应显式配置
允许的权限和执行环境，未提供审批响应不能自动当作同意。容器仍需 Docker。

`requirements-core.txt` 不含本地 embedding 大依赖；要启用 FastEmbed 语义搜索可装
`requirements.txt`。浏览器自动化、ARC 环境、训练框架等仍需要各自的可选依赖。
本次拆分不改变这些功能的模型能力或运行条件。

## Python SDK：自己接入程序，而不是接前端

```python
from pathlib import Path
from egoagent_core import AgentFactory, Harness

workspace = Path("/path/to/project").resolve()
factory = AgentFactory()
agents = {
    slot: factory.create("adaptive_deepseek_coder", name=slot, workspace=workspace)
    for slot in ("agent", "governor")
}
flow = Harness("harness/code_agent_fast", agents=agents, workspace=workspace)
result = flow.run()  # 交互式终端入口；保存 Session 和轨迹
```

调用 `AgentFactory` 前应在进程环境中配置模型密钥；仅 CLI / API 启动器自动读取本地
环境文件。自行嵌入的程序可显式调用 `llm.env_config.load_local_env`。

自建客户端 / 非交互任务可用 `PipelineRunner` 的 `get_input`、`get_approval`、
`on_output`、`is_running`、`before_node` 等接口接入。调用方必须明确传入
`RuntimePolicy`，不要把缺省构造误认为已经配置好部署安全策略。
它是 CLI 和 API 共用的执行器，不是另一套 Agent Loop。

其他无 UI 能力入口：

| 能力 | Python 接口 |
| --- | --- |
| Task 创建环境、执行、评分 | `task_bench.TaskBenchManager` |
| 能力搜索、激活和使用统计 | `capability_registry.CapabilityRegistry`、能力节点 |
| Flow 创建 / 结构补丁 / 版本 | `harness_blueprint.HarnessBlueprintService`、`harness_versions` |
| Skill / Knowledge 进化 | `self_evolution.capability_evolution.CapabilityEvolutionService` |
| Session 分叉与合并 | `session_branching.SessionBranchService` |
| 文件改动接受、拒绝、撤销 | `egoagent_core.change_tracker`（UI 按钮只是调用方） |
| 规则、记忆、检查点、模型路由 | `egoagent_core.project_rules`、`checkpoint_manager`、`model_router` |
| 节点事件录制与回放数据 | `flow_observation.FlowObservationStore` |
| 精确模型输入输出、训练导出 | `trajectory.TrajectoryReader` / `export_training_data`、`training_data` |

记录与回放的数据能力不依赖 UI；删 UI 后当然不再显示画布、聊天气泡或编辑器红绿块，
但对应的事件、轨迹和改动事务仍在。SDK 测试样例在导出的 `tests/` 中。

## 可选 HTTP 服务

从带 `--with-server` 的导出目录运行：

```powershell
python -m egoagent_server
```

默认 HTTP `127.0.0.1:8765`，WebSocket `127.0.0.1:8766`。
无 UI 时 `/` 返回 `frontend: not_installed` 的服务状态；`/api/harnesses` 等 API
仍正常工作。完整 checkout 中会默认服务 `harness_editor/dist/`；也可通过
`EGOAGENT_UI_DIST` 显式指定另行部署的静态目录。不要在缺少认证部署设计时暴露公网。

## 独立验证（不用真实 API）

在**不含前端和服务器**、带 `--with-tests` 的导出目录运行：

```powershell
python -m pip install -r requirements-dev.txt
python -I scripts/verify_headless.py --tests
```

验证器确认 UI / API 目录不存在，并安装 import guard：核心一旦尝试加载 UI / API
就失败。随后执行离线 Flow 和核心回归，覆盖文件事务、检查点、模型路由、Identity、
能力检索与进化、上下文压缩 / 精简、子 Flow、Task 执行评分、Session 分叉合并、
节点录制、精确轨迹和训练导出。模型响应使用 fixture，不发送源码或消耗 API 额度；
这验证工程功能，不声称重新验证了所有真实模型的输出质量。
