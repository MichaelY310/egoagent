import { useMemo } from 'react';
import type { ChangeEntry } from './RunObservability';
import type { RuntimeRunView, RuntimeStoryEvent } from '../runtimeTopology';

type RootRun = {
  runId: string;
  harness: string;
  slots: Record<string, string>;
  status: string;
  currentNode?: string | null;
  stepCount: number;
};

type Props = {
  root: RootRun;
  runs: RuntimeRunView[];
  changes: ChangeEntry[];
  events: RuntimeStoryEvent[];
  onOpenChanges?: () => void;
  compact?: boolean;
};

function shortId(value: string): string {
  return value ? value.slice(-8) : '--------';
}

function RunCard({ run, depth = 0, children }: { run: RuntimeRunView; depth?: number; children?: React.ReactNode }) {
  return <div className={`live-run-branch depth-${Math.min(depth, 3)}`}>
    <article className={`live-run-card ${run.status}`}>
      <header><span className="live-pulse" /><b>{run.harness}</b><code>{shortId(run.runId)}</code></header>
      <div className="live-run-bindings">{Object.entries(run.slots).map(([slot, identity]) => <span key={slot}>@{slot}<em>{identity}</em></span>)}</div>
      <p>{run.lastActivity || '等待运行事件…'}</p>
      <footer><span>{run.currentNode || run.parentNodeId || 'start'}</span><span>{run.nodeCalls} nodes</span><span>{run.modelCalls} model</span><span>{run.toolCalls} tools</span></footer>
    </article>
    {children && <div className="live-run-children">{children}</div>}
  </div>;
}

export default function LiveAgentArchitecture({ root, runs, changes, events, onOpenChanges, compact = false }: Props) {
  const childRuns = useMemo(() => runs.filter((run) => run.runId !== root.runId), [runs, root.runId]);
  const byParent = useMemo(() => {
    const result = new Map<string, RuntimeRunView[]>();
    childRuns.forEach((run) => {
      const key = run.parentRunId || root.runId;
      result.set(key, [...(result.get(key) || []), run]);
    });
    return result;
  }, [childRuns, root.runId]);
  const renderChildren = (parentId: string, depth: number): React.ReactNode => (byParent.get(parentId) || []).map((run) => (
    <RunCard key={run.runId} run={run} depth={depth}>{renderChildren(run.runId, depth + 1)}</RunCard>
  ));
  const latestChanges = changes.slice(-4).reverse();
  const latestEvents = events.slice(-6).reverse();
  const activeChildren = childRuns.filter((run) => ['starting', 'running'].includes(run.status)).length;

  return <aside className={`live-agent-architecture ${compact ? 'compact' : ''}`} aria-label="实时 Agent 架构">
    <header className="live-architecture-head">
      <div><span className={root.status === 'running' ? 'live-pulse' : 'live-pulse idle'} /><b>LIVE ARCHITECTURE</b><small>真实 Run / SubFlow / Evolution 事件</small></div>
      <div className="live-architecture-counts"><span>{childRuns.length + 1} runs</span><span>{activeChildren} active</span><span>{changes.length} changes</span></div>
    </header>
    <div className="live-root-run">
      <article className={`live-run-card root ${root.status}`}>
        <header><span className="live-pulse" /><b>{root.harness || 'root flow'}</b><code>{shortId(root.runId)}</code></header>
        <div className="live-run-bindings">{Object.entries(root.slots || {}).map(([slot, identity]) => <span key={slot}>@{slot}<em>{identity}</em></span>)}</div>
        <p>{root.currentNode ? `正在执行 ${root.currentNode}` : root.status === 'running' ? '正在启动 Flow…' : '等待运行'}</p>
        <footer><span>{root.stepCount} steps</span><span>{root.status}</span></footer>
      </article>
      <div className="live-run-children">{renderChildren(root.runId, 1)}</div>
    </div>
    {!compact && <>
      <section className="live-story">
        <div className="live-section-title"><b>事件故事线</b><small>谁创建了谁，以及为什么变化</small></div>
        {latestEvents.map((event) => <article className={event.tone} key={event.id}><i>{event.type === 'mutation' ? '↗' : event.type === 'subagent' ? '◇' : event.type === 'approval' ? '✓' : event.type === 'error' ? '!' : '●'}</i><div><b>{event.title}</b><p>{event.detail || '—'}</p></div><time>{new Date(event.time).toLocaleTimeString()}</time></article>)}
        {!latestEvents.length && <p className="live-empty">启动后，子 Agent、审批和进化会按真实发生顺序出现。</p>}
      </section>
      <section className="live-mutation-story">
        <div className="live-section-title"><b>Flow 版本变化</b>{changes.length > 0 && onOpenChanges && <button onClick={onOpenChanges}>查看事务</button>}</div>
        {latestChanges.map((change, index) => <article key={`${change.timestamp}-${index}`}>
          <header><b>{change.target}</b><code>{change.revision ? `rev ${change.revision}` : change.action}</code></header>
          <div className="mutation-node-chips">
            {change.addedNodes?.map((node) => <span className="added" key={`a-${node}`}>＋ {node}</span>)}
            {change.removedNodes?.map((node) => <span className="removed" key={`r-${node}`}>− {node}</span>)}
            {change.changedNodes?.map((node) => <span className="changed" key={`c-${node}`}>~ {node}</span>)}
            {!change.addedNodes?.length && !change.removedNodes?.length && !change.changedNodes?.length && <span>{change.field || change.action}</span>}
          </div>
          {(change.addedEdges?.length || change.removedEdges?.length) ? <small>连线 +{change.addedEdges?.length || 0} / −{change.removedEdges?.length || 0}</small> : null}
        </article>)}
        {!latestChanges.length && <p className="live-empty">Agent 修改 Flow 后，这里保留 before → after 结构差异。</p>}
      </section>
    </>}
  </aside>;
}
