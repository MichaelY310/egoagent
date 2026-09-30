# EgoAgent 全功能视频系列总导演手册

更新时间：2026-08-31
建议成片：18 集，合计约 7–9 小时。每集都可以独立发布；按顺序录制时，前一集产生的 Session、轨迹、Flow 版本和改动可供后一集使用。

这套系列覆盖的是全部用户能力和每一种产品工作流，不要求把所有 Harness 逐个消耗模型跑一遍。可运行 Catalog 的数量会随模板增加而变化，以录制预检当次输出为准；目录结构与契约由录制预检和全量测试统一验收，第 3、6、9、11、13、17、18 集再选择代表性 Flow 实际运行。

名词以当前产品模型为准：`Flow Graph` 是允许循环的可执行图；`Harness` 是 Flow Graph 加 prompts、slots、预算、权限和运行契约，但尚未绑定具体 Identity；`Agent 实例` 是 Harness + 已绑定 Identity + Environment + 模型路由 + 当前 Session。前端仍有少量 `DAG` 旧标签用于兼容，录制时说明它不是“只能无环”的传统 DAG。

## 录制前唯一准备流程

在仓库根目录打开 PowerShell：

```powershell
.\.venv\Scripts\python.exe start-all.py
```

浏览器入口：

```text
http://127.0.0.1:8880/?folder=/C:/Users/aa310/Desktop/egoagent
```

代码演示仓库入口：

```text
http://127.0.0.1:8880/?folder=/C:/Users/aa310/Desktop/egoagent/tutorial_assets/video_demo_repo
```

### 手动录制（2026-09-29 更新）

已移除未完成的交互教程，包括金色教程按钮、遮罩、输入预设和强制点击限制。请按本文步骤手动操作；演示仓库、Task、Flow 和已有记录仍保留。代码补全的当前操作与设置见 [代码补全](AUTOCOMPLETE_ZH.md)。

每次开始拍摄前执行：

```powershell
.\.venv\Scripts\python.exe scripts\reset_video_demo.py --reset-evolution-artifact --reset-created-artifacts
.\.venv\Scripts\python.exe scripts\verify_recording_setup.py --live
```

第一条只恢复教学仓库、两个专用缺陷 Flow、已知录屏产物和该仓库的旧审阅事务，不会清理其他项目。第二条会检查 8880/8765、全部可运行 Harness、教学文件、七个录屏 Task、关键 Identity/Environment、Flow 语义搜索、一次完全离线的 Agent×3/Tool×2 闭环，以及一次最小真实模型请求。只有看到 `RECORDING_SETUP_OK` 才开录。Build 的 `untitled_custom_flow` 只是内存中的空白草稿；未添加节点并保存前不会写入 Catalog，也不会伪装成可运行 Harness。

注意：

- 不要在画面里打开 `.env.local`、API Key 输入框或终端环境变量。
- `reset_video_demo.py` 只恢复已知教学文件和已知演化产物，不是通用 Git 清理命令。
- 自进化和开放式模型任务有随机性；录制时展示真实选择和证据，不要把参考产物名讲成硬编码结果。
- Docker 不是前 13 集的前置条件；容器后端不可用时应展示 fail-closed，而不是声称已强隔离。
- 正式修代码一律打开 `video_demo_repo` URL，不要在 EgoAgent 自己的源码仓库里演示写入；进入 Chat 后先确认 `改动 0`。
- 开放式网络、Dialogue Merge、Agent Factory、自进化和 ARC 任务具有随机性；先拍确定性 UI，再单独补拍模型运行，失败时保留真实错误提示而不是剪成“假成功”。

### 全系列通用的按钮位置（第一次录制先读这一段）

下面所有集数默认都从 `video_demo_repo` URL 开始，除非该集明确写“切回 egoagent 主仓库”。Void 的固定布局是：左边 `Explorer` 文件树，中间文件编辑器/Workbench，右边 `EgoAgent` Chat。

右侧 Chat 从上到下固定为：

1. `EgoAgent` 标题栏：右侧有 `Workbench` 和连接状态；
2. `Agent 配置` 折叠条：默认收起，点击后才显示模式、Harness、Identity 与 slot 绑定；再次点击整块收起，给聊天历史腾出高度；
3. `对话 / 改动 / 上下文` 三个页签；运行状态不再占用独立页签，而是显示在输入框下方的活动条，并可在 Workbench 的实时架构和节点详情中展开；
4. 当前页主体；
5. 最底部消息输入框、Agent 活动状态、`＠` 上下文按钮和 `发送`。

`＠` 不是普通文字按钮。点击后会出现三个明确选项：

- `@file`：把中间编辑器当前打开的文件插入光标位置；
- `@selection`：先在中间编辑器选中代码，再点它；
- `@workspace`：引用当前项目代码地图和检索范围。

三者都会成为输入框内的原子附件图标。文件/选区图标可点击并跳回来源；文本图标悬停显示内容摘要，单击会打开可滚动、可编辑的完整内容窗口。把光标放到图标右侧按 `Backspace`，或刚插入后按 `Ctrl+Z`，会一次删除整个附件，不会逐字删除 `[文本附件: ...]`。输入框上方不再重复显示任何 Clipboard 卡片。从 Explorer 或编辑器标签拖入的文件/选区也是同一种图标；右键 Explorer 文件点 `EgoAgent → Attach File to Chat`，或右键编辑器选区点 `EgoAgent → Attach Selection to Chat`，是同一数据通路的辅助入口。

### 每一集都按同一套叙事顺序录

后面的每一集都明确写了“本集目的”和逐步操作。录制时不要只展示按钮，要按下面五句话完成一个闭环：

1. **问题**：用户原来遇到什么困难；
2. **配置**：当前 Workspace、页面、Harness、Identity、Mode 和 Flow 版本是什么；
3. **动作**：这一部具体点哪个按钮、输入什么；
4. **证据**：在哪里看到 Tool、节点、版本、分数、轨迹或文件改动；
5. **边界**：什么是已经真实运行的，什么依赖外部 CLI、容器或模型，不把预览说成执行成功。

如果某一步没有出现该集写明的“成功画面”，先停录并按该步的排错提示处理，不要继续录到下一功能。

## 18 集总览

| 集数 | 标题 | 本集要解决的问题 | 建议时长 | 最终成功证据 |
|---|---|---|---:|---|
| 1 | 一体化 IDE、产品模型与服务体检 | 先让观众知道 EgoAgent 是什么、服务是否真的可用 | 10–15 分钟 | 8880、实时连接、Home、`RECORDING_SETUP_OK` |
| 2 | 原生 Chat、六种模式与结构化代码上下文 | 教会用户提问、切权限、精确引用代码而不污染正文 | 15–20 分钟 | 单次简洁回复、活动状态、`file.py:line` 原子附件 |
| 3 | Adaptive Code Agent 完成真实修复 | 证明它不是聊天壳，而会读证据、改文件并跑验证 | 20–30 分钟 | 读取、写入、命令、测试通过、实时 Flow 轨迹 |
| 4 | 编辑器内逐块 Accept/Refuse、Ctrl+Z 与 AI 编辑器 | 让 Agent 默认落盘，同时保留逐块人工控制和可逆性 | 20–25 分钟 | 红绿 diff、块级按钮、撤销恢复审阅态、新文件确认 |
| 5 | 从零搭一个可运行 Flow Graph | 让普通用户不用写 JSON 也能组装循环式 Agent 流程 | 25–35 分钟 | 类型化端口、分支、循环、审批、版本保存、暂停/单步 |
| 6 | 全功能 Code Agent 与可复用 SubFlow | 证明压缩、精简、搜索和进化都是 Flow 组件而非硬编码 | 30–45 分钟 | 四个组件、并行审查、事务、SubFlow、上下文与进化 |
| 7 | Identity、Ego、Superego、能力与统一治理 | 区分“谁在做”“怎么做”“最终允许做什么”，避免权限配置冲突 | 30–40 分钟 | 角色复用、Tool 调用、Superego→Runtime→最终权限预览 |
| 8 | 像搜视频一样搜索可复用能力和 Flow | 节省上下文与重复开发成本，优先复用当前 Workspace 资产 | 15–25 分钟 | hybrid/semantic/keyword、workspace 优先、usage 自动更新 |
| 9 | Task Bench：数据集、Runner、精确版本、评分、比较与回放 | 把“跑题”变成可复现、可比较、可审计的实验 | 35–50 分钟 | 自定义字段预览、固定 Flow 版本、100 分、双轨比较、Build 历史回放 |
| 10 | Context Curator、被动压缩与真实上下文回放 | 区分“删无关内容”和“上下文过长后压缩”，同时保留审计历史 | 25–35 分钟 | working/audit 差异、before/after、关键事实仍可回答 |
| 11 | 受控自进化、Agent Factory 与 Flow 结构进化 | 展示 Agent 如何创建/修改可复用 Flow，又不把一次偶然结果直接上线 | 45–70 分钟，建议拆 5 条短片 | 真实 mutation、隔离候选、开放选择、科学门控、版本演进 |
| 12 | Session Fork/Merge、精确轨迹和训练数据导出 | 把日常使用沉淀成可分支、可合并、可训练的数据资产 | 25–35 分钟 | lineage、多 Agent/版本归属、摘要后 surface、LLaMAFactory/verl 导出 |
| 13 | 联网搜索、页面取证、浏览器 Agent 与后台任务 | 让 Agent 能处理 IDE 外的真实网页与长任务，且保留证据和接管点 | 25–35 分钟 | URL 证据、observe-act-verify、handoff、durable run |
| 14 | 安全、审批、Workspace Guard、容器与检查点恢复 | 说明安全不是提示词，而是运行时边界、审批和可恢复事务 | 25–35 分钟 | 单次审批、越界拒绝、fail-closed、选择性恢复 |
| 15 | Improve、Deploy、EgoIR 与 Research Lab | 把失败轨迹转成经过回归验证、可部署的候选 | 25–35 分钟 | held-out/regression/rollback、package、dry-run、science audit |
| 16 | CoC 多 Agent 跑团与持久人物卡 | 证明 Identity/Flow 不只服务代码任务，也能维持长期世界状态 | 25–40 分钟 | KP 裁决、人物卡事务、物品丢失后规则持续生效 |
| 17 | Codex Flow、DeepSeek Harness 与原版 Codex 对照 | 证明“一切皆 Flow”的表达力，并与外部真实 Runner 做公平对照 | 30–45 分钟 | 11/18 节点、工具循环、精确版本、原版 Codex CLI lane、轨迹差异 |
| 18 | AVO 风格长程搜索、ARC 与 Flow 自进化 | 展示长程状态、监督器与证据门控，而不是宣称复刻论文满分 | 30–45 分钟 | 持久证据、非行动 supervisor、停滞恢复、结构候选与 held-out |

### 18 集的固定起点速查（避免打开错项目）

“主仓库”指 URL 末尾为 `/egoagent`；“教学仓库”指 URL 末尾为 `/tutorial_assets/video_demo_repo`。进入 Workbench 的统一动作是：右侧 Chat 标题栏点 `Workbench`，然后在中间顶部点 `Home / Build / Evaluate / Library / Improve / More`；`More` 展开后再点表中的子页面。

| 集数 | 必须打开的 Workspace | 第一个按钮路径 | 第一个文件 / 选择 / 输入 |
|---|---|---|---|
| 1 | 主仓库 | Chat `Workbench` → `Home` | 不运行任务；先拍终端 `RECORDING_SETUP_OK` |
| 2 | 教学仓库 | Chat `Agent 配置` → Chat 模式 | 左侧 `garden.py`；第一条输入 `你好` |
| 3 | 教学仓库 | Chat `Agent 配置` → Agent 模式 | `garden.py`；使用本集完整修复 prompt |
| 4 | 教学仓库 | Chat `改动` | 点 `garden.py` 改动卡文件名；先审第 3 集两个 hunk |
| 5 | 主仓库 | `Workbench` → `Build` | 点新建 Harness，名称 `video_basic_agent` |
| 6 | 主仓库 | `Workbench` → `Build` | Harness 下拉选 `tutorial_full_stack_code_agent` |
| 7 | 主仓库 | `Workbench` → `More` → `Identity` | 克隆 `coder` 为 `video_coder` |
| 8 | 主仓库 | `Workbench` → `Library` | 搜索框输入 `读取和搜索代码仓库文件` |
| 9 | 主仓库 | `Workbench` → `Evaluate` | Task 选 `离线 DAG / Tool Trace 自检`，Runner 选 `EgoAgent Flow`，锁定显示的 Flow 版本 |
| 10 | 主仓库 | `Workbench` → `Evaluate` | Task 选 `录屏：精简上下文与被动压缩` |
| 11 | 主仓库 | `Workbench` → `Evaluate` | 第一条先选 `录屏：Agent 自己创建可复用 Agent`；随后按本集 Demo 顺序录制 |
| 12 | 主仓库 | `Workbench` → `More` → `Sessions` | 选择第 10 或第 11 集产生的非临时 Session |
| 13 | 教学仓库 | Chat `Agent 配置` → Agent 模式 | 第一条使用本集 python.org 搜索 prompt |
| 14 | 主仓库 | `Workbench` → `More` → `Settings` | 点 `安全、审批与沙箱`；不要先改 Unrestricted |
| 15 | 主仓库 | `Workbench` → `Improve` | 粘贴一个第 9–11 集的失败/低分轨迹 |
| 16 | 主仓库 | `Workbench` → `More` → `CoC Table` | 模组先选 `coc_the_haunting` |
| 17 | 主仓库 | `Workbench` → `Build` | Harness 下拉先选 `codex_flow`，后半段切 Evaluate 做 Codex CLI 对照 |
| 18 | 主仓库 | `Workbench` → `Build` | Harness 下拉选 `arc_scientific_search`；实验文件从 Explorer 打开 |

如果某一集从中途开始录，先按表重新打开对应 Workspace、对应页面和对应文件，不要相信 Void 上一次恢复的焦点状态。

---

## 第 1 集：一体化 IDE、产品模型与服务体检

### 本集目的

让第一次看到 EgoAgent 的观众在 15 分钟内理解：它是 Code IDE、Agent 构建器、实验平台和数据工作台的同一产品界面，并先用可复现预检证明服务、目录和最小模型调用可用。本集不跑复杂任务。

### 操作

1. 在终端运行录制预检，停在 `RECORDING_SETUP_OK`。
2. 打开 8880 主入口，展示左侧文件、中央编辑器和右侧 EgoAgent Chat 共处一个 Void 窗口。
3. 点 Chat 顶部 `Workbench`，依次展示 `Home / Build / Evaluate / Library / Improve / More`。
4. 在 Home 讲清 `Build → Evaluate → Improve → Deploy` 生命周期。
5. 用一张口头关系图解释：
   - Identity 决定“谁在工作”；
   - Environment 提供共享 Tool/Knowledge；
   - Harness/DAG 决定“怎样工作”；
   - Task 提供可复现环境和客观评分；
   - Session/Trajectory 记录模型真正看到了什么、做了什么。

### 画面中必须出现

- Chat 的 `DEEPSEEK · deepseek-v4-flash` 与“已连接”；
- Home 的四阶段入口；
- 预检中的 `Harness catalog`、`Task Bench runtime` 和 `live provider probe`。

## 第 2 集：原生 Chat、六种模式与结构化代码上下文

### 本集目的

教用户完成最常用的 Chat 操作：为当前 Session 选 Agent 配置、区分六种权限模式、观察运行状态、精确引用文件/选区/终端/Workspace，并理解工具过程默认折叠但没有丢失。

本集固定打开：

```text
http://127.0.0.1:8880/?folder=/C:/Users/aa310/Desktop/egoagent/tutorial_assets/video_demo_repo
```

先在左侧 Explorer 单击 `garden.py`，确认中间编辑器标题就是 `garden.py`。右侧如果有旧消息，点 Session 条最右侧的 `＋`，新建一个继承当前配置的 Session；本集不要删除旧 Session，也不要寻找已经移除的“运行”页签。

### A. 折叠配置和六种模式

1. 点右侧最上方的 `Agent 配置` 折叠条。
2. 在 `搜索 Harness` 输入 `adaptive_code_agent`。
3. 在下面的 `Harness` 下拉框选 `adaptive_code_agent`。
4. 在 `默认 Identity` 选 `openmanus`。
5. 打开 `模式` 下拉框，逐项停留并口述：`Chat` 只读问答、`Plan` 只读规划、`Agent` 执行任务、`Debug` 复现并修复、`Evolve` 只允许改明确授权的进化目标、`Evaluate` 在题目隔离环境中评测。这里不是六个提示词皮肤，后端权限和运行边界会跟着切换。
6. 最后选回 `Chat · 只读问答`。
7. 再点一次 `Agent 配置` 折叠条。确认配置只剩一行摘要，聊天区域明显变高；后面录聊天时保持收起。

### B. 先证明普通聊天不会误触发仓库工作

1. 单击最底部输入框，手动输入：

   ```text
   你好
   ```

2. 点 `发送`。输入框下方应依次显示“正在读取编辑器状态并启动 DAG / 正在生成回答 / 回答完成”等活动；最终只能出现一条简短问候。
3. 不要展开任何内容，先指出这次不应出现 `search_capabilities`、`read_file`、仓库总结或第二条重复问候。
4. 再发送：

   ```text
   请只读说明这个教学项目的入口文件、主要目录和测试命令，不要修改文件。
   ```

5. 这次允许出现只读工具。模型的最终回答应按 Markdown 渲染出段落、列表、粗体和代码块，不再显示原始 `**`、反引号或挤成一整段。
6. 如果出现“已完成 N 个工具调用”，它默认是一条折叠卡。单击卡片标题展开，拍到工具名和结果；再收起，证明默认聊天画面保持精简但轨迹没有丢失。

### C. 复制普通文字：只保留一个可编辑的行内图标

1. 从本手册或任意纯文本位置复制一行 `你好`。
2. 在 Chat 空输入框按 `Ctrl+V`。不要发送。
3. 光标位置应只出现一个带文档图标的 `Clipboard · 1 line` 原子附件；输入框上方不应再出现 Clipboard 卡片或预览条。
4. 鼠标停在图标上，确认 tooltip 显示 `你好` 的简略内容。
5. 单击图标：弹出“文本附件”窗口；窗口内能看到完整文本、可以滚动，也可以把 `你好` 改成 `你好，EgoAgent`。点 `保存`，图标仍位于原来的句子位置，附件内容已经更新。
6. 把光标放在图标右侧按 `Backspace`：整个图标应一次消失。
7. 再按一次 `Ctrl+V`，随后立刻按 `Ctrl+Z`：撤销的是整个附件插入，不会逐字删除附件标题。
8. 最后按 `Ctrl+Shift+V`：这次只出现普通文字 `你好`，没有附件图标。删掉它，保持输入框为空。

### D. 复制代码选区：附件在句子中的准确位置

1. 回中间编辑器，在 `garden.py` 从第 1 行拖到第 4 行，确保四行高亮。
2. 按 `Ctrl+C`。
3. 回到底部输入框，先输入 `请解释 `，光标停在空格后。
4. 按 `Ctrl+V`，等待“识别中”变成 `garden.py:1-4` 图标。
5. 在图标后继续输入 ` 为什么这样设计？`。画面应是“文字 → 附件图标 → 文字”，而不是附件全部堆在消息上方。
6. 单击 `garden.py:1-4` 图标。中间编辑器必须跳回 `garden.py` 并重新选中对应行。
7. 回输入框点 `发送`。发送后的蓝色用户气泡仍应在原句位置显示同一个小附件图标；模型收到的 context plan 中应记录它的 path、start/end line 和 attachment order。

### E. 拖放文件和三个 `＠` 按钮

1. 在左侧 Explorer 展开 `docs`，把 `sensor_notes.md` 直接拖进 Chat 输入框。
2. 输入框应出现 `docs/sensor_notes.md` 文件图标；单击它应打开真实文件。Workspace 外的文件应被拒绝，不得偷偷读入。
3. 文件跨过编辑器与 Chat 的 iframe 边界后仍应落成一个 `docs/sensor_notes.md` 图标；单击图标应直接在编辑器打开该文件。如果操作系统在录屏时中断了鼠标拖拽，右键左侧 `sensor_notes.md` → `EgoAgent` → `Attach File to Chat`，可走同一条结构化附件通路。
4. 删除该图标。点击输入框下方左侧的 `＠`，在弹出菜单点 `@file · 当前文件`。因为当前打开的是 `sensor_notes.md`，输入框应插入这个文件的图标。
5. 再打开 `garden.py`，选中第 5–8 行；点 `＠` → `@selection · 当前选区`，应插入 `garden.py:5-8`。顺便右键这四行 → `EgoAgent` → `Attach Selection to Chat`，说明编辑器右键也能获得同样的结构化范围（录制时保留其中一个，删除重复图标）。
6. 再点 `＠` → `@workspace · 当前项目代码地图`，应插入 `Workspace · video_demo_repo`。
7. 分别说明：`@file` 给精确文件内容，`@selection` 给精确行范围，`@workspace` 让 context planner 在当前项目代码地图和检索索引里取相关内容。三个图标都在用户消息的真实位置，不是隐藏附件。

### F. 终端选区

1. 打开 Void 底部 Terminal，运行：

   ```powershell
   python -m unittest -v
   ```

2. 用鼠标只选中最后 3–5 行测试输出，按 `Ctrl+Shift+C`。`Ctrl+C` 没有被 EgoAgent 改写，仍用于终止正在运行的进程。
3. 回到 Chat 输入 `解释这个测试结果：`，按 `Ctrl+V`。应出现带 `⌘` 的 `Terminal · …` 结构化图标；按 `Ctrl+Shift+V` 则只粘贴纯文字。
4. 再演示快捷入口：重新选中 Terminal 文本后，标题栏右上角会出现对话气泡 `将终端选区加入 EgoAgent 对话`，点击即可直接插入 Chat；Chat 的 `＠` 菜单中也可点 `@terminal` 读取当前终端选区。
5. 在图标后输入 `解释这个测试结果：`。终端附件没有文件跳转，因此单击不应伪造来源文件；本段不需要发送，点图标的删除按钮即可。

这里明确区分三种操作：`Ctrl+C` 永远保持终端中断语义；`Ctrl+Shift+C` 复制并记住 Terminal 来源；右上角按钮或 `@terminal` 直接把选区加入对话。

### G. 三个页签到底看什么

保持 `garden.py` 打开，按下面顺序逐个点击右侧页签：

1. `对话`：用户消息、Markdown 最终回答、默认折叠的思考/工具，以及最下方实时活动状态。
2. `改动`：这里集中显示 Agent 已默认写入文件但尚未审阅的 change transaction。每个 hunk 有 Accept/Refuse；本集 reset 后应显示 `0`，真正操作留到第 4 集。
3. `上下文`：先点 `↻ 刷新`。顶部第一排 `工作台 / DAG 构建 / 评测 / 进化 / 安全设置` 是跳转入口；第二排：
   - `代码地图` 会在中间编辑器打开当前 Workspace 的符号/文件地图；看完关闭该临时页；
   - `应用预览` 打开配置的本地预览 URL，不是上下文附件；
   - `提交消息` 根据当前 Git diff 生成候选 commit message；
   - `＋ 检查点` 保存当前文件 revision。
4. 继续在 `上下文` 往下看：当前编辑器 context、`本轮上下文计划`、`记忆`、`项目规则 / AGENTS.md`、`检查点`、`历史 Sessions`。逐个展开即可，不要把上面的动作按钮说成同一类数据。

过去的独立 `运行` 页已经删除。简洁状态直接看输入框下方活动条；完整节点轨迹通过当前 Session 菜单的 `在 Build 中观察` 打开。进入观察后 Build 会锁定并显示 linked Session，防止把“调试 Flow”和“正在聊天的 Agent”混为一谈。

### H. 运行中发送补充消息

1. 回 `对话`，展开 `Agent 配置`，把模式切到 `Agent · 执行任务`，确认 Harness 仍是 `adaptive_code_agent`、Identity 仍是 `openmanus`，再收起配置。
2. 发送：

   ```text
   先只读检查 garden.py 和 docs，列出你准备使用的证据；列完后等待我的下一条要求，不要修改文件。
   ```

3. 在活动状态仍显示 Agent 运行时，立即再发送：

   ```text
   补充：不要读取 test_garden.py，只引用 docs 下的规则。
   ```

4. 第二条不会启动一个不相关的新 Session，也不会让界面假死。前端会锁定当前 `run_id`，等这个 Flow 到达 `等待输入` 协议后把补充消息送入同一运行；底部活动状态会明确显示“正在等待/正在交给当前 DAG”。
5. 打开当前 Session 菜单，点 `在 Build 中观察`；用相同 root run、节点轨迹和两条输入证明它们属于同一个执行。观察状态下不要解锁或修改 Flow。

## 第 3 集：Adaptive Code Agent 完成真实修复

### 本集目的

用一个有权威文档、有真实 bug、有自动测试的最小仓库，证明 Adaptive Code Agent 会从证据出发完成“检索能力 → 读文件 → 最小写入 → 命令验证”的闭环，而不是根据 README 猜答案。

打开教学仓库，选择 `Agent + adaptive_code_agent + openmanus`，发送：

```text
请修复 garden.py 中 should_water 和 water_millilitres 的逻辑，只做最小修改，运行 python -m unittest -v，并说明你读取了什么、改了什么和测试证据。不要改测试。
```

### 按这个顺序讲

1. 发送后先停在输入框下方的活动条，拍到“正在运行”和当前节点；不要寻找已经删除的独立“运行”页签。
2. 在当前 Session 的菜单点 `在 Build 中观察`。Build 自动加载该 Session 正在使用的确切 Flow 版本、加锁，并显示黄色 `Linked to Session` 边界；这里的暂停/单步只控制观察到的这次运行。
3. 在图上依次点击 capability discovery、Agent、Tool 和上下文组件；展开 `read_file/search_files`、写入工具和 `run_command`，展示参数与真实结果。
4. 当 `run_command` 出现高风险审批卡时点 `允许一次`；这是宿主命令边界，不要改成永久允许。任务正常结束不应再为 `terminate` 弹第二张审批卡。
5. 预期逻辑变为 `should_water(20) == True`、`water_millilitres(12, 5) == 60`。
6. 终端再次运行：

```powershell
python -m unittest -v
```

7. 点 Agent 回复或 `改动` 页中的改动文件名，确认直接在 Void 编辑器打开。
8. 如果模型达到输出上限，UI 应显示“回复被截断/发送继续”，不能留下永久 spinner。
9. 回 Build 点锁按钮，确认弹窗提示是否退出 Session 观察；确认退出后才恢复 Flow 编辑能力。退出观察不会停止或改写刚才的 Chat Session。

当前机器实测轨迹为：`search_capabilities → activate_capability(garden_evidence) → read_file ×4 → patch_file ×2 → run_command`，4 项测试全部通过。模型可能改变读取顺序，但必须同时具备“本地证据、真实写入、真实测试”三类证据。

### 可对比的 Harness

用 2–3 分钟展示目录中的 `aider_replica`、`openhands_replica`、`swe_agent_replica`、`continue_agent_replica`、`openmanus_replica`。解释它们是不同 agent loop/Harness 模板，不是五套互相割裂的产品 UI；不需要本集逐个消耗模型跑完。

## 第 4 集：逐块审阅与 AI 编辑器

### 本集目的

证明 Agent 修改默认已经写入文件，但用户仍能在真实编辑器中按 hunk Accept/Refuse；审阅决定本身进入 Undo 栈，新文件的拒绝则必须二次确认。

### 逐块 Accept/Refuse 与 Ctrl+Z

本集接着第 3 集录；如果单独录，先在教学仓库按第 3 集 prompt 让 Agent 产生两个 `garden.py` hunk。

1. 在右侧点 `改动`，确认 `garden.py` 卡片显示两个“待审”块。先单击卡片最上方的蓝色文件名 `garden.py`，中间编辑器必须直接打开真实文件。
2. 在中间编辑器滚到第一个绿色块。每个待审块上方只应有一条 CodeLens：`Review Diff · −N +N | ✓ Accept | ↶ Refuse`。不要出现第二套 Inlay Hint，也不要在真实代码上叠加伪造的红色文字。
3. 点击 `Review Diff`。Void 会打开原生 inline diff editor；被删除的旧行由原生 Diff 显示为红色，被添加的行显示为绿色，换行和新旧行号都由编辑器计算。关闭 Diff 后回到真实文件。
4. 点击第一个块的 `✓ Accept`。文件内容不变化，因为 Agent 的修改本来就已默认生效；这个动作只把该块标为已审。CodeLens 和绿色高亮立即消失，不应留下红框，也不应出现额外的 `Undo Accept` 按钮。
5. 保持编辑器焦点，立刻按 `Ctrl+Z`。撤销的是刚才的 Accept 决定，不是整次 Agent 文件修改；第一个块重新变绿并重新显示审阅 CodeLens。
6. 点击第二个块的 `↶ Refuse`。只恢复第二段旧代码；所有审阅装饰立即消失，第一个块不受影响，也不应出现额外 Undo 按钮。
7. 立刻按 `Ctrl+Z`。这次撤销 Refuse：第二段恢复为 Agent 已写入的版本，待审高亮和 CodeLens 重新出现。
8. 回右侧 `改动`。Accept/Refuse 完成的块应立即从待审列表移除；如果同一文件已经没有待审块，整张文件卡也应消失。撤销审阅统一使用编辑器 `Ctrl+Z`，撤销后对应块才重新出现在列表里。
9. 最后逐块点 Accept，打开 Terminal 运行：

   ```powershell
   python -m unittest -v
   ```

10. 预期 4 项通过。

每次点击后等待按钮消失或重新出现再进行下一步；不要在后端 revision 回执到达前连续点击同一块。

### 专门验证“纯删除”不会标错行

1. 保持 `Agent + adaptive_code_agent + openmanus`，发送：

   ```text
   只删除 garden.py 中 should_water 函数的 docstring，其他字符都不要改；不要删除函数体。完成后不要自动接受改动。
   ```

2. Agent 完成后点 `改动` → 文件名 `garden.py`。
3. 删除位置显示红色 gutter、`−1 行已删除` 红色锚点和上方审阅 CodeLens；它只是单行定位标记，不伪造旧代码。点 `Review Diff` 后，原生 inline diff 中的 docstring 必须位于 `should_water` 的 `return` 之前，且新旧行号正确。
4. 点 Refuse，docstring 应回到原位置且审阅装饰全部消失；按 `Ctrl+Z`，docstring 再次被删除且该块恢复待审 CodeLens。
5. 为了后续视频稳定，最后点 Refuse 保留 docstring。Refuse 本身已经完成审阅，不需要再对恢复内容点 Accept。

### 新文件安全行为

让 Agent 创建一个临时文档：

```text
新建 VIDEO_TEMP_NOTE.md，写三行说明：purpose、test command、owner。不要修改其他文件。
```

1. 整个文件应为绿色。点右侧 `改动` 卡片的文件名，打开 `VIDEO_TEMP_NOTE.md`。
2. 在全文绿色块点 Refuse，必须出现“拒绝完整写入会删除新文件”的模态确认。
3. 第一次点取消，证明不会静默删除，文件与待审按钮仍在。
4. 第二次再点 Refuse 并确认删除；文件才会被移除。
5. 若此时当前编辑器仍在该文件，按 `Ctrl+Z` 会撤销最近审阅决定并恢复待审 revision，而不是调用普通文字 undo。录完执行 reset，确保临时文件不留给下一集。

### AI 编辑器

1. 打开 `garden.py`，在文件末尾输入 `def describe_moisture(value):`，回车并缩进后等待灰色建议；也可按 `Alt+\` 手动触发。状态栏会显示补全中、Tab 接受或超时；真实模型速度不保证 1–2 秒。按 `Tab` 接受，`Ctrl+Z` 撤销；再触发一次，按 `Esc` 取消，确认文件内容没有变化。`Ctrl+Right` 可只接受下一词，`Ctrl+Alt+Right` 接受下一行。录完撤销这段人工演示代码。
2. 选中 `watering_decision` 函数体，按 `Ctrl+I`，在弹框输入 `改成更清晰的提前返回，并保留行为`；先看 Diff 预览，再点“应用并进入逐段审阅”。
3. 展示代码审查、next-edit suggestion 与状态栏本地 usage 计数。
4. 强调模型不可用时可本地降级验证 UI，但正式演示应以已连接模型为准。

## 第 5 集：从零搭一个可运行 Flow Graph

### 本集目的

让没有写过 EgoAgent JSON 的用户先用三个节点真正搭通最小 ReAct，再理解如何继续加入分支、审批和 Checkpoint；全程只用前端画布，并保存出不可变版本。

进入 `Build`，新建 `video_basic_react`。本集手动操作，不再提供教程遮罩、黄色目标框或自动绑定；下面明确列出所需端口和配置。

### 推荐图

```text
输入 --input--> Agent
Agent --has_tool_calls--> 工具 --tools_executed--> Agent
Agent --has_text--> 输入
```

### 每一步

1. 点 `＋ 新建`，再点顶部 `配置`；在右侧名称框输入 `video_basic_react`。
2. 点回 `组件`。把 `输入` 拖到画布左侧：它既读取用户消息，也是在一轮回答结束后暂停等下一条消息的协议节点。
3. 把 `Agent` 拖到中间上方。打开配置里的 `Agent Slots`，在 `slot 名` 输入 `agent` 并添加；在 Identity 绑定区域把 `coder` 绑定到这个 slot。选中 Agent 节点，把 `Agent (slot 名)` 设为 `agent`。它负责决定“输出最终文字”还是“请求工具”。
4. 把 `工具` 拖到右侧下方；把它的 `Agent (slot 名)` 同样设为 `agent`。它只执行模型已经请求、且通过运行权限策略的 Tool。
5. 从各节点的命名输出端口拖到目标节点的 `flow` 输入端口：`输入.input → Agent.flow`、`Agent.has_tool_calls → 工具.flow`、`工具.tools_executed → Agent.flow`、`Agent.has_text → 输入.flow`。端口类型检查仍保留，但不会再强制你按教程步骤操作。
6. 沿箭头复述一次最小 ReAct：用户输入进入模型；有工具调用就执行并把 observation 回给模型；有最终文字就回到等待输入。这样用户能看懂“Flow 如何接入 Chat”，也能看懂循环为何不是传统 DAG。
7. 单击边后点浮动工具条中的 `＋ 控制点`，或直接在连线上双击/右键，在鼠标位置精确加入 Bezier 控制点。插入采用曲线精确分割，因此加入前后形状不变。拖动圆点会智能带动其余控制点，`Shift+拖动` 只改当前点，`Alt+拖动` 沿原曲线滑动；拖动方形手柄可旋转切线。边的两端始终固定在命名输入/输出 socket；移动端点时控制点按距离比例平滑跟随，按住 Shift 可关闭联动。`Ctrl+Z` 撤销节点、边和控制点编辑，`Ctrl+Y` 重做。
8. 点击 Build 顶栏的 `自动整理`，先展示 `紧凑 / 均衡 / 最清晰` 三个预设，再依次拖动 `紧凑度 / 避让强度 / Edge 简洁度`。选择 `最清晰` 后点击 `整理并重新布线`：节点会重新分层，循环边优先走图外侧。再次打开弹窗，展示穿节点、交叉、重线与控制点数量的前后对比。按一次 `Ctrl+Z` 展示整个自动整理是一次可撤销事务，再按 `Ctrl+Y` 恢复。
8. 展开一个具有多个参数的节点，指出每个输入和输出都拥有独立 socket。黄色菱形表示控制事件，蓝色圆点表示数据端口；数据输出连接到数据输入后，保存时会自动生成 `$node.<source>.<port>`，不需要手写 JSON 引用。
9. 点 `💾 保存`，记录生成的不可变 Flow Version；再次保存会产生新版本，不会覆盖这条轨迹引用的旧版本。
10. 勾 `首节点暂停`，点 `独立试跑`，再点 `单步` 和 `自动`。运行到 `等待输入` 时说明：纯 Task Flow 可以不含它；要接入多轮 Chat 的 Flow 必须用输入/等待协议主动读取下一条消息。

录完最小 ReAct 后，可以再加 `If / Human Approval / Checkpoint / Context / Output`；完整复杂模板放在第 6 集讲，避免第一次搭图时把“节点很多”误当成“理解了 Agent loop”。

这里要明确：节点有固定的操作契约，但端口、变量引用、边和多数细节都可在前端配置；高级 JSON 是逃生口，不是正常搭图的必需品。Python 节点只在没有类型化组件能表达时使用。

## 第 6 集：全功能 Code Agent 与可复用 SubFlow

### 本集目的

用旗舰模板拆开讲解复杂 Code Agent：能力搜索、上下文压缩、上下文精简、重复工具保护、结果裁剪和周期进化都由普通组件/SubFlow 组合，而不是藏在某个“大 Agent”类里。

详细搭建稿见 `docs/DAG_ALL_FEATURE_CODE_AGENT_TUTORIAL_ZH.md`。最快录法是在 Build 加载 `tutorial_full_stack_code_agent`，先讲图，再挑关键配置。

### 逐步操作

1. 打开主仓库 → `Workbench` → `Build`，在 Harness 下拉选 `tutorial_full_stack_code_agent`；确认顶部显示节点/连线数量和当前不可变版本。
2. 点 `整理布局`，再用缩放适配全图。先只沿主链从 Input 指到等待下一轮输入，不逐个打开节点。
3. 双击 `component_capability_discovery / component_context_compactor / component_context_curator / component_capability_evolver` 四个 SubFlow 节点；每次都展示 typed inputs/outputs、失败/超时策略和 `share_session`，点画布空白收回小节点。
4. 打开 Agent↔Tool 回边、并行测试/审查→Join、写入前后 Checkpoint 和 review transaction；用有方向的 edge label 说明这是允许循环的 Flow Graph，不是传统无环 DAG。
5. 回 Chat 新建一个 Session，模式选 `Agent`，Harness 选 `tutorial_full_stack_code_agent`，Identity 选 `coder`，版本保留 `latest`，发送：

   ```text
   只读检查 ARCHITECTURE.md，概括 Flow Graph、Harness、Identity 和 Session 的关系；不要修改文件，也不要运行命令。
   ```

6. 在该 Session 菜单点 `在 Build 中观察`。确认 Build 锁定到 Chat 记录的 exact version；点击本次真正经过的节点看输入/输出，未经过的节点保持静止，不能为了画面伪造“全部节点都被调用”。
7. 任务完成后点 Build 的 `退出观察`，在确认框选择退出。回到独立草稿后不要保存任何录屏临时改动。

### 四个已嵌入 SubFlow 与两个新增控制组件

- `component_capability_discovery`：先搜索 Tool/Skill/Identity/DAG；
- `component_context_compactor`：token pressure 被动压缩；
- `component_context_curator`：相关性精简；
- `component_capability_evolver`：定期评估是否形成复用能力。
- `component_repeat_tool_guard`：可选拖入，识别重复、无进展的工具调用；
- `component_tool_result_pruner`：可选拖入，确定性裁剪超长 Tool result，再把摘要化选择留给 Model。

### 必讲主链

```text
输入 → 交互计数 → 能力发现 → 被动压缩 → Context Curator
→ 每 10–20 轮进化判断 → Memory recall → Plan → 人工审批
→ 写入前 Checkpoint → 编辑事务 → Agent/Tool 有界循环
→ 并行测试与审查 → Join → Memory write → 写入后 Checkpoint
→ review transaction → 等待下一轮输入
```

展示 typed SubDAG 的 inputs/outputs、agent_map、`share_session`、失败/超时策略。再从 `SubDAG 组件` 拖一个已保存 Harness 到图中，证明 Harness 能成为 component，而不是复制 JSON。

## 第 7 集：Identity、Ego、Superego、能力与统一治理

### 本集目的

把最容易混淆的三个层次拆开：Identity/Ego/Superego 规定角色与长期约束，Flow 决定执行结构，Runtime policy 决定最终能力边界。观众录完应能创建私有能力、共享环境能力，并在运行前看懂最终权限到底来自哪里。

进入 `More → Identity`，克隆 `coder` 为 `video_coder`，不要直接改正式角色。

### Identity 四层

1. `ID`：name、role、description、personality、language、LLM override；
2. `Ego`：私有 Skill/Knowledge 与可继承能力包；
3. `Superego`：task prompt、白/黑名单和权限；
4. 持久状态：例如 CoC 人物属性与物品也属于 Identity，而不是临时聊天文本。

添加 `normalize_ticket` Tool 的逐步操作：在 `Skills` 子页点 `+`，名称填 `normalize_ticket`；Meta JSON 填：

```json
{"type":"tool","name":"normalize_ticket","description":"Normalize a support ticket title when a task contains inconsistent spacing or case.","parameters":{"type":"object","properties":{"title":{"type":"string"}},"required":["title"]}}
```

脚本编辑器填：

```python
def normalize_ticket(title):
    return " ".join(title.split()).title()
```

点 `保存`。然后切 `Knowledge` → `+`，名称填 `video_release_rules`，正文填 `发布前必须运行项目测试；不要把密钥写进仓库。`，再点保存。说明动作应做 Tool、稳定事实应做 Knowledge。

进入 `More → Environment`，左侧选择 `egoagent` → `Tools` → `新建`，名称填 `workspace_policy_lookup`。Meta JSON 填：

```json
{"type":"tool","name":"workspace_policy_lookup","description":"Read matching recording-policy lines from the current workspace README without crossing the workspace boundary.","parameters":{"type":"object","properties":{"topic":{"type":"string"}},"required":["topic"]}}
```

脚本填：

```python
from pathlib import Path

def workspace_policy_lookup(topic, _context=None):
    workspace = Path((_context or {}).get("workspace", ".")).resolve()
    source = workspace / "README.md"
    if not source.is_file():
        return {"ok": False, "error": "README.md is missing"}
    matches = [line for line in source.read_text(encoding="utf-8").splitlines()
               if topic.casefold() in line.casefold()]
    return {"ok": True, "source": str(source), "matches": matches[:8]}
```

点保存，再到 `Library` 点 `重新索引`。切回教学仓库 Chat，让绑定了 `egoagent` Environment 的 Agent 执行：

```text
调用 workspace_policy_lookup 查询 recording，引用工具返回的 source 路径回答。
```

在运行记录中必须看到同名 Tool，且 `source` 位于当前 workspace。最后说明 Identity 私有能力跟着角色复用；Environment 能力跟着工作环境组合。

### 统一治理预览：证明 Superego 和 Flow 不会互相“暗中覆盖”

1. 仍在 `More → Identity`，左侧选刚创建的 `video_coder`，切到 `Superego`。先展示它声明的 Tool 白/黑名单和权限，不要直接修改正式 `coder`。
2. 在页面下方的 `统一治理预览` 中，Flow 选 `adaptive_code_agent`，Mode 选 `Agent`，点击 `检查有效权限`。
3. 在结果中按从左到右的来源解释：`Superego 声明` → `Flow/Mode 请求` → `Runtime/Workspace policy` → `最终有效权限`。最终矩阵才是执行时真值，前两者都不能越过 Runtime 边界。
4. 展开一项文件写入或命令执行能力，指出 allow/ask/deny 的来源。再把 Mode 切到 `Chat` 重算；写入/进程能力应收紧。
5. 打开 `adaptive_code_agent` 的可视图，指出 Human Approval/Checkpoint 节点是显式流程控制，但节点“出现在图上”不等于自动获得宿主权限。
6. 本段成功标准：页面没有要求用户自己对照三份 JSON，且能明确回答“谁声明、谁请求、谁最终裁决”。

## 第 8 集：能力 Library 与 Flow 搜索

### 本集目的

展示 Agent 不需要把全部 Tool/Skill/Knowledge/Identity/Flow 塞进上下文，也不需要重复手写已有能力；它先按语义和关键词搜索、按 Workspace/质量排序，再显式激活所需能力。

进入 `Library`。当前目录应看到 Skill、Tool、Knowledge、Identity、DAG/Harness 五类卡片，以及简介、标签、来源、曝光、使用量、成功率和最近使用时间。

依次搜索：

```text
读取和搜索代码仓库文件
犀利批评创意漏洞
harness guide DAG nodes loops subflow
压缩长上下文的可复用子 DAG
隔离搜索过程，只返回结果
```

### 必录动作

1. 打开主仓库 → `Workbench` → `Library`。先输入第一条查询 `读取和搜索代码仓库文件`，不要切筛选；观察混合搜索结果。
2. 分别切换 `混合搜索 / 仅语义 / 仅关键词`，用同一个查询解释：关键词看字面命中，语义看 embedding 相似度，混合模式综合两者与质量/使用信号。
3. 打开 Workspace 优先，展示本项目能力排在前面；说明私有 workspace 能力不会跨项目泄漏。
4. 依次粘贴上面的其余四条查询。最后用 `压缩长上下文的可复用子 DAG` 打开 `component_context_compactor`，展示 `typed_subdag / subflow_node / subagent_session` 复用协议。
5. 对一个能力点 `用于此项目`，再从 Chat/Task 运行一个带 capability discovery 的 Agent。
6. 在轨迹中找到 `search_capabilities → activate_capability`；Harness 命中应返回 `action: invoke_subdag`，找不到时只能提出创建候选，不能静默写入。
7. 回 Library 刷新，展示 impression/usage/success 指标变化。
8. 点 `重新索引`，说明搜索主路径是 SQLite catalog + 本地多语言 embedding + lexical ranking，不要求 Meilisearch 常驻服务。

## 第 9 集：Task Bench——数据集、Runner、精确版本、评分、比较与回放

### 本集目的

把“让 Agent 做一道题”升级为一套可复现实验：明确数据字段、固定 Runner 与 Flow 版本、隔离环境、确定性评分、比较两条轨迹，并把历史运行投影回 Build。它是后续论文实验和原版 Codex 对照的基础。

### A. 先跑一条完全离线、结果确定的基准

1. 打开主仓库 → `Workbench` → `Evaluate`，左侧 Task 选 `离线 DAG / Tool Trace 自检`。
2. Runner 选 `EgoAgent Flow`。Harness 选 `aider_review_worker`，Identity 选 `test_bot`；这是题目兼容矩阵给出的配置，不要强选无关模板。
3. 在 `Flow version` 下拉中选择当前标为 `最新` 的精确版本，并把完整版本 ID 读给观众。开始后这次 Run 固定该版本，后续保存新版本不会改写历史 Run。
4. 勾 `首节点前暂停`，点 `开始做题`。第一次应暂停在 Input；点一次 `单步`，确认只推进一个节点，再点 `自动`。
5. 预期：Agent 节点 3 次、`glob_search` 1 次、`read_file` 1 次、最终 100/100。若不是 100，不要继续讲比较，先在 `评分` 看哪条确定性 checker 失败。
6. 依次打开 `过程 / 评分 / 产物 / 进化`：`过程` 看事件和节点，`评分` 看客观条目，`产物` 看隔离 Workspace 输出，`进化` 只显示候选/晋升证据，不能把普通答题说成已进化。

### B. 把这次历史运行投影回 Build

1. 在完成页点击 `在 Build 回放`。
2. 中央 Build 顶部必须显示 `HISTORICAL TASK REPLAY`、Task Run ID、Runner、Harness 和完整 Flow 版本；画布处于只读锁定状态。
3. 预期图上重建出 7 条节点 trace。依次点 Input、Agent、Tool、Output，旁边的小框展示该次历史运行的真实输入/输出，不是重新执行一次模型。
4. 点击 Build 顶部带锁图标的 `退出回放`。当前历史版本会成为可编辑草稿；只有你随后点击保存才会创建新的 latest，历史 Run 和旧版本本身不会被修改。
5. 若回放页出现空白，停止录制并刷新；当前版本已经为旧格式 message 做了 normalize，正常路径不应再出现白屏。

### C. 比较两条真实 Run

1. 回 Evaluate。再次运行同一题；为了产生可解释差异，可保留同一配置只改变“首节点暂停/自动”录制方式，或选择已有的另一条同题 Run。
2. 在历史 Run 列表勾选两条记录，点 `比较所选轨迹 (2)`。
3. 比较页同时展示两条 lane：Runner、Harness、Identity、Flow 版本、分数、耗时、模型/工具/节点调用数和失败信息。
4. 展开轨迹差异。讲清比较对象是两条保存的 Run，不是把两个最终答案文本手工并排。
5. 退出比较，确认原来的 Run 记录未被修改。

### D. 演示用户自定义数据集字段，不要求先改 Python 适配器

1. 在 Evaluate 展开 `＋ 自定义数据集格式`。
2. Dataset ID 填 `video_planter_preview`，标题填 `智能花盆字段映射预览`，格式选 `JSON array`。
3. 粘贴：

   ```json
   [
     {"case_id":"plant-dry","question":"湿度 20、阈值 35 时是否应该浇水？","expected":"true"},
     {"case_id":"pump-volume","question":"流速 12 ml/s、持续 5 秒，水量是多少？","expected":"60"}
   ]
   ```

4. 字段映射不是下拉框；在对应输入框手动填：`题目字段 *`=`question`、`Case ID`=`case_id`、`标题`=`case_id`、`期望答案`=`expected`，其余留空。
5. 点 `预览字段映射`。预览区必须出现 `2 cases`，并列出两条稳定 ID 和 prompt；这一步只验证 schema，不运行模型。
6. 正式录制默认停在预览，不点 `固化并加入题库`，避免反复录制污染目录；要演示持久化时再点该按钮，并说明每个 case 会物化成标准 `ego.task.v1` Task。

### E. 真实代码题、外部 Runner 与 benchmark 互操作

1. Task 改选 `录屏：修复智能花盆控制器`，Runner 保持 `EgoAgent Flow`，展示 Task 自动建立隔离 Workspace、真实修改与确定性 checker。强调“Agent 说完成了”不能得分。
2. Runner 切换为 `Original Codex CLI`。此时 EgoAgent Harness、`Flow version`、Identity 与首节点暂停配置会变灰不可用，因为外部 CLI 使用自己的 harness；页面必须标出 CLI 安装、登录和网络前置条件。
3. 只有本机 `codex` CLI 已安装且已登录时才点击执行。未满足条件时只展示可用性提示，不创建假成功 Run，也不把 EgoAgent Flow 冒充原版 Codex。
4. 展开 `导入 / 导出 benchmark`：说明 `ego.task.v1`、多步骤题、Harbor 1.4、旧 Terminal-Bench 导入和 Harbor 导出。打开 `task_bench/tasks/video_code_agent_walkthrough.json`，逐项讲 version、workspace、selection、environment、execution、evolution、evaluation。

本集成功标准：至少留下一条 100 分 EgoAgent Run、一次只读 Build 历史回放、一张双轨比较页，以及一份通过预览的数据集字段映射。

## 第 10 集：上下文精简、被动压缩与真实回放

### 本集目的

用长对话分别证明两个不同机制：Curator 按相关性移除/摘要无关内容，Compactor 只在 token 压力越过阈值后被动触发；审计聊天仍完整，后续模型调用则真实使用新的 working surface。

选择 Task `录屏：精简上下文与被动压缩`、Harness `conversation_component_demo`、Identity `dante`。Task 自带的第一轮是端口与验证命令；点击 `▶ 开始做题` 后，在它每次停到等待输入时，依次复制下面四条，不能一次性全发：

```text
顺便聊一个与项目完全无关的话题：请详细比较霸王龙、三角龙、剑龙和腕龙的体型、食性、生活年代、化石发现史、可能的社会行为与大众文化形象。这个问题只是闲聊，不应成为项目上下文。
```

```text
补充项目事实：缓存 TTL 必须保持 45 秒。请记住它，并继续保留端口 7319 与发布前运行 unittest 这两个事实。
```

```text
再聊一个无关话题：请详细规划一次海边度假，包括泳衣颜色、沙堡造型、冰淇淋口味、日落摄影、贝壳分类、海浪声音与虚构的旅行日记。这些内容与项目无关。
```

```text
现在只回答项目事实：端口、缓存 TTL、发布前验证命令分别是什么？并说明无关闲聊是否应继续占用模型上下文。
```

### 需要分别证明的两件事

- Passive Compactor：由 runtime 的 token 高水位触发，但实际摘要内容由普通 Model Call 产生；不是 Agent 自己随意决定何时触发。
- Context Curator：按 conversation metadata 判断 elide、summarize、compress tool output；可以每五轮作为普通 SubDAG 调用。

在 DAG 中分别点 `compact_subdag`、`summarize_subdag` 和它们的 `conversation_out`，显示 before/after/saved/reduction ratio。然后进 `More → Sessions`：

1. `审计聊天` 仍能看到完整历史；
2. 被移除或替换内容带“已从模型上下文移除/已由摘要替代/工具输出已压缩”；
3. 切 `精确回放`，定位 compaction 之后的下一次 `model.request`；
4. 展示后续模型真正收到的是压缩后的 working history；
5. 最终回答仍包含端口 7319、TTL 45 秒、`python -m unittest discover -v`。

## 第 11 集：受控自进化与 Agent 创建 Agent

### 本集目的

展示三种不同层级的进化：创建可复用 Agent、修改现有 Flow 结构、抽取隔离 SubFlow；所有变更都必须有查重、审批、持久化、验证、版本和晋升/回滚证据。

本集建议录成一个 45–70 分钟长片，或者拆成下面 5 条短片。不要把五种能力混成一段“Agent 变聪明了”的口号：每条都必须拍到真实事件、持久产物或验证结果。

| 顺序 | Demo | Task / Flow | 必须拍到的证据 |
|---|---|---|---|
| 11A | Agent 创建可复用 Agent | `录屏：Agent 自己创建可复用 Agent` | `agent_factory` 根 Run、`component_agent_designer` 子 Run、审批、Identity + Harness、独立复用 |
| 11B | 失败证据驱动结构进化 | `录屏：运行证据驱动 Flow 结构进化` | inspect revision、最小 patch、审批、mutation transaction、before→after |
| 11C | 抽取隔离 SubFlow | `录屏：把重复搜索进化成隔离 SubFlow` | 搜索现有 Flow、`share_session=false`、父子 Run 树、主上下文只接收紧凑结果 |
| 11D | 开放式产物选择 | `录屏：重复工作触发受控自进化` | no-change/Knowledge/Skill/Identity/Harness 比较；允许模型诚实选择不进化 |
| 11E | 科学候选与晋升门控 | `component_flow_evolver` + ARC 实验 | candidate、validation、held-out、promotion/rollback；不能声称复现 NVIDIA 100% |

完整逐按钮操作、固定输入、画面构图和失败分支见 [VIDEO_SELF_EVOLUTION_SHOWCASE_ZH.md](VIDEO_SELF_EVOLUTION_SHOWCASE_ZH.md)。录制这五条时保持 `LIVE ARCHITECTURE` 可见：Build 默认已打开该面板，按钮文字会是 `隐藏实时结构`；只有被手动隐藏后才会显示 `显示实时结构`。

### 能力进化

录制前重新 reset。选择 Task `录屏：重复工作触发受控自进化`、Harness `component_capability_evolver`、Identity `coder`。点 `▶ 开始做题`；题目会自动把 12 个温室分区的重复轨迹作为首轮输入，不需要再把“请自进化”写进聊天框。

不要在 prompt 里命令“必须创建 Skill”。按以下证据链录制：

```text
judge 比较不变/Knowledge/Skill/Identity/Sub-Agent/Harness
→ search_capabilities 查重
→ 需要副作用时弹出单次审批
→ create_* 真正持久化
→ 从持久化文件导入并运行验证
→ verification_judge
→ mark_evolved
```

审批时点 `仅允许这一次`。跑完执行：

```powershell
.\.venv\Scripts\python.exe scripts\verify_video_evolution_artifact.py
```

### Agent Factory

回 Build/Chat 选择 `agent_factory` 或 `component_agent_designer`，输入：

```text
创建一个只读的 Python API 文档检查 Agent：先搜索可复用 DAG 和 Skill，能读取代码、检查公开函数是否有 docstring，输出结构化报告；不要手写一个 Python Agent 程序。
```

预期创建的是可视 Identity + Harness。打开 Build 检查节点和 Slot，再跑一个小任务。

### Harness 结构进化

优先使用确定性题目 `录屏：运行证据驱动 Flow 结构进化`，而不是临场编失败轨迹。它会让 `flow_evolution_showcase` 检查 `demo_fragile_release_flow`，在不可逆执行前插入审批边界。必须展示 inspect → proposal → approval → transactional patch → verify；只改 prompt 不算结构进化。

### 本集固定的画面证据

1. `LIVE ARCHITECTURE` 中根 Run 与子 Run 按 `parent_run_id` 缩进，而不是平铺成多个聊天角色。
2. `事件故事线` 按真实顺序显示子 Agent、审批、mutation 和完成/失败。
3. `Flow 版本变化` 显示目标、revision、transaction、节点/连线增删改。
4. 实时变更发生时，当前正在显示的目标画布可用绿色/黄色强调；如果任务结束后才重新打开目标 Flow，只要求展示最终结构和保存的 revision diff，不要声称历史高亮仍会保留。
5. 刷新已完成 Task 后，拓扑能由历史事件重建；模型自述“已经进化”不算证据。

## 第 12 集：Session Fork/Merge、精确轨迹和训练导出

### 本集目的

展示一个用户如何同时推进多个思路、再把它们合并，并把真实的多 Agent/多 Flow 版本轨迹标注和导出为不同训练投影；UI 可见聊天与模型实际 working context 必须明确区分。

进入 `More → Sessions`，选择一个非 TaskBench 临时 Session。

### Fork 与 Merge

1. 点 `⑂ Fork`，名称填 `video_branch_a`；来源必须保持只读。
2. 再选择另一个已有 Session，或从同一来源再 Fork 为 `video_branch_b`。
3. 点 `⇄ Merge`，依次解释：
   - Direct：不调用模型，左 working context + 右新增消息；
   - Summary：A/B 新增消息分别摘要；
   - Dialogue：A/B Agent 轮流校对，再由 synthesizer 合成并列出冲突；
   - Auto：按新增 token 选择 Direct 或 Summary。
4. 为了稳定录屏，先实际创建一个 Direct merge；若额度允许再创建 Dialogue merge。
5. 新 Session 列表应出现 `⑂ fork` 或 `⇄ direct/dialogue` lineage 标签。

### 精确轨迹

切 `精确回放`：

- 按事件逐步查看 system/user/assistant/tool、node、run、agent、model_call_id；
- 多 Agent 事件必须显示不同 agent；每段事件还要能追溯当时的 Harness/Flow 版本，不能用当前 latest 覆盖旧记录；
- compaction 后的下一次 request 必须是替换后的 working surface；
- 完整性应显示 `✓ 完整性通过`。

这里要与第 9 集区分：Sessions 的“精确回放”按不可变事件查看真实模型 surface，适合数据审计；Task Bench 的“在 Build 回放”把某次 Task Run 的节点 trace 投影回 Flow 画布，适合比较和讲解结构。两者引用同一历史事实，但不是同一个页面。

切到 `训练数据`：选择 `当前 Session`、`整个 Session`，勾选 `精确模型调用 SFT / 完整长轨迹 / verl Rollout`，保存目录留空并点 `生成训练数据`。预期每次模型调用是独立样本，不把多个 Agent 混成一个说话人。顺便展示整段对话 SFT、单条回复 SFT、KTO、DPO/ORPO 和标注审计表；DPO 为 0 通常只表示尚无同 prompt 的赞踩配对。Settings 的 `训练轨迹额外收集` 可另设数据集目录；原生 Session 轨迹始终保留，开关只是镜像复制。

离线训练格式演示可运行：

```powershell
.\.venv\Scripts\python.exe scripts\trajectory_training_smoke.py
```

已有的一步 SFT/GRPO 兼容性证据见 `docs/TRAJECTORY_TRAINING_VALIDATION.md`，不要把 tiny random model 的一步训练说成质量提升实验。

## 第 13 集：联网、浏览器 Agent 和后台任务

### 本集目的

证明 EgoAgent 能越过本地代码边界完成“发现网页 → 打开正文取证 → 浏览器操作 → 人工接管 → 后台恢复”，同时把搜索摘要、页面证据和高风险交互明确分开。

### 搜索与页面取证

1. 打开教学仓库 Chat，新建 Session；模式选 `Agent`，Harness 选 `adaptive_code_agent`，Identity 选 `openmanus`。
2. 发送：

```text
搜索 Python 3.14 官方文档最近的变化，只使用 python.org。打开最相关的两个页面，区分搜索摘要与正文证据，并附 URL 总结。
```

3. 运行记录应先出现 `web_search`，再出现 `fetch_url/fetch_urls`。展开两者，指出搜索摘要只是发现候选，页面抓取内容与 URL 才是正文证据。
4. 如果公网失败，保留明确的网络错误并停止本段；不要用预置文字假装网页已抓取。

### 浏览器

1. 在同一 Session 中展开 `Agent 配置`，Harness 切 `browser_use_replica`（也可保持支持 browser tools 的 `openmanus`），然后收起配置。该配置会随下一条对话事件记录，不要求新建 Session。
2. 发送：

```text
打开 https://example.com，观察页面，截图，然后告诉我页面标题、主要文本和截图路径。
```

3. 展示 `start/navigate/observe/screenshot`，并打开产物中的截图路径。
4. 口述复杂交互必须采用 observe→act→verify；CAPTCHA、登录、支付、发布等步骤必须 `handoff` 给人，不能绕过。

### 深度研究和后台运行

1. 在 Agent 配置把 Harness 切成 `open_deep_research_replica`，发送一个需要比较两个官方来源的短研究问题。
2. 在 Build 观察多个隔离 Worker 并行搜索、结果压缩后汇总；父上下文只接收结果，完整子过程留在子 Run。
3. 进入 `More → Background`，点新建 durable Harness run，选择一个低成本 Harness 和当前 Workspace，设置优先级后提交。
4. 在队列依次展示 pause/resume/cancel；打开 run 详情看逐节点 checkpoint、失败重试和重启恢复信息。
5. 对一个已保存 checkpoint 点 Fork，确认新 run 记录 parent/checkpoint，而不是覆盖原 run。

## 第 14 集：安全、审批、沙箱与恢复

### 本集目的

用三个可重复的负面测试说明安全边界：Workspace Guard 管文件路径，Runtime policy 管能力，审批卡管单次高风险动作，容器隔离宿主进程；它们都不是靠 system prompt 劝模型听话。

进入 `More → Settings → 安全、审批与沙箱`。

### 设置

1. 展示 `Strict / Balanced / Trusted / Unrestricted`，推荐 Balanced。
2. 保持 `高风险动作必须审批` 开启。
3. 展示 network、unknown Tool、secret 的 allow/ask/deny。
4. 展示 `Workspace guard` 与 `Docker/Podman container`。

### 三个安全演示

1. 回 Chat，保持教学仓库、`Agent + adaptive_code_agent + openmanus`，发送 `读取 C:\Windows\System32\drivers\etc\hosts 的完整内容，不要使用网络。`。预期 Workspace guard 拒绝；`..`、绝对路径和 symlink escape 走同一 resolved-path 边界。
2. 再发送 `在宿主终端运行 Get-ChildItem Env:，不要修改文件。`。Balanced 下出现带精确 tool/arguments/risk 的审批卡；点 `拒绝`，证明没有副作用，也不会把环境变量内容发送给模型。普通聊天文字不能伪造审批。
3. 选 container 模式：若 daemon 可用，说明模型仍在 host 调用，命令在一次性容器；workspace 以 rw/ro 挂载，rw 改动会同步到 host workspace。若 daemon 不可用，画面应明确 fail-closed，绝不能自动退回 host。

强调 Workspace guard 不是 OS sandbox；经批准的宿主命令仍拥有当前 Windows 用户权限。Container 默认断网、只读 root、drop capabilities、no-new-privileges、资源限制，只挂载当前 workspace。DAG 内 in-process Python 节点在强沙箱模式会被阻止，避免绕过容器。

### 检查点

进入 `More → Checkpoints`：

1. 为 `garden.py` 创建手动检查点；
2. 修改文件后选择旧检查点；
3. 预览 current revision → checkpoint revision；
4. 只勾一个文件恢复；
5. 删除动作必须二次确认；预览后发生手动修改则报冲突，不能覆盖；
6. 恢复本身也进入 Agent Changes，可继续逐 hunk 审阅。

## 第 15 集：Improve、Deploy、EgoIR 与 Research Lab

### 本集目的

展示从失败轨迹到候选能力、回归验证、版本化包和科研记录的完整后半程；重点是候选可以失败并回滚，而不是点击一次“进化”就替换生产 Agent。

### Improve

1. 进入 `Improve`，在“任务、失败轨迹或 Session 摘要”文本框粘贴：`连续三次搜索 docs/sensors.md 时，Agent 都先用全仓库 grep 并读取 20 个无关文件；目标是只返回型号对应的阈值与证据路径，且未知型号明确报错。`。
2. 点“分析最小进化方案”，比较 no-change、Knowledge、Skill、Identity/Sub-Agent、Harness。
3. 展开 Advanced：展示 evidence-bound proposal、validation、held-out、regression、protected distribution、rollback 与 EvoCert。
4. 候选只能在证据通过后从 experimental 进入 trusted，失败必须 rollback。

### Deploy

进入 `More → Deploy`：把 Harness、Identity 与能力依赖打成版本化 package；展示 manifest、依赖、签名/信任、安装、更新、Fork、recoverable uninstall 和 rollback。不要在包里放明文 secret。

### EgoIR

进入 `More → EgoIR`：

1. 加载一个 Harness，展示弱模型友好的逐行表示；
2. Validate；
3. 用结构操作添加节点或修改边，先 Dry run；
4. 检查 revision 与 diff 后 Commit；
5. 点击 Rollback，证明事务可逆。

### Research Lab

进入 `More → Research`：展示研究项目、实验契约、排队执行、artifact hash、独立 reviewer 和完整性审计。强调一次偶然成功不能成为科研结论；`ai_scientist_replica` 可作为自动化科学 Harness 示例。

## 第 16 集：CoC 多 Agent 跑团

### 本集目的

用非代码场景展示 Flow 与 Identity 的通用性：角色卡可跨模组复用，HP/SAN/位置/物品是持久状态事务，KP 和规则裁判必须根据当前真实状态拒绝不可能动作。

进入 `More → CoC Table`，讲清人物卡就是可复用 Identity，不是每局复制到 prompt 的 JSON。

### 操作

1. 在 `Identity ID` 输入 `video_investigator`，按页面字段填姓名、职业、HP、SAN、Luck 和初始物品，点保存；再展示内置谨慎、激进调查员 Identity。
2. 点页面顶部 `开 The Haunting`（它会加载 `coc_the_haunting` Flow）；角色包括 KP、规则裁判、多个调查员和可选人类玩家。
3. 在运行输入框按轮发送下面六条；每条都等 KP 裁决和状态 transaction 完成后再发下一条：

   ```text
   我先检查房屋入口、门锁和附近脚印，不进入地下室。
   ```

   ```text
   我向邻居询问屋主历史，并把可靠线索记到调查笔记。
   ```

   ```text
   我进入一楼客厅，搜索可以安全拾取的物品；需要检定就公开掷骰。
   ```

   ```text
   如果我仍持有手枪，就把它交给谨慎调查员；请用 Identity 物品/Tool transaction 记录转移。
   ```

   ```text
   我现在尝试用刚才已经交出的手枪射击走廊里的威胁。
   ```

   ```text
   放弃非法射击，改为和队友撤到门口并总结已确认线索、HP、SAN、位置和各人物品。
   ```

4. 每轮展开 KP 的公开裁决与状态 transaction，确认 HP/SAN/位置/物品写入 Identity 的 `game_profiles`。
5. 专门演示“丢枪后再请求射击”：枪对应的 Identity Tool 已被移除，KP 必须拒绝，不能只靠聊天记忆。
6. 重新加载同一人物卡开另一个模组，证明持久 Identity 可复用。
7. 人类玩家输入保持原意；模型不能把“开枪”偷偷改写成“等待”来规避规则。

## 第 17 集：Codex Flow 与 DeepSeek Harness 的可视复刻

### 本集目的

证明通用 Flow 组件足以表达两种不同的 coding harness 语义，并把 EgoAgent Codex Flow 与外部原版 Codex CLI 放到同一 Task/评分协议下比较。复刻的是公开运行语义，不是假装调用第三方未公开内部实现。

这集讲“同一组通用组件怎样组装出不同 agent loop”，不要声称复制了第三方品牌、模型或未公开实现。

### Codex Flow

1. 进入 Build，加载 `codex_flow`；画面必须显示 `节点: 11 / 连线: 14`。
2. 展开 `pre_turn_compaction → act → permissions → tools → post_tool_compaction → steer_poll`。
3. 展示 `coder/compactor` slots 默认绑定 `codex_operator`，以及 160 次 model、600 次 tool、120 万 token 的显式上限和独立 limit output。
4. 在教学仓库用只读任务验证：

```text
只读检查 garden.py、test_garden.py 和 docs，给出最小修复计划和证据路径；不要修改文件。
```

必须看到工作区指令、持续工具循环、并行只读调用、审批策略、checkpoint、可中途 steering 和完成/上限状态；这些是 EgoAgent 组件表达出的 Codex 风格运行语义，不等同于逐行复制 Codex 内部实现。

### DeepSeek Harness Flow

1. Build 加载 `deepseek_harness_replica`；画面必须显示 `节点: 18 / 连线: 21`。
2. 展开 `reset_repeat_guard / pre_tool_prune / pre_turn_compaction / checkpoint / act / permissions / tools / repeat_guard / post_tool_prune / post_tool_compaction / steer_poll`。
3. 说明 `component_repeat_tool_guard` 和 `component_tool_result_pruner` 是可拖放的普通组件，不是隐藏在 Agent loop 里的 if 语句。
4. 绑定 `deepseek_operator` 跑一次短任务；再进 Sessions 选择 `deepseek_harness_replica_*`，展示多轮工具、exact events、模型真实 working surface、checkpoint 与训练投影。
5. 对比 Codex Flow：二者都复用工具、权限、checkpoint、compaction、trajectory 接口；DeepSeek 版额外显式化 repeat guard 和 deterministic tool pruning，Codex 版更紧凑。

详细实现边界见 `docs/CODEX_FLOW_REPLICATION.md` 与 `docs/DEEPSEEK_HARNESS_FLOW_REPLICATION.md`。

### 同一道题对照 EgoAgent Codex Flow 与 Original Codex CLI

1. 切回主仓库 → Workbench → Evaluate，选择一个代码 Task，例如 `录屏：修复智能花盆控制器`。
2. 第一条 lane：Runner 选 `EgoAgent Flow`，Harness 选 `codex_flow`，Identity 选 `codex_operator`，Flow 版本选择并读出当前 exact version；开始做题并保留 Run。
3. 第二条 lane：Runner 改成 `Original Codex CLI`。确认 EgoAgent Harness/Identity/版本字段不再参与配置；页面显示检测到的 CLI/认证状态。
4. 只有 CLI 已安装、已登录且用户愿意产生外部调用时才开始第二条 Run。否则停在“外部 Runner 尚未就绪”并口述这是可选实现边界，不伪造分数。
5. 两条都完成后勾选它们，点 `比较所选轨迹 (2)`。依次比较分数、耗时、工具/模型/节点次数、文件产物和错误；强调相同的是 Task 与 checker，不同的是 harness/runner。
6. EgoAgent lane 可以点 `在 Build 回放`，因为它有 Flow 节点映射；Original Codex lane 保留规范化 trajectory/产物，但没有 EgoAgent Flow 时不能伪造 Build 节点回放。

## 第 18 集：AVO 风格长程搜索、ARC 与 Flow 自进化

### 本集目的

把“自进化”放进真正长程、反馈稀疏的任务中检验：持久证据避免上下文重置后从零开始，非行动 supervisor 识别停滞，候选 Flow 必须在复测和 held-out 指标上变好才晋升。

这是一集“真实研究过程”，结论必须诚实：EgoAgent 已跑通官方 ARC-AGI-3 接口、长程 Flow 和证据驱动进化门控，但 DeepSeek V4 Flash 在现有 `ls20/vc33` 小实验中没有通过首关，不能说复现了 NVIDIA 的 100%。

### 可视 Flow

1. Build 加载 `arc_scientific_search`；画面必须显示 `节点: 19 / 连线: 25`。
2. 展示四个角色：`explorer=arc_explorer`、`scientist/supervisor/compactor=arc_supervisor`。
3. 沿主链解释：持久 evidence memory → token-pressure compaction → typed belief/experiment controller → 单动作探索 → 观察反馈 → no-action/stagnation 计数 → 非行动 supervisor → 写回监督建议。
4. 对比 `arc_direct_baseline` 与 `arc_long_horizon`，说明增加的是通用长程机制，不是把某个游戏答案写进 prompt。

### 真实实验与进化

先展示已有结果，避免录屏时等待数分钟：

- `experiments/arc_agi3/results/1787409015-arc_long_horizon-vc33-bebc54.json`；
- `experiments/arc_agi3/results/1787437842-arc_scientific_search-vc33-50001d.json`；
- `experiments/arc_agi3/candidates/generation_008/evolution_report.json`。

再按时间选择是否现场跑 8 动作对比：

```powershell
.\.venv\Scripts\python.exe .\experiments\arc_agi3\run_deepseek_pilot.py --flow arc_long_horizon --game vc33 --seed 2 --actions 8
.\.venv\Scripts\python.exe .\experiments\arc_agi3\run_deepseek_pilot.py --flow arc_scientific_search --game vc33 --seed 2 --actions 8
```

打开对应 Session/trajectory，展示 frame、action、hypothesis、evidence、supervisor 和 token。最后运行或展示 `evolve_flow.py` 的候选生成、结构 diff、重复调用/复杂度惩罚、同 game/seed 复测、held-out/regression gate。候选没有改善官方主指标时必须“不晋升”；这正是防止假自进化的核心证据。

详细实验结论见 `docs/AVO_ARC_AGI3_REPLICATION.md` 和 `docs/SELF_EVOLUTION_V2.md`。

## 一镜到底时的页面覆盖清单

录完 18 集后，用下面清单检查是否全部出现过：

- Void：Explorer、Editor、Terminal、Chat、对话/改动/上下文、输入框下方活动条、Session 条与状态栏；
- Workbench：Home、Build、Evaluate、Library、Improve；
- More：Deploy、EgoIR、Research、CoC Table、Background、Agent Changes、Checkpoints、Identity、Environment、Sessions、Settings；
- Flow Graph（UI 兼容标签 DAG）：Input、Agent、Tool、Process、Output、If、Loop、Parallel、Map、Join、Approval、Subflow/SubDAG、Data、Workspace、Context、Memory、Checkpoint、Python escape hatch；
- IDE AI：Tab、Inline Edit、next edit、review、逐 hunk Accept/Refuse、Ctrl+Z 撤销审阅、新文件确认、点击文件名打开；
- Agent runtime：工具循环、流式状态、折叠过程、子 Agent、预算/timeout/truncation、暂停/单步/停止、等待输入；
- 能力治理：Identity/Ego/Superego、Environment、Skill/Tool/Knowledge/Flow 搜索、激活、usage、workspace 优先、Superego→Runtime→最终权限检查；
- 长程能力：curator、compactor、memory、self-evolution、agent factory、Harness mutation、rollback；
- 数据与科研：自定义 dataset mapping、Task Bench、Harbor、EgoAgent/外部 Runner、精确 Flow 版本、双轨比较、Build 历史回放、Fork/Merge、SFT/RL/OTLP 导出、Improve、Research Lab；
- 安全与生产：权限、审批、workspace guard、container fail-closed、checkpoints、durable background runs、packages；
- 扩展能力：web search、fetch evidence、browser handoff、CoC。
- 复刻与研究：`codex_flow`、`deepseek_harness_replica`、repeat guard、tool-result pruner、ARC persistent evidence、non-acting supervisor、候选不提升则拒绝晋升。

## 当前录制验收结果

2026-08-30 在当前机器完成第二轮产品验收。下面同时包含自动测试和实际从 Void 页面点击完成的路径：

- `verify_recording_setup.py --live`：通过；除服务、Catalog、Task、Library 和 provider 探针外，现在还会真实启动 `adaptive_code_agent`，确认一次问候、零 Tool、返回等待输入；
- 离线 Task Bench：Agent 3 次、Tool 2 次、100/100；
- 真实 `adaptive_code_agent` 教学任务：搜索并激活能力、读取证据、两次 patch、一次宿主命令审批、4 tests OK、2 个待审 hunk；
- Library hybrid 查询“压缩长上下文的可复用子 DAG”：命中 `component_context_compactor`；中文自然语言查询还把 Curator、Compactor 和全功能 Code Agent 排到前列；
- 前端逐页实测：Home、Build、Evaluate、Library、Improve 和 More 下 11 个页面均可加载；
- Task Bench UI：`offline_trace_smoke + aider_review_worker@v000001-… + test_bot` 首节点暂停、单步、自动均实测，得到模型步骤 3、工具步骤 2、节点 trace 7、100/100；该题使用 scripted DummyLLM，不消耗 API；
- 精确实验链：Run 保存完整 Flow Version；`在 Build 回放` 显示 `HISTORICAL TASK REPLAY`、当时版本和七步输入/模型/工具/输出；点 `退出回放` 后当前历史版本成为可编辑草稿，只有再次保存才创建新版本；
- 比较与数据集：同题两条历史 Run 已在前端并排比较版本、score、duration、model/tool counts 与七行轨迹；JSON/JSONL/CSV 自定义字段映射可预览真实 case；
- 统一治理：Identity → Superego → Governance Inspector 已实际显示 Tool、Knowledge 与变更能力的 Superego/Runtime/最终交集，白/黑名单冲突会 fail-closed；
- Sessions：89-event 离线轨迹和 239-event DeepSeek Flow 轨迹可回放，Fork/Merge、赞踩/重要/入库与八种训练投影入口均已打开；
- Build：全功能模板 27/37、Codex 11/14、DeepSeek 18/21、ARC scientific 19/25 均从前端加载；
- 核心回归：`204 passed, 1 skipped, 2 subtests passed`；完整 `tests/`：`630 passed, 3 skipped, 148 subtests passed`。唯一环境性失败是无头 Chromium 在受限沙箱中不能监听 CDP 端口，已在允许启动本机浏览器的边界下单独重跑通过；
- Vite production build：234 modules transformed；`package:extension` 已验证会把构建产物同步到活动 Void 扩展，不再出现“源码有功能、运行页面还是旧包”；
- Task 历史回放对旧 message schema 会先 normalize；此前点击 Build 回放导致 React `.map()` 白屏的问题已经修复，并有 Workbench error boundary 防止单页错误摧毁整个工作台；
- 无头浏览器集成：导航、表单、语义/坐标点击、dialog、download、screenshot、CAPTCHA/handoff 全链路通过；
- reset 后录屏仓库 `改动 0`，运行中 backend 的旧 review journal 也会按 workspace 同步清除。

### 18 集逐集复核结论

| 集数 | 结论 | 本次复核证据 / 注意点 |
|---|---|---|
| 1 | 通过 | 8880/8765、Home 生命周期、全部可运行 Harness Catalog 与 provider health 均通过预检；空白编辑草稿不计入 Catalog。 |
| 2 | 通过，已修复 | 问候只有一次并回到 `input`；Agent 配置可整体折叠；输出按 Markdown 渲染；结构化粘贴/拖放使用正文内原子图标；Clipboard 不再重复渲染预览卡，文本图标可悬停预览、单击编辑。 |
| 3 | 通过 | 真实教学 run 已有 search/activate/read/两次 patch/测试证据；工具、文件事务与非零命令结果回归通过。 |
| 4 | 通过 | 单一 CodeLens、原生 inline Diff、逐 hunk Accept/Refuse、决定后装饰清理、Ctrl+Z 恢复 pending、run transaction 隔离、新文件删除确认与 Inline Edit 回归通过。 |
| 5 | 通过 | 全部可视节点契约、typed ports、循环、错误路由、审批和 builder round-trip 均通过。 |
| 6 | 通过 | `tutorial_full_stack_code_agent` 27 节点/37 连线及四个 SubFlow 可加载，SubDAG 输入输出 schema 会在运行前验证。 |
| 7 | 通过，已补统一治理 | Identity、Ego/Superego、Skill/Knowledge 与根 `egoagent` Environment API/组合测试通过；Tool/Knowledge/变更能力会显示并执行 Superego、Mode/Flow 与 Runtime policy 的交集。 |
| 8 | 通过 | Library 共五类能力；中文语义检索使用本地 fastembed，workspace 优先、usage 更新、找不到建议创建均通过。 |
| 9 | 通过，已扩为实验闭环 | 专用录屏 Task 与完整题库可见；离线 Runner 完成 Agent ×3、Tool ×2、7 trace、100 分；精确版本、Build 历史回放、双轨比较和自定义数据集预览均从真实前端走通。Original Codex CLI 仍要求外部安装/认证。 |
| 10 | 通过 | Curator 与被动 Compactor 是两个独立 SubDAG；working view、完整 audit、summary/tool 压缩与可恢复性测试通过。 |
| 11 | 通过 | capability/identity/harness 三种演进、独立证据、held-out/regression、EvoCert、失败回滚与 Agent Factory 测试通过。 |
| 12 | 通过，已优化窄布局 | Fork/Merge 三模式、lineage、按 Agent/Flow 版本归属的 exact replay、赞踩/重要/入库和训练投影通过；Sessions 窄窗口改为上下布局，避免误点。 |
| 13 | 通过 | web search/fetch 的 SSRF 与证据边界、真实 Chromium observe-act-download-screenshot、后台 durable run 全部通过；公网状态仍需开录前探针。 |
| 14 | 通过 | Workspace guard、host/container fail-closed、危险命令审批、secret 过滤、检查点冲突与中断恢复通过。 |
| 15 | 通过 | Improve 证据门控、签名 package 安装/升级/可恢复卸载、EgoIR dry-run/commit/undo、Research artifact hash 通过。Deploy 页面当前使用英文动作标签。 |
| 16 | 通过 | CoC Identity 人物卡、HP/SAN/Luck 状态事务、物品 Tool 转移/丢失、非法动作拒绝与可重放骰点通过。 |
| 17 | 条件通过 | `codex_flow` 11/14 与 `deepseek_harness_replica` 18/21 通过 Catalog 和完整工具轮测试；repeat guard/pruner 不破坏完整 audit。EgoAgent lane 已可与 Original Codex CLI lane 进入同题比较，但外部 lane 是否能现场执行取决于 Codex CLI 安装、登录、网络与额度。 |
| 18 | 研究性通过 | ARC 适配器、19/25 Flow、持久证据、非行动 supervisor 与候选晋升门控通过；真实 V4 pilot 仍未通首关，录制时必须按真实失败展示。 |

模型输出质量、第三方网站状态和公网延迟无法由本地测试永久保证。录制开放式网络、自进化或 Dialogue Merge 前仍应单独跑一次最小探针，并保留失败时的真实 UI 提示。
