# 录制前功能验收矩阵

更新时间：2026-08-24。本表区分“自动测试”“真实模型运行”“录制时仍应目视确认”，避免把存在 UI 当成能力已经验证。完整 18 集拍摄顺序见 `docs/VIDEO_SERIES_MASTER_GUIDE_ZH.md`，现场速查见 `docs/VIDEO_RECORDING_RUN_CARD_ZH.md`。

| 功能 | 自动/构建证据 | 真实运行证据 | 录制时看哪里 |
|---|---|---|---|
| 统一 IDE / backend | 8880 与 8765 preflight | provider probe healthy | Void 能打开，Chat 显示实时连接 |
| Harness 目录 | 65/65 audit 通过 | 多个真实 Task 使用同一 PipelineRunner | Build 加载模板、Task Bench 画布 |
| Code Agent | Task/Runtime/工具与文件事务测试 | `adaptive_code_agent_20260823_151237`：真实 search/activate/read/patch/run，4 tests OK | 过程、产物、Agent Changes、编辑器 Diff |
| 逐 hunk Accept/Reject/Undo | Change Review API 与扩展构建通过 | 真实 Agent transaction 可生成 review journal | 编辑器绿色/红色、高层 CodeLens、新文件删除确认 |
| DAG 语义搜索 | Registry 测试含 lexical/semantic/hybrid 和缓存 | `run_20260816_192037_816edffd` 调用 search + activate | Library 卡片；运行轨迹 search/activate |
| Workspace 隔离 | 新增回归：A workspace 的能力不会出现在 B 的 list/search/get/event | 自进化新 run 不再看到旧 Task workspace 的 garden Skill | 搜索结果 scope 与 workspace |
| DAG/SubDAG 复用 | Harness 搜索返回 typed_subdag reuse contract | discovery 组件可搜索并激活 Harness | Library 的 DAG/Harness 详情、invoke_subdag |
| Context Curator | Context Runtime 测试 | `run_20260816_200845_929f9bad`，精简约 63.9% | summarize_subdag / conversation_out / Sessions 标记 |
| Passive Compactor | Context pressure 与 block plan 测试 | 同一 run，被动压缩约 72.6% | compact_subdag / before-after-saved |
| 受控自进化 | authoring、schema/signature、runtime evidence gate 测试 | `run_20260816_204121_52ce104a`，评分 1.0 | judge → approval → search → create → PASS → mark_evolved |
| 自进化产物外部验收 | `verify_video_evolution_artifact.py` | 两组计算与未知型号均 PASS | 终端输出和 Task 的原始 tool result |
| 非零命令失败识别 | run_command `ok`/exit code 与 DAG `succeeded` 回归 | 失败实验没有进入 mark_evolved | verification_evidence_gate |
| Windows 多行 `python -c` | 真实回归确认两行均执行 | 最终验收原始输出包含 PASS | run_command tool card |
| Task Bench Identity 选择 | 单槽/多槽绑定回归 | 最终 Evolver 实际写入 coder | Task 配置、tool argument identity_name |
| Task Bench | Task runner、隔离、暂停、评分、Harbor 测试 | context/evolution/code 三类真实任务 | DAG 小框、四个详情页 |
| 离线录屏自检 | preflight 每次自动运行 scripted model/tool loop | `run_20260820_152938_badaa247`：Agent ×3、Tool ×2、100/100 | 首节点暂停 → 单步 → 自动；glob/read 各一次 |
| Identity / Environment | API 与 manager tests | Task options 显示 root `egoagent` Environment | More → Identity / Environment |
| Provider/streaming | provider adapter tests、probe | DeepSeek V4 Flash 真调用 | Settings 健康状态、model usage |
| Session feedback / 训练数据 | annotation、redaction、SFT/KTO/DPO/trajectory/verl exporter tests | Sessions 页真实轨迹可赞踩、标重要、入库 | Sessions → 训练数据；八种投影与样本数 |
| Session Fork/Merge | immutable source、direct/summary/dialogue/auto、lineage tests | 普通 Session 显示 Fork/Merge；TaskBench 子 Session 正确隐藏 | Sessions 顶部按钮与 lineage 标签 |
| 精确轨迹 | append-only event、integrity、working/audit projection tests | 最新离线 run 为 89 exact events；DeepSeek replica run 为 239 exact events | 完整性、逐事件播放、Agent/事件过滤 |
| 安全/沙箱 | workspace escape、secret、host/container、fail-closed tests | 真实 `run_command` 在 Balanced 下弹单次 HIGH 审批 | Settings 与聊天审批卡；terminate 不重复审批 |
| Codex Flow | config/runtime capability tests | Build 实测 11 节点/14 连线 | compaction、permissions、tools、steering、limit output |
| DeepSeek Harness Flow | replica + exact trajectory tests | `deepseek_harness_replica_20260823_091801`，239 exact events | 18 节点/21 连线、guard/pruner/checkpoint/steering |
| AVO/ARC 长程 Flow | official adapter、Flow、candidate gate tests | V4 Flash `vc33/ls20` 实验跑通但未过首关；候选未改善则不晋升 | 19 节点/25 连线、memory/experiment/supervisor、真实失败 |
| Frontend | TypeScript/Vite production build | Workbench assets 已打包到扩展 | Void 内打开各主页面 |
| Chat 启动边界 | 真实 `adaptive_code_agent` startup 回归 + preflight live roundtrip | `interactive_44fd4785051742458ecef73df74c5100`：一次问候、零 Tool、回到 input | 不应出现“进入等待输入前结束”或重复问候；若失败显示后端具体原因 |
| 结构化附件顺序 | Extension/Context Engine 元数据测试 + bundle contract | 编辑器复制得到正文原位 `[代码附件: garden.py:1-4]` 和可点击卡片 | 在标记前后分别输入文字；删除标记时卡片同步消失；`Ctrl+Shift+V` 纯文本 |
| 窄布局可操作性 | production bundle 含 responsive Sessions/toolbar contract | Workbench 窄 iframe 下 Sessions 自动上下布局 | `训练数据` 等按钮不再与 Session 行重叠或误点 |

最终开发回归：共发现 `530` 项，`527` 项通过，`3` 项按环境声明跳过；Chrome/CDP 测试在受限测试沙箱内无法连接临时调试端口，随后在正常主机权限下 `2/2` 单独通过。Vite 生产构建转换 `224` 个模块。录制 preflight 已得到 `RECORDING_SETUP_OK`，本地多语言语义检索、离线真实 Agent/Tool 循环、DeepSeek V4 Flash 最小调用，以及 `adaptive_code_agent` 的真实启动/问候/返回等待输入均通过。

## 已修复的录制阻断问题

- 另一个 Task workspace 的私有 Skill 曾能进入搜索候选；现已在 list/search/get/metrics/event 全链路隔离。
- 自进化曾可能依赖模型自述验证；现由 Tool `succeeded`、退出码、持久化 mutation evidence 和验收 evidence 共同把关。
- `run_command` 曾在 Windows 静默只执行多行 `python -c` 的第一行；现识别该完整命令形态并以 argv 无 shell 执行。
- 单 Slot Harness 曾由后端静默使用 Harness 默认 Identity；现“整体 Identity”在单槽时就是实际绑定，多槽仍保留逐 Slot 默认/覆盖。
- 弱模型把 JSON Schema 编码成字符串或把 `_context` 放进 schema 时会失败；现兼容 JSON 字符串、从公开 schema 移除 `_context`，并拒绝“读取 `_context` 却没有函数参数”的坏代码。
- Agent Changes 曾展示别的 workspace 或 Task 内部 journal；现按当前 workspace 过滤并隐藏内部 task run。
- 模型只返回被隐藏/未声明的工具调用时，运行器曾把同一响应里的说明文字误当最终答案；现会记录协议闭合消息并有界重试，不会假成功。
- OpenHands 复刻曾声明 `finish` 路由但 Identity 没有对应 Tool；现提供显式 `finish` Skill，调用后进入独立 Goal Judge，批次中更晚的工具被丢弃。
- 旧的自动弹出 Improve overlay 会遮住 IDE；已移除，结构改动在运行观测和 Agent Changes 中查看。
- Task Bench 与 Environment Manager 对根 `.environment` 的命名曾不一致；现统一显示为 `egoagent`。
- 录屏专用 `test_bot` 曾没有继承它的 scripted tool calls 所需的只读/导航能力，安全边界会正确拒绝 `glob_search/read_file`，导致自检只有 50 分；现显式继承两个能力包，并把 3 次 Agent、2 次 Tool、100 分闭环加入每次录制 preflight。
- OpenManus 的纯完成工具 `terminate` 曾因缺少权限元数据触发第二张 HIGH 审批；现显式声明只读权限，宿主测试命令仍保留单次审批。
- reset 曾只恢复教学文件，运行中的 backend 仍可能缓存旧 hunk；现通过 workspace-scoped API 同步清理内存和 journal，只影响 `video_demo_repo`。
- Chat 启动 Identity 的日志曾引用不存在的 `full_path`，导致后端健康但真实 Agent 在到达 `input` 前崩溃；现改用已校验的 `full_identity`，并把真实启动、一次问候、零 Tool、返回等待输入加入 `--live` 预检。
- 结构化复制曾只显示附件卡，正文没有占位，导致多附件与句子之间的顺序丢失；现光标处写入稳定引用标记，引用随上下文元数据进入模型，删除正文标记会同步移除附件。
- 单独粘贴 `你好` 曾因为 `[文本附件: …]` 标记而绕过寒暄分支，错误进入 capability discovery 并读取教学仓库；现实际前端 helper 会把“唯一普通文本附件且内容为寒暄”还原为等价纯文本，同时保留用户可见的附件标记。非寒暄文本和代码附件不受此快捷分支影响。
- IDE 窄分栏下 Sessions 的 320px 固定左栏会遮住详情按钮并造成误点；现改为窄宽度自动上下布局，Workbench 顶部路由改为可滚动。

## 代码与 UI 精简结论

- 主路径只保留 Home、Build、Evaluate、Library、Improve 五个入口；高级页面收进 More。
- 大页面按需 lazy-load，DAG 仅渲染可见节点，Task trace 窗口只展示最近 200 条，避免长跑卡顿。
- 上下文精简、被动压缩、能力发现和进化都已拆成 SubDAG，而不是散落在 UI 定时器或专用 hardcode 中。
- 语义搜索主路径是 SQLite catalog + 本地 fastembed；不要求启动 Meilisearch。仓库中的 Meilisearch 兼容/历史实验文件不参与录制主路径，没有为了“看起来干净”而删除可追溯实验。
- Python 节点仍保留为迫不得已的逃生口；教学模板不依赖 Python 节点实现上下文或进化语义。

## 模型随机性与诚实边界

- 自进化“是否进化、选择何种 artifact、叫什么名字”仍由模型判断，所以名字可能与参考 run 不同。
- 审批不是装饰：拒绝应直接结束且不创建产物。
- 即使 Task 的前四项流程检查通过，只要没有 `mark_evolved` 和 mutation event，录屏自进化题也不会通过。
- Provider 自身可能限流或断网；先运行 `verify_recording_setup.py --live`。API key 不应出现在画面、文档、Git diff 或终端历史中。
- Docker 只用于声明 container backend 的外部 benchmark；四个视频 Task 均不需要 Docker。

## 最终交付前命令

```powershell
python scripts/reset_video_demo.py --reset-evolution-artifact --reset-created-artifacts
python scripts/verify_recording_setup.py --live
python -m unittest discover -s tests -v
```

前两条是每次录制都建议执行的；最后一条是开发验收，不需要在教学视频中完整展示。
