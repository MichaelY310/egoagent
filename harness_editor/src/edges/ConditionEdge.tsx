import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type EdgeProps } from '@xyflow/react';

const CONDITION_LABELS: Record<string, string> = {
  input: '用户输入',
  has_tool_calls: '有工具调用',
  no_tool_calls: '无工具调用',
  has_text: '有文本',
  default: '→',
};

export default function ConditionEdge({
  id,
  sourceX, sourceY,
  targetX, targetY,
  sourcePosition, targetPosition,
  data,
  selected,
}: EdgeProps) {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX, sourceY,
    sourcePosition,
    targetX, targetY,
    targetPosition,
  });

  const condition = (data as any)?.condition || 'default';
  const label = CONDITION_LABELS[condition] || condition;

  return (
    <>
      <BaseEdge id={id} path={edgePath} style={{ stroke: selected ? '#0ea5e9' : '#4a5568', strokeWidth: 2 }} />
      <EdgeLabelRenderer>
        <div
          className="condition-edge-label"
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: 'all',
          }}
        >
          {label}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}
