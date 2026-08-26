# Open-source Harness replication program

Source inventory: `open-source-agent-harness.html.pdf`, reviewed on 2026-08-09.
The PDF contains 15 candidates. Every candidate was retained: none is merely a
single skill. Official repositories are pinned below and stored in the ignored
`research/upstream/` directory. The clones are research inputs only; upstream
code is not copied into EgoAgent.

## Pinned source revisions

| Project | Official repository | Revision | Disposition |
| --- | --- | --- | --- |
| OpenHands | All-Hands-AI/OpenHands | `4470813ce58f` | Current Agent Canvas/UI boundary |
| OpenHands SDK | All-Hands-AI/software-agent-sdk | `c7e270aae43a` | Actual current loop, tools, events and goal runner used for the reproduction |
| Aider | Aider-AI/aider | `5dc9490bb35f` | Coding Harness |
| SWE-agent | SWE-agent/SWE-agent | `3ea751c087f3` | Coding Harness + Agent-computer interface |
| Continue | continuedev/continue | `5522c6f44ca0` | IDE/CLI product; Agent and plan-mode cores reproduced |
| AI Scientist | SakanaAI/AI-Scientist | `1de1dbc1f4ee` | Multi-stage scientific Harness |
| GPT Researcher | assafelovic/gpt-researcher | `5d84d2f5553e` | Research Harness |
| Open Deep Research | langchain-ai/open_deep_research | `20aaa0d422bd` | Hierarchical research Harness |
| Voyager | MineDojo/Voyager | `55e45a880755` | Lifelong-learning environment Harness |
| Generative Agents | joonspk-research/generative_agents | `fe05a71d3e4e` | Simulation Harness with cognitive memory |
| MetaGPT | geekan/MetaGPT | `11cdf466d042` | Role/SOP multi-Agent Harness |
| Browser Use | browser-use/browser-use | `32601887cfbc` | Browser Agent Harness |
| Stagehand | browserbase/stagehand | `7566804ed4b9` | Browser SDK plus Agent Harness |
| OpenManus | FoundationAgents/OpenManus | `52a13f2a57d8` | ReAct, ToolCall and planning Harnesses |
| AutoGPT | Significant-Gravitas/AutoGPT | `ce6ab7b074a6` | Persisted block-graph Agent platform |
| Devika | stitionai/devika | `80bb343cbe4a` | Multi-stage software-engineer Harness |

## Source findings and DAG reproductions

| Project | Harness behavior confirmed from source | EgoAgent reproduction |
| --- | --- | --- |
| OpenHands | Typed responses distinguish content, tool calls, reasoning-only and empty replies. Pending confirmed actions execute before a new model call; malformed or empty replies receive environment feedback. Tool calls are serial by default but can be concurrent, their observations retain request order, and `Finish` truncates later calls in the batch and ends the inner loop. Repeating the same failing action gets a soft nudge on the third failure and hard-stops on the fourth; action/observation, monologue and alternating cycles have separate thresholds. `/goal` is an outer independent judge loop with ten attempts and strict `{score, complete, missing}` output; invalid judge output conservatively means incomplete rather than triggering a hidden retry. | `openhands_replica`: compacted context, policy review, ordered tool trajectory, third-error nudge/fourth-error stop, terminal-tool batch truncation and direct outer-judge routing, checkpoints, ten bounded attempts, conservative judge parsing and a no-extra-model-call budget finalizer. `identity/openhands` composes coding and research EGO capabilities while withholding inner `submit_result` authority. |
| Aider | `Coder.run_one` repeats `send_message` while `reflected_message` is set, capped by `max_reflections=3`. EditBlockCoder extracts filename-scoped SEARCH/REPLACE blocks and shell fences, accepts empty SEARCH for create/append, tries exact/consistent-leading-whitespace/paired-ellipsis matching, retains successfully applied blocks when others fail and tells the model not to resend them. Default `auto_lint=true`, `auto_test=false`; lint/test failures ask before another reflection. Suggested shell commands require explicit approval. Architect mode produces a plan, optionally asks before invoking a fresh editor coder (`auto_accept_architect` defaults true), then records that changes were made. | `aider_replica` + `aider_review_worker`: source-shaped architect/editor separation with configurable auto-accept, deterministic native edit-block parser, Workspace-confined recoverable partial application plus optional all-or-nothing mode, similar-line failure feedback, three bounded format/apply/lint reflections, default lint/test flags, explicit repair and shell approvals, safe budget finalization, and the same per-hunk green/red review transaction used by Void. No Python node or model-generated edit tool call is required. |
| SWE-agent | `DefaultAgent.run` repeatedly calls `step` until done. The thought/action parser selects the final complete top-level fenced block; everything outside is thought. `forward_with_handling` re-queries format/blocked/shell-syntax errors up to `max_requeries=3`, then autosubmits a typed exit status. Each valid turn executes one ACI action and appends the templated observation. `LastNObservations` retains the instance observation and latest observations while replacing older output with line-count markers. Explicit submit/exit and cost/context/environment failures are stop conditions. | `swe_agent_replica`: native one-action parser (no Python), exactly-one-action enforcement, bounded three-turn format correction with `exit_format`, environment errors fed back as observations, source-shaped trajectory fields, first/recent observation history processing, per-action checkpoints, explicit submission/exit, and a safe no-more-model-calls `exit_budget` finalizer. Tool-side submission can still pass through the shared per-hunk edit review. |
| Continue | `streamChatResponse` recomputes the mode-specific system message and visible tools each iteration, streams one response, executes approved tool calls and loops while calls exist; no-call text stops. Tool-argument/preprocessing failures and execution errors become tool results. Permissions are checked in order; approved calls execute concurrently. Normal mode asks for writes/Bash, headless rejects unresolved asks, plan mode absolutely excludes Write/Edit/MultiEdit before the request but deliberately allows Bash and other non-write/MCP tools, and auto mode allows all. Input is validated before the API; pre-call, post-tool-overflow and threshold compaction can replace active history with a summary. If compaction occurred in a would-stop turn, one `continue` message resumes the loop. | `continue_agent_replica` and `continue_plan_replica`: provider-time tool filtering plus execution-time policy defense, first-match Continue policy order, concurrent approved tools with ordered trajectory, error observations fed into the next model turn, thresholded persistent compaction, one bounded post-compaction continuation, per-tool checkpoints and typed no-extra-model-call budget finalization. Plan hides write/patch/multi-edit definitions and blocks injected writes while retaining `run_command`, matching the pinned source's explicit Bash exception. |
| AI Scientist | `generate_ideas` creates one idea at a time against `experiment.py`, seed ideas and the prior archive; the launched path uses three total reflection rounds and an `I am done` early stop. Novelty is a sequential decision-or-query loop for at most ten rounds and defaults to not novel without an explicit decision. Each novel idea gets an isolated copy of the template and run-0 baseline. A coder incrementally drives at most five successful runs; the same run gets at most four failed implementation attempts, followed by up to four plotting attempts and a final notes update. Writeup performs a bounded twenty-round citation loop. Review samples five independent reviews, asks for a meta-review, deterministically replaces nine numeric fields with rounded valid-review means, reflects for up to five total rounds, and optionally improves only the paper before a complete second review. | `ai_scientist_replica`, `ai_scientist_novelty_worker`, `ai_scientist_experiment_run_worker` and `ai_scientist_idea_worker`: per-idea three-round generation, template/baseline reads, sequential ten-round conservative novelty, isolated template copies, five-run/four-repair execution with typed process evidence, plot/notes stages, twenty-round evidence-only citation integration, a real tracked `paper.md`, five-review ensemble, deterministic source-shaped score overlay, early/constrained review reflection and optional paper-only improvement/re-review. The default graph generates three new ideas for practical API cost, while `generation_slots` is configurable up to the upstream CLI's larger batch. |
| GPT Researcher | Standard research selects a dynamic agent/role, performs an actual initial search before planning up to the configured sub-queries, appends the original query outside subtopic mode, processes those branches concurrently, deduplicates visited URLs, optionally curates the best sources and abstains when no context exists. Deep mode first generates search-informed follow-up questions with automatic answers, then defaults to breadth 4/depth 2/concurrency 2. Each query has an explicit research goal, launches a full standard researcher, extracts cited learnings and follow-ups, and recursively narrows breadth with `max(2, breadth//2)`; all-branch failure stops descent and final context is capped at 25k words. | `gpt_researcher_replica` + `gpt_researcher_query_worker` reproduce the seed-search-before-plan standard path, dynamic role, original-query coverage, bounded parallel search/scrape loops, curation, cited synthesis and abstention. `gpt_researcher_deep_replica`, `gpt_researcher_deep_worker` and `gpt_researcher_deep_query_worker` reproduce the web-informed automatic plan, typed query goals/learnings/citations, configurable recursive breadth/depth, two-worker concurrency, failure-safe empty result and native 25k-word context cap. No Python node is used. |
| Open Deep Research | Clarification and research-brief generation are separate structured calls. A lead supervisor repeatedly calls conceptual `think_tool`, `ConductResearch` and `ResearchComplete` operations; configured default is six research iterations, while the pinned `>` guard permits a seventh model decision whose delegations are not executed. At most five research calls execute concurrently and overflow calls become explicit error observations. Every researcher performs up to ten parallel-tool ReAct rounds, then a separate compression model preserves raw evidence. No-tool/no-call, explicit completion and limits terminate their respective loops. Final report generation retries token overflow up to three times after the first attempt with progressive findings truncation. | `open_deep_research_replica` + `open_deep_research_worker`: separate clarification/brief calls, source-shaped adaptive seven-decision/six-execution supervisor, explicit reflection history, five-unit concurrency guard with overflow evidence, repeated Map reductions, ten-round parallel-tool workers, three-attempt evidence compression, raw-note retention, and four-attempt progressively trimmed final synthesis. Invalid structured supervisor output stops conservatively and no findings produces an explicit abstention. |
| Voyager | The pinned learner defaults to 160 curriculum iterations and hard-codes `Mine 1 wood log` as its first automatic task. It retrieves the top five executable skills, gives each task four action attempts, parses action programs with three corrections and critic/curriculum decisions with five corrections. Success stores an executable program under a stable program name; failure and completion update persistent progress, deduplicate completed tasks and remove them from failed tasks. | `voyager_replica` + `voyager_action_worker`: source-shaped first task, configurable 160-slot curriculum, top-five recall, four rollouts, strict critic, five-attempt structured decisions, persistent cleaned progress, and a separate skill manager. Successful tool trajectories—not merely prose summaries—are upserted as reusable skills under a stable ID. Minecraft soft/hard reset and exact JavaScript AST execution remain an environment adapter boundary. |
| Generative Agents | A tick is ordered `perceive → retrieve → plan → reflect → execute`. Perception has vision radius 4, attention bandwidth 3 and skips event triples seen in the last five retained events. Retrieval combines recency/relevance/importance; reflection fires after accumulated poignancy reaches 150, derives three focal points, retrieves up to 30 memories per focus and writes five evidence-linked insights per focus before resetting the trigger. Planning maintains a daily schedule/current action; execution maps an address to one path step. | `generative_agent_replica` + `generative_reflection_worker`: at most three typed events, recent-five event-key dedupe, 0.5/3/2 scored recall, persistent daily/current-action scratch, the correct plan-before-reflect order, threshold 150, three sequential focal searches, up to fifteen evidence-linked thought memories, reflection reset and a typed environment-ready action. Stanford Town arena visibility and actual path movement remain an external world adapter. |
| MetaGPT | Base roles observe subscribed messages, remember unseen news, then run react/by-order/plan-and-act and publish addressed results; an Environment concurrently runs every non-idle role each company round. The pinned default CLI now hires TeamLeader, ProductManager, Architect, Engineer2 and DataAnalyst in MGX, invests $3, runs up to five rounds, and uses adaptive RoleZero tool loops (TeamLeader 3, Engineer2 40, general roles 50). Classic fixed SOP roles still implement PRD → design → tasks → code/summarize → QA, with QA allowed five test/debug rounds. | `metagpt_mgx_replica` + `metagpt_rolezero_worker` reproduce current intent routing, TeamLeader dependency-aware delegation, five company rounds, $3 cost ceiling, durable addressed/acknowledged reports, native Identity/EGO tools, source-shaped per-role reaction limits, exclusive edit calls, sequential stop-on-error batches, terminal commands and human continuation at the limit. `metagpt_software_company_replica` remains the explicit classic fixed-SOP path with typed artifacts and QA repair. |
| Browser Use | Maintains browser state/history, prompts a grounded action list, executes actions, interrupts the remaining list after navigation/state change, records observations, detects repeated failure and validates the final outcome. | `browser_use_replica`: typed page/viewport/element/dialog/download observations, real CDP mouse/keyboard actions, screenshot evidence, stale-batch interruption, stuck recovery, CAPTCHA human approval and independent final evidence judge. |
| Stagehand | Agent mode defaults to DOM; DOM and hybrid loops default to 20 steps, while CUA clients default to 10. DOM excludes coordinate tools and hybrid adjusts the tool set. If the loop reaches its limit without `done`, Stagehand forces a structured final answer. Per-step and post-step evidence are retained. Agent cache keys include mode/instruction/variables/excluded tools, replays one deterministic action at a time and repairs changed selectors when replay fails. | `stagehand_replica`: source-default mode/caps, mode-specific protocols, typed forced `done`, persistent deterministic action replay with self-healing repair, atomic DOM/coordinate actions, dialog/download/human evidence and independent fused verification. |
| OpenManus | `BaseAgent` owns IDLE/RUNNING/FINISHED state and defaults to ten steps. ToolCallAgent defaults to 30, executes all model tool calls sequentially, records errors as observations and requires a special terminate tool; Manus overrides to 20 steps and 10,000-character observations, adds Python/browser/editor/AskHuman/Terminate/MCP tools and injects browser context when BrowserUse appeared in the recent three messages. PlanningFlow creates typed statuses, falls back to Analyze/Execute/Verify, selects an executor (including `[AGENT]`) and summarizes. | `openmanus_replica`: exact 20-step explicit-termination loop, sequential tools, bounded observations, browser-change interruption, AskHuman and typed Terminate EGO skills, checkpoints/stuck recovery and structured outcome. `openmanus_planning_replica` adds typed plan fallback, executor-selected subflows, completed/blocked status and resumable per-step checkpoints. Identity/EGO composition remains intact. |
| AutoGPT | The current platform is a persisted port-level block DAG. Every block has typed Pydantic input/output schemas and may yield multiple named outputs. A downstream execution is queued only when required inputs have accumulated; static links can reuse the latest value while dynamic output events form new executions. The manager runs ready nodes concurrently, persists every output, enqueues matching ports, supports cancellation/resume, per-block wall-clock limits and credentials. Human-in-the-loop is a block-level editable approve/reject data split, not a single whole-graph gate. | `autogpt_platform_replica`: the planner now emits explicit typed blocks and named links, not dependency waves. The existing Subflow component runs them through an internal persisted port-event scheduler: repeated/multi-output events, static reuse, event-ordered fan-in, bounded cycles, concurrent ready work, dynamic schemas, editable block review, error routing, cancellation and stable-ID resume are native. Each block still runs a real Harness with the mapped Identity/EGO; ordered execution/event records feed an independent verifier. Hosted credential/OAuth connectors, schedules/triggers and proprietary blocks remain service adapters rather than hidden prompt claims. |
| Devika | Initial work runs Planner → short visible `internal_monologue` state → Researcher (at most three advanced queries and optional user question) → first-result browsing/formatting → one-shot multi-file Coder. Follow-ups route to answer, run, deploy, feature, bug or report. Runner asks for OS-specific commands and, on failure, makes at most two command-or-patch recovery attempts. Feature/Patcher rewrite full returned files. Browser interaction is a five-step simplified-DOM loop. The pinned `run-code` API and `git_clone` branch are still TODO; command splitting loses quoting, runner discards stderr and file writes lack path confinement. | `devika_replica`: source-shaped route, plan/status/research/code stages, up to three mapped research jobs, explicit user clarification and dedicated answer/run/feature/bug/report/deploy paths. Run keeps command-vs-code diagnosis but uses safe non-shell tools with stdout/stderr; feature/bug use minimal tracked edits and verification instead of unsafe whole-file overwrite. Browser reuses the real Browser Use Harness with Devika's five-step cap. Deploy requires approval and all long paths checkpoint. |

## Verification status

- All 32 replica/worker JSON graphs pass schema validation.
- Forty-five offline replication tests cover every project and alternate modes. Five
  OpenHands contracts separately prove evidence-driven retry, conservative invalid
  judge handling, inner-loop termination and same-batch truncation on `Finish`, the
  exact ten-attempt cap, and budget finalization without an extra model call. Seven
  Aider contracts separately prove edit parsing/application/review, format
  correction, failed-match feedback, lint reflection, three-round termination,
  inert unapproved shell suggestions and safe budget finalization. Four
  SWE-agent contracts separately prove action/observation/submission, bounded
  format-error autosubmit, environment-error feedback and budget-exhaustion
  finalization without an extra model call.
- Four AI Scientist contracts prove the end-to-end accepted-study path, per-idea
  three-round generation, sequential ten-query conservative novelty, isolated
  template/baseline handling, five-review score aggregation and the four-attempt
  failed-run repair cap.
- Three research-harness contracts separately prove Open Deep Research's adaptive
  supervisor/parallel compressed workers, GPT Researcher's seed-search-before-plan
  standard path, and its typed breadth/depth path with preserved citation maps.
- Four Continue contracts separately prove concurrent tool/error feedback,
  request-time plus execution-time plan restrictions, thresholded persistent
  compaction with exactly one continuation, and budget finalization without an
  extra model call.
- Three Stagehand contracts prove fused evidence verification, forced structured
  completion, source-default mode caps and deterministic cache replay/repair.
  Two OpenManus contracts prove explicit termination and typed planning status.
  Four AutoGPT contracts prove independent parallel blocks, dynamic port fan-in,
  repeated outputs with static reuse, persisted records, dynamic schemas and
  per-block review. Two Devika contracts prove its new-project
  chain and distinct run/feature/bug/browser paths.
- Runtime tests cover structured subflow results, dynamic-limit Map/Loop and Join, safe filters,
  safe expression calculation/slicing/stable deduplication, recent-first word caps,
  deterministic processes/artifacts/resources, retries, budgets, context,
  memory, approvals, the one-action parser/history processor, thresholded
  persistent compaction, request-time tool visibility, first/last-match policy,
  bounded auto-continuation, conservative structured-judge fallback, terminal-tool routing,
  safe run-limit finalization, soft/hard error streak handling, stuck detection,
  stable topological layers, dynamic JSON-Schema routing, bounded tool observations,
  twelve port-scheduler contracts for repeated/static/fan-in/cycle/concurrency/error/
  approval/schema/cancellation/limit/resume behavior,
  and optional Workspace-confined screenshot observations for vision-capable models.
- Durable coordinator tests cover atomic claims, idempotent enqueue, heartbeat,
  cancellation, expired-worker recovery from the newest checkpoint, redacted
  ordered events, HTTP routes and execution through the shared PipelineRunner.
- Agent-bus tests cover subscription routing, idempotent publication, atomic
  single-consumer claims, same-owner checkpoint renewal, lease-expiry
  redelivery, acknowledgement, dead letters and Workspace confinement.
- Two MetaGPT contracts cover both the current MGX adaptive company and the
  classic fixed SOP, including acknowledged Agent-bus artifact delivery.
  AutoGPT separately inspects its port-level execution/event snapshot and
  requires every repeated/static execution to be durably represented.
- Container backend contracts cover security-default command construction,
  secret-free launcher arguments, invalid privilege/network rejection, typed
  Process results and forced cleanup after normal exit and timeout. The live
  test is conditional on a running daemon and an explicit local image.
- Browser tooling has a real local-Chrome integration test covering typed DOM
  and coordinate actions, JavaScript dialog interruption/decision, verified
  downloads, screenshots, CAPTCHA detection, human handoff and resource cleanup.
- Full live parity still depends on external model/search/browser services and
  project-specific toolchains. Those infrastructure gaps are tracked in
  `OPEN_SOURCE_HARNESS_GAPS.md`; they are not hidden behind prompt claims.
- The complete Python suite contains 161 tests. The final full run passed all
  executable tests and skipped only the optional live-container integration
  because this workstation has no running Docker/Podman Linux daemon. The
  Windows lease scenario passed five consecutive stress reruns and the real
  Chrome download scenario passed three consecutive focused reruns before the
  final full suite. The Harness editor passes TypeScript checking and a
  production Vite build; Void's precompiled extension and Webview scripts pass
  Node syntax validation.

## Replication rule

Normal DAG components are used first. Identity and EGO remain the sole place
for persona, behavioral logic, knowledge and tool capability. Python is an
escape hatch only. A replica is accepted only when an offline contract proves
its state transitions and stop conditions; exact environment parity is marked
separately until the real external toolchain has been exercised.
