# EgoAgent Code Agent 产品验收与对照实验

这组实验验证的不是“功能是否出现在配置文件里”，而是 DeepSeek V4 Flash 是否真的经过对应节点、调用对应能力、留下可回放轨迹，并通过独立的文件/命令/JSON 检查。已有结果是单次工程验收，不应被描述成统计显著性结论。

## 一键检查已有证据

下面两个命令不调用模型，也不消耗 API：

```powershell
.\.venv\Scripts\python.exe experiments\product_code_agent_acceptance\summarize_campaign.py
.\.venv\Scripts\python.exe experiments\product_code_agent_acceptance\validate_campaign.py
```

预期第二个命令退出码为 `0`，并在 `results/PROOF_REPORT_20260904.md` 显示 `11/11 proof checks passed`。机器检查直接读取原始 report、lossless trajectory 和 JUnit，不相信 Agent 的自我宣称。

## 推荐的五组演示

### 1. 小任务：Core 与 Full 的产品路由边界

```powershell
.\.venv\Scripts\python.exe experiments\product_code_agent_acceptance\run_matrix.py `
  --tasks product_parallel_diagnostics `
  --flows product_core_code_agent product_adaptive_code_agent `
  --identity adaptive_deepseek_coder `
  --label demo_small_router
```

两者都应通过 5 个检查。已有配对结果中 Core 为 60,937 tokens / 36.0s，Full 为 70,021 tokens / 72.5s。结论是小型一次性修复应走 Core，不是“节点越多越好”。

### 2. 超长工具输出：只裁模型上下文，不损失训练轨迹

```powershell
.\.venv\Scripts\python.exe experiments\product_code_agent_acceptance\run_matrix.py `
  --tasks product_large_observation_repair `
  --flows product_adaptive_tool_pruning_off product_adaptive_tool_pruning_on `
  --identity adaptive_deepseek_coder `
  --label demo_tool_pruning
```

两组都应修复同一约 50 KB 文件并通过。已有结果为 315,740 对 109,133 tokens（`-65.4%`）；开启组的原始 `read_file` 仍完整保留在 `trajectory.jsonl`，模型工作上下文只保留带哈希的头尾摘要。

### 3. 被动压缩与主动精简不是同一功能

```powershell
.\.venv\Scripts\python.exe experiments\product_code_agent_acceptance\run_matrix.py `
  --tasks product_context_endurance_ledger `
  --flows product_context_endurance_ungoverned product_context_endurance_compaction_only `
  --identity adaptive_deepseek_coder `
  --label demo_passive_compaction
```

压缩只在声明的 token 高水位越线时触发；要在轨迹里看到 `conversation_applied` 的 `mode=block_plan`。已有干净结果保持 25/25 正确，总 token 从 80,657 降到 58,999。频繁 proactive curation 是负面对照：它同样正确，但破坏前缀缓存并增加成本，因此生产 Flow 设有 `curation_minimum_tokens` 门槛。

### 4. 持久记忆的 A/B

```powershell
.\.venv\Scripts\python.exe experiments\product_code_agent_acceptance\run_matrix.py `
  --tasks product_cross_session_memory `
  --flows product_adaptive_no_memory product_adaptive_code_agent `
  --identity adaptive_deepseek_coder `
  --label demo_memory_ab
```

第一步给出随机事实且禁止写入项目文件，第二步创建全新 Session。无记忆对照预期只能完成 1/2；开启组通过 `recall` 从 workspace memory 找回事实并完成 2/2。

### 5. 受治理进化与 fresh-session 复用

先使用 `product_recurring_quasar_release`（七轮相同契约、不同输入）分别跑 control 与 evolver，再用 `product_quasar_release_transfer` 验证新 Session 复用。已固化的主证据位于：

- `results/20260904_062148_quasar_learning_control_r1/report.json`
- `results/20260904_062444_quasar_learning_evolver_r1/report.json`
- `results/20260904_063733_quasar_transfer_control_r1/report.json`
- `results/20260904_065355_quasar_transfer_direct_reuse_r3/report.json`

学习阶段两组都是 7/7，但进化组主动付出更高成本，创建 `normalize_quasar_release_v3`，第一次验证失败后修复、通过、同 Session 热加载。随后 fresh-session transfer 两组都是 3/3，复用组真实调用 Skill 三次，总 token `-21.9%`、工具调用 `-78.6%`。这才是自进化的完整价值链：发现重复压力 → 产生候选 → 独立验证/修复 → 发布 → 同轮加载 → 新 Session 搜索与复用。

## 在前端查看

1. 打开 IDE 右上角 `Open Agent Workbench`。
2. 左侧进入 `Evaluate / Task Bench`。
3. 在题目库选择上述 Task；选择 Flow、精确 Flow version 和 Identity。
4. 点 `开始做题`。左侧 Flow 图显示当前节点，右侧 `过程` 显示每个 node/model/tool 的输入输出。
5. 结束后查看：
   - `评分`：确定性检查，而不是模型自评；
   - `产物`：点击文件名在 IDE 中打开隔离 workspace；
   - `进化`：真实 Flow/Identity/Skill mutation；
   - 最近运行勾选两项后点 `比较所选轨迹`：并排对齐首次分歧；
   - 有安全 completed checkpoint 的中断运行会显示 `↻`，点击后在新的克隆 workspace 恢复，原运行不被改写；
   - 点 `在 Build 回放`：用固定 Flow 版本重放节点轨迹。

## 数据位置和安全边界

- Task 的隔离 workspace 与 `run.json`：`.egoagent/task_runs/<run_id>/`。
- 每个 step 的 lossless 轨迹：`.egoagent/task_runs/<run_id>/session/<step>/trajectory.jsonl`。
- 紧凑实验报告：本目录的 `results/<timestamp>_<label>/report.json`。
- 总汇总：`results/CAMPAIGN_REPORT_20260904.md`。
- 机器证明：`results/PROOF_REPORT_20260904.json`。
- 恢复/循环故障注入：`results/RESILIENCE_JUNIT_20260904.xml`。
- 全仓库回归：`results/FULL_SUITE_JUNIT_20260904.xml`。

凭据只从被 Git 忽略的本地环境文件加载；脚本只打印变量名，不读取或写入报告。恢复只能复制 `.egoagent/task_runs/<source>/workspace`，in-flight 副作用不会被一键重放。

## 最终工程回归

最终宿主环境回归为 `688 passed, 3 skipped, 164 subtests passed`；Workbench 生产构建为 239 个模块，扩展打包已同步到 `void_extension/egoagent-dag-chat/workbench` 与当前 Void 扩展。浏览器端到端用例覆盖导航、结构化观察、表单输入、元素与坐标点击、对话框、下载、截图、标签页和清理。

浏览器驱动已改用 Chromium 当前推荐的 browser-level CDP WebSocket + flattened Target session，并让 Chromium 通过 `DevToolsActivePort` 原子分配调试端口。受限命令沙箱会阻止 Windows Chromium GPU 子进程并造成假失败；产品正常宿主进程不会关闭 Chromium 自身的安全沙箱，宿主回归已通过。

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider `
  --basetemp=tmp\pytest-product-proof `
  --junitxml=experiments\product_code_agent_acceptance\results\FULL_SUITE_JUNIT_20260904.xml
cd harness_editor
npm run package:extension
```

## 结果应如何解释

- Full Flow 的主要价值是长程可靠性、复用、审计和隔离，不保证每个单次任务更便宜。
- 子 Agent 在当前大任务 A/B 中隔离了不相交 package，但总 token 增加 29%；它是上下文隔离机制，不是通用省钱开关。
- 被动压缩降低了本组总 token，但未缓存输入受供应商 prefix cache 方差影响，不能保证每次下降。
- 正常 v24 真实任务没有误触重复提醒；故障注入证明同一只读调用连续 3 次时，DeepSeek 风格 Flow 会把可见提醒送入模型上下文。
- 若要报告胜率或平均成本，需要固定温度、预注册 Task/Flow 版本并进行多 seed 重复；本 campaign 只支撑产品能力和工程边界判断。
