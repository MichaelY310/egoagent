# Agent 包市场、分发、安装和回滚

状态：**开发中，默认关闭，未达到 main 产品验收标准**。

- 分支：`codex/feature-deployment`
- 起点：`8b4048c`（2026-11-25 main 产品收敛提交）
- 门禁：`product_features/deployment.json`
- 依赖：无其他实验功能依赖。
- 总览：[PROJECT_STATUS.md](../../PROJECT_STATUS.md)；历史证据：[成熟度审查](../FEATURE_MATURITY_AUDIT_20261123_ZH.md)。

## 所有权范围

- `agent_package.py`
- `package_registry.py`
- `product_runtime.py`
- `harness_editor/src/components/PackageMarketplace.tsx`
- `harness_editor/src/components/ProductSetupPanel.tsx`

共用 API、引擎和 UI 外壳的修改应尽量抽取通用接口，不复制核心实现。当前源码仍在 main 中受门禁保护；本分支是独立完善的工作线，不是已交付声明。

## 开放前必须完成

- [ ] 本轮已修复 required 签名验证和 Windows 路径预检；继续覆盖篡改、未知签名者和安装事务。
- [ ] 真实安装/升级/中断/回滚必须不覆盖用户数据或留下半安装状态。
- [ ] 给出完整 IDE 运行时合法来源、许可和可复现安装；当前不能仅凭 clone 宣称开箱即用。
- [ ] 明确可执行代码与权限，安装需要用户知情；市场元数据不能冒充可信签名。
- [ ] 在干净、无用户数据/凭据的副本中运行定向测试与完整回归，并记录失败和跳过项。
- [ ] 实际点通用户入口、异常与恢复路径，附可复现步骤；有必要时用真实外部依赖单独验收。
- [ ] 合并最新 main 后更新总览、开发日志与验证记录，才能提交开放入口的 PR。

## 开发与验证

仅在此开发分支和隔离数据目录内将上述 manifest 的 `enabled` 改为 `true`。然后重新构建扩展并重启后端；不要只改 UI 标志。开启开关不是解决缺陷，也不是安全隔离。

在不含 `.env` / `.env.local` 的干净导出副本中，用已经安装开发依赖的 Python 执行：

```powershell
python scripts/verify_release.py --output tmp/deployment-verification tests/test_agent_package.py tests/test_product_runtime.py tests/test_release_boundaries.py
npm --prefix harness_editor run package:extension
```

HTTP 产品门禁测试应分别覆盖关闭/开启状态；单测显式注入 feature manifest，不把临时打开开关误提交为发布通过。不要把这一目录中的测试成功等同于真实模型效果、平台兼容性或安全认证。

## 记录

2026-11-25：从收敛 main 创建功能分支，列出所有权与验收条件；本分支尚未增加新的功能修复。

