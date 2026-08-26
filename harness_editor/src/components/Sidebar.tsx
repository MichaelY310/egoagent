import { type DragEvent } from 'react';
import type { OpType } from '../types';
import type { HarnessCatalogItem } from '../api/client';
import type { DagContractCatalog } from './DagFormEditors';

interface NodeChoice { op: OpType; icon: string; cssClass: string; label: string; description: string }

type SidebarProps = {
  components?: HarnessCatalogItem[];
  contracts?: DagContractCatalog | null;
};

export default function Sidebar({ components = [], contracts }: SidebarProps) {
  const grouped = new Map<string, NodeChoice[]>();
  Object.entries(contracts?.nodes || {}).forEach(([op, contract]) => {
    if (contract.editor?.palette === false) return;
    const category = contract.editor?.category || '高级';
    const nodes = grouped.get(category) || [];
    nodes.push({
      op: op as OpType,
      icon: contract.editor?.icon || '◇',
      cssClass: contract.editor?.css_class || 'dnd-tool',
      label: op,
      description: contract.description || op,
    });
    grouped.set(category, nodes);
  });
  const groups = ['核心', '流程', '数据', '高级']
    .map((title) => ({ title, nodes: grouped.get(title) || [] }))
    .filter((group) => group.nodes.length > 0);
  const onDragStart = (event: DragEvent, op: OpType) => {
    event.dataTransfer.setData('application/egoagent-node', op);
    event.dataTransfer.effectAllowed = 'move';
  };

  const onComponentDragStart = (event: DragEvent, item: HarnessCatalogItem) => {
    event.dataTransfer.setData('application/egoagent-node', '子流程');
    event.dataTransfer.setData('application/egoagent-subdag', JSON.stringify(item));
    event.dataTransfer.effectAllowed = 'move';
  };

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h2>EgoAgent DAG</h2>
        <p>Identity 与 EGO 决定行为，DAG 决定协作流程</p>
      </div>

      {groups.map((group) => (
        <div className="sidebar-section" key={group.title}>
          <h3>{group.title}</h3>
          {group.nodes.map((node) => (
            <div
              key={node.op}
              className={`dnd-node ${node.cssClass}`}
              draggable
              onDragStart={(event) => onDragStart(event, node.op)}
              title={node.description}
            >
              <span className="icon">{node.icon}</span>
              <span>{node.label}</span>
            </div>
          ))}
        </div>
      ))}
      {groups.length === 0 && <div className="sidebar-section"><p>正在加载节点定义…</p></div>}

      {components.length > 0 && <div className="sidebar-section subdag-library">
        <h3>SubDAG 组件</h3>
        <div style={{ fontSize: 10, color: 'var(--text-dim)', marginBottom: 7 }}>
          拖入后保留显式输入、输出与对话效果
        </div>
        {components.map((item) => (
          <div
            key={item.name}
            className="dnd-node dnd-llm subdag-card"
            draggable
            onDragStart={(event) => onComponentDragStart(event, item)}
            title={item.component?.description || item.description}
          >
            <span className="icon">{item.component?.icon || '◫'}</span>
            <span>
              {item.component?.display_name || item.name}
              <small style={{ display: 'block', opacity: .68 }}>{item.component?.category || 'component'}</small>
            </span>
          </div>
        ))}
      </div>}

      <div className="sidebar-section">
        <h3>连线</h3>
        <div style={{ fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.8 }}>
          <div><b>true / false</b> — 条件分支</div>
          <div><b>has_tool_calls</b> — Agent 请求工具</div>
          <div><b>error / timeout</b> — 失败处理</div>
          <div><b>expr: ...</b> — 安全表达式</div>
          <div><b>default</b> — 默认路径</div>
        </div>
      </div>
    </div>
  );
}
