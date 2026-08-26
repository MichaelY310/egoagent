# Session Fork 与 Merge

日期：2026-08-18  
状态：已实现并通过服务、HTTP API、轨迹一致性与前端构建测试

## 目标

EgoAgent 的 Session 分支不是复制一块 UI 文本。它复制可继续运行的模型工作历史、
完整审计历史与 Session 状态，同时给新分支分配独立的 `session_id` 和 `trace_id`。
来源 Session 永远只读，所有 fork/merge 都创建一个新 Session。

这使用户可以从同一上下文探索两种实现，再把结果合并；也保证导出训练数据时不会
把两个分支误认为同一个 Agent 的连续原始轨迹。

## 在 IDE 中使用

1. 打开左侧 `Sessions` / `Session Explorer`。
2. 选择一个非 TaskBench 临时 Session。
3. 点击标题栏的 `⑂ Fork`。
4. 可填写新名称；留空时自动生成唯一名称。
5. Fork 后，新 Session 会被自动选中。来源列表项和新列表项互不影响。

合并时选择左侧 Session，点击 `⇄ Merge`，再选择右侧 Session 和方法：

- `Auto`：估算两个分支在共同点之后的新增 tokens。低于阈值时 Direct，高于阈值时 Summary。
- `Direct`：以左侧当前 working context 为基础，原样追加右侧共同分支点后的消息；不调用模型。
- `Summary`：分别总结 A、B 的新增消息，再把两个独立摘要放入新模型上下文。
- `Dialogue`：A Agent 与 B Agent 轮流交换独有事实、修改和冲突，最后由 synthesis Agent 形成合并记忆。

列表中的 `⑂ fork`、`⇄ direct/summary/dialogue` 标签展示直接父 Session。将鼠标悬停
可看到父项；选择新 Session 后可在“精确回放”里检查所有合并模型调用。

## 共同分支点与“新增消息”

新消息不是按文本长度猜测。每条现代 Session 消息拥有稳定 `_message_id`，Fork 保留
这些 ID；合并时取两个 audit history 的最长共同前缀。旧 Session 没有 ID 时，使用
规范 JSON 内容哈希作为兼容回退。

Direct 的结果为：

```text
left.working_context + right.audit_messages_after_common_prefix
```

这样左侧分支做过 context compaction 时，已压缩的工作 surface 仍被尊重；右侧共同
历史不会重复插入。原始来源消息及前后哈希保存在 `lineage.json`。

## 超长摘要

Summary 不会把两个分支先混在一起摘要。A、B 分别调用 `merge_summarizer_a` 与
`merge_summarizer_b`；超长单分支按约 36,000 字符切块，各块摘要后再 reduce。
这避免长分支挤掉短分支，也保留分支归属。

Auto 默认阈值为 12,000 estimated tokens，可在 UI 修改。估算只用于路由，不作为
训练 token 数。所有真正模型请求仍保存完整 request、response、usage 和 call ID。

## 对话式合并

Dialogue 默认两轮，最多四轮：

```text
branch A -> branch B -> branch A -> branch B -> synthesizer
```

Prompt 要求双方只讨论共同分支点之后的独有内容，保留用户意图、代码/文件修改、
测试证据、错误、未完成事项和来源归属；矛盾必须显式列出，不能静默选择一边。
输入转录被包在 `<new_content>` 中并声明为数据，降低历史内容中的 prompt injection
改变合并任务的风险。

每个参与者有不同的轨迹 `agent`：

- `merge_branch_a`
- `merge_branch_b`
- `merge_synthesizer`
- 超长预处理时还有 `merge_summarizer_a/b`

因此 LLaMAFactory/verl 导出仍是一条模型调用一个样本，不会混淆多 Agent 身份。

## 文件与事件

每个分支结果目录包含：

- `messages.json`：新 Session 当前模型 surface；
- `full_messages.json`：可见审计历史；
- `state.json`：Session 状态和 `session_lineage`；
- `session.json`：独立 session/trace 元数据；
- `lineage.json`：父 Session、共同前缀、消息 hash、merge mode 与模型 call IDs；
- `trajectory.jsonl`：新 Session 自包含的 append-only 事实流。

新增轨迹事件：

- `session.forked`
- `session.merge.started`
- `model.request/response/error`（Summary/Dialogue）
- `conversation.surface.replace`
- `session.merge.completed`

Fork 不复制来源 JSONL，因为共享 trace/event ID 会造成追加歧义。新 trace 通过一次
完整 `conversation.surface.replace` 建立自包含投影，并通过 lineage 引用来源。

## HTTP API

```text
POST /api/session/<source>/fork
{"name":"optional-new-name"}

POST /api/sessions/merge
{
  "left":"branch-a",
  "right":"branch-b",
  "mode":"auto|direct|summary|dialogue",
  "name":"optional-new-name",
  "threshold_tokens":12000,
  "dialogue_rounds":2
}

GET /api/session/<name>/lineage
```

Session 名只能是一个安全文件名，拒绝绝对路径、`..`、目录分隔符和 Windows 保留字符。
目标已存在时拒绝覆盖。

## Project 归属与跨项目合并

现代 Session 在 `session.json` 中保存真实 `workspace`；旧记录由 Project Portfolio 从轨迹
或 Working directory 消息迁移归属。Fork 始终保留来源 Project。跨项目时 Direct 被拒绝，
Auto 固定路由到 Summary；Summary 与 Dialogue 的新 Session 写入左侧 Project，并在
`lineage.json` 保存两个来源 workspace 和 `target_workspace`。完整使用方式见
[多项目与多 Session 管理](PROJECT_PORTFOLIO.md)。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_session_branching.py tests/test_session_branching_api.py -q
cd harness_editor
npm run build
```

覆盖：来源不变、自包含新 trace、共同前缀去重、Auto 长度路由、A/B 独立摘要、
五次对话式模型调用的 Agent 归属、轨迹 hash/pair 校验、HTTP round-trip、路径穿越和
重复目标保护。
