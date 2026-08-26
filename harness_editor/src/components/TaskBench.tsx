import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import * as api from '../api/client';
import PipelineNodeComponent from '../nodes/PipelineNode';
import ConditionEdge from '../edges/ConditionEdge';
import { loadWorkbenchSession, publishWorkbenchEvent, updateWorkbenchSession } from '../workbenchSession';
import { openFileInIde, type IdeContextItem } from '../ideBridge';
import type {
  HarnessConfig,
  NodeTrace,
  PipelineNode,
  TaskBenchOptions,
  TaskRunState,
  TaskSpec,
} from '../types';

const nodeTypes = { pipelineNode: PipelineNodeComponent };
const edgeTypes = { conditionEdge: ConditionEdge };
const TERMINAL = new Set(['passed', 'failed', 'error', 'stopped', 'timeout']);

function pretty(value: unknown): string {
  if (value === undefined || value === null || value === '') return '—';
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

function formatTime(seconds?: number | null): string {
  if (!seconds) return '—';
  return new Date(seconds * 1000).toLocaleTimeString();
}

function graphFor(config: HarnessConfig | null, run: TaskRunState | null): { nodes: Node[]; edges: Edge[] } {
  if (!config) return { nodes: [], edges: [] };
  const entries = Object.entries(config.pipeline?.nodes || {});
  const cols = Math.max(1, Math.ceil(Math.sqrt(entries.length || 1)));
  const traces = run?.node_traces || [];
  const latest = new Map<string, NodeTrace>();
  const invocationCounts = new Map<string, number>();
  traces.forEach((trace) => {
    latest.set(trace.node_id, trace);
    invocationCounts.set(trace.node_id, (invocationCounts.get(trace.node_id) || 0) + 1);
  });
  const recent = new Set([...traces].slice(-3).map((trace) => trace.sequence));
  const activeNode = run?.pending_node || run?.current_node;
  const nodes: Node[] = entries.map(([id, node], index) => {
    const trace = latest.get(id);
    const isActive = id === activeNode && !!run?.running;
    return {
      id,
      type: 'pipelineNode',
      position: { x: 80 + (index % cols) * 390, y: 70 + Math.floor(index / cols) * 220 },
      data: {
        ...node,
        highlight: isActive,
        runtimeStatus: trace?.status,
        runtimeCount: invocationCounts.get(id) || 0,
        runtimeTrace: trace,
        runtimeActivityMode: isActive ? 'active' : trace && recent.has(trace.sequence) ? 'recent' : undefined,
        runtimePaused: isActive && run?.paused,
      },
    };
  });
  const edges: Edge[] = [];
  entries.forEach(([id, node]) => {
    (node.edges || []).forEach((edge, edgeIndex) => {
      if (!edge.to) return;
      edges.push({
        id: `${id}-${edge.to}-${edgeIndex}`,
        source: id,
        target: edge.to,
        type: 'conditionEdge',
        data: { condition: edge.condition },
      });
    });
  });
  return { nodes, edges };
}

function runSnapshotSignature(run: TaskRunState): string {
  const traces = run.node_traces || [];
  const last = traces[traces.length - 1];
  return [
    run.status,
    run.step_count,
    run.current_node || '',
    run.pending_node || '',
    run.paused ? 1 : 0,
    traces.length,
    last?.sequence || 0,
    last?.status || '',
    typeof last?.model?.response === 'string' ? last.model.response.length : 0,
    last?.tools?.length || 0,
    run.evolution_events?.length || 0,
    run.artifacts?.length || 0,
    run.evaluation?.score ?? '',
  ].join(':');
}

function StatusPill({ status }: { status: string }) {
  const label: Record<string, string> = {
    created: '已创建', running: '运行中', evaluating: '评分中', passed: '通过', failed: '未通过',
    error: '错误', stopped: '已停止', timeout: '超时',
  };
  return <span className={`task-status task-status-${status}`}>{label[status] || status}</span>;
}

export default function TaskBench() {
  const restoredSelection = useRef(loadWorkbenchSession().evaluation || {}).current;
  const [tasks, setTasks] = useState<TaskSpec[]>([]);
  const [options, setOptions] = useState<TaskBenchOptions>({ harnesses: [], identities: [], environments: [] });
  const [selectedTaskId, setSelectedTaskId] = useState(restoredSelection.taskId || '');
  const [harnessName, setHarnessName] = useState(restoredSelection.harness || '');
  const [identityName, setIdentityName] = useState(restoredSelection.identity || '');
  const [environmentNames, setEnvironmentNames] = useState<string[]>(restoredSelection.environments || []);
  const [slotBindings, setSlotBindings] = useState<Record<string, string>>(restoredSelection.slotBindings || {});
  const [startPaused, setStartPaused] = useState(false);
  const [config, setConfig] = useState<HarnessConfig | null>(null);
  const [run, setRun] = useState<TaskRunState | null>(null);
  const [selectedTrace, setSelectedTrace] = useState<NodeTrace | null>(null);
  const [input, setInput] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [runHistory, setRunHistory] = useState<Array<Partial<TaskRunState>>>([]);
  const [detailTab, setDetailTab] = useState<'timeline' | 'evaluation' | 'artifacts' | 'evolution'>('timeline');
  const [compatibility, setCompatibility] = useState<any>(null);
  const [importSource, setImportSource] = useState('');
  const [interopMessage, setInteropMessage] = useState('');
  const [showMinimap, setShowMinimap] = useState(false);
  const [ideContext, setIdeContext] = useState<IdeContextItem[]>(loadWorkbenchSession().handoff?.items || []);
  const lastRunSignature = useRef('');
  const previousHarness = useRef(harnessName);

  const selectedTask = useMemo(() => tasks.find((task) => task.id === selectedTaskId) || null, [tasks, selectedTaskId]);
  const selectedHarness = useMemo(() => options.harnesses.find((item) => item.name === harnessName), [options.harnesses, harnessName]);

  useEffect(() => {
    const receiveHandoff = (event: Event) => {
      const items = (event as CustomEvent<{ items?: IdeContextItem[] }>).detail?.items;
      if (Array.isArray(items)) setIdeContext(items);
    };
    window.addEventListener('egoagent:context-handoff', receiveHandoff);
    return () => window.removeEventListener('egoagent:context-handoff', receiveHandoff);
  }, []);

  useEffect(() => {
    Promise.all([api.listTaskBenchTasks(), api.getTaskBenchOptions(), api.listTaskBenchRuns(), api.getTaskBenchCompatibility()])
      .then(([loadedTasks, loadedOptions, loadedRuns, loadedCompatibility]) => {
        setTasks(loadedTasks);
        setOptions(loadedOptions);
        setRunHistory(loadedRuns);
        setCompatibility(loadedCompatibility);
        const restoredTaskId = restoredSelection.taskId && loadedTasks.some((task: TaskSpec) => task.id === restoredSelection.taskId)
          ? restoredSelection.taskId
          : loadedTasks[0]?.id || '';
        setSelectedTaskId(restoredTaskId);
        if (restoredSelection.runId) {
          api.getTaskBenchRun(restoredSelection.runId)
            .then((restoredRun) => {
              lastRunSignature.current = runSnapshotSignature(restoredRun);
              setRun(restoredRun);
            })
            .catch(() => updateWorkbenchSession({ evaluation: { runId: undefined } }));
        }
      })
      .catch((reason) => setError(reason.message));
  }, []);

  useEffect(() => {
    if (!selectedTask) return;
    const saved = loadWorkbenchSession().evaluation;
    const restoringSameTask = saved?.taskId === selectedTask.id;
    setHarnessName(restoringSameTask && saved?.harness ? saved.harness : selectedTask.selection.recommended_harness || options.harnesses[0]?.name || '');
    setIdentityName(restoringSameTask && saved?.identity ? saved.identity : selectedTask.selection.recommended_identity || options.identities[0]?.name || '');
    setSlotBindings(restoringSameTask ? saved?.slotBindings || {} : {});
    setEnvironmentNames(restoringSameTask ? saved?.environments || [] : []);
    setSelectedTrace(null);
  }, [selectedTask?.id, options.harnesses.length, options.identities.length]);

  useEffect(() => {
    if (!selectedTaskId) return;
    const timer = window.setTimeout(() => updateWorkbenchSession({
      evaluation: {
        taskId: selectedTaskId,
        harness: harnessName,
        identity: identityName,
        environments: environmentNames,
        slotBindings,
        runId: run?.id,
      },
    }), 250);
    return () => window.clearTimeout(timer);
  }, [selectedTaskId, harnessName, identityName, environmentNames, slotBindings, run?.id]);

  useEffect(() => {
    publishWorkbenchEvent('runtime-status', {
      scope: 'evaluate',
      running: Boolean(run?.running),
      paused: Boolean(run?.paused),
      currentNode: run?.pending_node || run?.current_node,
      harness: harnessName,
      runId: run?.id,
      status: run?.status || 'idle',
      taskId: selectedTaskId,
    });
  }, [run?.id, run?.running, run?.paused, run?.pending_node, run?.current_node, run?.status, harnessName, selectedTaskId]);

  const reloadHarness = useCallback(() => {
    if (!harnessName) { setConfig(null); return; }
    api.loadHarness(harnessName).then(setConfig).catch((reason) => setError(reason.message));
  }, [harnessName]);

  useEffect(() => { reloadHarness(); }, [reloadHarness]);
  useEffect(() => {
    if (previousHarness.current && previousHarness.current !== harnessName) setSlotBindings({});
    previousHarness.current = harnessName;
  }, [harnessName]);
  useEffect(() => {
    if (run?.evolution_events?.some((event) => event.data?.harness === harnessName)) reloadHarness();
  }, [run?.evolution_events?.length]);

  useEffect(() => {
    if (!run?.id || TERMINAL.has(run.status)) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await api.getTaskBenchRun(run.id) as TaskRunState;
        if (cancelled) return;
        const signature = runSnapshotSignature(next);
        if (signature !== lastRunSignature.current) {
          lastRunSignature.current = signature;
          setRun(next);
        }
        if (!TERMINAL.has(next.status)) timer = window.setTimeout(poll, 650);
        else {
          api.listTaskBenchRuns().then(setRunHistory).catch(() => {});
          setDetailTab(next.evaluation ? 'evaluation' : 'timeline');
        }
      } catch (reason: any) {
        if (!cancelled) setError(reason.message);
      }
    };
    timer = window.setTimeout(poll, 200);
    return () => { cancelled = true; if (timer) window.clearTimeout(timer); };
  }, [run?.id, run?.status]);

  const graph = useMemo(() => graphFor(config, run), [config, run?.node_traces, run?.current_node, run?.pending_node, run?.paused, run?.running]);
  const activeNodeId = run?.pending_node || run?.current_node;
  const activeTrace = selectedTrace || [...(run?.node_traces || [])].reverse().find((trace: NodeTrace) => trace.node_id === activeNodeId) || null;
  const visibleTraces = useMemo(() => (run?.node_traces || []).slice(-200), [run?.node_traces]);
  const hiddenTraceCount = Math.max(0, (run?.node_traces?.length || 0) - visibleTraces.length);

  const compatibleHarnesses = useMemo(() => {
    const allowed = selectedTask?.selection.compatible_harnesses || [];
    return allowed.length ? options.harnesses.filter((item) => allowed.includes(item.name)) : options.harnesses;
  }, [selectedTask, options.harnesses]);
  const compatibleIdentities = useMemo(() => {
    const allowed = selectedTask?.selection.compatible_identities || [];
    return allowed.length ? options.identities.filter((item) => allowed.includes(item.name)) : options.identities;
  }, [selectedTask, options.identities]);

  const launch = async () => {
    if (!selectedTask || !harnessName || !identityName) return;
    setBusy(true); setError(''); setSelectedTrace(null); setDetailTab('timeline');
    try {
      const slotEntries = Object.entries(selectedHarness?.slots || {});
      const resolvedSlotBindings = Object.fromEntries(
        slotEntries.map(([slot, definition]) => [
          slot,
          slotBindings[slot] || (slotEntries.length === 1 ? identityName : (definition as { identity?: string }).identity || identityName),
        ]),
      );
      const next = await api.startTaskBenchRun({
        task_id: selectedTask.id,
        harness: harnessName,
        identity: identityName,
        environments: environmentNames,
        slot_bindings: resolvedSlotBindings,
        debug_mode: startPaused ? 'paused' : 'auto',
        ide_context: ideContext,
      });
      lastRunSignature.current = runSnapshotSignature(next);
      setRun(next);
    } catch (reason: any) { setError(reason.message); }
    finally { setBusy(false); }
  };

  const control = async (action: 'pause' | 'step' | 'auto' | 'stop') => {
    if (!run) return;
    try { setRun(await api.controlTaskBenchRun(run.id, action)); }
    catch (reason: any) { setError(reason.message); }
  };

  const sendInput = async () => {
    if (!run || !input.trim()) return;
    try { await api.sendTaskBenchInput(run.id, input.trim()); setInput(''); }
    catch (reason: any) { setError(reason.message); }
  };

  const openHistory = async (runId: string) => {
    try { const loaded = await api.getTaskBenchRun(runId); setRun(loaded); setSelectedTaskId(loaded.task_id); }
    catch (reason: any) { setError(reason.message); }
  };

  const importExternalTask = async () => {
    if (!importSource.trim()) return;
    setBusy(true); setError(''); setInteropMessage('');
    try {
      const result = await api.importTaskBenchTask(importSource.trim());
      const loadedTasks = await api.listTaskBenchTasks();
      setTasks(loadedTasks); setSelectedTaskId(result.task.id);
      setInteropMessage(`已导入 ${result.format}: ${result.task.id}`);
    } catch (reason: any) { setError(reason.message); }
    finally { setBusy(false); }
  };

  const exportHarbor = async () => {
    if (!selectedTask) return;
    setBusy(true); setError(''); setInteropMessage('');
    try {
      const result = await api.exportTaskBenchHarbor(selectedTask.id);
      setInteropMessage(`Harbor 目录已生成：${result.path}`);
    } catch (reason: any) { setError(reason.message); }
    finally { setBusy(false); }
  };

  return (
    <div className="task-bench">
      <aside className="task-library">
        <div className="task-brand"><span>▦</span><div><b>Task Bench</b><small>可复现的 Agent 做题实验台</small></div></div>
        <details className="task-interop">
          <summary>导入 / 导出 benchmark</summary>
          <small>支持 Harbor 1.4、旧 Terminal-Bench 和 ego.task.v1。资源会内嵌进题目，运行不依赖原目录。</small>
          <input value={importSource} onChange={(event) => setImportSource(event.target.value)} placeholder="本地题目目录或 task.json" />
          <div><button disabled={busy || !importSource.trim()} onClick={importExternalTask}>导入题目</button><button disabled={busy || !selectedTask} onClick={exportHarbor}>导出 Harbor</button></div>
          <span className={compatibility?.docker?.available ? 'ready' : 'blocked'}>Docker {compatibility?.docker?.available ? '可用' : '不可用'} · 多步骤已启用</span>
          {compatibility?.docker?.reason && <small title={compatibility.docker.reason}>{compatibility.docker.reason}</small>}
          {interopMessage && <p>{interopMessage}</p>}
        </details>
        <div className="task-section-label">题目库 · {tasks.length}</div>
        <div className="task-list">
          {tasks.map((task) => (
            <button key={task.id} className={`task-card ${task.id === selectedTaskId ? 'active' : ''}`} onClick={() => setSelectedTaskId(task.id)}>
              <span className={`difficulty difficulty-${task.difficulty}`}>{task.difficulty}</span>
              <b>{task.title}</b>
              <small>{task.description}</small>
              <span className="task-card-meta">{task.external_format?.type || task.category} · {task.steps?.length ? `${task.steps.length} steps` : `${task.evaluation.checks.length} checks`}</span>
            </button>
          ))}
        </div>
        <div className="task-section-label">最近运行</div>
        <div className="task-history">
          {runHistory.slice(0, 8).map((item) => (
            <button key={item.id} onClick={() => item.id && openHistory(item.id)}>
              <span>{item.task_id}</span><StatusPill status={item.status || 'created'} />
            </button>
          ))}
          {!runHistory.length && <small>还没有运行记录</small>}
        </div>
      </aside>

      <main className="task-main">
        <header className="task-header">
          <div>
            <div className="task-title-row"><h2>{selectedTask?.title || '选择一道题目'}</h2>{run && <StatusPill status={run.status} />}</div>
            <p>{selectedTask?.prompt}</p>
            <div className="task-tags">{selectedTask?.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
          </div>
          <div className="task-run-meta">
            {run ? <><code>{run.id}</code><span>{run.task_step ? `task step ${run.task_step}` : `node step ${run.step_count}`}</span><span>{formatTime(run.started_at)}</span>{run.policy?.hidden_tools?.length ? <span title={run.policy.hidden_tools.join(', ')}>策略隐藏 {run.policy.hidden_tools.length} tools</span> : null}</> : <span>尚未启动</span>}
          </div>
        </header>

        {ideContext.length > 0 && <section className="task-ide-context">
          <div><b>来自 IDE 的任务上下文</b><small>会复制到隔离题目工作区并写入可复现运行记录。</small></div>
          <div>{ideContext.map((item, index) => <button key={`${item.path}:${item.startLine || 0}:${index}`} onClick={() => openFileInIde(item.path, item.startLine || 1, item.endLine)} title={item.path}>
            {item.kind === 'selection' ? '选区' : '文件'} · {item.relativePath || item.path.split(/[\\/]/).pop()} {item.startLine ? `L${item.startLine}${item.endLine && item.endLine !== item.startLine ? `–${item.endLine}` : ''}` : ''}
          </button>)}<button className="clear" onClick={() => { setIdeContext([]); updateWorkbenchSession({ handoff: { items: [], updatedAt: Date.now() } }); }}>清除</button></div>
        </section>}

        <section className="task-config-bar">
          <label>Harness<select value={harnessName} onChange={(event) => setHarnessName(event.target.value)} disabled={!!run?.running}>
            {compatibleHarnesses.map((item) => <option key={item.name} value={item.name}>{item.name} · {item.node_count} nodes</option>)}
          </select></label>
          <label>Identity<select value={identityName} onChange={(event) => setIdentityName(event.target.value)} disabled={!!run?.running}>
            {compatibleIdentities.map((item) => <option key={item.name} value={item.name}>{item.name}{item.role ? ` · ${item.role}` : ''}</option>)}
          </select></label>
          <div className="task-env-picker">
            <span>Environment</span>
            <div className="task-env-summary">隔离工作区 · {selectedTask?.environment.network === 'disabled' ? '网络工具禁用' : '继承网络'}</div>
            {options.environments.map((environment) => <label key={environment.name}><input type="checkbox" checked={environmentNames.includes(environment.name)} onChange={(event) => setEnvironmentNames((current) => event.target.checked ? [...current, environment.name] : current.filter((name) => name !== environment.name))} />{environment.name}</label>)}
          </div>
          <label className="task-debug-toggle"><input type="checkbox" checked={startPaused} onChange={(event) => setStartPaused(event.target.checked)} disabled={!!run?.running} /> 首节点前暂停</label>
          {!run?.running ? <button className="task-launch" disabled={busy || !selectedTask} onClick={launch}>{busy ? '准备中…' : '▶ 开始做题'}</button> : <div className="task-controls">
            <button onClick={() => control('pause')} disabled={run.paused}>⏸</button><button onClick={() => control('step')}>单步</button><button onClick={() => control('auto')}>自动</button><button className="danger" onClick={() => control('stop')}>停止</button>
          </div>}
        </section>

        {selectedHarness && Object.keys(selectedHarness.slots || {}).length > 1 && (
          <section className="task-slot-bindings"><b>多 Agent Slot</b>{Object.keys(selectedHarness.slots).map((slot) => <label key={slot}><span>@{slot}</span><select value={slotBindings[slot] || selectedHarness.slots[slot]?.identity || identityName} onChange={(event) => setSlotBindings((current) => ({ ...current, [slot]: event.target.value }))}>{compatibleIdentities.map((identity) => <option key={identity.name} value={identity.name}>{identity.name}</option>)}</select></label>)}</section>
        )}
        {selectedTask?.evolution.allowed && <div className="task-evolution-notice">🧬 此题允许结构/能力进化。Harness、Identity、Skill、Knowledge 的新增与修改会被记录为评分证据，并实时显示。</div>}
        {selectedTask?.steps?.length ? <div className="task-evolution-notice">⇥ 多步骤任务共 {selectedTask.steps.length} 阶段；默认每阶段刷新模型上下文，但共享容器和工作区。只有题目声明 resume_trajectory 才续接对话。</div> : null}
        {selectedTask?.environment.backend === 'container' && !compatibility?.docker?.available ? <div className="task-error">此题需要 Docker；当前诊断：{compatibility?.docker?.reason || 'Docker 不可用'}</div> : null}
        {error && <div className="task-error">{error}</div>}

        <section className="task-workbench">
          <div className="task-dag-panel">
            <div className="task-panel-title"><span>DAG 运行面板</span><div className="task-panel-actions"><button className={showMinimap ? 'active' : ''} onClick={() => setShowMinimap((visible) => !visible)}>{showMinimap ? '隐藏概览' : '概览'}</button><small>{run?.paused ? `暂停在 ${run.pending_node}` : run?.running ? `正在执行 ${run.current_node || '准备中'}` : `${graph.nodes.length} nodes`}</small></div></div>
            <ReactFlowProvider>
              <ReactFlow nodes={graph.nodes} edges={graph.edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} onlyRenderVisibleElements fitView nodesDraggable={false} nodesConnectable={false} elementsSelectable onNodeClick={(_event, node) => {
                const trace = [...(run?.node_traces || [])].reverse().find((item) => item.node_id === node.id) || null;
                setSelectedTrace(trace); setDetailTab('timeline');
              }}>
                <Background gap={22} size={1} /><Controls showInteractive={false} />{showMinimap && <MiniMap pannable zoomable />}
              </ReactFlow>
            </ReactFlowProvider>
            {activeTrace && <aside className="task-trace-peek">
              <div><b>{activeTrace.node_id}</b><span>{activeTrace.op} · {activeTrace.status}</span><button onClick={() => setSelectedTrace(null)}>×</button></div>
              {activeTrace.model?.response ? <><label>模型输出</label><pre>{pretty(activeTrace.model.response)}</pre></> : null}
              {activeTrace.tools?.length ? <><label>工具</label>{activeTrace.tools.map((tool, index) => <pre key={index}>🔧 {tool.name}\n{pretty(tool.result || tool.reason)}</pre>)}</> : null}
              {!activeTrace.model?.response && !activeTrace.tools?.length ? <><label>输入 / 输出</label><pre>{pretty(activeTrace.output ?? activeTrace.input)}</pre></> : null}
            </aside>}
          </div>

          <div className="task-detail-panel">
            <nav>{(['timeline', 'evaluation', 'artifacts', 'evolution'] as const).map((name) => <button key={name} className={detailTab === name ? 'active' : ''} onClick={() => setDetailTab(name)}>{name === 'timeline' ? '过程' : name === 'evaluation' ? '评分' : name === 'artifacts' ? '产物' : '进化'}{name === 'evolution' && run?.evolution_events?.length ? ` ${run.evolution_events.length}` : ''}</button>)}</nav>
            <div className="task-detail-body">
              {detailTab === 'timeline' && <div className="task-timeline">
                {hiddenTraceCount > 0 && <div className="task-trace-window-note">为保持流畅，已折叠更早的 {hiddenTraceCount} 条轨迹</div>}
                {visibleTraces.map((trace) => <button key={trace.sequence} className={selectedTrace?.sequence === trace.sequence ? 'active' : ''} onClick={() => setSelectedTrace(trace)}><span className={`trace-dot ${trace.status}`} /><b>#{trace.sequence} {trace.node_id}</b><small>{trace.op}{trace.agent ? ` · @${trace.agent}` : ''}</small><em>{trace.tools?.length ? `🔧 ${trace.tools[trace.tools.length - 1]?.name}` : trace.model?.response ? String(trace.model.response).slice(-100) : pretty(trace.output).slice(0, 100)}</em></button>)}
                {!run?.node_traces?.length && <div className="task-empty">启动后，每次节点调用都会出现在这里。</div>}
              </div>}
              {detailTab === 'evaluation' && <div className="task-evaluation">
                {run?.evaluation ? <><div className="task-score"><strong>{Math.round(run.evaluation.score * 100)}</strong><span>/ 100<br />通过线 {Math.round(run.evaluation.pass_score * 100)}</span></div>{run.evaluation.checks.map((check) => <div className={`task-check ${check.passed ? 'passed' : 'failed'}`} key={check.id}><span>{check.passed ? '✓' : '×'}</span><div><b>{check.id}</b><small>{check.type} · weight {check.weight}</small><p>{check.summary}</p></div></div>)}</> : <div className="task-empty">任务结束后执行确定性评分；Agent 的自述不会被当作成功证据。</div>}
              </div>}
              {detailTab === 'artifacts' && <div className="task-artifacts">{run?.artifacts?.map((artifact) => <details key={artifact.path}><summary><button onClick={(event) => { event.preventDefault(); openFileInIde(`${run.workspace.replace(/[\\/]$/, '')}/${artifact.path}`); }} title="在 Void 编辑器打开"><b>{artifact.path}</b></button><span>{artifact.size} B</span></summary><pre>{artifact.preview || 'binary / too large'}</pre></details>)}{!run?.artifacts?.length && <div className="task-empty">完成后显示隔离工作区文件与预览。</div>}</div>}
              {detailTab === 'evolution' && <div className="task-evolution-log">
                {run?.evolution_events?.map((event) => <div key={event.sequence}><b>{event.type}</b><time>{formatTime(event.time)}</time><pre>{pretty(event.data)}</pre></div>)}
                {run?.mutations && Object.keys(run.mutations).length > 0 && <details open><summary>最终结构差异</summary><pre>{pretty(run.mutations)}</pre></details>}
                {!run?.evolution_events?.length && <div className="task-empty">创建 Agent、修改 Harness、安装 Skill/Knowledge 时会实时记录在这里。</div>}
              </div>}
            </div>
            {run?.running && <div className="task-input"><input value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') sendInput(); }} placeholder="仅在 DAG 请求澄清/审批时输入…" /><button onClick={sendInput}>发送</button></div>}
          </div>
        </section>
      </main>
    </div>
  );
}
