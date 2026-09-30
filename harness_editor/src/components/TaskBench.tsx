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
import FlowRunViewer from './FlowRunViewer';
import { configToFlow } from '../flowGraph';
import PipelineNodeComponent from '../nodes/PipelineNode';
import ConditionEdge from '../edges/ConditionEdge';
import LiveAgentArchitecture from './LiveAgentArchitecture';
import type { ChangeEntry } from './RunObservability';
import { loadWorkbenchSession, publishWorkbenchEvent, updateWorkbenchSession } from '../workbenchSession';
import { openFileInIde, type IdeContextItem } from '../ideBridge';
import type {
  HarnessConfig,
  NodeTrace,
  PipelineNode,
  TaskBenchOptions,
  TaskDatasetSummary,
  TaskRunState,
  TaskSpec,
} from '../types';
import { deriveRuntimeRuns, normalizeMutationPayload, storyEvent } from '../runtimeTopology';

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
  if (!config && run?.selection?.runner === 'codex_cli') {
    const traces = run.node_traces || [];
    const nodes: Node[] = traces.map((trace, index) => ({
      id: trace.node_id,
      type: 'pipelineNode',
      position: { x: 80 + (index % 4) * 390, y: 70 + Math.floor(index / 4) * 220 },
      data: {
        id: trace.node_id, op: trace.op, agent: trace.agent,
        runtimeStatus: trace.status, runtimeCount: 1, runtimeTrace: trace,
        runtimeActivityMode: index >= traces.length - 3 ? 'recent' : undefined,
        highlight: trace.node_id === (run.pending_node || run.current_node) && run.running,
      },
    }));
    const edges: Edge[] = nodes.slice(1).map((node, index) => ({
      id: `external-${index}-${index + 1}`, source: nodes[index].id, target: node.id,
      type: 'conditionEdge', data: { condition: 'next event' },
    }));
    return { nodes, edges };
  }
  if (!config) return { nodes: [], edges: [] };
  return configToFlow(config);
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
    run.events?.length || 0,
    run.artifacts?.length || 0,
    run.evaluation?.score ?? '',
  ].join(':');
}

function StatusPill({ status }: { status: string }) {
  const label: Record<string, string> = {
    created: '已创建', preparing: '准备环境中', running: '运行中', evaluating: '评分中', passed: '通过', failed: '未通过',
    error: '错误', stopped: '已停止', timeout: '超时',
  };
  return <span className={`task-status task-status-${status}`}>{label[status] || status}</span>;
}

export default function TaskBench() {
  const restoredSelection = useRef(loadWorkbenchSession().evaluation || {}).current;
  const [tasks, setTasks] = useState<TaskSpec[]>([]);
  const [datasets, setDatasets] = useState<TaskDatasetSummary[]>([]);
  const [datasetFilter, setDatasetFilter] = useState('');
  const [datasetDraft, setDatasetDraft] = useState({
    id: '', title: '', format: 'jsonl' as 'json' | 'jsonl' | 'csv',
    content: '{"id":"case-1","prompt":"Answer with alpha","expected":"alpha"}',
    idField: 'id', titleField: '', promptField: 'prompt', expectedField: 'expected',
    workspaceField: '', metadataField: '',
  });
  const [datasetEvaluation, setDatasetEvaluation] = useState('');
  const [datasetPreview, setDatasetPreview] = useState<any>(null);
  const [options, setOptions] = useState<TaskBenchOptions>({ runners: [], harnesses: [], identities: [], environments: [] });
  const [selectedTaskId, setSelectedTaskId] = useState(restoredSelection.taskId || '');
  const [runnerName, setRunnerName] = useState<'ego_flow' | 'codex_cli'>(restoredSelection.runner || 'ego_flow');
  const [harnessName, setHarnessName] = useState(restoredSelection.harness || '');
  const [harnessVersion, setHarnessVersion] = useState(restoredSelection.harnessVersion || '');
  const [harnessVersionOptions, setHarnessVersionOptions] = useState<api.HarnessVersion[]>([]);
  const [versionOwner, setVersionOwner] = useState('');
  const [identityName, setIdentityName] = useState(restoredSelection.identity || '');
  const [environmentNames, setEnvironmentNames] = useState<string[]>(restoredSelection.environments || []);
  const [slotBindings, setSlotBindings] = useState<Record<string, string>>(restoredSelection.slotBindings || {});
  const [startPaused, setStartPaused] = useState(false);
  const [config, setConfig] = useState<HarnessConfig | null>(null);
  const [configError, setConfigError] = useState('');
  const configRequest = useRef(0);
  const [run, setRun] = useState<TaskRunState | null>(null);
  const [selectedTrace, setSelectedTrace] = useState<NodeTrace | null>(null);
  const [input, setInput] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [runHistory, setRunHistory] = useState<Array<Partial<TaskRunState>>>([]);
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<any>(null);
  const [detailTab, setDetailTab] = useState<'timeline' | 'evaluation' | 'artifacts' | 'evolution'>('timeline');
  const [compatibility, setCompatibility] = useState<any>(null);
  const [importSource, setImportSource] = useState('');
  const [interopMessage, setInteropMessage] = useState('');
  const [showMinimap, setShowMinimap] = useState(false);
  const [compactLibraryOpen, setCompactLibraryOpen] = useState(false);
  const [ideContext, setIdeContext] = useState<IdeContextItem[]>(loadWorkbenchSession().handoff?.items || []);
  const lastRunSignature = useRef('');
  const previousHarness = useRef(harnessName);

  const selectedTask = useMemo(() => tasks.find((task) => task.id === selectedTaskId) || null, [tasks, selectedTaskId]);
  const selectedHarness = useMemo(() => options.harnesses.find((item) => item.name === harnessName), [options.harnesses, harnessName]);
  const visibleTasks = useMemo(
    () => datasetFilter ? tasks.filter((task) => task.dataset?.id === datasetFilter) : tasks,
    [tasks, datasetFilter],
  );

  useEffect(() => {
    const receiveHandoff = (event: Event) => {
      const items = (event as CustomEvent<{ items?: IdeContextItem[] }>).detail?.items;
      if (Array.isArray(items)) setIdeContext(items);
    };
    window.addEventListener('egoagent:context-handoff', receiveHandoff);
    return () => window.removeEventListener('egoagent:context-handoff', receiveHandoff);
  }, []);

  useEffect(() => {
    api.getTaskBenchOptions().then(setOptions).catch((reason) => setError(`运行选项：${reason.message}`));
    api.listTaskBenchRuns().then(setRunHistory).catch((reason) => setError(`历史记录：${reason.message}（不影响题库）`));
    api.getTaskBenchCompatibility().then(setCompatibility).catch((reason) => setError(`环境检测：${reason.message}`));
    api.listTaskDatasets().then(setDatasets).catch((reason) => setError(`数据集：${reason.message}`));
    api.listTaskBenchTasks()
      .then((loadedTasks) => {
        setTasks(loadedTasks);
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
    if (!harnessName) { setHarnessVersionOptions([]); setHarnessVersion(''); return; }
    let cancelled = false;
    api.listHarnessVersions(harnessName).then((index) => {
      if (cancelled) return;
      setHarnessVersionOptions(index.versions || []);
      setVersionOwner(harnessName);
      setHarnessVersion((current) => (index.versions || []).some((item) => item.id === current) ? current : index.latest || '');
    }).catch((reason) => { if (!cancelled) setError(reason.message); });
    return () => { cancelled = true; };
  }, [harnessName]);

  useEffect(() => {
    if (!selectedTaskId) return;
    const timer = window.setTimeout(() => updateWorkbenchSession({
      evaluation: {
        taskId: selectedTaskId,
        runner: runnerName,
        harness: harnessName,
        harnessVersion,
        identity: identityName,
        environments: environmentNames,
        slotBindings,
        runId: run?.id,
      },
    }), 250);
    return () => window.clearTimeout(timer);
  }, [selectedTaskId, runnerName, harnessName, harnessVersion, identityName, environmentNames, slotBindings, run?.id]);

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
    const requestId = ++configRequest.current;
    setConfigError('');
    if (runnerName === 'codex_cli' || !harnessName) { setConfig(null); return; }
    // A new Flow must not be requested with the previous Flow's version ID.
    const version = versionOwner === harnessName && harnessVersionOptions.some(item => item.id === harnessVersion) ? harnessVersion : '';
    const request = version ? api.loadHarnessVersion(harnessName, version) : api.loadHarness(harnessName);
    request.then(value => { if (requestId === configRequest.current) setConfig(value); })
      .catch(reason => { if (requestId === configRequest.current) setConfigError(`Flow 预览加载失败：${reason.message}`); });
  }, [runnerName, harnessName, harnessVersion, versionOwner, harnessVersionOptions]);

  useEffect(() => { reloadHarness(); return () => { configRequest.current += 1; }; }, [reloadHarness]);
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
  const liveRuns = useMemo(() => deriveRuntimeRuns(run?.events || []), [run?.events]);
  const rootLiveRun = liveRuns.find((item) => !item.parentRunId) || liveRuns[0];
  const liveStory = useMemo(() => (run?.events || []).flatMap((event) => {
    const projected = storyEvent(event.type, event.data || {}, event.time * 1000);
    return projected ? [projected] : [];
  }), [run?.events]);
  const liveChanges = useMemo<ChangeEntry[]>(() => (run?.evolution_events || []).flatMap((event) => {
    if (event.type !== 'harness_mutation') return [];
    const mutation = normalizeMutationPayload(event.data || {});
    return [{
      timestamp: event.time * 1000,
      type: 'harness' as const,
      target: mutation.target || 'Flow',
      action: mutation.action,
      revision: mutation.revision,
      transactionId: mutation.transactionId,
      nodes: mutation.nodes,
      diff: mutation.diff,
      addedNodes: mutation.addedNodes,
      removedNodes: mutation.removedNodes,
      changedNodes: mutation.changedNodes,
      addedEdges: mutation.addedEdges,
      removedEdges: mutation.removedEdges,
    }];
  }), [run?.evolution_events]);

  const compatibleHarnesses = useMemo(() => {
    const allowed = selectedTask?.selection.compatible_harnesses || [];
    return allowed.length ? options.harnesses.filter((item) => allowed.includes(item.name)) : options.harnesses;
  }, [selectedTask, options.harnesses]);
  const compatibleIdentities = useMemo(() => {
    const allowed = selectedTask?.selection.compatible_identities || [];
    return allowed.length ? options.identities.filter((item) => allowed.includes(item.name)) : options.identities;
  }, [selectedTask, options.identities]);

  const launch = async () => {
    if (!selectedTask || (runnerName === 'ego_flow' && (!harnessName || !identityName))) return;
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
        runner: runnerName,
        harness: harnessName,
        harness_version: harnessVersion || 'latest',
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
    try {
      const loaded = await api.getTaskBenchRun(runId);
      setRun(loaded); setSelectedTaskId(loaded.task_id);
      setRunnerName(loaded.selection?.runner || 'ego_flow');
    }
    catch (reason: any) { setError(reason.message); }
  };

  const recoverHistory = async (runId: string) => {
    setBusy(true); setError(''); setSelectedTrace(null); setDetailTab('timeline');
    try {
      const recovered = await api.recoverTaskBenchRun(runId, startPaused ? 'paused' : 'auto');
      lastRunSignature.current = runSnapshotSignature(recovered);
      setRun(recovered); setSelectedTaskId(recovered.task_id);
      setRunnerName(recovered.selection?.runner || 'ego_flow');
    } catch (reason: any) { setError(reason.message); }
    finally { setBusy(false); }
  };

  const compareSelectedRuns = async () => {
    if (selectedRunIds.length < 2) return;
    setBusy(true); setError('');
    try { setComparison(await api.compareTaskBenchRuns(selectedRunIds)); }
    catch (reason: any) { setError(reason.message); }
    finally { setBusy(false); }
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

  const datasetPayload = () => ({
    id: datasetDraft.id.trim(), title: datasetDraft.title.trim() || datasetDraft.id.trim(),
    format: datasetDraft.format, content: datasetDraft.content,
    mapping: {
      id: datasetDraft.idField.trim(), title: datasetDraft.titleField.trim(),
      prompt: datasetDraft.promptField.trim(), expected: datasetDraft.expectedField.trim(),
      workspace_files: datasetDraft.workspaceField.trim(), metadata: datasetDraft.metadataField.trim(),
    },
    evaluation_template: datasetEvaluation.trim() ? JSON.parse(datasetEvaluation) : undefined,
  });

  const previewDataset = async () => {
    setBusy(true); setError('');
    try { setDatasetPreview(await api.previewTaskDataset(datasetPayload())); }
    catch (reason: any) { setError(reason.message); }
    finally { setBusy(false); }
  };

  const saveDataset = async () => {
    if (!datasetDraft.id.trim()) { setError('请先填写 Dataset ID'); return; }
    setBusy(true); setError('');
    try {
      const created = await api.createTaskDataset(datasetPayload());
      const [loadedDatasets, loadedTasks] = await Promise.all([api.listTaskDatasets(), api.listTaskBenchTasks()]);
      setDatasets(loadedDatasets); setTasks(loadedTasks); setDatasetFilter(created.id);
      setSelectedTaskId(created.tasks?.[0] || ''); setInteropMessage(`已固化 ${created.row_count} 个 case · ${created.id}`);
    } catch (reason: any) { setError(reason.message); }
    finally { setBusy(false); }
  };

  return (
    <div className={`task-bench ${compactLibraryOpen ? 'library-open' : ''}`}>
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
        <details className="task-interop task-dataset-importer">
          <summary>＋ 自定义数据集格式</summary>
          <small>粘贴 JSON / JSONL / CSV，选择字段含义。系统先预览映射，再固化每个 case、来源哈希和可运行题目。</small>
          <div className="task-dataset-name-row">
            <input value={datasetDraft.id} onChange={(event) => setDatasetDraft({ ...datasetDraft, id: event.target.value })} placeholder="Dataset ID，例如 my_eval" />
            <input value={datasetDraft.title} onChange={(event) => setDatasetDraft({ ...datasetDraft, title: event.target.value })} placeholder="显示名称" />
          </div>
          <select value={datasetDraft.format} onChange={(event) => setDatasetDraft({ ...datasetDraft, format: event.target.value as typeof datasetDraft.format })}>
            <option value="jsonl">JSONL · 每行一个对象</option><option value="json">JSON · 对象数组</option><option value="csv">CSV · 首行为字段名</option>
          </select>
          <textarea rows={7} value={datasetDraft.content} onChange={(event) => setDatasetDraft({ ...datasetDraft, content: event.target.value })} spellCheck={false} aria-label="数据集内容" />
          <div className="task-dataset-mapping">
            <label>题目字段 *<input value={datasetDraft.promptField} onChange={(event) => setDatasetDraft({ ...datasetDraft, promptField: event.target.value })} placeholder="prompt 或 case.question" /></label>
            <label>Case ID<input value={datasetDraft.idField} onChange={(event) => setDatasetDraft({ ...datasetDraft, idField: event.target.value })} placeholder="id" /></label>
            <label>标题<input value={datasetDraft.titleField} onChange={(event) => setDatasetDraft({ ...datasetDraft, titleField: event.target.value })} placeholder="title（可空）" /></label>
            <label>期望答案<input value={datasetDraft.expectedField} onChange={(event) => setDatasetDraft({ ...datasetDraft, expectedField: event.target.value })} placeholder="expected（可空）" /></label>
            <label>工作区文件<input value={datasetDraft.workspaceField} onChange={(event) => setDatasetDraft({ ...datasetDraft, workspaceField: event.target.value })} placeholder="fixtures（对象，可空）" /></label>
            <label>元数据<input value={datasetDraft.metadataField} onChange={(event) => setDatasetDraft({ ...datasetDraft, metadataField: event.target.value })} placeholder="metadata（可空）" /></label>
          </div>
          <details className="task-dataset-evaluator"><summary>高级 · 自定义确定性评分模板</summary><textarea rows={5} value={datasetEvaluation} onChange={(event) => setDatasetEvaluation(event.target.value)} placeholder={'留空时用 expected 做 response_contains；也可填 {"pass_score":1,"checks":[{"type":"json_equals","path":"answer.json","pointer":"/answer","expected":"${expected}"}]}'} /></details>
          <div><button disabled={busy || !datasetDraft.promptField.trim()} onClick={previewDataset}>预览字段映射</button><button disabled={busy || !datasetDraft.id.trim() || !datasetPreview} onClick={saveDataset}>固化并加入题库</button></div>
          {datasetPreview && <div className="task-dataset-preview"><b>{datasetPreview.row_count} cases · {datasetPreview.fields?.join(', ')}</b>{datasetPreview.cases?.slice(0, 3).map((item: any) => <span key={item.id}><code>{item.id}</code>{item.prompt}</span>)}</div>}
        </details>
        {datasets.length > 0 && <div className="task-dataset-filters"><button className={!datasetFilter ? 'active' : ''} onClick={() => setDatasetFilter('')}>全部 {tasks.length}</button>{datasets.map((dataset) => <button key={dataset.id} className={datasetFilter === dataset.id ? 'active' : ''} onClick={() => { setDatasetFilter(dataset.id); setSelectedTaskId(dataset.tasks?.[0] || ''); }} title={`${dataset.format} · sha256 ${dataset.source_sha256}`}><b>{dataset.title}</b><small>{dataset.row_count} cases</small></button>)}</div>}
        <div className="task-section-label">题目库 · {visibleTasks.length}{datasetFilter ? ` / ${tasks.length}` : ''}</div>
        <div className="task-list">
          {visibleTasks.map((task) => (
            <button key={task.id} disabled={Boolean(run?.running)} className={`task-card ${task.id === selectedTaskId ? 'active' : ''}`} onClick={() => { setRun(null); setSelectedTaskId(task.id); setCompactLibraryOpen(false); }}>
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
            <div key={item.id} className="task-history-row">
              <label title="选择两到八条轨迹进行并排比较"><input type="checkbox" checked={Boolean(item.id && selectedRunIds.includes(item.id))} onChange={(event) => item.id && setSelectedRunIds((current) => event.target.checked ? [...current, item.id!] : current.filter((id) => id !== item.id))} /></label>
              <button onClick={() => item.id && openHistory(item.id)}><span>{item.task_id}</span><small>{item.selection?.runner === 'codex_cli' ? 'Original Codex CLI' : `${item.selection?.harness || 'Flow'} · ${item.selection?.harness_version?.slice(0, 10) || 'legacy'}`}</small></button>
              {item.id && item.recovery_available
                ? <button className="task-recover" disabled={busy} onClick={() => recoverHistory(item.id!)} title="从最后一个安全的已完成 checkpoint 创建恢复运行">↻</button>
                : <span className="task-recover-space" />}
              <StatusPill status={item.status || 'created'} />
            </div>
          ))}
          {!runHistory.length && <small>还没有运行记录</small>}
        </div>
        <button className="task-compare-launch" disabled={busy || selectedRunIds.length < 2} onClick={compareSelectedRuns}>比较所选轨迹 ({selectedRunIds.length})</button>
      </aside>

      <main className="task-main">
        <div className="task-compact-picker">
          <label>选择题目 <select aria-label="选择题目" value={selectedTaskId} disabled={Boolean(run?.running)} onChange={event => { setRun(null); setSelectedTaskId(event.target.value); }}>
            {visibleTasks.map(task => <option key={task.id} value={task.id}>{task.title}</option>)}
          </select></label>
          <button onClick={() => setCompactLibraryOpen(value => !value)}>{compactLibraryOpen ? '收起题库' : '题库 / 导入 / 历史'}</button>
        </div>
        <header className="task-header">
          <div>
            <div className="task-title-row"><h2>{selectedTask?.title || '选择一道题目'}</h2>{run && <StatusPill status={run.status} />}</div>
            <p>{selectedTask?.prompt}</p>
            <div className="task-tags">{selectedTask?.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
          </div>
          <div className="task-run-meta">
            {run ? <><code>{run.id}</code><span title={run.runner?.version || run.selection.harness_version}>{run.selection.runner === 'codex_cli' ? `Original Codex · ${run.runner?.version || 'version pending'}` : `Flow ${run.selection.harness_version?.slice(0, 15) || 'legacy'}`}</span><span>{run.task_step ? `task step ${run.task_step}` : `node step ${run.step_count}`}</span><span>{formatTime(run.started_at)}</span>{run.policy?.hidden_tools?.length ? <span title={run.policy.hidden_tools.join(', ')}>策略隐藏 {run.policy.hidden_tools.length} tools</span> : null}{run.selection.runner !== 'codex_cli' && <button onClick={() => publishWorkbenchEvent('replay-task-run', { runId: run.id })}>观察 / 回放</button>}</> : <span>尚未启动</span>}
          </div>
        </header>

        {ideContext.length > 0 && <section className="task-ide-context">
          <div><b>来自 IDE 的任务上下文</b><small>会复制到隔离题目工作区并写入可复现运行记录。</small></div>
          <div>{ideContext.map((item, index) => <button key={`${item.path}:${item.startLine || 0}:${index}`} onClick={() => openFileInIde(item.path, item.startLine || 1, item.endLine)} title={item.path}>
            {item.kind === 'selection' ? '选区' : '文件'} · {item.relativePath || item.path.split(/[\\/]/).pop()} {item.startLine ? `L${item.startLine}${item.endLine && item.endLine !== item.startLine ? `–${item.endLine}` : ''}` : ''}
          </button>)}<button className="clear" onClick={() => { setIdeContext([]); updateWorkbenchSession({ handoff: { items: [], updatedAt: Date.now() } }); }}>清除</button></div>
        </section>}

        <section className="task-config-bar">
          <label>Runner<select value={runnerName} onChange={(event) => setRunnerName(event.target.value as 'ego_flow' | 'codex_cli')} disabled={!!run?.running}>
            {(options.runners || []).map((item) => <option key={item.name} value={item.name} disabled={!item.available}>{item.display_name}{!item.available ? ' · 未检测到' : ''}</option>)}
          </select></label>
          <label className={runnerName === 'codex_cli' ? 'task-config-disabled' : ''}>Harness<select value={harnessName} onChange={(event) => setHarnessName(event.target.value)} disabled={!!run?.running || runnerName === 'codex_cli'}>
            {compatibleHarnesses.map((item) => <option key={item.name} value={item.name}>{item.name} · {item.node_count} nodes</option>)}
          </select></label>
          <label className={runnerName === 'codex_cli' ? 'task-config-disabled' : ''}>Flow version<select value={harnessVersion} onChange={(event) => setHarnessVersion(event.target.value)} disabled={!!run?.running || runnerName === 'codex_cli'}>
            {harnessVersionOptions.slice().reverse().map((version) => <option key={version.id} value={version.id}>{version.id === selectedHarness?.latest_version || version.id === harnessVersionOptions[harnessVersionOptions.length - 1]?.id ? '最新 · ' : ''}{version.label} · {version.id.slice(0, 15)}</option>)}
          </select></label>
          <label className={runnerName === 'codex_cli' ? 'task-config-disabled' : ''}>Identity<select value={identityName} onChange={(event) => setIdentityName(event.target.value)} disabled={!!run?.running || runnerName === 'codex_cli'}>
            {compatibleIdentities.map((item) => <option key={item.name} value={item.name}>{item.name}{item.role ? ` · ${item.role}` : ''}</option>)}
          </select></label>
          <div className="task-env-picker">
            <span>Environment</span>
            <div className="task-env-summary">{selectedTask?.environment.backend === 'container' ? 'Docker 容器' : '本地独立目录（非 OS 沙箱）'} · {selectedTask?.environment.network === 'disabled' ? '网络工具禁用' : '继承网络'}</div>
            {options.environments.map((environment) => <label key={environment.name}><input type="checkbox" checked={environmentNames.includes(environment.name)} onChange={(event) => setEnvironmentNames((current) => event.target.checked ? [...current, environment.name] : current.filter((name) => name !== environment.name))} />{environment.name}</label>)}
          </div>
          <label className="task-debug-toggle"><input type="checkbox" checked={startPaused} onChange={(event) => setStartPaused(event.target.checked)} disabled={!!run?.running || runnerName === 'codex_cli'} /> 首节点前暂停</label>
          {!run?.running ? <button className="task-launch" disabled={busy || !selectedTask || (runnerName !== 'codex_cli' && (!options.identities.length || !harnessName || !identityName)) || (runnerName === 'codex_cli' && !options.runners?.find((item) => item.name === 'codex_cli')?.available)} onClick={launch}>{busy ? '准备中…' : '▶ 开始做题'}</button> : <div className="task-controls">
            {run.selection.runner !== 'codex_cli' && <><button onClick={() => control('pause')} disabled={run.paused}>⏸</button><button onClick={() => control('step')}>单步</button><button onClick={() => control('auto')}>自动</button></>}<button className="danger" onClick={() => control('stop')}>停止</button>
          </div>}
        </section>

        {runnerName === 'codex_cli' && <div className="task-evolution-notice">⇄ 对照基线：直接调用已安装的原版 Codex CLI。它不使用 EgoAgent Identity/Flow；原始 JSONL、版本、文件产物和确定性评分会进入同一运行记录。安全边界是 Codex 自带 workspace-write，而不是 EgoAgent Flow 的逐节点权限策略。</div>}

        {selectedHarness && Object.keys(selectedHarness.slots || {}).length > 1 && (
          <section className="task-slot-bindings"><b>多 Agent Slot</b>{Object.keys(selectedHarness.slots).map((slot) => <label key={slot}><span>@{slot}</span><select value={slotBindings[slot] || selectedHarness.slots[slot]?.identity || identityName} onChange={(event) => setSlotBindings((current) => ({ ...current, [slot]: event.target.value }))}>{compatibleIdentities.map((identity) => <option key={identity.name} value={identity.name}>{identity.name}</option>)}</select></label>)}</section>
        )}
        {selectedTask?.evolution.allowed && <div className="task-evolution-notice">🧬 此题允许结构/能力进化。Harness、Identity、Skill、Knowledge 的新增与修改会被记录为评分证据，并实时显示。</div>}
        {selectedTask?.steps?.length ? <div className="task-evolution-notice">⇥ 多步骤任务共 {selectedTask.steps.length} 阶段；默认每阶段刷新模型上下文，但共享容器和工作区。只有题目声明 resume_trajectory 才续接对话。</div> : null}
        {selectedTask?.environment.backend === 'container' && !compatibility?.docker?.available ? <div className="task-error">此题需要 Docker；当前诊断：{compatibility?.docker?.reason || 'Docker 不可用'}</div> : null}
        {error && <div className="task-error">{error}</div>}
        {configError && !run && <div className="task-error">{configError} <button onClick={reloadHarness}>重试 Flow 预览</button></div>}

        <section className="task-workbench">
          <div className="task-dag-panel">
            <div className="task-panel-title"><span>Flow 运行面板</span><div className="task-panel-actions">{(!run || run.selection.runner === 'codex_cli') && <button className={showMinimap ? 'active' : ''} onClick={() => setShowMinimap((visible) => !visible)}>{showMinimap ? '隐藏概览' : '概览'}</button>}<small>{run?.paused ? `暂停在 ${run.pending_node}` : run?.running ? `正在执行 ${run.current_node || '准备中'}` : run ? '查看真实运行记录' : `${graph.nodes.length} nodes`}</small></div></div>
            {run?.selection.runner === 'codex_cli' && (selectedTask?.evolution.allowed || liveRuns.length > 1 || liveChanges.length > 0) && <div className="task-live-architecture">
              <LiveAgentArchitecture
                root={{
                  runId: rootLiveRun?.runId || '',
                  harness: rootLiveRun?.harness || harnessName,
                  slots: rootLiveRun?.slots || slotBindings,
                  status: run?.running ? 'running' : run?.status || 'idle',
                  currentNode: run?.pending_node || run?.current_node,
                  stepCount: run?.step_count || 0,
                }}
                runs={liveRuns}
                changes={liveChanges}
                events={liveStory}
                compact={!run?.running && liveChanges.length === 0}
              />
            </div>}
            {run && run.selection.runner !== 'codex_cli' ? <FlowRunViewer rootId={run.id} onAlbum={() => publishWorkbenchEvent('navigate', { tab: 'observe' })} /> : <ReactFlowProvider>
              <ReactFlow key={`${harnessName}:${harnessVersion}:${graph.nodes.map(node => node.id).join('|')}`} nodes={graph.nodes} edges={graph.edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} onlyRenderVisibleElements={false} minZoom={0.08} fitView nodesDraggable={false} nodesConnectable={false} elementsSelectable onNodeClick={(_event, node) => {
                const trace = [...(run?.node_traces || [])].reverse().find((item) => item.node_id === node.id) || null;
                setSelectedTrace(trace); setDetailTab('timeline');
              }}>
                <Background gap={22} size={1} /><Controls showInteractive={false} />{showMinimap && <MiniMap pannable zoomable />}
              </ReactFlow>
            </ReactFlowProvider>}
            {activeTrace && run?.selection.runner === 'codex_cli' && <aside className="task-trace-peek">
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
      {comparison && <section className="task-comparison-overlay" style={{ '--compare-lanes': comparison.runs?.length || 2 } as any} role="dialog" aria-modal="true" aria-label="轨迹对比">
        <header><div><b>轨迹对比</b><small>{comparison.same_task ? '同一题目的 Flow / Identity / 版本对照' : '不同题目；分数不可直接归因于 Flow'}</small></div><button onClick={() => setComparison(null)}>×</button></header>
        <div className="task-comparison-summary">{comparison.runs?.map((item: any) => <article key={item.id}>
          <code>{item.id}</code><b>{item.runner === 'codex_cli' ? 'Original Codex CLI' : `${item.harness} · ${item.identity}`}</b><small>{item.runner === 'codex_cli' ? item.runner_version : item.harness_version}</small>{item.runner !== 'codex_cli' && <button onClick={() => { setComparison(null); publishWorkbenchEvent('replay-task-run', { runId: item.id }); }}>观察 / 回放</button>}
          <strong>{item.score === null || item.score === undefined ? '—' : `${Math.round(item.score * 100)}/100`}</strong>
          <span>{item.status} · {item.duration_seconds ?? '—'}s · {item.model_calls ?? '—'} model · {item.tool_calls ?? '—'} tools</span>
        </article>)}</div>
        <div className="task-comparison-traces">
          <div className="task-comparison-head"><span>#</span>{comparison.runs?.map((item: any) => <b key={item.id}>{item.runner === 'codex_cli' ? 'Original Codex' : item.harness}<small>{(item.runner === 'codex_cli' ? item.runner_version : item.harness_version)?.slice(0, 24)}</small></b>)}</div>
          {comparison.trace_rows?.slice(0, 250).map((row: any) => <div key={row.index} className={row.diverged ? 'diverged' : ''}><span>{row.index}</span>{row.lanes.map((lane: any, index: number) => lane ? <article key={index}><b>{lane.node_id}</b><small>{lane.op}{lane.agent ? ` · @${lane.agent}` : ''} · {lane.status}</small>{lane.tool_names?.length ? <em>🔧 {lane.tool_names.join(', ')}</em> : lane.model_response ? <em>{lane.model_response.slice(0, 160)}</em> : null}</article> : <article key={index} className="missing">此 Flow 已结束</article>)}</div>)}
        </div>
      </section>}
    </div>
  );
}
