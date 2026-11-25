# EgoAgent

本地代码助手：用 **Flow Graph** 定义执行结构，用 **Identity** 配置角色、能力与行为约束；在 IDE 中写代码、审阅修改、管理 Session 和回放运行。

> 开发者预览版，并非开箱即用的跨平台发行版。Flow 允许循环；源码中的 `dag` / `harness` 是保留的历史命名。模型效果取决于所选模型，副本 Flow 不代表与原产品完全等价。

**main 是收敛后的日常代码助手，不是实验功能合集。** 未完成入口及其依赖默认隐藏/禁用，代码保留以便独立完善。
当前状态与全部开发分支：[项目状态总览](PROJECT_STATUS.md)；持续更新的记录：[开发日志](PROGRESS.md)。

## 能做什么

| 功能 | 使用入口 |
| --- | --- |
| 代码问答、修改、命令执行；逐块 Accept / Refuse；Tab 灰字补全 | IDE → Chat / 文件编辑器 |
| 多项目、多 Session；改名、分叉、合并；逐轮记录配置 | Chat / Workbench → Sessions |
| 可循环 Flow、子 Flow、输入输出绑定、版本、连线编辑与自动排版 | Workbench → Build |
| Identity / Ego / Superego、工具、Skill、Knowledge；文字和语义能力搜索 | Workbench → Identity / 工具与 Skills / 能力库 |
| 上下文压缩、结果裁剪、记忆、子 Flow 与并行组件 | Build / 已开放的 Cookbook |
| 运行可视化、节点输入输出、子运行、录制相簿与事件回放 | Chat → 观察 / Workbench → 运行相簿 |

权限审批与沙箱可配置。**Workspace Guard 不是操作系统隔离**；全自动审批也不等于安全。只在信任的项目中运行 Agent。容器需另装 Docker，挂载目录中的改动仍可能影响宿主文件。

## 安装共同依赖

只需要 Agent / Flow，不需要界面？看 [纯核心使用与分层说明](docs/HEADLESS_CORE_ZH.md)。
`python -m egoagent_core` 可独立运行；`scripts/export_core.py` 可导出不含前端和服务器的源码目录。
下面是**带 UI 的完整产品**安装方式。

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

已有运行时后，可选择以下启动方式：

Windows 也可以执行一次 `.\desktop\install-browser.ps1`，在桌面创建 **EgoAgent 浏览器版** 快捷方式。
以后双击会自动启动或复用后台，等待 IDE/API 就绪后打开默认浏览器，不打开桌面版窗口，也不需要保留终端。
关闭浏览器不会停止后台；启动失败会弹窗提示，日志在 `.runtime/desktop/browser-launcher.log` 和 `services.log`。

或者手动启动：

```powershell
.\.venv\Scripts\python.exe start-all.py
```

打开 **http://127.0.0.1:8880/**，通过 File → Open Folder 选择项目。保持该终端运行；`Ctrl+C` 停止启动器及其子服务。浏览器版和桌面版共用本机后端数据。

**没有 Void 运行时？** 可以先使用独立 Workbench，体验 Flow / Identity / 工具目录 / 独立试跑与回放（不含完整 IDE 编辑器与原生 Chat）：

```powershell
.\.venv\Scripts\python.exe -m egoagent_server
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
   **Identity 的 Base URL / model 显式配置优先，分别留空才继承全局设置。** 自定义地址连接失败会报错，不会悄悄切换模型。不同服务的密钥用 `llm.api_key_env` 指定环境变量；全局密钥仅用于对应服务地址，不自动发给其他服务器。
2. 在 **Workbench → Build → 配置 → 角色与 Identity** 为 Flow 的角色选择 Identity，并设置运行策略后保存。默认 `code_agent_fast` 已包含角色绑定；未绑定的旧模板需要在这里补齐。`test_bot` 是固定脚本测试角色，不调用真实模型。
   IDE 打开项目，展开 **Chat → 选择 Flow**，只选择 Harness 和 Flow 版本。Chat 与 Build 独立试跑均读取该版本保存的 Identity 和运行策略，不再提供默认 Identity、模式或逐角色覆盖。修改配置后保存新版本，在 Chat 切换版本，下一条消息才使用它；工作区审批和沙箱不会因此解除。
3. 发送“只读说明这个项目的入口和测试命令，不要修改文件”。需要写代码时再下达修改任务，并审阅改动。
4. 点击 Chat 的 **观察**，将 Build 链接到该 Session；此时图只读。解锁并确认退出链接后才能编辑/独立试跑，不会暂停 Chat 中的 Agent。
5. 日常使用先选 `code_agent_fast`。依赖未完成功能的 Auto/Long/Team 等 Flow 会按依赖隐藏，不要按历史教程强行选择。各分支的释放条件见状态总览。
6. 学习组装从 Build 的 `cookbook_01_react` 开始；原 24 个阶段中，仅展示当前发行范围支持的课程。**工具与 Skills** 可检索工具、查看参数和源码；在 IDE 中点编辑会打开源文件。在 Identity 中选择启动时加载的能力，重新创建或加载 Agent 后生效，不是安全白名单。

Tab 补全：输入后等待灰字，`Tab` 接受、`Esc` 取消、`Ctrl+Z` 撤销。详见 [自动补全](docs/AUTOCOMPLETE_ZH.md)。SSH / WSL 暂在 `codex/feature-remote`，目标环境需另配依赖与模型：[远程使用](docs/REMOTE_WORKSPACES_ZH.md)。

## 正在开发 / 尚有限制

- **分发与安装**：完整 IDE 运行时自动安装、独立安装包、macOS/Linux 桌面版尚未交付。
- **默认关闭**：Evaluate、Improve、Research/EgoIR/副本、训练导出、部署市场、后台队列、CoC、Heart Flow、SSH/WSL；各自在 `codex/feature-*` 分支继续开发。保留源码不代表在 main 开放。
- **自进化与训练效果**：尚不保证稳定收益、通用热替换或训练框架全面兼容。保存 Flow 版本不等于热替换正在执行的节点。
- **取消与超时**：Process 节点终止子进程树；普通 Python/工具线程无法安全强杀，超时后等待其停止再返回且不自动重试。需要严格硬超时的工作应使用独立进程/容器。
- **远程与兼容性**：SSH 需预先配置免交互认证；不自动同步不同机器的 Session/密钥。未覆盖所有浏览器、模型及系统组合。
- 低完成度的强制新手教程已移除；Cookbook 是可编辑的 Flow 示例，不是强制点击向导。最新进度见 [开发日志](PROGRESS.md)，历史发布检查见 [2026-09-30 开发状态](docs/DEVELOPMENT_STATUS_20260930.md)。

## 开发与验证

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
$tests = Get-ChildItem tests -Filter '*.test.cjs' | ForEach-Object { $_.FullName }
node --test $tests
npm --prefix harness_editor run package:extension
```

`package:extension` 构建并同步 Workbench 到扩展；更改后重新加载 IDE。后端变更需重启服务。不要提交密钥、Session、轨迹、远程令牌和 `.runtime/`。

核心：`egoagent_core/` + 根目录 Python 运行时、`llm/`、`task_bench/`、`self_evolution/`；定义资源：`harness/`、`identity/`、`capability_packs/`。可选 API：`egoagent_server/`。可删除的界面：`harness_editor/`（React，旧 Python 路径仅兼容转发）、`void_extension/`（IDE 集成）、`desktop/`（桌面壳）。核心不导入 UI / API，分层回归见 `tests/test_core_separation.py`。

更多：[Flow 设计](docs/DAG_AUTHORING_MODEL.md) · [观察与回放](docs/UNIFIED_FLOW_OBSERVATION_ZH.md)。历史视频与实验文档可能包含未开放功能，以 [项目状态总览](PROJECT_STATUS.md) 为准。

许可证：[Apache-2.0](LICENSE)。第三方依赖遵循各自许可证；Void/VS Code 运行时需单独取得。
