# EgoAgent

用可视化 **Flow Graph** 定义 Agent 的执行结构，用 **Identity** 配置角色、能力与行为约束；在同一个工作台中写代码、调试 Agent、运行任务和查看轨迹。

> 开发者预览版，并非开箱即用的跨平台发行版。Flow 允许循环；源码中的 `dag` / `harness` 是保留的历史命名。模型效果取决于所选模型，副本 Flow 不代表与原产品完全等价。

## 能做什么

| 功能 | 使用入口 |
| --- | --- |
| 代码问答、修改、命令执行；逐块 Accept / Refuse；Tab 灰字补全 | IDE → Chat / 文件编辑器 |
| 多项目、多 Session；改名、分叉、合并；逐轮记录配置 | Chat / Workbench → Sessions |
| 可循环 Flow、子 Flow、输入输出绑定、版本、连线编辑与自动排版 | Workbench → Build |
| Identity / Ego / Superego、工具、Skill、Knowledge；文字和语义能力搜索 | Workbench → Identity / 能力库 |
| 上下文压缩、结果裁剪、记忆；按需委派和复用能力进化 | Code Agent 系列 Flow |
| Chat 与 Task 统一运行可视化、节点输入输出、子运行、录制相簿与事件回放 | Chat → 观察 / Workbench → 观察与回放 |
| 选择 Task、准备本地或容器环境、评分与对比 | Workbench → Task Bench |
| 轨迹、反馈标注与训练数据导出；SSH / WSL 工作区 | Workbench 数据入口 / IDE → SSH / WSL |

权限审批与沙箱可配置。**Workspace Guard 不是操作系统隔离**；全自动审批也不等于安全。只在信任的项目中运行 Agent。容器需另装 Docker，挂载目录中的改动仍可能影响宿主文件。

## 安装共同依赖

需要 Git、Python **3.10+**、Node.js **20+**。下面以 Windows PowerShell 为例：

```powershell
git clone https://github.com/MichaelY310/egoagent.git
cd egoagent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix harness_editor ci
npm --prefix harness_editor run build
```

Linux 上用 `python3 -m venv .venv`，后续 Python 路径替换为 `.venv/bin/python`。语义搜索首次使用可能下载 embedding 模型；浏览器自动化、Docker、训练框架均为额外依赖。

## 浏览器模式

**完整 IDE** 还需要与操作系统匹配的 Void Web 运行时，放在 `void-web/`（包含 `out/server-main.js`、`out/vs/`、`extensions/` 和运行依赖；通常还带 `node.exe` 或 `node`）。运行时不在本仓库，**目前没有已验证的一键下载/安装流程**；仅克隆仓库不足以启动完整 IDE。普通桌面 Void 安装包不能直接替代 Web 运行时。

已有运行时后，在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe start-all.py
```

打开 **http://127.0.0.1:8880/**，通过 File → Open Folder 选择项目。保持该终端运行；`Ctrl+C` 停止启动器及其子服务。浏览器版和桌面版共用本机后端数据。

**没有 Void 运行时？** 可以先使用独立 Workbench，体验 Flow / Identity / Task / 回放（不含完整 IDE 编辑器与原生 Chat）：

```powershell
.\.venv\Scripts\python.exe harness_editor/server.py
```

打开 **http://127.0.0.1:8765/**。也需要先完成前端 build。不要与完整服务重复启动，否则端口会冲突。

## Desktop 模式（Windows x64）

先满足完整浏览器 IDE 的依赖，另需 **.NET Framework 4.8** 与 **Microsoft Edge WebView2 Runtime**：

```powershell
.\desktop\install.ps1
```

脚本编译桌面窗口并创建 **EgoAgent** 快捷方式。之后双击即可自动启动或复用服务，不必手工开终端。文件菜单可打开项目、切换最近项目或新建窗口。

这是 **WebView2 桌面壳 + 同一套 IDE/后端**，不是独立 Electron 发行包；不能只复制 exe 给别人。关闭窗口不会停止后台任务，需要时在“服务”菜单中停止。详情：[桌面使用与安装](docs/DESKTOP_APP_ZH.md)。

## 第一次使用

1. 在 **Workbench → Settings** 配置模型服务地址、模型名、API Key，并测试连接。密钥保存在被 Git 忽略的 `.env.local`，不要写入 Flow 或 Identity；也可参考 [.env.example](.env.example)。没有模型服务时可编辑图和运行离线测试，但不能真正进行 AI 对话/补全。
2. IDE 打开项目，展开 **Chat → Agent 配置**，选择 `code_agent_auto`，默认 Identity 为 `adaptive_deepseek_coder`。只读问题选 Chat，允许修改时选 Agent。
3. 发送“只读说明这个项目的入口和测试命令，不要修改文件”。需要写代码时再下达修改任务，并审阅改动。
4. 点击 Chat 的 **观察**，将 Build 链接到该 Session；此时图只读。解锁并确认退出链接后才能编辑/独立试跑，不会暂停 Chat 中的 Agent。
5. 低开销任务选 `code_agent_fast`；长程复用任务选 `code_agent_long`；多个独立子系统选 `code_agent_team`。不保证每次触发进化或委派。详见 [Code Agent 配置](docs/CODE_AGENT_PROFILES_ZH.md)。

Tab 补全：输入后等待灰字，`Tab` 接受、`Esc` 取消、`Ctrl+Z` 撤销。详见 [自动补全](docs/AUTOCOMPLETE_ZH.md)。SSH / WSL 从 IDE 的 **SSH / WSL** 入口连接，目标环境需另配依赖与模型：[远程使用](docs/REMOTE_WORKSPACES_ZH.md)。

## 正在开发 / 尚有限制

- **分发与安装**：完整 IDE 运行时自动安装、独立安装包、macOS/Linux 桌面版尚未交付。
- **自进化与副本 Flow**：结构修改、Skill 创建、验证与回滚机制已实现；稳定收益和通用热替换仍需验证。保存新版本不等于自动热替换正在执行的节点。
- **评测与训练**：Task、轨迹导出和适配器可用；大规模 benchmark、分布式 RL 和各训练框架完整兼容性仍属实验范围。
- **远程与兼容性**：SSH 需预先配置免交互认证；不自动同步不同机器的 Session/密钥。未覆盖所有浏览器、模型及系统组合。
- 低完成度的强制新手教程已移除，保留手动文档与演示素材。进度与本轮验证见 [开发状态](docs/DEVELOPMENT_STATUS_20260930.md)。

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
$tests = Get-ChildItem tests -Filter '*.test.cjs' | ForEach-Object { $_.FullName }
node --test $tests
npm --prefix harness_editor run package:extension
```

`package:extension` 构建并同步 Workbench 到扩展；更改后重新加载 IDE。后端变更需重启服务。不要提交密钥、Session、轨迹、远程令牌和 `.runtime/`。

核心目录：`harness/`（Flow）、`identity/`（角色与能力）、`harness_editor/`（API + React）、`void_extension/`（IDE 集成）、`desktop/`（桌面壳）、`task_bench/`（任务）、`tests/`（回归）。

更多：[Flow 设计](docs/DAG_AUTHORING_MODEL.md) · [Task 格式](docs/TASK_BENCH.md) · [观察与回放](docs/UNIFIED_FLOW_OBSERVATION_ZH.md) · [手动演示指南](docs/VIDEO_SERIES_MASTER_GUIDE_ZH.md)

许可证：[Apache-2.0](LICENSE)。第三方依赖遵循各自许可证；Void/VS Code 运行时需单独取得。
