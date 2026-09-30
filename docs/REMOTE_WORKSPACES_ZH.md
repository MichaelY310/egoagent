# SSH / WSL 远程项目使用指南

这不是一个仅能 `ssh` 的终端：远程窗口的文件浏览器、编辑器、终端、EgoAgent 后端、Chat、Workbench 和 Session 都在目标 Linux 环境工作。Windows 只负责浏览器与连接管理。打开 Windows 项目与打开 Linux 项目不会混用工作目录或后端地址。

## 1. 从哪里打开

1. 按平时的方法启动本机 EgoAgent：在仓库目录运行 `.venv\Scripts\python.exe start-all.py`。
2. 浏览器打开 `http://127.0.0.1:8880/`。
3. 点击 **左下角 `SSH / WSL`**，或 Chat 顶部 **`SSH / WSL`**。也可以按 `Ctrl+Shift+P` 搜索 `EgoAgent: Open SSH / WSL Workspace`。
4. 菜单中可新建连接，也可选择保存过的连接，打开、重连、改名或移除。

以下为连接示例；新安装不会自带开发者的连接记录：

| 名称 | 目标 | 初始项目目录 |
| --- | --- | --- |
| WSL Ubuntu | 本机 Ubuntu WSL | `/home/your-user` |
| my-server · terminal-bench | SSH config 的 `my-server` | `/srv/projects/my-project` |

建议在 WSL 中新建一个指向**具体项目**的连接，不要把整个 home 当成项目。连接后可用 IDE 的 **File → Open Folder** 切换同一目标上的目录；保存的连接书签仍指向原始目录。

## 2. 新建 WSL 连接

1. 选择 **新建 WSL 项目连接**，选择已经安装的发行版，例如 `Ubuntu`。
2. 填目标中的现有 Linux 目录，例如 `/home/your-user/my-project`，不能填 `C:\...`。Windows 挂载目录则使用 `/mnt/c/...`。
3. 填连接名。确认安装提示，默认选择 **连接（不复制密钥）**。
4. 等待安装完成，浏览器会打开独立远程窗口。左下角显示连接名。
5. IDE 可能询问是否信任项目。请自行核对路径，只信任你认可的项目；**不要为了方便信任整个 home 或父目录**。Restricted Mode 可能禁用终端、任务和部分扩展功能。

## 3. 新建 SSH 连接

1. 先在 Windows 终端确认普通 `ssh my-server` 可以登录。EgoAgent 复用已有 OpenSSH 配置；需要已经配置免交互认证，且确认过服务器指纹。
2. 选择 **新建 SSH 项目连接** → `my-server`。也可输入 `user@host`；端口、跳板机与私钥路径请放在 `~/.ssh/config`，不要填成一段命令。
3. 项目路径填 `/srv/projects/my-project`，设置名称并确认安装。
4. 打开后左下角显示 `my-server · terminal-bench`。此时文件与命令位于服务器上，不是 Windows 文件的镜像。

连接使用严格主机指纹检查，不自动接受新主机，不自动转发 SSH Agent。首次认证/密码/二次验证尚不能在连接向导中完成，须先用系统终端配置。

## 4. 在远程继续使用 Agent

- Chat 选择 Flow、版本与 Identity，像本机一样发任务。
- 打开 Workbench 可以编辑 Flow、查看 Session、运行任务与观察执行。它访问的是该连接自己的后端。
- 远程终端在目标环境执行；例如 `pwd`、`uname -s`、`python3 ...`。依赖、Python 环境、Docker、浏览器工具也需要在**目标**环境可用。
- 预览你自己启动的 Web 应用时，输入 Windows 浏览器能访问的地址。当前只自动转发 EgoAgent 的端口，不自动转发任意应用端口；例如服务器应用使用 3000，可另外运行 `ssh -N -L 127.0.0.1:3000:127.0.0.1:3000 my-server`，再预览 `http://127.0.0.1:3000/`。
- 文件修改、Accept/Refuse 与撤销操作针对目标文件。不要把远程路径解释成 Windows 路径。
- Session、轨迹、Flow 版本与 Identity 修改留在目标运行时中；不同连接的运行时相互隔离。目前**不自动同步**本机与远程的历史、密钥和后续 Flow 修改。

### 模型需要另外配置

“已连接”表示 EgoAgent 后端连通，**不代表模型已配置或测试成功**。新目标可能显示默认 Ollama 地址；没有运行 Ollama 时不能直接调用它。

两种方式：

1. 在远程窗口打开 **Workbench → More → Settings**，填写模型服务配置并运行连接测试。
2. 断开该连接，再选择 **连接并复制模型配置**，然后明确确认信任目标机器。它仅复制支持的模型环境变量到目标运行时的 `.env.local`，不复制 SSH 密钥或整个本机环境。

目标管理员可能读取服务器上的 API Key，因此不要向不信任的服务器复制。当前实机 SSH 验证**没有复制 API Key**；WSL 的 Flash 连通测试读取本机已有配置，没有把它发送给 SSH 主机。

## 5. 重连、关闭与数据位置

### 网页版如何真正打开 WSL / SSH（2026-09-15 更新）

1. 点击状态栏或 Chat 顶部的 **SSH / WSL**。
2. 选择已有连接，再选 **打开远程项目**（未连接时先完成连接）。
3. 网页版显示 **工作区已就绪** 对话框：点 **在新页面打开** 保留本机页面；或点 **在当前页面打开** 直接切换。
4. 如果浏览器拦截新页面，对话框会保留并说明原因。选当前页面打开，或复制对话框中的地址即可。不需要全局允许弹窗。
5. 成功后，文件树显示 Linux 路径，状态栏显示 `WSL: Ubuntu …` 或对应 SSH 名称，Chat 显示目标后端已连接。

桌面版继续使用原生新窗口。连接就绪与窗口实际打开是两件事；不会再仅凭连接成功就声称“已打开”。

更新代码后，已有桌面窗口选择 **视图 → 重新加载界面**，网页刷新一次。已连接的远程安装需重新连接才会部署后续代码更新；连接记录、项目和 Session 保留。

### 消息显示与后台恢复

模型事件和保存的输出均携带 `run_id / workspace / harness / harness_version / mode / agents / surface`。Chat 不再因为流事件缺少版本号而丢弃本 Session 的回答；旧远程运行时的事件仅在精确匹配当前运行时兼容，显式版本不符仍拒绝。

WebSocket 重连、页面恢复可见时会补收当前运行输出，连接正常时也每 15 秒低频校准。后台若真的重启，会显示“本轮中断，可重新发送并继续此 Session”，不会把一个已恢复的 API 一直误报为后端不可用。守护进程仅自动恢复退出的后台，不再因一次 TCP 探测超时结束存活进程。

- 关闭浏览器标签页不停止远程运行。
- 在本机 `SSH / WSL` 菜单选择该连接 → **断开连接**，会停止该连接中的服务与终端进程。先保存文件、结束正在运行的任务。
- 再次连接保留远程项目、Session、Identity 与 Flow 数据。应用有更新时自动部署代码更新，不覆盖已有 Identity/Flow 文件。
- **移除连接记录**仅删除本机书签，不删除远程项目或安装目录。
- 本机书签：`.egoagent/remote_workspaces.json`；连接日志：`.runtime/remote-<id>.log`。
- 目标安装：`~/.local/share/egoagent/connections/<id>/`；应用与 Session：其下的 `app/` 和 `app/sessions/`；编辑器状态：`editor-data/`。
- 首次约 62 MB 编辑器下载，安装约 250 MB，加上后续 Session/轨迹增长。使用纯 Python 依赖包，不需要 sudo，不下载模型，不改变系统 Python。

## 6. 安全边界与已知限制

SSH 采用加密隧道，只绑定 loopback 地址。远程 API/事件流需要每次连接生成的凭证；编辑器服务使用受保护安装目录中的 Unix socket。未认证请求返回 401，不把服务器上的 loopback 端口当成身份认证。

这是远程执行，不是容器沙箱。Agent 仍须遵守 EgoAgent 的工作区/审批策略；需要操作系统级隔离时，在目标环境配置现有 container 模式。服务器管理员与同一系统用户不在此连接隔离的防护范围内。

当前支持 Windows 管理端、Linux x64/arm64 SSH 目标与 WSL、目标 `python3 >= 3.10`。Windows/macOS SSH 目标尚不支持。可选的语义向量模型、浏览器依赖、GPU/CUDA、Docker 等不随连接安装；相应功能仍取决于目标环境。首次优先直连下载并验证官方 SHA256；网络受限时会明确报错，不擅自更改系统代理/DNS。当前电脑已有校验通过的 x64 编辑器缓存。

## 7. 本次验证及复测

在 Ubuntu WSL 和 my-server 上分别创建了 `/tmp/egoagent-remote-demo-*` 测试目录，未让 Agent 修改 `terminal-bench` 源码。可重复运行：

```powershell
.venv\Scripts\python.exe scripts/remote_smoke_runner.py <连接 ID>
```

测试覆盖目标身份、Flow/Identity 列表、文件写入、Refuse、Undo Refuse、Accept、Undo Accept、Linux 命令执行、Chat Flow 等待用户输入、Session 保存和配置归属，以及 Chat/Workbench 同时订阅事件流。报告写入 `.runtime/remote-smoke-<id>.json`。

可选 WSL 模型小测试：

```powershell
.venv\Scripts\python.exe scripts/remote_smoke_runner.py <WSL 连接 ID> --model-env /mnt/c/Users/aa310/Desktop/egoagent
```

这会读取指定目录的已有模型配置并发出一次很短的 API 请求，**不是完整编码任务评测**。SSH runner 禁止使用这个本机配置参数。

前端已检查远程入口、文件树、Chat 和 Workbench。浏览器的“信任文件夹”属于用户决定；自动测试没有关闭这个保护，因此终端的前端操作仍需用户信任具体项目后自行确认。底层 Linux 命令与文件审阅 API 已做实机验证。
