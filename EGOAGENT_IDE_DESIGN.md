# EgoAgent IDE — 完整功能设计文档

> 目标：在 Void (VSCode Web fork) 中实现一个对标 Cursor/Trae 水平的 AI Agent IDE，
> 同时保留 EgoAgent 独有的 DAG 编排、多 Agent 协作、自进化等高级特性。
> 最终形态：**完全替代独立前端**，所有操作均可在 IDE 内完成。

---

## 第一部分：功能清单总览

### P0 — 核心必备（用户体验基础）

| # | 功能 | 类别 | 说明 |
|---|------|------|------|
| 1 | **Agent Chat 面板** | 交互 | 侧边栏对话，支持多 Agent 消息区分（颜色/头像/名称） |
| 2 | **文件编辑 Diff 视图** | 编辑 | Agent 修改文件后展示逐块 diff，每块可 Accept/Reject |
| 3 | **Agent 修改看板** | 编辑 | 列出 Agent 本次会话修改的所有文件，点击查看 diff |
| 4 | **@ 上下文引用** | 上下文 | @file @folder @code @workspace 将代码加入聊天 |
| 5 | **终端命令集成** | 执行 | Agent 可执行终端命令，危险命令需审批 |
| 6 | **Harness 选择器** | DAG | 下拉框切换 Harness（DAG 模板） |
| 7 | **DAG 流程可视化** | DAG | 实时显示当前 DAG 节点执行进度 |
| 8 | **工具调用展示** | 交互 | 折叠式展示 Agent 的每次工具调用和结果 |

### P1 — 高级功能（差异化竞争力）

| # | 功能 | 类别 | 说明 |
|---|------|------|------|
| 9 | **一句话创建 Agent** | 元能力 | "帮我创建一个适合 React 项目的代码审查 Agent" |
| 10 | **DAG 可视化编辑器** | DAG | 拖拽式编辑 DAG 节点/边，实时预览 |
| 11 | **Identity 管理面板** | 管理 | 浏览/创建/编辑/删除 Identity |
| 12 | **Environment 注册中心** | 环境 | 发现、注册、管理所有环境（工具+知识） |
| 13 | **进化控制台** | 进化 | 启动/监控/查看进化历史 |
| 14 | **Session 历史浏览器** | 历史 | 浏览历史对话，支持回放和分析 |
| 15 | **多 Agent 协作实时追踪** | DAG | WebSocket 实时推送每个节点/Agent 的执行状态 |
| 16 | **Checkpoint/Rollback** | 安全 | Agent 修改前自动快照，支持一键回滚 |
| 17 | **Knowledge Base 管理** | 知识 | 查看/编辑/导入 Agent 的知识库 |

### P2 — 增强体验（锦上添花）

| # | 功能 | 类别 | 说明 |
|---|------|------|------|
| 18 | **Tab 代码补全** | 编辑 | 基于 LLM 的智能代码补全 |
| 19 | **内联编辑 (Cmd+K)** | 编辑 | 选中代码后自然语言描述修改 |
| 20 | **跨会话记忆** | 上下文 | 记住项目偏好和编码风格 |
| 21 | **项目规则系统** | 配置 | .egoagent/rules/ 定义 AI 行为约束 |
| 22 | **实验管理面板** | 实验 | 配置/启动/对比实验结果 |
| 23 | **自对弈训练面板** | 进化 | 可视化三角色自对弈进化过程 |
| 24 | **MCP 工具市场** | 扩展 | 浏览/安装外部 MCP 工具 |
| 25 | **Agent 评估报告** | 分析 | 自动评估 Agent 表现并生成报告 |
| 26 | **多模型路由** | 配置 | 不同任务使用不同模型 |

---

## 第二部分：功能详细设计

---

### 功能 1：Agent Chat 面板

**位置**：IDE 右侧固定面板（可折叠）

**UI 结构**：
```
┌─────────────────────────────────┐
│ EgoAgent  [●Ready] [harness ▼] │  ← 顶栏：状态 + harness 选择
├─────────────────────────────────┤
│ ┌─ DAG Flow ──────────────────┐ │  ← DAG 进度条（可折叠）
│ │ [入口]→[推理]→[执行]→[推理] │ │
│ └─────────────────────────────┘ │
├─────────────────────────────────┤
│                                 │
│  👤 You                    14:32│  ← 用户消息
│  ┌─────────────────────────┐   │
│  │ 帮我重构这个函数         │   │
│  └─────────────────────────┘   │
│                                 │
│  🤖 Coder (dante)         14:32│  ← Agent 消息（含身份标签）
│  ┌─────────────────────────┐   │
│  │ 我来分析这段代码...      │   │
│  │                         │   │
│  │ ▶ Tool: read_file       │   │  ← 可折叠工具调用
│  │   path: src/utils.ts    │   │
│  │   ─────────────────     │   │
│  │   [result: 45 lines]    │   │
│  │                         │   │
│  │ ▶ Tool: patch_file      │   │  ← 文件修改工具 → 触发 Diff 视图
│  │   [View Changes →]      │   │  ← 点击跳转 Diff 面板
│  └─────────────────────────┘   │
│                                 │
├─────────────────────────────────┤
│ [@file] [Ask the DAG agent...] [→]│  ← 输入栏 + @ 按钮
└─────────────────────────────────┘
```

**多 Agent 模式**（如 creative_roundtable）：
- 每个 Agent 有独立颜色标识和名称标签
- 格式：`🟢 创意家 (creative_brain)` / `🔴 批评家 (sharp_critic)`
- 支持折叠单个 Agent 的完整输出
- DAG 流程条高亮当前活跃的 Agent 节点

**数据流**：
```
前端 → POST /v1/chat/completions {model: "egoagent-dag:harness:identity"}
后端 → 执行 DAG Pipeline → 收集每个节点输出
后端 → 返回 [MULTI_AGENT_TRACE]\n[{agent, content, node_id}, ...]
前端 → 解析 trace → 渲染多个消息气泡
```

**关键实现细节**：
- 消息保存在前端 `msgs[]` 数组，完整历史传递给后端
- 支持非流式（当前代理层限制）和流式（未来 WebSocket 支持）
- Agent 标签颜色从固定调色板循环分配
- 工具调用折叠块内显示：工具名 + 参数摘要 + 结果摘要
- 文件操作类工具（patch_file/write_file）自动触发 Diff 通知

---

### 功能 2：文件编辑 Diff 视图

**触发方式**：Agent 调用 patch_file/write_file/multi_edit 后自动弹出

**UI 设计**：
```
┌─────────────────────────────────────────────────────┐
│ Agent Changes: src/utils.ts         [✓ All] [✗ All] │  ← 文件级操作
├─────────────────────────────────────────────────────┤
│                                                     │
│   12 │ function helper() {                          │
│   13 │-  return oldValue;          [✓] [✗]         │  ← 逐块 Accept/Reject
│   13 │+  return newValue;                           │
│   14 │ }                                           │
│                                                     │
│   ─────── chunk separator ───────                   │
│                                                     │
│   28 │ class Parser {                               │
│   29 │+  private cache = new Map(); [✓] [✗]        │  ← 新增代码块
│   30 │+                                             │
│   31 │   parse(input) {                             │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**实现方案**：

1. **后端变更追踪**：
   - 在 `patch_file`/`write_file` 工具执行时，保存变更记录到 session context
   - 记录格式：`{file, old_content, new_content, chunks: [{start, end, old, new}]}`
   - 通过 WebSocket 或 API 端点 `GET /api/session/changes` 推送变更

2. **前端 Diff 渲染**：
   - 使用 Monaco Editor 内置的 DiffEditor 组件（Void/VSCode 自带）
   - 分割为独立 chunks，每个 chunk 一组 Accept/Reject 按钮
   - Accept：保留 Agent 修改（文件已写入，无需操作）
   - Reject：调用后端 `POST /api/revert-chunk` 还原该块

3. **文件状态管理**：
   - Agent 修改文件时立即写入磁盘（保持与 IDE 文件系统同步）
   - Reject 时通过 patch 反向操作还原
   - 全部处理完毕后清除变更记录

**Accept/Reject 规则**：
- 如果 30 秒内用户无操作，默认保留（Agent 已写入）
- 支持 "Auto-Accept All" 模式（适合信任 Agent 的场景）
- Reject 后通知 Agent："用户拒绝了对 X 的修改，原因：..."

---

### 功能 3：Agent 修改看板

**位置**：Chat 面板底部或独立 Tab

**UI 设计**：
```
┌─────────────────────────────────────────┐
│ 📋 Changes This Session    [↩ Revert All]│
├─────────────────────────────────────────┤
│ ✓ src/utils.ts         +12 -3   [View] │  ← 已接受
│ ⚠ src/index.ts         +5  -0   [View] │  ← 待审查
│ ✓ tests/utils.test.ts  +28 -0   [View] │  ← 新文件
│ ✗ config.json          +1  -1   [Undo] │  ← 已拒绝
├─────────────────────────────────────────┤
│ Total: 4 files | +46 -4 lines           │
└─────────────────────────────────────────┘
```

**数据源**：
- 后端维护 `session.file_changes[]` 列表
- 每次文件操作工具执行时追加记录
- 前端定期轮询或通过 WebSocket 实时更新
- 支持按状态筛选：All / Pending / Accepted / Rejected

**API 设计**：
```
GET  /api/session/changes          → [{file, status, additions, deletions, chunks}]
POST /api/session/changes/accept   → {file, chunk_index?}  (不传 chunk_index = 全文件)
POST /api/session/changes/reject   → {file, chunk_index?, reason?}
POST /api/session/changes/revert-all → 回滚本 session 所有修改
```

---

### 功能 4：@ 上下文引用

**触发方式**：在输入框输入 `@` 后弹出选择器

**支持的引用类型**：

| 引用 | 语法 | 行为 |
|------|------|------|
| `@file` | `@filename.ts` | 将整个文件内容附加到消息上下文 |
| `@folder` | `@src/components/` | 将目录树 + 每个文件前 10 行附加 |
| `@code` | `@ClassName.method` | 精准引用代码符号（基于 AST） |
| `@workspace` | `@workspace` | 项目级语义搜索，自动找最相关文件 |
| `@diff` | `@diff` | 当前 git diff 作为上下文 |
| `@terminal` | `@terminal` | 最近的终端输出 |
| `@harness` | `@creative_roundtable` | 引用 harness 配置作为上下文 |
| `@identity` | `@dante` | 引用 identity 配置 |
| `@session` | `@session:last` | 引用历史对话 |

**UI 交互**：
```
输入 @ → 弹出浮层：
┌──────────────────────┐
│ 📄 File              │  ← 展开后显示文件搜索框
│ 📁 Folder            │
│ 💻 Code Symbol       │
│ 🌐 Workspace         │
│ 📊 Git Diff          │
│ 🖥️ Terminal Output   │
│ 🔧 Harness Config    │
│ 👤 Identity          │
└──────────────────────┘
```

**实现方案**：
1. 输入框监听 `@` 字符，弹出 autocomplete 浮层
2. 选择类型后：
   - file/folder：调用后端 `GET /api/files/search?q=...` 模糊搜索
   - code：调用后端 `GET /api/symbols/search?q=...`（基于 workspace 索引）
   - workspace：不选具体文件，后端自动 semantic search
3. 选中后在输入框显示为 pill/tag：`[@utils.ts]`
4. 发送时将引用内容序列化到 messages 的 system/user 消息中
5. 格式：`[Context: @file utils.ts]\n```\n<file content>\n```\n\n<user message>`

---

### 功能 5：终端命令集成

**触发方式**：Agent 调用 `run_command` 工具时

**UI 设计**：

在 Chat 中内联展示：
```
🤖 Agent
  我需要安装依赖...
  
  ▶ Terminal: npm install lodash
  ┌─────────────────────────────────┐
  │ $ npm install lodash            │
  │ added 1 package in 2s           │
  │ [Exit: 0]                       │
  └─────────────────────────────────┘
```

危险命令审批模式：
```
  ⚠️ Agent 请求执行以下命令：
  ┌─────────────────────────────────┐
  │ rm -rf node_modules && npm i    │
  ├─────────────────────────────────┤
  │ [✓ Allow] [✓ Always Allow] [✗]  │
  └─────────────────────────────────┘
```

**安全规则**：
- **自动允许**：`cat`, `ls`, `pwd`, `echo`, `npm install`, `pip install`, `git status`, `git diff`, `python -c`, `node -e`
- **需要审批**：`rm`, `git push`, `docker`, `sudo`, `kill`, `chmod`, `curl | sh`
- **永不允许**：`rm -rf /`, `:(){ :|:& };:`, `dd if=/dev/zero`
- 用户可配置 "Always Allow" 列表（记录在 session 中）

**实现**：
- 后端 `run_command` 工具已有黑名单检查
- 前端通过 WebSocket 事件 `tool_approval_required` 弹出审批对话框
- 用户选择后发送 `POST /api/tool/approve {approved: bool, always: bool}`
- "Always Allow" 存储在 localStorage + 后端 session config

---

### 功能 6：Harness 选择器

**位置**：Chat 面板顶栏

**当前状态**：已实现下拉框，但需要增强

**增强设计**：
```
┌─────────────────────────────────────┐
│ ▼ creative_roundtable               │
├─────────────────────────────────────┤
│ 💬 单 Agent                          │
│   react_single      — ReAct 循环    │
│   coder_react       — 编码专用      │
│   quick_test        — 快速验证      │
│                                     │
│ 🛡️ 带守卫                           │
│   guarded_react     — 工具审查      │
│   dual_guardian     — 双重守卫      │
│   text_review_react — 文字审查      │
│                                     │
│ 👥 多 Agent 协作                     │
│   creative_roundtable — 创意讨论    │
│   debate_with_moderator — 辩论      │
│                                     │
│ 🔄 进化/研究                         │
│   evolution_cycle   — 自进化        │
│   research_loop     — 研究循环      │
│   improver          — 系统改进      │
├─────────────────────────────────────┤
│ [+ 新建 Harness]                    │
└─────────────────────────────────────┘
```

**功能**：
- 分类展示所有 harness（按用途分组）
- 鼠标悬停显示 tooltip：节点数、Agent 列表、简介
- "新建 Harness" 按钮打开创建向导或 DAG 编辑器
- 切换 harness 时清空对话历史（可选保留）

---

### 功能 7：DAG 流程可视化

**位置**：Chat 面板顶部（可折叠）

**设计规格**：

简化模式（默认）：
```
[●入口] ——→ [○推理] ——→ [○工具] ——→ [○推理]
              ↑___________________________|
```
- `●` = 已完成（绿色）
- `◉` = 当前执行（蓝色脉冲动画）
- `○` = 待执行（灰色）
- 箭头上显示条件标签

展开模式（点击展开）：
```
┌─────────────────────────────────────────────┐
│ 🔄 creative_roundtable (运行中 · Step 3/5)  │
├─────────────────────────────────────────────┤
│                                             │
│  [等待输入] ✓                                │
│       ↓                                     │
│  [创意家推理] ✓ (2.1s)                       │
│       ↓ has_text                            │
│  [批评家推理] ◉ (running...)                 │
│       ↓ has_text                            │
│  [创意家改进] ○                              │
│       ↓ has_text                            │
│  [批评家终评] ○                              │
│       ↓ default                             │
│  [等待输入] ○  ←── 循环回到顶部              │
│                                             │
└─────────────────────────────────────────────┘
```

**数据源**：
- WebSocket 事件 `node_enter` 更新当前节点
- 初始 DAG 拓扑从 `GET /api/harness/<name>` 获取
- 节点耗时从 WebSocket `node_complete` 事件获取

---

### 功能 8：工具调用展示

**设计**：每次工具调用显示为可折叠块

```
▶ 🔧 read_file                          2.3s
  ┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈
  path: src/components/Button.tsx
  offset: 1, limit: 50
  ─── Result ───
  [50 lines read successfully]

▶ 🔧 patch_file                         0.5s  [View Diff →]
  ┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈
  path: src/components/Button.tsx
  old_string: "onClick={handler}"
  new_string: "onClick={() => handler()}"
  ─── Result ───
  ✓ Successfully patched

▼ 🔧 run_command                         5.1s
  ┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈
  command: npm test
  ─── Output (collapsed) ───
  PASS src/Button.test.tsx
  Tests: 3 passed, 3 total
  [Exit: 0]
```

**规则**：
- 默认折叠（只显示工具名 + 耗时）
- 文件内容类结果限制显示前 20 行
- patch_file/write_file 显示 "View Diff" 链接
- run_command 输出超过 10 行时折叠
- 失败的工具调用显示红色边框

---

### 功能 9：一句话创建 Agent

**触发方式**：在 Chat 中输入类似 "帮我创建一个..." 的请求

**流程**：
```
用户: "帮我创建一个专门做 React 代码审查的 Agent"
     ↓
系统: 分析需求 → 调用 create_identity + create_harness
     ↓
展示: 
┌─────────────────────────────────────────┐
│ 🎉 已创建 Agent: react_reviewer         │
├─────────────────────────────────────────┤
│ Identity: react_reviewer                │
│ Role: React Code Reviewer               │
│ Harness: guarded_react                  │
│ Tools: read_file, search_files, glob    │
│                                         │
│ [📋 查看配置] [✏️ 编辑] [▶ 立即使用]    │
│ [❌ 删除]                                │
└─────────────────────────────────────────┘
```

**保留与发现**：
- 创建的 Agent 自动保存到 `identity/<name>/` 目录
- 自动注册到全局 Registry (`~/.egoagent_registry.json`)
- 在 Harness 选择器中自动出现
- Identity 管理面板中可浏览所有已创建的 Agent

**命名冲突处理**：
- 创建时检查是否已存在同名 identity
- 如果冲突：提示 "react_reviewer 已存在，是否覆盖 / 使用 react_reviewer_2？"
- 覆盖前自动创建 `.backup/` 快照

**自动推断**：
- 根据用户描述推断：
  - personality traits（分析型/创意型/严谨型等）
  - 需要的 tools（代码审查 → read_file + search_files）
  - 适合的 harness 模板（审查 → text_review_react）
  - LLM 参数（创意任务 → temperature 0.8，审查 → 0.3）

---

### 功能 10：DAG 可视化编辑器

**位置**：独立编辑器 Tab（类似 VSCode 的自定义编辑器）

**UI 设计**：
```
┌─────────────────────────────────────────────────────────┐
│ 🔧 DAG Editor: creative_roundtable    [Save] [Run] [×]  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│   ┌──────┐     ┌──────────┐     ┌──────────┐          │
│   │ 入口  │────→│ 创意推理  │────→│ 批评推理  │          │
│   └──────┘     └──────────┘     └──────────┘          │
│                                       │                 │
│                                       ↓ has_text        │
│                                 ┌──────────┐           │
│                                 │ 改进推理  │           │
│                                 └──────────┘           │
│                                       │                 │
│                              ↙ default  ↘ end_session  │
│                       [循环回入口]    [结束]              │
│                                                         │
├─────────────────────────────────────────────────────────┤
│ Node Properties (selected: 创意推理)                     │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Operation: [推理 ▼]                                  │ │
│ │ Agent Slot: [creative_brain ▼]                       │ │
│ │ Prompt Override: [                              ]    │ │
│ │ Outgoing Edges:                                      │ │
│ │   → 批评推理 [condition: has_text]                    │ │
│ │   → 入口 [condition: no_text]                        │ │
│ │ [+ Add Edge]                                         │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**操作**：
- 拖拽创建新节点
- 拖拽连线创建边
- 点击节点/边编辑属性
- 右键菜单：删除/复制/对齐
- Save 保存到 `harness/<name>/config.json`
- Run 立即在 Chat 面板中执行

**实现方案**：
- 使用轻量级图渲染库（dagre-d3 或自绘 SVG/Canvas）
- 编辑操作通过 API `PUT /api/harness/<name>` 持久化
- 支持导入/导出 JSON 格式

---

### 功能 11：Identity 管理面板

**位置**：侧边栏独立 Tab

**UI**：
```
┌─────────────────────────────────────┐
│ 👤 Identities        [+ Create New] │
├─────────────────────────────────────┤
│ 🔍 Search...                        │
├─────────────────────────────────────┤
│                                     │
│ ▼ Coding                            │
│   🟢 dante          编码工程师       │
│   🟢 coder          高级软件工程师   │
│   🔵 searcher       代码搜索专家     │
│                                     │
│ ▼ Creative                          │
│   🟡 creative_brain 创意家           │
│   🔴 sharp_critic   批评家           │
│                                     │
│ ▼ System                            │
│   ⚙️ improver_agent  系统改进        │
│   🛡️ privacy_guard  隐私守卫         │
│                                     │
└─────────────────────────────────────┘
```

点击单个 Identity 展开详情：
- ID 配置（name, role, description, traits）
- LLM 配置（model, temperature 等）
- SuperEgo 配置（hooks, whitelist/blacklist）
- Skills 列表（可增删）
- Knowledge 列表（可增删）
- 操作按钮：编辑 / 克隆 / 删除 / 测试对话

---

### 功能 12：Environment 注册中心

**问题**：当前环境分散在多个位置，用户难以发现和管理

**设计**：

```
┌─────────────────────────────────────────────┐
│ 🌍 Environment Registry                     │
├─────────────────────────────────────────────┤
│                                             │
│ 📍 Global (~/.environment)                  │
│   Tools (5): read_file, write_file,         │
│     patch_file, search_files, run_command   │
│   Knowledge (0)                             │
│                                             │
│ 📍 Workspace (/home/tiger/project/.env)     │
│   Tools (2): deploy, lint                   │
│   Knowledge (1): project_guide              │
│                                             │
│ 📍 Identity: dante (ego/)                   │
│   Tools (27): create_harness, ...           │
│   Knowledge (1): harness_guide              │
│                                             │
├─────────────────────────────────────────────┤
│ ⚠️ Conflicts:                               │
│   "read_file" defined in:                   │
│   - Global (priority: LOW)                  │
│   - dante/ego (priority: HIGH) ← 生效      │
│                                             │
├─────────────────────────────────────────────┤
│ [+ Register New Environment]                │
│ [🔍 Auto-Detect Workspace]                  │
└─────────────────────────────────────────────┘
```

**注册机制**：
- 所有环境统一注册到 `~/.egoagent_registry.json`
- 打开新 workspace 时自动检测（通过 `api_extensions.py` 的 detect 功能）
- 冲突策略：Identity EGO > Workspace > Global（后加载覆盖先加载）
- UI 上明确标注冲突并显示哪个版本生效

**命名冲突处理规则**：
1. **同一环境内**：不允许重名，创建时报错
2. **跨环境同名**：按优先级决定生效版本，UI 标注冲突
3. **用户手动解决**：支持重命名或设置 `no_tool_override` 标记
4. **冲突面板**：展示所有冲突，一键解决

---

### 功能 13：进化控制台

**UI**：
```
┌─────────────────────────────────────────────────────┐
│ 🧬 Evolution Console                                │
├─────────────────────────────────────────────────────┤
│ Target: [dante ▼]  Strategy: [engine ▼]             │
│                                                     │
│ 📊 Current Status: Cycle 3/10 · Step: 蒸馏原则     │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Score: 0.45 → 0.52 → 0.58 → ?                  │ │
│ │         ────────█████████░░░                    │ │
│ └─────────────────────────────────────────────────┘ │
│                                                     │
│ 📝 Recent Actions:                                  │
│   Cycle 2: 添加原则 "代码修改前先搜索确认"          │
│   Cycle 2: 修改 temperature 0.7 → 0.5             │
│   Cycle 1: 添加原则 "使用完整路径"                  │
│                                                     │
│ 📚 Principle Library (12 条):                       │
│   [Score 0.85] "修改文件前先 read_file 确认内容"    │
│   [Score 0.72] "搜索时使用精确路径"                  │
│   ...                                               │
│                                                     │
│ [▶ Start] [⏸ Pause] [⏹ Stop] [📋 Full Report]     │
└─────────────────────────────────────────────────────┘
```

---

### 功能 14：Session 历史浏览器

**UI**：
```
┌─────────────────────────────────────────┐
│ 📜 Session History                       │
├─────────────────────────────────────────┤
│ 🔍 Search sessions...                   │
├─────────────────────────────────────────┤
│ Today                                    │
│  14:32 dante · coder_react              │
│  "重构 utils.ts 中的 helper 函数"       │
│  Result: ✅ Success (3 files modified)   │
│                                         │
│  11:15 creative_roundtable              │
│  "设计智能花盆 APP"                      │
│  Result: ✅ 4 agents, 8 turns           │
│                                         │
│ Yesterday                                │
│  ...                                    │
├─────────────────────────────────────────┤
│ [📊 Analyze] [🔄 Replay] [📋 Export]    │
└─────────────────────────────────────────┘
```

**功能**：
- 浏览所有历史 session（按时间倒序）
- 点击 session 查看完整对话回放
- 支持分析（调用 evaluate_session）
- 支持将历史对话作为上下文 @session 引用
- 搜索：按关键词/时间/harness/identity 筛选

---

### 功能 15：多 Agent 协作实时追踪

**设计**：当使用多 Agent harness 时，Chat 面板实时展示每个 Agent 的思考过程

```
┌─────────────────────────────────────────────────────┐
│ 🔄 Live: creative_roundtable (Running)              │
├─────────────────────────────────────────────────────┤
│                                                     │
│ 🟢 创意家 is thinking...                             │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 我认为可以从以下几个角度...                       │ │  ← 流式输出
│ │ █                                               │ │
│ └─────────────────────────────────────────────────┘ │
│                                                     │
│ 🔴 批评家 waiting...                                 │  ← 等待中
│ 🟡 创意家(改进) pending...                           │  ← 未开始
│                                                     │
└─────────────────────────────────────────────────────┘
```

**实现**：需要 WebSocket 直连（绕过当前代理层）或轮询 API

---

### 功能 16：Checkpoint/Rollback

**设计**：
- Agent 开始工作前自动创建 Git stash 或内部 checkpoint
- 每个重大操作后创建增量 checkpoint
- 用户可随时回滚到任意 checkpoint

```
Agent Changes Timeline:
  [CP0: 初始] → [CP1: 读取文件] → [CP2: 修改 utils.ts] → [CP3: 修改 index.ts]
                                         ↑
                                    [← 回滚到此]
```

**实现**：
- 基于 git stash 或自建的文件快照系统
- API: `POST /api/checkpoint/create`, `POST /api/checkpoint/rollback/{id}`
- 前端在 Chat 面板中显示 checkpoint 标记

---

### 功能 17：Knowledge Base 管理

**UI**：
```
┌─────────────────────────────────────────────┐
│ 📚 Knowledge Base                            │
├─────────────────────────────────────────────┤
│ 📍 dante/ego/knowledge/                     │
│   📄 harness_guide (1.2KB)     [Edit][Del]  │
│                                             │
│ 📍 Global/.environment/knowledge/           │
│   (empty)                                   │
│                                             │
│ [+ Import File] [+ Create New]              │
│ [📥 Import from URL]                        │
└─────────────────────────────────────────────┘
```

**功能**：
- 查看所有 knowledge 文件内容
- 直接在 IDE 中编辑（打开为文本文件）
- 导入外部文件/URL 作为知识
- 关联到特定 Identity 或全局

---

## 第三部分：架构设计

### 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Browser (Void Web IDE)                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌──────────┐  │
│  │ Monaco   │  │ Chat      │  │ DAG      │  │ Settings │  │
│  │ Editor   │  │ Panel     │  │ Editor   │  │ Panels   │  │
│  │ (files)  │  │ (agents)  │  │ (visual) │  │ (CRUD)   │  │
│  └────┬─────┘  └─────┬─────┘  └────┬─────┘  └────┬─────┘  │
│       │               │             │              │        │
│       └───────────────┼─────────────┼──────────────┘        │
│                       ↓                                     │
│              ┌─────────────────┐                            │
│              │ EgoAgent Client │  ← 统一 API 客户端层        │
│              │ (JS module)     │                            │
│              └────────┬────────┘                            │
│                       │                                     │
└───────────────────────┼─────────────────────────────────────┘
                        │ HTTP + WebSocket
                        ↓
┌───────────────────────────────────────────────────────────────┐
│              Proxy Layer (start-all.py :8880)                  │
│  /v1/*, /api/* → Backend:8765    │   /* → Void:8869          │
└────────────────────┬──────────────────────────────────────────┘
                     ↓
┌───────────────────────────────────────────────────────────────┐
│                 EgoAgent Backend (:8765 + :8766 WS)            │
├───────────────────────────────────────────────────────────────┤
│  server.py          │  api_extensions.py                      │
│  - /v1/chat/comp.   │  - /api/environments                   │
│  - /api/harnesses   │  - /api/experiments                    │
│  - /api/identities  │  - /api/harnesses/detailed             │
│  - /api/sessions    │  - /api/pipeline/sessions              │
│  - /api/execution   │                                        │
│  - /api/evolution   │                                        │
├───────────────────────────────────────────────────────────────┤
│  pipeline_engine.py │  self_evolution/engine.py               │
│  - DAG execution    │  - Principle Library                    │
│  - Node operations  │  - TextGrad Optimizer                   │
│  - WebSocket events │  - Gated Controller                     │
│  - Sub-pipelines    │  - Self-Play / TriRole                  │
├───────────────────────────────────────────────────────────────┤
│  agent.py + identity + environment + tools                    │
└───────────────────────────────────────────────────────────────┘
                     ↓
┌───────────────────────────────────────────────────────────────┐
│                    LLM Service (vLLM :9638)                    │
│                    Model: qwen (1.5B / 7B / 72B)              │
└───────────────────────────────────────────────────────────────┘
```

### 前端技术方案

由于 Void Web 的限制（无法使用 VSCode 扩展 API），采用 **直接注入** 方案：

1. **主入口**：修改 `workbench.html`，注入主框架 HTML + 加载 JS 模块
2. **JS 模块化**：将功能拆分为独立 JS 文件，通过 `<script>` 标签加载
   - `egoagent-core.js` — API 客户端、状态管理
   - `egoagent-chat.js` — Chat 面板逻辑
   - `egoagent-diff.js` — Diff 视图逻辑
   - `egoagent-dag.js` — DAG 编辑器
   - `egoagent-panels.js` — 管理面板（Identity/Environment/Session）
3. **样式**：独立 CSS 文件注入，使用 CSS 变量兼容 VSCode 主题
4. **通信**：所有 API 调用通过 `window.location.origin` 相对路径

### 后端新增 API

```
# Diff/Changes 管理
GET  /api/session/changes              — 获取当前 session 的文件变更列表
POST /api/session/changes/accept       — 接受变更（全文件或单块）
POST /api/session/changes/reject       — 拒绝变更（触发还原）
POST /api/session/changes/revert-all   — 回滚所有变更

# Checkpoint
POST /api/checkpoint/create            — 创建快照
GET  /api/checkpoints                  — 列出快照
POST /api/checkpoint/rollback/{id}     — 回滚到指定快照

# 上下文引用
GET  /api/files/search?q=...           — 模糊搜索文件
GET  /api/files/content?path=...       — 获取文件内容
GET  /api/symbols/search?q=...         — 代码符号搜索

# 工具审批
POST /api/tool/approve                 — 批准/拒绝工具执行

# Agent 创建
POST /api/agent/create-from-description — 从自然语言描述创建 Agent
```

---

## 第四部分：实现优先级与路线图

### Phase 1 — 基础可用 (P0)
1. ✅ Chat 面板（已实现基础版）
2. 文件编辑 Diff 视图
3. Agent 修改看板
4. @ 上下文引用
5. 终端命令集成（审批模式）
6. ✅ Harness 选择器（已实现基础版）
7. ✅ DAG 流程可视化（已实现基础版）
8. 工具调用展示优化

### Phase 2 — 高级特性 (P1)
9. 一句话创建 Agent
10. DAG 可视化编辑器
11. Identity 管理面板
12. Environment 注册中心
13. 进化控制台
14. Session 历史浏览器
15. 多 Agent 实时追踪
16. Checkpoint/Rollback
17. Knowledge Base 管理

### Phase 3 — 增强体验 (P2)
18-26. Tab 补全、内联编辑、跨会话记忆等

---

## 第五部分：设计决策记录

### Q1: Agent 创建后如何保留和发现？
**决策**：
- 保存位置：`identity/<name>/` 目录
- 注册：自动写入 `~/.egoagent_registry.json`
- 发现：Identity 管理面板 + Harness 选择器下拉 + @identity 引用
- 生命周期：永久保留直到用户主动删除
- 命名规则：小写字母 + 下划线，不超过 32 字符

### Q2: Environment 命名冲突如何处理？
**决策**：
- **同一环境内重名**：创建时报错，提示重命名
- **跨环境同名**：按优先级覆盖（Identity EGO > Workspace > Global）
- **UI 提示**：环境面板标注所有冲突，显示实际生效版本
- **手动解决**：支持重命名或添加 `no_tool_override` 标记
- **最佳实践**：建议用户为自定义工具添加前缀（如 `myproject_deploy`）

### Q3: 多 Agent 输出如何展示？
**决策**：
- 每个 Agent 独立消息气泡，颜色区分
- 支持折叠单个 Agent 的完整输出
- DAG 流程条同步高亮当前 Agent
- 最终汇总由最后一个 Agent 产出（或专门的 "Moderator" 节点）

### Q4: Diff Accept/Reject 默认行为？
**决策**：
- Agent 修改立即写入磁盘（保持实时性）
- 未处理的变更标记为 "pending"
- 30 秒无操作不自动处理（始终等待用户决定）
- 支持 "Auto-Accept" 模式（在设置中开启）
- Reject 时执行反向 patch 还原

### Q5: 项目规则系统格式？
**决策**：
- 文件位置：`.egoagent/rules/` 目录
- 格式：Markdown 文件（`.md`）
- 加载时机：每次 Chat 发送消息时注入 system prompt
- 优先级：项目规则 > 全局规则 > Identity 默认规则
- 示例规则文件：
  ```markdown
  # 代码风格规则
  - 使用 TypeScript strict mode
  - 函数不超过 30 行
  - 每个文件必须有 JSDoc 注释
  ```
