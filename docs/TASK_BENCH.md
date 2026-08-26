# EgoAgent Task Bench

Task Bench 是 Studio 内置的、可复现的 Agent 做题实验台。它把题目、工作区、Harness、Identity、Environment、运行预算、DAG trace、自进化证据和评分放进同一个版本化协议中。

## 在 Studio 中使用

1. 启动 `python start-all.py`，打开 `http://127.0.0.1:8765/` 或统一入口中的 Studio。
2. 点击顶部 **Task Bench**。
3. 从左侧选择题目，再选择 Harness、Identity 和可选 Environment pack。多 Agent Harness 会出现逐 slot 绑定。
4. 可勾选“首节点前暂停”，然后点击“开始做题”。
5. 运行时可以暂停、单步、自动执行或停止。当前节点旁显示实时活动卡：模型文本、工具名、条件/数据输出和错误摘要；点击节点查看完整输入、模型请求、回复、工具和输出。
6. 右侧可以切换过程、评分、产物、进化。运行记录与隔离工作区保存在 `.egoagent/task_runs/<run_id>/`。

没有 API 时可运行 **离线 DAG / Tool Trace 自检**。它明确使用 `test_bot` 的 scripted DummyLLM，不伪装成真实模型能力；适合验证 UI、工具循环、两个 Harness 和评分器。

## Task v1 格式

题目位于 `task_bench/tasks/*.json`，schema 位于 `task_bench/schema.json`。

```json
{
  "version": "ego.task.v1",
  "id": "example",
  "title": "Example task",
  "description": "What this task measures",
  "category": "coding",
  "difficulty": "easy",
  "tags": ["python"],
  "prompt": "The exact user task",
  "workspace": {
    "files": {
      "src/example.py": "def answer():\n    return 0\n"
    }
  },
  "selection": {
    "recommended_harness": "aider_replica",
    "recommended_identity": "dante",
    "compatible_harnesses": [],
    "compatible_identities": []
  },
  "environment": {
    "backend": "local",
    "network": "disabled"
  },
  "execution": {
    "timeout_seconds": 300
  },
  "evolution": {
    "allowed": false,
    "targets": []
  },
  "evaluation": {
    "pass_score": 1.0,
    "checks": [
      {"id": "tests", "type": "command", "command": ["python", "-m", "unittest"], "weight": 3},
      {"id": "answer", "type": "file_contains", "path": "src/example.py", "value": "return 42", "weight": 1}
    ]
  }
}
```

核心规则：

- fixture 路径必须在 Task workspace 内；每次运行都创建独立目录。
- `command` check 必须是字符串数组，以 `shell=False` 运行，并被限制在 Task workspace；不接受 shell 字符串。
- `network: disabled` 会在模型看到工具 schema 前隐藏 `browser`、`fetch_url`、`fetch_urls` 和 `web_search`。这项列表与统一权限模块共享，不会因新增联网 Tool 而遗漏。这是一项 Agent 工具策略，不等同于操作系统级网络沙箱；需要强网络隔离的题目应选择容器环境。
- `evolution.allowed: false` 会隐藏 Harness/Identity/Skill/Knowledge mutation 工具。
- 允许进化时还会按 `targets` 限制可见 mutation 工具，并且同一时刻只允许一个进化题运行，避免结构差异互相污染。
- 评分只读取产物、退出码、DAG trace、工具调用和实际结构 diff。Agent 声称“已完成”不会自动得分。

## 内置 evaluator

| 类型 | 作用 |
|---|---|
| `file_exists` | 文件或路径存在 |
| `file_contains` / `file_not_contains` / `file_regex` | 文本确定性检查 |
| `json_equals` | JSON Pointer 对应值检查；目标值字段名为 `expected` |
| `command` | 无 shell 的本地测试命令与退出码 |
| `response_contains` | 最终 assistant 回复检查 |
| `node_visited` / `op_visited` | 指定 DAG 节点或节点类型被真实执行 |
| `tool_called` | 指定工具被真实调用 |
| `event_emitted` | 指定运行/进化事件出现 |
| `harness_created` / `harness_modified` | Harness 文件结构差异 |
| `identity_created` / `capability_added` | Identity、Skill 或 Knowledge 文件结构差异 |

每项 check 有独立 `weight`。最终分数为通过项权重 / 总权重，并与 `pass_score` 比较。

## 自进化与 Agent 创建观察

进化题运行前后会对 `harness/` 和 `identity/` 建立内容 hash manifest。运行中，`harness_mutation`、`identity_evolution`、`agent_system_created` 事件实时显示；运行结束后再用实际文件 diff 评分。这样即使事件丢失，真正创建或修改的结构仍有证据。

Task workspace 默认隔离，但允许进化的题目会有意修改仓库级 Harness/Identity 能力。Studio 会显示紫色提示；这类运行是持久变更，应像普通 Agent 改代码一样接受审查。并发的非进化题可以独立运行，进化题会被串行化。

## HTTP API

- `GET /api/task-bench/tasks`
- `GET /api/task-bench/options`
- `GET /api/task-bench/runs`
- `GET /api/task-bench/runs/<run_id>`
- `POST /api/task-bench/runs`
- `POST /api/task-bench/runs/<run_id>/control`
- `POST /api/task-bench/runs/<run_id>/input`

`control` 支持 `pause`、`step`、`auto` 和 `stop`。暂停发生在节点副作用之前，暂停/重试本身不会增加节点尝试次数。

## 当前内置题目

- `offline_trace_smoke`：无 API 的模型/工具/trace 自检。
- `json_release_config`：JSON 配置编辑。
- `python_sum_fix`：Python bugfix + pytest 评分。
- `create_research_agent`：创建 Identity + 可视化 Harness。
- `evolve_local_search`：把重复本地检索沉淀为 Skill/Knowledge。
