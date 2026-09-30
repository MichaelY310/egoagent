# EgoAgent Windows 桌面版

## 平时怎么用

1. 双击桌面或开始菜单里的 **EgoAgent**。
2. 首次启动会显示“正在准备 IDE 和 Agent 服务”。启动器检查本机后端和编辑器；没启动时自动启动，已经启动则复用，不需要再开 PowerShell。
3. 进入独立的 EgoAgent 窗口。文件编辑器、右侧 Chat、Workbench/Flow 使用现有产品代码，不是另做一个功能较少的界面。
4. 顶部原生菜单 **文件 → 打开本机项目文件夹…** 可以换项目；**最近打开** 保留最近 12 个仍存在的目录。下次启动恢复最后一个本机项目。
5. **文件 → 新建窗口** 可以同时查看不同项目。一个窗口切换项目不会强制切换其他窗口；它们复用后台服务。
6. 再次双击图标会优先激活已有窗口，不会每次再起一整套服务。

SSH / WSL 继续从 Chat 中的 **SSH / WSL** 或 IDE 左下角远程入口进入。本机文件夹选择器不负责选择 Linux 路径。已登记远程连接的本机转发地址可在独立 EgoAgent 窗口中打开；不会把含远程令牌的 URL 保存到最近项目列表。

## 关闭、恢复与停止

- 关闭窗口前会提醒保存。**关闭窗口不停止后台 Agent**，重开后可以继续查看服务端保存的 Sessions。
- **服务 → 检查 / 恢复连接**：重新检查并恢复桌面界面；如果后台不存在则尝试重新启动。未保存文件请先保存，恢复连接会重新加载编辑器。
- **服务 → 打开运行日志**：打开 `.runtime/desktop`，桌面启动的服务输出在 `services.log`。
- **服务 → 停止桌面版启动的后台…**：明确确认后，向桌面版自己启动的后台发出退出信号。会影响共享该后台的窗口和任务。不会按照端口随意结束进程，也不会强杀手动启动的其他实例。
- 恢复后台不代表恢复所有正在执行的进程；需要暂停/断点恢复的任务依然遵循原有运行时规则。

## 与浏览器版的数据关系

同一仓库、同一本机服务端的数据不另存一套：模型配置、项目、已持久化 Session、Flow、Identity 等仍由现有 EgoAgent 后端管理。**桌面窗口的浏览器缓存和登录/界面状态与 Chrome、Edge 分开**，所以第一次不一定自动选中浏览器里正在看的 Session；从 Session Portfolio 选择已有记录即可。

桌面版不导出 API Key，不把凭证嵌入 exe；也不修改防火墙、DNS、代理、开机启动或工作区的 Agent 安全策略。外部 http/https 链接交给系统默认浏览器；不向页面开放直接调用任意本机程序的 WebView 主机对象。

## 安装 / 更新

适用于已经能够运行 EgoAgent 的 Windows x64 仓库，需要现有 `.venv`、`void-web`、Node、.NET Framework 4.8 和 Microsoft Edge WebView2 Runtime。

关闭 EgoAgent 桌面窗口后，在仓库根目录的 PowerShell 执行：

```powershell
.\desktop\install.ps1
```

安装脚本下载微软 WebView2 SDK（固定版本并检查 SHA-256），编译桌面壳，运行基础测试，创建当前用户桌面和开始菜单快捷方式。不需要管理员权限；不会自动改变 PowerShell 执行策略。若机器的组织策略禁止脚本执行，应按组织要求处理，不要关闭安全防护。

如系统没有 WebView2 Runtime，请安装微软官方运行时，参考 [WebView2 分发文档](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)。安装脚本不会擅自安装系统组件。

可选：

```powershell
# 编译和运行测试，不创建快捷方式
.\desktop\install.ps1 -NoShortcuts

# 指定项目 / 独立窗口
.\.runtime\desktop\EgoAgent.exe --folder "C:\path\to\project"
.\.runtime\desktop\EgoAgent.exe --new-window
```

## 版本边界

这是 **Windows 原生窗口 + WebView2 + 现有 Void/EgoAgent 后端**，窗口没有浏览器地址栏，自动管理本机服务。它不是完整重编译的 Electron/Void 桌面发行版，也还不是包含 Python、Node、Void、模型配置的一键分发安装包。**不要只复制 `EgoAgent.exe` 给别人使用**；目前需要保留仓库及其运行环境。移动仓库后重新运行安装脚本更新路径和快捷方式。

所有实际文件操作、命令执行和安全审批仍由现有运行时负责；WebView 的页面隔离不是 Agent 命令的操作系统沙箱。

## 实现位置与验证

- `desktop/DesktopApp.cs`：原生窗口、WebView 导航边界、项目菜单、状态提示和多窗口。
- `desktop/DesktopCore.cs`：URL/路径策略、参数转义、原子保存最近项目。
- `desktop/bootstrap.py`：跨窗口启动锁、健康检查、后台归属记录和专属退出标记。
- `start-all.py --stop-file …`：仅桌面启动器使用的可选退出信号，原有手动启动方式不变。
- `.runtime/desktop`：生成的程序、窗口状态、启动归属记录、日志；不是源码发布目录。
- `%LOCALAPPDATA%\EgoAgent\WebView2`：按仓库隔离的桌面渲染缓存。

已增加桌面策略/状态测试，以及启动、复用、端口占用、错误页面、代理隔离、并发启动、退出归属和超时测试；测试不调用收费模型。

本机验收（2026-09-15）：69 项 Python 测试和 3 个 subtests 通过，22 项桌面策略/状态断言通过。用 Windows 界面实际检查了自动启动服务、快捷方式重开、重复启动激活、恢复项目、打开源码、Chat 已连接、Workbench Home/Build、项目选择器、多窗口及关闭窗口后后台存活。修复了原生菜单遮住 IDE 标题栏的问题。本轮没有重新验证每个模型任务、SSH/WSL 实机连接或全部 IDE 功能；这些沿用原有实现。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_desktop_launcher.py tests/test_remote_workspaces.py tests/test_void_workbench_integration.py -q
```
