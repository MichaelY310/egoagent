import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { PipelineNode } from '../types';

const OP_CONFIG: Record<string, { icon: string; cssClass: string; label: string }> = {
  '等待输入': { icon: '⌨', cssClass: 'node-wait-input', label: '等待输入' },
  '推理':     { icon: '🧠', cssClass: 'node-infer', label: '推理' },
  '处理工具':  { icon: '🔧', cssClass: 'node-process-tool', label: '处理工具' },
  '处理文字':  { icon: '📝', cssClass: 'node-process-text', label: '处理文字' },
  '执行工具':  { icon: '⚡', cssClass: 'node-exec-tool', label: '执行工具' },
  '脚本':     { icon: '📜', cssClass: 'node-script', label: '脚本' },
  'llm_call': { icon: '💬', cssClass: 'node-llm-call', label: 'LLM Call' },
};

function PipelineNodeComponent({ data, selected }: NodeProps) {
  const nodeData = data as unknown as PipelineNode;
  const cfg = OP_CONFIG[nodeData.op] || OP_CONFIG['推理'];
  const highlight = (data as any).highlight ? ' highlight' : '';
  const subHarness = (data as any).subHarness as string | undefined;

  return (
    <div className={`pipeline-node ${cfg.cssClass}${highlight}${subHarness ? ' sub-harness-active' : ''}`}>
      <Handle type="target" position={Position.Top} />
      <div className="node-header">
        <span className="node-icon">{cfg.icon}</span>
        <span className="node-title">{cfg.label}</span>
      </div>
      {nodeData.agent && <div className="node-agent">@{nodeData.agent}</div>}
      {nodeData.prompt && <div className="node-prompt">prompt: {nodeData.prompt}</div>}
      {nodeData.script && <div className="node-script-badge">🗂 {nodeData.script}.py</div>}
      {nodeData.op === 'llm_call' && nodeData.prompt && (
        <div className="node-prompt">template: {nodeData.prompt}</div>
      )}
      {subHarness && (
        <div className="node-sub-harness-badge">
          ⚡ 子Session: {subHarness}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

export default memo(PipelineNodeComponent);
