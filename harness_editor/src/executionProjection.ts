import type { NodeTrace } from './types';

export type SubHarnessMessage = {
  agent: string;
  text: string;
  tools: Array<{ name: string; result: string }>;
};

export type SubHarnessData = {
  harness_id: string;
  harness_name: string;
  slots: Record<string, string>;
  messages: SubHarnessMessage[];
  status: 'running' | 'completed';
};

export type ChatMessage = {
  id: number;
  agent: string;
  text: string;
  tools: Array<{ name: string; result: string }>;
  blocked: Array<{ name: string; reason: string }>;
  sub_harness?: SubHarnessData;
};

export type PendingStreamToken = {
  kind: 'main' | 'sub';
  nodeId?: string;
  harnessId?: string;
  agent: string;
  text: string;
};

export function renderTraceValue(value: unknown): string {
  if (value === undefined || value === null || value === '') return '—';
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

export function updateLatestTrace(
  traces: NodeTrace[], nodeId: string | undefined, updater: (trace: NodeTrace) => NodeTrace,
): NodeTrace[] {
  if (!nodeId) return traces;
  for (let index = traces.length - 1; index >= 0; index--) {
    if (traces[index].node_id === nodeId) {
      return traces.map((trace, itemIndex) => itemIndex === index ? updater(trace) : trace);
    }
  }
  return traces;
}

export function stripEventEnvelope(data: Record<string, unknown>): Record<string, unknown> {
  const { run_id: _runId, node_id: _nodeId, ...payload } = data;
  return payload;
}

export function appendTraceTokenBatch(traces: NodeTrace[], tokens: PendingStreamToken[]): NodeTrace[] {
  const chunks = new Map<string, string>();
  tokens.forEach((token) => {
    if (token.kind === 'main' && token.nodeId && token.text) {
      chunks.set(token.nodeId, `${chunks.get(token.nodeId) || ''}${token.text}`);
    }
  });
  if (chunks.size === 0) return traces;
  const latestIndexes = new Map<string, number>();
  for (let index = traces.length - 1; index >= 0 && latestIndexes.size < chunks.size; index--) {
    const nodeId = traces[index].node_id;
    if (chunks.has(nodeId) && !latestIndexes.has(nodeId)) latestIndexes.set(nodeId, index);
  }
  return traces.map((trace, index) => {
    const chunk = chunks.get(trace.node_id);
    if (!chunk || latestIndexes.get(trace.node_id) !== index) return trace;
    return { ...trace, model: { ...trace.model, response: `${trace.model.response || ''}${chunk}` } };
  });
}

export function appendMessageTokenBatch(
  messages: ChatMessage[], tokens: PendingStreamToken[], nextId: () => number,
): ChatMessage[] {
  if (tokens.length === 0) return messages;
  const updated = [...messages];
  tokens.forEach((token) => {
    if (token.kind === 'main') {
      const last = updated[updated.length - 1];
      if (last && last.agent === token.agent && last.tools.length === 0 && last.blocked.length === 0 && !last.sub_harness) {
        updated[updated.length - 1] = { ...last, text: `${last.text}${token.text}` };
      } else {
        updated.push({ id: nextId(), agent: token.agent, text: token.text, tools: [], blocked: [] });
      }
      return;
    }
    for (let index = updated.length - 1; index >= 0; index--) {
      const subHarness = updated[index].sub_harness;
      if (!subHarness || subHarness.harness_id !== token.harnessId) continue;
      const subMessages = [...subHarness.messages];
      const last = subMessages[subMessages.length - 1];
      if (last && last.agent === token.agent && last.tools.length === 0) {
        subMessages[subMessages.length - 1] = { ...last, text: `${last.text}${token.text}` };
      } else {
        subMessages.push({ agent: token.agent, text: token.text, tools: [] });
      }
      updated[index] = { ...updated[index], sub_harness: { ...subHarness, messages: subMessages } };
      break;
    }
  });
  return updated;
}

export function traceSnapshotSignature(traces: NodeTrace[] | undefined): string {
  if (!traces?.length) return '0';
  const last = traces[traces.length - 1];
  return [
    traces.length, last.sequence, last.status,
    typeof last.model?.response === 'string' ? last.model.response.length : 0,
    last.tools?.length || 0, last.completed_at || 0,
  ].join(':');
}
