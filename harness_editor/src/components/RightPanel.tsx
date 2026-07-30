import { useState, useEffect, type DragEvent } from 'react';
import type { HarnessConfig, PipelineNode, SlotDef, PromptDef, EdgeCondition } from '../types';

interface Props {
  config: HarnessConfig;
  selectedNode: PipelineNode | null;
  selectedEdge: { id: string; condition: EdgeCondition; source: string; target: string } | null;
  onConfigChange: (config: HarnessConfig) => void;
  onNodeUpdate: (nodeId: string, updates: Partial<PipelineNode>) => void;
  onEdgeUpdate: (edgeId: string, condition: EdgeCondition) => void;
  onDeleteNode: (nodeId: string) => void;
  onDeleteEdge: (edgeId: string) => void;
  onSave: () => void;
  onLoad: (name: string) => void;
  harnessList: string[];
  identityList: string[];
  onRefreshIdentities: () => void;
}

export default function RightPanel({
  config, selectedNode, selectedEdge,
  onConfigChange, onNodeUpdate, onEdgeUpdate,
  onDeleteNode, onDeleteEdge,
  onSave, onLoad, harnessList, identityList,
  onRefreshIdentities,
}: Props) {
  const [newSlotName, setNewSlotName] = useState('');
  const [newSlotDesc, setNewSlotDesc] = useState('');
  const [newPromptName, setNewPromptName] = useState('');
  const [newPromptDefault, setNewPromptDefault] = useState('');
  const [loadName, setLoadName] = useState('');

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        onSave();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onSave]);

  const handleSlotDrop = (slotName: string, e: DragEvent) => {
    e.preventDefault();
    const identityName = e.dataTransfer.getData('application/egoagent-identity');
    if (!identityName) return;
    onConfigChange({
      ...config,
      slots: {
        ...config.slots,
        [slotName]: {
          ...config.slots[slotName],
          identity: identityName,
        },
      },
    });
  };

  const handleSlotDragOver = (e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'link';
  };

  // ---- Node Editor ----
  if (selectedNode) {
    return (
      <div className="right-panel">
        <div className="panel-section">
          <h3>节点配置: {selectedNode.id}</h3>
          <label>操作类型</label>
          <select
            value={selectedNode.op}
            onChange={(e) => onNodeUpdate(selectedNode.id, { op: e.target.value as PipelineNode['op'] })}
          >
            <option value="等待输入">等待输入</option>
            <option value="推理">推理</option>
            <option value="处理工具">处理工具</option>
            <option value="处理文字">处理文字</option>
            <option value="执行工具">执行工具</option>
          </select>

          {(selectedNode.op === '推理' || selectedNode.op === '处理工具' || selectedNode.op === '处理文字' || selectedNode.op === '执行工具') && (
            <>
              <label>Agent (slot 名)</label>
              <select
                value={selectedNode.agent || ''}
                onChange={(e) => onNodeUpdate(selectedNode.id, { agent: e.target.value || undefined })}
              >
                <option value="">-- 选择 slot --</option>
                {Object.keys(config.slots).map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </>
          )}

          {(selectedNode.op === '处理工具' || selectedNode.op === '处理文字') && (
            <>
              <label>Prompt 模板</label>
              <select
                value={selectedNode.prompt || ''}
                onChange={(e) => onNodeUpdate(selectedNode.id, { prompt: e.target.value || undefined })}
              >
                <option value="">-- 无 --</option>
                {Object.keys(config.prompts).map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </>
          )}

          <div className="btn-row">
            <button className="btn btn-danger btn-sm" onClick={() => onDeleteNode(selectedNode.id)}>
              删除节点
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ---- Edge Editor ----
  if (selectedEdge) {
    return (
      <div className="right-panel">
        <div className="panel-section">
          <h3>连线配置</h3>
          <p style={{ fontSize: 12, color: 'var(--text-dim)', marginBottom: 10 }}>
            {selectedEdge.source} → {selectedEdge.target}
          </p>
          <label>条件</label>
          <select
            value={selectedEdge.condition}
            onChange={(e) => onEdgeUpdate(selectedEdge.id, e.target.value as EdgeCondition)}
          >
            <option value="input">用户输入</option>
            <option value="has_tool_calls">有工具调用</option>
            <option value="no_tool_calls">无工具调用</option>
            <option value="has_text">有文本</option>
            <option value="default">默认</option>
          </select>
          <div className="btn-row">
            <button className="btn btn-danger btn-sm" onClick={() => onDeleteEdge(selectedEdge.id)}>
              删除连线
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ---- Global Config ----
  return (
    <div className="right-panel">
      <div className="panel-section">
        <h3>Harness 配置</h3>

        <label>名称</label>
        <input
          value={config.name}
          onChange={(e) => onConfigChange({ ...config, name: e.target.value })}
        />

        <label>描述</label>
        <input
          value={config.description}
          onChange={(e) => onConfigChange({ ...config, description: e.target.value })}
        />

        <label>返回模式</label>
        <select
          value={config.return_mode}
          onChange={(e) => onConfigChange({ ...config, return_mode: e.target.value as 'all' | 'last' })}
        >
          <option value="all">all (全部消息)</option>
          <option value="last">last (最后一条)</option>
        </select>

        <label>最大步数</label>
        <input
          type="number"
          value={config.pipeline.max_steps}
          onChange={(e) => onConfigChange({
            ...config,
            pipeline: { ...config.pipeline, max_steps: parseInt(e.target.value) || 100 }
          })}
        />

        <label>
          <input
            type="checkbox"
            checked={config.pipeline.workspace_preview}
            onChange={(e) => onConfigChange({
              ...config,
              pipeline: { ...config.pipeline, workspace_preview: e.target.checked }
            })}
            style={{ width: 'auto', marginRight: 6 }}
          />
          注入 workspace 预览
        </label>

        <label>起始节点</label>
        <select
          value={config.pipeline.start}
          onChange={(e) => onConfigChange({
            ...config,
            pipeline: { ...config.pipeline, start: e.target.value }
          })}
        >
          {Object.keys(config.pipeline.nodes).map((nid) => (
            <option key={nid} value={nid}>{nid}</option>
          ))}
        </select>

        <div className="btn-row">
          <button className="btn btn-primary" onClick={onSave}>💾 保存 (Ctrl+S)</button>
        </div>
      </div>

      {/* Slots */}
      <div className="panel-section">
        <h3>Slots</h3>
        {Object.entries(config.slots).map(([name, def]) => (
          <div
            key={name}
            className="slot-item"
            onDrop={(e) => handleSlotDrop(name, e)}
            onDragOver={handleSlotDragOver}
            style={{ cursor: 'copy' }}
            title="拖放 identity 到此绑定"
          >
            <div>
              <span className="slot-name">{name}</span>
              <span className="slot-desc"> — {def.description}</span>
            </div>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
              {(def as SlotDef & { identity?: string }).identity && (
                <span style={{ fontSize: 10, color: '#7ecfff', background: '#1a2a3a', padding: '1px 6px', borderRadius: 3 }}>
                  🎭 {(def as SlotDef & { identity?: string }).identity}
                </span>
              )}
              {def.required && <span className="slot-required">必填</span>}
              <button
                className="btn btn-danger btn-sm"
                onClick={() => {
                  const slots = { ...config.slots };
                  delete slots[name];
                  onConfigChange({ ...config, slots });
                }}
              >×</button>
            </div>
          </div>
        ))}
        <div className="add-row">
          <input placeholder="slot 名" value={newSlotName} onChange={(e) => setNewSlotName(e.target.value)} />
          <input placeholder="描述" value={newSlotDesc} onChange={(e) => setNewSlotDesc(e.target.value)} />
          <button className="btn btn-secondary btn-sm" onClick={() => {
            if (!newSlotName.trim()) return;
            onConfigChange({
              ...config,
              slots: { ...config.slots, [newSlotName.trim()]: { description: newSlotDesc.trim(), required: false } }
            });
            setNewSlotName('');
            setNewSlotDesc('');
          }}>+</button>
        </div>
      </div>

      {/* Identity 拖放区 */}
      <div className="panel-section">
        <h3>🎭 Identity 绑定</h3>
        <p style={{ fontSize: 11, color: '#888', marginBottom: 8 }}>
          从 Identity 管理页拖放 identity 到上方 slot 即可绑定
        </p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {identityList.map((id) => (
            <span
              key={id}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData('application/egoagent-identity', id);
                e.dataTransfer.effectAllowed = 'link';
              }}
              style={{
                padding: '3px 8px',
                background: '#1a2a3a',
                borderRadius: 4,
                fontSize: 11,
                color: '#7ecfff',
                cursor: 'grab',
                border: '1px solid #333',
              }}
              title={`拖放到 slot 绑定 ${id}`}
            >
              🎭 {id}
            </span>
          ))}
          <button
            className="btn btn-secondary btn-sm"
            onClick={onRefreshIdentities}
            style={{ fontSize: 11 }}
          >
            🔄 刷新
          </button>
        </div>
      </div>

      {/* Prompts */}
      <div className="panel-section">
        <h3>Prompts</h3>
        {Object.entries(config.prompts).map(([name, def]) => (
          <div key={name} className="slot-item" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="slot-name">{name}</span>
              <button
                className="btn btn-danger btn-sm"
                onClick={() => {
                  const prompts = { ...config.prompts };
                  delete prompts[name];
                  onConfigChange({ ...config, prompts });
                }}
              >×</button>
            </div>
            <span className="slot-desc">{def.description}</span>
            <textarea
              style={{ marginTop: 4, fontSize: 11 }}
              rows={3}
              value={def.default}
              onChange={(e) => onConfigChange({
                ...config,
                prompts: { ...config.prompts, [name]: { ...def, default: e.target.value } }
              })}
            />
          </div>
        ))}
        <div className="add-row" style={{ flexDirection: 'column', gap: 4 }}>
          <input placeholder="prompt 名" value={newPromptName} onChange={(e) => setNewPromptName(e.target.value)} />
          <textarea
            placeholder="默认值"
            rows={2}
            value={newPromptDefault}
            onChange={(e) => setNewPromptDefault(e.target.value)}
          />
          <button className="btn btn-secondary btn-sm" onClick={() => {
            if (!newPromptName.trim()) return;
            onConfigChange({
              ...config,
              prompts: {
                ...config.prompts,
                [newPromptName.trim()]: { description: '', default: newPromptDefault }
              }
            });
            setNewPromptName('');
            setNewPromptDefault('');
          }}>+</button>
        </div>
      </div>

      {/* Load / New */}
      <div className="panel-section">
        <h3>加载 / 新建</h3>
        <select value={loadName} onChange={(e) => setLoadName(e.target.value)} style={{ marginBottom: 8 }}>
          <option value="">-- 选择 harness --</option>
          {harnessList.map((h) => (
            <option key={h} value={h}>{h}</option>
          ))}
        </select>
        <div className="btn-row">
          <button className="btn btn-secondary btn-sm" onClick={() => {
            if (loadName) onLoad(loadName);
          }}>加载</button>
          <button className="btn btn-secondary btn-sm" onClick={() => {
            onConfigChange({
              name: 'new_harness',
              description: '',
              slots: {},
              prompts: {},
              return_mode: 'all',
              pipeline: { start: '', max_steps: 100, workspace_preview: false, nodes: {} }
            });
          }}>新建</button>
        </div>
      </div>
    </div>
  );
}
