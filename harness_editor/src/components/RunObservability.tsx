import { useMemo, useState } from 'react';
import type { NodeTrace } from '../types';

export interface ChangeEntry {
  timestamp: number;
  type: 'harness' | 'identity';
  target: string;
  action: string;
  field?: string;
  oldValue?: string;
  newValue?: string;
  nodes?: string[];
  pipelineStart?: string;
  diff?: unknown;
  revision?: string;
  transactionId?: string;
  addedNodes?: string[];
  removedNodes?: string[];
  changedNodes?: string[];
  addedEdges?: string[];
  removedEdges?: string[];
}

type ChildRun = {
  harness_id: string;
  harness_name: string;
  slots: Record<string, string>;
  status: 'running' | 'completed';
  messages: Array<{ agent: string; text: string; tools: Array<{ name: string; result: string }> }>;
};

type Props = {
  traces: NodeTrace[];
  childRuns: ChildRun[];
  mutations: ChangeEntry[];
  onSelectTrace: (sequence: number) => void;
  onOpenChanges: () => void;
};

function preview(value: unknown, limit = 110): string {
  if (value == null || value === '') return '';
  let text: string;
  try { text = typeof value === 'string' ? value : JSON.stringify(value); } catch { text = String(value); }
  text = text.replace(/\s+/g, ' ').trim();
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function traceSummary(trace: NodeTrace): string {
  if (trace.error?.message) return trace.error.message;
  const pressure = (trace.stats as any)?.context_compaction;
  if (pressure) return pressure.phase === 'compacted'
    ? `context: ${pressure.before_tokens_estimated || 0} → ${pressure.after_tokens_estimated || 0} tokens`
    : `context ${pressure.phase || 'pressure'}: ${pressure.rendered_tokens_estimated || 0} tokens`;
  const tool = trace.tools?.[trace.tools.length - 1];
  if (tool) return `${tool.blocked ? 'blocked' : 'tool'}: ${tool.name} · ${preview(tool.blocked ? tool.reason : tool.result)}`;
  if (trace.model?.response) return preview(trace.model.response);
  return preview(trace.output) || preview(trace.input) || '等待事件…';
}

export default function RunObservability({ traces, childRuns, mutations, onSelectTrace, onOpenChanges }: Props) {
  const [section, setSection] = useState<'timeline' | 'children' | 'mutations'>('timeline');
  const agents = useMemo(() => {
    const names = Array.from(new Set(traces.map((trace) => trace.agent || 'system')));
    return names.length ? names : ['system'];
  }, [traces]);
  const totals = useMemo(() => traces.reduce((sum, trace) => ({
    duration: sum.duration + Number(trace.duration_ms || 0),
    tokens: sum.tokens + Number(trace.usage?.input_tokens || 0) + Number(trace.usage?.output_tokens || 0),
    retries: sum.retries + Number(trace.retries?.length || 0),
    failures: sum.failures + (trace.status === 'error' ? 1 : 0),
  }), { duration: 0, tokens: 0, retries: 0, failures: 0 }), [traces]);
  const finalCost = Number(traces[traces.length - 1]?.stats?.cost_actual || traces[traces.length - 1]?.stats?.cost_estimated || 0);

  return (
    <section className="run-observability" aria-label="运行可观测性">
      <header className="observability-summary">
        <span>{traces.length} 节点调用</span><span>{totals.tokens} tokens</span>
        <span>{(totals.duration / 1000).toFixed(2)} s</span><span>{totals.retries} 重试</span>
        <span>${finalCost.toFixed(6)}</span>
        <span className={totals.failures ? 'bad' : ''}>{totals.failures} 失败</span>
      </header>
      <nav className="observability-tabs">
        <button className={section === 'timeline' ? 'active' : ''} onClick={() => setSection('timeline')}>时间线 / 泳道</button>
        <button className={section === 'children' ? 'active' : ''} onClick={() => setSection('children')}>子 Harness ({childRuns.length})</button>
        <button className={section === 'mutations' ? 'active' : ''} onClick={() => setSection('mutations')}>实时变更 ({mutations.length})</button>
      </nav>

      {section === 'timeline' && (
        <div className="observability-swimlanes" style={{ gridTemplateColumns: `44px repeat(${agents.length}, minmax(130px, 1fr))` }}>
          <div className="lane-corner">序号</div>
          {agents.map((agent) => <div className="lane-head" key={agent}>@{agent}</div>)}
          {traces.map((trace) => (
            <div className="lane-row" key={trace.sequence} style={{ gridColumn: `1 / span ${agents.length + 1}`, gridTemplateColumns: `44px repeat(${agents.length}, minmax(130px, 1fr))` }}>
              <div className="lane-sequence">#{trace.sequence}</div>
              {agents.map((agent) => trace.agent === agent || (!trace.agent && agent === 'system') ? (
                <button key={agent} className={`lane-event ${trace.status}`} onClick={() => onSelectTrace(trace.sequence)}>
                  <b>{trace.node_id}</b><small>{trace.op} · {trace.status}</small><p>{traceSummary(trace)}</p>
                  <footer>
                    {trace.duration_ms != null && <span>{Math.round(trace.duration_ms)}ms</span>}
                    {(trace.usage?.input_tokens || trace.usage?.output_tokens) && <span>{Number(trace.usage?.input_tokens || 0) + Number(trace.usage?.output_tokens || 0)}tok</span>}
                    {!!trace.artifacts?.length && <span>{trace.artifacts.length} files</span>}
                  </footer>
                </button>
              ) : <div key={agent} className="lane-empty" />)}
            </div>
          ))}
          {traces.length === 0 && <div className="observability-empty" style={{ gridColumn: `1 / span ${agents.length + 1}` }}>执行后会按顺序显示每次节点调用。</div>}
        </div>
      )}

      {section === 'children' && <div className="child-run-tree">
        {childRuns.map((child) => <details key={child.harness_id} open={child.status === 'running'}>
          <summary><span>{child.status === 'running' ? '●' : '✓'}</span><b>{child.harness_name}</b><small>{child.harness_id.slice(0, 8)} · {child.messages.length} events</small></summary>
          <div className="child-run-slots">{Object.entries(child.slots).map(([slot, identity]) => <span key={slot}>{slot}={identity}</span>)}</div>
          {child.messages.map((message, index) => <div className="child-run-event" key={`${message.agent}-${index}`}><b>@{message.agent}</b><p>{preview(message.text, 300)}</p>{message.tools.map((tool, toolIndex) => <code key={`${tool.name}-${toolIndex}`}>⚡ {tool.name}</code>)}</div>)}
        </details>)}
        {childRuns.length === 0 && <div className="observability-empty">当前运行还没有启动子 Harness。</div>}
      </div>}

      {section === 'mutations' && <div className="mutation-timeline">
        {mutations.map((change, index) => <article key={`${change.timestamp}-${index}`}>
          <header><b>{change.type === 'harness' ? 'Harness' : 'Identity'} · {change.target}</b><span>{change.action}</span></header>
          {change.field && <code>{change.field}</code>}
          {change.nodes && <small>{change.nodes.join(' → ')}</small>}
          {change.diff !== undefined && change.diff !== null && (
            <pre>{typeof change.diff === 'string' ? change.diff : JSON.stringify(change.diff, null, 2)}</pre>
          )}
        </article>)}
        {mutations.length > 0 && <button className="open-agent-changes" onClick={onOpenChanges}>在 Agent Changes 中审查文件改动</button>}
        {mutations.length === 0 && <div className="observability-empty">Harness 或 Identity 被修改时，结构差异会实时出现在这里。</div>}
      </div>}
    </section>
  );
}
