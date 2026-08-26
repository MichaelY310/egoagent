# EgoAgent 全功能教学视频录制手册

> 本页保留为旧版素材库。实际录制请优先使用 18 集新版总导演手册：`docs/VIDEO_SERIES_MASTER_GUIDE_ZH.md`；开录时把 `docs/VIDEO_RECORDING_RUN_CARD_ZH.md` 放在旁边。新版还补齐 Session 反馈/训练数据、Codex/DeepSeek Flow 复刻、repeat guard/tool-result pruner，以及 AVO/ARC 长程自进化的诚实研究展示。

这份手册按可直接录制的顺序编排。主产品入口是 Void 内的 EgoAgent，不需要再打开旧 Studio 网站。

## 0. 录制前准备

主仓库入口：

`http://127.0.0.1:8880/?folder=/C:/Users/aa310/Desktop/egoagent`

代码改动演示仓库入口：

`http://127.0.0.1:8880/?folder=/C:/Users/aa310/Desktop/egoagent/tutorial_assets/video_demo_repo`

如果刚重启电脑，本机用下面这条命令启动全部服务；它会同时准备 8765 Backend、8869 Void 和用户入口 8880：

```powershell
.\.venv\Scripts\python.exe start-all.py
```

给其他用户演示安装时，应先在他们自己的虚拟环境运行 `python -m pip install -r requirements.txt`，再用同一个 Python 执行 `python start-all.py`，不要照抄上面的本机绝对路径。

先在仓库终端执行：

```powershell
.\.venv\Scripts\python.exe scripts\reset_video_demo.py --reset-evolution-artifact --reset-created-artifacts
.\.venv\Scripts\python.exe scripts\verify_recording_setup.py --live
```

第一条命令只恢复 8 个已知教学文件，清理教学仓库的旧审阅事务和精确命名的录屏产物；它不会删除其他项目。第二条命令检查 8880/8765、65 个 Harness、教学题目、Identity、Environment、Flow/DAG 搜索复用协议和真实模型连通性。看到 `RECORDING_SETUP_OK` 后再开始。

录制中如果改坏了教学仓库，再运行同一条 reset 命令即可。

## 1. 先讲清楚产品模型

推荐用一分钟解释四层关系：

- `Identity`：角色、性格、长期知识、私有 Skill、权限。
- `Environment`：当前运行环境共同提供的 Tool 和 Knowledge。
- `Flow Graph`：允许循环的节点/边结构；前端少量 `DAG` 是兼容标签。
- `Harness`：Flow Graph 加 prompts、slots、预算、权限和运行契约，尚未绑定具体 Identity。
- `Agent 实例`：Harness + 已绑定 Identity + Environment + 模型路由 + 当前 Session。
- `Task`：可复现的题目、隔离工作区、选择的 Harness/Identity/Environment、评分标准和运行证据。

普通使用从 Void 右侧原生 Chat 面板开始；构建、评测和管理功能都在同一 IDE 内的 Workbench 中。

## 2. Void 原生 Code Agent

打开教学仓库 URL，点右侧 Chat 图标。顶部可选择：

- 模式：Chat、Plan、Agent、Debug、Evolve、Evaluate。
- Harness：推荐日常代码任务用 `adaptive_code_agent`，完整教学用 `tutorial_full_stack_code_agent`。
- 默认 Identity：代码任务推荐 `coder`；批判性复核可用 `sharp_critic`；通用治理/规划可用 `dante`。
- `Agent 绑定与 DAG`：多 Agent Harness 可分别绑定各个 Slot。

四个页签分别是：

- `对话`：用户、Agent、工具卡片和子 Harness。
- `运行`：当前节点、步数、完整轨迹和最近工具调用。
- `改动`：逐文件、逐 hunk 审阅。
- `上下文`：本轮选入/排除的 IDE 上下文、记忆、规则、检查点和历史 Session。

先做一个只读演示：

```text
请先只读这个项目，说明它做什么、入口文件在哪里、测试怎么运行。不要修改文件。
```

在 `运行` 中证明模型真正使用了 DAG：依次找到当前节点、模型回复和 `read_file`、`list_files` 或搜索工具；在 `上下文` 中展示当前文件、工作区规则和 token 选择理由。

## 3. 真实代码修改与逐段 Accept / Reject

保持教学仓库打开，选择 `adaptive_code_agent + openmanus + Agent`，发送：

```text
请修复 garden.py 中 should_water 和 water_millilitres 的逻辑，只做最小修改，运行 python -m unittest -v，并说明证据。不要改测试。
```

预期结果：`should_water(20)` 从错误的 `False` 改为 `True`，`water_millilitres(12, 5)` 从错误的 17 改为 60，四个测试通过。

验证改动审阅：

1. 打开 `garden.py`。Agent 的修改已经写入文件，新增内容是绿色，删除/替换的旧内容是红色参考。
2. 每个代码块上方有 `✓ 接受 Agent 改动` 和 `✕ 拒绝 Agent 改动` CodeLens。
3. 接受表示保留当前文件内容；拒绝只恢复这一块的旧内容。
4. 对刚才的接受或拒绝执行 Undo，撤销的是“审阅决定”，不是整次 Agent 修改。
5. 也可在 Chat 的 `改动` 页或 Workbench 的 `Agent Changes` 批量处理。
6. 新文件会整文件绿色。拒绝整文件时必须再次确认是否删除，不会静默删文件。

录制一个 hunk 接受、另一个拒绝、再 Undo 拒绝。最后全部接受并运行测试。需要重录时执行 reset。

无模型时，`改动` 页的 `✦ AI 多段改动` 仍可生成演示提案，用于单独展示审阅 UI；正式能力演示优先使用真实 Agent 改动。

## 4. Library：像搜视频一样搜索能力

从 Chat 的 `上下文 → 工作台` 打开 Workbench，进入 `Library`。能力卡不会把所有正文塞进上下文，只展示名称、简介、标签、来源、曝光量、使用量、成功率和最近使用时间。

依次演示以下筛选与查询：

| 分类 | 查询示例 | 期望 |
|---|---|---|
| Tools | `search reusable capabilities in local registry` | `search_capabilities`、`activate_capability` |
| Skills | `读取和搜索代码仓库文件` | `search_files`、`read_file`、`glob_search` |
| Knowledge | `harness guide DAG nodes loops subflow` | `harness_guide` |
| Identity | `犀利批评创意漏洞` | `sharp_critic` |
| DAG / Harness | `压缩长上下文的可复用子 DAG` | `component_context_compactor` / curator |
| DAG / Harness | `隔离搜索过程，只返回结果` | research/search worker Harness |

分别切换 `混合搜索`、`仅语义`、`仅关键词`。混合搜索采用本地多语言向量 + 关键词排序；无需 Meilisearch 服务。当前 Workspace 的 Skill/Tool/Knowledge 优先，但另一个 Workspace 的私有能力不会泄漏进结果。

对 Tool、Skill、Knowledge 点 `用于此项目`；对 Identity 或 Harness 点 `选择并复制名称`。打开 Harness 详情时展示 `reuse`：

- `typed_subdag`：有类型化 component inputs/outputs，可直接拖为 SubDAG。
- `subflow_node`：可用 `子流程` 节点调用。
- `subagent_session`：可作为隔离子 Agent Session 启动。

证明 Agent 真用了搜索而不是只展示 UI：运行一个包含 `component_capability_discovery` 的 Agent，在节点轨迹中依次找到：

1. `search_capabilities` 的查询、候选卡与 `creation_recommended`。
2. `activate_capability` 的 capability ID。
3. 返回的 `action`。普通 Skill 可能是 `load_tool` 或 `apply_instructions`；Harness 是 `invoke_subdag`，并携带 SubDAG 复用协议。

能力被搜索会增加 impressions，被激活会增加 usage，执行成功/失败会更新成功率。点 `重新索引` 可立即看到新建能力。

## 5. Identity：角色、Ego、Skill 与 Knowledge

进入 `More → Identity`。

推荐先选择 `coder`，展示四类配置：

- `ID`：name、role、description、personality、traits、tone、language 和 LLM 覆盖配置。
- `Superego`：Task Prompt、Tool/Knowledge 白名单与黑名单、权限开关。
- `Skills`：Identity 私有的可执行工具或说明型 Skill。
- `Knowledge`：Identity 长期携带的知识。

有三种创建方式：自然语言创建完整 Agent、新建空 Identity、克隆现有 Identity。录制时可以克隆 `coder` 为 `video_coder`，避免改动正式角色，录完后删除。

添加一个 Identity Skill 的最小示例：

1. 在 Skills 输入 `normalize_ticket`，点 `+`。
2. Meta JSON 使用：

```json
{
  "type": "tool",
  "name": "normalize_ticket",
  "description": "Normalize a support ticket title when a task contains inconsistent spacing or case.",
  "parameters": {
    "type": "object",
    "properties": {"title": {"type": "string"}},
    "required": ["title"]
  }
}
```

3. 脚本中定义同名顶层函数：

```python
def normalize_ticket(title):
    return " ".join(title.split()).title()
```

4. 保存、重新索引 Library，搜索 `normalize inconsistent support title`。

Knowledge 的操作类似：新建名称，填写 Meta JSON 与 Markdown 正文。Knowledge 适合事实，不适合带副作用的动作。

## 6. Environment：给一个运行环境添加 Tool / Knowledge

进入 `More → Environment`。根目录 `.environment` 在 UI 中名为 `egoagent`，Task Bench 也能选到同一个 Environment。

演示 Tool：

1. 选择 `egoagent`，在 Tools 新建 `workspace_policy_lookup`。
2. Meta JSON 填入：

```json
{
  "type": "tool",
  "name": "workspace_policy_lookup",
  "description": "Read matching recording-policy lines from the current workspace README without crossing the workspace boundary.",
  "parameters": {
    "type": "object",
    "properties": {"topic": {"type": "string"}},
    "required": ["topic"]
  }
}
```

3. 脚本填入以下实现；`_context` 是运行时私有参数，不要写入公开 schema：

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

4. 保存后重新索引 Library。

演示 Knowledge：在 Knowledge 新建 `video_recording_rules`，写一段 Markdown。将 Environment 勾选到 Task 或 Agent 后，其 Tool/Knowledge 才进入该运行；Identity 私有能力与 Environment 共享能力因此可以独立组合。

要证明 Environment Tool 真被调用，而非只存在于管理页：让使用 `egoagent` Environment 的 Agent 执行“调用 `workspace_policy_lookup` 查询 `recording`，引用来源路径回答”。在 `运行 → 工具调用` 中找到同名 Tool，并确认结果中的 `source` 位于当前教学 workspace。录完可在 Environment 页删掉这两个教学条目。

## 7. Task Bench：题目、隔离、回放与 DAG 逐节点观察

进入 `Evaluate`。左侧是题目库和最近运行；顶部可选择 Harness、Identity、Environment，多 Agent Harness 还会出现 Slot 绑定。

勾选 `首节点前暂停` 后点 `▶ 开始做题`：

- `单步`：只放行一个节点。
- `自动`：恢复自动执行。
- `⏸`：请求在下一节点前暂停。
- `停止`：级联终止主 DAG 和子 DAG。

点击 DAG 中任意发光节点，旁边的小框会显示：模型输出、工具和结果，或普通节点的输入/输出。右侧四页是 `过程 / 评分 / 产物 / 进化`。评分是确定性检查，Agent 自述不会被当作通过证据。

题目格式是 `ego.task.v1`，可参考：

- `task_bench/tasks/video_code_agent_walkthrough.json`
- `task_bench/tasks/video_context_governance_walkthrough.json`
- `task_bench/tasks/video_self_evolution_walkthrough.json`

基本字段是 version、id、title、prompt、workspace.files、selection、environment、execution、evolution、evaluation；也支持多步骤、Harbor 1.4 和旧 Terminal-Bench 导入，并可导出 Harbor 目录。容器题才需要 Docker；本教程任务全部使用 local backend。

## 8. 精简上下文与被动压缩：两个不同功能

选择题目 `录屏：精简上下文与被动压缩`，Harness `conversation_component_demo`，Identity `dante`，开始后按顺序输入：

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

第五轮后验证：

- DAG 上 `compact_subdag` 与 `summarize_subdag` 都被调用。
- Compactor 是 token pressure 触发的被动功能，先把长块压到目标 token 水位。
- Curator 是相关性精简，模型根据 conversation metadata 决定 elide、summarize 或压缩工具输出。
- 点两个子 DAG 内的 `conversation_out`，查看 before/after/saved/reduction ratio。
- 在 `Sessions` 中，原对话仍可见，但模型上下文中被移除或被摘要替代的消息带有 `已从模型上下文移除`、`已由摘要替代`、`工具输出已压缩` 标记。
- 最终仍应答出 7319、45 秒和 `python -m unittest discover -v`。

已验证的参考记录是 `run_20260816_200845_929f9bad`：评分 1.0，两次 `conversation_applied`，分别节省约 72.6% 和 63.9% 的估算 token。

## 9. 受控自进化：自然决策、搜索、审批、创建、验证

录制前必须先运行 reset，确保没有同名 Skill。选择：

- Task：`录屏：重复工作触发受控自进化`
- Harness：`component_capability_evolver`
- Identity：`coder`

启动后不要替模型选择产物类型。模型会比较不变、Knowledge、Skill、子 Agent 和 Harness；本题应自然选择一个确定性 Skill。出现审批框后输入 `approved`。

按节点证明整个过程：

1. `judge`：模型说明 12 个分区、80% 重复轨迹为什么值得或不值得进化。
2. `search_tools`：只搜索一次能力库，确认没有合适重复项。
3. `mutation_tools`：`create_skill` 返回 `ok: true` 与持久化路径；失败时不会产生 mutation 事件，并只有一次受限修正机会。
4. `verification_tools`：从创建结果给出的 `scripts/<name>.py` 导入真实产物，不能测试复制的 inline code。
5. 原始结果必须包含 `exit_code: 0` 和 `PASS`。
6. `verification_judge` 只有在创建证据和验收证据都成立时才返回 verified。
7. `mark_evolved` 最后才把 evolved 置 true。
8. `进化` 页展示 `identity_evolution` 和最终新增的两个文件。

随后在终端独立验证：

```powershell
python scripts/verify_video_evolution_artifact.py
```

已验证的参考记录是 `run_20260816_204121_52ce104a`：评分 1.0，模型创建 `greenhouse_water_usage`，持久化导入测试输出 `PASS`。系统没有把前面几次失败试验强行标为成功；非零退出码、权限拒绝、无持久化证据都会被确定性分支拦住。

## 10. DAG / SubDAG 搜索与子 Agent 复用

这是能力搜索的一部分，已经实现，不依赖 Meilisearch。

在 `Library → DAG / Harness` 搜索 `压缩长上下文`，打开 `component_context_compactor` 详情，可以看到 typed SubDAG 的输入、输出和 agent_map。在 `Build` 的 `SubDAG 组件` 区域，它可以直接拖入当前图。

Agent 创建子 Agent 时应先调用 `search_capabilities(... kinds=['harness'])`：

- 若命中 typed SubDAG，`activate_capability` 返回 `action: invoke_subdag` 和可复用接口。
- 若只命中普通 Harness，可按 `subflow_node` 或 `subagent_session` 使用。
- 只有没有强匹配时才创建新 Harness。

`tutorial_full_stack_code_agent` 的 discovery SubDAG 和主 Agent 指令已经包含“创建子 Agent 前搜索可复用 DAG”这一规则。运行时在 `search_tools` 与 `activate_tools` 查看证据。

## 11. Build：搭建、运行和观察 DAG

进入 `Build`：左侧拖节点，中间连线，右侧编辑配置。基础节点按最少五类组织：Input、Agent、Tool、Process、Output；高级能力包括 If、Loop、Parallel、Map、Join、Human Approval、Subflow、Data、Workspace、Context、Memory、Checkpoint 和兜底 Python。

运行前可勾 `首节点暂停`。运行时可暂停、单步、自动和停止。切到 `运行观测`，点击节点调用可看：输入、模型收到的内容、模型回复、工具请求与结果、重试、产物、token/cost 统计和最终输出。

完整的全功能 Code Agent 搭建教程见 `docs/DAG_ALL_FEATURE_CODE_AGENT_TUTORIAL_ZH.md`。

## 12. 其余页面的短演示

建议每页录 20–60 秒：

- `Home`：Build → Evaluate → Improve → Deploy 主流程、最近评测和失败信号。
- `Improve`：从一次真实失败创建隔离实验；候选先 validation、held-out、regression，再进入 trusted，失败则回滚。
- `Deploy`：把 Harness/Identity/能力组成版本化 package，查看依赖、发布和回滚。
- `EgoIR`：弱模型友好的逐行 Harness 表示；先 Validate/Dry run，再 Commit，带 revision 与 Undo transaction。
- `Research`：研究项目、实验契约、队列与证据，不把一次偶然跑通当科研结论。
- `CoC Table`：人物卡是可复用 Identity；属性/物品写入 Identity 状态，KP 通过事务更新并维护连续性。
- `Background`：后台任务、优先级、隔离、重试、状态通知和停止。
- `Agent Changes`：跨文件逐块审阅、冲突与事务状态。
- `Checkpoints`：查看自动/手动快照，恢复前检查节点、产物、审批和 revision。
- `Sessions`：对话、完整审计历史、节点轨迹和上下文精简标记。
- `Settings`：provider/model/base URL、健康探针、网络与代理；API key 不显示在教程或仓库中。
- Void `上下文` 快捷功能：代码地图、应用预览、生成提交消息、创建检查点。
- 编辑器 AI：Tab 自动补全、Inline Edit、代码审查和逐段 Agent Diff；模型不可用时可用本地演示回退验证 UI。

## 13. 推荐录制顺序

1. 产品四层模型与主界面。
2. Void Chat 只读问答。
3. 代码修改、测试、逐段 Accept/Reject/Undo。
4. Identity 与 Environment。
5. Library 语义搜索，包括 DAG/SubDAG。
6. Build 基础 DAG，再加载全功能 Code Agent。
7. Task Bench 暂停/单步/评分/产物。
8. 上下文精简与被动压缩。
9. 受控自进化与独立验收。
10. Improve/Deploy/EgoIR/Research/CoC/Background/Sessions/Settings 快速巡览。

录完后如果要把仓库恢复到干净教学状态，再运行：

```powershell
python scripts/reset_video_demo.py --reset-evolution-artifact
```
