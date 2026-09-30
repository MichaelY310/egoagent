import type { HarnessConfig, TaskRunEvent } from './types';

export type RuntimeRunStatus = 'starting' | 'running' | 'completed' | 'failed' | 'cancelled';

export type RuntimeRunView = {
  runId: string;
  parentRunId?: string;
  parentNodeId?: string;
  harness: string;
  slots: Record<string, string>;
  status: RuntimeRunStatus;
  currentNode?: string;
  nodeCalls: number;
  modelCalls: number;
  toolCalls: number;
  lastActivity: string;
  startedAt: number;
  completedAt?: number;
};

export type RuntimeStoryEvent = {
  id: string;
  type: 'run' | 'subagent' | 'mutation' | 'approval' | 'error';
  title: string;
  detail: string;
  time: number;
  tone: 'live' | 'good' | 'warn' | 'bad' | 'neutral';
};

export type FlowGraphDiff = {
  addedNodes: string[];
  removedNodes: string[];
  changedNodes: string[];
  addedEdges: string[];
  removedEdges: string[];
};

function preview(value: unknown, limit = 180): string {
  if (value == null || value === '') return '';
  let text = '';
  try { text = typeof value === 'string' ? value : JSON.stringify(value); } catch { text = String(value); }
  text = text.replace(/\s+/g, ' ').trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function parseObject(value: unknown): Record<string, any> {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, any>;
  if (typeof value !== 'string') return {};
  const text = value.trim();
  if (!text.startsWith('{')) return {};
  try {
    const parsed = JSON.parse(text);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

export function runtimeEventBelongsToRoot(
  data: Record<string, any>, rootRunId: string, knownRunIds: ReadonlySet<string>,
): boolean {
  const runId = String(data.run_id || '');
  const parentRunId = String(data.parent_run_id || '');
  return Boolean(
    rootRunId && (
      runId === rootRunId ||
      knownRunIds.has(runId) ||
      parentRunId === rootRunId ||
      knownRunIds.has(parentRunId)
    )
  );
}

export function reduceRuntimeRunEvent(
  runs: RuntimeRunView[], eventType: string, data: Record<string, any>, now = Date.now(),
): RuntimeRunView[] {
  const runId = String(data.run_id || '');
  if (!runId) return runs;
  const index = runs.findIndex((run) => run.runId === runId);
  const existing: RuntimeRunView = index >= 0 ? runs[index] : {
    runId,
    parentRunId: String(data.parent_run_id || '') || undefined,
    parentNodeId: String(data.node_id || '') || undefined,
    harness: String(data.harness || data.subflow || 'child flow'),
    slots: data.slots && typeof data.slots === 'object' ? data.slots : {},
    status: 'starting',
    nodeCalls: 0,
    modelCalls: 0,
    toolCalls: 0,
    lastActivity: '正在创建运行上下文…',
    startedAt: now,
  };
  const next = { ...existing };
  if (data.parent_run_id) next.parentRunId = String(data.parent_run_id);
  if (!next.parentNodeId && data.node_id) next.parentNodeId = String(data.node_id);
  if (eventType === 'run_started') {
    next.harness = String(data.harness || data.subflow || next.harness);
    next.slots = data.slots && typeof data.slots === 'object' ? data.slots : next.slots;
    next.status = 'running';
    next.lastActivity = `从 ${String(data.start || 'start')} 开始`;
  } else if (eventType === 'node_enter') {
    next.status = 'running';
    next.currentNode = String(data.node_id || next.currentNode || '');
    next.nodeCalls += 1;
    next.lastActivity = `${String(data.op || '节点')} · ${next.currentNode}`;
  } else if (eventType === 'model_request') {
    next.modelCalls += 1;
    next.lastActivity = `模型正在处理 ${String(data.node_id || next.currentNode || '')}`.trim();
  } else if (eventType === 'token' || eventType === 'sub_token') {
    const token = preview(data.text, 90);
    if (token) next.lastActivity = `${next.lastActivity.startsWith('模型输出') ? next.lastActivity : '模型输出 · '}${token}`.slice(-180);
  } else if (eventType === 'model_response') {
    next.lastActivity = preview(data.text) || '模型响应完成';
  } else if (eventType === 'tool' || eventType === 'sub_tool') {
    next.toolCalls += 1;
    next.lastActivity = `工具 ${String(data.name || data.tool || '')} · ${preview(data.result, 110)}`;
  } else if (eventType === 'done' || eventType === 'run_completed' || eventType === 'subagent_completed') {
    next.status = 'completed';
    next.completedAt = now;
    next.lastActivity = preview(data.result) || '运行完成';
  } else if (eventType === 'cancelled') {
    next.status = 'cancelled';
    next.completedAt = now;
    next.lastActivity = preview(data.message) || '运行已停止';
  } else if (eventType === 'error' || eventType === 'subagent_failed') {
    next.status = 'failed';
    next.completedAt = now;
    next.lastActivity = preview(data.error || data.message) || '运行失败';
  }
  const updated = [...runs];
  if (index >= 0) updated[index] = next;
  else updated.push(next);
  return updated.slice(-80);
}

function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${key}:${stable(item)}`).join(',')}}`;
  return JSON.stringify(value);
}

function graphEdges(config: HarnessConfig): Set<string> {
  const result = new Set<string>();
  Object.entries(config.pipeline?.nodes || {}).forEach(([source, node]) => {
    (node.edges || []).forEach((edge) => result.add(`${source}:${edge.condition || 'default'}→${edge.to || 'END'}`));
  });
  return result;
}

export function diffFlowGraphs(before: HarnessConfig, after: HarnessConfig): FlowGraphDiff {
  const beforeNodes = before.pipeline?.nodes || {};
  const afterNodes = after.pipeline?.nodes || {};
  const beforeIds = new Set(Object.keys(beforeNodes));
  const afterIds = new Set(Object.keys(afterNodes));
  const beforeEdges = graphEdges(before);
  const afterEdges = graphEdges(after);
  return {
    addedNodes: [...afterIds].filter((id) => !beforeIds.has(id)).sort(),
    removedNodes: [...beforeIds].filter((id) => !afterIds.has(id)).sort(),
    changedNodes: [...afterIds].filter((id) => beforeIds.has(id) && stable(beforeNodes[id]) !== stable(afterNodes[id])).sort(),
    addedEdges: [...afterEdges].filter((edge) => !beforeEdges.has(edge)).sort(),
    removedEdges: [...beforeEdges].filter((edge) => !afterEdges.has(edge)).sort(),
  };
}

export function normalizeMutationPayload(data: Record<string, any>): Record<string, any> {
  const result = parseObject(data.result);
  const args = parseObject(data.arguments);
  const blueprint = result.blueprint && typeof result.blueprint === 'object' ? result.blueprint : {};
  const operations = Array.isArray(data.operations) ? data.operations : Array.isArray(args.operations) ? args.operations : [];
  const addedNodes = operations.filter((operation: any) => operation?.op === 'add_step').map((operation: any) => String(operation.step?.id || operation.id || '')).filter(Boolean);
  const removedNodes = operations.filter((operation: any) => operation?.op === 'remove_step').map((operation: any) => String(operation.id || operation.step_id || '')).filter(Boolean);
  const changedNodes = operations.filter((operation: any) => ['update_step', 'replace_step', 'set_fields'].includes(operation?.op)).map((operation: any) => String(operation.id || operation.step_id || '')).filter(Boolean);
  const addedEdges = operations.filter((operation: any) => operation?.op === 'connect').map((operation: any) => `${operation.from || '?'}:${operation.condition || 'default'}→${operation.to || '?'}`);
  const removedEdges = operations.filter((operation: any) => operation?.op === 'disconnect').map((operation: any) => `${operation.from || '?'}:${operation.condition || 'default'}→${operation.to || '?'}`);
  return {
    target: String(data.harness || result.harness || result.name || args.harness_name || blueprint.name || ''),
    action: String(data.action || result.action || args.action || 'update'),
    revision: String(data.revision || result.revision || result.revision_after || ''),
    transactionId: String(data.transaction_id || result.transaction_id || ''),
    diff: data.diff ?? result.diff,
    nodes: data.nodes || result.current_nodes || blueprint.steps?.map((step: any) => step.id),
    operations,
    addedNodes,
    removedNodes,
    changedNodes,
    addedEdges,
    removedEdges,
    raw: Object.keys(result).length ? result : data,
  };
}

export function deriveRuntimeRuns(events: TaskRunEvent[]): RuntimeRunView[] {
  let runs: RuntimeRunView[] = [];
  (events || []).forEach((event) => { runs = reduceRuntimeRunEvent(runs, event.type, event.data || {}, event.time * 1000); });
  return runs;
}

export function storyEvent(eventType: string, data: Record<string, any>, now = Date.now()): RuntimeStoryEvent | null {
  const id = `${eventType}:${String(data.run_id || data.invocation_id || data.transaction_id || now)}:${now}`;
  if (eventType === 'subagent_spawned' || eventType === 'subagent.spawned') return {
    id, type: 'subagent', title: `创建子 Agent · ${String(data.child_harness || data.harness || '')}`,
    detail: `${String(data.purpose || 'subflow')} · ${Object.entries(data.identity_bindings || {}).map(([slot, identity]) => `${slot}=${identity}`).join(', ')}`,
    time: now, tone: 'live',
  };
  if (eventType === 'subagent_completed' || eventType === 'subagent.completed') return {
    id, type: 'subagent', title: `子 Agent 完成 · ${String(data.child_harness || data.harness || '')}`,
    detail: preview(data.result) || '结果已返回父 Flow', time: now, tone: 'good',
  };
  if (eventType === 'subagent_failed' || eventType === 'subagent.failed') return {
    id, type: 'error', title: `子 Agent 失败 · ${String(data.child_harness || data.harness || '')}`,
    detail: preview(data.error), time: now, tone: 'bad',
  };
  if (eventType === 'approval_required') return {
    id, type: 'approval', title: '等待人类批准', detail: preview(data.prompt || data.reason), time: now, tone: 'warn',
  };
  if (eventType === 'approval') return {
    id, type: 'approval', title: `审批${data.decision === 'approved' ? '通过' : '拒绝'}`,
    detail: preview(data.message), time: now, tone: data.decision === 'approved' ? 'good' : 'warn',
  };
  if (eventType === 'harness_mutation' || eventType === 'identity_evolution' || eventType === 'agent_system_created') {
    const mutation = normalizeMutationPayload(data);
    return {
      id, type: 'mutation', title: eventType === 'agent_system_created' ? '创建可复用 Agent' : eventType === 'identity_evolution' ? 'Identity 能力进化' : 'Flow 结构已改变',
      detail: `${mutation.target || data.identity || ''}${mutation.action ? ` · ${mutation.action}` : ''}`,
      time: now, tone: 'good',
    };
  }
  return null;
}
