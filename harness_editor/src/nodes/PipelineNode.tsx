import { memo, useEffect } from 'react';
import { Handle, Position, useUpdateNodeInternals, type NodeProps } from '@xyflow/react';
import type { PipelineNode } from '../types';
import type { NodeTrace } from '../types';
import type { DagNodeContract } from '../components/DagFormEditors';
import { FLOW_INPUT_HANDLE, socketsForNode } from '../graphSockets';

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

function PipelineNodeComponent({ id, data, isConnectable }: NodeProps) {
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
  const mutationState = String((data as any)._mutationState || '');
  const expanded = Boolean((data as any)._expanded);
  const liveActivity = activity(runtimeTrace, runtimePaused);
  const liveMetrics = metrics(runtimeTrace);
  const sockets = socketsForNode(node, contract);
  const updateNodeInternals = useUpdateNodeInternals();
  const socketSignature = `${sockets.inputs.map((socket) => socket.id).join('|')}::${sockets.outputs.map((socket) => socket.id).join('|')}::${expanded}`;
  useEffect(() => {
    updateNodeInternals(id);
  }, [id, socketSignature, updateNodeInternals]);
  const summary = node.agent ? `@${node.agent}`
    : node.condition ? `if ${compact(node.condition, 42)}`
      : node.prompt ? compact(node.prompt, 48)
        : node.command != null ? compact(node.command, 48)
          : node.script ? `${node.script}.py`
            : node.key ? `${node.action || 'set'} ${node.key}`
              : node.id;
  const configPreview = Object.fromEntries(
    Object.entries(node as unknown as Record<string, unknown>).filter(([key]) => !key.startsWith('_') && ![
      'highlight', 'subHarness', 'runtimeStatus', 'runtimeCount', 'runtimeTrace', 'runtimeActivityMode', 'runtimePaused',
    ].includes(key)),
  );

  return (
    <div className={`pipeline-node ${config.cssClass}${expanded ? ' expanded' : ' compact'}${highlight}${subHarness ? ' sub-harness-active' : ''}${runtimeStatus ? ` runtime-${runtimeStatus}` : ''}${mutationState ? ` mutation-${mutationState}` : ''}`} data-node-id={node.id} data-op={node.op} title={expanded ? '点击画布空白处收起' : '双击展开完整节点内容'}>
      <div className="node-header">
        <span className="node-icon">{config.icon}</span>
        <span className="node-title">{config.label}<small>{node.id}</small></span>
      </div>
      {!expanded && <div className="node-compact-summary">{summary}</div>}
      <div className="node-socket-columns" aria-label="节点输入与输出">
        <div className="node-socket-list inputs" aria-label="输入 sockets">
          <div className="node-socket-row control input" title="控制流入口；可接收多个事件路径">
            <Handle id={FLOW_INPUT_HANDLE} type="target" position={Position.Left} isConnectable={isConnectable} className="tutorial-target-handle socket-control" data-socket-id={FLOW_INPUT_HANDLE} />
            <span>flow</span><small>控制</small>
          </div>
          {sockets.inputs.map((socket) => <div key={socket.id} className="node-socket-row data input" title={`${socket.name}: ${socket.type}${socket.required ? ' · 必填' : ''}`}>
            <Handle id={socket.id} type="target" position={Position.Left} isConnectable={isConnectable} className="socket-data" data-socket-id={socket.id} />
            <span>{socket.name}</span><small>{socket.type}{socket.required ? ' *' : ''}</small>
          </div>)}
        </div>
        <div className="node-socket-list outputs" aria-label="输出 sockets">
          {sockets.outputs.map((socket) => <div key={socket.id} className={`node-socket-row ${socket.socketClass} output`} title={`${socket.name}: ${socket.type}`}>
            <span>{socket.name}</span><small>{socket.type === 'control' ? '事件' : socket.type}</small>
            <Handle id={socket.id} type="source" position={Position.Right} isConnectable={isConnectable} className={socket.socketClass === 'event' ? 'tutorial-source-handle socket-control' : 'socket-data'} data-socket-id={socket.id} />
          </div>)}
        </div>
      </div>
      {expanded && <div className="node-expanded-content">
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
      </div>}
      {runtimeStatus && (
        <div className={`node-runtime-badge ${runtimeStatus}`}>
          {runtimeStatus === 'running' ? '运行中' : runtimeStatus === 'completed' || runtimeStatus === 'ok' ? '已完成' : runtimeStatus === 'error' ? '失败' : '待执行'}
          {runtimeCount > 1 ? ` ×${runtimeCount}` : ''}
        </div>
      )}
      {mutationState && <div className={`node-mutation-badge ${mutationState}`}>{mutationState === 'added' ? '＋ 新节点' : '↗ 已改变'}</div>}
      {runtimeActivityMode && liveActivity && (expanded || runtimeActivityMode === 'active') && (
        <div className={`node-activity-card ${runtimeActivityMode}${runtimePaused ? ' paused' : ''}`}>
          <div className="node-activity-phase"><span>{liveActivity.icon}</span><b>{liveActivity.phase}</b>{runtimeCount > 1 && <em>#{runtimeCount}</em>}</div>
          <p>{liveActivity.text}</p>
          {liveMetrics.length > 0 && <div className="node-activity-metrics">{liveMetrics.map((metric) => <span key={metric}>{metric}</span>)}</div>}
          {runtimeActivityMode === 'active' && <small>点击节点查看完整输入 / 输出 / 工具</small>}
        </div>
      )}
      {runtimeActivityMode === 'recent' && liveActivity && !expanded && <div className="node-runtime-summary"><span>{liveActivity.icon}</span>{liveActivity.phase}</div>}
      {expanded && <>
        <details className="node-config-preview"><summary>完整节点配置</summary><pre>{JSON.stringify(configPreview, null, 2)}</pre></details>
      </>}
    </div>
  );
}

export default memo(PipelineNodeComponent);
