# EgoAgent 录屏现场操作卡

更新时间：2026-08-23  
完整台词与步骤：[VIDEO_SERIES_MASTER_GUIDE_ZH.md](VIDEO_SERIES_MASTER_GUIDE_ZH.md)

这张卡只放“开录时不能忘”的内容。系列共 18 集；不要在一个超长视频里临场寻找入口。

## 开录前 5 分钟

在 EgoAgent 仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe start-all.py
```

另开一个 PowerShell：

```powershell
.\.venv\Scripts\python.exe scripts\reset_video_demo.py --reset-evolution-artifact --reset-created-artifacts
.\.venv\Scripts\python.exe scripts\verify_recording_setup.py --live
```

必须看到 `RECORDING_SETUP_OK`。然后打开代码演示专用入口：

```text
http://127.0.0.1:8880/?folder=/C:/Users/aa310/Desktop/egoagent/tutorial_assets/video_demo_repo
```

画面上再确认四件事：

- Chat 显示 `DEEPSEEK · deepseek-v4-flash` 和“实时连接/已连接”；
- `改动 0`；
- Workbench 能看到 `Home / Build / Evaluate / Library / Improve / More`；
- 不打开 `.env.local`，不展示 API Key 输入内容。

`garden.py` 初始测试失败是刻意设计，不是环境坏了。第 3 集修完后应为 4 tests OK。

## 两个工作区怎么选

| 用途 | 打开的 folder |
|---|---|
| 真实修代码、逐 hunk、AI 编辑、检查点 | `tutorial_assets/video_demo_repo` |
| 展示 EgoAgent 源码、现有实验文件、Research/AVO 报告 | `egoagent` |

不要让 Code Agent 在 EgoAgent 自己的源码根目录里做教学写入。Workbench 的 Library、Sessions、Settings 等页面在两个入口都能用。

## 推荐录制顺序

按依赖关系拍，不必按发布顺序剪：

1. 第 1、2 集：界面和 Chat；
2. 第 3 集：真实修复，保留两个 pending hunks；
3. 紧接第 4 集：Accept/Reject/Undo、新文件确认、Tab/Inline Edit；完成后再 reset；
4. 第 5、6、7、8 集：搭图、全功能 Flow、Identity/Environment、Library；
5. 第 9、10、11 集：Task Bench、上下文治理、自进化；
6. 第 12 集：用前面已经产生的非 TaskBench Session 做 Fork/Merge/轨迹/训练导出；
7. 第 13、14 集：网络/浏览器/后台与安全/检查点；
8. 第 15、16 集：科研/发布和 CoC；
9. 第 17、18 集：Codex/DeepSeek Flow 复刻与 AVO/ARC 研究。

## 前端入口速查

| 功能 | 点击路径 | 画面证据 |
|---|---|---|
| 六种模式 | Chat → 模式 | Chat/Plan/Agent/Debug/Evolve/Evaluate |
| 结构化复制 | 编辑器/终端选中 → `Ctrl+C` → Chat `Ctrl+V` | 正文原位 `[代码附件: file:line-line]`/`[终端附件: …]` + 可点击卡片；`Ctrl+Shift+V` 为纯文本 |
| 运行状态 | Chat → 运行 | 当前发光节点、节点卡、输入输出、工具、暂停/继续 |
| 代码改动 | Chat → 改动 | hunk 红绿 Diff、接受/拒绝、文件名可点击 |
| 全局改动台 | Workbench → More → Agent Changes | 同一持久 transaction、文件级与 hunk 级操作 |
| Flow Builder | Workbench → Build | typed ports、循环、条件、审批、SubFlow、预算、权限 |
| Task Bench | Workbench → Evaluate | 13 道题、隔离 workspace、逐节点面板、确定性评分 |
| 能力搜索 | Workbench → Library | hybrid/semantic/keyword、Workspace 优先、五种能力类型 |
| 自进化 | Workbench → Improve | 最小产物选择、held-out、rollback、EvoCert |
| Identity | Workbench → More → Identity | ID/Superego/Skills/Knowledge |
| Environment | Workbench → More → Environment | workspace Tool/Knowledge |
| Session/轨迹/数据 | Workbench → More → Sessions | 赞踩/重要/入库、Fork/Merge、exact replay、训练数据 |
| 安全与模型 | Workbench → More → Settings | Provider、角色路由、镜像采集、安全档位与沙箱 |
| 后台运行 | Workbench → More → Background | queue、pause/resume/cancel、replay/checkpoint fork |
| 检查点 | Workbench → More → Checkpoints | 精确预览、冲突检查、选择性恢复 |
| 发布 | Workbench → More → Deploy | 版本、组件、权限、签名与可恢复安装 |
| 弱模型图表示 | Workbench → More → EgoIR | validate、dry-run、commit、undo |
| 科研 | Workbench → More → Research | 项目、实验契约、hash、独立审查 |
| CoC | Workbench → More → CoC Table | Identity 人物卡、物品 Tool、KP 状态事务 |

## 三条稳定演示输入

### 真实 Code Agent

选择 `Agent + adaptive_code_agent + openmanus`：

```text
请修复 garden.py 中 should_water 和 water_millilitres 的逻辑，只做最小修改，运行 python -m unittest -v，并说明你读取了什么、改了什么和测试证据。不要改测试。
```

预期最少出现：能力搜索/激活、read、两个 patch、`run_command` 审批、4 tests OK、`改动 2`。`run_command` 点“允许一次”；正常结束的 `terminate` 不应再要求审批。

### Library 语义搜索

```text
压缩长对话，减少工具输出占用的上下文
```

预期前列包含 `conversation_component_demo`、`component_context_curator`、`component_context_compactor` 或 `tutorial_full_stack_code_agent`，并显示 `SEMANTIC · fastembed · sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`。

### Agent 创建 Agent

```text
创建一个只读的 Python API 文档检查 Agent：先搜索可复用 DAG 和 Skill，能读取代码、检查公开函数是否有 docstring，输出结构化报告；不要手写一个 Python Agent 程序。
```

预期产物是可视 Harness/Flow + Identity，不是一个 Python Agent 文件；任何持久写入必须经过单次审批。

## 必须拍到的数字与标识

- Chat：52 个用户可运行 Harness；Catalog：65 个 Harness 全部通过结构校验；
- `tutorial_full_stack_code_agent`：27 节点、37 连线；
- `codex_flow`：11 节点、14 连线；
- `deepseek_harness_replica`：18 节点、21 连线；
- `arc_scientific_search`：19 节点、25 连线；
- 离线 Task Bench：Agent ×3、Tool ×2、100%；
- 精确轨迹：显示 `✓ 完整性通过`、event sequence、agent、model_call_id、working/audit；
- Library：Skill、Tool、Knowledge、Identity、DAG/Harness 五类。

这些数字来自本次代码与前端实测；能力库卡片总数、Session 数和 usage 会随使用变化，不要念成固定常数。

## 现场故障判断

| 现象 | 处理 |
|---|---|
| 8880 黑屏/打不开 | 回终端确认 start-all 仍在运行，再刷新；不要重复启动多个实例 |
| `Failed to fetch` | 看 8765/8880 是否仍在；重跑 preflight |
| `DAG 在进入等待输入节点前结束` | 先重跑最新版 `verify_recording_setup.py --live`；现在真实 Chat 启动失败会显示后端具体原因，不应只剩这句泛化提示 |
| 附件只有卡片、正文没有位置 | 说明扩展仍是旧包；重启 `start-all.py` 并 Reload Window。新版正文会出现 `[代码附件: …]`，删除标记也会移除卡片 |
| 粘贴 `你好` 却开始读仓库 | 说明仍加载了旧版 `chat.js`；新版会保留文本附件 UI，但在进入 Harness 前把单个寒暄附件还原为纯问候，必须是一次回复、零 Tool |
| Workbench 很窄、Sessions 按钮重叠 | 新版会自动把 Sessions 切成上下布局，顶部导航可横向滚动；若录制画面仍过窄，可暂时收起 Explorer 或 Chat 获得更清楚的画面 |
| `改动` 不是 0 | 重新运行完整 reset 命令，再刷新 `改动` 页 |
| Fork/Merge 按钮没有出现 | 选一个名称不含 `/` 的普通 Chat Session；TaskBench 子 Session 故意不显示按钮 |
| Agent 停在审批 | 展开审批卡；普通宿主命令只允许一次，危险动作按剧情拒绝 |
| 模型输出半截但仍运行 | 等 UI 的截断/继续提示；若永久 spinner，停止本次 take 并保存 Session 作为 bug 证据 |
| Semantic 未就绪 | 关键词路径仍可用；不要声称这次展示了语义排序，修复 embedding 状态后重录 |
| Docker daemon 不可用 | 正确画面是 fail-closed；不要切回 host 后声称仍在容器 |
| ARC 没通关 | 这是当前真实研究结果；展示 evidence、停滞监督与不晋升门控，不能剪成“复现 100%” |

## 每集收尾

录到最后 10 秒时固定回答三件事：本集配置了什么、运行证据在哪里、失败时怎样回滚/复现。然后记下 Session 名称；第 12 集会用它做 Fork/Merge、精确回放和训练数据导出。
