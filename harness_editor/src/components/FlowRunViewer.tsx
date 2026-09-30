import { useEffect, useMemo, useRef, useState } from 'react';
import { Background, Controls, ReactFlow, ReactFlowProvider, useNodesState } from '@xyflow/react';
import { configToFlow } from '../flowGraph';
import PipelineNode from '../nodes/PipelineNode';
import ConditionEdge from '../edges/ConditionEdge';
import { contractFor, type DagContractCatalog } from './DagFormEditors';
import * as api from '../api/client';
import type { HarnessConfig, NodeTrace } from '../types';
import './FlowRunViewer.css';

export type ObservedEvent = { sequence: number; run_id: string; time: number; type: string; graph_id: string; data: Record<string, any> };
export type ObservedRun = { id: string; root_id: string; parent_id?: string; status: string; graph_id: string; metadata: Record<string, any> };
type Frame = { runs: ObservedRun[]; events: ObservedEvent[]; graphs: Record<string, HarnessConfig>; base_graphs?: {run_id: string; graph_id: string}[] };
const nodeTypes = { pipelineNode: PipelineNode };
const edgeTypes = { conditionEdge: ConditionEdge };
const pretty = (value: unknown) => typeof value === 'string' ? value : JSON.stringify(value, null, 2);
const eventLabel: Record<string, string> = {
  graph_snapshot: '执行图快照', run_started: '运行开始', node_enter: '进入节点', node_input: '节点输入',
  node_output: '节点输出', node_exit: '离开节点', model_request: '模型请求', model_response: '模型回复',
  token: '流式回复', tool: '工具结果', tool_start: '调用工具', tool_call: '调用工具',
  harness_mutation: '修改库中 Flow（不等于已热替换）', context_compacted: '上下文压缩',
  observation_finished: '运行结束', waiting_input: '等待输入', approval_required: '等待审批',
  debug_paused: '执行前暂停', debug_resumed: '继续执行', cancelled: '已停止',
  input_required: '等待用户输入', tool_end: '工具结束', action_observation: '工具执行观察', label: 'Agent 开始回复',
};

function RecordedGraph({ config, events, selectedNode, onSelect }: {
  config: HarnessConfig; events: ObservedEvent[]; selectedNode: string; onSelect: (id: string) => void;
}) {
  const [nodes, setNodes, onNodesChange] = useNodesState<any>([]);
  const [instance, setInstance] = useState<any>(null);
  const [contracts, setContracts] = useState<DagContractCatalog | null>(null);
  useEffect(() => { let active = true; api.getDagContracts().then(value => { if (active) setContracts(value); }).catch(() => {}); return () => { active = false; }; }, []);
  const shape = useMemo(() => configToFlow(config), [config]);
  const nodeSignature = shape.nodes.map(node => `${node.id}:${node.position.x}:${node.position.y}`).join('|');
  const projection = useMemo(() => {
    const latest = new Map<string, NodeTrace>();
    let active = '';
    let paused = false;
    for (const event of events) {
      if (['done', 'observation_finished', 'cancelled', 'error'].includes(event.type)) {
        if (active && latest.has(active) && latest.get(active)?.status === 'running') latest.get(active)!.status = 'error';
        active = ''; paused = false;
      }
      if (event.type === 'debug_paused') paused = true;
      if (event.type === 'debug_resumed') paused = false;
      const data = event.data;
      const id = String(data.node_id || '');
      if (!id) continue;
      let trace = latest.get(id);
      if (!trace || event.type === 'node_input') {
        trace = { sequence: event.sequence, node_id: id, op: data.op || '', agent: data.agent, status: 'running', model: {}, tools: [] };
        latest.set(id, trace);
      }
      if (event.type === 'node_input') { trace.input = data.input; trace.last_output = data.last_output; }
      if (event.type === 'node_enter') active = id;
      if (event.type === 'node_output') trace.output = data.output ?? data;
      if (event.type === 'node_exit') { trace.status = data.status === 'error' ? 'error' : 'completed'; if (active === id) active = ''; }
      if (event.type === 'token') trace.model.response = String(trace.model.response || '') + String(data.text || '');
      if (event.type === 'model_request') trace.model.request = data;
      if (event.type === 'model_response') trace.model.response = data.content ?? data.text ?? data;
      if (event.type === 'tool') trace.tools.push({ name: data.name || 'tool', arguments: data.arguments, result: data.result });
      if (event.type === 'error') trace.status = 'error';
    }
    return { latest, active, paused };
  }, [events]);
  useEffect(() => {
    setNodes(shape.nodes.map(node => ({ ...node, selected: node.id === selectedNode,
      data: { ...node.data, id: node.id, runtimeTrace: projection.latest.get(node.id),
        _contract: contractFor(contracts, String(node.data.op || '')),
        runtimeStatus: projection.latest.get(node.id)?.status, highlight: projection.active === node.id,
        runtimeActivityMode: projection.active === node.id ? 'active' : undefined,
        runtimePaused: projection.active === node.id && projection.paused,
      },
    })));
  }, [shape, projection, selectedNode, setNodes, contracts]);
  useEffect(() => {
    if (!instance) return;
    const timer = window.setTimeout(() => instance.fitView({ padding: 0.2, duration: 180, minZoom: 0.08 }), 100);
    return () => window.clearTimeout(timer);
  }, [instance, nodeSignature, contracts]);
  const edges = useMemo(() => shape.edges.map(edge => ({ ...edge, data: { ...edge.data, editable: false } })), [shape]);
  return <ReactFlow nodes={nodes} edges={edges} onNodesChange={changes => onNodesChange(changes.filter(change => change.type === 'dimensions'))}
    nodeTypes={nodeTypes} edgeTypes={edgeTypes} onInit={setInstance} onNodeClick={(_event, node) => onSelect(node.id)}
    nodesDraggable={false} nodesConnectable={false} deleteKeyCode={null} minZoom={0.08} fitView onlyRenderVisibleElements={false}>
    <Background /><Controls showInteractive={false} />
  </ReactFlow>;
}

export default function FlowRunViewer({ rootId, recordingId = '', onAlbum }: {
  rootId: string; recordingId?: string; onAlbum?: () => void;
}) {
  const [frame, setFrame] = useState<Frame>({ runs: [], events: [], graphs: {} });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [follow, setFollow] = useState(!recordingId);
  const [playing, setPlaying] = useState(false);
  const [cursor, setCursor] = useState(-1);
  const [runId, setRunId] = useState('');
  const [nodeId, setNodeId] = useState('');
  const [previewGraph, setPreviewGraph] = useState('');
  const [recording, setRecording] = useState<any>(null);
  const [notice, setNotice] = useState('');
  const generation = useRef(0);

  useEffect(() => {
    const gen = ++generation.current;
    let cancelled = false;
    let after = 0;
    let timer = 0;
    setFrame({ runs: [], events: [], graphs: {} }); setCursor(-1); setRunId(''); setNodeId('');
    setFollow(!recordingId); setPlaying(false); setRecording(null); setNotice(''); setError(''); setPreviewGraph('');
    const poll = async () => {
      setLoading(true);
      try {
        const data = await api.readFlowObservation(rootId, after, recordingId);
        if (cancelled) return;
        after = data.cursor;
        setFrame(previous => {
          const addedGraphs = Object.fromEntries(Object.entries(data.graphs).filter(([id]) => !previous.graphs[id]));
          const sameRuns = JSON.stringify(previous.runs) === JSON.stringify(data.runs);
          if (sameRuns && !data.events.length && !Object.keys(addedGraphs).length) return previous;
          return { runs: sameRuns ? previous.runs : data.runs,
            events: data.events.length ? [...previous.events, ...data.events] : previous.events,
            graphs: Object.keys(addedGraphs).length ? { ...previous.graphs, ...addedGraphs } as Frame['graphs'] : previous.graphs,
            base_graphs: data.base_graphs };
        });
        if (data.recording) setRecording(data.recording);
        setError('');
        if (data.has_more || !recordingId || data.recording?.end_sequence == null) {
          timer = window.setTimeout(poll, data.has_more ? 40 : 1100);
        }
      } catch (reason) {
        if (!cancelled) { setError((reason as Error).message); timer = window.setTimeout(poll, 3000); }
      } finally { if (!cancelled) setLoading(false); }
    };
    void poll();
    if (!recordingId) void api.listFlowRecordings().then(items => {
      if (gen === generation.current) setRecording(items.find((item: any) => item.root_id === rootId && item.end_sequence == null) || null);
    }).catch(() => {});
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [rootId, recordingId]);

  const end = frame.events.length - 1;
  const position = follow ? end : Math.min(cursor, end);
  const currentEvent = frame.events[position];
  const visible = useMemo(() => frame.events.slice(0, position + 1), [frame.events, position]);
  const selectedRun = frame.runs.find(run => run.id === runId) || frame.runs.find(run => run.id === currentEvent?.run_id) || frame.runs[0];
  const runEvents = useMemo(() => visible.filter(event => event.run_id === selectedRun?.id), [visible, selectedRun?.id]);
  const graphId = runEvents[runEvents.length - 1]?.graph_id || frame.base_graphs?.find(item => item.run_id === selectedRun?.id)?.graph_id
    || frame.events.find(event => event.run_id === selectedRun?.id)?.graph_id || selectedRun?.graph_id;
  const config = frame.graphs[previewGraph || graphId || ''];
  const nodeEvents = nodeId ? runEvents.filter(event => event.data.node_id === nodeId) : currentEvent ? [currentEvent] : [];
  const structureEvents = visible.filter(event => event.type === 'harness_mutation' || (event.type === 'graph_snapshot' && event.data.reason === 'active_graph_changed'));
  useEffect(() => {
    if (!playing) return;
    const timer = window.setInterval(() => setCursor(value => {
      if (value >= end) { setPlaying(false); return value; }
      return value + 1;
    }), 350);
    return () => window.clearInterval(timer);
  }, [playing, end]);
  const seek = (value: number) => { setFollow(false); setPlaying(false); setCursor(value); setNodeId(''); setPreviewGraph(''); };
  const record = async (action: 'start' | 'stop' | 'save') => {
    try {
      const saved = await api.recordFlowObservation({ action, root_id: rootId, recording_id: recording?.id,
        title: `${selectedRun?.metadata.harness || 'Flow'} · ${new Date().toLocaleString()}` });
      if (action !== 'save') setRecording(saved);
      setNotice(action === 'start' ? '录制已开始；从当前事件位置保存' : '已保存到运行相簿');
    } catch (reason) { setError((reason as Error).message); }
  };
  return <section className="flow-observer" aria-label="统一 Flow 运行查看器">
    <header className="observer-toolbar">
      <strong>{recordingId ? '◷ 轨迹回放' : '◉ 实时 Flow'} <small>{rootId.slice(-12)}</small></strong>
      <span>{selectedRun?.metadata.entry_type} · {selectedRun?.metadata.harness} · {({ running: '运行中', completed: '已完成', paused: '已暂停', waiting_input: '等待用户输入', waiting_approval: '等待审批', cancelled: '已停止', error: '执行失败', recording_boundary: '录制在此结束' } as Record<string,string>)[selectedRun?.status || ''] || selectedRun?.status || '准备中'}</span>
      {!recordingId && <><button disabled={!selectedRun} onClick={() => void record(recording?.end_sequence == null && recording ? 'stop' : 'start')}>
        {recording?.end_sequence == null && recording ? '■ 停止录制' : '● 开始录制'}</button>
        <button disabled={!selectedRun} onClick={() => void record('save')}>保存完整运行到相簿</button></>}
      {onAlbum && <button onClick={onAlbum}>运行相簿 ↗</button>}
    </header>
    {error && <div role="alert" className="observer-notice">{error}</div>}
    {notice && <div role="status" className="observer-notice">{notice}</div>}
    {previewGraph && <div className="observer-notice">库中修改预览（不是当前执行图） <button onClick={() => setPreviewGraph('')}>返回实际执行图</button></div>}
    <div className="observer-meta">
      <label>Agent / 子 Flow <select value={runId} onChange={event => { setRunId(event.target.value); setNodeId(''); setPreviewGraph(''); }}>
        <option value="">跟随当前事件</option>
        {frame.runs.map(run => <option key={run.id} value={run.id}>{run.parent_id ? '↳ ' : ''}{run.metadata.harness} · {run.id.slice(-6)}</option>)}
      </select></label>
      <span title={selectedRun?.metadata.workspace}>{selectedRun?.metadata.workspace}</span>
      <span>版本 {selectedRun?.metadata.flow_version || graphId?.slice(0, 12) || '—'}</span>
      {selectedRun?.parent_id && <span>父节点 {selectedRun.metadata.parent_node_id}</span>}
    </div>
    <div className="observer-body">
      <div className="observer-canvas">
        {config?.pipeline?.nodes ? <ReactFlowProvider key={selectedRun?.id}><RecordedGraph config={config} events={runEvents} selectedNode={nodeId} onSelect={setNodeId} /></ReactFlowProvider>
          : <div className="observer-empty">{loading ? '正在读取图与事件…' : '等待 Flow 进入执行器。准备环境时尚无节点事件；旧版运行没有统一录制，请查看原始历史。'}</div>}
      </div>
      <aside className="observer-inspector">
        <strong>{nodeId ? `节点 ${nodeId} · 本位置之前的输入输出` : '当前事件 · 点节点查看输入输出'}</strong>
        {nodeEvents.slice(-30).map(event => <details key={event.sequence} open={nodeEvents.length === 1}>
          <summary>#{event.sequence} {eventLabel[event.type] || event.type}</summary><pre>{pretty(event.data)}</pre>
        </details>)}
        {nodeEvents.length > 30 && <small>节点详情显示最近 30 条；时间线可定位更早事件。</small>}
        {!!structureEvents.length && <details><summary>结构变化 · {structureEvents.length}</summary>
          {structureEvents.map(event => <details key={event.sequence}><summary>#{event.sequence} {eventLabel[event.type]}</summary>
            <p>主画布始终是实际执行图。以下是库中编辑的独立快照，不暗示已生效。</p>
            {['before_graph_id', 'after_graph_id'].map(key => event.data[key] && <details key={key}><summary>{key.startsWith('before') ? '修改前' : '修改后'}</summary><button onClick={() => setPreviewGraph(event.data[key])}>在画布预览此版本</button><pre>{pretty(frame.graphs[event.data[key]])}</pre></details>)}
          </details>)}
        </details>}
      </aside>
    </div>
    <footer className="observer-playback">
      <button disabled={position < 0} onClick={() => seek(position - 1)}>← 上一步</button>
      <button disabled={!frame.events.length} onClick={() => { setFollow(false); setCursor(position >= end ? -1 : position); setPlaying(!playing); }}>{playing ? '暂停回放' : '▶ 播放'}</button>
      <button disabled={position >= end} onClick={() => seek(position + 1)}>下一步 →</button>
      <input aria-label="回放事件位置" type="range" min={-1} max={Math.max(0, end)} value={position} onChange={event => seek(Number(event.target.value))} />
      <span>{position + 1} / {frame.events.length}</span>
      {!recordingId && <button className={follow ? 'active' : ''} onClick={() => { setFollow(true); setPlaying(false); setNodeId(''); }}>跟随实时</button>}
    </footer>
    <div className="observer-timeline" aria-label="运行事件时间线">
      {frame.events.slice(Math.max(0, position - 35), Math.max(position + 1, 60)).map(event => <button key={event.sequence}
        className={event.sequence === currentEvent?.sequence ? 'active' : ''} onClick={() => seek(frame.events.indexOf(event))}>
        <small>{new Date(event.time * 1000).toLocaleTimeString()}</small> #{event.sequence} {event.data.node_id || ''} · {eventLabel[event.type] || event.type}
      </button>)}
    </div>
    <small className="observer-disclaimer">只读观察与回放，不重跑工具。图与事件已脱敏；完整模型请求仍保存于原 trajectory 训练记录。控制运行请回到原入口。</small>
  </section>;
}
