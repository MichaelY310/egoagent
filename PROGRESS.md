# EgoAgent · Development Log

This is the maintained development log. New entries are added above the
historical notes; validation applies only to the explicitly recorded scope.
For installation, see [README](README.md). For source ownership, see
[Repository Guide](docs/REPOSITORY_GUIDE.md).

## 2026-11-23 · 功能成熟度独立审查（非发布认证）

- 按当前工作树完成七大板块的功能盘点、关键源码/测试交叉检查与成熟度分级；
  报告见 [功能地图与成熟度审查](docs/FEATURE_MATURITY_AUDIT_20261123_ZH.md)，
  结构化结果见 [验证摘要](docs/FEATURE_MATURITY_VERIFICATION_20261123.json)。
- 无真实凭据的隔离源码副本最终回归：**888 passed、3 skipped、258 subtests passed**；
  Node **126 passed**；TypeScript/Vite 构建通过（247 modules，复用现有依赖）；
  **135/135** Flow 结构/依赖检查通过；独立 Workbench 首页、6 静态资源、5 个只读 API
  在临时 loopback HTTP 服务中通过。没有调用收费模型、重做完整 IDE E2E 或全新安装。
- 保留首次失败记录：2 项 export 失败源于审查副本无独立 Git 索引，纠正后通过；
  3 项审阅日志 `os.replace` 在 Windows 出现 `WinError 5`，定向 28 项及随后完整复测通过，
  偶发失败根因尚未确定。3 个跳过项是两项 symlink 权限测试及未配置镜像的真实容器测试。
- 假数据/临时目录受控复现确认：Parallel 父策略上下文继承丢失、Knowledge env 授权缺口、
  Anthropic 显式密钥被环境密钥覆盖、Windows 更新包盘符路径逃逸、required-signature
  接受未验证签名、通用 timeout 后仍可执行副作用、诊断 prompt 排除设置未生效。
  同时识别 Legacy/V2 Evolution 的评价对象与证据门控缺口等静态问题，详见报告。
- 结论仍为**可信本地开发者预览版**；不能据测试通过宣称强隔离、任意节点无损热替换、
  普遍自进化收益或稳定公开发行。上述问题**尚未修复**；本轮未修改业务代码、未提交或推送 Git。

## 2026-11-23 · 源码分层与近期产品更新归档

本次整理从上次发布提交 `de0252a` 起积累的改动，继续定位为开发者预览版。
日期是整理/发布日期，不代表下面所有功能都在同一天编写或重新实机验收。

### 1. 核心、服务器和前端分离

- `egoagent_core/` 收拢模型路由、上下文、项目规则、改动审阅、检查点、
  工作区后台任务、Agent 创建与工具库等服务；`agent.py`、Flow 引擎、
  `llm/`、Task/进化模块仍属于无界面运行时。
- `egoagent_server/` 承担 HTTP/SSE/WebSocket 接口。`harness_editor/src/`
  保留 React 前端；旧 Python 导入路径以兼容别名转发到同一实现，避免
  两份代码或两套全局状态。
- 增加 `python -m egoagent_core` 和 `python -m egoagent_server` 入口、
  `requirements-core.txt`、源码导出与禁用前端导入的验收脚本；新增
  Windows/Linux GitHub Actions 核心边界检查与独立前端测试/构建任务。
- 这还是源码分发，不是独立 Python wheel。可删除 UI 后保留核心，但不能
  只复制 `egoagent_core/` 而遗漏根目录运行时和 Flow/Identity 资源。
  用法见 [纯核心指南](docs/HEADLESS_CORE_ZH.md)。

### 2. Flow 配置与 24 阶段 Cookbook

- Chat 仅选择 Harness 和 Flow 版本；角色 Identity、运行策略等保存进
  Build 中的版本配置，Chat 与独立试跑使用同一配置来源。
- 新增 `cookbook_01_react` 至 `cookbook_24_adaptive_team`，从 ReAct、
  自定义工具、Identity/审批递进到子 Flow、能力发现、上下文精简/压缩、
  Session 恢复、durable、结构化输出、规划、委派/并行团队、评估改进、
  澄清、记忆、网络研究、预算和 Flow 创建/改进。
- 配套角色、确定性计算工具、三个内部子 Flow 与简短的界面说明一起发布。
  示例覆盖机制，不承诺每次模型调用都自发进化或带来收益。
- Identity 显式 URL/model 优先，只有空字段继承全局配置；密钥按服务来源
  解析，避免自定义端点被悄悄替换或收到其他服务的全局凭证。

### 3. 工具与 Skills 的可发现、可编辑入口

- Workbench 主导航新增「工具与 Skills」，可搜索、分类、分页查看源码来源、
  工具参数和说明；同名但不同来源的工具保留区分。
- 在 IDE 中编辑会打开实际 Python / `SKILL.md` 文件；源码索引采用静态解析，
  浏览目录不会导入并执行工具代码。
- Identity 编辑器复用同一能力目录，可选择启动时加载的工具；空选择和继承
  默认行为明确区分，保存带并发修改检测。
- 选择结果在新建/重载 Identity 时应用，不热改运行中的 Agent；它是能力
  组合，不代替权限审批，也不是禁止动态发现其他能力的安全边界。

### 4. 启动、连接与界面稳定性

- Windows 浏览器启动器与 `desktop/install-browser.ps1`：快捷方式复用或启动
  后台，等待服务就绪后打开默认浏览器，不打开桌面版壳窗口。
- Workbench 保存页面恢复状态；修复 Identity 缺省数组渲染、工作区上下文
  获取和源文件跳转桥接；Build 的组件/配置默认展开并修正边栏裁切。
- Harness 目录请求增加超时、明确错误、立即重试、退避重连，先加载名称，
  描述失败不阻断选择器；刷新保留仍有效的选项与版本。
- WebSocket 使用启动器实际分配的端口，不再假设是 API 端口加一；同步
  扩展脚本版本与 Workbench 构建产物。

### 5. 仓库与实验资料整理

- 更新 README、分层/贡献指南，保留原发布检查和实验协议，不抹掉历史。
- 实验源码、分析测试和阶段说明与产品代码分目录；实验报告的旧结果不是
  本轮复测结论，也不能据此宣称科研方法已被证实。
- 本轮新增的 `.runtime-logs/`、原始实验结果、会话/轨迹、Flow 版本缓存、
  连接令牌、模型密钥与实验生成的业务专用 Skills 留在本机，未删除、
  不上传。此前已发布的研究摘要保持原状，不重写 Git 历史。
- 移出版本控制的旧 `meilisearch/` 上游源码（1,738 个文件）仍完整保留
  在本机；当前能力搜索使用本地目录服务，不依赖这个 Rust 源码副本。
- `void_extension/.../workbench/` 是随扩展分发的生成文件；修改其 React
  源码后通过 `npm --prefix harness_editor run package:extension` 重新生成，
  不手工维护重复 UI。

### 发布验证

本节在发布前以实际回归结果补全。自动化测试、真实浏览器验收、模型实跑
和外部环境验收分别记录，不将一种检查等同于另一种。

### 仍需继续的工作

- 完整 Void Web 运行时没有已验证的一键安装/分发流程；仅克隆仓库不等于
  获得可直接运行的完整 IDE。
- 任意节点无损热替换、通用自进化收益、多平台桌面发行和大规模训练兼容
  仍有限制；Workspace Guard 不是强操作系统沙箱。
- 外部模型、SSH/WSL、Docker/GPU 和长程任务需在对应环境独立验证。

## 2026-09-30 · 上次发布检查

完整检查记录见 [开发状态与发布检查](docs/DEVELOPMENT_STATUS_20260930.md)，
对应 `de0252a`。其中测试数量和功能状态属于该次发布，不是当前自动累计值。

## Early V2 prototype · Historical snapshot

以下保留最早的开发记录。旧端口、模型、18 个模板数量及待办清单仅表示
当时状态；当前入口和分层以 README、ARCHITECTURE 及上面的新日志为准。

## Overview

EgoAgent V2 is a self-evolving DAG-based Agent system with a browser-accessible IDE interface. It combines a Void Editor (VSCode fork) with a custom EgoAgent panel for managing identities, harnesses, DAG pipelines, knowledge bases, and self-evolution capabilities.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Browser (localhost:8880)                            │
│  ┌─────────────────┬───────────────────────────┐    │
│  │  Void Editor    │  EgoAgent Panel            │    │
│  │  (Code IDE)     │  Chat / Identity / Env /   │    │
│  │                 │  Sessions / Evolve / DAG / │    │
│  │                 │  KB / CP / Rules / Mem /   │    │
│  │                 │  Models / Exp              │    │
│  └─────────────────┴───────────────────────────┘    │
└─────────────────────────────────────────────────────┘
         │                        │
         ▼                        ▼
┌─────────────────┐    ┌─────────────────────┐
│  Void Web       │    │  EgoAgent Backend   │
│  (port 8869)    │    │  (port 8765)        │
└─────────────────┘    └─────────────────────┘
         │                        │
         └────────┬───────────────┘
                  ▼
       ┌─────────────────────┐
       │  Proxy (port 8880)  │
       │  start-all.py       │
       │  HTTP + WebSocket   │
       └─────────────────────┘
                  │
                  ▼
       ┌─────────────────────┐
       │  vLLM Model Service │
       │  Qwen3-8B-yangyuan  │
       └─────────────────────┘
```

## Core Components

### 1. Agent Core (`agent.py`)
- LLM streaming with think-tag filtering (Qwen3 `<think>...</think>`)
- Tool call parsing (XML format with fallback)
- Session auto-recording
- Multi-identity support

### 2. Pipeline Engine (`pipeline_engine.py`)
- DAG-based execution flow
- Conditional edge routing (has_tool_calls / has_text / default)
- Multi-agent orchestration (e.g., creative_roundtable: 4-node brainstorm→critique→refine→evaluate)

### 3. Harness System (`harness/`)
- `react_single` - Standard ReAct loop
- `creative_roundtable` - Multi-agent brainstorm with creator + critic
- `coder_react` - Coding-focused ReAct (30 steps, 10 tools)
- `debate_with_moderator` - Debate format
- `evolution_cycle` / `meta_evolution_cycle` - Self-evolution pipelines
- `guarded_react` / `dual_guardian` - Safety-aware agents
- And more (18 harnesses total)

### 4. Self-Evolution (`self_evolution/`)
- Evolver/Solver separated architecture
- Structural self-evolution (modify DAG pipelines)
- Principles-based evolution
- Experiment tracking and evaluation

### 5. Harness Editor (`harness_editor/`)
- **Backend** (`server.py`): FastAPI-style HTTP server with SSE streaming
  - `/v1/chat/completions` - OpenAI-compatible chat endpoint with DAG routing
  - `/api/harnesses` - List/get harness configs
  - `/api/identities` - CRUD for agent identities
  - `/api/sessions` - Session management
  - `/api/checkpoints` - Checkpoint save/restore
  - `/api/rules` - Project rules management
  - `/api/models` - Model registry
  - `/api/knowledge` - Knowledge base per identity
  - `/api/evolve` - Evolution trigger and history
  - `/api/experiments` - Experiment management
- **Frontend** (`src/`): React + TypeScript + Vite
  - DAG visual editor (React Flow)
  - Evolution panel with history/compare
  - Full CRUD panels for all entities

### 6. IDE Integration (`start-all.py`)
- Single-port reverse proxy (8880) combining Void + EgoAgent
- WebSocket tunnel for editor connectivity
- Script injection (panel.js, p1.js, p2.js, editor.js)
- SSE streaming passthrough

## Current Status

### Completed ✅
- [x] Agent core with streaming, think-tag filter, tool execution
- [x] Pipeline engine with DAG traversal and conditional edges
- [x] 18 harness configurations
- [x] Multi-agent streaming protocol (`[AGENT_START:name]` / `[AGENT_END]`)
- [x] Void Editor integration with single-port proxy
- [x] WebSocket tunnel for editor connectivity
- [x] Identity CRUD (list/detail/edit/clone/delete)
- [x] Environment management (tools/knowledge assignment)
- [x] Session history (list/view/restore/delete)
- [x] Evolution panel (new run/history/compare/principles)
- [x] DAG visual editor (load harness, display nodes/edges)
- [x] Knowledge Base panel
- [x] Checkpoints panel (save/restore/clear)
- [x] Rules panel (add/edit/delete)
- [x] Memory panel (list/search)
- [x] Models panel (list/add/remove)
- [x] Experiments panel (list/create/detail/stats)
- [x] `_on_token` callback simplified (removed redundant think-tag filter)
- [x] BrokenPipe error handling
- [x] Script injection for all 4 frontend JS files
- [x] Tab switching with proper UI state management

### Known Issues / In Progress ⚠️
- [ ] Creative roundtable shows only 2 of 4 expected agent turns (needs verification after _on_token fix)
- [ ] Streaming appears non-incremental in some cases (full bubble appears at once)
- [ ] DAG panel may show blank after harness selection (error handling added, needs testing)
- [ ] Some panel backend endpoints return mock/placeholder data
- [ ] Evolve panel user-facing features (multi-session harness evolution) partially implemented

### Not Started / Future 🔮
- [ ] Exp panel: research-oriented evolution with dataset evaluation
- [ ] Full streaming verification for multi-agent DAG
- [ ] Production-grade error recovery
- [ ] Mobile-responsive UI

## File Structure (Key Files)

```
egoagent/
├── agent.py                    # Core agent class
├── pipeline_engine.py          # DAG execution engine
├── harness.py                  # Harness loader/manager
├── environment.py              # Tool/environment management
├── config.py / config.yaml     # Global configuration
├── start-all.py                # Single-port proxy server
├── harness/                    # 18 harness configurations
│   ├── react_single/config.json
│   ├── creative_roundtable/config.json
│   └── ...
├── harness_editor/             # Web-based editor
│   ├── server.py               # Backend API
│   ├── src/                    # React frontend source
│   └── dist/                   # Built frontend
├── identity/                   # Agent identities
│   ├── dante/                  # Default coding agent
│   ├── creative_brain/         # Creative agent
│   ├── sharp_critic/           # Critic agent
│   └── ...
├── self_evolution/             # Evolution engine
│   ├── engine.py
│   └── data/
├── experiments/                # Experiment tracking
└── scripts/                    # Utility scripts
```

## Running

```bash
# Start all services (proxy on 8880)
python start-all.py

# Or start individually:
# Backend API
cd harness_editor && python server.py  # port 8765

# Void Editor (requires void-server binary)
void-server --port 8869

# Access in browser
open http://localhost:8880
```

## Model Configuration

Default LLM: `Qwen3-8B-yangyuan` via vLLM
- Endpoint: configurable per identity in `id.json`
- Supports streaming with think-tag filtering
- Temperature/max_tokens configurable per identity
