export type OpType = '等待输入' | '推理' | '处理工具' | '处理文字' | '执行工具' | '脚本' | 'llm_call';
export type EdgeCondition = 'input' | 'has_tool_calls' | 'no_tool_calls' | 'has_text' | 'default';

export interface PipelineNode {
  id: string;
  op: OpType;
  agent?: string;
  prompt?: string;
  edges: { condition: EdgeCondition; to: string }[];
  // 脚本节点专用
  script?: string;          // 脚本文件名（不含 .py）
  input_vars?: string[];
  output_vars?: string[];
  // llm_call 节点专用
  output_var?: string;
  parse_as?: 'text' | 'json';
}

export interface SlotDef {
  description: string;
  required: boolean;
  identity?: string;
}

export interface PromptDef {
  description: string;
  default: string;
}

export interface HarnessConfig {
  name: string;
  description: string;
  slots: Record<string, SlotDef>;
  prompts: Record<string, PromptDef>;
  return_mode: 'all' | 'last';
  pipeline: {
    start: string;
    max_steps: number;
    workspace_preview: boolean;
    nodes: Record<string, PipelineNode>;
  };
}

export interface ExecutionState {
  running: boolean;
  current_node: string | null;
  step_count: number;
  messages_count: number;
}
