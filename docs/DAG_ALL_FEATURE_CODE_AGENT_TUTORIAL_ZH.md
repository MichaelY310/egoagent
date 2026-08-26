# 用 DAG 搭建全功能 Code Agent

本教程的最终结果是 `tutorial_full_stack_code_agent`。它不是伪代码：模板包含 27 个真实节点、4 个 Identity Slot、4 个可复用 SubDAG，并能直接运行。

## 最快的学习方式

进入 `Build → 加载 / 新建`，加载 `tutorial_full_stack_code_agent`，先打开 `显示概览` 看全图。若要边学边改：加载后把 Harness 名改为 `my_full_stack_code_agent`，再保存，避免覆盖教学模板。

四个 Slot：

| Slot | Identity | 责任 |
|---|---|---|
| `agent` | `coder` | 读取、编辑、运行测试 |
| `governor` | `dante` | 能力发现、上下文治理、计划和证据判定 |
| `quality_reviewer` | `sharp_critic` | 独立正确性/回归审查 |
| `safety_reviewer` | `privacy_guard` | 范围、权限、秘密和安全审查 |

## 第一段：输入与每轮状态

拖入并连接：

```text
input → reset_goal → reset_answer → reset_feedback → count_turn
```

- Input 把 `text` 映射到 `$ctx.request`。
- 三个 Data/set 清除上一轮完成、回答和反馈状态。
- Data/increment 使用 session scope，把 `tutorial.turn_count` 保存到 `$ctx.turn_count`。

这部分说明 DAG 的数据流是显式的：节点 output port 通过 `outputs` 写入 `$ctx`，后续节点用 `${ctx.request}` 或 `$ctx.request` 引用。

## 第二段：搜索 Tool、Skill、Identity 和 DAG

拖入 SubDAG `component_capability_discovery`：

- agent map：`searcher → governor`
- input：`query = ${ctx.request}`、`max_tool_rounds = 3`
- output：`result → capability_discovery`、`searched → capability_searched`
- `share_session = true`

这个 SubDAG 只允许一次 `search_capabilities`，再选择一次 `activate_capability`，最后无工具总结。Harness 搜索结果含 typed SubDAG/subflow/subagent 复用协议。主 Agent 的指令再次要求“创建子 Agent 前先搜索 DAG”。

## 第三段：两个不同的上下文组件

连接：

```text
discover → curation_due ─true→ curate ─┐
                         └false────────┼→ compact → evolution_due
```

- `curation_due`：If 表达式 `ctx.turn_count % ctx.curation_interval == 0`。
- `curate`：SubDAG `component_context_curator`，每 3 轮检查 relevance，普通 Model 根据 conversation metadata 产生 turn plan，再由 Conversation Output 应用。
- `compact`：SubDAG `component_context_compactor`，每轮检查 token pressure；只有达到 high watermark 才由普通 Model 产生 block plan。

推荐教学参数：curator interval 3、保护最近 1 轮；compactor context limit 8192、high watermark 0.55、target ratio 0.35、reserved output 1024。

不要把这两个功能混为一谈：curator 去掉无关/失败/冗长内容，compactor 在上下文太长时被动压缩。

## 第四段：受控进化

连接：

```text
evolution_due ─true→ evolve ─┐
              └false────────┼→ recall
```

- If：`ctx.turn_count % ctx.evolution_interval == 0`，模板每 5 轮检查；生产可改 10–20。
- SubDAG：`component_capability_evolver`。
- agent map：`evolver → governor`。
- input：`require_approval = true`、`protect_recent_turns = 1`。
- output：decision、result、evolved 分别映射到当前 DAG 上下文。

Evolver 的节点链是：conversation snapshot → Model judge → approval → search once → create/activate once → deterministic tool evidence gate → persisted-artifact verification → Model judge → mark evolved。失败不会因为模型自述而变成功。

## 第五段：持久记忆、计划和人工审批

连接：

```text
recall → plan → approve_plan → checkpoint_before → begin_transaction
```

- Memory/search：namespace `tutorial_code_agent`，query `$ctx.request`，top_k 4，相关性权重最高。
- Model/plan：输出严格 JSON 到 `$ctx.implementation_plan`。
- Human Approval：用户可以编辑计划；批准才进入副作用节点，拒绝回到 Input。
- Checkpoint/save：标签 `tutorial-before-code-change`。
- Workspace/begin_transaction：之后所有 Agent 文件写入归入一个可逐块审阅的事务。

计划 Model 节点不是“专用硬编码 Plan 节点”；它是普通 Model，只是通过 prompt、JSON schema 和 output mapping 获得计划语义。Summarize/curate/evolve 也采用相同模块化原则。

## 第六段：最多三次的代码实现循环

Loop 配置：

- list `$ctx.attempts = [1,2,3]`
- item `attempt`
- counter `attempt_index`
- body start `infer`
- break when `ctx.goal_complete`
- max count 3

循环体：

```text
infer ─tool_calls→ tools → infer
  └text→ judge → work_loop
```

- `infer` 是 `coder` Agent，最多 16 个 tool round，能搜索/读写/执行测试，但仍受权限和 workspace 限制。
- Tool 节点执行真实工具，自动检查点并记录结构化 `succeeded` 证据。
- `judge` 是 governor 的普通 Model JSON 判定器，写入 `goal_complete` 与 `feedback`；不假定未报告的测试已经通过。

`interactive_max_tokens = null` 表示此 Harness 不人为设置输出 token 上限；provider 自身限制仍然存在，截断会在事件与 UI 中明确标记。

## 第七段：并行审查与 Join

实现循环结束后连接 Parallel：

- branch `quality → quality_review`
- branch `safety → safety_review`
- join `review_join`
- max workers 2，fail_fast false

两个 Model 使用不同 Identity 和 prompt。Join strategy 为 values，把结果写入 `$ctx.reviews`。这是隔离不同审查目标、减少单一 Agent 自证偏差的示例。

## 第八段：记忆、后置检查点和逐块审阅

连接：

```text
review_join → remember → checkpoint_after → review_changes → input
```

- Memory/add：保存 request、answer、reviews，importance 5。
- Checkpoint/save：标签 `tutorial-after-code-change`。
- Workspace/review_transaction：把事务交给逐 hunk UI；pending policy 为 accept，用户仍可逐块 Reject/Undo。
- 最后回到 Input，形成长期交互 Agent。

## 如何把现有 Harness 拖成 SubDAG

1. 先让被复用 Harness 在其 config 中声明 `component`：name、share_session、typed inputs、typed outputs。
2. 保存后它会出现在左侧 `SubDAG 组件`。
3. 拖入画布，右侧选择 Harness、agent map、component inputs 和 component outputs。
4. 对话治理组件通常 `share_session=true`；隔离搜索 worker 通常 false，只把 result 返回父 DAG。
5. 也可以先到 Library 搜索 Harness，详情中的 reuse contract 会告诉你 typed SubDAG、普通 subflow 或隔离 session 的调用方式。

## 如何从零验证这个复杂 Agent

推荐先加载模板，不手工输入 27 个节点。打开教学仓库，选择 `tutorial_full_stack_code_agent`，绑定四个默认 Identity，发送：

```text
修复 garden.py 的两个逻辑错误，只做最小修改，运行 unittest。创建子 Agent 前必须先搜索能力库中的可复用 DAG。
```

录制时检查：

1. discovery SubDAG 搜索能力库。
2. plan 输出结构化 JSON，并停在人工审批。
3. checkpoint 与 transaction 在任何写入前建立。
4. Loop 最多三次；测试证据决定提前 break。
5. quality/safety 两条分支同时亮起，随后 Join。
6. Agent Changes 出现逐块改动。
7. 后续第 3 轮触发 curator，第 5 轮触发 evolution approval；compactor 只在 token pressure 足够高时触发。

若只想验证某个组件，直接使用对应录屏 Task，不必为了触发它进行很多轮代码修改。

## 不建议的做法

- 不要把整个总结、进化或搜索逻辑塞进一个 Python 节点；优先普通 Model + typed Context/Data effect。
- 不要让所有 Skill schema 常驻模型上下文；只保留 `search_capabilities` 和 `activate_capability` 入口。
- 不要在没有搜索 DAG 时创建重复子 Agent。
- 不要让模型自述决定测试成功；Tool 的 `succeeded`、exit code、评分器和 persisted artifact 才是证据。
- 不要把 `_context` 暴露成模型参数；它由受信任运行时注入。
- 不要把一次失败直接永久写进 trusted Agent；先隔离实验、验证、held-out、regression，再 promotion。
