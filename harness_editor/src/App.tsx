import { lazy, Suspense, useState, useCallback, useRef, useEffect, type DragEvent } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  type Node,
  type Edge,
  type Connection,
  type OnConnect,
  ReactFlowProvider,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import Sidebar from './components/Sidebar';
import RightPanel from './components/RightPanel';
import { contractFor, type DagContractCatalog } from './components/DagFormEditors';
import RunObservability, { type ChangeEntry } from './components/RunObservability';
import PipelineNodeComponent from './nodes/PipelineNode';
import ConditionEdge from './edges/ConditionEdge';
import * as api from './api/client';
import { EMBEDDED_IN_IDE, INITIAL_TAB, WORKSPACE, isCurrentWorkspace } from './api/runtime';
import type { HarnessConfig, PipelineNode, EdgeCondition, OpType, ExecutionState, NodeTrace } from './types';
import {
  loadWorkbenchSession,
  publishWorkbenchEvent,
  updateWorkbenchSession,
  type WorkbenchRoute,
} from './workbenchSession';
import type { IdeContextItem } from './ideBridge';
import {
  appendMessageTokenBatch,
  appendTraceTokenBatch,
  renderTraceValue,
  stripEventEnvelope,
  traceSnapshotSignature,
  updateLatestTrace,
  type ChatMessage,
  type PendingStreamToken,
} from './executionProjection';

const nodeTypes = { pipelineNode: PipelineNodeComponent };
const edgeTypes = { conditionEdge: ConditionEdge };

// EgoAgent has several data-heavy workbenches. Keep the DAG editor fast by only
// downloading and evaluating a workbench when the user opens it.
const IdentityManager = lazy(() => import('./components/IdentityManager'));
const EnvironmentManager = lazy(() => import('./components/EnvironmentManager'));
const SessionExplorer = lazy(() => import('./components/SessionExplorer'));
const Settings = lazy(() => import('./components/Settings'));
const EvolutionPanel = lazy(() => import('./components/EvolutionPanel'));
const TaskBench = lazy(() => import('./components/TaskBench'));
const ChangeDashboard = lazy(() => import('./components/ChangeDashboard'));
const CheckpointDashboard = lazy(() => import('./components/CheckpointDashboard'));
const BackgroundRuns = lazy(() => import('./components/BackgroundRuns'));
const PackageMarketplace = lazy(() => import('./components/PackageMarketplace'));
const CapabilityLibrary = lazy(() => import('./components/CapabilityLibrary'));
const EgoIRWorkbench = lazy(() => import('./components/EgoIRWorkbench'));
const ResearchLab = lazy(() => import('./components/ResearchLab'));
const StudioHome = lazy(() => import('./components/StudioHome'));
const CoCCharacterDesk = lazy(() => import('./components/CoCCharacterDesk'));

const DEFAULT_CONFIG: HarnessConfig = {
  name: 'new_harness',
  description: '',
  slots: {},
  prompts: {},
  return_mode: 'all',
  pipeline: { start: '', max_steps: 100, workspace_preview: false, nodes: {} },
};

type TabType = WorkbenchRoute;

const STUDIO_TABS: Array<{ id: TabType; icon: string; label: string; detail: string; group: 'primary' | 'manage' | 'system' }> = [
  { id: 'home', icon: '⌂', label: 'Home', detail: '构建、评测、改进与发布', group: 'primary' },
  { id: 'harness', icon: '◇', label: 'Build', detail: 'Identity + EGO + DAG', group: 'primary' },
  { id: 'tasks', icon: '▦', label: 'Evaluate', detail: '任务、数据集、回放与评分', group: 'primary' },
  { id: 'library', icon: '▤', label: 'Library', detail: '发现并复用本地能力', group: 'primary' },
  { id: 'evolution', icon: '↗', label: 'Improve', detail: '从真实失败到可信演进', group: 'primary' },
  { id: 'packages', icon: '⬡', label: 'Deploy', detail: '版本化能力包与发布', group: 'manage' },
  { id: 'ir', icon: '⌘', label: 'EgoIR', detail: '轻量 Agent IR', group: 'manage' },
  { id: 'research', icon: '⌬', label: 'Research', detail: '科研实验与契约', group: 'manage' },
  { id: 'coc', icon: '◐', label: 'CoC Table', detail: '人物卡、模组与多 Agent 跑团', group: 'manage' },
  { id: 'background', icon: '◉', label: 'Background', detail: '后台 Agent 运行', group: 'manage' },
  { id: 'changes', icon: '±', label: 'Agent Changes', detail: '逐块审阅文件改动', group: 'manage' },
  { id: 'checkpoints', icon: '◷', label: 'Checkpoints', detail: '快照与恢复', group: 'manage' },
  { id: 'identity', icon: '◎', label: 'Identity', detail: '角色、Ego 与能力', group: 'manage' },
  { id: 'environment', icon: '◈', label: 'Environment', detail: '工具与运行环境', group: 'manage' },
  { id: 'sessions', icon: '▥', label: 'Sessions', detail: '会话与执行记录', group: 'manage' },
  { id: 'settings', icon: '⚙', label: 'Settings', detail: '模型与 Workbench 设置', group: 'system' },
];

const DEFAULT_TAB_META = STUDIO_TABS[0];

const STUDIO_TAB_IDS = new Set<TabType>(STUDIO_TABS.map((item) => item.id));

function readInitialTab(): TabType {
  const requested = INITIAL_TAB as TabType | null;
  if (requested && STUDIO_TAB_IDS.has(requested)) return requested;
  const restored = loadWorkbenchSession().route;
  return restored && STUDIO_TAB_IDS.has(restored) ? restored : 'home';
}

function StudioPageFallback() {
  return (
    <div className="studio-page-loading" role="status">
      <span className="studio-loading-mark" />
      <div><strong>正在打开工作台</strong><small>仅在需要时加载，保持 IDE 响应流畅</small></div>
    </div>
  );
}

type InterruptedRun = {
  id: string;
  status: string;
  error?: string;
  checkpoint?: {
    phase?: string;
    node?: string;
    operation?: string;
    created_at?: number;
    pending_approvals?: Record<string, unknown>;
    artifacts?: string[];
    completed_steps?: Array<Record<string, unknown>>;
    revisions?: Record<string, unknown>;
  };
};

function defaultNodeData(id: string, op: OpType, contracts?: DagContractCatalog | null): PipelineNode {
  const base: PipelineNode = { id, op, edges: [], inputs: {}, outputs: {} };
  const defaults = contractFor(contracts, op)?.editor?.defaults || {};
  return { ...base, ...structuredClone(defaults) } as PipelineNode;
}

function configToFlow(config: HarnessConfig): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  const nodeEntries = Object.entries(config.pipeline.nodes);
  const cols = Math.ceil(Math.sqrt(nodeEntries.length || 1));

  nodeEntries.forEach(([id, pn], i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    nodes.push({
      id,
      type: 'pipelineNode',
      position: { x: 100 + col * 390, y: 80 + row * 220 },
      data: { ...pn },
    });
  });

  nodeEntries.forEach(([id, pn]) => {
    pn.edges.forEach((e) => {
      if (!e.to) return;
      edges.push({
        id: `${id}->${e.to}`,
        source: id,
        target: e.to,
        type: 'conditionEdge',
        data: { condition: e.condition },
      });
    });
  });

  return { nodes, edges };
}

function initialBuilderState(): { config: HarnessConfig; nodes: Node[]; edges: Edge[]; selectedNodeId: string | null; selectedEdgeId: string | null; showOutput: boolean; outputView: 'conversation' | 'timeline' } {
  const stored = loadWorkbenchSession().builder;
  const config = stored?.config?.pipeline?.nodes ? stored.config : DEFAULT_CONFIG;
  const graph = configToFlow(config);
  if (stored?.positions) {
    graph.nodes = graph.nodes.map((node) => ({
      ...node,
      position: stored.positions?.[node.id] || node.position,
    }));
  }
  return {
    config,
    ...graph,
    selectedNodeId: stored?.selectedNodeId || null,
    selectedEdgeId: stored?.selectedEdgeId || null,
    showOutput: stored?.showOutput === true,
    outputView: stored?.outputView === 'timeline' ? 'timeline' : 'conversation',
  };
}

function flowToConfig(config: HarnessConfig, flowNodes: Node[], flowEdges: Edge[]): HarnessConfig {
  const nodes: Record<string, PipelineNode> = {};

  flowNodes.forEach((n) => {
    const data = n.data as unknown as PipelineNode;
    // Preserve every runtime field. The old editor rebuilt a short whitelist,
    // silently deleting advanced configuration on every save.
    const node = { ...data, id: n.id, edges: [] } as PipelineNode;
    delete node.highlight;
    delete node.subHarness;
    delete node.runtimeStatus;
    delete node.runtimeCount;
    delete node.runtimeTrace;
    delete node.runtimeActivityMode;
    delete node.runtimePaused;
    delete node._contract;
    nodes[n.id] = node;
  });

  flowEdges.forEach((e) => {
    const src = nodes[e.source];
    if (src) {
      const condition = (e.data as any)?.condition || 'default';
      if (!src.edges.find((se) => se.to === e.target)) {
        src.edges.push({ condition, to: e.target });
      }
    }
  });

  return {
    ...config,
    pipeline: {
      ...config.pipeline,
      nodes,
    },
  };
}

let nodeIdCounter = 0;
function nextNodeId(): string {
  nodeIdCounter++;
  return `node_${nodeIdCounter}`;
}

const AGENT_COLORS: Record<string, string> = {
  '创意家': '#c084fc',
  '批评家': '#f87171',
  '裁判': '#fbbf24',
  '正方': '#4ade80',
  '反方': '#f87171',
  'guardian': '#60a5fa',
  'worker': '#22d3ee',
  'agent': '#22d3ee',
  'coder': '#22d3ee',
  'user': '#a3e635',
};

export default function App() {
  const restoredBuilderRef = useRef<ReturnType<typeof initialBuilderState> | null>(null);
  if (!restoredBuilderRef.current) restoredBuilderRef.current = initialBuilderState();
  const restoredBuilder = restoredBuilderRef.current;
  const [tab, setTab] = useState<TabType>(readInitialTab);
  const [showAdvancedNavigation, setShowAdvancedNavigation] = useState(false);
  const [runtimeOnline, setRuntimeOnline] = useState<boolean | null>(null);
  const [config, setConfig] = useState<HarnessConfig>(restoredBuilder.config);
  const [flowNodes, setFlowNodes, onNodesChange] = useNodesState<Node>(restoredBuilder.nodes);
  const flowContractSignature = flowNodes.map((node) => `${node.id}:${String((node.data as any).op || '')}`).join('|');
  const [flowEdges, setFlowEdges, onEdgesChange] = useEdgesState<Edge>(restoredBuilder.edges);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(restoredBuilder.selectedNodeId);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(restoredBuilder.selectedEdgeId);
  const [harnessList, setHarnessList] = useState<string[]>([]);
  const [componentList, setComponentList] = useState<api.HarnessCatalogItem[]>([]);
  const [identityList, setIdentityList] = useState<string[]>([]);
  const [dagContracts, setDagContracts] = useState<DagContractCatalog | null>(null);
  const [execState, setExecState] = useState<ExecutionState>({
    running: false,
    current_node: null,
    step_count: 0,
    messages_count: 0,
    debug_mode: 'auto',
    paused: false,
    pause_requested: false,
    pending_node: null,
    node_traces: [],
  });
  const activeExecutionRunId = useRef<string | undefined>(undefined);

  useEffect(() => {
    activeExecutionRunId.current = execState.run_id;
  }, [execState.run_id]);
  const [nodeTraces, setNodeTraces] = useState<NodeTrace[]>([]);
  const [selectedTraceSequence, setSelectedTraceSequence] = useState<number | null>(null);
  const [startPaused, setStartPaused] = useState(false);
  const [debugInputOverride, setDebugInputOverride] = useState('{}');
  const [debugSkipOutput, setDebugSkipOutput] = useState('{}');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const chatMsgId = useRef(0);
  const [inputText, setInputText] = useState('');
  const [saveMsg, setSaveMsg] = useState('');
  const [showOutput, setShowOutput] = useState(restoredBuilder.showOutput);
  const [showMinimap, setShowMinimap] = useState(false);
  const [outputView, setOutputView] = useState<'conversation' | 'timeline'>(restoredBuilder.outputView);
  const [waitingNodeId, setWaitingNodeId] = useState<string | null>(null);
  const [activeSubHarness, setActiveSubHarness] = useState<string | null>(null);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [rfInstance, setRfInstance] = useState<any>(null);
  const outputsRef = useRef<HTMLDivElement>(null);
  const flowNodesRef = useRef<Node[]>([]);
  flowNodesRef.current = flowNodes;
  const configRef = useRef(config);
  configRef.current = config;
  const [improveChanges, setImproveChanges] = useState<ChangeEntry[]>([]);
  const [interruptedRuns, setInterruptedRuns] = useState<InterruptedRun[]>([]);
  const [recoveryBusy, setRecoveryBusy] = useState<string | null>(null);
  const [approvalBusy, setApprovalBusy] = useState(false);

  const refreshInterruptedRuns = useCallback(async () => {
    try {
      const response = await api.listInterruptedRuns();
      setInterruptedRuns(Array.isArray(response?.runs) ? response.runs : []);
    } catch {
      // The durable queue is optional for a purely local editing session.
    }
  }, []);

  const handleRecovery = useCallback(async (run: InterruptedRun, action: 'resume' | 'discard') => {
    const inDoubt = run.checkpoint?.phase !== 'completed';
    if (action === 'resume' && inDoubt) {
      const confirmed = window.confirm(
        `任务 ${run.id.slice(0, 8)} 在节点 ${run.checkpoint?.node || 'unknown'} 中断。` +
        '请先检查文件和外部副作用；确认后该节点会重新执行。继续吗？',
      );
      if (!confirmed) return;
    }
    if (action === 'discard' && !window.confirm('丢弃这个中断任务？现有文件与产物不会被删除。')) return;
    setRecoveryBusy(run.id);
    try {
      await api.recoverDurableRun(run.id, action, { confirm_in_doubt: inDoubt });
      await refreshInterruptedRuns();
    } catch (error) {
      window.alert(error instanceof Error ? error.message : String(error));
    } finally {
      setRecoveryBusy(null);
    }
  }, [refreshInterruptedRuns]);

  useEffect(() => {
    // Runtime traces only affect the visual DAG. Avoid remapping every node
    // while the user is on Home, Evaluate, CoC, or another Studio workbench.
    if (tab !== 'harness') return;
    const recent = new Set(nodeTraces.slice(-3).map((trace) => trace.sequence));
    const activeNode = execState.pending_node || execState.current_node;
    const latestByNode = new Map<string, NodeTrace>();
    for (let index = nodeTraces.length - 1; index >= 0; index--) {
      const trace = nodeTraces[index];
      if (!latestByNode.has(trace.node_id)) latestByNode.set(trace.node_id, trace);
    }
    setFlowNodes((nodes) => {
      let changed = false;
      const next = nodes.map((node) => {
        const trace = latestByNode.get(node.id);
        const active = execState.running && node.id === activeNode;
        const activityMode = active ? 'active' : trace && recent.has(trace.sequence) ? 'recent' : undefined;
        const paused = active && execState.paused;
        if (
          (node.data as any).runtimeTrace === trace &&
          (node.data as any).runtimeActivityMode === activityMode &&
          Boolean((node.data as any).runtimePaused) === paused
        ) return node;
        changed = true;
        return {
          ...node,
          data: { ...node.data, runtimeTrace: trace, runtimeActivityMode: activityMode, runtimePaused: paused },
        };
      });
      return changed ? next : nodes;
    });
  }, [tab, nodeTraces, execState.current_node, execState.pending_node, execState.running, execState.paused, setFlowNodes]);

  useEffect(() => {
    refreshInterruptedRuns();
  }, [refreshInterruptedRuns]);

  useEffect(() => {
    // Harness and Identity catalogs are Builder-only data. Deferring these
    // directory scans makes the product Home and focused workbenches instant.
    if (tab !== 'harness') return;
    Promise.all([api.listHarnesses(), api.listIdentities(), api.listHarnessDetails(), api.getDagContracts()])
      .then(([harnesses, identities, details, contracts]) => {
        setHarnessList(harnesses);
        setIdentityList(identities);
        setComponentList(details.filter((item) => Boolean(item.component)));
        setDagContracts(contracts as DagContractCatalog);
      })
      .catch(() => {});
  }, [tab]);

  useEffect(() => {
    if (!dagContracts?.nodes) return;
    setFlowNodes((nodes) => nodes.map((node) => {
      const op = String((node.data as any).op || '');
      const contract = contractFor(dagContracts, op);
      return (node.data as any)._contract === contract ? node : { ...node, data: { ...node.data, _contract: contract } };
    }));
  }, [dagContracts, flowContractSignature, setFlowNodes]);

  useEffect(() => {
    // Do not keep a live execution renderer mounted for every Studio page.
    // A run that is already active remains subscribed when the user briefly
    // visits another page, so execution state is never lost.
    if (tab !== 'harness' && !execState.running) return;
    const pendingStreamTokens: PendingStreamToken[] = [];
    let streamFlushTimer: number | null = null;

    const flushStreamTokens = () => {
      if (streamFlushTimer !== null) {
        window.clearTimeout(streamFlushTimer);
        streamFlushTimer = null;
      }
      if (pendingStreamTokens.length === 0) return;
      const batch = pendingStreamTokens.splice(0, pendingStreamTokens.length);
      setNodeTraces((prev) => appendTraceTokenBatch(prev, batch));
      setChatMessages((prev) => appendMessageTokenBatch(prev, batch, () => ++chatMsgId.current));
    };

    const queueStreamToken = (token: PendingStreamToken) => {
      pendingStreamTokens.push(token);
      // A model can emit dozens of WebSocket events per second. Ten visual
      // updates per second still feels live and halves React/XYFlow work.
      if (streamFlushTimer === null) streamFlushTimer = window.setTimeout(flushStreamTokens, 100);
    };

    const unsub = api.subscribeExecution((msg) => {
      const incomingScope = msg.scope || msg;
      if (incomingScope?.workspace && !isCurrentWorkspace(incomingScope.workspace)) return;
      const incomingRunId = incomingScope?.run_id ? String(incomingScope.run_id) : undefined;
      if (activeExecutionRunId.current && incomingRunId && incomingRunId !== activeExecutionRunId.current) return;
      const incomingType = msg.type as string | undefined;
      const incomingData = msg.data || {};
      if (incomingType === 'token') {
        queueStreamToken({
          kind: 'main',
          nodeId: incomingData.node_id,
          agent: incomingData.agent || 'unknown',
          text: incomingData.text || '',
        });
        return;
      }
      if (incomingType === 'sub_token') {
        queueStreamToken({
          kind: 'sub',
          harnessId: incomingData.harness_id || '',
          agent: incomingData.agent || 'unknown',
          text: incomingData.text || '',
        });
        return;
      }
      // Preserve event order: text queued before a tool/result must appear
      // before that tool/result in the conversation and node trace.
      flushStreamTokens();

      if (msg.running !== undefined) {
        if (Array.isArray(msg.node_traces)) {
          setNodeTraces(msg.node_traces);
        }
        setExecState((prev) => {
          // 只在 running 从 false 变为 true 时清空消息（新一轮执行开始）
          if (msg.running && !prev.running) {
            setChatMessages([]);
            chatMsgId.current = 0;
          }
          return { ...prev, ...msg, node_traces: Array.isArray(msg.node_traces) ? msg.node_traces : prev.node_traces };
        });
        setFlowNodes((nds) => {
          let changed = false;
          const next = nds.map((node) => {
            const highlighted = node.id === msg.current_node;
            if (Boolean((node.data as any).highlight) === highlighted) return node;
            changed = true;
            return { ...node, data: { ...node.data, highlight: highlighted } };
          });
          return changed ? next : nds;
        });
        if (msg.running) {
          setShowOutput(true);
        }
        // 同步 waitingNodeId：根据 current_node 判断是否为等待输入节点
        if (msg.current_node && ['输入', '等待输入'].includes(configRef.current.pipeline.nodes[msg.current_node]?.op)) {
          setWaitingNodeId(msg.current_node);
        } else if (!msg.running) {
          setWaitingNodeId(null);
        }
      } else if (msg.type) {
        const type = msg.type as string;
        const data = msg.data || {};

        if (type === 'node_input') {
          const trace: NodeTrace = {
            sequence: Date.now() + Math.random(),
            node_id: data.node_id,
            op: data.op || '',
            agent: data.agent || '',
            status: 'entered',
            input: data.input,
            last_output: data.last_output,
            output: undefined,
            model: { request: undefined, response: '', tool_calls: [] },
            tools: [],
            usage: {},
            retries: [],
            artifacts: [],
            error: null,
            stats: {},
            started_at: Date.now() / 1000,
          };
          setNodeTraces((prev) => [...prev.slice(-499), trace]);
          setFlowNodes((nds) => nds.map((n) => n.id === data.node_id ? {
            ...n,
            data: {
              ...n.data,
              runtimeStatus: 'entered',
              runtimeCount: Number((n.data as any).runtimeCount || 0) + 1,
            },
          } : n));
        } else if (type === 'node_enter') {
          setExecState((prev) => ({ ...prev, current_node: data.node_id, step_count: prev.step_count + 1 }));
          setNodeTraces((prev) => {
            const index = [...prev].reverse().findIndex((trace) => trace.node_id === data.node_id);
            if (index < 0) return prev;
            const actual = prev.length - 1 - index;
            return prev.map((trace, i) => i === actual ? { ...trace, status: 'running' } : trace);
          });
          setFlowNodes((nds) => {
            let changed = false;
            const next = nds.map((node) => {
              const highlighted = node.id === data.node_id;
              const runtimeStatus = highlighted ? 'running' : (node.data as any).runtimeStatus;
              if (Boolean((node.data as any).highlight) === highlighted && (node.data as any).runtimeStatus === runtimeStatus) return node;
              changed = true;
              return { ...node, data: { ...node.data, highlight: highlighted, runtimeStatus } };
            });
            return changed ? next : nds;
          });
          const nodeOp = configRef.current.pipeline.nodes[data.node_id]?.op;
          if (nodeOp && ['输入', '等待输入'].includes(nodeOp)) {
            setWaitingNodeId(data.node_id);
          } else {
            setWaitingNodeId(null);
          }
        } else if (type === 'model_request') {
          setNodeTraces((prev) => updateLatestTrace(prev, data.node_id, (trace) => ({
            ...trace,
            model: { ...trace.model, request: stripEventEnvelope(data) },
          })));
        } else if (type === 'model_response') {
          setNodeTraces((prev) => updateLatestTrace(prev, data.node_id, (trace) => ({
            ...trace,
            model: { ...trace.model, response: data.text, tool_calls: data.tool_calls || [] },
          })));
        } else if (type === 'provider_usage') {
          setNodeTraces((prev) => updateLatestTrace(prev, data.node_id, (trace) => ({
            ...trace,
            usage: {
              model: data.model,
              request_ids: data.request_ids || [],
              attempts: data.attempts,
              reconnects: data.reconnects,
              input_tokens: data.input_tokens,
              cached_input_tokens: data.cached_input_tokens,
              output_tokens: data.output_tokens,
            },
          })));
        } else if (['context_pressure', 'context_compaction_started', 'context_compacted', 'context_compaction_failed'].includes(type)) {
          setNodeTraces((prev) => updateLatestTrace(prev, data.node_id, (trace) => ({
            ...trace,
            stats: {
              ...(trace.stats || {}),
              context_compaction: {
                ...(((trace.stats as any) || {}).context_compaction || {}),
                ...stripEventEnvelope(data),
                phase: type === 'context_pressure' ? 'triggered'
                  : type === 'context_compaction_started' ? 'compacting'
                    : type === 'context_compacted' ? 'compacted' : 'failed',
              },
            },
          })));
        } else if (type === 'node_retry') {
          setNodeTraces((prev) => updateLatestTrace(prev, data.node_id, (trace) => ({
            ...trace,
            retries: [...(trace.retries || []), { attempt: data.attempt, max_attempts: data.max_attempts, message: data.message }],
          })));
        } else if (type === 'node_error') {
          setNodeTraces((prev) => updateLatestTrace(prev, data.node_id, (trace) => ({
            ...trace,
            error: { type: data.type || 'Error', message: data.message || '', attempt: data.attempt, max_attempts: data.max_attempts },
            status: 'error',
          })));
        } else if (type === 'node_input_override') {
          setNodeTraces((prev) => updateLatestTrace(prev, data.node_id, (trace) => ({
            ...trace,
            input: data.input,
            stats: { ...(trace.stats || {}), debug_input_override: true },
          })));
        } else if (type === 'node_skipped') {
          setNodeTraces((prev) => updateLatestTrace(prev, data.node_id, (trace) => ({
            ...trace,
            output: data.output,
            stats: { ...(trace.stats || {}), debug_skipped: true },
          })));
        } else if (type === 'debug_retry') {
          setNodeTraces((prev) => updateLatestTrace(prev, data.node_id, (trace) => ({
            ...trace,
            input: data.input,
            error: null,
            status: 'running',
            retries: [...(trace.retries || []), { attempt: data.attempt, max_attempts: 10, message: `Debugger retry after: ${data.previous_error || ''}` }],
          })));
        } else if (type === 'node_output') {
          setNodeTraces((prev) => updateLatestTrace(prev, data.node_id, (trace) => ({
            ...trace,
            output: data.output,
            artifacts: Array.isArray(data.output?.artifacts) ? data.output.artifacts : trace.artifacts,
            status: data.status === 'error' ? 'error' : 'ok',
          })));
        } else if (type === 'node_exit') {
          setNodeTraces((prev) => updateLatestTrace(prev, data.node_id, (trace) => ({
            ...trace,
            status: data.status === 'error' ? 'error' : 'completed',
            completed_at: Date.now() / 1000,
            duration_ms: Math.max(0, Math.round(((Date.now() / 1000) - (trace.started_at || Date.now() / 1000)) * 1000)),
            stats: data.stats || {},
          })));
          setFlowNodes((nds) => nds.map((n) => n.id === data.node_id ? {
            ...n,
            data: { ...n.data, runtimeStatus: data.status === 'error' ? 'error' : 'completed' },
          } : n));
        } else if (type === 'tool') {
          const agent = data.agent || 'system';
          setNodeTraces((prev) => updateLatestTrace(prev, data.node_id, (trace) => ({
            ...trace,
            tools: [...trace.tools, { name: data.name || '', arguments: data.arguments, result: data.result }],
          })));
          setChatMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.agent === agent) {
              return [...prev.slice(0, -1), { ...last, tools: [...last.tools, { name: data.name, result: data.result }] }];
            }
            chatMsgId.current++;
            return [...prev, { id: chatMsgId.current, agent, text: '', tools: [{ name: data.name, result: data.result }], blocked: [] }];
          });
          // 自动刷新：如果 improver 修改了当前加载的 harness，重载 pipeline 可视化
          if ((data.name === 'modify_harness' || data.name === 'manage_harness') && data.result) {
            try {
              const res = JSON.parse(data.result);
              if (res.success || res.ok) {
                setImproveChanges(prev => [...prev, {
                  timestamp: Date.now(),
                  type: "harness",
                  target: res.harness,
                  action: res.action,
                  field: res.target || res.transaction_id,
                  nodes: res.current_nodes || res.blueprint?.steps?.map((step: any) => step.id),
                  pipelineStart: res.pipeline_start || res.blueprint?.start,
                  diff: res.diff,
                }]);
                // 如果修改的是当前加载的 harness，刷新 DAG
                if (res.harness === configRef.current.name) {
                  setTimeout(() => {
                    api.loadHarness(configRef.current.name).then((cfg) => {
                      cfg.prompts = cfg.prompts || {};
                      cfg.slots = cfg.slots || {};
                      cfg.pipeline = cfg.pipeline || { start: '', max_steps: 100, workspace_preview: false, nodes: {} };
                      setConfig(cfg);
                      const { nodes, edges } = configToFlow(cfg);
                      setFlowNodes(nodes);
                      setFlowEdges(edges);
                    }).catch(() => {});
                  }, 500);
                }
              }
            } catch {}
          }
          // modify_identity 追踪
          if (data.name === 'modify_identity' && data.result) {
            try {
              const res = JSON.parse(data.result);
              if (res.success) {
                setImproveChanges(prev => [...prev, {
                  timestamp: Date.now(),
                  type: "identity",
                  target: res.identity,
                  action: "set_field",
                  field: res.field,
                  oldValue: res.old_value,
                  newValue: res.new_value,
                }]);
              }
            } catch {}
          }
          if (data.name === 'create_agent_system' && data.result) {
            try {
              const res = JSON.parse(data.result);
              if (res.ok) {
                Promise.all([api.listHarnesses(), api.listIdentities()]).then(([harnesses, identities]) => {
                  setHarnessList(harnesses);
                  setIdentityList(identities);
                }).catch(() => {});
                setSaveMsg(`新 Agent ${res.identity?.name || ''} 与 Harness ${res.harness || ''} 已创建，可从右侧加载。`);
              }
            } catch {}
          }
        } else if (type === 'identity_evolution') {
          api.listIdentities().then(setIdentityList).catch(() => {});
          setImproveChanges((prev) => [...prev, {
            timestamp: Date.now(),
            type: 'identity',
            target: data.identity,
            action: `${data.action}:${data.pack || ''}`,
            field: data.transaction_id,
          }]);
          setSaveMsg(`Identity ${data.identity || ''} 能力${data.action === 'rollback' ? '已回滚' : '已进化'} · ${data.pack || ''}`);
        } else if (type === 'agent_system_created') {
          Promise.all([api.listHarnesses(), api.listIdentities()]).then(([harnesses, identities]) => {
            setHarnessList(harnesses);
            setIdentityList(identities);
          }).catch(() => {});
          setSaveMsg(`新 Agent ${data.identity || ''} 与 Harness ${data.harness || ''} 已创建，可从右侧加载。`);
        } else if (type === 'harness_mutation') {
          if (data.harness === configRef.current.name) {
            api.loadHarness(data.harness).then((cfg) => {
              cfg.prompts = cfg.prompts || {};
              cfg.slots = cfg.slots || {};
              cfg.pipeline = cfg.pipeline || { start: '', max_steps: 100, workspace_preview: false, nodes: {} };
              setConfig(cfg);
              const { nodes, edges } = configToFlow(cfg);
              setFlowNodes(nodes);
              setFlowEdges(edges);
              setSaveMsg(`Harness ${data.action === 'create' ? '已创建' : '已更新'} · ${data.transaction_id || data.revision || ''}`);
            }).catch(() => {});
          }
          setImproveChanges((prev) => [...prev, {
            timestamp: Date.now(),
            type: 'harness',
            target: data.harness,
            action: data.action,
            diff: data.diff,
          }]);
        } else if (type === 'blocked') {
          const agent = data.agent || 'system';
          setNodeTraces((prev) => updateLatestTrace(prev, data.node_id, (trace) => ({
            ...trace,
            tools: [...trace.tools, { name: data.tool || '', blocked: true, reason: data.reason || '' }],
          })));
          setChatMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.agent === agent) {
              return [...prev.slice(0, -1), { ...last, blocked: [...last.blocked, { name: data.tool, reason: data.reason }] }];
            }
            chatMsgId.current++;
            return [...prev, { id: chatMsgId.current, agent, text: '', tools: [], blocked: [{ name: data.tool, reason: data.reason }] }];
          });
        } else if (type === 'approval_required') {
          setExecState((prev) => ({
            ...prev,
            status: 'waiting_approval',
            waiting_for_input: true,
            pending_approval: data,
          }));
          setShowOutput(true);
        } else if (type === 'approval') {
          setExecState((prev) => ({
            ...prev,
            status: prev.running ? 'running' : prev.status,
            waiting_for_input: false,
            pending_approval: null,
          }));
        } else if (type === 'model_output_truncated') {
          const failure = data.failure || {};
          chatMsgId.current++;
          setChatMessages((prev) => [...prev, {
            id: chatMsgId.current,
            agent: 'system',
            text: `⚠️ ${failure.title || '模型输出已截断'}\n${failure.message || data.message || ''}${failure.action ? `\n下一步：${failure.action}` : ''}`,
            tools: [],
            blocked: [],
          }]);
        } else if (type === 'run_limit_exceeded') {
          const failure = data.failure || {};
          setExecState((prev) => ({ ...prev, status: 'limit_exceeded', termination: data }));
          chatMsgId.current++;
          setChatMessages((prev) => [...prev, {
            id: chatMsgId.current,
            agent: 'system',
            text: `⛔ ${failure.title || '运行达到限制'}\n${failure.message || data.message || ''}${failure.action ? `\n下一步：${failure.action}` : ''}`,
            tools: [],
            blocked: [],
          }]);
        } else if (type === 'cancelled') {
          setExecState((prev) => ({ ...prev, status: 'cancelled', termination: data }));
        } else if (type === 'error') {
          const failure = data.failure || {};
          chatMsgId.current++;
          setChatMessages((prev) => [...prev, {
            id: chatMsgId.current,
            agent: 'system',
            text: `❌ ${failure.title || '执行失败'}\n${failure.message || data.message || ''}${failure.action ? `\n下一步：${failure.action}` : ''}`,
            tools: [],
            blocked: [],
          }]);
        } else if (type === 'sub_harness_start') {
          chatMsgId.current++;
          setActiveSubHarness(data.harness_name || '');
          // 更新当前执行节点显示子 harness 名称
          setFlowNodes((nds) =>
            nds.map((n) => ({
              ...n,
              data: { ...n.data, subHarness: (n.data as any).highlight ? data.harness_name : undefined },
            }))
          );
          setChatMessages((prev) => [...prev, {
            id: chatMsgId.current,
            agent: data.parent_agent || 'system',
            text: '',
            tools: [],
            blocked: [],
            sub_harness: {
              harness_id: data.harness_id || '',
              harness_name: data.harness_name || '',
              slots: data.slots || {},
              messages: [],
              status: 'running',
            }
          }]);
        } else if (type === 'sub_tool') {
          const harnessId = data.harness_id || '';
          const agent = data.agent || 'system';
          const toolEntry = { name: data.name || '', result: data.result || '' };
          setChatMessages((prev) => {
            for (let i = prev.length - 1; i >= 0; i--) {
              const sh = prev[i].sub_harness;
              if (sh && sh.harness_id === harnessId) {
                const msgs = [...sh.messages];
                const lastMsg = msgs[msgs.length - 1];
                if (lastMsg && lastMsg.agent === agent) {
                  msgs[msgs.length - 1] = { ...lastMsg, tools: [...(lastMsg.tools || []), toolEntry] };
                } else {
                  msgs.push({ agent, text: '', tools: [toolEntry] });
                }
                const updated = [...prev];
                updated[i] = { ...updated[i], sub_harness: { ...sh, messages: msgs } };
                return updated;
              }
            }
            return prev;
          });
        } else if (type === 'sub_harness_end') {
          const harnessId = data.harness_id || '';
          setActiveSubHarness(null);
          // 清除节点上的子 harness 标记
          setFlowNodes((nds) =>
            nds.map((n) => ({
              ...n,
              data: { ...n.data, subHarness: undefined },
            }))
          );
          setChatMessages((prev) => {
            for (let i = prev.length - 1; i >= 0; i--) {
              const sh = prev[i].sub_harness;
              if (sh && sh.harness_id === harnessId) {
                const updated = [...prev];
                updated[i] = { ...updated[i], sub_harness: { ...sh, status: 'completed' } };
                return updated;
              }
            }
            return prev;
          });
        }
      }
    });

    return () => {
      if (streamFlushTimer !== null) window.clearTimeout(streamFlushTimer);
      pendingStreamTokens.length = 0;
      unsub();
    };
  }, [tab, execState.running, setFlowNodes]);

  const lastOutputTick = useRef(0);
  const lastPolledNode = useRef<string | null>(null);
  const lastPolledTraceSignature = useRef('');

  // HTTP polling fallback: keep execState + agentOutputs in sync even when WebSocket is down
  useEffect(() => {
    // WebSocket is the live transport. HTTP is only a recovery safety net for
    // the visible Builder and should not wake every other Studio workbench.
    if (tab !== 'harness') return;
    const interval = setInterval(async () => {
      if (document.hidden) return;
      try {
          const state = await api.getExecutionState(activeExecutionRunId.current);
          if (state.workspace && !isCurrentWorkspace(state.workspace)) return;
        if (state) {
          if (Array.isArray(state.node_traces)) {
            const signature = traceSnapshotSignature(state.node_traces);
            if (signature !== lastPolledTraceSignature.current) {
              lastPolledTraceSignature.current = signature;
              setNodeTraces(state.node_traces);
            }
          }
          setExecState((prev) => {
            if (
              prev.running === state.running &&
              prev.step_count === state.step_count &&
              prev.current_node === state.current_node &&
              prev.pending_node === state.pending_node &&
              prev.paused === state.paused &&
              prev.pause_requested === state.pause_requested &&
              prev.pause_reason === state.pause_reason &&
              prev.messages_count === state.messages_count &&
              prev.debug_mode === state.debug_mode
            ) {
              return prev;
            }
            return { ...prev, ...state, node_traces: state.node_traces || prev.node_traces };
          });
          // 只在 current_node 真正变化时更新节点高亮
          if (state.current_node !== lastPolledNode.current) {
            lastPolledNode.current = state.current_node;
            setFlowNodes((nds) =>
              nds.map((n) => ({
                ...n,
                data: { ...n.data, highlight: n.id === state.current_node },
              }))
            );
          }
          if (state.running) setShowOutput(true);
          // HTTP 轮询仅在 WebSocket 未提供数据时作为兜底，不覆盖已有消息
          if (state.outputs && state.outputs.length > 0 && state._tick !== lastOutputTick.current) {
            lastOutputTick.current = state._tick;
            setChatMessages((prev) => prev.length === 0 ? state.outputs : prev);
          }
        }
      } catch {}
    }, 2500);
    return () => clearInterval(interval);
  }, [tab, setFlowNodes]);

  const userScrolledUp = useRef(false);

  useEffect(() => {
    if (outputsRef.current && !userScrolledUp.current) {
      outputsRef.current.scrollTop = outputsRef.current.scrollHeight;
    }
  }, [chatMessages]);

  const loadConfig = useCallback(async (name: string) => {
    try {
      const cfg = await api.loadHarness(name);
      cfg.prompts = cfg.prompts || {};
      cfg.slots = cfg.slots || {};
      cfg.return_mode = cfg.return_mode || 'all';
      cfg.pipeline = cfg.pipeline || { start: '', max_steps: 100, workspace_preview: false, nodes: {} };
      setConfig(cfg);
      const { nodes, edges } = configToFlow(cfg);
      setFlowNodes(nodes);
      setFlowEdges(edges);
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
      setSelectedTraceSequence(null);
      setNodeTraces([]);
      setSaveMsg(`已加载: ${name}`);
      setTimeout(() => setSaveMsg(''), 2000);
    } catch (e: any) {
      setSaveMsg(`加载失败: ${e.message}`);
      setTimeout(() => setSaveMsg(''), 3000);
    }
  }, [setFlowNodes, setFlowEdges]);

  const saveConfig = useCallback(async () => {
    try {
      const updated = flowToConfig(config, flowNodes, flowEdges);
      setConfig(updated);
      await api.saveHarness(updated.name, updated);
      const details = await api.listHarnessDetails();
      setComponentList(details.filter((item) => Boolean(item.component)));
      setHarnessList((prev) => {
        if (!prev.includes(updated.name)) return [...prev, updated.name];
        return prev;
      });
      setSaveMsg(`已保存: ${updated.name}`);
      setTimeout(() => setSaveMsg(''), 2000);
    } catch (e: any) {
      setSaveMsg(`保存失败: ${e.message}`);
      setTimeout(() => setSaveMsg(''), 3000);
    }
  }, [config, flowNodes, flowEdges]);

  const onConnect: OnConnect = useCallback(
    (connection: Connection) => {
      const newEdge: Edge = {
        ...connection,
        id: `${connection.source}->${connection.target}`,
        type: 'conditionEdge',
        data: { condition: 'default' as EdgeCondition },
      } as Edge;
      setFlowEdges((eds) => addEdge(newEdge, eds));
    },
    [setFlowEdges],
  );

  const onDragOver = useCallback((event: DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault();
      const op = event.dataTransfer.getData('application/egoagent-node') as OpType;
      if (!op || !reactFlowWrapper.current || !rfInstance) return;

      const bounds = reactFlowWrapper.current.getBoundingClientRect();
      const position = rfInstance.screenToFlowPosition({
        x: event.clientX - bounds.left,
        y: event.clientY - bounds.top,
      });

      const id = nextNodeId();
      let data = defaultNodeData(id, op, dagContracts);
      const rawComponent = event.dataTransfer.getData('application/egoagent-subdag');
      if (op === '子流程' && rawComponent) {
        try {
          const item = JSON.parse(rawComponent) as api.HarnessCatalogItem;
          const inputDefaults = Object.fromEntries(
            Object.entries(item.component?.inputs || {})
              .filter(([, spec]) => Object.prototype.hasOwnProperty.call(spec, 'default'))
              .map(([name, spec]) => [name, spec.default]),
          );
          const outputBindings = Object.fromEntries(
            Object.keys(item.component?.outputs || {}).map((name) => [name, `${id}.${name}`]),
          );
          data = {
            ...data,
            harness: item.name,
            share_session: Boolean(item.component?.share_session),
            component_inputs: inputDefaults,
            component_outputs: outputBindings,
            result_mode: 'data',
          };
        } catch {
          // Fall back to a normal Subflow node when drag metadata is malformed.
        }
      }
      const newNode: Node = {
        id,
        type: 'pipelineNode',
        position,
        data: data as unknown as Record<string, unknown>,
      };

      setFlowNodes((nds) => [...nds, newNode]);
    },
    [dagContracts, rfInstance, setFlowNodes],
  );

  const onNodeClick = useCallback((_event: any, node: Node) => {
    setSelectedNodeId(node.id);
    setSelectedEdgeId(null);
    const latest = [...nodeTraces].reverse().find((trace) => trace.node_id === node.id);
    setSelectedTraceSequence(latest?.sequence ?? null);
    if (latest) setShowOutput(true);
  }, [nodeTraces]);

  const onEdgeClick = useCallback((_event: any, edge: Edge) => {
    setSelectedEdgeId(edge.id);
    setSelectedNodeId(null);
  }, []);

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
  }, []);

  const selectedNode = selectedNodeId
    ? (flowNodes.find((n) => n.id === selectedNodeId)?.data as unknown as PipelineNode) || null
    : null;

  const selectedTrace = selectedTraceSequence == null
    ? null
    : nodeTraces.find((trace) => trace.sequence === selectedTraceSequence) || null;

  const selectedEdge = selectedEdgeId
    ? (() => {
        const e = flowEdges.find((ed) => ed.id === selectedEdgeId);
        if (!e) return null;
        return {
          id: e.id,
          condition: ((e.data as any)?.condition || 'default') as EdgeCondition,
          source: e.source,
          target: e.target,
        };
      })()
    : null;

  const handleNodeUpdate = useCallback(
    (nodeId: string, updates: Partial<PipelineNode>) => {
      setFlowNodes((nds) =>
        nds.map((n) =>
          n.id === nodeId ? { ...n, data: { ...n.data, ...updates } } : n
        )
      );
    },
    [setFlowNodes],
  );

  const handleEdgeUpdate = useCallback(
    (edgeId: string, condition: EdgeCondition) => {
      setFlowEdges((eds) =>
        eds.map((e) =>
          e.id === edgeId ? { ...e, data: { ...e.data, condition } } : e
        )
      );
    },
    [setFlowEdges],
  );

  const handleDeleteNode = useCallback(
    (nodeId: string) => {
      setFlowNodes((nds) => nds.filter((n) => n.id !== nodeId));
      setFlowEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
      setSelectedNodeId(null);
    },
    [setFlowNodes, setFlowEdges],
  );

  const handleDeleteEdge = useCallback(
    (edgeId: string) => {
      setFlowEdges((eds) => eds.filter((e) => e.id !== edgeId));
      setSelectedEdgeId(null);
    },
    [setFlowEdges],
  );

  const handleStartExec = useCallback(async () => {
    try {
      const updated = flowToConfig(config, flowNodes, flowEdges);
      setConfig(updated);
      await api.saveHarness(updated.name, updated);

      const agents: Record<string, string> = {};
      const missingSlots: string[] = [];
      Object.entries(updated.slots).forEach(([slotName, slotDef]: [string, any]) => {
        const identity = slotDef.identity;
        if (!identity && slotDef.required) {
          missingSlots.push(slotName);
        }
        agents[slotName] = `identity/${identity || slotName}`;
      });
      if (missingSlots.length > 0) {
        setSaveMsg(`请先绑定 slot: ${missingSlots.join(', ')}（从右侧面板拖放 Identity）`);
        setTimeout(() => setSaveMsg(''), 5000);
        return;
      }
      const started = await api.startExecution(updated.name, agents, startPaused ? 'paused' : 'auto');
      const runId = String(started.run_id || started.state?.run_id || '');
      activeExecutionRunId.current = runId || undefined;
      setExecState((prev) => ({
        ...prev,
        run_id: runId || undefined,
        running: true,
        current_node: null,
        step_count: 0,
        debug_mode: startPaused ? 'paused' : 'auto',
        paused: false,
        pause_requested: startPaused,
        pending_node: null,
        node_traces: [],
      }));
      setShowOutput(true);
      setChatMessages([]);
      setNodeTraces([]);
      setSelectedTraceSequence(null);
      setFlowNodes((nodes) => nodes.map((node) => ({
        ...node,
        data: { ...node.data, highlight: false, runtimeStatus: undefined, runtimeCount: undefined },
      })));
      chatMsgId.current = 0;
      setImproveChanges([]);
    } catch (e: any) {
      setSaveMsg(`启动失败: ${e.message}`);
      setTimeout(() => setSaveMsg(''), 3000);
    }
  }, [config, flowNodes, flowEdges, startPaused, setFlowNodes]);

  const handleStopExec = useCallback(async () => {
    try {
      await api.stopExecution(activeExecutionRunId.current);
    } catch {}
  }, []);

  const handleExecutionControl = useCallback(async (action: 'pause' | 'step' | 'auto') => {
    try {
      const state = await api.controlExecution(action, {}, activeExecutionRunId.current);
      setExecState((prev) => ({ ...prev, ...state, node_traces: state.node_traces || prev.node_traces }));
    } catch (error: any) {
      setSaveMsg(`调试控制失败: ${error.message}`);
    }
  }, []);

  const handleDebugDirective = useCallback(async (action: 'skip' | 'override_inputs' | 'retry_with_inputs') => {
    const nodeId = execState.pending_node;
    if (!nodeId || !execState.paused) {
      setSaveMsg('只有在节点执行前暂停时才能使用此操作');
      return;
    }
    try {
      const raw = action === 'skip' ? debugSkipOutput : debugInputOverride;
      const parsed = JSON.parse(raw || '{}');
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('必须是 JSON 对象');
      const payload = action === 'skip' ? { node_id: nodeId, output: parsed } : { node_id: nodeId, inputs: parsed };
      const state = await api.controlExecution(action, payload, activeExecutionRunId.current);
      setExecState((prev) => ({ ...prev, ...state, node_traces: state.node_traces || prev.node_traces }));
      setSaveMsg(action === 'skip' ? `已安全跳过 ${nodeId}` : action === 'retry_with_inputs' ? `正在用修改后的输入重试 ${nodeId}` : `将用修改后的输入运行 ${nodeId}`);
    } catch (error: any) {
      setSaveMsg(`调试操作失败: ${error.message}`);
    }
  }, [debugInputOverride, debugSkipOutput, execState.paused, execState.pending_node]);

  const handleSendInput = useCallback(() => {
    if (!waitingNodeId) return; // 只有在等待输入节点时才允许发送
    const text = inputText.trim();
    if (!text) return;
    console.log("[App] handleSendInput called, text:", text);
    // 在聊天面板中显示用户消息气泡
    chatMsgId.current++;
    setChatMessages((prev) => [...prev, { id: chatMsgId.current, agent: 'user', text, tools: [], blocked: [] }]);
    api.sendInputViaWs(text, activeExecutionRunId.current);
    setInputText('');
  }, [inputText, waitingNodeId]);

  const handleApproval = useCallback(async (decision: 'approved' | 'rejected') => {
    const pending = execState.pending_approval;
    if (!pending) return;
    setApprovalBusy(true);
    try {
      await api.respondToExecutionApproval(String(pending.approval_id || ''), decision, activeExecutionRunId.current);
      setExecState((prev) => ({ ...prev, pending_approval: null, waiting_for_input: false, status: 'running' }));
    } catch (error) {
      setSaveMsg(`审批提交失败: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setApprovalBusy(false);
    }
  }, [execState.pending_approval]);

  const handleInputKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendInput();
    }
  }, [handleSendInput]);

  const refreshIdentities = useCallback(async () => {
    const list = await api.listIdentities();
    setIdentityList(list);
  }, []);

  const agentSlots = Object.keys(config.slots);
  const activeTabMeta = STUDIO_TABS.find((item) => item.id === tab) || DEFAULT_TAB_META;

  const probeRuntime = useCallback(async () => {
    try {
      await api.getWorkspace();
      setRuntimeOnline(true);
    } catch {
      setRuntimeOnline(false);
    }
  }, []);

  useEffect(() => {
    void probeRuntime();
    const interval = window.setInterval(() => {
      if (!document.hidden) void probeRuntime();
    }, 8000);
    return () => window.clearInterval(interval);
  }, [probeRuntime]);

  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set('tab', tab);
    window.history.replaceState(null, '', url);
    updateWorkbenchSession({ route: tab });
    if (EMBEDDED_IN_IDE) publishWorkbenchEvent('route-change', { tab });
  }, [tab]);

  useEffect(() => {
    const receiveShellMessage = (event: MessageEvent) => {
      const message = event.data || {};
      if (message.source !== 'egoagent-shell') return;
      if (message.type === 'navigate') {
        const destination = message.tab as TabType;
        if (STUDIO_TAB_IDS.has(destination)) setTab(destination);
      }
      if (message.type === 'context-handoff' && Array.isArray(message.items)) {
        const items = message.items as IdeContextItem[];
        updateWorkbenchSession({ handoff: { items, updatedAt: Date.now() } });
        window.dispatchEvent(new CustomEvent('egoagent:context-handoff', { detail: { items } }));
        setTab('tasks');
      }
    };
    window.addEventListener('message', receiveShellMessage);
    return () => window.removeEventListener('message', receiveShellMessage);
  }, []);

  const persistBuilderDraft = useCallback(() => {
    const positions = Object.fromEntries(flowNodes.map((node) => [node.id, node.position]));
    updateWorkbenchSession({
      builder: {
        config: flowToConfig(config, flowNodes, flowEdges),
        positions,
        selectedNodeId,
        selectedEdgeId,
        showOutput,
        outputView,
      },
    });
  }, [config, flowNodes, flowEdges, selectedNodeId, selectedEdgeId, showOutput, outputView]);

  useEffect(() => {
    if (execState.running) return;
    const timer = window.setTimeout(persistBuilderDraft, 350);
    return () => window.clearTimeout(timer);
  }, [execState.running, persistBuilderDraft]);

  useEffect(() => {
    const persistWhenHidden = () => {
      if (document.visibilityState === 'hidden' && !execState.running) persistBuilderDraft();
    };
    document.addEventListener('visibilitychange', persistWhenHidden);
    return () => document.removeEventListener('visibilitychange', persistWhenHidden);
  }, [execState.running, persistBuilderDraft]);

  useEffect(() => {
    publishWorkbenchEvent('runtime-status', {
      scope: 'builder',
      workspace: WORKSPACE,
      running: execState.running,
      waitingForInput: Boolean(execState.waiting_for_input || waitingNodeId),
      paused: execState.paused,
      currentNode: execState.pending_node || execState.current_node,
      harness: config.name,
      runId: execState.run_id,
    });
  }, [config.name, execState.running, execState.waiting_for_input, execState.paused, execState.pending_node, execState.current_node, waitingNodeId, execState.run_id]);

  return (
    <div className={`app-container ${EMBEDDED_IN_IDE ? 'embedded-workbench' : ''}`}>
      <header className={EMBEDDED_IN_IDE ? 'workbench-toolbar' : 'studio-titlebar'}>
        <span className="studio-product-mark" aria-hidden="true">E</span>
        <div className="studio-title-path">
          <strong>{EMBEDDED_IN_IDE ? 'Agent Workbench' : 'EgoAgent Workbench'}</strong><span>/</span><b>{activeTabMeta.label}</b>
        </div>
        {EMBEDDED_IN_IDE ? <nav className="workbench-route-tabs" aria-label="Agent Workbench">
          {STUDIO_TABS.filter((item) => item.group === 'primary').map((item) => <button
            key={item.id}
            className={tab === item.id ? 'active' : ''}
            aria-current={tab === item.id ? 'page' : undefined}
            onClick={() => setTab(item.id)}
          >{item.label}</button>)}
          <button
            className={`workbench-more ${showAdvancedNavigation ? 'active' : ''}`}
            aria-expanded={showAdvancedNavigation}
            onClick={() => setShowAdvancedNavigation((visible) => !visible)}
          >More</button>
          {showAdvancedNavigation && <div className="workbench-route-menu" role="menu">
            {STUDIO_TABS.filter((item) => item.group !== 'primary').map((item) => <button
              key={item.id}
              role="menuitem"
              className={tab === item.id ? 'active' : ''}
              onClick={() => { setTab(item.id); setShowAdvancedNavigation(false); }}
            ><span>{item.icon}</span><div><b>{item.label}</b><small>{item.detail}</small></div></button>)}
          </div>}
        </nav> : <div className="studio-command-center">{activeTabMeta.detail}</div>}
        <button
          type="button"
          className={`studio-connection ${runtimeOnline === false ? 'offline' : runtimeOnline === null ? 'checking' : ''}`}
          title={runtimeOnline === false ? '点击重试连接本地 EgoAgent runtime' : '本地 EgoAgent runtime 状态'}
          onClick={() => void probeRuntime()}
        ><span />{runtimeOnline === false ? 'Runtime offline · 重试' : runtimeOnline === null ? 'Checking runtime' : 'Local runtime'}</button>
      </header>

      {runtimeOnline === false && <div className="runtime-offline-banner" role="alert">
        <div><strong>本地 Runtime 未连接</strong><span>Workbench 草稿仍保留；需要运行、评测或保存时，请启动 EgoAgent 后重试。</span></div>
        <button onClick={() => void probeRuntime()}>重试</button>
      </div>}

      {!EMBEDDED_IN_IDE && <nav className="activity-bar" aria-label="EgoAgent 工作区">
        {STUDIO_TABS.filter((item) => item.group === 'primary').map((item) => (
          <button
            key={item.id}
            className={`activity-button ${tab === item.id ? 'active' : ''}`}
            data-tab={item.id}
            data-label={`${item.label} · ${item.detail}`}
            aria-label={item.label}
            aria-current={tab === item.id ? 'page' : undefined}
            onClick={() => setTab(item.id)}
          >
            <span aria-hidden="true">{item.icon}</span>
          </button>
        ))}
        <button
          className={`activity-button activity-more ${showAdvancedNavigation ? 'active' : ''}`}
          data-label="More · 高级工作台与记录"
          aria-label="更多工作台"
          aria-expanded={showAdvancedNavigation}
          onClick={() => setShowAdvancedNavigation((visible) => !visible)}
        ><span aria-hidden="true">•••</span></button>
        {showAdvancedNavigation && <div className="activity-advanced" role="group" aria-label="高级工作台">
          {STUDIO_TABS.filter((item) => item.group === 'manage').map((item) => <button
            key={item.id}
            className={tab === item.id ? 'active' : ''}
            onClick={() => { setTab(item.id); setShowAdvancedNavigation(false); }}
          ><span>{item.icon}</span><div><b>{item.label}</b><small>{item.detail}</small></div></button>)}
        </div>}
        <div className="activity-spacer" />
        {STUDIO_TABS.filter((item) => item.group === 'system').map((item) => (
          <button
            key={item.id}
            className={`activity-button ${tab === item.id ? 'active' : ''}`}
            data-label={`${item.label} · ${item.detail}`}
            aria-label={item.label}
            aria-current={tab === item.id ? 'page' : undefined}
            onClick={() => setTab(item.id)}
          ><span aria-hidden="true">{item.icon}</span></button>
        ))}
      </nav>}

      {interruptedRuns.length > 0 && (
        <div className="run-recovery-card" role="alert" aria-label="中断任务恢复">
          <div className="run-recovery-title">
            <span>需要处理的中断任务 ({interruptedRuns.length})</span>
            <button onClick={refreshInterruptedRuns} title="刷新">↻</button>
          </div>
          {interruptedRuns.map((run) => (
            <details key={run.id} className="run-recovery-item">
              <summary>
                <b>{run.id.slice(0, 8)}</b>
                <span>{run.checkpoint?.operation || '未知操作'} · {run.checkpoint?.node || '未知节点'}</span>
                <span className={run.checkpoint?.phase === 'completed' ? 'safe' : 'warning'}>
                  {run.checkpoint?.phase === 'completed' ? '可安全续跑' : '需检查副作用'}
                </span>
              </summary>
              <div className="run-recovery-detail">
                <p>{run.error || '工作进程意外结束。'}</p>
                <div>已完成步骤：{run.checkpoint?.completed_steps?.length || 0}</div>
                <div>产物：{run.checkpoint?.artifacts?.join(', ') || '无'}</div>
                <pre>{JSON.stringify({
                  pending_approvals: run.checkpoint?.pending_approvals,
                  revisions: run.checkpoint?.revisions,
                }, null, 2)}</pre>
                <div className="run-recovery-actions">
                  <button
                    className="btn btn-exec"
                    disabled={recoveryBusy === run.id}
                    onClick={() => handleRecovery(run, 'resume')}
                  >继续</button>
                  <button
                    className="btn btn-secondary"
                    disabled={recoveryBusy === run.id}
                    onClick={() => handleRecovery(run, 'discard')}
                  >丢弃记录</button>
                </div>
              </div>
            </details>
          ))}
        </div>
      )}

      <Suspense fallback={<StudioPageFallback />}>
      {tab === 'home' && <div className="studio-page studio-page-scroll"><StudioHome onNavigate={(destination) => setTab(destination)} onOpenHarness={(name) => { setTab('harness'); void loadConfig(name); }} /></div>}
      {tab === 'coc' && <div className="studio-page studio-page-scroll"><CoCCharacterDesk onOpenHarness={(name) => { setTab('harness'); void loadConfig(name); }} /></div>}
      {/* Harness Tab */}
      {tab === 'harness' && (
        <>
          <Sidebar components={componentList} contracts={dagContracts} />
          <div className="flow-area" ref={reactFlowWrapper}>
            <ReactFlowProvider>
              <ReactFlow
                nodes={flowNodes}
                edges={flowEdges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onInit={setRfInstance}
                onDrop={onDrop}
                onDragOver={onDragOver}
                onNodeClick={onNodeClick}
                onEdgeClick={onEdgeClick}
                onPaneClick={onPaneClick}
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                onlyRenderVisibleElements
                fitView
                deleteKeyCode={['Backspace', 'Delete']}
              >
                <Background />
                <Controls />
                {showMinimap && <MiniMap
                  nodeColor={(n) => {
                    const op = (n.data as unknown as PipelineNode)?.op;
                    return contractFor(dagContracts, op)?.editor?.color || '#4a5568';
                  }}
                />}
              </ReactFlow>
            </ReactFlowProvider>

            <div className="toolbar">
              {saveMsg && (
                <span style={{ fontSize: 12, color: 'var(--success)', alignSelf: 'center', marginRight: 8 }}>
                  {saveMsg}
                </span>
              )}
              <button className={`btn btn-secondary ${showMinimap ? 'active' : ''}`} onClick={() => setShowMinimap((visible) => !visible)}>
                {showMinimap ? '隐藏概览' : '显示概览'}
              </button>
              <button className="btn btn-secondary" onClick={saveConfig}>💾 保存</button>
              {!execState.running ? (
                <>
                  <label className="debug-start-option" title="在第一个节点产生任何副作用之前停住">
                    <input type="checkbox" checked={startPaused} onChange={(event) => setStartPaused(event.target.checked)} />
                    首节点暂停
                  </label>
                  <button className="btn btn-exec" onClick={handleStartExec}>▶ 执行</button>
                </>
              ) : (
                <>
                  <button className="btn btn-secondary" onClick={() => handleExecutionControl('pause')} disabled={execState.debug_mode === 'paused' && execState.pause_requested}>
                    ⏸ 暂停
                  </button>
                  <button className="btn btn-secondary debug-step" onClick={() => handleExecutionControl('step')}>
                    ⏭ 单步
                  </button>
                  <button className="btn btn-secondary" onClick={() => handleExecutionControl('auto')} disabled={execState.debug_mode === 'auto'}>
                    ↻ 自动
                  </button>
                  <button className="btn btn-exec running" onClick={handleStopExec}>⏹ 停止</button>
                </>
              )}
              <button
                className="btn btn-secondary"
                onClick={() => setShowOutput(!showOutput)}
                style={{ marginLeft: 8 }}
              >
                {showOutput ? '📋 隐藏输出' : '📋 显示输出'}
              </button>
            </div>

            {/* 微信风格聊天气泡输出面板 */}
            {showOutput && (
              <div className="chat-output-panel">
                <div className="chat-output-body">
                  <div ref={outputsRef} className="chat-message-list" onScroll={(e) => {
                    const el = e.currentTarget;
                    userScrolledUp.current = el.scrollHeight - el.scrollTop - el.clientHeight > 60;
                  }}>
                  <div className="output-view-switch">
                    <button className={outputView === 'conversation' ? 'active' : ''} onClick={() => setOutputView('conversation')}>对话</button>
                    <button className={outputView === 'timeline' ? 'active' : ''} onClick={() => setOutputView('timeline')}>运行观测</button>
                  </div>
                  {outputView === 'timeline' && <RunObservability
                    traces={nodeTraces}
                    childRuns={chatMessages.flatMap((message) => message.sub_harness ? [message.sub_harness] : [])}
                    mutations={improveChanges}
                    onSelectTrace={setSelectedTraceSequence}
                    onOpenChanges={() => setTab('changes')}
                  />}
                  <div className="conversation-stream" style={{ display: outputView === 'conversation' ? 'flex' : 'none' }}>
                  {chatMessages.length === 0 && !execState.running && (
                    <div className="chat-empty-hint">等待输出...</div>
                  )}
                  {chatMessages.map((msg) => {
                    const color = AGENT_COLORS[msg.agent] || '#22d3ee';
                    const isUser = msg.agent === 'user';
                    const slotIdx = agentSlots.indexOf(msg.agent);
                    const isRight = isUser || (slotIdx >= 0 && slotIdx % 2 === 1);

                    // 如果是 sub_harness 消息，渲染嵌套面板
                    if (msg.sub_harness) {
                      const sh = msg.sub_harness;
                      return (
                        <div key={msg.id} className="chat-bubble-row left">
                          <span className="chat-bubble-sender" style={{ color }}>
                            {msg.agent} → 子Session
                          </span>
                          <div className="sub-harness-panel" style={{ borderColor: `${color}66` }}>
                            <div className="sub-harness-header">
                              <span className="sub-harness-icon">{sh.status === 'running' ? '⚡' : '✅'}</span>
                              <span className="sub-harness-title">{sh.harness_name}</span>
                              <span className="sub-harness-slots">
                                {Object.entries(sh.slots).map(([slot, id]) => `${slot}=${id}`).join(', ')}
                              </span>
                              <span className={`sub-harness-status ${sh.status}`}>
                                {sh.status === 'running' ? '运行中...' : '已完成'}
                              </span>
                            </div>
                            <div className="sub-harness-messages">
                              {sh.messages.map((subMsg, i) => {
                                const subColor = AGENT_COLORS[subMsg.agent] || '#a78bfa';
                                return (
                                  <div key={i} className="sub-harness-msg">
                                    <span className="sub-msg-agent" style={{ color: subColor }}>
                                      {subMsg.agent}
                                    </span>
                                    <span className="sub-msg-text">{subMsg.text}</span>
                                    {subMsg.tools && subMsg.tools.map((t, j) => (
                                      <span key={j} className="sub-msg-tool">🔧 {t.name}</span>
                                    ))}
                                  </div>
                                );
                              })}
                              {sh.status === 'running' && sh.messages.length === 0 && (
                                <div className="sub-harness-waiting">子 Agent 正在思考...</div>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    }

                    return (
                      <div key={msg.id} className={`chat-bubble-row ${isRight ? 'right' : 'left'}`}>
                        <span className="chat-bubble-sender" style={{ color }}>{msg.agent}</span>
                        <div className="chat-bubble" style={{
                          background: isRight ? `${color}18` : '#1a1a2e',
                          borderColor: `${color}44`,
                          borderRadius: isRight ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                        }}>
                          {msg.text}
                          {msg.tools.map((t, i) => {
                            // Diff 卡片渲染 for modify_harness / modify_identity
                            if ((t.name === 'modify_harness' || t.name === 'modify_identity') && t.result) {
                              try {
                                const res = JSON.parse(t.result);
                                if (res.success) {
                                  return (
                                    <div key={i} className="chat-tool-entry" style={{
                                      background: '#0f2744',
                                      border: '1px solid #065f46',
                                      borderRadius: 8,
                                      padding: '8px 12px',
                                      marginTop: 6,
                                    }}>
                                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                                        <span style={{ color: '#4ade80', fontWeight: 'bold', fontSize: 12 }}>
                                          ✅ {t.name === 'modify_harness' ? '🔗 Harness 修改' : '🤖 Identity 修改'}
                                        </span>
                                        <span style={{ color: '#888', fontSize: 11 }}>
                                          {res.harness || res.identity || ''} → {res.action}
                                        </span>
                                      </div>
                                      {res.target && (
                                        <div style={{ fontSize: 11, color: '#7ecfff', marginBottom: 2 }}>
                                          字段: <code style={{ background: '#1e3a5f', padding: '1px 4px', borderRadius: 3 }}>{res.target}</code>
                                        </div>
                                      )}
                                      {res.current_nodes && (
                                        <div style={{ fontSize: 10, color: '#666', marginTop: 4 }}>
                                          Pipeline 节点: {res.current_nodes.join(' → ')}
                                        </div>
                                      )}
                                    </div>
                                  );
                                }
                              } catch { /* fallback to plain text */ }
                            }
                            return (
                              <div key={i} className="chat-tool-entry">
                                🔧 <b>{t.name}</b>: {t.result}
                              </div>
                            );
                          })}
                          {msg.blocked.map((b, i) => (
                            <div key={i} className="chat-blocked-entry">
                              🚫 <b>{b.name}</b>: {b.reason}
                            </div>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                  </div>
                  </div>
                  {selectedTrace && (
                    <aside className="node-trace-inspector">
                      <div className="trace-inspector-header">
                        <div>
                          <strong>{selectedTrace.node_id}</strong>
                          <span>{selectedTrace.op}{selectedTrace.agent ? ` · @${selectedTrace.agent}` : ''}</span>
                        </div>
                        <button onClick={() => setSelectedTraceSequence(null)} aria-label="关闭节点检查器">×</button>
                      </div>
                      <div className="trace-invocations">
                        {nodeTraces.filter((trace) => trace.node_id === selectedTrace.node_id).map((trace) => (
                          <button
                            key={trace.sequence}
                            className={trace.sequence === selectedTrace.sequence ? 'active' : ''}
                            onClick={() => setSelectedTraceSequence(trace.sequence)}
                          >
                            #{trace.sequence} · {trace.status}
                          </button>
                        ))}
                      </div>
                      <div className="trace-metrics">
                        {selectedTrace.duration_ms != null && <span>{selectedTrace.duration_ms < 1000 ? `${Math.round(selectedTrace.duration_ms)} ms` : `${(selectedTrace.duration_ms / 1000).toFixed(2)} s`}</span>}
                        {selectedTrace.usage?.model && <span>{selectedTrace.usage.model}</span>}
                        {(selectedTrace.usage?.input_tokens || selectedTrace.usage?.output_tokens) && <span>{Number(selectedTrace.usage?.input_tokens || 0) + Number(selectedTrace.usage?.output_tokens || 0)} tokens</span>}
                        {!!selectedTrace.usage?.cached_input_tokens && <span>{selectedTrace.usage.cached_input_tokens} cached</span>}
                        {!!selectedTrace.usage?.attempts && <span>{selectedTrace.usage.attempts} attempts</span>}
                        {!!selectedTrace.usage?.reconnects && <span>{selectedTrace.usage.reconnects} reconnects</span>}
                        {!!Number(selectedTrace.stats?.cost_actual || selectedTrace.stats?.cost_estimated || 0) && <span>累计 ${Number(selectedTrace.stats?.cost_actual || selectedTrace.stats?.cost_estimated || 0).toFixed(6)}</span>}
                        {!!selectedTrace.retries?.length && <span>{selectedTrace.retries.length} retries</span>}
                        {!!selectedTrace.artifacts?.length && <span>{selectedTrace.artifacts.length} artifacts</span>}
                      </div>
                      {(selectedTrace.stats as any)?.context_compaction && (() => {
                        const pressure = (selectedTrace.stats as any).context_compaction;
                        return <div className={`trace-context-pressure ${pressure.phase || ''}`}>
                          <b>上下文 {pressure.phase === 'compacted' ? '已压缩' : pressure.phase === 'failed' ? '压缩失败' : '达到高水位'}</b>
                          <span>{Number(pressure.before_tokens_estimated ?? pressure.rendered_tokens_estimated ?? 0).toLocaleString()} → {Number(pressure.after_tokens_estimated ?? pressure.target_tokens ?? 0).toLocaleString()} tokens</span>
                          {pressure.saved_tokens_estimated != null && <small>节省 {Number(pressure.saved_tokens_estimated).toLocaleString()} · {Math.round(Number(pressure.reduction_ratio || 0) * 100)}%</small>}
                          {pressure.error && <small>{String(pressure.error)}</small>}
                        </div>;
                      })()}
                      {selectedTrace.error && <div className="trace-error"><b>{selectedTrace.error.type || 'Error'}</b>: {selectedTrace.error.message}</div>}
                      {execState.paused && execState.pending_node === selectedTrace.node_id && execState.pause_reason === 'before' && (
                        <div className="trace-debug-actions">
                          <strong>执行前控制</strong>
                          <label>修改输入（JSON 对象）</label>
                          <textarea value={debugInputOverride} onChange={(event) => setDebugInputOverride(event.target.value)} spellCheck={false} />
                          <button onClick={() => handleDebugDirective('override_inputs')}>用此输入继续</button>
                          <label>跳过时模拟的输出（JSON 对象）</label>
                          <textarea value={debugSkipOutput} onChange={(event) => setDebugSkipOutput(event.target.value)} spellCheck={false} />
                          <button className="danger" onClick={() => handleDebugDirective('skip')}>安全跳过节点</button>
                          <small>跳过不会调用模型、工具或进程；模拟输出仍会沿 DAG 的数据流继续传递。</small>
                        </div>
                      )}
                      {execState.paused && execState.pending_node === selectedTrace.node_id && execState.pause_reason === 'error' && (
                        <div className="trace-debug-actions error-retry">
                          <strong>节点失败后已暂停</strong>
                          <label>修改输入后重试（JSON 对象）</label>
                          <textarea value={debugInputOverride} onChange={(event) => setDebugInputOverride(event.target.value)} spellCheck={false} />
                          <button onClick={() => handleDebugDirective('retry_with_inputs')}>用此输入重试</button>
                          <small>运行时已经用完节点自身的重试次数。该操作会保留失败记录，并开始一次明确标记的调试重试；“自动”会放弃调试重试并按原错误路由。</small>
                        </div>
                      )}
                      <details open>
                        <summary>输入</summary>
                        <pre>{renderTraceValue(selectedTrace.input)}</pre>
                      </details>
                      {selectedTrace.model?.request != null && (
                        <details open>
                          <summary>模型收到的内容</summary>
                          <pre>{renderTraceValue(selectedTrace.model.request)}</pre>
                        </details>
                      )}
                      {selectedTrace.model?.response != null && selectedTrace.model.response !== '' && (
                        <details open>
                          <summary>模型回复</summary>
                          <pre>{renderTraceValue(selectedTrace.model.response)}</pre>
                        </details>
                      )}
                      {selectedTrace.model?.tool_calls != null && renderTraceValue(selectedTrace.model.tool_calls) !== '[]' && (
                        <details>
                          <summary>模型请求的工具</summary>
                          <pre>{renderTraceValue(selectedTrace.model.tool_calls)}</pre>
                        </details>
                      )}
                      {selectedTrace.tools.length > 0 && (
                        <details open>
                          <summary>工具执行（{selectedTrace.tools.length}）</summary>
                          {selectedTrace.tools.map((tool, index) => (
                            <div key={`${tool.name}-${index}`} className={`trace-tool ${tool.blocked ? 'blocked' : ''}`}>
                              <b>{tool.blocked ? '🚫' : '🔧'} {tool.name}</b>
                              {tool.arguments !== undefined && <pre>{renderTraceValue(tool.arguments)}</pre>}
                              <pre>{renderTraceValue(tool.blocked ? tool.reason : tool.result)}</pre>
                            </div>
                          ))}
                        </details>
                      )}
                      {!!selectedTrace.retries?.length && (
                        <details open>
                          <summary>重试记录（{selectedTrace.retries.length}）</summary>
                          <pre>{renderTraceValue(selectedTrace.retries)}</pre>
                        </details>
                      )}
                      {!!selectedTrace.artifacts?.length && (
                        <details open>
                          <summary>产物（{selectedTrace.artifacts.length}）</summary>
                          <div className="trace-artifacts">{selectedTrace.artifacts.map((artifact) => <code key={artifact}>{artifact}</code>)}</div>
                        </details>
                      )}
                      {selectedTrace.stats && Object.keys(selectedTrace.stats).length > 0 && (
                        <details>
                          <summary>运行统计</summary>
                          <pre>{renderTraceValue(selectedTrace.stats)}</pre>
                        </details>
                      )}
                      <details open>
                        <summary>输出 · {selectedTrace.status}</summary>
                        <pre>{renderTraceValue(selectedTrace.output)}</pre>
                      </details>
                    </aside>
                  )}
                </div>
                {execState.pending_approval && (
                  <div className={`studio-approval-card risk-${execState.pending_approval.risk?.level || 'high'}`} role="alertdialog" aria-label="危险操作审批">
                    <div className="studio-approval-header">
                      <strong>需要你的允许</strong>
                      <span>{String(execState.pending_approval.risk?.level || 'high').toUpperCase()}</span>
                    </div>
                    <p>{execState.pending_approval.prompt || execState.pending_approval.reason || 'Agent 请求执行可能产生副作用的操作。'}</p>
                    {execState.pending_approval.tool && <code>{execState.pending_approval.tool}</code>}
                    {execState.pending_approval.arguments !== undefined && (
                      <pre>{renderTraceValue(execState.pending_approval.arguments)}</pre>
                    )}
                    {execState.pending_approval.risk?.summary && <small>{execState.pending_approval.risk.summary}</small>}
                    <div className="studio-approval-actions">
                      <button className="reject" disabled={approvalBusy} onClick={() => handleApproval('rejected')}>拒绝</button>
                      <button className="approve" disabled={approvalBusy} onClick={() => handleApproval('approved')}>仅允许这一次</button>
                    </div>
                  </div>
                )}
                {!execState.running && execState.termination && (
                  <div className={`studio-termination-notice ${execState.status || 'error'}`} role="status">
                    <strong>{execState.termination.failure?.title || execState.termination.title || (execState.status === 'limit_exceeded' ? '运行达到限制' : '本次运行已结束')}</strong>
                    <span>{execState.termination.failure?.message || execState.termination.message || ''}</span>
                    {(execState.termination.failure?.action || execState.termination.action) && <small>下一步：{execState.termination.failure?.action || execState.termination.action}</small>}
                  </div>
                )}
                <div className="chat-input-bar">
                  {waitingNodeId && <span className="chat-waiting-badge">⏳ {waitingNodeId}</span>}
                  <input type="text" value={inputText}
                    onChange={(e) => { setInputText(e.target.value); }}
                    onKeyDown={handleInputKeyDown}
                    placeholder={execState.pending_approval ? '请先在上方明确允许或拒绝危险操作' : !execState.running ? '点击 ▶ 执行 启动' : (waitingNodeId ? `输入消息发送到 ${waitingNodeId}，回车发送...` : 'Agent 正在思考中...')}
                    disabled={!waitingNodeId || Boolean(execState.pending_approval)}
                    className="chat-input-field"
                    style={{ boxShadow: waitingNodeId ? '0 0 6px rgba(59,130,246,0.3)' : 'none' }}
                  />
                  <button onClick={handleSendInput} disabled={!waitingNodeId || Boolean(execState.pending_approval)}
                    className="chat-send-btn"
                    style={{ background: waitingNodeId ? '#7ecfff' : '#333' }}
                  >发送</button>
                </div>
                <div className="chat-status-bar">
                  <span><span className={`status-dot ${execState.running ? (execState.paused || execState.pending_approval ? 'paused' : 'running') : 'idle'}`} />{execState.pending_approval ? '等待危险操作审批' : execState.running ? (execState.paused ? `${execState.pause_reason === 'error' ? '失败后暂停' : '执行前暂停'}于 ${execState.pending_node || execState.current_node}` : waitingNodeId ? `本轮已完成 · 等待输入 (step ${execState.step_count})` : execState.pause_requested ? `将在下一节点暂停 (step ${execState.step_count})` : `自动运行 (step ${execState.step_count})`) : execState.status === 'limit_exceeded' ? '已达到运行限制' : execState.status === 'error' ? '执行失败' : execState.status === 'cancelled' ? '已停止' : '就绪'}</span>
                  <span>节点: {flowNodes.length}</span>
                  <span>连线: {flowEdges.length}</span>
                  {execState.current_node && <span>当前节点: <b>{execState.current_node}</b></span>}
                  <span>轨迹: {nodeTraces.length}</span>
                </div>
              </div>
            )}

            {/* 未执行时的状态栏 */}
            {!showOutput && (
              <div className="status-bar">
                <span>
                  <span className="status-dot idle" />
                  就绪
                </span>
                <span>节点: {flowNodes.length}</span>
                <span>连线: {flowEdges.length}</span>
              </div>
            )}
          </div>

          <RightPanel
            config={config}
            selectedNode={selectedNode}
            selectedEdge={selectedEdge}
            onConfigChange={setConfig}
            onNodeUpdate={handleNodeUpdate}
            onEdgeUpdate={handleEdgeUpdate}
            onDeleteNode={handleDeleteNode}
            onDeleteEdge={handleDeleteEdge}
            onSave={saveConfig}
            onLoad={loadConfig}
            harnessList={harnessList}
            componentList={componentList}
            identityList={identityList}
            dagContracts={dagContracts}
            onRefreshIdentities={refreshIdentities}
          />
        </>
      )}

      {tab === 'tasks' && (
        <div className="studio-page">
          <TaskBench />
        </div>
      )}

      {tab === 'ir' && (
        <div className="studio-page">
          <EgoIRWorkbench />
        </div>
      )}

      {tab === 'research' && (
        <div className="studio-page">
          <ResearchLab />
        </div>
      )}

      {tab === 'background' && (
        <div className="studio-page studio-page-scroll">
          <BackgroundRuns />
        </div>
      )}

      {tab === 'packages' && (
        <div className="studio-page studio-page-scroll"><PackageMarketplace /></div>
      )}

      {tab === 'library' && (
        <div className="studio-page studio-page-scroll"><CapabilityLibrary /></div>
      )}

      {tab === 'changes' && (
        <div className="studio-page studio-page-scroll">
          <ChangeDashboard />
        </div>
      )}

      {tab === 'checkpoints' && (
        <div className="studio-page studio-page-scroll">
          <CheckpointDashboard />
        </div>
      )}

      {/* Identity Tab */}
      {tab === 'identity' && (
        <div className="studio-page">
          <IdentityManager />
        </div>
      )}

      {/* Environment Tab */}
      {tab === 'environment' && (
        <div className="studio-page">
          <EnvironmentManager />
        </div>
      )}

      {/* Sessions Tab */}
      {tab === 'sessions' && (
        <div className="studio-page">
          <SessionExplorer />
        </div>
      )}

      {/* Settings Tab */}
      {tab === 'settings' && (
        <div className="studio-page studio-page-scroll">
          <Settings />
        </div>
      )}
      {/* Evolution Tab */}
      {tab === 'evolution' && (
        <div className="studio-page studio-page-scroll">
          <EvolutionPanel />
        </div>
      )}
      </Suspense>
    </div>
  );
}
