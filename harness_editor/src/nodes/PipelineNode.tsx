import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { PipelineNode } from '../types';
import type { NodeTrace } from '../types';
import type { DagNodeContract } from '../components/DagFormEditors';

const NODE_CLASS_BY_PALETTE_CLASS: Record<string, string> = {
  'dnd-wait': 'node-wait-input',
  'dnd-infer': 'node-infer',
  'dnd-exec': 'node-exec-tool',
  'dnd-tool': 'node-process-tool',
  'dnd-text': 'node-process-text',
  'dnd-llm': 'node-llm-call',
  'dnd-script': 'node-script',
};

function compact(value: unknown, limit = 150): string {
  if (value === undefined || value === null || value === '') return '';
  let text = '';
  if (typeof value === 'string') text = value;
  else {
    try { text = JSON.stringify(value); } catch { text = String(value); }
  }
  text = text.replace(/\s+/g, ' ').trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function activity(trace: NodeTrace | undefined, paused: boolean): { phase: string; text: string; icon: string } | null {
  if (!trace) return null;
  if (trace.error) return {
    phase: `${trace.error.type || '节点'}失败`,
    text: compact(trace.error.message) || '节点执行失败',
    icon: '×',
  };
  const latestTool = trace.tools?.[trace.tools.length - 1];
  if (latestTool) {
    return {
      phase: latestTool.blocked ? `工具被拦截 · ${latestTool.name}` : `工具 · ${latestTool.name}`,
      text: compact(latestTool.blocked ? latestTool.reason : latestTool.result) || '等待工具返回…',
      icon: latestTool.blocked ? '!' : '⚡',
    };
  }
  const response = compact(trace.model?.response);
  if (response) return { phase: paused ? '模型已暂停' : trace.status === 'completed' || trace.status === 'ok' ? '模型回复' : '模型正在输出', text: response, icon: '●' };
  if (trace.model?.request) return { phase: paused ? '模型调用前暂停' : '模型正在思考', text: compact(trace.model.request) || '已组装模型上下文', icon: '◌' };
  const output = compact(trace.output);
  if (output) return { phase: trace.status === 'error' ? '节点失败' : '节点输出', text: output, icon: trace.status === 'error' ? '×' : '✓' };
  const input = compact(trace.input || trace.last_output);
  return { phase: paused ? '执行前暂停' : trace.status === 'entered' ? '准备执行' : '运行中', text: input || '等待节点产生输出…', icon: paused ? 'Ⅱ' : '›' };
}

function metrics(trace: NodeTrace | undefined): string[] {
  if (!trace) return [];
  const result: string[] = [];
  if (trace.duration_ms != null) result.push(`${trace.duration_ms < 1000 ? Math.round(trace.duration_ms) + 'ms' : (trace.duration_ms / 1000).toFixed(1) + 's'}`);
  const input = Number(trace.usage?.input_tokens || 0);
  const output = Number(trace.usage?.output_tokens || 0);
  if (input || output) result.push(`${input + output} tok`);
  if (trace.usage?.cached_input_tokens) result.push(`${trace.usage.cached_input_tokens} cached`);
  const cost = Number(trace.stats?.cost_actual || trace.stats?.cost_estimated || 0);
  if (cost) result.push(`Σ$${cost.toFixed(5)}`);
  if (trace.retries?.length) result.push(`${trace.retries.length} retry`);
  if (trace.artifacts?.length) result.push(`${trace.artifacts.length} artifact`);
  return result;
}

function PipelineNodeComponent({ data }: NodeProps) {
  const node = data as unknown as PipelineNode;
  const contract = (data as any)._contract as DagNodeContract | undefined;
  const config = {
    icon: contract?.editor?.icon || '◇',
    cssClass: NODE_CLASS_BY_PALETTE_CLASS[contract?.editor?.css_class || ''] || 'node-process-tool',
    label: node.op,
  };
  const highlight = (data as any).highlight ? ' highlight' : '';
  const subHarness = (data as any).subHarness as string | undefined;
  const runtimeStatus = (data as any).runtimeStatus as string | undefined;
  const runtimeCount = Number((data as any).runtimeCount || 0);
  const runtimeTrace = (data as any).runtimeTrace as NodeTrace | undefined;
  const runtimeActivityMode = (data as any).runtimeActivityMode as 'active' | 'recent' | undefined;
  const runtimePaused = Boolean((data as any).runtimePaused);
  const liveActivity = activity(runtimeTrace, runtimePaused);
  const liveMetrics = metrics(runtimeTrace);
  const inputPorts = [...new Set([...Object.keys(contract?.inputs || {}), ...Object.keys(node.inputs || {})])];
  const outputPorts = [...new Set([...Object.keys(contract?.outputs || {}), ...Object.keys(node.outputs || {})])];

  return (
    <div className={`pipeline-node ${config.cssClass}${highlight}${subHarness ? ' sub-harness-active' : ''}${runtimeStatus ? ` runtime-${runtimeStatus}` : ''}`}>
      <Handle type="target" position={Position.Top} />
      <div className="node-header">
        <span className="node-icon">{config.icon}</span>
        <span className="node-title">{config.label}</span>
      </div>
      {inputPorts.length > 0 && <div className="node-port-strip inputs" aria-label="输入端口">{inputPorts.map((name) => <span key={name} title={`${name}: ${contract?.inputs?.[name]?.type || 'any'}`}><i />{name}<small>{contract?.inputs?.[name]?.type || ''}</small></span>)}</div>}
      {node.agent && <div className="node-agent">@{node.agent}</div>}
      {node.condition && <div className="node-prompt">if: {String(node.condition)}</div>}
      {node.key && <div className="node-prompt">{node.action || 'set'}: {node.key}</div>}
      {node.op === '数据' && !node.key && node.action && <div className="node-prompt">{node.action}</div>}
      {node.prompt && <div className="node-prompt">prompt: {node.prompt}</div>}
      {node.script && <div className="node-script-badge">{node.script}.py</div>}
      {node.command != null && <div className="node-prompt">process: {String(node.command)}</div>}
      {node.timeout_seconds && <div className="node-prompt">timeout: {node.timeout_seconds}s</div>}
      {node.op === '进程' && node.backend && node.backend !== 'local' && <div className="node-prompt">backend: {node.backend}</div>}
      {node.op === '子流程' && node.mode === 'port_graph' && <div className="node-prompt">端口事件图</div>}
      {subHarness && <div className="node-sub-harness-badge">子流程: {subHarness}</div>}
      {runtimeStatus && (
        <div className={`node-runtime-badge ${runtimeStatus}`}>
          {runtimeStatus === 'running' ? '运行中' : runtimeStatus === 'completed' || runtimeStatus === 'ok' ? '已完成' : runtimeStatus === 'error' ? '失败' : '待执行'}
          {runtimeCount > 1 ? ` ×${runtimeCount}` : ''}
        </div>
      )}
      {runtimeActivityMode && liveActivity && (
        <div className={`node-activity-card ${runtimeActivityMode}${runtimePaused ? ' paused' : ''}`}>
          <div className="node-activity-phase"><span>{liveActivity.icon}</span><b>{liveActivity.phase}</b>{runtimeCount > 1 && <em>#{runtimeCount}</em>}</div>
          <p>{liveActivity.text}</p>
          {liveMetrics.length > 0 && <div className="node-activity-metrics">{liveMetrics.map((metric) => <span key={metric}>{metric}</span>)}</div>}
          {runtimeActivityMode === 'active' && <small>点击节点查看完整输入 / 输出 / 工具</small>}
        </div>
      )}
      {outputPorts.length > 0 && <div className="node-port-strip outputs" aria-label="输出端口">{outputPorts.map((name) => <span key={name} title={`${name}: ${contract?.outputs?.[name]?.type || 'any'}`}><i />{name}<small>{contract?.outputs?.[name]?.type || ''}</small></span>)}</div>}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

export default memo(PipelineNodeComponent);
