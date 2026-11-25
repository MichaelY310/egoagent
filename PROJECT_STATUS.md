# EgoAgent 项目状态总览

维护入口：本文件记录当前产品边界、成熟度、分支与发布门槛；[PROGRESS.md](PROGRESS.md) 只追加开发记录。
最后核对：2026-11-25。状态 **AMBER：main 已收敛为本地开发者产品；自动化回归通过，但不等于面向不可信项目的稳定发行认证**。

## 产品目标

本地可配置代码助手：在 IDE 中处理代码，用 Flow 定义执行结构、Identity 定义行为与能力；支持可审阅改动、会话管理和运行回放。不是 benchmark 平台或未经验证的无人值守自进化系统。

## 本轮执行清单

- [x] 核对 11 月 23 日审查文档、源码和隔离复现证据；原报告的谨慎结论成立。
- [x] 保存完整整合快照 `codex/archive-integrated-20261125`，保留他人的整理。
- [x] 修复凭据、Knowledge、并行继承、更新包、签名、诊断隐私边界并补回归测试；线程超时改为等待收尾，仍不具备强杀保证。
- [x] 收紧主产品导航、API 和 Flow 依赖；未完成部分默认不可进入。
- [x] 为 9 组开发功能创建独立分支，各自提交任务单，记录解除门禁的条件。
- [x] 隔离环境重跑测试、构建、启动和前端操作；记录未能覆盖的边界。
- [x] 更新 main，推送全部功能分支及集成快照，并用远端引用核对提交哈希。

## 功能与分支

完成度不用虚假的百分数：**可用**=对应机制已有实现与自动化回归；**Beta**=关键真实环境/完整用户路径未充分验证；**实验**=不能作为产品效果保证。可用不代表所有输入均无缺陷。

| 范围 | 目标 main 状态 | 开发分支/当前归属 | 合并或验收条件 |
|---|---|---|---|
| 无界面核心、模型路由、同步/流式运行 | 可用；真实供应商兼容为 Beta | main | 纯核心导出验收通过；外部模型本轮未调用 |
| 本地浏览器/Windows 桌面 IDE | Beta，源码安装 | main | 本机完整浏览器 IDE 启动通过；本轮未重做桌面与全新机器安装 |
| Flow 图/版本、Identity、工具/Skills 目录 | 可用 | main | Typed ports、循环、子 Flow、模型/工具/数据/审批/并行节点；保存/绑定回归及编辑页面实测 |
| Tab 补全、代码修改、Accept/Reject/撤销 | 可用机制，IDE 全链路 Beta | main | 单元/集成测试通过；本轮未用真实模型完成全部原生编辑器交互 |
| 项目/Session、Fork/Merge、上下文/记忆 | 可用 | main | 持久化、分叉/多会话合并、配置版本、压缩/精简的确定性回归；模型生成质量不作保证 |
| 运行可视化、轨迹、相簿/回放 | 可用 | main | 节点事件、子运行、模型输入快照、版本记录与只读回放；不保证所有外部副作用可重演 |
| 审批、workspace guard、检查点、设置 | 可用但非强隔离 | main | 明确权限与失败；任意可信 Python 仍在宿主运行；大项目检查点可能不完整 |
| 本地能力搜索、复用 | 文字搜索可用；语义搜索可选/Beta | main | SQLite 排序/用量/来源；隐藏未发布 Flow/Identity；embedding 首次下载与真实检索效果未重验 |
| Task/Evaluate/数据集与外部 runner 对照 | 隐藏 | codex/feature-evaluation | 环境创建、真实题目、评分、隔离、完整失败处理 |
| 自动进化/Agent 设计/结构优化 | 隐藏 | codex/feature-evolution | 评估实际候选，不用模拟证据批准真实修改 |
| Research/EvoCert/ARC/科学搜索/副本 | 隐藏 | codex/feature-research | 公平预算、真实验证、独立留出集；不宣称完美复刻 |
| 训练数据筛选/SFT/RL 工具链 | 隐藏 | codex/feature-training | 负反馈排除、分 agent 投影、实际框架验证 |
| 包市场/部署/更新分发 | 隐藏 | codex/feature-deployment | 可信签名、安装隔离、更新回滚、完整分发 |
| 后台持久任务与工作区交付 | 隐藏 | codex/feature-background | 大文件不误删、取消、恢复、交付冲突检测 |
| CoC 跑团 | 隐藏 | codex/feature-coc | 规则/资产一致性、多人运行与交互验收 |
| Heart Flow 专注实验 | 隐藏 | codex/feature-heartflow | 独立可移除、用户测试证明收益 |
| SSH/WSL 远程工作区 | Beta，隐藏 | codex/feature-remote | 真实平台安装、凭据/项目隔离、窗口跳转；SSH 禁用代理转发 |
| 公网检索、浏览器工具、进程/容器节点 | 可选组件/Beta | main | 不默认安装浏览器/Docker；受工作区策略限制；本轮未实机验收外网浏览器和 Docker |

完整历史功能盘点见 [11 月 23 日审查](docs/FEATURE_MATURITY_AUDIT_20261123_ZH.md)。上表覆盖产品领域；具体 Node/tool/API 清单以源码契约与目录为准，不把每个工具都当作独立产品。

## 分支与合并约定

- `main`：本地代码助手。默认 `code_agent_fast`；本次保留 19 个独立 Cookbook 阶段。历史 Session 不删除，引用关闭功能的运行不能在 main 新启动。
- `codex/archive-integrated-20261125`：整理前完整集成快照 `9b2f6d8`，仅供找回历史实现，不是推荐日常分支。
- 表中的 9 个 `codex/feature-*` 都从本次整理后的 main 建立，各有 `docs/development/<功能>.md` 任务单。未完成代码保留在 main，但由共享 `product_features/*.json` 关闭；不是复制 9 套核心实现。
- 开发分支仍默认关闭开关，避免把创建分支误当作功能已通过验收。开发时可在该分支开启所需开关并重新打包；Evolution/Research 必须同时满足 Evaluate 依赖。达标的 PR 才能在 main 开放。
- 产品门禁不是安全沙箱：受信任的开发者仍可从 Python SDK 使用底层模块。不要把它作为隔离恶意代码的权限边界。
- 每次合并同时更新本文件、`PROGRESS.md`、验证记录；写明失败/跳过项。修 bug 优先合 main 后再合回开发分支，不批量覆盖彼此变更。

本轮产品代码提交为 `8b4048c`，9 条功能分支以它为共同起点。以下任务单在对应分支，不在 main 中重复维护：
[Evaluation](https://github.com/MichaelY310/egoagent/blob/codex/feature-evaluation/docs/development/evaluation.md) ·
[Evolution](https://github.com/MichaelY310/egoagent/blob/codex/feature-evolution/docs/development/evolution.md) ·
[Research](https://github.com/MichaelY310/egoagent/blob/codex/feature-research/docs/development/research.md) ·
[Training](https://github.com/MichaelY310/egoagent/blob/codex/feature-training/docs/development/training.md) ·
[Deployment](https://github.com/MichaelY310/egoagent/blob/codex/feature-deployment/docs/development/deployment.md) ·
[Background](https://github.com/MichaelY310/egoagent/blob/codex/feature-background/docs/development/background.md) ·
[CoC](https://github.com/MichaelY310/egoagent/blob/codex/feature-coc/docs/development/coc.md) ·
[Heart Flow](https://github.com/MichaelY310/egoagent/blob/codex/feature-heartflow/docs/development/heartflow.md) ·
[Remote](https://github.com/MichaelY310/egoagent/blob/codex/feature-remote/docs/development/remote.md)。
当前各分支只新增了各自的开发/验收清单，功能实现仍与这一 main 起点相同；后续修复才在对应分支独立演进。

## 本轮验证

- 完整 Python：**915 passed / 3 skipped / 258 subtests passed**。
- 前端/扩展 Node：**133 passed**；干净 `npm ci`、TypeScript/Vite 构建通过；依赖审计 **0 vulnerabilities**（本轮时间点）。
- 删除 UI/API 的源码导出：**313 passed / 1 skipped / 37 subtests passed**；真实执行无模型 Flow 成功。
- 完整 IDE 在本机 `8880` 启动，文件树、编辑器、Chat 已连接且 Harness 列表正常；隔离 Workbench 操作检查见 [机器可读验收](docs/RELEASE_VERIFICATION_20261125.json)。
- 三个完整测试跳过项：Windows 两项 symlink 权限路径、没有指定 Docker 镜像的真实容器测试。不能计为通过。
- 本轮未调用真实付费模型，未完整重测 WebView2/SSH/WSL、所有 Tab/审阅手势、真实 browser automation/SFT/RL；不得据此写“所有功能 100% 正常”。

## 审查依据与限制

- [原始成熟度审查](docs/FEATURE_MATURITY_AUDIT_20261123_ZH.md) 与 [机器可读结果](docs/FEATURE_MATURITY_VERIFICATION_20261123.json) 是历史证据，不改写为新版本测试结果。
- 研究和实验源码可留在仓库，但 main 默认不暴露其入口；功能分支用于独立完善，并非承诺效果已完成。
- 用户凭据、Session、运行产物、依赖、第三方源码快照不提交；本机文件保留。源码及配置更新仍需检查用户已有修改。

## 下一个 7 天的维护顺序

1. 第 1–2 天：从全新用户目录验收浏览器/桌面启动、真实模型 Chat/Tab/逐块审阅；保留失败轨迹。
2. 第 3 天：在 remote 分支补 WSL/SSH 真实端到端与凭据隔离测试。
3. 第 4–5 天：先完善 Evaluate 的环境和评分契约，再允许 Evolution 使用其结果。
4. 第 6–7 天：修复后台大文件交付和训练负反馈筛选；其余分支逐项达标再合并，不以按钮存在或测试数量代替产品验收。
