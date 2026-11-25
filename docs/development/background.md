# 后台持久任务、恢复与工作区交付

状态：**开发中，默认关闭，未达到 main 产品验收标准**。

- 分支：`codex/feature-background`
- 起点：`8b4048c`（2026-11-25 main 产品收敛提交）
- 门禁：`product_features/background.json`
- 依赖：无其他实验功能依赖。
- 总览：[PROJECT_STATUS.md](../../PROJECT_STATUS.md)；历史证据：[成熟度审查](../FEATURE_MATURITY_AUDIT_20261123_ZH.md)。

## 所有权范围

- `egoagent_core/background_workspace.py`
- `harness_editor/src/components/BackgroundRuns.tsx`
- `harness/cookbook_10_durable/`

共用 API、引擎和 UI 外壳的修改应尽量抽取通用接口，不复制核心实现。当前源码仍在 main 中受门禁保护；本分支是独立完善的工作线，不是已交付声明。

## 开放前必须完成

- [ ] 修复扫描省略的大文件（包括超过 20 MB 文件）不能被当作删除；交付前验证完整性。
- [ ] 恢复遵循精确版本和副作用幂等性；不重复写入、提交或执行外部动作。
- [ ] 取消、重启、失败重试、并发修改与交付冲突均有确定性测试。
- [ ] 有主机重启后的真实恢复演示；普通 Python 线程不可强杀的边界在 UI 中明确。
- [ ] 在干净、无用户数据/凭据的副本中运行定向测试与完整回归，并记录失败和跳过项。
- [ ] 实际点通用户入口、异常与恢复路径，附可复现步骤；有必要时用真实外部依赖单独验收。
- [ ] 合并最新 main 后更新总览、开发日志与验证记录，才能提交开放入口的 PR。

## 开发与验证

仅在此开发分支和隔离数据目录内将上述 manifest 的 `enabled` 改为 `true`。然后重新构建扩展并重启后端；不要只改 UI 标志。开启开关不是解决缺陷，也不是安全隔离。

在不含 `.env` / `.env.local` 的干净导出副本中，用已经安装开发依赖的 Python 执行：

```powershell
python scripts/verify_release.py --output tmp/background-verification tests/test_background_workspace.py tests/test_run_coordinator.py
npm --prefix harness_editor run package:extension
```

HTTP 产品门禁测试应分别覆盖关闭/开启状态；单测显式注入 feature manifest，不把临时打开开关误提交为发布通过。不要把这一目录中的测试成功等同于真实模型效果、平台兼容性或安全认证。

## 记录

2026-11-25：从收敛 main 创建功能分支，列出所有权与验收条件；本分支尚未增加新的功能修复。

