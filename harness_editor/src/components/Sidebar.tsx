import { type DragEvent } from 'react';
import type { OpType } from '../types';

const NODE_TYPES: { op: OpType; icon: string; cssClass: string; label: string }[] = [
  { op: '等待输入', icon: '⌨', cssClass: 'dnd-wait',  label: '等待输入' },
  { op: '推理',     icon: '🧠', cssClass: 'dnd-infer', label: '推理' },
  { op: '处理工具',  icon: '🔧', cssClass: 'dnd-tool',  label: '处理工具' },
  { op: '处理文字',  icon: '📝', cssClass: 'dnd-text',  label: '处理文字' },
  { op: '执行工具',  icon: '⚡', cssClass: 'dnd-exec',  label: '执行工具' },
];

export default function Sidebar() {
  const onDragStart = (event: DragEvent, op: OpType) => {
    event.dataTransfer.setData('application/egoagent-node', op);
    event.dataTransfer.effectAllowed = 'move';
  };

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h2>EgoAgent Harness</h2>
        <p>拖拽节点到画布，连线定义流程</p>
      </div>

      <div className="sidebar-section">
        <h3>节点类型</h3>
        {NODE_TYPES.map((nt) => (
          <div
            key={nt.op}
            className={`dnd-node ${nt.cssClass}`}
            draggable
            onDragStart={(e) => onDragStart(e, nt.op)}
          >
            <span className="icon">{nt.icon}</span>
            <span>{nt.label}</span>
          </div>
        ))}
      </div>

      <div className="sidebar-section">
        <h3>连线条件</h3>
        <div style={{ fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.8 }}>
          <div>🔵 <b>用户输入</b> — 等待输入后触发</div>
          <div>🟢 <b>有工具调用</b> — 推理产生 tool_calls</div>
          <div>🟡 <b>有文本</b> — 推理产生文本</div>
          <div>⚪ <b>→</b> — 默认（总是走这条）</div>
        </div>
      </div>

      <div className="sidebar-section">
        <h3>操作说明</h3>
        <div style={{ fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.8 }}>
          <div>🖱 拖拽节点到画布</div>
          <div>🔗 从节点底部拖到另一节点顶部连线</div>
          <div>🖱 点击节点/边查看配置</div>
          <div>🗑 选中后按 Delete 删除</div>
          <div>💾 Ctrl+S 保存</div>
        </div>
      </div>
    </div>
  );
}
