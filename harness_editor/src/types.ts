export type OpType =
  | '输入' | 'Agent' | '工具审查' | '文本处理' | '工具' | '进程' | '工作区' | '条件' | '数据' | '保存数据' | '读取数据'
  | '循环' | '并行' | '映射' | '合并' | '人工审批' | '子流程' | '检查点'
  | '输出' | '结束' | 'Python' | '模型' | '上下文' | '记忆'
  // Backwards-compatible operation names used by existing Harness files.
  | '等待输入' | '推理' | '处理工具' | '处理文字' | '执行工具' | '脚本' | 'llm_call';

export type EdgeCondition = string;

export interface PipelineEdge {
  condition: EdgeCondition;
  to: string | null;
  when?: string;
}

export interface RetryPolicy {
  max_attempts?: number;
  delay_seconds?: number;
  backoff?: number;
}

export interface ParallelBranch {
  name?: string;
  start: string;
  data?: Record<string, unknown>;
}

export interface PipelineNode {
  id: string;
  op: OpType;
  agent?: string;
  prompt?: string;
  edges: PipelineEdge[];

  // Explicit typed-ish data ports. Values such as $ctx.key and $node.id.port
  // are resolved by the runtime without converting objects to strings.
  inputs?: Record<string, unknown>;
  outputs?: Record<string, string>;

  // Reliability policies shared by every node.
  timeout_seconds?: number;
  retry?: number | RetryPolicy;
  error_to?: string;
  output_schema?: Record<string, unknown>;
  checkpoint?: boolean;
  checkpoint_label?: string;

  // Python / legacy Model fields.
  script?: string;
  input_vars?: string[];
  output_vars?: string[];
  output_var?: string;
  parse_as?: 'text' | 'json' | 'json_object';
  json_fallback?: unknown;
  max_tokens?: number;
  temperature?: number;

  // Deterministic process execution (never invokes a shell).
  backend?: 'local' | 'container' | 'docker' | 'podman';
  container?: Record<string, unknown>;
  container_cleanup_timeout_seconds?: number;
  command?: unknown;
  args?: unknown[];
  cwd?: unknown;
  env?: Record<string, unknown>;
  stdin?: unknown;
  encoding?: string;
  success_codes?: number[];
  fail_on_error?: boolean;
  artifacts?: string[];
  max_output_chars?: number;
  termination_grace_seconds?: number;
  resources?: Record<string, number>;
  target?: unknown;
  paths?: unknown[];
  patterns?: string[];
  overwrite?: boolean;
  backup_before_restore?: boolean;
  ignore?: string[];
  from_sequence?: number;
  event_types?: string[];
  transaction_id?: unknown;
  pending_policy?: 'accept' | 'reject' | 'error';

  // Context selection and compaction.
  roles?: string[];
  names?: string[];
  last_n?: number;
  observation_last_n?: number;
  polling?: number;
  context_limit_tokens?: number;
  max_output_tokens?: number;
  reserved_tokens?: number;
  compaction_buffer_ratio?: number;
  compaction_buffer_cap?: number;
  summary_max_tokens?: number;
  summary_prompt_tokens?: number;
  persist_session?: boolean;
  compacted_var?: string;
  max_chars?: number;
  keep_last?: number;
  summarize?: boolean;
  review_interval?: number;
  protect_recent_turns?: number;
  max_tool_chars?: number;
  stats_var?: string;
  high_watermark?: number;
  target_ratio?: number;
  reserved_output_tokens?: number;
  extra_input_tokens?: number;
  turn_preview_chars?: number;
  block_preview_chars?: number;
  apply_mode?: 'turn_plan' | 'block_plan' | 'restore_full';
  plan?: unknown;
  target_tokens?: unknown;
  reviewed_turn_ids?: unknown;

  // Logic and data nodes.
  condition?: string | boolean;
  expression?: string;
  action?: 'set' | 'get' | 'delete' | 'append' | 'extend' | 'merge' | 'increment' | 'state_transition' | 'range' | 'evaluate' | 'slice' | 'trim_words' | 'unique' | 'filter' | 'aggregate_fields' | 'topological_levels' | 'validate_schema' | 'save' | 'load' | 'replay' | 'select' | 'snapshot' | 'apply' | 'compact' | 'auto_compact' | 'last_n_observations' | 'curate' | 'restore_full'
    | 'mkdir' | 'copy' | 'publish' | 'snapshot' | 'restore' | 'list' | 'read_text' | 'read_json' | 'read_binary' | 'write_text' | 'write_json' | 'write_binary' | 'move' | 'rename' | 'apply_search_replace' | 'apply_edits'
    | 'begin_transaction' | 'changes' | 'review_transaction' | 'rollback_transaction'
    | 'add' | 'add_unique' | 'upsert' | 'search' | 'list' | 'clear' | 'needs_reflection' | 'mark_reflected'
    | 'agent_register' | 'agent_heartbeat' | 'agent_unregister' | 'agent_list'
    | 'message_publish' | 'message_receive' | 'message_ack' | 'message_nack' | 'message_list';
  scope?: 'run' | 'session' | 'file';
  key?: string;
  value?: unknown;
  default?: unknown;
  fields?: string[];
  limits?: Record<string, [number, number]>;
  round_to_int?: boolean;
  id_field?: string;
  dependency_field?: string;
  schema?: Record<string, unknown>;
  range_start?: unknown;
  range_stop?: unknown;
  range_step?: unknown;
  max_items?: number;
  delta?: number;
  max_bytes?: number;
  truncate?: boolean;
  allow_missing?: boolean;
  append?: boolean;
  track_change?: boolean;
  indent?: number;
  trailing_newline?: boolean;
  binary_encoding?: 'base64' | 'hex' | 'utf8';
  path?: string;
  namespace?: string;
  query?: unknown;
  memory_type?: string;
  retention?: number;
  dedupe_key?: string;
  upsert_key?: string;
  memory_id?: string;
  importance?: number;
  keywords?: string[];
  metadata?: Record<string, unknown>;
  evidence?: unknown[];
  top_k?: number;
  threshold?: number;
  recency_half_life_seconds?: number;
  weights?: { relevance?: number; recency?: number; importance?: number };
  agent_id?: unknown;
  subscriptions?: string[];
  topic?: unknown;
  topics?: string[];
  sender?: unknown;
  recipients?: string[];
  recipient?: unknown;
  payload?: unknown;
  headers?: Record<string, unknown>;
  idempotency_key?: unknown;
  delay_seconds?: number;
  max_attempts?: number;
  lease_seconds?: number;
  owner?: unknown;
  receipts?: unknown;
  limit?: number;
  state?: 'pending' | 'leased' | 'acked' | 'dead';
  include_inactive?: boolean;
  max_payload_bytes?: number;

  // Control-flow nodes.
  list_var?: string;
  item_var?: string;
  counter_var?: string;
  body_start?: string;
  max_count?: number;
  result_var?: string;
  break_when?: string;
  branches?: Array<string | ParallelBranch>;
  join?: string;
  max_workers?: number;
  parallel?: boolean;
  sensitive_fields?: string[];
  attach_images?: boolean;
  max_image_bytes?: number;
  max_observation_chars?: number;
  interrupt_when?: string;
  stuck_threshold?: number;
  error_stuck_threshold?: number;
  error_nudge_threshold?: number;
  error_nudge_prompt?: string;
  error_nudge_to?: string;
  alternating_stuck_threshold?: number;
  truncate_after_tools?: string[];
  exclusive_tools?: string[];
  only_first_tools?: string[];
  terminal_tools_to?: string;
  fail_fast?: boolean;
  source?: unknown;
  full_source?: unknown;
  start_index?: unknown;
  end_index?: unknown;
  step?: unknown;
  max_words?: unknown;
  strategy?: 'list' | 'values' | 'flatten' | 'concat' | 'merge' | 'first' | 'last';
  separator?: string;

  // Human, subflow and output nodes.
  prompt_text?: string;
  reuse_last?: boolean;
  editable?: boolean;
  name?: string;
  choices?: string[];
  approved_values?: string[];
  harness?: string;
  block_harness?: string;
  identity_map?: Record<string, string>;
  agent_map?: Record<string, string>;
  share_session?: boolean;
  component_inputs?: Record<string, unknown>;
  component_outputs?: Record<string, string>;
  initial_message?: string;
  block_message?: string;
  result_mode?: 'text' | 'messages' | 'result' | 'data';
  inline_pipeline?: unknown;
  port_graph?: unknown;
  state_path?: string;
  resume_state?: boolean;
  records_var?: string;
  events_var?: string;
  compiled_graph_var?: string;
  max_executions?: number;
  max_events?: number;
  review_default?: 'approved' | 'rejected';
  dynamic_name?: string;
  dynamic_slots?: Record<string, unknown>;
  dynamic_prompts?: Record<string, unknown>;
  max_dynamic_nodes?: number;
  max_depth?: number;
  allow_unsafe?: boolean;
  label?: string;
  record?: boolean;
  continue?: boolean;
  tools?: 'auto' | 'all' | 'none' | boolean;
  instructions?: unknown;
  review_mode?: 'agent' | 'policy' | 'both';
  policies?: Array<{ tool: string; permission: 'allow' | 'ask' | 'deny' | 'exclude' }>;
  policy_match?: 'first' | 'last';
  default_permission?: 'allow' | 'ask' | 'deny' | 'exclude';
  ask_default?: 'approved' | 'rejected';
  duplicate_threshold?: number;
  max_empty_responses?: number;
  empty_response_prompt?: string;
  empty_response_to?: string;
  stuck_prompt?: string;
  stuck_to?: string;

  // One-thought/one-action protocols such as SWE-agent.
  mode?: 'agent' | 'thought_action' | 'swe_action' | 'aider_search_replace' | 'aider_editblock' | 'port_graph';
  action_tool?: string;
  action_argument?: string;
  action_arguments?: Record<string, unknown>;
  submission_commands?: string[];
  exit_commands?: string[];
  max_requeries?: number;
  format_error_prompt?: string;
  require_edits?: boolean;
  valid_filenames?: unknown;
  edits?: unknown;
  allowed_paths?: unknown;
  atomic?: boolean;
  fallback_to_allowed_paths?: boolean;
  max_tool_calls_per_turn?: number;
  max_tool_rounds?: number;
  tool_round_limit_prompt?: string;
  require_tool_before_text?: boolean;
  require_tool_for_mutations?: boolean;
  required_tool_patterns?: string[];
  max_required_tool_retries?: number;
  required_tool_prompt?: string;
  tool_call_count_error_to?: string;
  tool_call_count_error_prompt?: string;
  end_session_to?: string;
  visible_tools?: string[];
  hidden_tools?: string[];
  auto_continue_when?: string | boolean;
  auto_continue_prompt?: unknown;
  auto_continue_to?: string;
  max_auto_continuations?: number;

  [key: string]: unknown;
}

export interface SlotDef {
  description: string;
  required: boolean;
  identity?: string;
}

export interface PromptDef {
  description: string;
  default: string;
}

export interface PipelineBudget {
  max_model_calls?: number;
  max_tool_calls?: number;
  max_process_calls?: number;
  max_tokens?: number;
  max_cost?: number;
  max_elapsed_seconds?: number;
  prices?: { input_per_million?: number; output_per_million?: number };
}

export interface PipelinePermissionRule {
  decision: 'allow' | 'ask' | 'deny';
  permission_class?: 'read' | 'write' | 'process' | 'network' | 'secret' | 'mutation';
  tool?: string;
  workspace?: string;
  modes?: string[];
  arguments?: Record<string, string>;
  reason?: string;
}

export interface PipelinePermissions {
  defaults?: Partial<Record<'read' | 'write' | 'process' | 'network' | 'secret' | 'mutation', 'allow' | 'ask' | 'deny'>>;
  allow_sensitive_files?: boolean;
  allow_global_mutation?: boolean;
  mutation_targets?: string[];
  rules?: PipelinePermissionRule[];
}

export interface ComponentPortSpec {
  description?: string;
  required?: boolean;
  default?: unknown;
  schema?: Record<string, unknown>;
  path?: string;
}

export interface HarnessComponentManifest {
  name?: string;
  display_name?: string;
  category?: string;
  description?: string;
  icon?: string;
  share_session?: boolean;
  inputs: Record<string, ComponentPortSpec>;
  outputs: Record<string, ComponentPortSpec>;
}

export interface HarnessConfig {
  name: string;
  description: string;
  slots: Record<string, SlotDef>;
  prompts: Record<string, PromptDef>;
  return_mode: 'all' | 'last';
  component?: HarnessComponentManifest;
  pipeline: {
    start: string;
    mode?: 'agent' | 'ask' | 'plan' | 'chat' | 'evaluate' | 'task' | 'evolve' | string;
    max_steps: number;
    max_node_steps?: number;
    timeout_seconds?: number;
    workspace_preview: boolean;
    context?: Record<string, unknown>;
    reducers?: Record<string, string | { strategy: string; separator?: string }>;
    resource_limits?: Record<string, number>;
    event_log?: boolean | string | { path?: string };
    auto_checkpoint?: boolean;
    secret_names?: string[];
    permissions?: PipelinePermissions;
    budget?: PipelineBudget;
    budget_exceeded_to?: string;
    limit_exceeded_to?: string;
    limit_finalizer_max_steps?: number;
    checkpoint_dir?: string;
    nodes: Record<string, PipelineNode>;
  };
}

export interface ExecutionState {
  run_id?: string;
  workspace?: string;
  harness?: string;
  agents?: Record<string, string>;
  running: boolean;
  status?: 'idle' | 'running' | 'waiting_approval' | 'completed' | 'limit_exceeded' | 'cancelled' | 'error' | string;
  termination?: {
    kind?: string;
    code?: string;
    title?: string;
    message?: string;
    action?: string;
    failure?: {
      code?: string;
      title?: string;
      message?: string;
      action?: string;
      recoverable?: boolean;
    };
    [key: string]: unknown;
  } | null;
  pending_approval?: {
    approval_id?: string;
    prompt?: string;
    tool?: string;
    arguments?: unknown;
    reason?: string;
    default?: string;
    risk?: {
      level?: 'low' | 'medium' | 'high' | 'critical' | string;
      summary?: string;
      findings?: Array<{ code?: string; message?: string }>;
    };
    [key: string]: unknown;
  } | null;
  warnings?: Array<Record<string, unknown>>;
  security?: Record<string, unknown>;
  sandbox?: Record<string, unknown>;
  waiting_for_input?: boolean;
  current_node: string | null;
  step_count: number;
  messages_count: number;
  debug_mode: 'auto' | 'paused';
  paused: boolean;
  pause_requested: boolean;
  pending_node: string | null;
  pause_reason?: 'before' | 'error' | null;
  node_traces: NodeTrace[];
  _tick?: number;
  outputs?: unknown[];
}

export interface NodeTraceTool {
  name: string;
  arguments?: unknown;
  result?: unknown;
  blocked?: boolean;
  reason?: string;
}

export interface NodeTrace {
  sequence: number;
  node_id: string;
  op: string;
  agent?: string;
  status: 'entered' | 'running' | 'ok' | 'completed' | 'error';
  input?: unknown;
  last_output?: unknown;
  output?: unknown;
  model: {
    request?: unknown;
    response?: unknown;
    tool_calls?: unknown;
  };
  tools: NodeTraceTool[];
  usage?: {
    model?: string;
    request_ids?: string[];
    attempts?: number;
    reconnects?: number;
    input_tokens?: number;
    cached_input_tokens?: number;
    output_tokens?: number;
  };
  retries?: Array<{
    attempt?: number;
    max_attempts?: number;
    message?: string;
  }>;
  artifacts?: string[];
  error?: {
    type?: string;
    message?: string;
    attempt?: number;
    max_attempts?: number;
  } | null;
  stats?: Record<string, unknown>;
  duration_ms?: number;
  started_at?: number;
  completed_at?: number;
}

export interface TaskCheck {
  id?: string;
  type: string;
  weight?: number;
  [key: string]: unknown;
}

export interface TaskSpec {
  version: 'ego.task.v1';
  id: string;
  title: string;
  description: string;
  category: string;
  difficulty: 'starter' | 'easy' | 'medium' | 'hard' | 'research';
  tags: string[];
  prompt: string;
  workspace: { files: Record<string, string | { content?: string; content_base64?: string; binary?: boolean }> };
  selection: {
    recommended_harness?: string;
    recommended_identity?: string;
    compatible_harnesses?: string[];
    compatible_identities?: string[];
  };
  environment: {
    backend?: 'local' | 'container'; network?: 'inherit' | 'disabled' | 'required';
    container?: { dockerfile?: string; build_context?: string; workdir?: string; cpus?: number; memory_mb?: number };
  };
  execution: { timeout_seconds?: number };
  evolution: { allowed?: boolean; targets?: string[] };
  evaluation: { pass_score: number; checks: TaskCheck[] };
  steps?: Array<{
    id: string; title?: string; prompt: string; resume_trajectory?: boolean;
    workspace?: { files: Record<string, string | { content?: string; content_base64?: string }> };
    evaluation: { pass_score: number; checks: TaskCheck[] };
    artifacts?: string[];
  }>;
  external_format?: { type: 'harbor' | 'terminal-bench'; schema_version?: string; task_version?: string; authors?: string[] };
}

export interface TaskBenchOptions {
  harnesses: Array<{ name: string; description: string; slots: Record<string, SlotDef>; node_count: number }>;
  identities: Array<{ name: string; description: string; role: string }>;
  environments: Array<{ name: string; description: string }>;
}

export interface TaskEvaluationCheck {
  id: string;
  type: string;
  passed: boolean;
  weight: number;
  summary: string;
  details: Record<string, unknown>;
}

export interface TaskEvaluation {
  score: number;
  earned: number;
  total_weight: number;
  pass_score: number;
  passed: boolean;
  checks: TaskEvaluationCheck[];
}

export interface TaskRunEvent {
  sequence: number;
  time: number;
  type: string;
  data: Record<string, any>;
}

export interface TaskRunState {
  id: string;
  task_id: string;
  task: TaskSpec;
  selection: {
    harness: string;
    identity: string;
    environments: string[];
    slot_bindings: Record<string, string>;
  };
  status: 'created' | 'running' | 'evaluating' | 'passed' | 'failed' | 'error' | 'stopped' | 'timeout';
  running: boolean;
  debug_mode: 'auto' | 'paused';
  paused: boolean;
  pause_requested: boolean;
  pending_node: string | null;
  current_node: string | null;
  step_count: number;
  task_step: string | null;
  task_steps: Array<{
    id: string; title: string; status: string; started_at: number; completed_at: number | null;
    evaluation: TaskEvaluation | null;
  }>;
  node_traces: NodeTrace[];
  events: TaskRunEvent[];
  outputs: Array<Record<string, any>>;
  evolution_events: TaskRunEvent[];
  evaluation: TaskEvaluation | null;
  mutations: Record<string, any>;
  artifacts: Array<{ path: string; size: number; preview: string }>;
  workspace: string;
  created_at: number;
  started_at: number | null;
  completed_at: number | null;
  error: string | null;
  stats: Record<string, any>;
  policy: { hidden_tools: string[]; network: string };
}
