# EgoAgent 产品开发分块文档

> 最后更新: 2026-06-28
> 本文档将 EgoAgent 产品按功能领域划分为 3 个独立开发区块。

---

## 产品总览

EgoAgent 是一个**文件系统驱动的多 Agent 框架**。核心理念：

- **Identity 即目录**：agent 的完整定义（性格、工具、知识、约束）就是一个文件系统目录
- **自我进化**：Agent 可以通过写文件来创建或修改 identity、skill、knowledge
- **声明式编排**：多 Agent 协作通过 Harness 的数据流图编排
- **环境分层**：全局环境 → workspace 环境 → identity 自身，逐层叠加工具和知识

---

## 区块划分

```
┌──────────────────────────────────────────────────────────┐
│                    区块 3: 评估系统                        │
│         SWE-bench 评估 + Meilisearch 全局搜索              │
├──────────────────────────────────────────────────────────┤
│                    区块 2: Harness 编排                    │
│      多 Agent 协作、数据流图、嵌套、Session 管理            │
├──────────────────────────────────────────────────────────┤
│                    区块 1: 算法引擎                        │
│    Agent 推理、工具执行、消息协议、权限、Identity 定义、    │
│    Environment 工具/知识发现、Registry、LLM 后端            │
└──────────────────────────────────────────────────────────┘
```

**依赖关系**：算法引擎 → Harness 编排 → 评估系统

---

## 区块 1: 算法引擎

> **负责人**: ________  
> **依赖**: 无  
> **核心文件**: `agent.py`, `environment.py`, `llm/`, `config.py`, `config.yaml`, `utils.py`, `identity/*/`, `playground_malkuth/`, `~/.egoagent_registry.json`

### 职责

Agent 的"大脑"和"身份"——推理能力、工具执行、Identity 定义、工具/知识发现。这是整个框架的地基。

### 核心架构

```
┌─────────────────────────────────────────┐
│              算法引擎                     │
│                                          │
│  ┌──────────┐  ┌──────────────────────┐ │
│  │  Agent   │  │  Identity/Environment │ │
│  │  推理     │  │  定义层               │ │
│  │  工具执行  │  │  ID/EGO/SEGO         │ │
│  │  消息协议  │  │  工具/知识发现        │ │
│  │  权限控制  │  │  Registry            │ │
│  └──────────┘  └──────────────────────┘ │
│                                          │
│  ┌──────────────────────────────────┐   │
│  │  LLM 后端 (OpenAI 兼容 HTTP API)  │   │
│  └──────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

### 子模块

#### 1A. Agent 推理与执行 (`agent.py`)

三种原子操作：

| 方法 | 功能 |
|------|------|
| `step(messages)` | LLM 推理 → 返回文本 + 工具调用 |
| `process_text(text, context, prompt)` | 审查/改写文本输出 |
| `process_tool_calls(tool_calls, context, prompt)` | 审查/过滤工具调用 |

关键机制：
- **消息协议**：`<tool_call>` / `<tool_response>` / `<system_instructions>` XML 标签，role:user 统一
- **工具执行**：自动 `os.chdir(workspace)`，支持 `_context` 参数注入
- **权限控制**：whitelist/blacklist + `config.yaml` 命令黑名单

#### 1B. Identity 定义 (`identity/{name}/`)

```
identity/{name}/
├── id.json          # 性格、角色、LLM 配置
├── ego/
│   ├── skills/      # 专属工具 (meta.json + scripts/*.py)
│   └── knowledge/   # 专属知识 (meta.json + *.txt)
└── superego/
    ├── config.json  # 权限、白名单/黑名单、task_prompt
    └── *_hook.py    # pre/post LLM/tool hooks
```

已有 Identity：

| Identity | 角色 | 工具数 | 特点 |
|----------|------|--------|------|
| **coder** | 高级软件工程师 | 11 | 主力编程 agent |
| **searcher** | 代码搜索专家 | 4 | whitelist 限制只有搜索工具 |
| **privacy_guard** | 隐私审查员 | 0 | temperature=0.1 |
| **dante** | 通用 agent | 10 | 有 harness 创建等管理工具 |
| **id1** | 基础 coding engineer | 4 | 最小工具集 |
| **dog/cat** | 测试 agent | 4 | 带前缀的测试 agent |

#### 1C. Environment 工具/知识发现 (`environment.py`)

三层叠加（后加载覆盖先加载）：
1. Identity 自身 `identity/{name}/ego/`
2. 全局环境 `/home/tiger/.environment/`
3. Workspace 环境 `{workspace}/.environment/`

核心工具（playground_malkuth，20 个）：

| 类别 | 工具 |
|------|------|
| 搜索 | `search_files`, `glob_search` |
| 文件 | `read_file`, `write_file`, `patch_file`, `multi_edit`, `ls`, `copy` |
| 系统 | `run_command`, `check_command_status`, `stop_command` |
| 编排 | `create_harness`, `assign_agent` |
| 自进化 | `copy_identity`, `copy_harness` |
| 元信息 | `list_identities`, `list_all_resources` |
| 控制 | `end_session` |

#### 1D. LLM 后端 (`llm/`)

- OpenAI 兼容 HTTP API，流式/非流式
- 自动记录 IO 日志到 session
- 当前模型：Qwen3-8B-yangyuan

#### 1E. 全局 Registry (`~/.egoagent_registry.json`)

记录所有 identity 和 environment 路径，用于 Meilisearch 索引和 `list_all_resources`。

### 待办事项

| 优先级 | 任务 |
|--------|------|
| P0 | Agent 创建 identity 工具（从零创建，非仅复制） |
| P0 | Agent 创建 tool/knowledge 工具（写文件到 ego 目录） |
| P1 | Registry 自动注册（创建 identity 时自动更新） |
| P1 | 流式输出支持 |
| P1 | 工具调用重试机制（JSON 解析失败自动重试） |
| P1 | 多 LLM provider 支持（Anthropic、本地模型等） |
| P1 | Sync 审核机制（Agent 创建新内容时审核冲突） |
| P2 | 工具执行超时 |
| P2 | 并行工具调用 |
| P2 | 工具热重载（无需重启） |
| P2 | 工具依赖管理 |
| P3 | Token 计数与自动裁剪 |
| P3 | Identity 版本管理 |
| P3 | Identity 市场 |

---

## 区块 2: Harness 编排

> **负责人**: ________  
> **依赖**: 区块 1（算法引擎）  
> **核心文件**: `harness.py`, `pipeline_engine.py`, `harness/*/config.json`, `harness/*/protocol.py`（向后兼容）, `run_harness.py`

### 职责

多 Agent 协作的编排层——控制 Agent 之间的交互流程、Session 生命周期管理。是框架区别于单 Agent 系统的核心差异化能力。

### 核心架构

```
┌──────────────────────────────────────────────────────┐
│                   Harness 编排                         │
│                                                       │
│  ┌────────────────────────────────────────────────┐  │
│  │           Pipeline 引擎 (pipeline_engine.py)     │  │
│  │                                                  │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │  │
│  │  │  react   │  │ sequential│  │  conditional │  │  │
│  │  │  循环推理 │  │  顺序执行  │  │   条件分支    │  │  │
│  │  └──────────┘  └──────────┘  └──────────────┘  │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │  │
│  │  │ parallel │  │  round    │  │   custom     │  │  │
│  │  │  并行执行 │  │  轮次制    │  │   自定义脚本  │  │  │
│  │  └──────────┘  └──────────┘  └──────────────┘  │  │
│  └────────────────────────────────────────────────┘  │
│                                                       │
│  ┌──────────┐  ┌──────────┐  ┌────────────────────┐ │
│  │  Slot 管理 │  │ 嵌套执行  │  │  Session 持久化    │ │
│  │  必填校验  │  │  栈式管理  │  │  messages/state   │ │
│  └──────────┘  └──────────┘  └────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

### 设计理念：声明式 Pipeline

Harness 编排不再需要写 `protocol.py`。只需在 `config.json` 中定义 `pipeline`，引擎自动解释执行。

```json
{
  "name": "guarded_react",
  "slots": {
    "worker": {"description": "主 agent", "required": true},
    "guardian": {"description": "审查 agent", "required": true}
  },
  "prompts": {
    "guardian_review": {
      "default": "审查以下工具调用..."
    }
  },
  "pipeline": {
    "type": "react",
    "max_steps": 100,
    "steps": [
      {"agent": "worker", "op": "推理"},
      {"agent": "guardian", "op": "处理工具", "prompt": "guardian_review"}
    ]
  }
}
```

### 原子操作类型

| 操作 | Agent 方法 | 输入 | 输出 | 用途 |
|------|-----------|------|------|------|
| `推理` | `step(messages)` | 对话历史 | text + tool_calls | 正常 LLM 推理 |
| `处理文字` | `process_text(text, context, prompt)` | text | 修改后的 text | 审查/改写文本输出 |
| `处理工具` | `process_tool_calls(tool_calls, context, prompt)` | tool_calls | 过滤后的 tool_calls | 审查/过滤工具调用 |

### Pipeline 类型

| 类型 | 说明 | 适用场景 |
|------|------|---------|
| `react` | 用户输入 → steps 序列 → 执行工具 → 循环 | 单/多 Agent ReAct、带 Guardian 的 ReAct |
| `sequential` | 按阶段顺序执行，阶段间传递数据 | 流水线处理、多阶段任务 |
| `round` | 多角色轮次制，每轮按顺序发言 | 辩论、圆桌讨论、回合制游戏 |
| `parallel` | 多个 agent 同时推理，结果汇总 | 多专家并行分析、投票 |
| `conditional` | 根据上一步结果选择分支 | 动态路由、异常处理 |
| `custom` | 回退到 protocol.py 自定义脚本 | 极其复杂的编排逻辑 |

### 已有 Harness

#### react_single — 单 Agent ReAct

```
用户输入 → [agent:推理] → 工具调用 → 系统执行 → 工具结果 → (循环)
```

- Slots: `agent`（必填）
- Pipeline: `{"type": "react", "steps": [{"agent": "agent", "op": "推理"}]}`
- 支持用户直接调用工具 `\tool_name(args)`

#### coder_react — 编程专用 ReAct

```
用户输入 → [agent:推理] → 工具调用 → 系统执行 → 工具结果 → (循环，最多30步)
```

- Slots: `agent`（必填）
- Pipeline: `{"type": "react", "max_steps": 30, "workspace_preview": true, "steps": [...]}`
- 自动注入 workspace 目录预览

#### guarded_react — 带 Guardian 审查

```
用户输入 → [worker:推理] → [guardian:处理工具] → 系统执行 → (循环)
```

- Slots: `worker`（必填）、`guardian`（必填）
- Pipeline: `{"type": "react", "steps": [{"agent": "worker", "op": "推理"}, {"agent": "guardian", "op": "处理工具", "prompt": "guardian_review"}]}`
- Guardian 输出可见（`✓ 通过` / `✗ 拦截: reason`）

#### turn_based — 多轮辩论

```
裁判开场 → [正方:推理] → [反方:推理] → [裁判:推理] → (循环，最多5轮)
```

- Slots: `正方`（必填）、`反方`（必填）、`裁判`（必填）
- 裁判可提前 `[DONE]` 宣判
- 当前使用 `protocol.py`（custom 类型），待迁移到 `round` pipeline

---

### 复杂编排场景 Brainstorm

以下场景超出了当前简单 ReAct/轮次制的表达能力，需要更丰富的 Pipeline 原语。

---

#### 场景 A: TRPG 跑团（桌游主持人 + 多名玩家）

```
┌─────────────────────────────────────────────────────┐
│                    TRPG 跑团                          │
│                                                       │
│  [KP:推理] 描述场景、推进剧情                          │
│      │                                                │
│      ▼                                                │
│  ┌─────────────────────────────────────┐             │
│  │       按顺序询问存活玩家              │             │
│  │  ┌──────┐  ┌──────┐  ┌──────┐       │             │
│  │  │玩家A │→│玩家B │→│玩家C │→ ...   │             │
│  │  │(存活)│ │(存活)│ │(死亡)│ 跳过    │             │
│  │  └──┬───┘  └──┬───┘  └──────┘       │             │
│  │     │         │                      │             │
│  │     ▼         ▼                      │             │
│  │  推理+工具   推理+工具                │             │
│  │  (受限tool) (受限tool)               │             │
│  └─────────────────────────────────────┘             │
│      │                                                │
│      ▼                                                │
│  [KP:处理] 汇总所有玩家行动，判定结果                   │
│      │                                                │
│      ▼                                                │
│  [KP:推理] 更新场景状态 → 下一轮                        │
└─────────────────────────────────────────────────────┘
```

**需要的原语**：
- **动态可见性**：每个玩家只能看到 KP 的公开描述 + 自己的私密信息（不同 agent 看到不同的 messages 子集）
- **条件跳过**：玩家死亡/离线时自动跳过该 slot
- **受限工具集**：不同玩家有不同的可用工具（如战士有攻击技能、法师有魔法）
- **状态持久化**：角色 HP、装备、位置等状态跨轮次保持
- **KP 汇总节点**：收集所有玩家行动后统一判定

**Config 设想**：
```json
{
  "name": "trpg_coc",
  "slots": {
    "kp": {"description": "守秘人", "required": true},
    "players": {
      "type": "list",
      "description": "玩家列表",
      "item_slot": {
        "name": "player_{index}",
        "identity": "identity/player",
        "state": {"hp": 10, "alive": true, "inventory": []}
      }
    }
  },
  "pipeline": {
    "type": "round",
    "max_rounds": 100,
    "phases": [
      {
        "name": "kp_narrate",
        "agent": "kp",
        "op": "推理",
        "prompt": "kp_narrate"
      },
      {
        "name": "players_act",
        "type": "sequential",
        "foreach": "players",
        "condition": "item.alive == true",
        "steps": [
          {"agent": "$item", "op": "推理", "visibility": "kp_public + self_private"}
        ]
      },
      {
        "name": "kp_resolve",
        "agent": "kp",
        "op": "推理",
        "prompt": "kp_resolve"
      }
    ]
  }
}
```

---

#### 场景 B: 多轮辩论 + 投票团 + 观众提问

```
┌──────────────────────────────────────────────────────┐
│              辩论赛（正方 vs 反方 + 裁判 + 投票团）      │
│                                                       │
│  第 1 轮:                                              │
│    [正方:推理] 立论                                     │
│    [反方:推理] 立论                                     │
│    [观众A:推理] 提问 → [正方:推理] 回答                  │
│    [观众B:推理] 提问 → [反方:推理] 回答                  │
│    [裁判:推理] 点评                                     │
│                                                       │
│  第 2 轮:                                              │
│    [正方:推理] 反驳                                     │
│    [反方:推理] 反驳                                     │
│    [投票团:并行推理] 5人同时打分                         │
│    [裁判:推理] 汇总评分 + 点评                           │
│                                                       │
│  第 3 轮: 自由辩论                                      │
│    [正方:推理] → [反方:推理] → [正方:推理] → ...        │
│    (直到任一方超时或裁判叫停)                            │
│                                                       │
│  最终:                                                  │
│    [投票团:并行推理] 最终投票                            │
│    [裁判:推理] 宣布结果                                  │
└──────────────────────────────────────────────────────┘
```

**需要的原语**：
- **轮次内多阶段**：每轮有多个不同结构的子阶段
- **并行执行 + 汇总**：投票团 5 人同时打分，结果汇总给裁判
- **条件终止**：自由辩论阶段，裁判可随时 `[STOP]` 终止
- **动态路由**：观众提问后根据问题指向路由到正方或反方
- **加权投票**：不同投票者权重不同（如裁判 3 票、普通观众 1 票）

---

#### 场景 C: 圆桌协作 + 任务分发（项目经理模式）

```
┌──────────────────────────────────────────────────────┐
│              圆桌协作（PM + 多名专家）                   │
│                                                       │
│  [用户] 提出需求                                        │
│      │                                                │
│      ▼                                                │
│  [PM:推理] 分析需求，拆解为子任务                       │
│      │                                                │
│      ▼                                                │
│  ┌─────────────────────────────────────┐             │
│  │        并行分发子任务                 │             │
│  │  ┌──────────┐  ┌──────────┐        │             │
│  │  │前端专家   │  │后端专家   │  ...   │             │
│  │  │(coder)   │  │(coder)   │        │             │
│  │  └────┬─────┘  └────┬─────┘        │             │
│  │       │             │               │             │
│  │       ▼             ▼               │             │
│  │  各自 ReAct      各自 ReAct         │             │
│  │  (独立workspace) (独立workspace)    │             │
│  └─────────────────────────────────────┘             │
│      │                                                │
│      ▼                                                │
│  [PM:推理] 收集所有结果，整合、检查冲突                  │
│      │                                                │
│      ├── 有冲突 → 重新分发                             │
│      └── 无冲突 → [PM:推理] 输出最终方案                │
└──────────────────────────────────────────────────────┘
```

**需要的原语**：
- **并行子 harness**：每个专家在自己的 workspace 中独立 ReAct
- **子任务上下文注入**：PM 将子任务描述注入到对应专家的 system prompt
- **结果收集与合并**：所有子任务完成后 PM 统一处理
- **冲突检测 + 重试**：PM 检测到冲突后自动重新分发

---

#### 场景 D: 狼人杀 / 阿瓦隆（不完全信息博弈）

```
┌──────────────────────────────────────────────────────┐
│                    狼人杀                              │
│                                                       │
│  夜晚阶段:                                             │
│    [主持人:推理] 宣布夜晚降临                           │
│    [狼人:并行推理] 选择击杀目标（只有狼人能看到彼此）     │
│    [预言家:推理] 查验一名玩家身份（结果仅预言家可见）     │
│    [女巫:推理] 决定是否使用解药/毒药                     │
│                                                       │
│  白天阶段:                                             │
│    [主持人:推理] 宣布夜晚结果                           │
│    ┌─────────────────────────────────────┐           │
│    │       自由讨论（所有存活玩家）         │           │
│    │  玩家1 → 玩家2 → ... → 玩家N         │           │
│    │  (死亡玩家跳过)                       │           │
│    └─────────────────────────────────────┘           │
│    [所有存活玩家:并行推理] 投票放逐                     │
│    [主持人:推理] 宣布投票结果                           │
│                                                       │
│  循环直到游戏结束                                      │
└──────────────────────────────────────────────────────┘
```

**需要的原语**：
- **私密消息通道**：狼人之间、预言家-主持人之间有私密通信
- **角色身份隐藏**：每个 agent 不知道其他 agent 的真实角色
- **选择性信息揭示**：主持人控制哪些信息对哪些玩家可见
- **投票聚合**：收集所有投票后按规则判定结果
- **游戏结束条件检测**：自动检测狼人数量 == 村民数量 等终止条件

---

#### 场景 E: 代码审查委员会

```
┌──────────────────────────────────────────────────────┐
│               代码审查委员会                            │
│                                                       │
│  [作者:推理] 提交代码 + 设计说明                        │
│      │                                                │
│      ▼                                                │
│  ┌─────────────────────────────────────┐             │
│  │        并行审查（3名审查者）           │             │
│  │  ┌──────────┐  ┌──────────┐         │             │
│  │  │安全审查   │  │性能审查   │  ...    │             │
│  │  │(security) │  │(perf)    │         │             │
│  │  └────┬─────┘  └────┬─────┘         │             │
│  │       │             │               │             │
│  │       ▼             ▼               │             │
│  │  各自审查+工具    各自审查+工具      │             │
│  │  (只读工具)       (只读工具)        │             │
│  └─────────────────────────────────────┘             │
│      │                                                │
│      ▼                                                │
│  [主席:推理] 汇总审查意见，判定是否通过                  │
│      │                                                │
│      ├── 通过 → 合并                                   │
│      └── 驳回 → [作者:推理] 修改 → 重新审查             │
└──────────────────────────────────────────────────────┘
```

**需要的原语**：
- **只读工具约束**：审查者只能读取代码，不能修改
- **审查意见结构化**：每个审查者输出标准格式（通过/驳回 + 理由 + 建议）
- **主席汇总判定**：根据审查意见自动判定（全票通过 / 多数通过 / 一票否决）
- **驳回循环**：驳回后自动回到作者修改阶段

---

#### 场景 F: 多专家会诊（医疗/技术诊断）

```
┌──────────────────────────────────────────────────────┐
│               多专家会诊                                │
│                                                       │
│  [患者/用户] 描述症状/问题                              │
│      │                                                │
│      ▼                                                │
│  ┌─────────────────────────────────────┐             │
│  │        并行初诊                      │             │
│  │  ┌──────────┐  ┌──────────┐        │             │
│  │  │内科专家   │  │外科专家   │  ...   │             │
│  │  └────┬─────┘  └────┬─────┘        │             │
│  │       │             │               │             │
│  │       ▼             ▼               │             │
│  │  各自推理+工具   各自推理+工具       │             │
│  │  (各自知识库)    (各自知识库)       │             │
│  └─────────────────────────────────────┘             │
│      │                                                │
│      ▼                                                │
│  [主持人:推理] 汇总初诊意见，识别分歧点                  │
│      │                                                │
│      ▼                                                │
│  ┌─────────────────────────────────────┐             │
│  │        交叉辩论（针对分歧点）          │             │
│  │  内科 ↔ 外科 互相质疑 + 引用证据      │             │
│  └─────────────────────────────────────┘             │
│      │                                                │
│      ▼                                                │
│  [主持人:推理] 综合所有意见，给出最终诊断                │
└──────────────────────────────────────────────────────┘
```

**需要的原语**：
- **专属知识库**：每个专家有不同的 knowledge base
- **分歧检测**：自动识别专家意见中的矛盾点
- **交叉辩论子阶段**：针对分歧点让相关专家互相辩论
- **证据引用追踪**：专家的论断需要引用知识库中的具体条目

---

#### 场景 G: 模拟联合国 (MUN)

```
┌──────────────────────────────────────────────────────┐
│               模拟联合国                               │
│                                                       │
│  阶段 1: 立场陈述                                      │
│    [美国:推理] → [中国:推理] → [俄罗斯:推理] → ...     │
│                                                       │
│  阶段 2: 自由磋商                                      │
│    ┌─────────────────────────────────────┐           │
│    │  任意代表可发言，可形成联盟            │           │
│    │  美国 → 英国 → 中国 → 法国 → ...     │           │
│    │  (动态顺序，基于举手/优先级)          │           │
│    └─────────────────────────────────────┘           │
│                                                       │
│  阶段 3: 决议草案                                      │
│    [起草国:推理] 撰写决议草案                           │
│    [所有国家:并行推理] 投票 (赞成/反对/弃权)            │
│    [主席:推理] 宣布结果                                 │
│                                                       │
│  阶段 4: 修正案（如有）                                 │
│    [反对国:推理] 提出修正案                             │
│    [所有国家:并行推理] 投票                             │
└──────────────────────────────────────────────────────┘
```

**需要的原语**：
- **动态发言顺序**：基于优先级队列或举手机制
- **联盟形成**：agent 之间可以私聊形成联盟
- **决议草案协作**：多个 agent 共同编辑一份文档
- **多轮投票**：不同阶段有不同的投票规则（简单多数 / 2/3 多数 / 否决权）

---

#### 场景 H: 创业模拟 / 商业决策

```
┌──────────────────────────────────────────────────────┐
│              创业模拟（CEO + 各部门）                    │
│                                                       │
│  [市场] 注入外部事件（竞争对手动态、政策变化）           │
│      │                                                │
│      ▼                                                │
│  ┌─────────────────────────────────────┐             │
│  │        部门并行分析                   │             │
│  │  ┌──────────┐  ┌──────────┐        │             │
│  │  │市场部     │  │技术部     │  ...   │             │
│  │  │(分析市场) │  │(评估技术) │        │             │
│  │  └────┬─────┘  └────┬─────┘        │             │
│  │       │             │               │             │
│  │       ▼             ▼               │             │
│  │  各自推理+工具   各自推理+工具       │             │
│  │  (市场数据)      (技术指标)         │             │
│  └─────────────────────────────────────┘             │
│      │                                                │
│      ▼                                                │
│  [CEO:推理] 综合各部门报告，做出决策                     │
│      │                                                │
│      ▼                                                │
│  [市场] 反馈决策结果，更新公司状态                      │
│      │                                                │
│      ▼                                                │
│  下一季度...                                           │
└──────────────────────────────────────────────────────┘
```

**需要的原语**：
- **外部事件注入**：非 agent 的"环境"角色定时注入事件
- **经济系统状态机**：公司资金、市场份额等数值状态跨轮次演化
- **部门预算约束**：不同部门有不同的资源限制
- **随机事件**：市场变化有一定随机性

---

### Pipeline 编排原语体系

综合以上场景，Harness 编排需要以下原语：

#### 第一层：流程控制原语

| 原语 | 说明 | 示例场景 |
|------|------|---------|
| `sequential` | 按顺序执行步骤 | 辩论发言顺序 |
| `parallel` | 多个 agent 同时推理 | 投票团打分、多专家并行分析 |
| `round` | 多轮循环，每轮有多个阶段 | 辩论、跑团、狼人杀 |
| `conditional` | 根据条件选择分支 | 裁判判定胜负、冲突检测 |
| `foreach` | 遍历 slot 列表执行 | 遍历存活玩家 |
| `while` | 条件循环 | 自由辩论直到有人叫停 |
| `sub_harness` | 启动子 harness（嵌套） | 专家独立 workspace 工作 |

#### 第二层：数据/消息控制原语

| 原语 | 说明 | 示例场景 |
|------|------|---------|
| `visibility` | 控制每个 agent 能看到哪些消息 | 狼人杀私密频道、TRPG 玩家视野 |
| `message_filter` | 按角色/标签过滤消息 | 只给专家看相关子任务 |
| `state_inject` | 向 agent 注入状态变量 | 注入角色 HP、公司资金 |
| `result_collect` | 收集多个 agent 的输出并合并 | 投票汇总、审查意见汇总 |
| `private_channel` | agent 之间的私密通信 | 狼人间私聊、联盟磋商 |

#### 第三层：Agent 能力约束原语

| 原语 | 说明 | 示例场景 |
|------|------|---------|
| `tool_whitelist` | 限制 agent 可用工具 | 审查者只读、玩家只能用自己的技能 |
| `tool_blacklist` | 禁止特定工具 | 禁止修改代码的审查者 |
| `knowledge_binding` | 绑定专属知识库 | 内科专家 vs 外科专家的知识库 |
| `step_limit` | 限制单次推理步数 | 防止 agent 无限循环 |
| `timeout` | 超时自动终止 | 自由辩论超时 |

#### 第四层：状态与判定原语

| 原语 | 说明 | 示例场景 |
|------|------|---------|
| `state_machine` | 全局状态机 | 游戏阶段切换、角色生死状态 |
| `vote_aggregator` | 投票聚合与判定 | 狼人杀投票、联合国表决 |
| `conflict_detector` | 检测 agent 输出中的冲突 | 多专家意见分歧检测 |
| `termination_condition` | 自定义终止条件 | 狼人数量 == 村民数量 |
| `event_trigger` | 外部事件触发 | 市场变化、随机事件 |

---

### Harness 嵌套

支持栈式嵌套——子 harness 运行时父 harness 被压栈，结束后自动恢复。

```python
create_harness(harness_dir="react_single", agents="agent:identity/searcher", task="搜索任务")
```

### Session 系统

- `messages`: 对话历史（传给 LLM）
- `full_messages`: 含 system prompt 的完整版（调试用）
- `state`: 任意键值对状态存储（跨轮次持久化）
- 持久化到 `sessions/{harness_name}_{timestamp}/`

### 启动方式

```bash
# 通用启动
python run_harness.py --harness_dir <dir> --agents slot:identity [--workspace <path>]

# 示例
python run_harness.py --harness_dir harness/react_single --agents agent:identity/dante --workspace playground_malkuth
python run_harness.py --harness_dir harness/coder_react --agents agent:identity/coder --workspace playground_malkuth
python run_harness.py --harness_dir harness/guarded_react --agents worker:identity/coder guardian:identity/privacy_guard
python run_harness.py --harness_dir harness/turn_based --agents 正方:identity/id1 反方:identity/id1 裁判:identity/dante --prompts "task:辩题"
```

### 待办事项

| 优先级 | 任务 | 说明 |
|--------|------|------|
| **P0** | ✅ 声明式 Pipeline Config | 已完成：`pipeline_engine.py` + `config.json` 中的 `pipeline` 字段 |
| **P0** | `round` pipeline 类型 | 多轮次制编排（辩论、跑团、狼人杀的基础） |
| **P0** | `parallel` pipeline 类型 | 多 agent 并行推理 + 结果汇总 |
| **P0** | `conditional` 条件分支 | 根据上一步输出选择不同分支 |
| **P0** | `foreach` 遍历执行 | 遍历 slot 列表（如遍历存活玩家） |
| **P1** | `visibility` 消息可见性控制 | 不同 agent 看到不同的消息子集（私密频道） |
| **P1** | `state_machine` 全局状态机 | 游戏阶段管理、角色状态追踪 |
| **P1** | `vote_aggregator` 投票聚合 | 投票收集 + 规则判定 |
| **P1** | `sub_harness` 子 harness 启动 | 专家独立 workspace 中工作 |
| **P1** | `message_filter` 消息过滤 | 按角色/标签选择性传递消息 |
| **P1** | Human-in-the-loop | 关键步骤暂停等待人工确认 |
| **P2** | `private_channel` 私密通信 | agent 间点对点私聊 |
| **P2** | `event_trigger` 外部事件注入 | 模拟市场变化、随机事件 |
| **P2** | `conflict_detector` 冲突检测 | 自动识别 agent 输出矛盾 |
| **P2** | Harness 可视化编辑器 | 用户画图定义 agent 协作流程 |
| **P2** | 动态 slot 分配 | 运行时自动选择最合适的 agent |
| **P3** | Harness 模板市场 | 社区共享 harness 模板 |
| **P3** | 性能监控 | 每个节点耗时、token 消耗统计 |
| **P3** | `termination_condition` 自定义终止 | 用户定义游戏结束条件表达式 |

---

## 区块 3: 评估系统

> **负责人**: ________  
> **依赖**: 区块 1（算法引擎）、区块 2（Harness 编排）  
> **核心文件**: `swebench_eval/`, `meilisearch_manager/`, `scripts/`

### 职责

验证 Agent 能力和全局资源搜索——评估 Agent 在真实编程任务上的表现，以及跨所有 identity/environment 的工具和知识搜索。

### 子模块

#### 3A. SWE-bench 评估

```
SWE-bench 数据集 → run_agent.py → agent 修复代码 → git diff → predictions.jsonl → run_eval.sh (Docker) → 评测报告
```

当前配置：

| 参数 | 值 |
|------|-----|
| Harness | `coder_react` |
| Identity | `coder` |
| 超时 | 300s |
| Max steps | 50 |

已做优化：`os.chdir(workspace)`、`patch_file` 转义容错、Task prompt 优化、Debug 输出、Git clone 代理。

使用方式：
```bash
python swebench_eval/run_agent.py --instance_id astropy__astropy-12907
python swebench_eval/run_agent.py --num_tasks 5
bash swebench_eval/run_eval.sh swebench_eval/predictions.jsonl  # 需要 Docker
```

#### 3B. Meilisearch 全局搜索

```
run_harness.py → MeilisearchManager → tools index + knowledges index
                                         ↑
                              从 Registry 加载所有资源
```

功能状态：

| 功能 | 状态 |
|------|------|
| 启动/停止服务、自动端口分配 | ✅ |
| 索引 tools / knowledges | ✅ |
| 搜索、Typo 容错、过滤器 | ✅ |
| 退出自动清理 | ✅ |
| Agent 搜索工具 | ⚠️ manager 已注入，缺搜索 tool |
| 增量索引 | ❌ 每次全量重建 |

### 待办事项

| 优先级 | 任务 | 所属 |
|--------|------|------|
| P0 | Agent Meilisearch 搜索工具 | 搜索 |
| P0 | SWE-bench 批量评估（跑全部 500 条） | 评估 |
| P1 | Docker 评估环境 | 评估 |
| P1 | 增量 Meilisearch 索引 | 搜索 |
| P1 | 评估指标看板（pass@k、通过率、耗时分布） | 评估 |
| P2 | 多模型对比评估 | 评估 |
| P2 | 搜索 ranking 优化 | 搜索 |
| P3 | 评估回归检测 | 评估 |

---

## 附录 A: 仓库文件归属

```
egoagent/
├── agent.py                  # [算法] Agent 核心类
├── environment.py            # [算法] 工具/知识加载器
├── config.py / config.yaml   # [算法] 全局配置
├── utils.py                  # [算法] 动态脚本加载
├── llm/                      # [算法] LLM 后端
├── identity/                 # [算法] Identity 定义
├── playground_malkuth/       # [算法] 主 playground 环境
├── playground/               # [算法] playground 环境
├── playground2/              # [算法] playground2 环境
├── .egoagent_registry.json   # [算法] 全局注册表
│
├── harness.py                # [Harness] Harness/Session 核心类
├── harness/                  # [Harness] Harness 模板
├── run_harness.py            # [Harness] 主启动脚本
├── examples.sh               # [Harness] 启动命令示例
├── sessions/                 # [Harness] 会话记录
│
├── swebench_eval/            # [评估] SWE-bench 评估
├── meilisearch_manager/      # [评估] Meilisearch 管理器
├── meilisearch/              # [评估] Meilisearch 源码
├── scripts/                  # [评估] 辅助脚本
│
└── design.txt                # 设计文档
```

## 附录 B: 依赖关系与开发顺序

```
算法引擎 ──→ Harness 编排 ──→ 评估系统
 (地基)      (协作层)        (验证层)
```

建议开发顺序：算法引擎 → Harness 编排 → 评估系统。每个区块内部按 P0 → P1 → P2 → P3 推进。
