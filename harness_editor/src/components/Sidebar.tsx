import { useMemo, useState, type DragEvent } from 'react';
import type { OpType } from '../types';
import type { HarnessCatalogItem } from '../api/client';
import type { DagContractCatalog } from './DagFormEditors';

interface NodeChoice { op: OpType; icon: string; cssClass: string; label: string; description: string }

type SidebarProps = {
  components?: HarnessCatalogItem[];
  contracts?: DagContractCatalog | null;
};

export default function Sidebar({ components = [], contracts }: SidebarProps) {
  const [query, setQuery] = useState('');
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({ 核心: true, 流程: true });
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
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const groups = ['核心', '流程', '数据', '高级']
    .map((title) => ({ title, nodes: grouped.get(title) || [] }))
    .map((group) => ({
      ...group,
      nodes: normalizedQuery
        ? group.nodes.filter((node) => `${node.label} ${node.description}`.toLocaleLowerCase().includes(normalizedQuery))
        : group.nodes,
    }))
    .filter((group) => group.nodes.length > 0);
  const visibleComponents = useMemo(() => components.filter((item) => {
    if (!normalizedQuery) return true;
    return `${item.name} ${item.description || ''} ${item.component?.display_name || ''} ${item.component?.description || ''} ${item.component?.category || ''}`
      .toLocaleLowerCase().includes(normalizedQuery);
  }), [components, normalizedQuery]);
  const toggleSection = (section: string, open: boolean) => {
    if (normalizedQuery) return;
    setOpenSections((current) => ({ ...current, [section]: open }));
  };
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
        <h2>Flow 组件</h2>
        <p>拖入画布组装 Harness；先用核心节点，按需展开高级能力。</p>
        <label className="palette-search">
          <span>⌕</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索节点或组件…" aria-label="搜索 Flow 组件" />
          {query && <button onClick={() => setQuery('')} aria-label="清除组件搜索">×</button>}
        </label>
      </div>

      {groups.map((group) => (
        <details className="sidebar-section palette-section" key={group.title}
          open={Boolean(normalizedQuery || openSections[group.title])}
          onToggle={(event) => toggleSection(group.title, event.currentTarget.open)}>
          <summary><span>{group.title}</span><small>{group.nodes.length}</small></summary>
          <div className="palette-section-body">{group.nodes.map((node) => (
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
            ))}</div>
        </details>
      ))}
      {groups.length === 0 && <div className="sidebar-section"><p>{normalizedQuery ? '没有匹配的节点。' : '正在加载节点定义…'}</p></div>}

      {visibleComponents.length > 0 && <details className="sidebar-section palette-section subdag-library"
        open={Boolean(normalizedQuery || openSections.components)}
        onToggle={(event) => toggleSection('components', event.currentTarget.open)}>
        <summary><span>复用组件</span><small>{visibleComponents.length}</small></summary>
        <p className="palette-help">已封装的 SubFlow；拖入后保留显式输入、输出与对话效果。</p>
        <div className="palette-section-body">{visibleComponents.map((item) => (
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
        ))}</div>
      </details>}

      {!normalizedQuery && <details className="sidebar-section palette-section"
        open={Boolean(openSections.edges)} onToggle={(event) => toggleSection('edges', event.currentTarget.open)}>
        <summary><span>连线条件</span><small>5</small></summary>
        <div className="palette-edge-help">
          <div><b>true / false</b> — 条件分支</div>
          <div><b>has_tool_calls</b> — Agent 请求工具</div>
          <div><b>error / timeout</b> — 失败处理</div>
          <div><b>expr: ...</b> — 安全表达式</div>
          <div><b>default</b> — 默认路径</div>
        </div>
      </details>}
    </div>
  );
}
