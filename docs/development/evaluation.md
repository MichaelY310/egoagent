# Task / Evaluate 与可复现评测

状态：**开发中，默认关闭，未达到 main 产品验收标准**。

- 分支：`codex/feature-evaluation`
- 起点：`8b4048c`（2026-11-25 main 产品收敛提交）
- 门禁：`product_features/evaluation.json`
- 依赖：无其他实验功能依赖
- 总览：[PROJECT_STATUS.md](../../PROJECT_STATUS.md)；历史证据：[成熟度审查](../FEATURE_MATURITY_AUDIT_20261123_ZH.md)。

## 所有权范围

- `task_bench/`
- `harness_editor/src/components/TaskBench.tsx`
- `egoagent_server/api_extensions.py`

共用 API、引擎和 UI 外壳的修改应尽量抽取通用接口，不复制核心实现。当前源码仍在 main 中受门禁保护；本分支是独立完善的工作线，不是已交付声明。

## 开放前必须完成

- [ ] 真实 task 的本地/容器环境准备、资源回收、超时和取消均有端到端证据。
- [ ] 评分器只评价实际产物；展示题目、环境、配置版本、运行轨迹、得分与失败原因。
- [ ] 原生 runner 与 EgoAgent runner 使用相同数据、预算和评估契约；不混用开发集与留出集。
- [ ] 离线 fixture 不得冒充真实 benchmark 通过；Docker 缺失时明确标为不可用。
- [ ] 在干净、无用户数据/凭据的副本中运行定向测试与完整回归，并记录失败和跳过项。
- [ ] 实际点通用户入口、异常与恢复路径，附可复现步骤；有必要时用真实外部依赖单独验收。
- [ ] 合并最新 main 后更新总览、开发日志与验证记录，才能提交开放入口的 PR。

## 开发与验证

仅在此开发分支和隔离数据目录内将上述 manifest 的 `enabled` 改为 `true`。然后重新构建扩展并重启后端；不要只改 UI 标志。开启开关不是解决缺陷，也不是安全隔离。

在不含 `.env` / `.env.local` 的干净导出副本中，用已经安装开发依赖的 Python 执行：

```powershell
python scripts/verify_release.py --output tmp/evaluation-verification tests/test_task_bench.py tests/test_task_bench_executable_fixture.py tests/test_task_datasets.py tests/test_harbor_adapter.py
npm --prefix harness_editor run package:extension
```

HTTP 产品门禁测试应分别覆盖关闭/开启状态；单测显式注入 feature manifest，不把临时打开开关误提交为发布通过。不要把这一目录中的测试成功等同于真实模型效果、平台兼容性或安全认证。

## 记录

2026-11-25：从收敛 main 创建功能分支，列出所有权与验收条件；本分支尚未增加新的功能修复。

