# 桌面版剪贴板与 WSL 文件拖放修复（更新于 2026-09-19）

## 原因

1. 桌面壳默认拒绝权限请求。只有 `ClipboardRead && IsUserInitiated` 才弹出询问，但编辑器经过异步命令/扩展通信再读剪贴板时，不一定保留这个标志，导致没有询问就拒绝。旧拒绝还可能被 WebView2 默认保存到 profile。
2. Chat 拖放解析只识别 Windows 路径和部分 URI，没有识别 Linux 绝对路径。WSL/SSH Explorer 的 `CodeFiles` 因而被丢弃；`file:` URI 也没有转换为当前远程 Workspace 的 URI。

## 修改

- 按用户 2026-09-19 的要求，当前 IDE 连接及其隔离的 `*.localhost` Webview 自动获得剪贴板读取权限，不再弹出 Yes/No，也不依赖可能在异步通信后丢失的 `IsUserInitiated`。
- 每次请求都检查顶层 IDE 来源、请求来源和端口，不保存成跨站点/跨连接的永久授权。剪贴板权限不等于向模型发送信息。
- 不给其他网站、其他端口或其他权限自动授权。不修改 Windows 剪贴板设置。
- 清理本应用已知 origin 的旧 `ClipboardRead=Deny` 为默认状态，让新的来源检查重新决定；不清理 cookie、其他权限或外部网站设置。新请求 `SavesInProfile=false`。
- 已删除剪贴板权限对话框和临时询问状态，桌面编辑操作不再被模态弹窗阻断。
- 拖放识别 Linux/Windows/UNC 路径、URI 列表和序列化 URI 对象；文件引用映射到当前 Workspace。显式远程 URI 保留原 authority，不能冒充另一个主机的同名文件。
- 读取前仍检查 `vscode.workspace.getWorkspaceFolder`。这不是将系统外部文件自动上传到 SSH/WSL 的功能；推荐从当前 IDE 左侧项目树拖入文件或文件夹。

## 验证与部署状态

截至 2026-09-19：

- 44 项 Node 前端测试通过（含 7 项新拖放回归测试）。
- 34 项桌面 C# policy/state 测试通过。
- 52 项 Python 桌面生命周期和 Void 集成测试通过（新增自动授权范围和无弹窗回归测试）。默认 pytest 临时目录有既有访问权限问题，测试改用新的仓库内 `.runtime/desktop-tests-<uuid>` 临时目录，没有修改原目录权限。
- 实机复现：原本机演示项目文件能拖入，而 WSL FastVideo 项目的 `docs` 目录被拒绝。
- 更新本机及已有 WSL 连接扩展、重新加载窗口后，WSL `docs/` 已成功变成正文内的结构化附件，预览包含实际目录清单。测试没有发送消息或调用模型。
- 新桌面壳已安装到 `.runtime/desktop/releases/20260919-211528-b532a808/EgoAgent.exe`，桌面和开始菜单的 EgoAgent 快捷方式已更新到这个版本。
- 实机复制 `garden.py` 的编辑器选区，Ctrl+V 在 Chat 出现 `garden.py:4-4` 结构化引用；Ctrl+Shift+V 插入对应纯文本。整个过程无剪贴板权限弹窗、无读取失败通知，没有发送消息或调用模型。
- 正在运行的旧窗口未强制关闭，后台未停止。旧窗口继续使用旧桌面壳；刷新页面不能更新壳，应使用新版窗口或从桌面快捷方式重新打开。

正式安装：从仓库运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\desktop\install.ps1
```

若旧版本正在运行，安装器将使用新的 release 目录，更新快捷方式，不覆盖已加载的程序，也不结束任何窗口。随后使用原桌面快捷方式启动新版，复制/粘贴无需确认。SSH 现有安装未直接连接更新，需要正常更新其扩展；新增远程安装会包含新解析代码。

## 参考

- [Microsoft WebView2 权限事件](https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/win32/icorewebview2permissionrequestedeventargs)：用户手势标志不等于用户对资源访问的授权意图。
- [SavesInProfile](https://learn.microsoft.com/en-us/dotnet/api/microsoft.web.webview2.core.corewebview2permissionrequestedeventargs.savesinprofile)：默认保存权限结果，设为 false 则只影响当前请求。
