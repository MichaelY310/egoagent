# 多项目与多 Session 管理

状态：已实现  
适用界面：Void 原生 Chat、Agent Workbench → Sessions

## 用户模型

EgoAgent 将三个概念分开保存：

- **Project**：一个规范化的 workspace 路径；移动前不会因为 URL 写法不同而重复建项。
- **Session**：某个 Project 中可继续、可回放、可 fork/merge 的对话与真实运行轨迹。
- **Live Run**：仍在执行或等待输入的 Session。一个 Project 可以同时保留多个 Live Run。

Session 的模型上下文、完整审计历史和轨迹仍保存在原 Session 目录。项目标题、置顶、
归档和当前 Session 等轻量元数据独立保存在 `.egoagent/project_portfolio.json`，不会修改
训练用轨迹，也不会被提交到 Git。

## 在原生 Chat 中并行多个 Session

1. 用 `python start-all.py` 启动 EgoAgent，并在 Void 中打开任意 workspace。
2. Chat 顶部的 Session 条会列出当前 Project 的所有运行中、等待输入和最近 Session。
3. 点 `＋` 创建新 Session；旧 Session 不会被停止。
4. 点任意 Session 胶囊切换。后台 Session 的 WebSocket 事件只更新自己的状态，不会
   把当前正在阅读的对话强制滚动或替换。
5. 点 `▥` 打开 Workbench 的 Project & Session Portfolio。

同一秒启动相同 Harness 的两个 Session 也有独立运行 ID，不会写进同一个目录。

## Project & Session Portfolio

在 IDE 右上角点 `Open Agent Workbench`，再按以下路径进入：

1. 顶栏点 `More`；
2. 在弹出的菜单点 `Sessions`；
3. 进入 `Project & Session Portfolio` 后，点左上角 `＋ Project`。

这里的 Project 就是一个 workspace 文件夹，不是要把当前项目“装进”另一个项目：

- 点左上角 `＋ Project` 可管理另一个 workspace：
  - `选择已有文件夹` 只登记路径，不移动、不复制目录；
  - `创建新文件夹` 先选父目录、再输入文件夹名，只创建空 workspace；
  - 勾选“完成后在新的 IDE 窗口打开”不会关闭当前 Project；
- 左栏按 Project 展示 Session 数、运行数、最近活动和路径；
- 可查看全部 Project，或只查看当前 Project；
- 可搜索 Project、Session 标题和首条用户任务摘要；
- 可置顶 Project 或 Session；
- 双击/打开多个 Session 后，它们以持久化标签页保留，刷新 Workbench 不丢失；
- 每个 Session 行右侧的 `⑂ / ⇄` 和详情栏的 `Fork / Merge` 调用同一套分支服务；
- Heart Flow 的续接胶囊也复用同一个 Fork / Merge 对话框，不存在另一套隐藏实现；
- 每个 Session 都可进入精确轨迹回放。

Workbench 顶栏右侧的 `◐` 下拉框可选择 `跟随 IDE / 浅色 / 深色`。选择会保存在浏览器
本地，下次打开仍然生效；Builder、Evaluate、Library、Improve、Sessions、Settings 和
More 中的管理页面共用同一套主题，不再各自写死黑色或白色面板。

旧 Session 会按顺序从 `session.json`、`trajectory.jsonl`、历史 System working-directory
消息推断所属 workspace，不需要一次性迁移或重写历史。无法可靠归属的记录进入
`Legacy / Unknown`，不会被错误塞进当前 Project。

## 跨项目 Merge

跨项目历史不允许 `Direct` 暴力拼接，因为右侧的工作目录、规则和文件引用在左侧
Project 中可能失效。可用方法为：

- `Auto`：跨项目时固定选择 `Summary`；同项目仍按 token 阈值选择 Direct/Summary。
- `Summary`：分别总结两个 Session 的新增内容，保留来源 Project、结论、文件事实、
  测试证据、阻塞项和下一步，再生成位于左侧 Project 的新 Session。
- `Dialogue`：两个分支 Agent 只交流共同点之后的新事实和冲突，最后由 synthesis Agent
  形成带来源的合并上下文；适合两个 Project 需要共享设计或研究发现的情况。

所有 merge 都新建 Session，不覆盖任何来源。结果 `lineage.json` 明确记录左右 Project、
目标 workspace、共同前缀和所用模型调用，训练数据导出不会把两个 Agent 错认成一个连续
原始轨迹。

## HTTP API

```text
GET  /api/projects?workspace=<optional-workspace>
GET  /api/projects/sessions?project_id=<id>&workspace=<path>
POST /api/projects/register
POST /api/projects/create
POST /api/projects/update
POST /api/projects/session/update

GET  /api/sessions?project_id=<id>&workspace=<path>
POST /api/session/<name>/fork
POST /api/sessions/merge
```

跨项目 merge 的请求可带 `target_workspace`；当前产品固定由左侧 Session 所属 Project
作为目标，避免把来源 Session 的路径错误注入另一个 workspace。

## 验证

```powershell
python -m unittest tests.test_project_portfolio tests.test_session_branching `
  tests.test_interactive_runs tests.test_interactive_execution_service `
  tests.test_chat_workspace tests.test_void_workbench_integration

cd harness_editor
npx tsc -b
npm run build
npm run package:extension
```

API 回归另见 `tests/test_project_portfolio_api.py`。测试覆盖旧记录迁移、项目分组与置顶、
同项目多运行、工作区隔离、跨项目 Direct 拒绝、Summary 目标归属和原生 IDE 接线。
