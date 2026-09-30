import type { DagNodeContract, DagPortSpec } from './components/DagFormEditors';
import type { PipelineNode } from './types';

export const FLOW_INPUT_HANDLE = 'flow';
export const EVENT_PREFIX = 'event:';
export const INPUT_PREFIX = 'input:';
export const OUTPUT_PREFIX = 'output:';

export type SocketClass = 'flow' | 'event' | 'input' | 'output' | 'unknown';

export type SocketDescriptor = {
  id: string;
  name: string;
  type: string;
  socketClass: SocketClass;
  required?: boolean;
  multiple?: boolean;
};

export function parseSocketHandle(handle: string | null | undefined): { socketClass: SocketClass; name: string } {
  const value = String(handle || '');
  if (!value || value === FLOW_INPUT_HANDLE) return { socketClass: 'flow', name: 'flow' };
  if (value.startsWith(EVENT_PREFIX)) return { socketClass: 'event', name: value.slice(EVENT_PREFIX.length) };
  if (value.startsWith(INPUT_PREFIX)) return { socketClass: 'input', name: value.slice(INPUT_PREFIX.length) };
  if (value.startsWith(OUTPUT_PREFIX)) return { socketClass: 'output', name: value.slice(OUTPUT_PREFIX.length) };
  return { socketClass: 'unknown', name: value };
}

function unique(names: Iterable<string>): string[] {
  return [...new Set([...names].filter(Boolean))];
}

function descriptor(name: string, socketClass: SocketClass, spec?: DagPortSpec): SocketDescriptor {
  const prefix = socketClass === 'event' ? EVENT_PREFIX : socketClass === 'input' ? INPUT_PREFIX : OUTPUT_PREFIX;
  return {
    id: `${prefix}${name}`,
    name,
    type: spec?.type || (socketClass === 'event' ? 'control' : 'any'),
    socketClass,
    required: spec?.required,
    multiple: spec?.multiple,
  };
}

export function socketsForNode(node: PipelineNode, contract?: DagNodeContract): {
  inputs: SocketDescriptor[];
  outputs: SocketDescriptor[];
} {
  const inputNames = unique([
    ...Object.keys(contract?.inputs || {}),
    ...Object.keys(node.inputs || {}),
    ...Object.keys(node.component_inputs || {}),
  ]);
  const outputNames = unique([
    ...Object.keys(contract?.outputs || {}),
    ...Object.keys(node.outputs || {}),
    ...Object.keys(node.component_outputs || {}),
    ...((node as any)._edgeOutputs || []),
  ]);
  const eventNames = unique([
    ...(contract?.events || []),
    ...((node.edges || []).map((edge) => String(edge.source_port || edge.condition || 'default'))),
    ...((node as any)._edgeEvents || []),
  ]);

  return {
    inputs: inputNames.map((name) => descriptor(name, 'input', contract?.inputs?.[name])),
    outputs: [
      ...eventNames.map((name) => descriptor(name, 'event')),
      ...outputNames.map((name) => descriptor(name, 'output', contract?.outputs?.[name])),
    ],
  };
}

export function portTypesCompatible(sourceType: string, targetType: string): boolean {
  const left = String(sourceType || 'any').toLowerCase();
  const right = String(targetType || 'any').toLowerCase();
  if (left === 'any' || right === 'any' || left === right) return true;
  if (left === 'integer' && right === 'number') return true;
  if (left === 'string' && right === 'message') return true;
  if (left === 'message' && right === 'string') return true;
  if (left === 'json' && ['messages', 'tool_calls'].includes(right)) return true;
  return false;
}

export function socketType(node: PipelineNode | undefined, contract: DagNodeContract | undefined, handle: string | null | undefined): string {
  const parsed = parseSocketHandle(handle);
  if (parsed.socketClass === 'flow' || parsed.socketClass === 'event') return 'control';
  const sockets = socketsForNode(node || ({ id: '', op: '数据', edges: [] } as PipelineNode), contract);
  return [...sockets.inputs, ...sockets.outputs].find((socket) => socket.id === handle)?.type || 'any';
}
