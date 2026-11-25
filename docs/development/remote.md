# SSH / WSL 远程工作区

状态：**开发中，默认关闭，未达到 main 产品验收标准**。

- 分支：`codex/feature-remote`
- 起点：`8b4048c`（2026-11-25 main 产品收敛提交）
- 门禁：`product_features/remote.json`
- 依赖：无其他实验功能依赖。
- 总览：[PROJECT_STATUS.md](../../PROJECT_STATUS.md)；历史证据：[成熟度审查](../FEATURE_MATURITY_AUDIT_20261123_ZH.md)。

## 所有权范围

- `remote_workspaces.py`
- `egoagent_server/remote_api.py`
- `void_extension/egoagent-dag-chat/remote-workspaces.js`
- `scripts/remote_runtime.py`
- `desktop/`

共用 API、引擎和 UI 外壳的修改应尽量抽取通用接口，不复制核心实现。当前源码仍在 main 中受门禁保护；本分支是独立完善的工作线，不是已交付声明。

## 开放前必须完成

- [ ] SSH 明确关闭代理转发，使用配置的认证，不复制本地密钥或环境凭据。
- [ ] 分别验收 Windows 浏览器、WebView2 桌面、WSL 和已授权 SSH：打开项目、真实 Chat、文件/终端和回放。
- [ ] 运行与写入始终命中目标机器及工作区；Session、端口和本地模型配置不能串用。
- [ ] 首次安装、断线重连、失败提示和返回本地均可用；不要未经授权向服务器上传运行时。
- [ ] 在干净、无用户数据/凭据的副本中运行定向测试与完整回归，并记录失败和跳过项。
- [ ] 实际点通用户入口、异常与恢复路径，附可复现步骤；有必要时用真实外部依赖单独验收。
- [ ] 合并最新 main 后更新总览、开发日志与验证记录，才能提交开放入口的 PR。

## 开发与验证

仅在此开发分支和隔离数据目录内将上述 manifest 的 `enabled` 改为 `true`。然后重新构建扩展并重启后端；不要只改 UI 标志。开启开关不是解决缺陷，也不是安全隔离。

在不含 `.env` / `.env.local` 的干净导出副本中，用已经安装开发依赖的 Python 执行：

```powershell
python scripts/verify_release.py --output tmp/remote-verification tests/test_remote_workspaces.py tests/test_chat_workspace.py
npm --prefix harness_editor run package:extension
```

HTTP 产品门禁测试应分别覆盖关闭/开启状态；单测显式注入 feature manifest，不把临时打开开关误提交为发布通过。不要把这一目录中的测试成功等同于真实模型效果、平台兼容性或安全认证。

## 记录

2026-11-25：从收敛 main 创建功能分支，列出所有权与验收条件；本分支尚未增加新的功能修复。

