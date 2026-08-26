# EgoAgent 全功能视频系列总导演手册

更新时间：2026-08-24  
建议成片：18 集，合计约 6–8 小时。每集都可以独立发布；按顺序录制时，前一集产生的 Session、轨迹和改动可供后一集使用。

这套系列覆盖的是全部用户能力和每一种产品工作流，不要求把 65 个 Harness 逐个消耗模型跑一遍。目录结构与契约由录制预检和全量测试统一验收，第 3、6、9、11、13、17、18 集再选择代表性 Flow 实际运行。

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

每次开始拍摄前执行：

```powershell
.\.venv\Scripts\python.exe scripts\reset_video_demo.py --reset-evolution-artifact --reset-created-artifacts
.\.venv\Scripts\python.exe scripts\verify_recording_setup.py --live
```

第一条只恢复教学仓库、已知录屏产物和该仓库的旧审阅事务，不会清理其他项目。第二条会检查 8880/8765、65 个 Harness、教学文件、四个录屏 Task、关键 Identity/Environment、Flow/DAG 语义搜索、一次完全离线的 Agent×3/Tool×2 闭环，以及一次最小真实模型请求。只有看到 `RECORDING_SETUP_OK` 才开录。

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
3. `对话 / 运行 / 改动 / 上下文` 四个页签；
4. 当前页主体；
5. 最底部消息输入框、Agent 活动状态、`＠` 上下文按钮和 `发送`。

`＠` 不是普通文字按钮。点击后会出现三个明确选项：

- `@file`：把中间编辑器当前打开的文件插入光标位置；
- `@selection`：先在中间编辑器选中代码，再点它；
- `@workspace`：引用当前项目代码地图和检索范围。

三者都会成为输入框内的原子附件图标。文件/选区图标可点击并跳回来源；文本图标悬停显示内容摘要，单击会打开可滚动、可编辑的完整内容窗口。把光标放到图标右侧按 `Backspace`，或刚插入后按 `Ctrl+Z`，会一次删除整个附件，不会逐字删除 `[文本附件: ...]`。输入框上方不再重复显示任何 Clipboard 卡片。从 Explorer 或编辑器标签拖入的文件/选区也是同一种图标；右键 Explorer 文件点 `EgoAgent → Attach File to Chat`，或右键编辑器选区点 `EgoAgent → Attach Selection to Chat`，是同一数据通路的辅助入口。

## 18 集总览

| 集数 | 标题 | 建议时长 | 核心证据 |
|---|---|---:|---|
| 1 | 一体化 IDE、产品模型与服务体检 | 10–15 分钟 | 8880、实时连接、Home、preflight |
| 2 | 原生 Chat、六种模式与结构化代码上下文 | 15–20 分钟 | 活动状态、折叠过程、`file.py:line` 上下文卡 |
| 3 | Adaptive Code Agent 完成真实修复 | 20–30 分钟 | 读取、改文件、命令、测试证据、DAG 轨迹 |
| 4 | 编辑器内逐块 Accept/Refuse、Ctrl+Z 与 AI 编辑器 | 20–25 分钟 | 红绿高亮、CodeLens、新文件确认、Tab、Inline Edit |
| 5 | 从零搭一个可运行 DAG | 25–35 分钟 | 类型化端口、分支、循环、审批、暂停/单步 |
| 6 | 27 节点全功能 Code Agent 与 SubDAG | 30–45 分钟 | 四个组件、并行审查、事务、上下文与进化 |
| 7 | Identity、Ego、Superego、Skill、Knowledge、Environment | 25–35 分钟 | 可复用角色、私有/共享能力、真实 Tool 调用 |
| 8 | 像搜视频一样搜索 Tool/Skill/Identity/Knowledge/DAG | 15–25 分钟 | hybrid/semantic/keyword、workspace 优先、usage 更新 |
| 9 | Task Bench：题目、隔离、逐节点做题和确定性评分 | 25–35 分钟 | pause→step→auto、100 分、产物、Harbor |
| 10 | Context Curator、被动压缩与真实上下文回放 | 25–35 分钟 | working/audit 差异、before/after、仍保留关键事实 |
| 11 | 受控自进化、Agent Factory 与 Harness 结构进化 | 30–45 分钟 | 搜索、选择最小产物、审批、持久化、独立验证 |
| 12 | Session Fork/Merge、精确轨迹和训练数据导出 | 25–35 分钟 | lineage、多 Agent、摘要后真实 surface、LLaMAFactory/verl |
| 13 | 联网搜索、页面取证、浏览器 Agent 与后台任务 | 25–35 分钟 | URL 证据、observe-act-verify、handoff、durable run |
| 14 | 安全、审批、Workspace Guard、容器与检查点恢复 | 25–35 分钟 | 单次审批、越界拒绝、fail-closed、选择性恢复 |
| 15 | Improve、Deploy、EgoIR 与 Research Lab | 25–35 分钟 | held-out/regression/rollback、package、dry-run、science audit |
| 16 | CoC 多 Agent 跑团与持久人物卡 | 25–40 分钟 | KP 裁决、Identity 数值/物品事务、丢枪后不能射击 |
| 17 | Codex Flow 与 DeepSeek Harness 的可视复刻 | 25–35 分钟 | 11/18 节点、工具循环、审批、compaction、steering、repeat guard/pruner |
| 18 | AVO 风格长程搜索、ARC 与 Flow 自进化 | 30–45 分钟 | 持久证据、科学实验、非行动 supervisor、停滞恢复、结构候选与 held-out |

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
| 9 | 主仓库 | `Workbench` → `Evaluate` | Task 选 `离线 DAG / Tool Trace 自检` |
| 10 | 主仓库 | `Workbench` → `Evaluate` | Task 选 `录屏：精简上下文与被动压缩` |
| 11 | 主仓库 | `Workbench` → `Evaluate` | Task 选 `录屏：重复工作触发受控自进化` |
| 12 | 主仓库 | `Workbench` → `More` → `Sessions` | 选择第 10 或第 11 集产生的非临时 Session |
| 13 | 教学仓库 | Chat `Agent 配置` → Agent 模式 | 第一条使用本集 python.org 搜索 prompt |
| 14 | 主仓库 | `Workbench` → `More` → `Settings` | 点 `安全、审批与沙箱`；不要先改 Unrestricted |
| 15 | 主仓库 | `Workbench` → `Improve` | 粘贴一个第 9–11 集的失败/低分轨迹 |
| 16 | 主仓库 | `Workbench` → `More` → `CoC Table` | 模组先选 `coc_the_haunting` |
| 17 | 教学仓库 | `Workbench` → `Build` | Harness 下拉先选 `codex_flow` |
| 18 | 主仓库 | `Workbench` → `Build` | Harness 下拉选 `arc_scientific_search`；实验文件从 Explorer 打开 |

如果某一集从中途开始录，先按表重新打开对应 Workspace、对应页面和对应文件，不要相信 Void 上一次恢复的焦点状态。

---

## 第 1 集：一体化 IDE、产品模型与服务体检

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

本集固定打开：

```text
http://127.0.0.1:8880/?folder=/C:/Users/aa310/Desktop/egoagent/tutorial_assets/video_demo_repo
```

先在左侧 Explorer 单击 `garden.py`，确认中间编辑器标题就是 `garden.py`。右侧如果有旧消息，点 `运行` → `清空消息` → 再点 `对话`。

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

2. 用鼠标只选中最后 3–5 行测试输出，按 `Ctrl+C`。
3. 回 Chat 输入 `解释这个测试结果：`，再按 `Ctrl+V`。
4. 应出现带 `⌘` 的 `Terminal · …` 图标。终端附件没有文件跳转，因此单击不应伪造来源文件。
5. 不需要发送；删除图标即可。

### G. 四个页签到底看什么

保持 `garden.py` 打开，按下面顺序逐个点击右侧页签：

1. `对话`：用户消息、Markdown 最终回答、默认折叠的思考/工具，以及最下方实时活动状态。
2. `运行`：上方按钮依次是 `启动 DAG / 停止 / 清空消息`；下面四个指标是状态、步数、当前节点、消息数，再往下是“执行轨迹”和“最近工具调用”。这里用于回答“现在跑到哪个节点”。
3. `改动`：这里集中显示 Agent 已默认写入文件但尚未审阅的 change transaction。每个 hunk 有 Accept/Refuse；本集 reset 后应显示 `0`，真正操作留到第 4 集。
4. `上下文`：先点 `↻ 刷新`。顶部第一排 `工作台 / DAG 构建 / 评测 / 进化 / 安全设置` 是跳转入口；第二排：
   - `代码地图` 会在中间编辑器打开当前 Workspace 的符号/文件地图；看完关闭该临时页；
   - `应用预览` 打开配置的本地预览 URL，不是上下文附件；
   - `提交消息` 根据当前 Git diff 生成候选 commit message；
   - `＋ 检查点` 保存当前文件 revision。
5. 继续在 `上下文` 往下看：当前编辑器 context、`本轮上下文计划`、`记忆`、`项目规则 / AGENTS.md`、`检查点`、`历史 Sessions`。逐个展开即可，不要把上面的动作按钮说成同一类数据。

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
5. 点 `运行`，用相同 run 的节点轨迹和消息数证明两条输入属于同一个执行。

## 第 3 集：Adaptive Code Agent 完成真实修复

打开教学仓库，选择 `Agent + adaptive_code_agent + openmanus`，发送：

```text
请修复 garden.py 中 should_water 和 water_millilitres 的逻辑，只做最小修改，运行 python -m unittest -v，并说明你读取了什么、改了什么和测试证据。不要改测试。
```

### 按这个顺序讲

1. `运行` 页出现 capability discovery、Agent、Tool、上下文组件等节点。
2. 展开 `read_file/search_files`、写入工具和 `run_command`，展示参数与真实结果。
3. 当 `run_command` 出现高风险审批卡时点 `允许一次`；这是宿主命令边界，不要改成永久允许。任务正常结束不应再为 `terminate` 弹第二张审批卡。
4. 预期逻辑变为 `should_water(20) == True`、`water_millilitres(12, 5) == 60`。
5. 终端再次运行：

```powershell
python -m unittest -v
```

6. 点 Agent 回复或 `改动` 页中的改动文件名，确认直接在 Void 编辑器打开。
7. 如果模型达到输出上限，UI 应显示“回复被截断/发送继续”，不能留下永久 spinner。

当前机器实测轨迹为：`search_capabilities → activate_capability(garden_evidence) → read_file ×4 → patch_file ×2 → run_command`，4 项测试全部通过。模型可能改变读取顺序，但必须同时具备“本地证据、真实写入、真实测试”三类证据。

### 可对比的 Harness

用 2–3 分钟展示目录中的 `aider_replica`、`openhands_replica`、`swe_agent_replica`、`continue_agent_replica`、`openmanus_replica`。解释它们是不同 agent loop/Harness 模板，不是五套互相割裂的产品 UI；不需要本集逐个消耗模型跑完。

## 第 4 集：逐块审阅与 AI 编辑器

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

1. 打开 `garden.py`，在文件末尾新起一行输入 `def describe_moisture(value):`，停 1–2 秒等待 ghost text；按 `Tab` 接受。再输入另一段触发建议并按 `Escape` 拒绝。录完撤销这段人工演示代码。
2. 选中 `watering_decision` 函数体，按 `Ctrl+I`，在弹框输入 `改成更清晰的提前返回，并保留行为`；先看 Diff 预览，再点“应用并进入逐段审阅”。
3. 展示代码审查、next-edit suggestion 与状态栏本地 usage 计数。
4. 强调模型不可用时可本地降级验证 UI，但正式演示应以已连接模型为准。

## 第 5 集：从零搭一个可运行 DAG

进入 `Build`，新建 `video_basic_agent`。

### 推荐图

```text
Input → Context(snapshot) → Agent
Agent --has_tool_calls--> Tool → Agent
Agent --has_text--> If
If(true) → Human Approval → Checkpoint → Output
If(false) → Loop → Agent
```

### 每一步

1. 从左侧拖 `Input / Agent / Tool / If / Loop / Human Approval / Context / Checkpoint / Output`。
2. 给 Agent 绑定 slot 和 Identity；在右侧用表单设置 instruction、工具可见性、最大工具轮数、temperature/max tokens。
3. 配 If 条件和 true/false 连线；给 Loop 设置有限次数，避免无界循环。
4. 打开 Harness 全局设置，展示预算、timeout、权限、auto checkpoint、错误路由与 typed inputs/outputs。
5. 保存并重新加载，证明图和高级字段没有丢失。
6. 勾 `首节点暂停`，依次点 `执行 → 单步 → 自动`。
7. 点击发光节点旁的小框，展示输入、模型收到的消息、回复、工具、重试、输出和 token/cost。
8. 演示失败后“修改输入重试”和无副作用“安全跳过节点”。

这里要明确：节点有固定的操作契约，但端口、变量引用、边和多数细节都可在前端配置；高级 JSON 是逃生口，不是正常搭图的必需品。Python 节点只在没有类型化组件能表达时使用。

## 第 6 集：27 节点全功能 Code Agent 与 SubDAG

详细搭建稿见 `docs/DAG_ALL_FEATURE_CODE_AGENT_TUTORIAL_ZH.md`。最快录法是在 Build 加载 `tutorial_full_stack_code_agent`，先讲图，再挑关键配置。

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

## 第 7 集：Identity、Ego、Superego、Skill、Knowledge、Environment

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

## 第 8 集：能力 Library 与 DAG 搜索

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

1. 分别切换 `混合搜索 / 仅语义 / 仅关键词`。
2. 打开 Workspace 优先，展示本项目能力排在前面；说明私有 workspace 能力不会跨项目泄漏。
3. 打开 `component_context_compactor`，展示 `typed_subdag / subflow_node / subagent_session` 复用协议。
4. 对一个能力点 `用于此项目`，再运行 discovery Agent。
5. 在轨迹中找到 `search_capabilities → activate_capability`，Harness 命中应返回 `action: invoke_subdag`。
6. 回 Library 刷新，展示 impression/usage/success 指标变化。
7. 点 `重新索引`，说明搜索主路径是 SQLite catalog + 本地多语言 embedding + lexical ranking，不要求 Meilisearch 常驻服务。

## 第 9 集：Task Bench 完整做题

先选 `离线 DAG / Tool Trace 自检`：

1. Harness 保持 `aider_review_worker`，Identity 保持 `test_bot`；这两个由题目兼容性约束，不要强选 `react_single`。
2. 勾 `首节点前暂停`，点 `开始做题`。
3. 第一次暂停在 Input；点一次 `单步`，再点 `自动`。
4. 预期：Agent 节点 3 次、`glob_search` 1 次、`read_file` 1 次、最终 100/100。
5. 点击每个节点旁的小框与 `过程 / 评分 / 产物 / 进化` 四页。

然后选 `录屏：修复智能花盆控制器`，展示 Task 自动建立隔离 workspace、真实修改与确定性 checker。强调“Agent 说完成了”不能得分。

展开 `导入 / 导出 benchmark`：说明 `ego.task.v1`、多步骤题、Harbor 1.4、旧 Terminal-Bench 导入和 Harbor 导出。可打开 `task_bench/tasks/video_code_agent_walkthrough.json` 讲 version、workspace、selection、environment、execution、evolution、evaluation。

## 第 10 集：上下文精简、被动压缩与真实回放

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

在 Improve 或 `Evolve` 模式给一段重复失败轨迹，让它提出添加/删除节点或换 SubDAG。必须先 dry-run/validation，再人工批准 commit；只改 prompt 不算结构进化。展示 mutation event、revision 和 rollback。

## 第 12 集：Session Fork/Merge、精确轨迹和训练导出

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
- 多 Agent 事件必须显示不同 agent；
- compaction 后的下一次 request 必须是替换后的 working surface；
- 完整性应显示 `✓ 完整性通过`。

切到 `训练数据`：选择 `当前 Session`、`整个 Session`，勾选 `精确模型调用 SFT / 完整长轨迹 / verl Rollout`，保存目录留空并点 `生成训练数据`。预期每次模型调用是独立样本，不把多个 Agent 混成一个说话人。顺便展示整段对话 SFT、单条回复 SFT、KTO、DPO/ORPO 和标注审计表；DPO 为 0 通常只表示尚无同 prompt 的赞踩配对。Settings 的 `训练轨迹额外收集` 可另设数据集目录；原生 Session 轨迹始终保留，开关只是镜像复制。

离线训练格式演示可运行：

```powershell
.\.venv\Scripts\python.exe scripts\trajectory_training_smoke.py
```

已有的一步 SFT/GRPO 兼容性证据见 `docs/TRAJECTORY_TRAINING_VALIDATION.md`，不要把 tiny random model 的一步训练说成质量提升实验。

## 第 13 集：联网、浏览器 Agent 和后台任务

### 搜索与页面取证

选择 `adaptive_code_agent + openmanus`：

```text
搜索 Python 3.14 官方文档最近的变化，只使用 python.org。打开最相关的两个页面，区分搜索摘要与正文证据，并附 URL 总结。
```

运行记录应先出现 `web_search`，再出现 `fetch_url/fetch_urls`。讲清搜索只是发现，页面抓取才是正文证据。

### 浏览器

切 `browser_use_replica` 或保持 openmanus：

```text
打开 https://example.com，观察页面，截图，然后告诉我页面标题、主要文本和截图路径。
```

展示 `start/navigate/observe/screenshot`。复杂交互采用 observe→act→verify；CAPTCHA、登录、支付、发布等步骤必须 `handoff` 给人，不能绕过。

### 深度研究和后台运行

- 用 `open_deep_research_replica` 展示多个隔离 Worker 并行搜索、结果压缩后汇总，父上下文只接收结果。
- 进入 `More → Background`：创建 durable Harness run，展示优先级、队列、pause/resume/cancel、逐节点 checkpoint、失败重试、重启恢复、从 checkpoint Fork。

## 第 14 集：安全、审批、沙箱与恢复

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

## 第 18 集：AVO 风格长程搜索、ARC 与 Flow 自进化

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

- Void：Explorer、Editor、Terminal、Chat、对话/运行/改动/上下文、状态栏；
- Workbench：Home、Build、Evaluate、Library、Improve；
- More：Deploy、EgoIR、Research、CoC Table、Background、Agent Changes、Checkpoints、Identity、Environment、Sessions、Settings；
- Flow Graph（UI 兼容标签 DAG）：Input、Agent、Tool、Process、Output、If、Loop、Parallel、Map、Join、Approval、Subflow/SubDAG、Data、Workspace、Context、Memory、Checkpoint、Python escape hatch；
- IDE AI：Tab、Inline Edit、next edit、review、逐 hunk Accept/Refuse、Ctrl+Z 撤销审阅、新文件确认、点击文件名打开；
- Agent runtime：工具循环、流式状态、折叠过程、子 Agent、预算/timeout/truncation、暂停/单步/停止、等待输入；
- 能力治理：Identity/Ego/Superego、Environment、Skill/Tool/Knowledge/DAG 搜索、激活、usage、workspace 优先；
- 长程能力：curator、compactor、memory、self-evolution、agent factory、Harness mutation、rollback；
- 数据与科研：Task Bench、Harbor、轨迹回放、Fork/Merge、SFT/RL 导出、Improve、Research Lab；
- 安全与生产：权限、审批、workspace guard、container fail-closed、checkpoints、durable background runs、packages；
- 扩展能力：web search、fetch evidence、browser handoff、CoC。
- 复刻与研究：`codex_flow`、`deepseek_harness_replica`、repeat guard、tool-result pruner、ARC persistent evidence、non-acting supervisor、候选不提升则拒绝晋升。

## 当前录制验收结果

2026-08-24 在当前机器完成：

- `verify_recording_setup.py --live`：通过；除服务、Catalog、Task、Library 和 provider 探针外，现在还会真实启动 `adaptive_code_agent`，确认一次问候、零 Tool、返回等待输入；
- 离线 Task Bench：Agent 3 次、Tool 2 次、100/100；
- 真实 `adaptive_code_agent` 教学任务：搜索并激活能力、读取证据、两次 patch、一次宿主命令审批、4 tests OK、2 个待审 hunk；
- Library hybrid 查询“压缩长上下文的可复用子 DAG”：命中 `component_context_compactor`；中文自然语言查询还把 Curator、Compactor 和全功能 Code Agent 排到前列；
- 前端逐页实测：Home、Build、Evaluate、Library、Improve 和 More 下 11 个页面均可加载；
- Task Bench UI：首节点暂停、单步、自动、工具轨迹与 100 分均实测；
- Sessions：89-event 离线轨迹和 239-event DeepSeek Flow 轨迹可回放，Fork/Merge、赞踩/重要/入库与八种训练投影入口均已打开；
- Build：全功能模板 27/37、Codex 11/14、DeepSeek 18/21、ARC scientific 19/25 均从前端加载；
- Python 回归共发现 530 项：527 项通过，3 项按环境能力声明跳过；其中 Chrome/CDP 集成在受限测试沙箱内无法连接临时调试端口，已在正常主机权限下 `2/2` 单独通过；
- Vite production build：224 modules transformed，构建成功；
- 无头浏览器集成：导航、表单、语义/坐标点击、dialog、download、screenshot、CAPTCHA/handoff 全链路通过；
- reset 后录屏仓库 `改动 0`，运行中 backend 的旧 review journal 也会按 workspace 同步清除。

### 18 集逐集复核结论

| 集数 | 结论 | 本次复核证据 / 注意点 |
|---|---|---|
| 1 | 通过 | 8880/8765、Home 生命周期、65/65 Harness Catalog 与 provider health 均通过预检。 |
| 2 | 通过，已修复 | 问候只有一次并回到 `input`；Agent 配置可整体折叠；输出按 Markdown 渲染；结构化粘贴/拖放使用正文内原子图标；Clipboard 不再重复渲染预览卡，文本图标可悬停预览、单击编辑。 |
| 3 | 通过 | 真实教学 run 已有 search/activate/read/两次 patch/测试证据；工具、文件事务与非零命令结果回归通过。 |
| 4 | 通过 | 单一 CodeLens、原生 inline Diff、逐 hunk Accept/Refuse、决定后装饰清理、Ctrl+Z 恢复 pending、run transaction 隔离、新文件删除确认与 Inline Edit 回归通过。 |
| 5 | 通过 | 全部可视节点契约、typed ports、循环、错误路由、审批和 builder round-trip 均通过。 |
| 6 | 通过 | `tutorial_full_stack_code_agent` 27 节点/37 连线及四个 SubFlow 可加载，SubDAG 输入输出 schema 会在运行前验证。 |
| 7 | 通过 | Identity、Ego/Superego、Skill/Knowledge 与根 `egoagent` Environment API/组合测试通过。 |
| 8 | 通过 | Library 共五类能力；中文语义检索使用本地 fastembed，workspace 优先、usage 更新、找不到建议创建均通过。 |
| 9 | 通过 | 四个录屏 Task 可见；离线真 Runner 完成 Agent ×3、Tool ×2、100 分，并覆盖暂停/单步/隔离/评分。 |
| 10 | 通过 | Curator 与被动 Compactor 是两个独立 SubDAG；working view、完整 audit、summary/tool 压缩与可恢复性测试通过。 |
| 11 | 通过 | capability/identity/harness 三种演进、独立证据、held-out/regression、EvoCert、失败回滚与 Agent Factory 测试通过。 |
| 12 | 通过，已优化窄布局 | Fork/Merge 三模式、lineage、exact replay、赞踩/重要/入库和训练投影通过；Sessions 窄窗口改为上下布局，避免误点。 |
| 13 | 通过 | web search/fetch 的 SSRF 与证据边界、真实 Chromium observe-act-download-screenshot、后台 durable run 全部通过；公网状态仍需开录前探针。 |
| 14 | 通过 | Workspace guard、host/container fail-closed、危险命令审批、secret 过滤、检查点冲突与中断恢复通过。 |
| 15 | 通过 | Improve 证据门控、签名 package 安装/升级/可恢复卸载、EgoIR dry-run/commit/undo、Research artifact hash 通过。Deploy 页面当前使用英文动作标签。 |
| 16 | 通过 | CoC Identity 人物卡、HP/SAN/Luck 状态事务、物品 Tool 转移/丢失、非法动作拒绝与可重放骰点通过。 |
| 17 | 通过 | `codex_flow` 11/14 与 `deepseek_harness_replica` 18/21 通过 Catalog 和完整工具轮测试；repeat guard/pruner 不破坏完整 audit。 |
| 18 | 研究性通过 | ARC 适配器、19/25 Flow、持久证据、非行动 supervisor 与候选晋升门控通过；真实 V4 pilot 仍未通首关，录制时必须按真实失败展示。 |

模型输出质量、第三方网站状态和公网延迟无法由本地测试永久保证。录制开放式网络、自进化或 Dialogue Merge 前仍应单独跑一次最小探针，并保留失败时的真实 UI 提示。
