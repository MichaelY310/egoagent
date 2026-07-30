import { useState, useCallback, useRef, useEffect, type DragEvent } from 'react';
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
import IdentityManager from './components/IdentityManager';
import EnvironmentManager from './components/EnvironmentManager';
import SessionExplorer from './components/SessionExplorer';
import Settings from './components/Settings';
import ImproveTracker, { type ChangeEntry } from './components/ImproveTracker';
import EvolutionPanel from './components/EvolutionPanel';
import PipelineNodeComponent from './nodes/PipelineNode';
import ConditionEdge from './edges/ConditionEdge';
import * as api from './api/client';
import type { HarnessConfig, PipelineNode, EdgeCondition, OpType } from './types';

const nodeTypes = { pipelineNode: PipelineNodeComponent };
const edgeTypes = { conditionEdge: ConditionEdge };

const DEFAULT_CONFIG: HarnessConfig = {
  name: 'new_harness',
  description: '',
  slots: {},
  prompts: {},
  return_mode: 'all',
  pipeline: { start: '', max_steps: 100, workspace_preview: false, nodes: {} },
};

type TabType = 'harness' | 'identity' | 'environment' | 'sessions' | 'settings' | 'evolution';

type SubHarnessMessage = {
  agent: string;
  text: string;
  tools: Array<{ name: string; result: string }>;
};

type SubHarnessData = {
  harness_id: string;
  harness_name: string;
  slots: Record<string, string>;
  messages: SubHarnessMessage[];
  status: 'running' | 'completed';
};

type ChatMessage = {
  id: number;
  agent: string;
  text: string;
  tools: Array<{ name: string; result: string }>;
  blocked: Array<{ name: string; reason: string }>;
  sub_harness?: SubHarnessData;
};

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
      position: { x: 100 + col * 260, y: 80 + row * 160 },
      data: { ...pn },
    });
  });

  nodeEntries.forEach(([id, pn]) => {
    pn.edges.forEach((e) => {
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

function flowToConfig(config: HarnessConfig, flowNodes: Node[], flowEdges: Edge[]): HarnessConfig {
  const nodes: Record<string, PipelineNode> = {};

  flowNodes.forEach((n) => {
    const data = n.data as unknown as PipelineNode;
    nodes[n.id] = {
      id: n.id,
      op: data.op,
      agent: data.agent,
      prompt: data.prompt,
      edges: [],
    };
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
  const [tab, setTab] = useState<TabType>('harness');
  const [config, setConfig] = useState<HarnessConfig>(DEFAULT_CONFIG);
  const [flowNodes, setFlowNodes, onNodesChange] = useNodesState<Node>([]);
  const [flowEdges, setFlowEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [harnessList, setHarnessList] = useState<string[]>([]);
  const [identityList, setIdentityList] = useState<string[]>([]);
  const [execState, setExecState] = useState({ running: false, current_node: null as string | null, step_count: 0, messages_count: 0 });
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const chatMsgId = useRef(0);
  const [inputText, setInputText] = useState('');
  const [saveMsg, setSaveMsg] = useState('');
  const [showOutput, setShowOutput] = useState(false);
  const [waitingNodeId, setWaitingNodeId] = useState<string | null>(null);
  const [activeSubHarness, setActiveSubHarness] = useState<string | null>(null);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [rfInstance, setRfInstance] = useState<any>(null);
  const outputsRef = useRef<HTMLDivElement>(null);
  const flowNodesRef = useRef<Node[]>([]);
  flowNodesRef.current = flowNodes;
  const configRef = useRef(config);
  configRef.current = config;
  // ImproveTracker state
  const [improveChanges, setImproveChanges] = useState<ChangeEntry[]>([]);
  const [showImproveTracker, setShowImproveTracker] = useState(false);

  useEffect(() => {
    api.listHarnesses().then(setHarnessList).catch(() => {});
    api.listIdentities().then(setIdentityList).catch(() => {});
  }, []);

  useEffect(() => {
    const unsub = api.subscribeExecution((msg) => {
      if (msg.running !== undefined) {
        setExecState((prev) => {
          // 只在 running 从 false 变为 true 时清空消息（新一轮执行开始）
          if (msg.running && !prev.running) {
            setChatMessages([]);
            chatMsgId.current = 0;
          }
          return msg;
        });
        setFlowNodes((nds) =>
          nds.map((n) => ({
            ...n,
            data: { ...n.data, highlight: n.id === msg.current_node },
          }))
        );
        if (msg.running) {
          setShowOutput(true);
        }
        // 同步 waitingNodeId：根据 current_node 判断是否为等待输入节点
        if (msg.current_node && configRef.current.pipeline.nodes[msg.current_node]?.op === '等待输入') {
          setWaitingNodeId(msg.current_node);
        } else if (!msg.running) {
          setWaitingNodeId(null);
        }
      } else if (msg.type) {
        const type = msg.type as string;
        const data = msg.data || {};

        if (type === 'node_enter') {
          setExecState((prev) => ({ ...prev, current_node: data.node_id, step_count: prev.step_count + 1 }));
          setFlowNodes((nds) =>
            nds.map((n) => ({
              ...n,
              data: { ...n.data, highlight: n.id === data.node_id },
            }))
          );
          const nodeOp = configRef.current.pipeline.nodes[data.node_id]?.op;
          if (nodeOp === '等待输入') {
            setWaitingNodeId(data.node_id);
          } else {
            setWaitingNodeId(null);
          }
        } else if (type === 'token') {
          const agent = data.agent || 'unknown';
          setChatMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.agent === agent && last.tools.length === 0 && last.blocked.length === 0) {
              return [...prev.slice(0, -1), { ...last, text: last.text + data.text }];
            }
            chatMsgId.current++;
            return [...prev, { id: chatMsgId.current, agent, text: data.text, tools: [], blocked: [] }];
          });
        } else if (type === 'tool') {
          const agent = data.agent || 'system';
          setChatMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.agent === agent) {
              return [...prev.slice(0, -1), { ...last, tools: [...last.tools, { name: data.name, result: data.result }] }];
            }
            chatMsgId.current++;
            return [...prev, { id: chatMsgId.current, agent, text: '', tools: [{ name: data.name, result: data.result }], blocked: [] }];
          });
          // 自动刷新：如果 improver 修改了当前加载的 harness，重载 pipeline 可视化
          if (data.name === 'modify_harness' && data.result) {
            try {
              const res = JSON.parse(data.result);
              if (res.success) {
                // 推入 ImproveTracker
                setImproveChanges(prev => [...prev, {
                  timestamp: Date.now(),
                  type: "harness",
                  target: res.harness,
                  action: res.action,
                  field: res.target,
                  nodes: res.current_nodes,
                  pipelineStart: res.pipeline_start,
                  diff: res.diff,
                }]);
                setShowImproveTracker(true);
                // 如果修改的是当前加载的 harness，刷新 DAG
                if (res.harness === configRef.current.name) {
                  setTimeout(() => {
                    api.loadHarness(configRef.current.name).then((cfg) => {
                      cfg.prompts = cfg.prompts || {};
                      cfg.slots = cfg.slots || {};
                      cfg.pipeline = cfg.pipeline || { start: '', max_steps: 100, workspace_preview: false, nodes: {} };
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
                setShowImproveTracker(true);
              }
            } catch {}
          }
        } else if (type === 'blocked') {
          const agent = data.agent || 'system';
          setChatMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.agent === agent) {
              return [...prev.slice(0, -1), { ...last, blocked: [...last.blocked, { name: data.tool, reason: data.reason }] }];
            }
            chatMsgId.current++;
            return [...prev, { id: chatMsgId.current, agent, text: '', tools: [], blocked: [{ name: data.tool, reason: data.reason }] }];
          });
        } else if (type === 'error') {
          chatMsgId.current++;
          setChatMessages((prev) => [...prev, { id: chatMsgId.current, agent: 'system', text: `❌ ${data.message}`, tools: [], blocked: [] }]);
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
        } else if (type === 'sub_token') {
          const harnessId = data.harness_id || '';
          const agent = data.agent || 'unknown';
          const text = data.text || '';
          setChatMessages((prev) => {
            // 从后往前找到对应的 sub_harness 气泡
            for (let i = prev.length - 1; i >= 0; i--) {
              const sh = prev[i].sub_harness;
              if (sh && sh.harness_id === harnessId) {
                const msgs = [...sh.messages];
                const lastMsg = msgs[msgs.length - 1];
                if (lastMsg && lastMsg.agent === agent && (!lastMsg.tools || lastMsg.tools.length === 0)) {
                  msgs[msgs.length - 1] = { ...lastMsg, text: lastMsg.text + text };
                } else {
                  msgs.push({ agent, text, tools: [] });
                }
                const updated = [...prev];
                updated[i] = { ...updated[i], sub_harness: { ...sh, messages: msgs } };
                return updated;
              }
            }
            return prev;
          });
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

    return unsub;
  }, [setFlowNodes]);

  const lastOutputTick = useRef(0);
  const lastPolledNode = useRef<string | null>(null);

  // HTTP polling fallback: keep execState + agentOutputs in sync even when WebSocket is down
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const state = await api.getExecutionState();
        if (state) {
          setExecState((prev) => {
            if (prev.running === state.running && prev.step_count === state.step_count && prev.current_node === state.current_node) {
              return prev;
            }
            return state;
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
    }, 1000);
    return () => clearInterval(interval);
  }, [setFlowNodes]);

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
      const newNode: Node = {
        id,
        type: 'pipelineNode',
        position,
        data: { id, op, edges: [] } as unknown as Record<string, unknown>,
      };

      setFlowNodes((nds) => [...nds, newNode]);
    },
    [rfInstance, setFlowNodes],
  );

  const onNodeClick = useCallback((_event: any, node: Node) => {
    setSelectedNodeId(node.id);
    setSelectedEdgeId(null);
  }, []);

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
      await api.startExecution(updated.name, agents);
      setExecState((prev) => ({ ...prev, running: true, current_node: null, step_count: 0 }));
      setShowOutput(true);
      setChatMessages([]);
      chatMsgId.current = 0;
      setImproveChanges([]);
      setShowImproveTracker(false);
    } catch (e: any) {
      setSaveMsg(`启动失败: ${e.message}`);
      setTimeout(() => setSaveMsg(''), 3000);
    }
  }, [config, flowNodes, flowEdges]);

  const handleStopExec = useCallback(async () => {
    try {
      await api.stopExecution();
    } catch {}
  }, []);

  const handleSendInput = useCallback(() => {
    if (!waitingNodeId) return; // 只有在等待输入节点时才允许发送
    const text = inputText.trim();
    if (!text) return;
    console.log("[App] handleSendInput called, text:", text);
    // 在聊天面板中显示用户消息气泡
    chatMsgId.current++;
    setChatMessages((prev) => [...prev, { id: chatMsgId.current, agent: 'user', text, tools: [], blocked: [] }]);
    api.sendInputViaWs(text);
    setInputText('');
  }, [inputText, waitingNodeId]);

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

  return (
    <div className="app-container">
      {/* Tab 导航 */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, zIndex: 100,
        display: 'flex', gap: 0, background: '#0f0f1a', borderBottom: '1px solid #333',
        padding: '0 16px', height: 40, alignItems: 'center',
      }}>
        <span style={{ fontWeight: 'bold', color: '#7ecfff', marginRight: 24, fontSize: 14 }}>
          ⚙ EgoAgent Studio
        </span>
        {(['harness', 'identity', 'environment', 'sessions', 'evolution', 'settings'] as TabType[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              padding: '8px 20px',
              border: 'none',
              borderBottom: tab === t ? '2px solid #7ecfff' : '2px solid transparent',
              background: 'transparent',
              color: tab === t ? '#fff' : '#888',
              cursor: 'pointer',
              fontSize: 13,
              fontWeight: tab === t ? 'bold' : 'normal',
            }}
          >
            {t === 'harness' ? '🔗 Harness 编排' : t === 'identity' ? '🤖 Identity 管理' : t === 'environment' ? '🌍 Environment 管理' : t === 'sessions' ? '📊 Sessions' : t === 'evolution' ? '🧬 Evolution' : '⚙️ Settings'}
          </button>
        ))}
      </div>

      {/* Harness Tab */}
      {tab === 'harness' && (
        <>
          <Sidebar />
          <div className="flow-area" ref={reactFlowWrapper} style={{ top: 40 }}>
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
                fitView
                deleteKeyCode={['Backspace', 'Delete']}
              >
                <Background />
                <Controls />
                <MiniMap
                  nodeColor={(n) => {
                    const op = (n.data as unknown as PipelineNode)?.op;
                    const colors: Record<string, string> = {
                      '等待输入': '#3b82f6',
                      '推理': '#22c55e',
                      '处理工具': '#f59e0b',
                      '处理文字': '#a855f7',
                      '执行工具': '#ec4899',
                    };
                    return colors[op] || '#4a5568';
                  }}
                />
              </ReactFlow>
            </ReactFlowProvider>

            <div className="toolbar">
              {saveMsg && (
                <span style={{ fontSize: 12, color: 'var(--success)', alignSelf: 'center', marginRight: 8 }}>
                  {saveMsg}
                </span>
              )}
              <button className="btn btn-secondary" onClick={saveConfig}>💾 保存</button>
              {!execState.running ? (
                <button className="btn btn-exec" onClick={handleStartExec}>▶ 执行</button>
              ) : (
                <button className="btn btn-exec running" onClick={handleStopExec}>⏹ 停止</button>
              )}
              {showOutput && (
                <button
                  className="btn btn-secondary"
                  onClick={() => setShowOutput(!showOutput)}
                  style={{ marginLeft: 8 }}
                >
                  {showOutput ? '📋 隐藏输出' : '📋 显示输出'}
                </button>
              )}
            </div>

            {/* 微信风格聊天气泡输出面板 */}
            {showOutput && (
              <div className="chat-output-panel">
                <div ref={outputsRef} className="chat-message-list" onScroll={(e) => {
                  const el = e.currentTarget;
                  userScrolledUp.current = el.scrollHeight - el.scrollTop - el.clientHeight > 60;
                }}>
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
                <div className="chat-input-bar">
                  {waitingNodeId && <span className="chat-waiting-badge">⏳ {waitingNodeId}</span>}
                  <input type="text" value={inputText}
                    onChange={(e) => { setInputText(e.target.value); }}
                    onKeyDown={handleInputKeyDown}
                    placeholder={!execState.running ? '点击 ▶ 执行 启动' : (waitingNodeId ? `输入消息发送到 ${waitingNodeId}，回车发送...` : 'Agent 正在思考中...')}
                    disabled={!waitingNodeId}
                    className="chat-input-field"
                    style={{ boxShadow: waitingNodeId ? '0 0 6px rgba(59,130,246,0.3)' : 'none' }}
                  />
                  <button onClick={handleSendInput} disabled={!waitingNodeId}
                    className="chat-send-btn"
                    style={{ background: waitingNodeId ? '#7ecfff' : '#333' }}
                  >发送</button>
                </div>
                <div className="chat-status-bar">
                  <span><span className={`status-dot ${execState.running ? 'running' : 'idle'}`} />{execState.running ? `运行中 (step ${execState.step_count})` : '就绪'}</span>
                  <span>节点: {flowNodes.length}</span>
                  <span>连线: {flowEdges.length}</span>
                  {execState.current_node && <span>当前节点: <b>{execState.current_node}</b></span>}
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
            identityList={identityList}
            onRefreshIdentities={refreshIdentities}
          />
          {/* ImproveTracker: 实时变更追踪面板 */}
          {showImproveTracker && (
            <ImproveTracker
              changes={improveChanges}
              onClose={() => setShowImproveTracker(false)}
            />
          )}
        </>
      )}

      {/* Identity Tab */}
      {tab === 'identity' && (
        <div style={{ position: 'absolute', top: 40, left: 0, right: 0, bottom: 0 }}>
          <IdentityManager />
        </div>
      )}

      {/* Environment Tab */}
      {tab === 'environment' && (
        <div style={{ position: 'absolute', top: 40, left: 0, right: 0, bottom: 0 }}>
          <EnvironmentManager />
        </div>
      )}

      {/* Sessions Tab */}
      {tab === 'sessions' && (
        <div style={{ position: 'absolute', top: 40, left: 0, right: 0, bottom: 0 }}>
          <SessionExplorer />
        </div>
      )}

      {/* Settings Tab */}
      {tab === 'settings' && (
        <div style={{ position: 'absolute', top: 40, left: 0, right: 0, bottom: 0, overflow: 'auto' }}>
          <Settings />
        </div>
      )}
      {/* Evolution Tab */}
      {tab === 'evolution' && (
        <div style={{ position: 'absolute', top: 40, left: 0, right: 0, bottom: 0, overflow: 'auto' }}>
          <EvolutionPanel />
        </div>
      )}
    </div>
  );
}
