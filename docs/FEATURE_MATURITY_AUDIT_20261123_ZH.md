# EgoAgent 功能地图与成熟度审查

**审查日期：2026-11-23｜对象：当前工作树，而不是仅 HEAD｜结论：开发者预览版，有实质实现，但不宜按稳定通用产品发布。**

## 1. 执行结论

- **总体健康：AMBER。** 核心功能不只是原型 UI：运行时、编辑审阅、Flow、Session、轨迹与评测已形成可测试链路；但安全授权、并行上下文、部分进化评估和分发仍有实质缺口。
- **面向不可信内容／普通用户的稳定公开发行：RED。** 本次受控验证发现更新包目录逃逸、Knowledge 环境变量授权缺口、Anthropic 适配器凭证覆盖、并行分支策略继承丢失及签名要求未实际强制验证等问题。在修复前不建议开放不可信能力包、更新包或无人值守运行。
- **可以给谁用：** 了解模型和本机权限、使用可信项目／可信能力、能检查日志和审阅改动的开发者。前提是先规避本报告的高影响路径；本报告不是对整个应用的安全背书。
- **不应宣称：** 开箱即用完整 IDE、强 OS 沙箱、任意节点无损热替换、全部副作用 exactly-once、通用自进化稳定增益、完整官方 benchmark 成绩或全面训练框架兼容。
- 不给“完成度 90%”之类数字：当前不同模块的实现成熟度、真实模型效果、安装交付和安全性差异很大，单一百分比会掩盖问题。

### 推荐的产品边界

| 产品层 | 建议定位 |
|---|---|
| 本机基础 Code Agent、Flow 编辑、Session、可审阅文件修改 | 受控开发者预览；以简单、单工作流路径为主 |
| 自动补全、词法能力目录、源码工具目录、离线 Flow、轨迹记录/回放 | 较成熟的组件；可供可信本地开发者使用 |
| 多角色并行、后台持久任务、远程工作区、浏览器与容器 | Beta；权限继承问题修复前限制并行自动操作 |
| Legacy Evolution、V2 structural、EvoCert、ARC/AVO、副本 Flow、Heart Flow | 显式 Experimental；不得把结构通过或演示评分当作真实收益证据 |
| 完整 IDE 一键分发、跨平台桌面、自包含安装包、全局强隔离 | 尚未交付或未建立相应保证 |

## 2. 优先阅读的开发记录

本次首先阅读了维护日志，而不是从旧设计稿推断现状。

| 文件 | 用途／阅读顺序 | 注意事项 |
|---|---|---|
| `PROGRESS.md:1` | **当前维护的开发日志，首选**；2026-11-23 条目记录分层、Cookbook、工具入口、连接修复 | 审查开始时最新“发布验证”仍未填写；本次新增的是独立审查记录，不是发布批准 |
| `docs/DEVELOPMENT_STATUS_20260930.md:1` | 上次发布检查，对应 `de0252a` | 777 Python / 71 Node 等属于历史，不是本轮结果 |
| `README.md:1` | 当前用户入口、安装、支持范围与明确限制 | 已明确 developer preview 和 Void runtime 分发缺口 |
| `docs/REPOSITORY_GUIDE.md:1` | 第一方源码、生成物、运行态和实验的归属地图 | 后端实现应读 `egoagent_core/`、`egoagent_server/`，不要只看兼容别名 |
| `ARCHITECTURE.md:1` | 架构契约与运行时数据流 | 个别旧路径文字仍称 `harness_editor/server.py`，当前实际实现已迁至 server 包 |
| `docs/EGOAGENT_FEATURE_AND_PARITY_AUDIT_20260908_ZH.md` | 历史功能／对标审计 | 不是当前版本的逐项复验 |
| `docs/EGOAGENT_UNIFIED_PRODUCT_RESEARCH_AUDIT_20260830_ZH.md` | 产品能力与研究能力边界 | 与最新实现对照使用 |
| `docs/CODE_AGENT_PRODUCT_ACCEPTANCE_PLAN_20260904_ZH.md:79` | 历史真实模型验收、失败记录与消融局限 | 有学习成本高于基线、复用获益、样本量不足等重要反例；不能只摘成功结果 |
| `docs/VIDEO_FEATURE_VERIFICATION_MATRIX.md:1` | 录制验收矩阵与历史运行证据 | 日期为 2026-08-24，里面模板数和 UI 导航不是当前完整清单 |
| `docs/EVOCERT_PILOT_RESULT_AND_NOVELTY_AUDIT_20260902.md` | EvoCert 结果可信度／新颖性反思 | 区分 advertised、activated、真的执行，以及 protected baseline 是否有效 |
| `docs/AUTOCOMPLETE_ZH.md:57` | 历史补全真实模型与 Tab/Esc/撤销验收 | 本轮未重复真实 IDE 人工操作 |

旧 `PROGRESS.md` 的 Early V2 “Completed”清单保留了早期状态，**不能用它判断今天哪些页面还返回占位数据**。本报告以当前代码及本轮验证为准。

## 3. 范围、方法与证据分层

### 3.1 实际检查范围

- 工作目录：`C:/Users/aa310/Desktop/egoagent`。
- HEAD 为 `de0252a`，当前工作树含大量分层及产品改动；本次检查**磁盘上的当前文件**，不是旧提交快照。
- 检查第一方 runtime、core、server、Workbench、Void 集成、能力／安全／部署、Task／数据／进化／实验入口，并把测试与文档交叉核对。
- 源码隔离副本包含 1,302 个经路径筛选的文件；原文件和副本的 SHA-256 在测试结束后均与初始 manifest 一致。未复制 `.env.local`、用户 Session、原始实验 runs/results 或旧进化数据。
- 未将 `void-web/` 上游 IDE、`meilisearch/` 上游源码、`.venv/`、依赖、缓存、生成 bundle 和私人运行数据逐行审计。扩展生成 UI 的源码来源是 `harness_editor/src/`。
- **不是每个工具、每个实验、每条 API 的逐行安全审计。** 完成的是全项目功能分层盘点与关键链路深入检查；Port Graph 深层恢复、完整 CDP、所有 CoC 规则、大型训练及全部实验算法未穷尽。

### 3.2 当前规模

| 项目 | 当前核对结果 | 正确解释 |
|---|---:|---|
| 顶层 `harness/*/config.json` | 135 | 不含 `.versions`；包含内部 worker、组件与实验，不是 135 个用户可见成品 |
| 默认 Flow 列表 API | 74 | 公开选择目录；详细目录返回 135 |
| 注册 canonical 节点 | 28 | 27 个默认 palette 项；“结束”不在默认 palette，别名不重复计数 |
| Cookbook | 24 | 递进机制示例，不是 24 种算法效果已获验证 |
| Identity 列表 API | 52 | 角色配置数量，不等于 52 个独立完善产品 |
| Python 测试文件 | 105 | `tests/test_*.py` |
| Node 测试文件 | 14 | `tests/*.test.cjs` |

节点注册见 `node_registry.py:74`。当前类别包括：输入、Agent、工具审查、文本处理、工具、进程、工作区、Python、模型、上下文、记忆、能力、条件、数据、保存／读取数据、循环、并行、映射、合并、审批、子流程、检查点、流程变体、搜索控制、循环守卫、输出、结束。

### 3.3 评级

- **A｜局部可用**：实现及确定性验证较扎实，适合可信本地开发者；不是整套产品的稳定／安全认证。
- **B｜Beta**：主链路可工作，但兼容、异常恢复、并发、交互或真实环境验证仍有缺口。
- **E｜Experimental**：研究／演示路径，或当前关键保证不成立。可以用于受控实验，不应用于稳定效果承诺。
- **M｜未交付**：指定交付形式或保证缺失；不代表相关模块全部没有代码。

“测试文件存在”“本轮自动测试通过”“本轮真实用户流程通过”是不同证据。下表测试列给出回归入口；不能把某测试模块全部通过解释为该子功能所有边界已覆盖。

## 4. 本轮实测结果

| 检查 | 本轮结果 | 范围与限制 |
|---|---|---|
| 隔离副本 Python 完整 `tests/` | **888 passed，3 skipped，258 subtests passed；283.28 秒** | Python 3.13.1、pytest 9.1.1；禁用 embeddings、清除模型凭据；Python 外联 socket 防护未触发外联尝试 |
| Node 原生 Chat／Workbench 契约测试 | **126 passed，0 failed，0 skipped** | Node 24.22.0；部分为 VM／伪 DOM 或源码契约，不是完整浏览器 E2E |
| TypeScript + Vite | **通过，247 modules，Vite 构建约 4.62 秒** | 复用当前 node_modules；`tsc --project tsconfig.json --noEmit`，Vite 输出到独立临时目录；不是全新 `npm ci` 验收 |
| Flow 目录结构、子 Flow、角色与组件输入输出 | **135 / 135 通过** | `scripts/audit_harness_catalog.py`；仅结构／依赖检查，不调用真实模型 |
| 独立 Workbench HTTP 冒烟 | **首页 + 6 静态资源 + 5 只读 API 全部 200** | fresh source export、临时随机 loopback 端口；未启动完整 IDE、durable worker 或真实模型 |
| Core separation / 导出 / 无 UI API | **随完整套件通过；定向 28 项也通过** | 无模型 Flow 实际执行；未另做全新机器安装或独立 wheel 验收 |
| 安全与运行时边界补充复现 | **确认 7 个机制问题，见第 6 节** | 假密钥、假日志、临时目录／文件、无外发请求，不读用户真实密钥 |

HTTP 只读端点：`/api/harnesses`、`/api/harnesses/detailed`、`/api/dag/contracts`、`/api/identities`、`/v1/models`。没有执行会触发模型的 Session evaluate GET。

**必须保留的失败历史：**

1. Python 首轮：883 passed、5 failed、3 skipped，另 258 subtests。两项 export 测试失败是本审查副本缺少独立 Git 索引，非产品缺陷；补上副本索引后通过。
2. 另外三项在 `egoagent_core/change_tracker.py:1186` 的 `os.replace` 出现 Windows `PermissionError [WinError 5]`，涉及后台 handoff teardown、二进制审阅和空新文件审阅。定向 28 项、随后完整套件均通过；**根因未定，按偶发可靠性风险保留，不能删掉首次失败记录**。
3. Node 首次调用工作目录不正确，且隔离副本没有 node_modules，出现 ENOENT／MODULE_NOT_FOUND；在正确项目根目录复跑只读测试后 126 项全过。这不是产品逻辑失败。
4. 3 个 Python 跳过项：Harbor symlink、权限 symlink（Windows 无创建权限），真实容器测试（未配置显式本地镜像）。**不代表符号链接安全或真实 Docker 已验证。**

未执行：真实收费模型任务、完整 Void/WebView2 逐按钮验收、真实 SSH/WSL、GPU／训练、大规模 benchmark、外部供应商故障注入、Windows/Linux 全新安装矩阵。部分 Python 测试会启动本地 fixture、浏览器／子进程；这仍不是完整用户工作流验收。

## 5. 功能地图：大板块 → 子功能 → 实现 → 完善度

代码定位相对项目根目录，行号对应审查时文件。

### 5.1 Code IDE 与交互

| 子功能 | 等级 | 代码位置 | 验证入口／critical 判断 |
|---|---|---|---|
| Workbench 导航、页面恢复、IDE 桥接 | B | `harness_editor/src/App.tsx:127`；`harness_editor/src/ideBridge.ts:42` | `workbench_restore.test.cjs`、`test_void_workbench_integration.py`；独立网页不具有完整 IDE 文件／编辑器能力 |
| 流式 Chat、工具过程、审批卡、重连对账 | B | `void_extension/egoagent-dag-chat/media/chat.js:877`、`:1330`；`egoagent_server/server.py:3523` | `chat_delivery.test.cjs`、`test_chat_progress_runtime.py`；有 run/workspace/version 隔离；后端重启保留历史不等于自动无损续跑 |
| 同项目多 Live Session、逐轮配置 | B | `void_extension/egoagent-dag-chat/media/chat.js:1518`；`egoagent_server/server.py:3570` | `test_interactive_runs.py`、`test_session_configuration_history.py`、`chat_saved_flow.test.cjs`；新配置通常重建运行，不热改任意节点 |
| Markdown、表格、代码块与安全链接渲染 | A | `void_extension/egoagent-dag-chat/media/markdown.js`；`tests/chat_markdown.test.cjs:90` | `chat_markdown.test.cjs`；原始 HTML 转义、危险协议限制、远程图片不自动请求；不是任意富文本插件支持 |
| 文件／选区／终端结构化附件 | B | `void_extension/egoagent-dag-chat/extension-v21.js:1464`、`:2801`；`void_extension/egoagent-dag-chat/media/chat.js:964` | `chat_context_drop.test.cjs`、`chat_workspace.test.cjs`；终端选区经剪贴板获取，不是完整终端状态／退出码；附件有长度限制 |
| 项目索引与上下文预算规划 | B | `egoagent_core/context_engine.py:408`、`:530` | `test_context_engine.py`、`test_context_engine_api.py`；lexical + hashed-subword，不等于外部语义 RAG；cached_only 冷启动与超预算整项排除需提示 |
| Tab 灰字补全、取消、缓存、敏感文件过滤 | A | `void_extension/egoagent-dag-chat/completion.js:67`；`egoagent_core/ai_service.py:237` | `autocomplete.test.cjs`、`test_ai_service.py`；历史有真实交互证据，本轮仅回归；客户端取消不保证供应商停止计费 |
| Inline Edit、预览追问与应用 | B | `void_extension/egoagent-dag-chat/extension-v21.js:2650`；`egoagent_server/server.py:3942` | `test_change_review_api.py:168`；有 stale 检测；AI 失败的规则降级不能冒充模型成功 |
| 逐 hunk Accept／Refuse／Undo | B | `egoagent_core/change_tracker.py:568`；`harness_editor/src/components/ChangeDashboard.tsx:82` | `test_change_tracker.py`、`test_change_review_api.py`；**文件先写入，Accept 记决定，Refuse 恢复，Undo 撤销决定**；不是 Agent 写入前的事务隔离；另有 bulk accept 误报问题 |
| 文件检查点、预览与选择性恢复 | B | `egoagent_core/checkpoint_manager.py:113`；`harness_editor/src/components/CheckpointDashboard.tsx:101` | `test_checkpoint_manager.py`；不是整机／网络／外部工具状态快照，用户须给出文件范围 |

### 5.2 Flow 建模与核心运行时

| 子功能 | 等级 | 代码位置 | 验证入口／critical 判断 |
|---|---|---|---|
| Headless SDK／CLI、核心与 UI 分层 | A | `egoagent_core/__init__.py:8`；`egoagent_core/__main__.py:1`；`scripts/export_core.py:60` | `test_core_separation.py:18`；实际无 UI Flow 能跑；仍需根模块和资源，不是独立 wheel |
| Identity 插槽、Harness、循环会话与恢复 | A | `harness.py:566`、`:681` | `test_cookbook.py:145`、`test_session_configuration_history.py`；可信 Python hooks 可执行；恢复会话不等于恢复所有外部副作用 |
| 单一节点注册、别名、表达式与图校验 | A | `node_registry.py:74`；`pipeline_schema.py:309`、`:391` | `test_node_registry.py`、`test_dag_contracts.py`；28 类节点，结构检查不等于完整静态类型系统 |
| 图编辑、端口、版本、布局、撤销重做 | B | `harness_editor/src/App.tsx:520`、`:1560`；`harness_editor/src/components/Sidebar.tsx:13`；`port_graph.py` | `test_port_graph.py`、`test_harness_versions.py`；可保存可执行配置，不只是画图；Port Graph 深层故障恢复未逐行穷尽 |
| Build 独立试跑、暂停／单步／跳过／改输入／重试 | B | `interactive_execution_service.py:141`；`harness_editor/src/App.tsx:1975` | `test_interactive_execution_service.py`；关联 Chat 的观察模式只读；暂停／停止是合作式，不是任意代码强停 |
| Agent 流式单步、工具协议与结构化输出 | B | `agent.py:1253`；`pipeline_engine.py:1820`；`pipeline_schema.py:317` | `test_pipeline_runtime.py`、`test_custom_llm_text_tool_fallback.py`；JSON Schema 是子集；think 标签跨分片仍有缺口 |
| 模型适配、路由、Fallback、SSE 重试 | B | `llm/providers.py:49`；`llm/custom_llm.py:217`、`:455`；`egoagent_core/model_router.py:265` | `test_provider_conformance.py`、`test_model_router.py`；本地假服务不证明所有供应商兼容；Anthropic 凭证分支需修 |
| Loop / Parallel / Map / Join / Reducer | B，修复前限制高权限并行 | `pipeline_engine.py:6466`、`:6524`、`:6597` | `test_pipeline_runtime.py:2485`、`test_cookbook_advanced.py:100`；真线程并发有实现，但策略继承、fail_fast、全树预算不够可靠 |
| 子 Flow、角色映射、共享／隔离 Session | B | `pipeline_engine.py:6812` | `test_dag_components.py`、`test_cookbook.py:136`；有深度与节点限制；动态子图不是自动受可信执行沙箱保护 |
| 数据状态、文件 JSON、AgentBus | B | `pipeline_engine.py:5055`、`:6440`；`agent_bus.py` | `test_agent_bus.py`、`test_pipeline_runtime.py`；常规文件读改写不能假设并发无丢失；数据节点持久副作用漏标 |
| 上下文精简／压力压缩／结果裁剪 | B | `context_policy.py:353`、`:450`、`:650` | `test_context_policy.py`、`test_cookbook.py:185`；保留完整 audit，失败可保守恢复；摘要语义无损及省钱不是保证 |
| 重试、超时、取消、预算与循环守卫 | B | `pipeline_engine.py:1693`、`:1764`、`:7819`；`loop_guard.py` | `test_approval_waits.py`、`test_pipeline_runtime.py`；超时后的非合作线程仍能产生副作用，重试不自动回滚；预算可事后超额 |
| 检查点与 durable Queue／lease／heartbeat | B | `pipeline_engine.py:1247`、`:1493`；`run_coordinator.py:120`、`:723` | `test_checkpoint_recovery.py`、`test_run_coordinator.py`；本地 SQLite 实现扎实，但不是分布式 exactly-once，崩溃窗口和外部副作用仍需人工确认 |
| 24 Cookbook、Auto/Fast/Long/Team 组合 | B（机制）；E（普适效果） | `harness/cookbook_*/config.json`；`harness/code_agent_*/config.json`；`harness_editor/src/cookbookCatalog.json` | `test_cookbook.py`、`test_cookbook_advanced.py`、`test_product_code_agent_flows.py`；多为 scripted model，不能按模板数量宣传成功率 |

### 5.3 Identity、工具、能力与知识

| 子功能 | 等级 | 代码位置 | 验证入口／critical 判断 |
|---|---|---|---|
| Identity 创建／克隆／模型字段／Ego／Superego | B | `harness_editor/src/components/IdentityManager.tsx:85`；`egoagent_core/agent_creator.py`；`governance.py` | `identity_editor.test.cjs`、`test_agent_creator.py`、`test_superego_governance.py`；行为提示和治理配置不等于 OS 安全边界 |
| Capability Pack 与 Environment 继承组合 | B | `environment.py:89`、`:209`；`agent.py:326`；`capability_registry.py:513` | `test_identity_composition.py`；工具代码属于可信扩展，名字覆盖与来源需清楚展示 |
| SQLite／FTS／中文词法能力目录 | A | `capability_registry.py:446`、`:600`、`:922`、`:1209` | `test_capability_registry.py`；工作区隔离与真实使用计数有覆盖；不依赖 Meilisearch 服务 |
| 语义／混合能力检索和 embedding 缓存 | B | `capability_registry.py:791`；`semantic_embeddings.py:145` | `test_capability_registry.py:229`；远程 embeddings 或本地 FastEmbed 需额外依赖／首次下载；与 context_engine 的 hashed-subword 不是同一实现 |
| 工具与 Skills 源码目录、Identity 启动选择 | A | `egoagent_core/tool_library.py:45`、`:171`、`:195`；`harness_editor/src/components/ToolLibrary.tsx` | `test_tool_library.py`、`tool_library_ui.test.cjs`；静态解析不执行代码，保存检测版本冲突；选择列表不是安全白名单 |
| 渐进发现、激活、说明型 Skill | B | `agent.py:656`、`:681` | `test_capability_registry.py:133`；同名激活可替换来源，Identity/Harness 卡片不等于已执行；需区分发现、加载、调用 |
| 可执行 Skill 创建、Schema／签名校验、引用摘要 | B | `capability_authoring.py:77`、`:142`；`capability_reference.py:29`、`:146` | `test_capability_authoring.py`、`test_capability_references.py`；函数签名校验是接口检查，不是包信任签名或代码安全证明 |
| Knowledge 加载／模板／激活 | E，修复后再升级 | `environment.py:14`、`:168`；`agent.py:721`、`:2019` | 未授权 env 渲染已受控复现；目录可检索 Markdown／独立文本，但激活器要求目录+meta.json+txt，格式契约不一致 |
| 网络搜索／抓取／来源编号 | B | `web_access.py:70`、`:217`、`:308` | `test_web_access.py`；有公开目标检查和输出预算；搜索摘要不等于已读正文，DNS 检查不等于连接 IP 钉扎 |
| CDP 浏览器、截图／下载／人类接管 | B | `identity/browser_operator/ego/skills/browser/scripts/browser.py:50`、`:642`、`:848`、`:894` | `test_browser_ego.py`；真实浏览器依赖与长期状态管理需单独验收，不是随核心安装即全可用 |
| AGENTS／项目规则、跨 Session 记忆 | B | `egoagent_core/project_rules.py:84`、`:191`；`pipeline_engine.py` Memory 节点 | `test_project_rules.py`、`test_context_policy.py`；项目记忆搜索与 Flow Memory 是不同层；规则有截断，长期记忆质量不能仅以落盘证明 |

### 5.4 项目、Session、后台任务与观察

| 子功能 | 等级 | 代码位置 | 验证入口／critical 判断 |
|---|---|---|---|
| Project Portfolio、归属／标题／置顶／归档 | B | `project_portfolio.py:158`；`harness_editor/src/components/SessionExplorer.tsx:109` | `test_project_portfolio.py`、`test_project_portfolio_api.py`；本地管理完整度较高，未实现多设备同步 |
| Session 列表／历史／分析／trash | B | `harness_editor/src/components/SessionExplorer.tsx:171`；`egoagent_server/server.py` Session 路由 | `test_session_configuration_history.py`；快速切换存在过期响应覆盖，见第 6 节；分析可能调用模型 |
| Fork / Direct / Summary / Dialogue Merge | B | `session_branching.py:347`、`:492`；`harness_editor/src/components/SessionBranchDialog.tsx:62` | `test_session_branching.py`、`test_session_branching_api.py`；合并对话与 lineage，**不是 Git／文件系统分支合并**；摘要依赖模型 |
| Background 隔离副本／handoff／变更复核 | B | `egoagent_core/background_workspace.py:28`、`:50`、`:129`；`harness_editor/src/components/BackgroundRuns.tsx:89` | `test_background_workspace.py`；目录复制不是沙箱；>20 MiB 文件省略可能误判为删除，且首次 Windows 日志 replace 曾失败 |
| 每 run 输入、调试与单次审批隔离 | B | `interactive_runs.py:58`、`:94`；`interactive_execution_service.py:141` | `test_interactive_runs.py`、`test_run_context_isolation.py`；live control 为内存状态，不等于持久队列；调用方应带准确 run_id |
| Chat／Task 统一图观察、父子运行、录制相簿 | A（记录服务）；B（UI） | `flow_observation.py:26`、`:75`、`:188`；`harness_editor/src/components/FlowRunViewer.tsx:106` | `test_flow_observation.py`；录制边界固定，活动图与库编辑区分；长期大库容量未验证 |
| 只读回放、节点 I/O、运行过滤 | A（机制）；B（UI） | `flow_observation.py:126`；`harness_editor/src/components/TrajectoryReplay.tsx:105` | `test_flow_observation.py`、`test_trajectory.py`；回放不重新执行外部动作；轨迹 UI 存在同类加载竞态 |
| 精确轨迹、模型／工具配对、能力 snapshot、hash | A（可信本地记录） | `trajectory.py:222`、`:339`、`:428`、`:508` | `test_trajectory.py`；有完整性检查，不是可信第三方签名；flush 不等于断电 fsync 保证，跨进程同文件写入未认证 |

### 5.5 Task Bench、评测和训练数据

| 子功能 | 等级 | 代码位置 | 验证入口／critical 判断 |
|---|---|---|---|
| Task spec、fixture 物化、独立目录 | B | `task_bench/engine.py:165`、`:573`、`:642` | `test_task_bench.py`、`test_task_bench_executable_fixture.py`；真文件／命令检查有覆盖，独立目录不是强隔离 |
| 确定性 evaluator、运行比较、checkpoint 恢复 | B | `task_bench/engine.py:306`、`:338`、`:1789`、`:1884` | `test_task_bench.py:240`、`:418`；题目评分规则本身需有效，不能把流程事件齐全等同于任务解决 |
| JSON／JSONL／CSV 数据集映射 | B | `task_bench/datasets.py:75`、`:131`、`:191` | `test_task_datasets.py`；本轮未逐段深审全部物化分支，不承诺任意 Schema／超大多模态数据 |
| 原版 Codex CLI runner 与 Ego Flow 比较 | B | `task_bench/engine.py:1287`、`:1426` | `test_task_bench.py:123`、`:316`；外部 CLI 安装、认证及真实模型需独立验收，不是内部 replica 等价原产品 |
| Harbor／Terminal-Bench 导入与 verifier 接线 | B | `task_bench/harbor_adapter.py:72`、`:134`、`:150`、`:224` | `test_harbor_adapter.py`；真实 Docker 本轮跳过，不能宣称全官方 benchmark 端到端覆盖 |
| 精确调用导出 SFT／VERL／episode／OTel | B | `trajectory.py:954`、`:1117` | `test_trajectory.py`；有源 hash 和模型调用投影；历史 tiny 单步训练不等于当前大规模框架兼容 |
| 人工反馈、筛选、DPO／KTO 数据投影 | B | `training_data.py:100`、`:319`；`harness_editor/src/components/TrainingDataControls.tsx` | `test_training_data.py`、`test_training_data_api.py`；会话整体正标与局部负标冲突过滤不足，见第 6 节 |
| GPU／分布式 RL／多模态真实工具 rollout | E / M（完整交付） | `scripts/prepare_verl_trajectory.py`；`docs/TRAJECTORY_TRAINING_VALIDATION.md` | 有适配脚本与历史限定验证，未建立当前全版本／设备矩阵，不能作为稳定训练平台销售 |

### 5.6 自进化、候选治理与研究

| 子功能 | 等级 | 代码位置 | 验证入口／critical 判断 |
|---|---|---|---|
| Blueprint／EgoIR 编译、patch、revision 与回滚 | B | `ego_ir.py:119`、`:535`；`harness_blueprint.py:162`、`:599` | `test_ego_ir.py`、`test_harness_blueprint.py`；结构与事务设施，不是修改方案正确或更优的证明；跨写入者锁仍需强化 |
| Typed Flow variant、声明 mutation surface、证据引用 | B | `flow_variants.py:29`、`:178` | `test_flow_variants.py`；remove-and-bypass 会改声明范围外的父边，需修；测量引用不自动建立因果可信度 |
| Code Agent 能力创建／独立验证／隔离失败产物／热加载 | B（机制）；E（普适收益） | `harness/product_adaptive_code_agent/config.json`；`self_evolution/capability_evolution.py:177`；`docs/CODE_AGENT_PRODUCT_ACCEPTANCE_PLAN_20260904_ZH.md:69` | `test_product_code_agent_flows.py`、`test_capability_evolution.py`；历史有真实复用与负收益实例；“同轮工具加载”不是“任意节点无损热替换” |
| 默认 Legacy Evolution 面板 | E | `harness_editor/src/components/EvolutionPanel.tsx:61`；`egoagent_server/server.py:3877`；`self_evolution/engine.py:380` | **评分只走 Identity 文本问答+LLM judge，不执行选中 Harness／新增工具**；不能证明结构／能力进化效果 |
| V2 structural 模式 | E | `egoagent_server/server.py:4604`、`:4648`、`:4674` | 产品入口动态导入实验实现，使用模拟 failure info；结构校验后写真实 Harness，未有真实任务收益 gate |
| Proof Evolution／EvoCert／证据晋级 | E | `self_evolution/proof_evolution.py:403`、`:496`、`:572`；`self_evolution/evolution_certificate.py:112` | `test_proof_evolution.py`、`test_evolution_certificate.py`；治理格式与 adapter 可用，外部输入测量与实验设计可信度仍待证明 |
| 开源 Agent replica／SWE smoke／研究脚本 | E | `harness/*_replica/config.json`；`experiments/real_swebench/run_flask_5014.py`；`research/` | `test_harness_replicas.py` 等；图契约相似不代表原产品功能／成绩等价；单真实 issue smoke 不是官方 SWE-bench 分数 |
| ARC-AGI-3／AVO 适配 | E | `arc_agi3_runtime.py:265`、`:313`、`:394` | `test_arc_agi3_runtime.py`；官方 SDK 接线与动作校验存在；历史主指标未提升、候选未晋升，不能称复现论文成绩 |
| Heart Flow 注意力续接 | E | `heart_flow/service.py:120`、`:213`、`:253` | `test_heart_flow.py`、`test_heart_flow_api.py`；capsule／focus／通知有实现，降低用户切换成本尚无本项目用户研究支持 |
| CoC／Tabletop 规则与角色事务 | E | `tabletop/coc7.py:45`、`:277`；`tabletop/coc_identity.py:269` | `test_coc7_runtime.py`；确定规则和批量事务不等于完整规则／剧本系统，完整领域覆盖未验收 |

### 5.7 安全、部署、发布与运维

| 子功能 | 等级 | 代码位置 | 验证入口／critical 判断 |
|---|---|---|---|
| 文件 Workspace Guard、模式与权限评估 | B | `permissions.py:155`、`:333`、`:498`、`:579` | `test_permissions.py`、`test_security_hardening.py`；内建路径检查有效但不能约束任意 Python 插件；并行继承缺口需先修 |
| Secret 授权、环境收缩、结果脱敏 | B，含高影响缺口 | `llm/env_config.py:16`；`agent.py:2060`；`product_runtime.py:192` | `test_llm_connection_config.py`、`test_security_hardening.py`；Knowledge 绕读与 Anthropic 覆盖使“所有服务密钥来源一致受控”不成立 |
| 宿主 Process／Docker-Podman 后端 | B | `process_backends.py:45`、`:103`、`:191` | `test_process_backends.py`；有无网络／资源限制／只读根等默认值；只包选定进程，不包全部 Tool，挂载仍影响宿主 |
| Local HTTP／WebSocket／远程 token | B | `local_api_security.py:20`、`:97`；`egoagent_server/server.py:1353` | `test_security_api.py`、`test_remote_workspaces.py`；默认 loopback，但 Origin 不是多用户认证；不能直接暴露公网 |
| SSH／WSL 打包、隧道、目标依赖 | B | `remote_workspaces.py:45`、`:151`、`:264`、`:325` | `test_remote_workspaces.py`；目标 Linux/认证/模型依赖需预配置，未做本轮实机；未显式禁用继承的 SSH ForwardAgent |
| Windows 浏览器启动器／桌面壳／服务复用 | B | `desktop/bootstrap.py:111`；`desktop/browser_launcher.py:43`；`desktop/DesktopApp.cs` | `test_browser_launcher.py`、`test_desktop_launcher.py`；已有运行时下可用，不是自包含安装包；本轮未重新安装或完整壳 UI 验收 |
| Provider 设置、网络代理、offline | B | `product_runtime.py:75`、`:94`、`:222` | `test_product_runtime.py`；offline 主要约束 router，embedding 仍可能远程／下载，不是系统断网模式 |
| 诊断包、手动更新与回滚 | E，修复前限制 | `product_runtime.py:281`、`:305`、`:315`、`:395` | `test_product_runtime.py`；已复现默认 prompt 排除开关无效、Windows ZIP 盘符路径逃逸 |
| Agent Package／本地 registry／依赖安装 | B；信任声明 E | `agent_package.py:176`、`:215`、`:278`；`package_registry.py:190`、`:212` | `test_agent_package.py`；有内容校验、单包备份、卸载冲突；require_signature 不保证 verified，整组依赖非原子／非全局版本求解 |
| 完整 IDE 一键获取／独立发行／跨平台桌面 | M | `README.md:41`、`:67`、`:92`；`desktop/bootstrap.py:127` | Void Web 运行时未随源码提供且无验证的一键安装；不能把本开发机可启动等同新用户可安装 |

**主导航核对：** Home、Build、Identity、工具与 Skills、Evaluate、运行相簿、Library、Improve、More；高级页包含 Deploy、EgoIR、Research、CoC Table、Background、Agent Changes、Checkpoints、Environment、Sessions、Heart Flow、Settings。有入口不等于已完成对应领域能力。

## 6. 已核实的关键问题与发布影响

### 6.1 受控运行已确认（未修复）

全部复现在 `tmp/feature-audit-20261123/` 内，使用假数据；未执行外部攻击、未读真实密钥、未向外部服务器发送请求。

| 优先级 | 问题／触发条件 | 观察结果 | 代码与建议 |
|---|---|---|---|
| P1 | **Parallel 丢失父显式权限策略与上下文**：外层 `RuntimePolicy(mode='chat')`，普通 ThreadPool 分支 | 分支 mode 变成 `agent`，policy 非同一对象，无 parent、无 approval callback | `pipeline_engine.py:6543`、`:6574`、`:1161`；显式传入策略、审批、secret/deadline/parent 或正确复制 context，并加跨线程安全回归。当前不应给并行路径安全继承保证 |
| P1 | **Knowledge 直接读未授权 env**：模板引用虚构变量，SecretView 为空授权名单 | 模板返回假值，SecretView 未脱敏 | `environment.py:14`；`agent.py:2019`、`:2060`；`llm/env_config.py:41`。模板必须走授权 resolver；缺失授权 fail closed；覆盖模型上下文与轨迹两条输出链 |
| P1 | **Anthropic 凭证覆盖**：自定义端点+显式 key，同时环境存在虚构 `ANTHROPIC_API_KEY` | 构造后使用全局假 key，`x-api-key` 也使用它；无网络请求 | `llm/providers.py:60` 与 `llm/connection_config.py:44`；避免绕过统一解析，明确 env/inline/origin 优先级；加不向其他来源附带全局 key 的测试 |
| P1 | **Windows 更新路径逃逸**：主动导入含盘符绝对路径的 ZIP | 写入模拟安装根以外的临时 marker；仍完全在审查目录 | `product_runtime.py:305`、`:342`；拒绝 drive/UNC/绝对路径，resolve 后确保 root containment，同时防父 symlink。此问题需用户导入更新包，不是无交互远程漏洞 |
| P1 | **required signature 并未要求验证成功**：合法格式、假 key 签名包，`require_signature=True`，不提供 trusted key | `inspect_package` 成功返回 `present-unverified` | `agent_package.py:241`；`package_registry.py:217`；强制签名时必须有可用信任根且状态为 verified；本次只 inspect，未安装 dummy 包 |
| P2 | **通用节点超时后仍执行副作用**：非合作函数等待 timeout 后释放 | 调用已抛 NodeTimeout，原线程随后仍写临时文件 | `pipeline_engine.py:7819`、`:1774`；不能直接对未知副作用函数自动重试；采用隔离进程或等待终止确认。此项不否定 Process 节点另有进程树清理 |
| P2 | **诊断 prompt 开关无效**：默认 `include_prompts_in_diagnostics=False`，合成日志包含假 prompt | ZIP 仍包含假 prompt；系统诊断探针被 mock，只测真实打包分支 | `product_runtime.py:58`、`:291`；实现结构化日志字段过滤或默认排除含 prompt 日志。没有自动上传，不应说已发生实际数据外传 |

### 6.2 源码控制流／数据流确认（未额外动态复现）

1. **Legacy Evolution 评估对象不符（P1，产品可信度）。**
   - `EvolutionPanel.tsx:61` 默认 engine；`egoagent_server/server.py:3882` 缺省也为 engine，`:3901` 调用旧循环。
   - `self_evolution/engine.py:380–437` 不使用传入 Harness，不创建 Agent、不执行工具，仅 Identity 描述问答+LLM 评分；后续却可安装能力并按该分数保留／回滚。
   - 修正：清楚标为 prompt-only experiment，或用真正 Task runner 的 matched baseline/candidate + held-out 评价。不能与新 Code Agent 工具验证路径混为一谈。

2. **V2 structural 使用模拟失败信息并提交真实图（P1，产品语义）。**
   - `egoagent_server/server.py:4604` 导入 `experiments/self_repair`；`:4648` 明确 simulated failure info；`:4674` 结构校验后提交真实 Harness。
   - 缺少真实任务 baseline、candidate、收益拒绝门；事务 revision 与结构有效不能代替能力改善证据。移除实验目录会使此产品模式失效。

3. **“数据”节点漏标持久副作用（P1，恢复边界）。**
   - `node_registry.py:88` 未 side_effecting；`pipeline_engine.py:5062`、`:5084` 能进行 AgentBus 和 file state 修改；`:1493` 的执行前 in_flight 保护只覆盖已标记类型。
   - 不能宣称所有副作用在崩溃恢复时均已保护；应按 action 分类或保守标记并做崩溃窗口测试。

4. **Flow variant 越过 mutation surface（P2）。** `flow_variants.py:222–238` 删除 B 只检查 B 的路径，却重写所有父节点指向 B 的边；应把父边也纳入授权验证与 audit。
5. **Session／Trajectory 快速切换的过期响应覆盖（P2）。** `SessionExplorer.tsx:171–195`、`TrajectoryReplay.tsx:105–124` 没有 request generation／取消；A 慢响应可覆盖已选择 B 的消息／报告。参考 IdentityManager 和 FlowRunViewer 已有过期隔离做法。
6. **按文件批量 Accept 忽略失败（P2）。** `egoagent_server/server.py:4001–4008` 不检查 `accept_change` 返回，revision conflict 仍可能报告 accepted。单项分支已返回错误。该 API 变体缺陷不能扩大说所有 UI 批量接受按钮都必然出错。
7. **大文件 handoff 误分类（P2）。** `background_workspace.py:38` 跳过 >20 MiB；`:144` 将 proposed 缺失解释成 deleted。小文件在隔离副本变大后会误预览为删除；应区分“不可处理”和“真实不存在”。删除仍有确认门，不是无条件已删除。
8. **负标注过滤不覆盖整个会话投影（P2）。** `training_data.py:380–384` 先把整体正标会话全收录，局部 down 后才处理；整段 conversation SFT 仍可含已否定 assistant 内容。应明确投影策略并增加冲突标注回归。
9. **think 标签跨 chunk 处理（P2）。** `agent.py:1331–1350` 仅按单个 delta 查完整标签；开标签被拆分可能显示本应过滤的内容，闭标签拆分可能吞正文。需增量 parser；与独立 reasoning_content 通道不同。
10. **fail_fast 不是及时失败／并行预算非全局硬限（P2）。** `pipeline_engine.py:6573–6591` 等所有 futures 完成才检查 errors 并汇总统计。应文档改名或实现取消与共享预算，而非只调整测试描述。
11. **Knowledge 检索与激活格式不一致（P2）。** `capability_registry.py:403` 可索引 Markdown／独立文本，`environment.py:168` 只加载目录+meta+txt；会出现搜到但激活不了。
12. **旧 Evolution 模型连接仍绕统一来源解析。** `self_evolution/engine.py:41–43` 以全局 Base URL 搭配多个供应商 key fallback，`:74` 独立 HTTP 调用；应与前述 Anthropic 问题一起统一来源约束，不能只修主 Agent 分支。

### 6.3 属于设计边界，不应误报为漏洞或完整功能

- 任意可信 Python Tool 在宿主进程加载执行（`environment.py:61`、`agent.py:1970`）；自报 read 权限不是可靠行为证明。**这不是“攻破 Docker”，而是 Docker 后端根本未包住全部插件。**
- Workspace Guard、源码工具选择、Superego prompt、独立工作目录分别解决不同问题，均不是强 OS 隔离。
- offline 不自动覆盖 embedding 与所有插件网络；本地 API Origin 检查不等于鉴权；SSH 没写 `-A` 不等于强制 `ForwardAgent=no`。
- Flow 版本保存、Identity 重载、工具热加载、debug retry 均不等于任意节点无损热替换。
- 当前测试没有发现全部问题；本报告的受控复现能在全量测试绿的情况下确认边界缺陷，表明还缺有针对性的回归，而非测试数量不够大。

## 7. 工程与交付层面的批判性评价

### 做得比较扎实的部分

- 统一节点目录、核心服务边界、兼容导入共享状态、真实离线 Flow 验证；不是前后端各维护一份运行逻辑。
- 审阅事务有文本／二进制／移动／冲突处理，Session／轨迹有来源和版本信息，不能简单归类为“界面展示项目”。
- 测试不全是 mock：有真实临时文件、SQLite、本地 HTTP、子进程、线程并发、源码导出；与此同时真实模型效果多数未进入本轮验收。
- 文档已相当诚实地承认分发、强隔离、自进化收益和训练范围限制；历史实验还保留了负结果与污染说明。

### 仍明显欠缺的部分

1. **能力面太宽，稳定层级未在 UI 清楚隔离。** 默认 Evolution 仍可能给用户错误的“所选 Agent 已被评测”的印象；研究页和常规操作页需显式实验标签。
2. **安全与语义约束分散。** 主连接解析修复不自动覆盖 Anthropic 和 Legacy Evolution；普通运行的 policy 不自动覆盖 ThreadPool 分支。需要共享不可绕过的接口，不是不断加单路径 patch。
3. **大文件维护热点仍突出。** `pipeline_engine.py` 8,455 行、`egoagent_server/server.py` 5,266 行、`harness_editor/src/App.tsx` 3,048 行、`void_extension/egoagent-dag-chat/extension-v21.js` 2,963 行、`void_extension/egoagent-dag-chat/media/chat.js` 2,717 行。代码行数本身不是缺陷，但跨模块不变量容易遗漏；新增逻辑应进入聚焦服务而非继续扩张这些入口。
4. **CI 不等于全套回归。** `.github/workflows/headless-core.yml` 覆盖 Win/Linux 核心边界及导出的 32 个核心测试模块、Linux Node/前端构建；没有运行整个 105 文件 Python 产品/API/实验分析集合，也没有真实 IDE E2E。不能把 CI 绿等同本报告全量绿。
5. **开发机成功与新用户交付差距大。** 前端依赖已存在、Void runtime 本机已存在、模型凭据本机有配置，均不能证明 fresh clone 可用。当前缺少验证的一键获取 Void runtime 流程。
6. **自动测试 green 并不抹平首次 Windows replace 失败。** 应保留重测证据，调查杀毒／文件占用／并发等可能因素；目前没有足够证据选定根因。
7. **实验与产品边界有反例。** V2 structural 产品路径依赖 experiments，和“核心独立”不是同一保证；应单独隔离该入口和依赖，不能只依据目录名字判定可删除。

## 8. 下一步七日执行建议

优先级按用户安全／产品正确性／交付价值排序，不是新增功能数量排序。

| 日期范围 | 工作 | 验收条件 |
|---|---|---|
| Day 1 | 修 Parallel 父策略/secret/deadline/审批继承；Knowledge env 授权；Anthropic 与 Legacy Evolution 来源约束 | 本报告的假值／假策略案例转为回归；禁止边界在子线程及所有 Provider 生效，无真实密钥外发 |
| Day 2 | 修 Windows update containment、required signature 和诊断 prompt 开关 | drive/UNC/parent-symlink/缺 trusted key/假 prompt 负测试全过；失败不得留下根外文件或半安装 |
| Day 3 | 修数据节点副作用标记、超时/重试副作用语义，明确 fail_fast 与预算 | 故障注入证明不无声重复持久操作；未知 in-flight 必须明确拒绝或审批，不称 exactly-once |
| Day 4 | 修 Session 加载竞态、bulk accept 误报、handoff 大文件、训练标注冲突 | 交错响应、revision conflict、大小跨阈值、session-up/message-down 四类回归通过 |
| Day 5 | Evolution 模式分级：Legacy prompt-only／V2 candidate 标实验；新路径连真实 Task evaluator | UI 明确评价对象、baseline/candidate/held-out 与预算；结构有效不能自动显示“能力提升” |
| Day 6 | 增加完整核心用户流程 E2E + 全量 Python CI，调查 Windows replace 偶发失败 | 新项目→只读 Chat→审批写入→Refuse/Undo→重启续接→观察回放；保留失败视频／日志并做脱敏 |
| Day 7 | fresh checkout 安装演练与发布边界文档 | 有匹配 Void runtime 的可复现来源或明确只发布 standalone Workbench/headless；验证支持系统，填写版本化验收记录 |

**近期不建议优先做：** 新增更多 Flow 模板、再加研究面板、扩大进化宣传、在现有授权缺口未修前开放不可信插件市场。先收窄稳定产品面，再扩功能。

## 9. 验证材料、复跑与交付说明

- `docs/FEATURE_MATURITY_VERIFICATION_20261123.json` 是本次结构化验证摘要，包含最终结果、首轮失败、未验收范围和受控复现结论。
- 本机原始测试／构建／HTTP／受控案例保留在 `tmp/feature-audit-20261123/`，它们是临时审查证据，不是产品源码或对外研究数据。
- 常规复跑入口（应使用无用户数据的副本；完整 pytest 会产生运行态）：

```text
python -m pytest tests -q -p no:cacheprovider
node --test tests/*.test.cjs
python scripts/audit_harness_catalog.py --json
# 在 harness_editor 下：
node node_modules/typescript/bin/tsc --project tsconfig.json --noEmit
node node_modules/vite/bin/vite.js build --outDir <新的临时输出目录>
```

本轮只生成报告、验证摘要和独立临时测试材料，并在开发日志新增审查索引；**没有修复上述缺陷，没有修改业务代码，没有提交／推送 Git，没有安装依赖或进行对外发布。**
