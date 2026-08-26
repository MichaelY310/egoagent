import { API_BASE as BASE, WORKSPACE, WS_BASE } from './runtime';

async function request(method: string, path: string, body?: unknown) {
  const opts: RequestInit = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(`${BASE}${path}`, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || res.statusText);
  }
  return res.json();
}

// ============ Harness ============

export async function listHarnesses(): Promise<string[]> {
  return request("GET", "/api/harnesses");
}

/** Canonical node/port contract shared by Studio, the runtime and authoring agents. */
export async function getDagContracts() {
  return request("GET", "/api/dag/contracts");
}

export type WorkspaceSecuritySettings = {
  version?: number;
  profile: 'strict' | 'balanced' | 'trusted' | 'unrestricted';
  require_dangerous_approval: boolean;
  dangerous_action_decision: 'allow' | 'ask' | 'deny';
  critical_action_decision: 'allow' | 'ask' | 'deny';
  unknown_tool_decision: 'allow' | 'ask' | 'deny';
  network_decision: 'allow' | 'ask' | 'deny';
  secret_decision: 'allow' | 'ask' | 'deny';
  allow_sensitive_files: boolean;
  workspace_only: boolean;
  sandbox: {
    mode: 'workspace' | 'container' | 'off';
    engine: 'docker' | 'podman';
    image: string;
    network: 'none' | 'bridge';
    read_only_root: boolean;
    workspace_access: 'ro' | 'rw';
    pids_limit: number;
    memory: string;
    cpus: number;
    tmpfs_size: string;
    pull_policy: 'never' | 'missing' | 'always';
    fail_closed: boolean;
  };
};

export async function getSecuritySettings(workspace = WORKSPACE) {
  return request('GET', `/api/security/settings?workspace=${encodeURIComponent(workspace || '')}`);
}

export async function saveSecuritySettings(settings: WorkspaceSecuritySettings, workspace = WORKSPACE) {
  return request('POST', '/api/security/settings', { workspace: workspace || undefined, settings });
}

export type HarnessCatalogItem = {
  name: string;
  description: string;
  slot_count: number;
  slots: string[];
  component?: {
    name?: string;
    display_name?: string;
    category?: string;
    description?: string;
    icon?: string;
    share_session?: boolean;
    inputs?: Record<string, { description?: string; required?: boolean; default?: unknown; schema?: Record<string, unknown> }>;
    outputs?: Record<string, { description?: string; path?: string; default?: unknown; schema?: Record<string, unknown> }>;
  } | null;
};

export type CapabilityReuseContract = {
  modes?: string[];
  identity?: string;
  binding?: string;
  harness?: string;
  slots?: Record<string, { required?: boolean; default_identity?: string | null; description?: string }>;
  invoke?: { tool?: string; arguments?: Record<string, unknown> };
  subflow?: Record<string, unknown>;
};

export async function listHarnessDetails(): Promise<HarnessCatalogItem[]> {
  return request("GET", "/api/harnesses/detailed");
}

export async function loadHarness(name: string) {
  return request("GET", `/api/harness/${encodeURIComponent(name)}`);
}

export async function saveHarness(name: string, config: unknown) {
  return request("PUT", `/api/harness/${encodeURIComponent(name)}`, config);
}

// ============ Identity ============

export async function listIdentities(): Promise<string[]> {
  const identities = await request("GET", "/api/identities");
  // The API returns rich identity summaries. Most editor controls only need the
  // stable name, so normalize both the current object shape and the legacy
  // string shape at this boundary instead of letting React render an object.
  if (!Array.isArray(identities)) return [];
  return identities
    .map((identity) => typeof identity === "string" ? identity : identity?.name)
    .filter((name): name is string => typeof name === "string" && name.length > 0);
}

export async function createAgentSystem(description: string, name?: string) {
  return request("POST", "/api/agent/create", { description, name: name || undefined });
}

export async function loadIdentity(name: string) {
  return request("GET", `/api/identity/${encodeURIComponent(name)}`);
}

export async function saveIdentity(name: string, idData: unknown) {
  return request("PUT", `/api/identity/${encodeURIComponent(name)}`, idData);
}

export async function saveSuperego(name: string, data: unknown) {
  return request("PUT", `/api/identity/${encodeURIComponent(name)}/superego`, data);
}

export async function loadSkill(identityName: string, skillName: string) {
  return request("GET", `/api/identity/${encodeURIComponent(identityName)}/skill/${encodeURIComponent(skillName)}`);
}

export async function saveSkill(identityName: string, skillName: string, data: { meta: unknown; scripts: Record<string, string> }) {
  return request("PUT", `/api/identity/${encodeURIComponent(identityName)}/skill/${encodeURIComponent(skillName)}`, data);
}

export async function deleteSkill(identityName: string, skillName: string) {
  return request("DELETE", `/api/identity/${encodeURIComponent(identityName)}/skill/${encodeURIComponent(skillName)}`);
}

export async function loadKnowledge(identityName: string, knowledgeName: string) {
  return request("GET", `/api/identity/${encodeURIComponent(identityName)}/knowledge/${encodeURIComponent(knowledgeName)}`);
}

export async function saveKnowledge(identityName: string, knowledgeName: string, data: { meta: unknown; content: string }) {
  return request("PUT", `/api/identity/${encodeURIComponent(identityName)}/knowledge/${encodeURIComponent(knowledgeName)}`, data);
}

export async function deleteKnowledge(identityName: string, knowledgeName: string) {
  return request("DELETE", `/api/identity/${encodeURIComponent(identityName)}/knowledge/${encodeURIComponent(knowledgeName)}`);
}

export async function cloneIdentity(name: string, newName: string) {
  return request("POST", `/api/identity/${encodeURIComponent(name)}/clone`, { new_name: newName });
}

export async function deleteIdentity(name: string) {
  return request("DELETE", `/api/identity/${encodeURIComponent(name)}`);
}

export type CoCCharacterCard = {
  actor_id?: string;
  identity: string;
  name: string;
  occupation: string;
  revision: number;
  derived: Record<string, number | boolean>;
  skills: Record<string, number>;
  conditions: string[];
  equipment: Record<string, Record<string, unknown>>;
};

export async function listCoCCharacters(): Promise<CoCCharacterCard[]> {
  const result = await request("GET", "/api/coc/characters");
  return Array.isArray(result?.characters) ? result.characters : [];
}

export async function createCoCCharacter(payload: Record<string, unknown>): Promise<{ ok: boolean; character: CoCCharacterCard }> {
  return request("POST", "/api/coc/characters", payload);
}

// ============ Environment ============

export async function listEnvironments() {
  return request("GET", "/api/environments");
}

export async function createEnvironment(name: string) {
  return request("POST", "/api/environments", { name });
}

export async function loadEnvironment(pathB64: string) {
  return request("GET", `/api/environment/${encodeURIComponent(pathB64)}`);
}

export async function loadEnvTool(pathB64: string, toolName: string) {
  return request("GET", `/api/environment/${encodeURIComponent(pathB64)}/tool/${encodeURIComponent(toolName)}`);
}

export async function saveEnvTool(pathB64: string, toolName: string, data: { meta: unknown; scripts: Record<string, string> }) {
  return request("PUT", `/api/environment/${encodeURIComponent(pathB64)}/tool/${encodeURIComponent(toolName)}`, data);
}

export async function deleteEnvTool(pathB64: string, toolName: string) {
  return request("DELETE", `/api/environment/${encodeURIComponent(pathB64)}/tool/${encodeURIComponent(toolName)}`);
}

export async function loadEnvKnowledge(pathB64: string, knowledgeName: string) {
  return request("GET", `/api/environment/${encodeURIComponent(pathB64)}/knowledge/${encodeURIComponent(knowledgeName)}`);
}

export async function saveEnvKnowledge(pathB64: string, knowledgeName: string, data: { meta: unknown; content: string }) {
  return request("PUT", `/api/environment/${encodeURIComponent(pathB64)}/knowledge/${encodeURIComponent(knowledgeName)}`, data);
}

export async function deleteEnvKnowledge(pathB64: string, knowledgeName: string) {
  return request("DELETE", `/api/environment/${encodeURIComponent(pathB64)}/knowledge/${encodeURIComponent(knowledgeName)}`);
}

// ============ Execution ============

let _ws: WebSocket | null = null;
let _wsCallbacks: Array<(msg: any) => void> = [];

export async function getExecutionState(runId?: string) {
  const params = new URLSearchParams();
  if (runId) params.set('run_id', runId);
  else if (WORKSPACE) params.set('workspace', WORKSPACE);
  const query = params.toString();
  return request("GET", `/api/execution/state${query ? `?${query}` : ''}`);
}

export async function startExecution(harness: string, agents: Record<string, string>, debugMode: 'auto' | 'paused' = 'auto') {
  return request("POST", "/api/execution/start", {
    harness,
    agents,
    debug_mode: debugMode,
    workspace: WORKSPACE || undefined,
  });
}

export async function stopExecution(runId?: string) {
  return request("POST", "/api/execution/stop", { run_id: runId, workspace: WORKSPACE || undefined });
}

export async function respondToExecutionApproval(
  approvalId: string,
  decision: 'approved' | 'rejected',
  runId?: string,
) {
  return request('POST', '/api/execution/approval', {
    run_id: runId,
    workspace: WORKSPACE || undefined,
    approval_id: approvalId,
    decision,
  });
}

export async function controlExecution(
  action: 'pause' | 'step' | 'continue' | 'resume' | 'auto' | 'skip' | 'override_inputs' | 'retry_with_inputs',
  payload: Record<string, unknown> = {},
  runId?: string,
) {
  return request("POST", "/api/execution/control", {
    action,
    ...payload,
    run_id: runId,
    workspace: WORKSPACE || undefined,
  });
}

export async function listInterruptedRuns() {
  return request("GET", "/api/runs/recovery");
}

export async function recoverDurableRun(
  runId: string,
  action: 'resume' | 'discard',
  options: { confirm_in_doubt?: boolean; allow_revision_conflicts?: boolean } = {},
) {
  return request("POST", `/api/runs/${encodeURIComponent(runId)}/${action}`, options);
}

export async function listDurableRuns(status?: string) {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return request("GET", `/api/runs${query}`);
}

export async function createDurableRun(payload: {
  harness: string;
  identity: string;
  messages: Array<{ role: string; content: string }>;
  workspace: string;
  mode: string;
  mutation_targets?: string[];
  priority?: number;
  max_attempts?: number;
  isolate?: boolean;
}) {
  return request("POST", "/api/runs", payload);
}

export async function controlDurableRun(runId: string, action: "pause" | "resume" | "cancel") {
  return request("POST", `/api/runs/${encodeURIComponent(runId)}/${action}`, {});
}

export async function getDurableRunEvents(runId: string, after = 0) {
  return request("GET", `/api/runs/${encodeURIComponent(runId)}/events?after=${after}`);
}

export async function forkDurableRun(runId: string, options: {
  from_checkpoint?: boolean;
  payload_overrides?: Record<string, unknown>;
  replay?: boolean;
} = {}) {
  const action = options.replay ? 'replay' : 'fork';
  return request("POST", `/api/runs/${encodeURIComponent(runId)}/${action}`, {
    from_checkpoint: options.from_checkpoint ?? !options.replay,
    payload_overrides: options.payload_overrides || {},
  });
}

export async function compareDurableRuns(left: string, right: string) {
  return request("GET", `/api/runs/compare?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`);
}

// ============ Agent Packages & local marketplace ============

export async function listPackages(query = "") {
  return request("GET", `/api/packages${query ? `?query=${encodeURIComponent(query)}` : ""}`);
}

export async function listInstalledPackages() {
  return request("GET", "/api/packages/installed");
}

export async function packAgentPackage(payload: Record<string, unknown>) {
  return request("POST", "/api/packages/pack", payload);
}

export async function addPackageArchive(archive: string, trust = "untrusted") {
  return request("POST", "/api/packages/add", { archive, trust });
}

export async function installRegistryPackage(name: string, version?: string, options: { allow_update?: boolean; allow_untrusted?: boolean } = {}) {
  return request("POST", "/api/packages/install", { name, version, ...options });
}

export async function uninstallAgentPackage(name: string, force = false) {
  return request("POST", "/api/packages/uninstall", { name, force });
}

export async function setPackageTrust(name: string, version: string, trust: "untrusted" | "local" | "verified") {
  return request("POST", "/api/packages/trust", { name, version, trust });
}

export async function ratePackage(name: string, version: string, score: number, note = "") {
  return request("POST", "/api/packages/rate", { name, version, reviewer: "local", score, note });
}

export async function forkRegistryPackage(name: string, version: string, newName: string, newVersion = "0.1.0") {
  return request("POST", "/api/packages/fork", { name, version, new_name: newName, new_version: newVersion });
}

// ============ Local Capability Library ============

export type CapabilityItem = {
  id: string;
  kind: 'skill' | 'tool' | 'knowledge' | 'identity' | 'harness';
  name: string;
  display_name?: string;
  description: string;
  tags: string[];
  scope: string;
  workspace_root?: string;
  path?: string;
  owner?: string;
  version?: string;
  impressions?: number;
  activations?: number;
  successes?: number;
  failures?: number;
  usage_count: number;
  success_rate: number | null;
  average_runtime_ms?: number | null;
  score?: number;
  lexical_score?: number;
  semantic_score?: number | null;
  match_reason?: string;
  reuse?: CapabilityReuseContract;
};

export async function listCapabilities(kind = ''): Promise<{ items: CapabilityItem[]; stats: Record<string, any>; pinned: string[] }> {
  return request("POST", "/api/capabilities/list", { workspace: WORKSPACE || undefined, kind: kind || undefined, limit: 2000 });
}

export async function searchCapabilities(query: string, kinds: string[] = [], limit = 50, mode: 'auto' | 'hybrid' | 'semantic' | 'lexical' = 'auto') {
  return request("POST", "/api/capabilities/search", { workspace: WORKSPACE || undefined, query, kinds, limit, mode });
}

export async function reindexCapabilities() {
  return request("POST", "/api/capabilities/reindex", { workspace: WORKSPACE || undefined });
}

export async function recordCapabilityEvent(capabilityId: string, event: 'activate' | 'execute' = 'activate', success?: boolean) {
  return request("POST", "/api/capabilities/event", {
    workspace: WORKSPACE || undefined,
    capability_id: capabilityId,
    event,
    success,
  });
}

export async function pinCapability(capabilityId: string, enabled: boolean) {
  return request("POST", "/api/capabilities/pin", {
    workspace: WORKSPACE || undefined,
    capability_id: capabilityId,
    enabled,
  });
}

export async function previewDurableRunHandoff(runId: string) {
  return request("GET", `/api/runs/${encodeURIComponent(runId)}/handoff`);
}

export async function applyDurableRunHandoff(runId: string, payload: {
  paths: string[];
  expected_revisions: Record<string, string>;
  confirm_delete?: boolean;
}) {
  const response = await fetch(`${BASE}/api/runs/${encodeURIComponent(runId)}/handoff`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({ error: response.statusText }));
  return { ...data, http_status: response.status };
}

// ============ Agent Change Review ============

export async function listAgentChanges(transactionId?: string, workspace?: string) {
  const params = new URLSearchParams();
  if (transactionId) params.set('transaction_id', transactionId);
  if (workspace) params.set('workspace', workspace);
  const query = params.size ? `?${params.toString()}` : '';
  return request("GET", `/api/session/changes${query}`);
}

export async function reviewAgentChange(
  action: 'accept' | 'reject' | 'undo',
  id: string,
  options: { hunk_id?: string; reason?: string; confirm_delete?: boolean } = {},
) {
  return request("POST", `/api/session/changes/${action}`, { id, ...options });
}

export async function revertAllAgentChanges(options: { transaction_id?: string; confirm_delete?: boolean } = {}) {
  return request("POST", "/api/session/changes/revert-all", options);
}

// ============ Exact trajectory replay and training export ============

export type TrajectoryEvent = {
  schema: string;
  event_id: string;
  sequence: number;
  timestamp: number;
  trace_id: string;
  session_id?: string | null;
  run_id?: string | null;
  parent_run_id?: string | null;
  harness?: string | null;
  node_id?: string | null;
  node_op?: string | null;
  agent?: string | null;
  identity?: string | null;
  model_call_id?: string | null;
  tool_call_id?: string | null;
  type: string;
  tags?: string[];
  data: Record<string, unknown>;
};

export type TrajectorySummary = {
  session: string;
  trace_id?: string | null;
  events: number;
  first_timestamp?: number | null;
  last_timestamp?: number | null;
  agents: string[];
  identities: string[];
  runs: string[];
  harnesses: string[];
  model_calls: number;
  event_types: Record<string, number>;
  validation: { valid: boolean; errors: string[]; warnings: string[]; incomplete_model_calls: string[] };
};

export type TrajectoryCollectionSettings = {
  schema?: string;
  enabled: boolean;
  destination: string;
  partition_by_date: boolean;
  partition_by_project: boolean;
  updated_at?: number | null;
};

export async function getTrajectorySummary(session: string): Promise<TrajectorySummary> {
  return request("GET", `/api/session/${encodeURIComponent(session)}/trajectory/summary`);
}

export async function getTrajectoryEvents(
  session: string,
  options: { after?: number; limit?: number; types?: string[]; agents?: string[] } = {},
): Promise<{ session: string; events: TrajectoryEvent[]; after: number; next_after: number; has_more: boolean }> {
  const query = new URLSearchParams();
  if (options.after) query.set("after", String(options.after));
  if (options.limit) query.set("limit", String(options.limit));
  if (options.types?.length) query.set("types", options.types.join(","));
  if (options.agents?.length) query.set("agents", options.agents.join(","));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request("GET", `/api/session/${encodeURIComponent(session)}/trajectory/events${suffix}`);
}

export async function getTrajectoryModelCalls(session: string, includeIncomplete = false) {
  return request("GET", `/api/session/${encodeURIComponent(session)}/trajectory/model-calls?include_incomplete=${includeIncomplete ? "1" : "0"}`);
}

export async function exportTrajectory(
  session: string,
  options: { destination?: string; include_reasoning?: boolean; include_incomplete?: boolean } = {},
) {
  return request("POST", `/api/session/${encodeURIComponent(session)}/trajectory/export`, options);
}

export async function getTrajectoryCollectionSettings(): Promise<{
  settings: TrajectoryCollectionSettings;
  native_collection: { enabled: true; description?: string };
}> {
  return request("GET", "/api/trajectory/settings");
}

export async function saveTrajectoryCollectionSettings(settings: TrajectoryCollectionSettings) {
  return request("POST", "/api/trajectory/settings", { settings });
}

// ============ Human feedback and curated training datasets ============

export type TrainingAnnotation = {
  schema: string;
  id: string;
  session: string;
  target_type: 'session' | 'message' | 'model_call' | 'event';
  target_id: string;
  source_hash: string;
  rating: 'up' | 'down' | 'neutral';
  important: boolean;
  include_in_training: boolean;
  tags: string[];
  note: string;
  created_at: number;
  updated_at: number;
};

export type TrainingAnnotationSummary = {
  total: number;
  ratings: Record<'up' | 'down' | 'neutral', number>;
  important: number;
  included: number;
  sessions: number;
};

export async function getTrainingAnnotations(options: { session?: string; target_type?: string } = {}): Promise<{
  annotations: TrainingAnnotation[];
  summary: TrainingAnnotationSummary;
}> {
  const query = new URLSearchParams();
  if (options.session) query.set('session', options.session);
  if (options.target_type) query.set('target_type', options.target_type);
  return request('GET', `/api/training/annotations${query.size ? `?${query.toString()}` : ''}`);
}

export async function saveTrainingAnnotation(input: {
  session: string;
  target_type: TrainingAnnotation['target_type'];
  target_id: string;
  source_hash?: string;
  rating?: TrainingAnnotation['rating'];
  important?: boolean;
  include_in_training?: boolean;
  tags?: string[];
  note?: string;
}): Promise<{ ok: true; annotation: TrainingAnnotation }> {
  return request('POST', '/api/training/annotations', input);
}

export type TrainingExportManifest = {
  schema: string;
  created_at: number;
  destination: string;
  selection: 'marked' | 'all';
  formats: string[];
  sources: Array<{ session: string; path: string; source_hash: string; annotations: number; selected: boolean }>;
  counts: Record<string, number>;
  files: Record<string, string | null>;
  manifest_path: string;
  quality_rules: string[];
};

export async function exportTrainingDataset(input: {
  sessions: string[];
  destination?: string;
  selection?: 'marked' | 'all';
  formats?: string[];
  include_reasoning?: boolean;
}): Promise<{ ok: true; manifest: TrainingExportManifest }> {
  return request('POST', '/api/training/export', input);
}

// ============ Session branching and merge ============

export type ProjectPortfolioItem = {
  id: string;
  workspace: string;
  title: string;
  description?: string;
  tags?: string[];
  pinned?: boolean;
  archived?: boolean;
  current?: boolean;
  available?: boolean;
  session_count: number;
  active_session_count?: number;
  active_session?: string;
  last_session_at?: number;
  last_opened_at?: number;
  run_count?: number;
  running_count?: number;
  waiting_count?: number;
};

export type PortfolioSession = {
  id: string;
  name: string;
  title?: string;
  path: string;
  workspace: string;
  workspace_provenance?: string;
  project_id: string;
  timestamp: number;
  message_count: number;
  working_message_count?: number;
  summary?: string;
  harness?: string;
  session_id?: string;
  trace_id?: string;
  has_trajectory?: boolean;
  trajectory_events?: number;
  trajectory_agents?: string[];
  health?: Record<string, unknown> | null;
  pinned?: boolean;
  archived?: boolean;
  lineage?: SessionLineage | null;
};

export async function listProjects(includeArchived = false): Promise<ProjectPortfolioItem[]> {
  const params = new URLSearchParams();
  if (WORKSPACE) params.set('workspace', WORKSPACE);
  if (includeArchived) params.set('include_archived', '1');
  const result = await request('GET', `/api/projects?${params.toString()}`);
  return result.projects || [];
}

export async function listProjectSessions(options: {
  project_id?: string;
  workspace?: string;
  include_archived?: boolean;
  limit?: number;
} = {}): Promise<PortfolioSession[]> {
  const params = new URLSearchParams();
  if (options.project_id) params.set('project_id', options.project_id);
  if (options.workspace) params.set('workspace', options.workspace);
  if (options.include_archived) params.set('include_archived', '1');
  params.set('limit', String(options.limit || 500));
  const result = await request('GET', `/api/projects/sessions?${params.toString()}`);
  return result.sessions || [];
}

export async function registerProject(workspace: string, title?: string) {
  return request('POST', '/api/projects/register', { workspace, title });
}

export async function updateProject(project_id: string, changes: Partial<Pick<ProjectPortfolioItem, 'title' | 'description' | 'tags' | 'pinned' | 'archived' | 'active_session'>>) {
  return request('POST', '/api/projects/update', { project_id, changes });
}

export async function updatePortfolioSession(session: string, changes: { title?: string; pinned?: boolean; archived?: boolean; last_opened_at?: number }) {
  return request('POST', '/api/projects/session/update', { session, changes });
}

export type SessionLineage = {
  schema?: string;
  operation?: 'fork' | 'merge';
  merge_mode?: 'direct' | 'summary' | 'dialogue';
  requested_mode?: 'auto' | 'direct' | 'summary' | 'dialogue';
  created_at?: number;
  parents?: Array<{
    name: string;
    session_id?: string;
    trace_id?: string;
    new_messages?: number;
  }>;
  common_base?: { messages?: number; audit_sha256?: string };
};

export async function forkSession(session: string, name?: string, workspace?: string) {
  return request("POST", `/api/session/${encodeURIComponent(session)}/fork`, { name, workspace });
}

export async function mergeSessions(options: {
  left: string;
  right: string;
  mode: 'auto' | 'direct' | 'summary' | 'dialogue';
  name?: string;
  threshold_tokens?: number;
  dialogue_rounds?: number;
  target_workspace?: string;
}) {
  return request("POST", "/api/sessions/merge", options);
}

export async function getSessionLineage(session: string): Promise<{ session: string; lineage: SessionLineage }> {
  return request("GET", `/api/session/${encodeURIComponent(session)}/lineage`);
}

// ============ Task Bench ============

export async function listTaskBenchTasks() {
  return request("GET", "/api/task-bench/tasks");
}

export async function getTaskBenchOptions() {
  return request("GET", "/api/task-bench/options");
}

export async function listTaskBenchRuns() {
  return request("GET", "/api/task-bench/runs");
}

export async function getTaskBenchRun(runId: string) {
  return request("GET", `/api/task-bench/runs/${encodeURIComponent(runId)}`);
}

export async function startTaskBenchRun(payload: {
  task_id: string;
  harness: string;
  identity: string;
  environments: string[];
  slot_bindings: Record<string, string>;
  debug_mode: 'auto' | 'paused';
  ide_context?: Array<{ kind: 'file' | 'selection'; path: string; relativePath?: string; language?: string; startLine?: number; endLine?: number; content: string }>;
}) {
  return request("POST", "/api/task-bench/runs", payload);
}

export async function controlTaskBenchRun(runId: string, action: 'pause' | 'step' | 'auto' | 'stop') {
  return request("POST", `/api/task-bench/runs/${encodeURIComponent(runId)}/control`, { action });
}

export async function sendTaskBenchInput(runId: string, text: string) {
  return request("POST", `/api/task-bench/runs/${encodeURIComponent(runId)}/input`, { text });
}

export async function getTaskBenchCompatibility() {
  return request("GET", "/api/task-bench/compatibility");
}

export async function importTaskBenchTask(source: string, overwrite = false) {
  return request("POST", "/api/task-bench/import", { source, overwrite });
}

export async function exportTaskBenchHarbor(taskId: string, destination?: string) {
  return request("POST", "/api/task-bench/export-harbor", { task_id: taskId, destination });
}

// ============ Product setup and diagnostics ============

export async function getProductSettings() {
  return request("GET", "/api/product/settings");
}

export async function saveProductSettings(settings: Record<string, unknown>) {
  return request("POST", "/api/product/settings", settings);
}

export async function getProductDiagnostics() {
  return request("GET", "/api/product/diagnostics");
}

export async function createDiagnosticsBundle() {
  return request("POST", "/api/product/diagnostics-bundle", {});
}

export async function configureProductProvider(payload: Record<string, unknown>) {
  return request("POST", "/api/product/provider", payload);
}

export async function listProductRollbacks() {
  return request("GET", "/api/product/rollbacks");
}

export async function applyProductUpdate(archive: string) {
  return request("POST", "/api/product/update", { archive });
}

export async function rollbackProductUpdate(id: string) {
  return request("POST", "/api/product/rollback", { id });
}

// ============ EgoIR ============

export async function getEgoIRGuide() { return request("GET", "/api/egoir/guide"); }
export async function loadEgoIR(name: string) { return request("GET", `/api/egoir/harness/${encodeURIComponent(name)}`); }
export async function validateEgoIR(text: string) { return request("POST", "/api/egoir/validate", { text }); }
export async function createEgoIR(text: string, dryRun = false) { return request("POST", "/api/egoir/create", { text, dry_run: dryRun }); }
export async function patchEgoIR(name: string, payload: Record<string, unknown>) { return request("POST", `/api/egoir/harness/${encodeURIComponent(name)}/patch`, payload); }
export async function rollbackEgoIR(transactionId: string, expectedRevision?: string) { return request("POST", "/api/egoir/rollback", { transaction_id: transactionId, expected_revision: expectedRevision }); }

// ============ Proof-carrying evolution ============

export async function listEvolutionProposals() { return request("GET", "/api/evolution/proposals"); }
export async function selectEvolutionArtifact(candidates: Array<Record<string, unknown>>, minimumUtility = 0.08) { return request("POST", "/api/evolution/select-artifact", { candidates, minimum_utility: minimumUtility }); }
export async function selectEmpiricalEvolutionArtifact(candidates: Array<Record<string, unknown>>) { return request("POST", "/api/evolution/select-artifact/empirical", { candidates }); }
export async function issueEvolutionCertificate(payload: Record<string, unknown>) { return request("POST", "/api/evolution/certificates/issue", payload); }
export async function registerEvolutionProposal(proposal: Record<string, unknown>, heldoutIds: string[] = []) { return request("POST", "/api/evolution/proposals", { proposal, heldout_ids: heldoutIds }); }
export async function applyEvolutionProposal(id: string, dryRun = false, humanApproved = false) { return request("POST", `/api/evolution/proposals/${encodeURIComponent(id)}/apply`, { dry_run: dryRun, human_approved: humanApproved }); }
export async function gateEvolutionProposal(id: string, baseline: Record<string, unknown>, candidate: Record<string, unknown>, humanApproved = false) { return request("POST", `/api/evolution/proposals/${encodeURIComponent(id)}/gate`, { baseline, candidate, human_approved: humanApproved }); }

export async function loadHarnessBlueprint(name: string) {
  return request("GET", `/api/harness/${encodeURIComponent(name)}/blueprint`);
}

export async function patchHarnessBlueprint(payload: {
  harness_name: string;
  operations: Record<string, unknown>[];
  expected_revision: string;
  reason?: string;
  dry_run?: boolean;
}) {
  return request("POST", "/api/harness-blueprint/patch", payload);
}

export async function analyzeCapabilityEvolution(observations: unknown, workspace = '') {
  return request("POST", "/api/evolution/capabilities/analyze", { observations, workspace });
}

export async function inspectCapabilityEvolution(identity: string) {
  return request("POST", "/api/evolution/capabilities/inspect", { identity });
}

export async function installCapabilityEvolution(identity: string, pack: string, dryRun: boolean, reason = '') {
  return request("POST", "/api/evolution/capabilities/install", { identity, pack, dry_run: dryRun, reason });
}

export async function rollbackCapabilityEvolution(transactionId: string) {
  return request("POST", "/api/evolution/capabilities/rollback", { transaction_id: transactionId });
}

// ============ File checkpoints ============

export async function getWorkspace() {
  const query = WORKSPACE ? `?workspace=${encodeURIComponent(WORKSPACE)}` : "";
  return request("GET", `/api/workspace${query}`);
}

export async function listCheckpoints(workspace = "") {
  const query = workspace ? `?workspace=${encodeURIComponent(workspace)}` : "";
  return request("GET", `/api/checkpoints${query}`);
}

export async function getCheckpoint(checkpointId: string) {
  return request("GET", `/api/checkpoints/${encodeURIComponent(checkpointId)}`);
}

export async function createCheckpoint(payload: {
  label: string;
  workspace: string;
  files: string[];
  metadata?: Record<string, unknown>;
}) {
  return request("POST", "/api/checkpoints/create", payload);
}

export async function previewCheckpointRestore(checkpointId: string, files?: string[]) {
  return request("POST", "/api/checkpoints/preview", { checkpoint_id: checkpointId, files });
}

export async function restoreCheckpoint(payload: {
  checkpoint_id: string;
  files: string[];
  expected_revisions: Record<string, string>;
  confirm_delete?: boolean;
}) {
  const response = await fetch(`${BASE}/api/checkpoints/rollback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({ error: response.statusText }));
  return { ...data, http_status: response.status };
}

// ============ Role-aware model profiles ============

export async function getModelProfiles() {
  return request("GET", "/api/model-profiles");
}

export async function saveModelProfile(profile: Record<string, unknown>) {
  return request("POST", "/api/model-profiles", profile);
}

export async function deleteModelProfile(profileId: string) {
  return request("DELETE", `/api/model-profiles/${encodeURIComponent(profileId)}`);
}

export async function assignModelRole(role: string, profiles: string[]) {
  return request("POST", "/api/model-roles", { role, profiles });
}

export async function previewModelRoute(payload: {
  role: string;
  context_tokens?: number;
  expected_output_tokens?: number;
  run_id?: string;
}) {
  return request("POST", "/api/model-route/preview", payload);
}

// ============ Model provider diagnostics ============

export async function getAIStatus() {
  return request("GET", "/api/ai/status");
}

export async function probeAIProvider() {
  return request("POST", "/api/ai/probe", {});
}

// ============ Reproducible research ============

export async function getHarnessConformance() {
  return request("GET", "/api/research/conformance");
}

export async function runHarnessConformance(behavioral = false, only: string[] = []) {
  return request("POST", "/api/research/conformance/run", { behavioral, only });
}

export async function getTranslationBenchmark() {
  return request("GET", "/api/research/translation-benchmark");
}

export async function scoreHarnessTranslation(contractId: string, candidate: string) {
  return request("POST", "/api/research/translation-benchmark/score", { contract_id: contractId, candidate });
}

export async function listScienceProjects() {
  return request("GET", "/api/science/projects");
}

export async function createScienceProject(objective: string, creator: string, projectId?: string) {
  return request("POST", "/api/science/projects", { objective, creator, project_id: projectId });
}

export async function getScienceProject(projectId: string) {
  return request("GET", `/api/science/projects/${encodeURIComponent(projectId)}`);
}

export async function addScienceArtifact(projectId: string, path: string, kind: string, actor: string) {
  return request("POST", `/api/science/projects/${encodeURIComponent(projectId)}/artifacts`, { path, kind, actor });
}

export async function addScienceSource(projectId: string, url: string, title: string, actor: string, snapshotArtifact?: string) {
  return request("POST", `/api/science/projects/${encodeURIComponent(projectId)}/sources`, { url, title, actor, snapshot_artifact: snapshotArtifact });
}

export async function submitScienceStage(projectId: string, stage: string, actor: string, payload: Record<string, unknown>, expectedRevision: number) {
  return request("POST", `/api/science/projects/${encodeURIComponent(projectId)}/stages`, { stage, actor, payload, expected_revision: expectedRevision });
}

export async function auditScienceProject(projectId: string) {
  return request("GET", `/api/science/projects/${encodeURIComponent(projectId)}/audit`);
}

export function hasWebSocket(): boolean {
  return _ws !== null && _ws.readyState === WebSocket.OPEN;
}

export function sendInputViaWs(text: string, runId?: string) {
  console.log("[sendInputViaWs] text:", text, "ws:", _ws, "readyState:", _ws?.readyState);
  if (_ws && _ws.readyState === WebSocket.OPEN) {
    _ws.send(JSON.stringify({ type: "input", text, run_id: runId, workspace: WORKSPACE || undefined }));
    console.log("[sendInputViaWs] sent successfully via WS");
  } else {
    console.warn("[sendInputViaWs] WebSocket not open, falling back to HTTP POST");
    fetch(`${BASE}/api/execution/input`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, run_id: runId, workspace: WORKSPACE || undefined }),
    }).catch((e) => console.error("[sendInputViaWs] HTTP fallback failed:", e));
  }
}

export function subscribeExecution(callback: (msg: any) => void): () => void {
  _wsCallbacks.push(callback);

  const connect = () => {
    if (_ws && _ws.readyState === WebSocket.OPEN) return;
    _ws = new WebSocket(WS_BASE);

    _ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        for (const cb of _wsCallbacks) {
          cb(msg);
        }
      } catch {}
    };

    _ws.onclose = () => {
      _ws = null;
      setTimeout(connect, 2000);
    };
  };

  connect();

  return () => {
    _wsCallbacks = _wsCallbacks.filter((c) => c !== callback);
  };
}
