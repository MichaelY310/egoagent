import { lazy, Suspense, useState, useCallback, useRef, useEffect, useMemo, type DragEvent } from 'react';
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
  ConnectionLineType,
  MarkerType,
  SelectionMode,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import Sidebar from './components/Sidebar';
import FlowRunViewer from './components/FlowRunViewer';
import { configToFlow, layoutFlowNodes } from './flowGraph';
import RightPanel from './components/RightPanel';
import { contractFor, type DagContractCatalog } from './components/DagFormEditors';
import RunObservability, { type ChangeEntry } from './components/RunObservability';
import LiveAgentArchitecture from './components/LiveAgentArchitecture';
import AutoLayoutPanel from './components/AutoLayoutPanel';
import PipelineNodeComponent from './nodes/PipelineNode';
import ConditionEdge from './edges/ConditionEdge';
import { GraphInteractionContext } from './GraphInteractionContext';
import * as api from './api/client';
import { EMBEDDED_IN_IDE, INITIAL_LINK_RUN_ID, INITIAL_TAB, RUNTIME_LABEL, WORKSPACE, isCurrentWorkspace } from './api/runtime';
import type { HarnessConfig, PipelineNode, EdgeCondition, OpType, ExecutionState, NodeTrace, BezierKnot } from './types';
import {
  EVENT_PREFIX,
  FLOW_INPUT_HANDLE,
  INPUT_PREFIX,
  OUTPUT_PREFIX,
  parseSocketHandle,
  portTypesCompatible,
  socketType,
} from './graphSockets';
import {
  loadWorkbenchSession,
  publishWorkbenchEvent,
  updateWorkbenchSession,
  type WorkbenchRoute,
} from './workbenchSession';
import { postToIde, type IdeContextItem } from './ideBridge';
import { applyWorkbenchTheme, readWorkbenchTheme, type WorkbenchTheme } from './theme';
import { autoLayoutFlow, DEFAULT_AUTO_LAYOUT_OPTIONS, type AutoLayoutOptions, type LayoutMetrics } from './graphAutoLayout';
import {
  appendMessageTokenBatch,
  appendTraceTokenBatch,
  normalizeChatMessages,
  renderTraceValue,
  stripEventEnvelope,
  traceSnapshotSignature,
  updateLatestTrace,
  type ChatMessage,
  type PendingStreamToken,
} from './executionProjection';
import {
  diffFlowGraphs,
  normalizeMutationPayload,
  reduceRuntimeRunEvent,
  runtimeEventBelongsToRoot,
  storyEvent,
  type RuntimeRunView,
  type RuntimeStoryEvent,
} from './runtimeTopology';

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
const ObservationRoom = lazy(() => import('./components/ObservationRoom'));
const ChangeDashboard = lazy(() => import('./components/ChangeDashboard'));
const CheckpointDashboard = lazy(() => import('./components/CheckpointDashboard'));
const BackgroundRuns = lazy(() => import('./components/BackgroundRuns'));
const PackageMarketplace = lazy(() => import('./components/PackageMarketplace'));
const CapabilityLibrary = lazy(() => import('./components/CapabilityLibrary'));
const EgoIRWorkbench = lazy(() => import('./components/EgoIRWorkbench'));
const ResearchLab = lazy(() => import('./components/ResearchLab'));
const StudioHome = lazy(() => import('./components/StudioHome'));
const CoCCharacterDesk = lazy(() => import('./components/CoCCharacterDesk'));
// HEART_FLOW_DEMO_HOOK: remove this lazy import, its tab and render block to
// uninstall the optional experiment; no Project/Session code is affected.
const HeartFlowDemo = lazy(() => import('./heartflow/HeartFlowDemo'));

const DEFAULT_CONFIG: HarnessConfig = {
  name: 'untitled_custom_flow',
  description: '',
  slots: {},
  prompts: {},
  return_mode: 'all',
  pipeline: { start: '', max_steps: 100, workspace_preview: false, nodes: {} },
};

type TabType = WorkbenchRoute;
type BuilderMode = 'build' | 'locked' | 'linked';

const IDLE_EXECUTION_STATE: ExecutionState = {
  running: false,
  current_node: null,
  step_count: 0,
  messages_count: 0,
  debug_mode: 'auto',
  paused: false,
  pause_requested: false,
  pending_node: null,
  node_traces: [],
};

const STUDIO_TABS: Array<{ id: TabType; icon: string; label: string; detail: string; group: 'primary' | 'manage' | 'system' }> = [
  { id: 'home', icon: '⌂', label: 'Home', detail: '构建、评测、改进与发布', group: 'primary' },
  { id: 'harness', icon: '◇', label: 'Build', detail: 'Identity + EGO + DAG', group: 'primary' },
  { id: 'tasks', icon: '▦', label: 'Evaluate', detail: '任务、数据集、回放与评分', group: 'primary' },
  { id: 'observe', icon: '◷', label: '运行相簿', detail: '所有入口的实时 Flow、录制与回放', group: 'primary' },
  { id: 'library', icon: '▤', label: 'Library', detail: '发现并复用本地能力', group: 'primary' },
  { id: 'evolution', icon: '↗', label: 'Improve', detail: '从真实失败到可信演进', group: 'primary' },
  { id: 'more', icon: '•••', label: 'More', detail: '高级工作台与记录', group: 'primary' },
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
  { id: 'flow', icon: '◍', label: 'Heart Flow', detail: '跨项目专注与续接实验', group: 'manage' },
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

function MoreWorkbench({ onNavigate }: { onNavigate: (tab: TabType) => void }) {
  const tools = STUDIO_TABS.filter((item) => item.group !== 'primary');
  return <main className="more-workbench">
    <header><span>ADVANCED WORKSPACES</span><h1>更多工作台</h1><p>这些功能不会在后台自动运行。选择一个明确的工作台后，才会加载对应数据和控制项。</p></header>
    <section aria-label="更多 EgoAgent 工作台">{tools.map((item) => <button key={item.id} onClick={() => onNavigate(item.id)}>
      <i>{item.icon}</i><span><b>{item.label}</b><small>{item.detail}</small></span><em>打开 →</em>
    </button>)}</section>
  </main>;
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

type GraphSnapshot = {
  config: HarnessConfig;
  nodes: Node[];
  edges: Edge[];
};

function cloneGraphSnapshot(config: HarnessConfig, nodes: Node[], edges: Edge[]): GraphSnapshot {
  return structuredClone({ config, nodes, edges });
}

function defaultNodeData(id: string, op: OpType, contracts?: DagContractCatalog | null): PipelineNode {
  const base: PipelineNode = { id, op, edges: [], inputs: {}, outputs: {} };
  const defaults = contractFor(contracts, op)?.editor?.defaults || {};
  return { ...base, ...structuredClone(defaults) } as PipelineNode;
}


function fitWholeGraph(instance: any, container: HTMLDivElement | null, nodes: Node[], edges: Edge[], duration = 260) {
  if (!instance || !container || !nodes.length) return;
  const xs: number[] = [];
  const ys: number[] = [];
  nodes.forEach((node) => {
    const width = Number(node.measured?.width || node.width || 188);
    const height = Number(node.measured?.height || node.height || 96);
    xs.push(node.position.x, node.position.x + width);
    ys.push(node.position.y, node.position.y + height);
  });
  edges.forEach((edge) => {
    const reroutes = Array.isArray((edge.data as any)?.reroutes) ? (edge.data as any).reroutes : [];
    reroutes.forEach((point: any) => {
      if (Number.isFinite(Number(point.x)) && Number.isFinite(Number(point.y))) {
        xs.push(Number(point.x));
        ys.push(Number(point.y));
      }
    });
  });
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const boundsWidth = Math.max(1, maxX - minX);
  const boundsHeight = Math.max(1, maxY - minY);
  const insetX = 54;
  const insetTop = 74;
  const insetBottom = 48;
  const availableWidth = Math.max(160, container.clientWidth - insetX * 2);
  const availableHeight = Math.max(120, container.clientHeight - insetTop - insetBottom);
  const zoom = clampViewportZoom(Math.min(availableWidth / boundsWidth, availableHeight / boundsHeight, 1.15));
  const x = insetX + (availableWidth - boundsWidth * zoom) / 2 - minX * zoom;
  const y = insetTop + (availableHeight - boundsHeight * zoom) / 2 - minY * zoom;
  instance.setViewport?.({ x, y, zoom }, { duration });
}

function clampViewportZoom(zoom: number) {
  return Math.max(0.08, Math.min(1.15, Number.isFinite(zoom) ? zoom : 1));
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
    node.editor_position = { x: Number(n.position.x), y: Number(n.position.y) };
    delete node.highlight;
    delete node.subHarness;
    delete node.runtimeStatus;
    delete node.runtimeCount;
    delete node.runtimeTrace;
    delete node.runtimeActivityMode;
    delete node.runtimePaused;
    delete (node as any)._mutationState;
    delete node._contract;
    delete (node as any)._expanded;
    delete (node as any)._edgeEvents;
    delete (node as any)._edgeOutputs;
    node.inputs = Object.fromEntries(Object.entries(node.inputs || {}).filter(([, value]) => (
      !(typeof value === 'string' && /^\$node\.[^.]+\..+$/.test(value))
    )));
    nodes[n.id] = node;
  });

  const dataLinks: NonNullable<HarnessConfig['pipeline']['data_links']> = [];
  flowEdges.forEach((e) => {
    const src = nodes[e.source];
    const target = nodes[e.target];
    const sourceSocket = parseSocketHandle(e.sourceHandle);
    const targetSocket = parseSocketHandle(e.targetHandle);
    const kind = String((e.data as any)?.kind || 'control');
    if (kind === 'data' || sourceSocket.socketClass === 'output' || targetSocket.socketClass === 'input') {
      if (!src || !target || sourceSocket.socketClass !== 'output' || targetSocket.socketClass !== 'input') return;
      target.inputs = { ...(target.inputs || {}), [targetSocket.name]: `$node.${e.source}.${sourceSocket.name}` };
      dataLinks.push({
        id: e.id,
        source: e.source,
        source_port: sourceSocket.name,
        target: e.target,
        target_port: targetSocket.name,
        reroutes: Array.isArray((e.data as any)?.reroutes)
          ? (e.data as any).reroutes.map((point: any, index: number) => ({
              id: String(point.id || `reroute-${index}`), x: Number(point.x), y: Number(point.y),
              ...(Number.isFinite(Number(point.angle)) ? { angle: Number(point.angle) } : {}),
              ...(Number.isFinite(Number(point.in_length)) ? { in_length: Number(point.in_length) } : {}),
              ...(Number.isFinite(Number(point.out_length)) ? { out_length: Number(point.out_length) } : {}),
            }))
          : [],
        source_handle: Number.isFinite(Number((e.data as any)?.sourceHandle)) ? Number((e.data as any).sourceHandle) : undefined,
        target_handle: Number.isFinite(Number((e.data as any)?.targetHandle)) ? Number((e.data as any).targetHandle) : undefined,
        curvature: Number((e.data as any)?.curvature ?? 0.72),
        label_offset: Number((e.data as any)?.labelOffset || 0),
      });
      return;
    }
    if (src) {
      const condition = (e.data as any)?.condition || 'default';
      src.edges.push({
        condition, to: e.target,
        source_port: sourceSocket.socketClass === 'event' ? sourceSocket.name : condition,
        target_port: targetSocket.socketClass === 'flow' ? FLOW_INPUT_HANDLE : targetSocket.name,
        route: ((e.data as any)?.route === 'straight' ? 'straight' : 'bezier') as any,
        reroutes: Array.isArray((e.data as any)?.reroutes)
          ? (e.data as any).reroutes.map((point: any, index: number) => ({
              id: String(point.id || `reroute-${index}`), x: Number(point.x), y: Number(point.y),
              ...(Number.isFinite(Number(point.angle)) ? { angle: Number(point.angle) } : {}),
              ...(Number.isFinite(Number(point.in_length)) ? { in_length: Number(point.in_length) } : {}),
              ...(Number.isFinite(Number(point.out_length)) ? { out_length: Number(point.out_length) } : {}),
            }))
          : [],
        source_handle: Number.isFinite(Number((e.data as any)?.sourceHandle)) ? Number((e.data as any).sourceHandle) : undefined,
        target_handle: Number.isFinite(Number((e.data as any)?.targetHandle)) ? Number((e.data as any).targetHandle) : undefined,
        channel_offset: 0,
        curvature: Number((e.data as any)?.curvature ?? 0.72),
        label_offset: Number((e.data as any)?.labelOffset || 0),
      });
    }
  });

  return {
    ...config,
    pipeline: {
      ...config.pipeline,
      nodes,
      data_links: dataLinks,
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
  const [observationTarget, setObservationTarget] = useState('');
  const [theme, setTheme] = useState<WorkbenchTheme>(readWorkbenchTheme);
  const [runtimeOnline, setRuntimeOnline] = useState<boolean | null>(null);
  const [config, setConfig] = useState<HarnessConfig>(restoredBuilder.config);
  const [flowNodes, setFlowNodes, onNodesChange] = useNodesState<Node>(restoredBuilder.nodes);
  const flowContractSignature = flowNodes.map((node) => `${node.id}:${String((node.data as any).op || '')}`).join('|');
  const [flowEdges, setFlowEdges, onEdgesChange] = useEdgesState<Edge>(restoredBuilder.edges);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(restoredBuilder.selectedNodeId);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(restoredBuilder.selectedEdgeId);
  const [expandedNodeId, setExpandedNodeId] = useState<string | null>(null);
  const [showBuilderPalette, setShowBuilderPalette] = useState(!EMBEDDED_IN_IDE);
  const [showBuilderInspector, setShowBuilderInspector] = useState(!EMBEDDED_IN_IDE);
  const [harnessList, setHarnessList] = useState<string[]>([]);
  const [harnessCatalog, setHarnessCatalog] = useState<api.HarnessCatalogItem[]>([]);
  const [harnessVersions, setHarnessVersions] = useState<api.HarnessVersion[]>([]);
  const [selectedHarnessVersion, setSelectedHarnessVersion] = useState('');
  const [latestHarnessVersion, setLatestHarnessVersion] = useState('');
  const [componentList, setComponentList] = useState<api.HarnessCatalogItem[]>([]);
  const [identityList, setIdentityList] = useState<string[]>([]);
  const [dagContracts, setDagContracts] = useState<DagContractCatalog | null>(null);
  const [execState, setExecState] = useState<ExecutionState>(IDLE_EXECUTION_STATE);
  // URL linking is transactional: remain an editable draft until both the
  // requested Session state and its exact Harness have loaded successfully.
  // Otherwise a stale/legacy run must never leave a false frozen canvas.
  const [builderMode, setBuilderMode] = useState<BuilderMode>('build');
  const [linkedRunId, setLinkedRunId] = useState('');
  const [historicalReplay, setHistoricalReplay] = useState<{ runId: string; taskId: string } | null>(null);
  const [leaveLinkedDialogOpen, setLeaveLinkedDialogOpen] = useState(false);
  const builderExecutionRunId = useRef<string | undefined>(undefined);
  const activeExecutionRunId = useRef<string | undefined>(undefined);
  const linkedHarnessRef = useRef('');
  const [nodeTraces, setNodeTraces] = useState<NodeTrace[]>([]);
  const [selectedTraceSequence, setSelectedTraceSequence] = useState<number | null>(null);
  const [startPaused, setStartPaused] = useState(false);
  const [executionStarting, setExecutionStarting] = useState(false);
  const [debugInputOverride, setDebugInputOverride] = useState('{}');
  const [debugSkipOutput, setDebugSkipOutput] = useState('{}');
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const chatMsgId = useRef(0);
  const [inputText, setInputText] = useState('');
  const [saveMsg, setSaveMsg] = useState('');
  const [showOutput, setShowOutput] = useState(restoredBuilder.showOutput);
  const [showMinimap, setShowMinimap] = useState(false);
  const [showLiveArchitecture, setShowLiveArchitecture] = useState(true);
  const [autoLayoutOptions, setAutoLayoutOptions] = useState<AutoLayoutOptions>(DEFAULT_AUTO_LAYOUT_OPTIONS);
  const [autoLayoutReport, setAutoLayoutReport] = useState<{ before: LayoutMetrics; after: LayoutMetrics } | null>(null);
  const [outputView, setOutputView] = useState<'conversation' | 'timeline'>(restoredBuilder.outputView);
  const [waitingNodeId, setWaitingNodeId] = useState<string | null>(null);
  const [activeSubHarness, setActiveSubHarness] = useState<string | null>(null);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [rfInstance, setRfInstance] = useState<any>(null);
  const outputsRef = useRef<HTMLDivElement>(null);
  const flowNodesRef = useRef<Node[]>([]);
  flowNodesRef.current = flowNodes;
  const flowEdgesRef = useRef<Edge[]>([]);
  flowEdgesRef.current = flowEdges;
  const configRef = useRef(config);
  configRef.current = config;
  const graphHistoryPast = useRef<GraphSnapshot[]>([]);
  const graphHistoryFuture = useRef<GraphSnapshot[]>([]);
  const [graphHistoryTick, setGraphHistoryTick] = useState(0);
  const [improveChanges, setImproveChanges] = useState<ChangeEntry[]>([]);
  const [runtimeRuns, setRuntimeRuns] = useState<RuntimeRunView[]>([]);
  const runtimeRunIds = useRef(new Set<string>());
  const [runtimeStory, setRuntimeStory] = useState<RuntimeStoryEvent[]>([]);
  const [interruptedRuns, setInterruptedRuns] = useState<InterruptedRun[]>([]);
  const [recoveryBusy, setRecoveryBusy] = useState<string | null>(null);
  const [approvalBusy, setApprovalBusy] = useState(false);

  useEffect(() => {
    setFlowNodes((nodes) => nodes.map((node) => {
      const expanded = node.id === expandedNodeId;
      if (Boolean((node.data as any)._expanded) === expanded) return node;
      return { ...node, data: { ...node.data, _expanded: expanded } };
    }));
  }, [expandedNodeId, setFlowNodes]);

  useEffect(() => {
    const editable = builderMode === 'build';
    setFlowEdges((edges) => edges.map((edge) => (
      (edge.data as any)?.editable === editable
        ? edge
        : { ...edge, data: { ...edge.data, editable } }
    )));
  }, [builderMode, setFlowEdges]);

  // The inspector keeps its own selected id so it can survive panel/layout
  // changes. Mirror that id back into XYFlow: custom edges receive the
  // `selected` prop only through the edge model, and their route handles must
  // therefore not depend on a transient pointer event.
  useEffect(() => {
    if (!selectedEdgeId) return;
    setFlowEdges((edges) => edges.map((edge) => {
      const selected = edge.id === selectedEdgeId;
      const zIndex = selected ? 20 : 0;
      return edge.selected === selected && edge.zIndex === zIndex ? edge : { ...edge, selected, zIndex };
    }));
  }, [selectedEdgeId, setFlowEdges]);

  const selectEdgeFromCanvas = useCallback((id: string, additive = false) => {
    if (!id) return;
    setExpandedNodeId(null);
    setSelectedNodeId(null);
    setSelectedEdgeId(additive ? null : id);
    if (!additive) setFlowNodes((nodes) => nodes.map((node) => node.selected ? { ...node, selected: false } : node));
    setFlowEdges((edges) => edges.map((edge) => {
      // The custom SVG hit target emits both pointerdown and click. Additive
      // selection is idempotent so that a Shift-click cannot toggle twice.
      const nextSelected = additive ? (edge.id === id ? true : Boolean(edge.selected)) : edge.id === id;
      const zIndex = nextSelected ? 20 : 0;
      return edge.selected === nextSelected && edge.zIndex === zIndex ? edge : { ...edge, selected: nextSelected, zIndex };
    }));
  }, [setFlowEdges, setFlowNodes]);
  const graphInteraction = useMemo(() => ({ selectEdge: selectEdgeFromCanvas }), [selectEdgeFromCanvas]);

  useEffect(() => {
    const selectFromCustomEdge = (event: Event) => {
      const detail = (event as CustomEvent<{ id?: string; additive?: boolean }>).detail;
      selectEdgeFromCanvas(String(detail?.id || ''), Boolean(detail?.additive));
    };
    window.addEventListener('egoagent-edge-select', selectFromCustomEdge);
    return () => window.removeEventListener('egoagent-edge-select', selectFromCustomEdge);
  }, [selectEdgeFromCanvas]);

  const recordGraphHistory = useCallback(() => {
    const snapshot = cloneGraphSnapshot(configRef.current, flowNodesRef.current, flowEdgesRef.current);
    graphHistoryPast.current = [...graphHistoryPast.current.slice(-99), snapshot];
    graphHistoryFuture.current = [];
    setGraphHistoryTick((value) => value + 1);
  }, []);

  const restoreGraphSnapshot = useCallback((snapshot: GraphSnapshot) => {
    setConfig(snapshot.config);
    setFlowNodes(snapshot.nodes);
    setFlowEdges(snapshot.edges);
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setExpandedNodeId(null);
  }, [setFlowEdges, setFlowNodes]);

  const undoGraph = useCallback(() => {
    const snapshot = graphHistoryPast.current.pop();
    if (!snapshot) return;
    graphHistoryFuture.current.push(cloneGraphSnapshot(configRef.current, flowNodesRef.current, flowEdgesRef.current));
    restoreGraphSnapshot(snapshot);
    setGraphHistoryTick((value) => value + 1);
    setSaveMsg('已撤销上一项 Flow 编辑');
  }, [restoreGraphSnapshot]);

  const redoGraph = useCallback(() => {
    const snapshot = graphHistoryFuture.current.pop();
    if (!snapshot) return;
    graphHistoryPast.current.push(cloneGraphSnapshot(configRef.current, flowNodesRef.current, flowEdgesRef.current));
    restoreGraphSnapshot(snapshot);
    setGraphHistoryTick((value) => value + 1);
    setSaveMsg('已重做 Flow 编辑');
  }, [restoreGraphSnapshot]);

  useEffect(() => {
    const begin = () => recordGraphHistory();
    window.addEventListener('egoagent-graph-history-begin', begin);
    return () => window.removeEventListener('egoagent-graph-history-begin', begin);
  }, [recordGraphHistory]);

  useEffect(() => {
    const eventsByNode = new Map<string, string[]>();
    const outputsByNode = new Map<string, string[]>();
    flowEdges.forEach((edge) => {
      const parsed = parseSocketHandle(edge.sourceHandle);
      if (parsed.socketClass === 'event') {
        const events = eventsByNode.get(edge.source) || [];
        if (!events.includes(parsed.name)) events.push(parsed.name);
        eventsByNode.set(edge.source, events);
      } else if (parsed.socketClass === 'output') {
        const outputs = outputsByNode.get(edge.source) || [];
        if (!outputs.includes(parsed.name)) outputs.push(parsed.name);
        outputsByNode.set(edge.source, outputs);
      }
    });
    setFlowNodes((nodes) => {
      let changed = false;
      const next = nodes.map((node) => {
        const events = eventsByNode.get(node.id) || [];
        const outputs = outputsByNode.get(node.id) || [];
        const previous = Array.isArray((node.data as any)._edgeEvents) ? (node.data as any)._edgeEvents : [];
        const previousOutputs = Array.isArray((node.data as any)._edgeOutputs) ? (node.data as any)._edgeOutputs : [];
        if (
          previous.length === events.length && previous.every((value: string, index: number) => value === events[index]) &&
          previousOutputs.length === outputs.length && previousOutputs.every((value: string, index: number) => value === outputs[index])
        ) return node;
        changed = true;
        return { ...node, data: { ...node.data, _edgeEvents: events, _edgeOutputs: outputs } };
      });
      return changed ? next : nodes;
    });
  }, [flowEdges, setFlowNodes]);

  useEffect(() => applyWorkbenchTheme(theme), [theme]);

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
        setHarnessCatalog(details);
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

    const seenMutationKeys = new Set<string>();
    const upsertHarnessChange = (entry: ChangeEntry) => setImproveChanges((previous) => {
      const key = entry.transactionId || `${entry.target}:${entry.action}:${entry.revision || ''}:${JSON.stringify(entry.diff || '')}`;
      const index = previous.findIndex((item) => (item.transactionId || `${item.target}:${item.action}:${item.revision || ''}:${JSON.stringify(item.diff || '')}`) === key);
      if (index < 0) return [...previous.slice(-39), entry];
      return previous.map((item, itemIndex) => itemIndex === index ? { ...item, ...entry } : item);
    });
    const projectHarnessMutation = (payload: Record<string, any>) => {
      const mutation = normalizeMutationPayload(payload);
      if (!mutation.target) return;
      const mutationKey = mutation.transactionId || `${mutation.target}:${mutation.action}:${mutation.revision}:${JSON.stringify(mutation.diff || '')}`;
      if (seenMutationKeys.has(mutationKey)) return;
      seenMutationKeys.add(mutationKey);
      const baseEntry: ChangeEntry = {
        timestamp: Date.now(),
        type: 'harness',
        target: mutation.target,
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
      };
      if (mutation.target !== configRef.current.name) {
        upsertHarnessChange(baseEntry);
        return;
      }
      const before = structuredClone(configRef.current);
      api.loadHarness(mutation.target).then((cfg) => {
        cfg.prompts = cfg.prompts || {};
        cfg.slots = cfg.slots || {};
        cfg.pipeline = cfg.pipeline || { start: '', max_steps: 100, workspace_preview: false, nodes: {} };
        const delta = diffFlowGraphs(before, cfg);
        const graph = configToFlow(cfg);
        graph.nodes = graph.nodes.map((node) => ({
          ...node,
          data: {
            ...node.data,
            _mutationState: delta.addedNodes.includes(node.id) ? 'added' : delta.changedNodes.includes(node.id) ? 'changed' : undefined,
          },
        }));
        setConfig(cfg);
        setFlowNodes(graph.nodes);
        setFlowEdges(graph.edges);
        upsertHarnessChange({ ...baseEntry, ...delta, nodes: Object.keys(cfg.pipeline.nodes) });
        setSaveMsg(`Flow 已实时更新 · +${delta.addedNodes.length} −${delta.removedNodes.length} ~${delta.changedNodes.length}`);
      }).catch((error) => {
        upsertHarnessChange(baseEntry);
        setSaveMsg(`Flow 已改变，但刷新失败：${error instanceof Error ? error.message : String(error)}`);
      });
    };

    const unsub = api.subscribeExecution((msg) => {
      const incomingScope = msg.scope || msg;
      if (incomingScope?.workspace && !isCurrentWorkspace(incomingScope.workspace)) return;
      // Never adopt the newest workspace run implicitly.  Build/debug and
      // Session visualization are explicit run-id scoped surfaces.
      const targetRunId = activeExecutionRunId.current;
      const incomingType = msg.type as string | undefined;
      const incomingData = msg.data || {};
      const runtimeEnvelope = { ...(incomingScope || {}), ...(incomingData || {}) };
      // Nested PipelineRunner events carry the child run id in the event data
      // while the websocket envelope can still be scoped to the root. Always
      // prefer the inner id so a SubFlow becomes a child card instead of
      // corrupting the root node trace.
      const incomingRunId = runtimeEnvelope?.run_id ? String(runtimeEnvelope.run_id) : undefined;
      if (!targetRunId || !incomingRunId || !runtimeEventBelongsToRoot(runtimeEnvelope, targetRunId, runtimeRunIds.current)) return;
      if (incomingType === 'run_started' || runtimeEnvelope.parent_run_id) runtimeRunIds.current.add(incomingRunId);
      const isChildRun = incomingRunId !== targetRunId;
      if (isChildRun && incomingType) {
        setRuntimeRuns((previous) => reduceRuntimeRunEvent(previous, incomingType, runtimeEnvelope));
        // Child events have their own node ids and traces. Showing them on the
        // parent canvas makes unrelated nodes flash; the live architecture
        // panel owns their rendering instead.
        return;
      }
      if (incomingType) {
        const narrative = storyEvent(incomingType, runtimeEnvelope);
        if (narrative) setRuntimeStory((previous) => [...previous.slice(-59), narrative]);
      }
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
        } else if (builderMode !== 'linked') {
          const finalMessage = msg.termination?.failure?.message || msg.termination?.message || '';
          const finalStatus = msg.status === 'error' || msg.status === 'limit_exceeded'
            ? `独立试跑失败${finalMessage ? ` · ${finalMessage}` : ''}`
            : msg.status === 'cancelled'
              ? '独立试跑已停止'
              : '独立试跑已结束';
          setSaveMsg(finalStatus);
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
          // Runtime mutations are projected as before/after graph revisions.
          if ((data.name === 'modify_harness' || data.name === 'manage_harness') && data.result) {
            projectHarnessMutation(data);
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
          projectHarnessMutation(data);
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
  }, [builderMode, tab, execState.running, setFlowNodes]);

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
      const targetRunId = activeExecutionRunId.current;
      if (!targetRunId) return;
      try {
          const state = await api.getExecutionState(targetRunId);
          if (state.workspace && !isCurrentWorkspace(state.workspace)) return;
          if (String(state.run_id || '') !== targetRunId) return;
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
              prev.debug_mode === state.debug_mode &&
              prev.status === state.status &&
              JSON.stringify(prev.termination || null) === JSON.stringify(state.termination || null)
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
          else if (builderMode !== 'linked') {
            const finalMessage = state.termination?.failure?.message || state.termination?.message || '';
            setSaveMsg(
              state.status === 'error' || state.status === 'limit_exceeded'
                ? `独立试跑失败${finalMessage ? ` · ${finalMessage}` : ''}`
                : state.status === 'cancelled' ? '独立试跑已停止' : '独立试跑已结束',
            );
          }
          // HTTP 轮询仅在 WebSocket 未提供数据时作为兜底，不覆盖已有消息
          if (state.outputs && state.outputs.length > 0 && state._tick !== lastOutputTick.current) {
            lastOutputTick.current = state._tick;
            setChatMessages((prev) => prev.length === 0 ? normalizeChatMessages(state.outputs) : prev);
          }
        }
      } catch {}
    }, 2500);
    return () => clearInterval(interval);
  }, [builderMode, tab, setFlowNodes]);

  const userScrolledUp = useRef(false);

  useEffect(() => {
    if (outputsRef.current && !userScrolledUp.current) {
      outputsRef.current.scrollTop = outputsRef.current.scrollHeight;
    }
  }, [chatMessages]);

  const loadConfig = useCallback(async (name: string, version = 'latest') => {
    try {
      setHistoricalReplay(null);
      if (builderMode === 'linked') {
        setBuilderMode('build');
        setLinkedRunId('');
        linkedHarnessRef.current = '';
        activeExecutionRunId.current = builderExecutionRunId.current;
      }
      const versionIndex = await api.listHarnessVersions(name);
      const resolvedVersion = version === 'latest' ? versionIndex.latest : version;
      const cfg = version === 'latest' ? await api.loadHarness(name) : await api.loadHarnessVersion(name, version);
      cfg.prompts = cfg.prompts || {};
      cfg.slots = cfg.slots || {};
      cfg.return_mode = cfg.return_mode || 'all';
      cfg.pipeline = cfg.pipeline || { start: '', max_steps: 100, workspace_preview: false, nodes: {} };
      setConfig(cfg);
      setHarnessVersions(versionIndex.versions || []);
      setLatestHarnessVersion(versionIndex.latest || '');
      setSelectedHarnessVersion(resolvedVersion || String((cfg as any)._flow_version || ''));
      const { nodes, edges } = configToFlow(cfg);
      setFlowNodes(nodes);
      setFlowEdges(edges);
      graphHistoryPast.current = [];
      graphHistoryFuture.current = [];
      setGraphHistoryTick((value) => value + 1);
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
      setSelectedTraceSequence(null);
      setNodeTraces([]);
      setRuntimeRuns([]);
      setRuntimeStory([]);
      runtimeRunIds.current.clear();
      setSaveMsg(`已加载: ${name}`);
      setTimeout(() => setSaveMsg(''), 2000);
    } catch (e: any) {
      setSaveMsg(`加载失败: ${e.message}`);
      setTimeout(() => setSaveMsg(''), 3000);
    }
  }, [builderMode, setFlowNodes, setFlowEdges]);

  const createHarnessDraft = useCallback(() => {
    if (builderMode !== 'build' || execState.running) return;
    const next = structuredClone(DEFAULT_CONFIG);
    setHistoricalReplay(null);
    setConfig(next);
    setFlowNodes([]);
    setFlowEdges([]);
    graphHistoryPast.current = [];
    graphHistoryFuture.current = [];
    setGraphHistoryTick((value) => value + 1);
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setSelectedTraceSequence(null);
    setExecState(IDLE_EXECUTION_STATE);
    setNodeTraces([]);
    setRuntimeRuns([]);
    setRuntimeStory([]);
    runtimeRunIds.current.clear();
    setChatMessages([]);
    builderExecutionRunId.current = undefined;
    activeExecutionRunId.current = undefined;
    setSaveMsg('已新建独立 Harness 草稿；保存时可修改名称');
  }, [builderMode, execState.running, setFlowEdges, setFlowNodes]);

  const enterLinkedSession = useCallback(async (runId: string) => {
    const target = String(runId || '').trim();
    if (!target) {
      setSaveMsg('请先选择一个 Session');
      return;
    }
    try {
      const state = await api.getExecutionState(target);
      if (!state?.harness) throw new Error('Session 没有记录 Harness');
      const versionIndex = await api.listHarnessVersions(state.harness);
      const versionApiSupported = versionIndex.supported !== false;
      if (state.harness_version && !versionApiSupported) {
        throw new Error(`Session 需要 Flow 版本 ${state.harness_version}，但当前运行的后端没有加载版本 API。请重启 EgoAgent 服务后重试。`);
      }
      const resolvedVersion = state.harness_version || versionIndex.latest;
      const cfg = state.harness_version ? await api.loadHarnessVersion(state.harness, state.harness_version) : await api.loadHarness(state.harness);
      cfg.prompts = cfg.prompts || {};
      cfg.slots = cfg.slots || {};
      cfg.return_mode = cfg.return_mode || 'all';
      cfg.pipeline = cfg.pipeline || { start: '', max_steps: 100, workspace_preview: false, nodes: {} };
      // Commit the UI mode only after both the exact run and its Harness have
      // loaded. A broken/stale Session must never freeze an unrelated graph and
      // make it look as though the link succeeded.
      setBuilderMode('linked');
      setLeaveLinkedDialogOpen(false);
      setLinkedRunId(target);
      activeExecutionRunId.current = target;
      runtimeRunIds.current = new Set([target]);
      setRuntimeRuns([]);
      setRuntimeStory([]);
      linkedHarnessRef.current = cfg.name;
      setConfig(cfg);
      setHarnessVersions(versionIndex.versions || []);
      setLatestHarnessVersion(versionIndex.latest || '');
      setSelectedHarnessVersion(resolvedVersion || String((cfg as any)._flow_version || ''));
      const graph = configToFlow(cfg);
      setFlowNodes(graph.nodes);
      setFlowEdges(graph.edges);
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
      setSelectedTraceSequence(null);
      setExecState({ ...IDLE_EXECUTION_STATE, ...state, node_traces: state.node_traces || [] });
      setNodeTraces(state.node_traces || []);
      setChatMessages(normalizeChatMessages(state.outputs));
      setShowOutput(true);
      setSaveMsg(versionApiSupported
        ? `只读链接: ${state.session_name || target.slice(-8)}`
        : `只读链接: ${state.session_name || target.slice(-8)} · 旧 Session 使用当前 Flow（重启后端可启用精确版本）`);
    } catch (error) {
      setSaveMsg(`无法链接 Session: ${error instanceof Error ? error.message : String(error)}`);
    }
  }, [setFlowEdges, setFlowNodes]);

  const leaveLinkedSession = useCallback(() => {
    setLeaveLinkedDialogOpen(false);
    setBuilderMode('build');
    setLinkedRunId('');
    linkedHarnessRef.current = '';
    builderExecutionRunId.current = undefined;
    activeExecutionRunId.current = undefined;
    runtimeRunIds.current.clear();
    setExecState(IDLE_EXECUTION_STATE);
    setNodeTraces([]);
    setRuntimeRuns([]);
    setRuntimeStory([]);
    setChatMessages([]);
    setSelectedTraceSequence(null);
    setFlowNodes((nodes) => nodes.map((node) => ({
      ...node,
      data: {
        ...node.data,
        highlight: false,
        runtimeStatus: undefined,
        runtimeCount: undefined,
        runtimeTrace: undefined,
        runtimeActivityMode: undefined,
        runtimePaused: undefined,
      },
    })));
    setSaveMsg(`已退出观察；${config.name} 可编辑。正在运行的 Session 继续使用启动时 Flow 快照，保存只影响后续运行`);
  }, [config.name, setFlowNodes]);

  const openTaskRunReplay = useCallback(async (runId: string) => {
    const target = String(runId || '').trim();
    if (!target) return;
    try {
      const recorded = await api.readFlowObservation(target);
      if (recorded.runs.length) {
        setObservationTarget(target);
        setTab('observe');
        return;
      }
      // Pre-observer history remains inspectable in the legacy snapshot view.
      const taskRun = await api.getTaskBenchRun(target);
      const harnessName = taskRun.selection?.harness;
      const version = taskRun.selection?.harness_version;
      if (!harnessName) throw new Error('Task run 没有记录 Flow');
      const [versionIndex, cfg] = await Promise.all([
        api.listHarnessVersions(harnessName),
        version ? api.loadHarnessVersion(harnessName, version) : api.loadHarness(harnessName),
      ]);
      cfg.prompts = cfg.prompts || {};
      cfg.slots = cfg.slots || {};
      cfg.return_mode = cfg.return_mode || 'all';
      cfg.pipeline = cfg.pipeline || { start: '', max_steps: 100, workspace_preview: false, nodes: {} };
      const graph = configToFlow(cfg);
      setTab('harness');
      setBuilderMode('locked');
      setHistoricalReplay({ runId: target, taskId: taskRun.task_id || 'task' });
      setLinkedRunId('');
      linkedHarnessRef.current = '';
      activeExecutionRunId.current = undefined;
      setConfig(cfg);
      setHarnessVersions(versionIndex.versions || []);
      setLatestHarnessVersion(versionIndex.latest || '');
      setSelectedHarnessVersion(version || versionIndex.latest || '');
      setFlowNodes(graph.nodes);
      setFlowEdges(graph.edges);
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
      setSelectedTraceSequence(null);
      setNodeTraces(taskRun.node_traces || []);
      setExecState({
        ...IDLE_EXECUTION_STATE,
        running: false,
        status: taskRun.status,
        current_node: taskRun.current_node,
        step_count: taskRun.step_count || 0,
        node_traces: taskRun.node_traces || [],
        harness: harnessName,
        harness_version: version,
      });
      setChatMessages(normalizeChatMessages(taskRun.outputs));
      setRuntimeStory((taskRun.events || []).flatMap((event: any) => {
        const item = storyEvent(event.type, event.data || {}, Number(event.time || 0) * 1000);
        return item ? [item] : [];
      }));
      setImproveChanges((taskRun.evolution_events || []).flatMap((event: any) => {
        if (event.type !== 'harness_mutation') return [];
        const mutation = normalizeMutationPayload(event.data || {});
        return [{
          timestamp: Number(event.time || 0) * 1000,
          type: 'harness' as const,
          target: mutation.target || harnessName,
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
      }));
      setShowOutput(true);
      setSaveMsg(`历史回放 · ${taskRun.task_id} · ${harnessName}@${version || 'legacy'}`);
    } catch (error) {
      setSaveMsg(`无法回放 Task run: ${error instanceof Error ? error.message : String(error)}`);
    }
  }, [setFlowEdges, setFlowNodes]);

  useEffect(() => {
    const handleWorkbenchCommand = (event: Event) => {
      const detail = (event as CustomEvent<Record<string, any>>).detail || {};
      if (detail.type === 'navigate' && STUDIO_TAB_IDS.has(detail.tab)) setTab(detail.tab);
      if (detail.type === 'replay-task-run' && detail.runId) void openTaskRunReplay(String(detail.runId));
    };
    window.addEventListener('egoagent:workbench', handleWorkbenchCommand);
    return () => window.removeEventListener('egoagent:workbench', handleWorkbenchCommand);
  }, [openTaskRunReplay]);

  const toggleBuilderLock = useCallback(() => {
    if (builderMode === 'linked') {
      setLeaveLinkedDialogOpen(true);
      return;
    }
    if (builderMode === 'locked' && historicalReplay) setHistoricalReplay(null);
    setBuilderMode((mode) => mode === 'build' ? 'locked' : 'build');
    setSaveMsg(builderMode === 'build' ? '已锁定编辑；仍可独立试跑和调试' : '已解锁编辑');
  }, [builderMode, historicalReplay]);

  useEffect(() => {
    if (builderMode !== 'linked' || !execState.harness || execState.harness === linkedHarnessRef.current) return;
    let cancelled = false;
    (execState.harness_version ? api.loadHarnessVersion(execState.harness, execState.harness_version) : api.loadHarness(execState.harness)).then((cfg) => {
      if (cancelled) return;
      cfg.prompts = cfg.prompts || {};
      cfg.slots = cfg.slots || {};
      cfg.return_mode = cfg.return_mode || 'all';
      cfg.pipeline = cfg.pipeline || { start: '', max_steps: 100, workspace_preview: false, nodes: {} };
      linkedHarnessRef.current = cfg.name;
      setConfig(cfg);
      const graph = configToFlow(cfg);
      setFlowNodes(graph.nodes);
      setFlowEdges(graph.edges);
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
    }).catch((error) => setSaveMsg(`Session 已切换 Harness，但加载失败: ${error.message}`));
    return () => { cancelled = true; };
  }, [builderMode, execState.harness, setFlowEdges, setFlowNodes]);

  const saveConfig = useCallback(async () => {
    try {
      const updated = flowToConfig(config, flowNodes, flowEdges);
      setConfig(updated);
      const saved = await api.saveHarness(updated.name, updated);
      const versions = await api.listHarnessVersions(updated.name);
      setHarnessVersions(versions.versions || []);
      setLatestHarnessVersion(versions.latest || String(saved.version || ''));
      setSelectedHarnessVersion(String(saved.version || versions.latest || ''));
      if (saved.version_created !== false) postToIde('harness-version-created', { harness: updated.name, version: saved.version });
      const details = await api.listHarnessDetails();
      setHarnessCatalog(details);
      setComponentList(details.filter((item) => Boolean(item.component)));
      setHarnessList((prev) => {
        if (!prev.includes(updated.name)) return [...prev, updated.name];
        return prev;
      });
      setSaveMsg(saved.version_created === false ? `内容未变化 · 仍为 ${saved.version}` : `已保存新版本: ${saved.version}`);
      setTimeout(() => setSaveMsg(''), 2000);
    } catch (e: any) {
      setSaveMsg(`保存失败: ${e.message}`);
      setTimeout(() => setSaveMsg(''), 3000);
    }
  }, [config, flowNodes, flowEdges]);

  const onConnect: OnConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      const sourceNode = flowNodesRef.current.find((node) => node.id === connection.source);
      const targetNode = flowNodesRef.current.find((node) => node.id === connection.target);
      const sourceData = sourceNode?.data as unknown as PipelineNode | undefined;
      const targetData = targetNode?.data as unknown as PipelineNode | undefined;
      const sourceSocket = parseSocketHandle(connection.sourceHandle);
      const targetSocket = parseSocketHandle(connection.targetHandle);
      const isControl = sourceSocket.socketClass === 'event' && targetSocket.socketClass === 'flow';
      const isData = sourceSocket.socketClass === 'output' && targetSocket.socketClass === 'input';
      if (!isControl && !isData) {
        setSaveMsg('无法连接：控制事件只能进入 flow；数据输出只能进入对应数据输入');
        return;
      }
      if (isData && connection.source === connection.target) {
        setSaveMsg('无法连接：节点的数据输出不能直接回接自身输入');
        return;
      }
      const condition: EdgeCondition = isControl ? sourceSocket.name : 'data';
      if (isData) {
        const sourceContract = sourceData ? contractFor(dagContracts, sourceData.op) : undefined;
        const targetContract = targetData ? contractFor(dagContracts, targetData.op) : undefined;
        const sourceType = socketType(sourceData, sourceContract, connection.sourceHandle);
        const targetType = socketType(targetData, targetContract, connection.targetHandle);
        if (!portTypesCompatible(sourceType, targetType)) {
          setSaveMsg(`端口类型不兼容：${sourceType} 不能连接到 ${targetType}`);
          return;
        }
      }
      recordGraphHistory();
      const newEdge: Edge = {
        ...connection,
        id: `${connection.source}->${connection.target}#${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
        type: 'conditionEdge',
        markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
        data: {
          condition,
          kind: isData ? 'data' : 'control',
          sourcePort: sourceSocket.name,
          targetPort: targetSocket.name,
          route: 'bezier',
          reroutes: [],
          channelOffset: 0,
          curvature: 0.72,
          labelOffset: 0,
          editable: true,
        },
      } as Edge;
      setFlowEdges((edges) => addEdge(newEdge, isData
        ? edges.filter((edge) => !(edge.target === connection.target && edge.targetHandle === connection.targetHandle))
        : edges));
      if (isData) {
        setFlowNodes((nodes) => nodes.map((node) => node.id === connection.target
          ? { ...node, data: { ...node.data, inputs: { ...((node.data as any).inputs || {}), [targetSocket.name]: `$node.${connection.source}.${sourceSocket.name}` } } }
          : node));
      }
    },
    [dagContracts, recordGraphHistory, setFlowEdges, setFlowNodes],
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

      recordGraphHistory();

      const position = rfInstance.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
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
      setConfig((current) => ({
        ...current,
        pipeline: {
          ...current.pipeline,
          start: current.pipeline.start || id,
        },
      }));
    },
    [dagContracts, recordGraphHistory, rfInstance, setFlowNodes],
  );

  const onNodeClick = useCallback((_event: any, node: Node) => {
    setExpandedNodeId((current) => current && current !== node.id ? null : current);
    if (_event.shiftKey) {
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
      return;
    }
    setSelectedNodeId(node.id);
    setSelectedEdgeId(null);
    const latest = [...nodeTraces].reverse().find((trace) => trace.node_id === node.id);
    setSelectedTraceSequence(latest?.sequence ?? null);
    if (latest) setShowOutput(true);
    if (builderMode === 'build' && !showBuilderInspector) {
      setShowBuilderInspector(true);
      window.setTimeout(() => rfInstance?.fitView?.({ padding: 0.18, duration: 180 }), 40);
    }
  }, [builderMode, nodeTraces, rfInstance, showBuilderInspector]);

  const onEdgeClick = useCallback((_event: any, edge: Edge) => {
    setExpandedNodeId(null);
    if (_event.shiftKey) {
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
      return;
    }
    setSelectedEdgeId(edge.id);
    setSelectedNodeId(null);
    if (builderMode === 'build' && !showBuilderInspector) {
      setShowBuilderInspector(true);
      window.setTimeout(() => rfInstance?.fitView?.({ padding: 0.18, duration: 180 }), 40);
    }
  }, [builderMode, rfInstance, showBuilderInspector]);

  const onPaneClick = useCallback(() => {
    setExpandedNodeId(null);
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
  }, []);

  const onSelectionChange = useCallback(({ nodes, edges }: { nodes: Node[]; edges: Edge[] }) => {
    const total = nodes.length + edges.length;
    if (total === 1 && nodes.length === 1) {
      setSelectedNodeId(nodes[0].id);
      setSelectedEdgeId(null);
    } else if (total === 1 && edges.length === 1) {
      setSelectedNodeId(null);
      setSelectedEdgeId(edges[0].id);
    } else {
      // A multi-selection is intentionally not represented by either single
      // inspector id. XYFlow's selected flags remain the source of truth.
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
    }
  }, []);

  const onNodeDoubleClick = useCallback((_event: any, node: Node) => {
    setSelectedNodeId(node.id);
    setSelectedEdgeId(null);
    setExpandedNodeId(node.id);
    if (builderMode === 'build' && !showBuilderInspector) {
      setShowBuilderInspector(true);
      window.setTimeout(() => rfInstance?.fitView?.({ padding: 0.18, duration: 180 }), 40);
    }
  }, [builderMode, rfInstance, showBuilderInspector]);

  const toggleBuilderPanel = useCallback((panel: 'palette' | 'inspector') => {
    if (builderMode !== 'build') return;
    if (panel === 'palette') setShowBuilderPalette((visible) => !visible);
    else setShowBuilderInspector((visible) => !visible);
    window.setTimeout(() => rfInstance?.fitView?.({ padding: 0.18, duration: 180 }), 40);
  }, [builderMode, rfInstance]);

  const arrangeFlow = useCallback(() => {
    recordGraphHistory();
    const result = autoLayoutFlow(flowNodesRef.current, flowEdgesRef.current, config.pipeline.start, autoLayoutOptions);
    setFlowNodes(result.nodes);
    setFlowEdges(result.edges);
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setExpandedNodeId(null);
    setAutoLayoutReport({ before: result.before, after: result.after });
    window.setTimeout(() => fitWholeGraph(rfInstance, reactFlowWrapper.current, result.nodes, result.edges, 280), 90);
    setSaveMsg(`已自动整理：穿节点 ${result.before.edgeNodeOverlaps}→${result.after.edgeNodeOverlaps}，交叉 ${result.before.edgeCrossings}→${result.after.edgeCrossings}，重叠线 ${result.before.edgeOverlaps}→${result.after.edgeOverlaps}`);
  }, [autoLayoutOptions, config.pipeline.start, recordGraphHistory, rfInstance, setFlowEdges, setFlowNodes]);

  const selectedNode = selectedNodeId
    ? (flowNodes.find((n) => n.id === selectedNodeId)?.data as unknown as PipelineNode) || null
    : null;

  const selectedNodeIds = useMemo(() => flowNodes.filter((node) => node.selected).map((node) => node.id), [flowNodes]);
  const selectedEdgeIds = useMemo(() => flowEdges.filter((edge) => edge.selected).map((edge) => edge.id), [flowEdges]);
  const selectedElementCount = selectedNodeIds.length + selectedEdgeIds.length;

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
          kind: String((e.data as any)?.kind || 'control') as 'control' | 'data',
          sourcePort: String((e.data as any)?.sourcePort || parseSocketHandle(e.sourceHandle).name),
          targetPort: String((e.data as any)?.targetPort || parseSocketHandle(e.targetHandle).name),
          route: String((e.data as any)?.route || 'bezier'),
          reroutes: Array.isArray((e.data as any)?.reroutes) ? (e.data as any).reroutes : [],
          channelOffset: Number((e.data as any)?.channelOffset || 0),
          curvature: Number((e.data as any)?.curvature ?? 0.62),
          labelOffset: Number((e.data as any)?.labelOffset || 0),
          source: e.source,
          target: e.target,
        };
      })()
    : null;

  const handleNodeUpdate = useCallback(
    (nodeId: string, updates: Partial<PipelineNode>) => {
      recordGraphHistory();
      setFlowNodes((nds) =>
        nds.map((n) =>
          n.id === nodeId ? { ...n, data: { ...n.data, ...updates } } : n
        )
      );
    },
    [recordGraphHistory, setFlowNodes],
  );

  const handleEdgeUpdate = useCallback(
    (edgeId: string, updates: { condition?: EdgeCondition; route?: string; reroutes?: BezierKnot[]; channelOffset?: number; curvature?: number; labelOffset?: number }) => {
      recordGraphHistory();
      setFlowEdges((eds) =>
        eds.map((e) =>
          e.id === edgeId ? {
            ...e,
            sourceHandle: updates.condition && String((e.data as any)?.kind || 'control') === 'control' ? `${EVENT_PREFIX}${updates.condition}` : e.sourceHandle,
            data: {
              ...e.data,
              ...updates,
              ...(updates.reroutes?.length === 0 ? { sourceHandle: undefined, targetHandle: undefined } : {}),
              ...(updates.condition ? { sourcePort: updates.condition } : {}),
            },
          } : e
        )
      );
    },
    [recordGraphHistory, setFlowEdges],
  );

  const handleDeleteNode = useCallback(
    (nodeId: string) => {
      recordGraphHistory();
      setFlowNodes((nds) => nds.filter((n) => n.id !== nodeId).map((node) => {
        const data = node.data as unknown as PipelineNode;
        const inputs = Object.fromEntries(Object.entries(data.inputs || {}).filter(([, value]) => (
          !(typeof value === 'string' && value.startsWith(`$node.${nodeId}.`))
        )));
        return Object.keys(inputs).length === Object.keys(data.inputs || {}).length ? node : { ...node, data: { ...node.data, inputs } };
      }));
      setFlowEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
      setSelectedNodeId(null);
    },
    [recordGraphHistory, setFlowNodes, setFlowEdges],
  );

  const handleDeleteEdge = useCallback(
    (edgeId: string) => {
      recordGraphHistory();
      const edge = flowEdgesRef.current.find((candidate) => candidate.id === edgeId);
      if (edge && String((edge.data as any)?.kind || 'control') === 'data') {
        const targetPort = parseSocketHandle(edge.targetHandle).name;
        setFlowNodes((nodes) => nodes.map((node) => {
          if (node.id !== edge.target) return node;
          const data = node.data as unknown as PipelineNode;
          const inputs = { ...(data.inputs || {}) };
          delete inputs[targetPort];
          return { ...node, data: { ...node.data, inputs } };
        }));
      }
      setFlowEdges((eds) => eds.filter((e) => e.id !== edgeId));
      setSelectedEdgeId(null);
    },
    [recordGraphHistory, setFlowEdges, setFlowNodes],
  );

  const handleDeleteSelection = useCallback(() => {
    const nodeIds = new Set(flowNodesRef.current.filter((node) => node.selected).map((node) => node.id));
    const edgeIds = new Set(flowEdgesRef.current.filter((edge) => edge.selected).map((edge) => edge.id));
    if (nodeIds.size === 0 && edgeIds.size === 0) return;

    recordGraphHistory();
    const removedDataPorts = new Map<string, Set<string>>();
    flowEdgesRef.current.forEach((edge) => {
      if (!edgeIds.has(edge.id) || nodeIds.has(edge.target) || String((edge.data as any)?.kind || 'control') !== 'data') return;
      const ports = removedDataPorts.get(edge.target) || new Set<string>();
      ports.add(parseSocketHandle(edge.targetHandle).name);
      removedDataPorts.set(edge.target, ports);
    });

    const survivingNodes = flowNodesRef.current
      .filter((node) => !nodeIds.has(node.id))
      .map((node) => {
        const data = node.data as unknown as PipelineNode;
        const removedPorts = removedDataPorts.get(node.id);
        const entries = Object.entries(data.inputs || {}).filter(([port, value]) => {
          if (removedPorts?.has(port)) return false;
          return !(typeof value === 'string' && [...nodeIds].some((nodeId) => value.startsWith(`$node.${nodeId}.`)));
        });
        const inputs = Object.fromEntries(entries);
        return entries.length === Object.keys(data.inputs || {}).length ? node : { ...node, data: { ...node.data, inputs } };
      });
    setFlowNodes(survivingNodes);
    setFlowEdges((edges) => edges.filter((edge) => !edgeIds.has(edge.id) && !nodeIds.has(edge.source) && !nodeIds.has(edge.target)));
    setConfig((current) => nodeIds.has(current.pipeline.start)
      ? { ...current, pipeline: { ...current.pipeline, start: survivingNodes[0]?.id || '' } }
      : current);
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setExpandedNodeId(null);
    setSaveMsg(`已删除 ${nodeIds.size} 个节点和 ${edgeIds.size} 条选中连接；相关连接已同步清理`);
  }, [recordGraphHistory, setFlowEdges, setFlowNodes]);

  const handleNodeDragStart = useCallback(() => {
    if (builderMode === 'build') recordGraphHistory();
  }, [builderMode, recordGraphHistory]);

  useEffect(() => {
    const handleGraphShortcut = (event: KeyboardEvent) => {
      if (builderMode !== 'build' || tab !== 'harness') return;
      const target = event.target as HTMLElement | null;
      const editingText = Boolean(target?.closest('input, textarea, select, [contenteditable="true"]'));
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
        if (editingText) return;
        event.preventDefault();
        if (event.shiftKey) redoGraph();
        else undoGraph();
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') {
        if (editingText) return;
        event.preventDefault();
        redoGraph();
        return;
      }
      if (editingText || (event.key !== 'Delete' && event.key !== 'Backspace')) return;
      const hasModelSelection = flowNodesRef.current.some((node) => node.selected) || flowEdgesRef.current.some((edge) => edge.selected);
      if (hasModelSelection) {
        event.preventDefault();
        handleDeleteSelection();
      } else if (selectedEdgeId) {
        event.preventDefault();
        handleDeleteEdge(selectedEdgeId);
      } else if (selectedNodeId) {
        event.preventDefault();
        handleDeleteNode(selectedNodeId);
      }
    };
    window.addEventListener('keydown', handleGraphShortcut);
    return () => window.removeEventListener('keydown', handleGraphShortcut);
  }, [builderMode, handleDeleteEdge, handleDeleteNode, handleDeleteSelection, redoGraph, selectedEdgeId, selectedNodeId, tab, undoGraph]);

  const canUndoGraph = graphHistoryTick >= 0 && graphHistoryPast.current.length > 0;
  const canRedoGraph = graphHistoryTick >= 0 && graphHistoryFuture.current.length > 0;

  const handleStartExec = useCallback(async () => {
    if (builderMode === 'linked') {
      setSaveMsg('该运行属于 Chat Session；请回到 Chat 控制它，或先退出关联');
      return;
    }
    if (executionStarting) return;
    setExecutionStarting(true);
    setSaveMsg('正在验证并启动独立 Harness…');
    try {
      const updated = flowToConfig(config, flowNodes, flowEdges);
      setConfig(updated);
      const savedForRun = await api.saveHarness(updated.name, updated);

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
        const message = `请先绑定 slot: ${missingSlots.join(', ')}（从右侧面板拖放 Identity）`;
        setSaveMsg(message);
        setShowOutput(true);
        chatMsgId.current += 1;
        setChatMessages((previous) => [...previous, { id: chatMsgId.current, agent: 'system', text: `无法启动：${message}`, tools: [], blocked: [] }]);
        return;
      }
      const started = await api.startExecution(updated.name, agents, startPaused ? 'paused' : 'auto', String(savedForRun.version || 'latest'));
      const runId = String(started.run_id || started.state?.run_id || '');
      builderExecutionRunId.current = runId || undefined;
      activeExecutionRunId.current = runId || undefined;
      runtimeRunIds.current = new Set(runId ? [runId] : []);
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
      setRuntimeRuns([]);
      setRuntimeStory([]);
      setSelectedTraceSequence(null);
      setFlowNodes((nodes) => nodes.map((node) => ({
        ...node,
        data: { ...node.data, highlight: false, runtimeStatus: undefined, runtimeCount: undefined },
      })));
      chatMsgId.current = 0;
      setImproveChanges([]);
      setSaveMsg(`独立试跑已启动 · Run ${runId.slice(-8)}`);
    } catch (e: any) {
      const message = `启动失败：${e.message}`;
      setSaveMsg(message);
      setShowOutput(true);
      chatMsgId.current += 1;
      setChatMessages((previous) => [...previous, { id: chatMsgId.current, agent: 'system', text: message, tools: [], blocked: [] }]);
      setExecState((previous) => ({ ...previous, running: false, status: 'error', termination: { kind: 'startup_error', message } }));
    } finally {
      setExecutionStarting(false);
    }
  }, [builderMode, config, executionStarting, flowNodes, flowEdges, startPaused, setFlowNodes]);

  const handleStopExec = useCallback(async () => {
    if (builderMode === 'linked') return;
    try {
      await api.stopExecution(builderExecutionRunId.current);
    } catch {}
  }, [builderMode]);

  const handleExecutionControl = useCallback(async (action: 'pause' | 'step' | 'auto') => {
    if (builderMode === 'linked') return;
    try {
      const state = await api.controlExecution(action, {}, builderExecutionRunId.current);
      setExecState((prev) => ({ ...prev, ...state, node_traces: state.node_traces || prev.node_traces }));
    } catch (error: any) {
      setSaveMsg(`调试控制失败: ${error.message}`);
    }
  }, [builderMode]);

  const handleDebugDirective = useCallback(async (action: 'skip' | 'override_inputs' | 'retry_with_inputs') => {
    if (builderMode === 'linked') return;
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
  }, [builderMode, debugInputOverride, debugSkipOutput, execState.paused, execState.pending_node]);

  const handleSendInput = useCallback(() => {
    if (builderMode === 'linked') return;
    if (!waitingNodeId) return; // 只有在等待输入节点时才允许发送
    const text = inputText.trim();
    if (!text) return;
    console.log("[App] handleSendInput called, text:", text);
    // 在聊天面板中显示用户消息气泡
    chatMsgId.current++;
    setChatMessages((prev) => [...prev, { id: chatMsgId.current, agent: 'user', text, tools: [], blocked: [] }]);
    api.sendInputViaWs(text, activeExecutionRunId.current);
    setInputText('');
  }, [builderMode, inputText, waitingNodeId]);

  const handleApproval = useCallback(async (decision: 'approved' | 'rejected') => {
    if (builderMode === 'linked') return;
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
  }, [builderMode, execState.pending_approval]);

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
      if (message.type === 'link-session' && message.runId) {
        setTab('harness');
        void enterLinkedSession(String(message.runId));
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
  }, [enterLinkedSession]);

  const initialLinkHandled = useRef(false);
  useEffect(() => {
    if (initialLinkHandled.current || !INITIAL_LINK_RUN_ID) return;
    initialLinkHandled.current = true;
    setTab('harness');
    void enterLinkedSession(INITIAL_LINK_RUN_ID);
  }, [enterLinkedSession]);

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
    if (builderMode !== 'build' || execState.running) return;
    const timer = window.setTimeout(persistBuilderDraft, 350);
    return () => window.clearTimeout(timer);
  }, [builderMode, execState.running, persistBuilderDraft]);

  useEffect(() => {
    const persistWhenHidden = () => {
      if (document.visibilityState === 'hidden' && builderMode === 'build' && !execState.running) persistBuilderDraft();
    };
    document.addEventListener('visibilitychange', persistWhenHidden);
    return () => document.removeEventListener('visibilitychange', persistWhenHidden);
  }, [builderMode, execState.running, persistBuilderDraft]);

  useEffect(() => {
    publishWorkbenchEvent('runtime-status', {
      scope: builderMode === 'linked' ? 'session-link' : 'builder',
      workspace: WORKSPACE,
      // A linked Session is being observed, not controlled by Workbench.  Do
      // not advertise it back to Chat as a second Workbench-owned run.
      running: builderMode !== 'linked' && execState.running,
      observing: builderMode === 'linked' && execState.running,
      waitingForInput: Boolean(execState.waiting_for_input || waitingNodeId),
      paused: execState.paused,
      currentNode: execState.pending_node || execState.current_node,
      harness: config.name,
      runId: execState.run_id,
    });
  }, [builderMode, config.name, execState.running, execState.waiting_for_input, execState.paused, execState.pending_node, execState.current_node, waitingNodeId, execState.run_id]);

  const harnessGroups = useMemo(() => {
    const details = new Map(harnessCatalog.map((item) => [item.name, item]));
    const labels: Record<string, string> = { system: '系统内置', example: 'Examples', experiment: 'Experiments', custom: 'Custom' };
    const order = ['system', 'example', 'experiment', 'custom'];
    const groups = new Map(order.map((category) => [category, [] as string[]]));
    harnessList.forEach((name) => {
      const category = details.get(name)?.catalog_category || 'custom';
      (groups.get(category) || groups.get('custom')!).push(name);
    });
    return order.map((category) => ({ category, label: labels[category], names: (groups.get(category) || []).sort() })).filter((group) => group.names.length);
  }, [harnessCatalog, harnessList]);

  return (
    <div className={`app-container ${EMBEDDED_IN_IDE ? 'embedded-workbench' : ''}`} data-workbench-tab={tab}>
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
        </nav> : <div className="studio-command-center">{activeTabMeta.detail}</div>}
        <label className="workbench-theme" title="Workbench 外观">
          <span aria-hidden="true">◐</span>
          <select aria-label="Workbench 主题" value={theme} onChange={(event) => setTheme(event.target.value as WorkbenchTheme)}>
            <option value="system">跟随 IDE</option>
            <option value="light">浅色</option>
            <option value="dark">深色</option>
          </select>
        </label>
        <button
          type="button"
          className={`studio-connection ${runtimeOnline === false ? 'offline' : runtimeOnline === null ? 'checking' : ''}`}
          title={runtimeOnline === false ? `点击重试连接 ${RUNTIME_LABEL}` : `运行位置：${RUNTIME_LABEL}`}
          onClick={() => void probeRuntime()}
        ><span />{runtimeOnline === false ? 'Runtime offline · 重试' : runtimeOnline === null ? 'Checking runtime' : RUNTIME_LABEL}</button>
      </header>

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
          {builderMode === 'build' && showBuilderPalette && <Sidebar components={componentList} contracts={dagContracts} />}
          <div className={`flow-area builder-${builderMode}`} ref={reactFlowWrapper}>
            <div className="builder-context-bar" role="region" aria-label="Build 锁定状态">
              {builderMode === 'linked' ? (
                <div className="builder-linked-identity" role="status">
                  <span>LINKED TO SESSION</span>
                  <b>{execState.session_title || execState.session_name || linkedRunId.slice(-8)}</b>
                  <small>{config.name} · Run {linkedRunId.slice(-8)}</small>
                </div>
              ) : historicalReplay ? (
                <div className="builder-replay-identity" role="status">
                  <span>HISTORICAL TASK REPLAY</span>
                  <b>{historicalReplay.taskId}</b>
                  <small>{config.name}@{selectedHarnessVersion || 'legacy'} · Run {historicalReplay.runId.slice(-8)}</small>
                </div>
              ) : (
                <label className="builder-harness-picker">
                  <span>{builderMode === 'build' ? '编辑 Harness' : '已锁定 Harness'}</span>
                  <select disabled={builderMode !== 'build'} value={config.name} onChange={(event) => void loadConfig(event.target.value)} aria-label="选择要编辑的 Harness">
                    {!harnessList.includes(config.name) && <option value={config.name}>{config.name}</option>}
                    {harnessGroups.map((group) => <optgroup key={group.category} label={group.label}>
                      {group.names.map((name) => <option key={name} value={name}>{name}</option>)}
                    </optgroup>)}
                  </select>
                  <select disabled={builderMode !== 'build'} value={selectedHarnessVersion} onChange={(event) => void loadConfig(config.name, event.target.value)} aria-label="选择 Harness 版本" title="选择不可变 Flow 版本；保存旧版本会生成新的 latest">
                    {harnessVersions.slice().reverse().map((version) => <option key={version.id} value={version.id}>{version.id === latestHarnessVersion ? '最新 · ' : ''}{version.label} · {version.id.slice(0, 15)}</option>)}
                  </select>
                  {builderMode === 'build' && <button type="button" className="builder-new-button" onClick={createHarnessDraft} disabled={execState.running} title="新建一个独立 Harness 草稿">＋ 新建</button>}
                </label>
              )}
              {builderMode === 'build' && <AutoLayoutPanel options={autoLayoutOptions} report={autoLayoutReport} onChange={setAutoLayoutOptions} onApply={arrangeFlow} />}
              {builderMode === 'build' && <div className="builder-history-controls" aria-label="Flow 编辑历史">
                <button type="button" onClick={undoGraph} disabled={!canUndoGraph} title="撤销上一次节点、连线或转接点编辑 (Ctrl+Z)">↶ 撤销</button>
                <button type="button" onClick={redoGraph} disabled={!canRedoGraph} title="重做 (Ctrl+Y / Ctrl+Shift+Z)">↷ 重做</button>
              </div>}
              <button type="button" className={`builder-arrange-button live-map-toggle ${showLiveArchitecture ? 'active' : ''}`} onClick={() => setShowLiveArchitecture((visible) => !visible)} title="显示真实父子 Run、SubFlow 和 Flow 版本变化">{showLiveArchitecture ? '隐藏实时结构' : '显示实时结构'}</button>
              {builderMode === 'build' && <div className="builder-panel-toggles" aria-label="Build 面板">
                <button type="button" className={showBuilderPalette ? 'active' : ''} aria-pressed={showBuilderPalette} onClick={() => toggleBuilderPanel('palette')} title="显示或隐藏组件库">组件</button>
                <button type="button" className={showBuilderInspector ? 'active' : ''} aria-pressed={showBuilderInspector} onClick={() => toggleBuilderPanel('inspector')} title="显示或隐藏配置检查器">配置</button>
              </div>}
              <button
                type="button"
                className={`builder-lock-button ${builderMode}`}
                onClick={toggleBuilderLock}
                aria-label={builderMode === 'build' ? '锁定 Build 编辑' : builderMode === 'linked' ? '退出 Session 关联' : historicalReplay ? '退出历史回放并编辑此版本' : '解锁 Build 编辑'}
                title={builderMode === 'linked' ? '退出 Session 关联并把当前 Flow 变成可编辑草稿' : historicalReplay ? '退出历史回放；当前不可变版本会成为可编辑草稿，保存将创建新版本' : builderMode === 'build' ? '锁定编辑，只保留运行与调试' : '解锁编辑'}
              >
                <i aria-hidden="true">{builderMode === 'build' ? '🔓' : '🔒'}</i>
                <span>{builderMode === 'linked' ? '退出观察' : historicalReplay ? '退出回放' : builderMode === 'locked' ? '已锁定' : '可编辑'}</span>
              </button>
              <div className={`builder-mode-badge ${builderMode}`}>
                {builderMode === 'linked' ? <><i>●</i><span><b>实时观察</b><small>输入与控制仍属于原 Chat</small></span></> : historicalReplay ? <><i>◷</i><span><b>历史回放</b><small>真实节点输入输出与当时 Flow 版本</small></span></> : <><i>{builderMode === 'locked' ? '■' : '✦'}</i><span><b>{builderMode === 'locked' ? '只运行' : '独立草稿'}</b><small>{builderExecutionRunId.current ? `独立 Run ${builderExecutionRunId.current.slice(-8)}` : '与 Chat Session 分离'}</small></span></>}
              </div>
            </div>
            {builderMode === 'linked' ? <FlowRunViewer rootId={linkedRunId} onAlbum={() => setTab('observe')} /> : <ReactFlowProvider>
              <GraphInteractionContext.Provider value={graphInteraction}>
              <ReactFlow
                nodes={flowNodes}
                edges={flowEdges}
                onNodesChange={builderMode === 'build' ? onNodesChange : (changes) => onNodesChange(changes.filter((change) => change.type === 'dimensions'))}
                onEdgesChange={builderMode === 'build' ? onEdgesChange : undefined}
                onConnect={builderMode === 'build' ? onConnect : undefined}
                onInit={setRfInstance}
                onDrop={builderMode === 'build' ? onDrop : undefined}
                onDragOver={builderMode === 'build' ? onDragOver : undefined}
                onNodeClick={onNodeClick}
                onNodeDoubleClick={onNodeDoubleClick}
                onNodeDragStart={handleNodeDragStart}
                onEdgeClick={onEdgeClick}
                onPaneClick={onPaneClick}
                onSelectionChange={onSelectionChange}
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                nodesDraggable={builderMode === 'build'}
                nodesConnectable={builderMode === 'build'}
                panOnDrag={true}
                selectionKeyCode={builderMode === 'build' ? 'Shift' : null}
                multiSelectionKeyCode={builderMode === 'build' ? 'Shift' : null}
                selectionOnDrag={false}
                selectionMode={SelectionMode.Partial}
                zoomOnScroll={true}
                zoomOnPinch={true}
                // Double-click belongs only to node expansion. Edge routing is
                // edited through explicit Blender-style reroute sockets.
                zoomOnDoubleClick={false}
                onlyRenderVisibleElements={flowNodes.length > 200}
                fitView
                connectionLineType={ConnectionLineType.Bezier}
                deleteKeyCode={[]}
              >
                <Background />
                <Controls showInteractive={false} />
                {showMinimap && <MiniMap
                  nodeColor={(n) => {
                    const op = (n.data as unknown as PipelineNode)?.op;
                    return contractFor(dagContracts, op)?.editor?.color || '#4a5568';
                  }}
                />}
              </ReactFlow>
              </GraphInteractionContext.Provider>
            </ReactFlowProvider>}
            {builderMode === 'build' && selectedElementCount > 1 && <div className="builder-selection-summary" role="status" aria-label="多选操作">
              <span><b>{selectedElementCount}</b> 个元素</span>
              <small>{selectedNodeIds.length} 节点 · {selectedEdgeIds.length} 连线</small>
              <button type="button" onClick={handleDeleteSelection}>删除所选</button>
            </div>}
            {showLiveArchitecture && builderMode !== 'linked' && <LiveAgentArchitecture
              root={{
                runId: String(activeExecutionRunId.current || execState.run_id || ''),
                harness: config.name,
                slots: execState.agents || Object.fromEntries(Object.entries(config.slots || {}).map(([slot, definition]: [string, any]) => [slot, definition.identity || slot])),
                status: execState.running ? 'running' : execState.status || 'idle',
                currentNode: execState.pending_node || execState.current_node,
                stepCount: execState.step_count || 0,
              }}
              runs={runtimeRuns}
              changes={improveChanges}
              events={runtimeStory}
              onOpenChanges={() => setTab('changes')}
            />}

            <div className="toolbar builder-execution-toolbar">
              {saveMsg && (
                <span role="status" style={{ fontSize: 11, color: /失败|无法|请先/.test(saveMsg) ? 'var(--danger)' : 'var(--success)', alignSelf: 'center', marginRight: 8 }}>
                  {saveMsg}
                </span>
              )}
              <button className={`btn btn-secondary ${showMinimap ? 'active' : ''}`} onClick={() => setShowMinimap((visible) => !visible)}>
                {showMinimap ? '隐藏概览' : '显示概览'}
              </button>
              {builderMode === 'build' && <button className="btn btn-secondary" onClick={saveConfig}>💾 保存</button>}
              {builderMode !== 'linked' && (!execState.running ? (
                <>
                  <label className="debug-start-option" title="在第一个节点产生任何副作用之前停住">
                    <input type="checkbox" checked={startPaused} onChange={(event) => setStartPaused(event.target.checked)} />
                    首节点暂停
                  </label>
                  <button className="btn btn-exec" onClick={handleStartExec} disabled={executionStarting}>
                    {executionStarting ? '启动中…' : '▶ 独立试跑'}
                  </button>
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
              ))}
              {builderMode === 'linked' && <span className="linked-control-note">运行控制在原 Chat Session 中</span>}
              <button
                className="btn btn-secondary"
                onClick={() => setShowOutput(!showOutput)}
                style={{ marginLeft: 8 }}
              >
                {showOutput ? '📋 隐藏输出' : '📋 显示输出'}
              </button>
            </div>

            {/* 微信风格聊天气泡输出面板 */}
            {showOutput && builderMode !== 'linked' && (
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
                    childRuns={runtimeRuns.filter((run) => run.runId !== activeExecutionRunId.current).map((run) => ({
                      harness_id: run.runId,
                      harness_name: run.harness,
                      slots: run.slots,
                      status: run.status === 'completed' ? 'completed' : 'running',
                      messages: [{ agent: 'runtime', text: run.lastActivity, tools: [] }],
                    }))}
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
                {<div className="chat-input-bar">
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
                </div>}
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

          {builderMode === 'build' && showBuilderInspector && <RightPanel
            config={config}
            selectedNode={selectedNode}
            selectedEdge={selectedEdge}
            onConfigChange={setConfig}
            onNodeUpdate={handleNodeUpdate}
            onEdgeUpdate={handleEdgeUpdate}
            onDeleteNode={handleDeleteNode}
            onDeleteEdge={handleDeleteEdge}
            onSave={saveConfig}
            harnessList={harnessList}
            componentList={componentList}
            identityList={identityList}
            dagContracts={dagContracts}
            onRefreshIdentities={refreshIdentities}
          />}
        </>
      )}

      {tab === 'observe' && <ObservationRoom initialRootId={observationTarget} />}
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

      {tab === 'flow' && (
        <div className="studio-page studio-page-scroll">
          <HeartFlowDemo onOpenSessions={() => setTab('sessions')} />
        </div>
      )}

      {tab === 'more' && (
        <div className="studio-page studio-page-scroll">
          <MoreWorkbench onNavigate={setTab} />
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
      {leaveLinkedDialogOpen && builderMode === 'linked' && (
        <div className="builder-unlink-backdrop" role="presentation" onMouseDown={() => setLeaveLinkedDialogOpen(false)}>
          <section
            className="builder-unlink-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="builder-unlink-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header>
              <span aria-hidden="true">🔓</span>
              <div>
                <b id="builder-unlink-title">退出观察模式并编辑这个 Flow？</b>
                <small>{execState.session_title || execState.session_name || `Session ${linkedRunId.slice(-8)}`}</small>
              </div>
            </header>
            <div className="builder-unlink-body">
              <p>退出后，Workbench 不再接收这个 Session 的节点、模型与工具输出，当前画布会保留为可编辑草稿。</p>
              <strong>正在运行的 Session 仍使用启动时的 Flow 快照；这里保存的修改只会用于后续运行，不会热替换当前执行。</strong>
            </div>
            <footer>
              <button type="button" onClick={() => setLeaveLinkedDialogOpen(false)}>继续观察</button>
              <button type="button" className="primary" onClick={leaveLinkedSession}>退出并编辑 Flow</button>
            </footer>
          </section>
        </div>
      )}
    </div>
  );
}
