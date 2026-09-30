import { useState, useEffect, useMemo, type DragEvent } from 'react';
import type { HarnessConfig, PipelineNode, SlotDef, PromptDef, EdgeCondition, OpType, BezierKnot } from '../types';
import type { HarnessCatalogItem } from '../api/client';
import {
  ComponentPortsEditor,
  ContractSummary,
  MappingEditor,
  PermissionEditor,
  SchemaEditor,
  StringListEditor,
  collectVariableSuggestions,
  contractFor,
  type DagContractCatalog,
  type DagPortSpec,
} from './DagFormEditors';

import { JsonField, ScriptEditor, ValueField } from './NodeFieldEditors';

const AGENT_OPS: OpType[] = ['Agent', '推理', '工具审查', '处理工具', '工具', '执行工具'];
const TEXT_OPS: OpType[] = ['文本处理', '处理文字'];
const PYTHON_OPS: OpType[] = ['Python', '脚本'];
const MODEL_OPS: OpType[] = ['模型', 'llm_call'];

interface Props {
  config: HarnessConfig;
  selectedNode: PipelineNode | null;
  selectedEdge: { id: string; condition: EdgeCondition; kind: 'control' | 'data'; sourcePort: string; targetPort: string; source: string; target: string; route: string; reroutes: BezierKnot[]; channelOffset: number; curvature: number; labelOffset: number } | null;
  onConfigChange: (config: HarnessConfig) => void;
  onNodeUpdate: (nodeId: string, updates: Partial<PipelineNode>) => void;
  onEdgeUpdate: (edgeId: string, updates: { condition?: EdgeCondition; route?: string; reroutes?: BezierKnot[]; channelOffset?: number; curvature?: number; labelOffset?: number }) => void;
  onDeleteNode: (nodeId: string) => void;
  onDeleteEdge: (edgeId: string) => void;
  onSave: () => void;
  harnessList: string[];
  componentList: HarnessCatalogItem[];
  identityList: string[];
  dagContracts: DagContractCatalog | null;
  onRefreshIdentities: () => void;
}

export default function RightPanel({
  config, selectedNode, selectedEdge,
  onConfigChange, onNodeUpdate, onEdgeUpdate,
  onDeleteNode, onDeleteEdge,
  onSave, harnessList, componentList, identityList, dagContracts,
  onRefreshIdentities,
}: Props) {
  const [newSlotName, setNewSlotName] = useState('');
  const [newSlotDesc, setNewSlotDesc] = useState('');
  const [newPromptName, setNewPromptName] = useState('');
  const [newPromptDefault, setNewPromptDefault] = useState('');
  const [identityQuery, setIdentityQuery] = useState('');
  const [showAllIdentities, setShowAllIdentities] = useState(false);
  const filteredIdentities = useMemo(() => {
    const query = identityQuery.trim().toLocaleLowerCase();
    return query
      ? identityList.filter((identity) => identity.toLocaleLowerCase().includes(query))
      : identityList;
  }, [identityList, identityQuery]);
  const visibleIdentities = showAllIdentities ? filteredIdentities : filteredIdentities.slice(0, 10);
  const variableSuggestions = useMemo(() => collectVariableSuggestions(config), [config]);

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
    const nodeContract = contractFor(dagContracts, selectedNode.op);
    const selectedComponent = componentList.find((item) => item.name === selectedNode.harness)?.component;
    const componentInputHints = Object.fromEntries(Object.entries(selectedComponent?.inputs || {}).map(([name, spec]) => [name, {
      type: typeof spec.schema?.type === 'string' ? spec.schema.type : 'any',
      description: spec.description,
    } satisfies DagPortSpec]));
    const componentOutputHints = Object.fromEntries(Object.entries(selectedComponent?.outputs || {}).map(([name, spec]) => [name, {
      type: typeof spec.schema?.type === 'string' ? spec.schema.type : 'any',
      description: spec.description,
    } satisfies DagPortSpec]));
    const retry = typeof selectedNode.retry === 'object' ? selectedNode.retry : {};
    const maxAttempts = typeof selectedNode.retry === 'number'
      ? selectedNode.retry + 1
      : retry.max_attempts || 1;
    const isData = ['数据', '保存数据', '读取数据'].includes(selectedNode.op);
    const dataAction = selectedNode.action || (selectedNode.op === '读取数据' ? 'get' : 'set');
    const busDataActions = [
      'agent_register', 'agent_heartbeat', 'agent_unregister', 'agent_list',
      'message_publish', 'message_receive', 'message_ack', 'message_nack', 'message_list',
    ];
    const isBusData = busDataActions.includes(dataAction);
    const operationGroups = ['核心', '流程', '数据', '高级'].map((category) => ({
      category,
      operations: Object.entries(dagContracts?.nodes || {})
        .filter(([, contract]) => (contract.editor?.category || '高级') === category)
        .map(([op]) => op),
    })).filter((group) => group.operations.length > 0);
    return (
      <div className="right-panel">
        <div className="panel-section">
          <h3>节点配置: {selectedNode.id}</h3>
          <label>操作类型</label>
          <select
            value={selectedNode.op}
            onChange={(e) => onNodeUpdate(selectedNode.id, { op: e.target.value as OpType })}
          >
            {operationGroups.map((group) => <optgroup key={group.category} label={group.category}>
              {group.operations.map((op) => <option key={op} value={op}>{op}</option>)}
            </optgroup>)}
            {!dagContracts?.nodes?.[selectedNode.op] && <option value={selectedNode.op}>{selectedNode.op}（兼容旧配置）</option>}
          </select>
          <ContractSummary contract={nodeContract} />

          {(['输入', '等待输入'].includes(selectedNode.op)) && (
            <>
              <label><input type="checkbox" checked={selectedNode.reuse_last !== false} onChange={(e) => onNodeUpdate(selectedNode.id, { reuse_last: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />复用最近一条用户消息</label>
              {selectedNode.reuse_last === false && <><label>向用户提问</label><textarea rows={3} value={selectedNode.prompt_text || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { prompt_text: e.target.value })} placeholder="请补充继续执行所需的信息…" /></>}
              <p style={{ fontSize: 10, color: '#888' }}>关闭复用后，该节点会暂停并等待一条新的用户输入。</p>
            </>
          )}

          {AGENT_OPS.includes(selectedNode.op) && (
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
              {(selectedNode.op === 'Agent' || selectedNode.op === '推理') && (
                <>
                  <label>工具可见性</label>
                  <select
                    value={String(selectedNode.tools ?? 'auto')}
                    onChange={(e) => onNodeUpdate(selectedNode.id, { tools: e.target.value as 'auto' | 'all' | 'none' })}
                  >
                    <option value="auto">自动（有工具分支时启用）</option>
                    <option value="all">始终提供工具</option>
                    <option value="none">不提供工具</option>
                  </select>
                  <label>本次动态指令（可选）</label><ValueField value={selectedNode.instructions} onChange={(instructions) => onNodeUpdate(selectedNode.id, { instructions })} placeholder="Goal: ${ctx.goal}\nJudge feedback: ${ctx.feedback}" />
                  <label>只向模型显示这些工具（逗号 glob；空为全部）</label><input value={(selectedNode.visible_tools || []).join(', ')} onChange={(e) => onNodeUpdate(selectedNode.id, { visible_tools: e.target.value.split(',').map(value => value.trim()).filter(Boolean) })} placeholder="read*, search*, run_command" />
                  <label>调用模型前隐藏的工具（逗号 glob）</label><input value={(selectedNode.hidden_tools || []).join(', ')} onChange={(e) => onNodeUpdate(selectedNode.id, { hidden_tools: e.target.value.split(',').map(value => value.trim()).filter(Boolean) })} placeholder="write*, *patch*, multi_edit" />
                  <label>自动续跑条件（可选）</label><input value={typeof selectedNode.auto_continue_when === 'string' ? selectedNode.auto_continue_when : selectedNode.auto_continue_when === true ? 'true' : ''} onChange={(e) => onNodeUpdate(selectedNode.id, { auto_continue_when: e.target.value || undefined })} placeholder="compacted == true" />
                  {selectedNode.auto_continue_when != null && <>
                    <label>自动续跑提示</label><ValueField value={selectedNode.auto_continue_prompt ?? 'continue'} onChange={(auto_continue_prompt) => onNodeUpdate(selectedNode.id, { auto_continue_prompt })} />
                    <label>续跑前跳转节点</label><select value={selectedNode.auto_continue_to || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { auto_continue_to: e.target.value || undefined })}><option value="">当前 Agent 节点</option>{Object.keys(config.pipeline.nodes).filter(id => id !== selectedNode.id).map(id => <option key={id} value={id}>{id}</option>)}</select>
                    <label>单次连续自动续跑上限</label><input type="number" min="0" value={selectedNode.max_auto_continuations ?? 1} onChange={(e) => onNodeUpdate(selectedNode.id, { max_auto_continuations: Math.max(0, Number(e.target.value) || 0) })} />
                  </>}
                  <label>重复响应保护（0 为关闭）</label>
                  <input type="number" min="0" value={selectedNode.duplicate_threshold ?? 0} onChange={(e) => onNodeUpdate(selectedNode.id, { duplicate_threshold: Math.max(0, Number(e.target.value) || 0) })} />
                  {(selectedNode.duplicate_threshold ?? 0) > 0 && <><label>卡死纠偏提示</label><textarea rows={3} value={selectedNode.stuck_prompt || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { stuck_prompt: e.target.value || undefined })} placeholder="换一种策略，或直接给出事实性结论。" /></>}
                  <label>空 / 纯 reasoning 响应重试次数</label><input type="number" min="0" value={selectedNode.max_empty_responses ?? 1} onChange={(e) => onNodeUpdate(selectedNode.id, { max_empty_responses: Math.max(0, Number(e.target.value) || 0) })} />
                  <label>空响应纠偏提示</label><textarea rows={3} value={selectedNode.empty_response_prompt || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { empty_response_prompt: e.target.value || undefined })} placeholder="请给出具体动作、问题或最终答案。" />
                  <label>每轮最多工具动作（0 为不限）</label><input type="number" min="0" value={selectedNode.max_tool_calls_per_turn ?? 0} onChange={(e) => onNodeUpdate(selectedNode.id, { max_tool_calls_per_turn: Math.max(0, Number(e.target.value) || 0) })} />
                  {(selectedNode.max_tool_calls_per_turn ?? 0) > 0 && <>
                    <label>动作数量错误后跳转</label><select value={selectedNode.tool_call_count_error_to || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { tool_call_count_error_to: e.target.value || undefined })}><option value="">重试当前节点</option>{Object.keys(config.pipeline.nodes).filter(id => id !== selectedNode.id).map(id => <option key={id} value={id}>{id}</option>)}</select>
                    <label>动作数量纠偏提示</label><textarea rows={3} value={selectedNode.tool_call_count_error_prompt || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { tool_call_count_error_prompt: e.target.value || undefined })} placeholder="每一步只能返回一个动作。" />
                  </>}
                  <label>本节点最多工具轮次（0 为不限）</label><input type="number" min="0" value={selectedNode.max_tool_rounds ?? 0} onChange={(e) => onNodeUpdate(selectedNode.id, { max_tool_rounds: Math.max(0, Number(e.target.value) || 0) })} />
                  {(selectedNode.max_tool_rounds ?? 0) > 0 && <><label>工具轮次耗尽提示</label><textarea rows={3} value={selectedNode.tool_round_limit_prompt || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { tool_round_limit_prompt: e.target.value || undefined })} placeholder="请根据已经获得的信息直接给出最终结果，不再调用工具。" /></>}
                  <label><input type="checkbox" checked={Boolean(selectedNode.require_tool_for_mutations)} onChange={(e) => onNodeUpdate(selectedNode.id, { require_tool_for_mutations: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />修改类请求不得在真实执行工具前宣称完成</label>
                  <label><input type="checkbox" checked={Boolean(selectedNode.require_tool_before_text)} onChange={(e) => onNodeUpdate(selectedNode.id, { require_tool_before_text: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />每个用户回合都必须先成功执行指定工具</label>
                  {(selectedNode.require_tool_for_mutations || selectedNode.require_tool_before_text) && <>
                    <label>可满足验收的工具（逗号 glob）</label><input value={(selectedNode.required_tool_patterns || ['write_file', 'patch_file', 'multi_edit']).join(', ')} onChange={(e) => onNodeUpdate(selectedNode.id, { required_tool_patterns: e.target.value.split(',').map(value => value.trim()).filter(Boolean) })} />
                    <label>缺少真实工具动作时最多纠偏次数</label><input type="number" min="0" value={selectedNode.max_required_tool_retries ?? 2} onChange={(e) => onNodeUpdate(selectedNode.id, { max_required_tool_retries: Math.max(0, Number(e.target.value) || 0) })} />
                    <label>纠偏提示</label><textarea rows={3} value={selectedNode.required_tool_prompt || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { required_tool_prompt: e.target.value || undefined })} placeholder="不要宣称完成；先执行实际编辑工具并验证结果。" />
                  </>}
                </>
              )}
              {(selectedNode.op === '工具' || selectedNode.op === '执行工具') && (
                <>
                  <label><input type="checkbox" checked={Boolean(selectedNode.parallel)} onChange={(e) => onNodeUpdate(selectedNode.id, { parallel: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />并行执行同一轮的多个工具调用</label>
                  <label>轨迹中隐藏的参数名</label><input value={(selectedNode.sensitive_fields || []).join(', ')} onChange={(e) => onNodeUpdate(selectedNode.id, { sensitive_fields: e.target.value.split(',').map(value => value.trim()).filter(Boolean) })} placeholder="password, token, text" />
                  <label><input type="checkbox" checked={Boolean(selectedNode.attach_images)} onChange={(e) => onNodeUpdate(selectedNode.id, { attach_images: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />把工具返回的 Workspace 图片附给 vision 模型</label>
                  {selectedNode.attach_images && <><label>单张图片最大字节数</label><input type="number" min="1" value={selectedNode.max_image_bytes || 8000000} onChange={(e) => onNodeUpdate(selectedNode.id, { max_image_bytes: Math.max(1, Number(e.target.value) || 1) })} /></>}
                  <label>单条工具观察最大字符（留空为不限）</label><input type="number" min="1" value={selectedNode.max_observation_chars ?? ''} onChange={(e) => onNodeUpdate(selectedNode.id, { max_observation_chars: e.target.value ? Math.max(1, Number(e.target.value) || 1) : undefined })} placeholder="10000" />
                  {!selectedNode.parallel && <><label>中断同轮后续动作（可选）</label><input value={selectedNode.interrupt_when || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { interrupt_when: e.target.value || undefined })} placeholder="tool == 'browser' and arguments.action == 'navigate'" /></>}
                  <label>相同动作与结果重复 N 次后纠偏（0 为关闭）</label><input type="number" min="0" value={selectedNode.stuck_threshold ?? 0} onChange={(e) => onNodeUpdate(selectedNode.id, { stuck_threshold: Math.max(0, Number(e.target.value) || 0) })} />
                  <label>相同动作连续失败 N 次后纠偏（0 为关闭）</label><input type="number" min="0" value={selectedNode.error_stuck_threshold ?? 0} onChange={(e) => onNodeUpdate(selectedNode.id, { error_stuck_threshold: Math.max(0, Number(e.target.value) || 0) })} />
                  <label>连续错误 N 次时先软提醒一次（0 为关闭）</label><input type="number" min="0" value={selectedNode.error_nudge_threshold ?? 0} onChange={(e) => onNodeUpdate(selectedNode.id, { error_nudge_threshold: Math.max(0, Number(e.target.value) || 0) })} />
                  <label>A-B 循环动作数（0 为关闭）</label><input type="number" min="0" value={selectedNode.alternating_stuck_threshold ?? 0} onChange={(e) => onNodeUpdate(selectedNode.id, { alternating_stuck_threshold: Math.max(0, Number(e.target.value) || 0) })} />
                  <label>遇到这些终止工具后丢弃同批后续调用</label><input value={(selectedNode.truncate_after_tools || []).join(', ')} onChange={(e) => onNodeUpdate(selectedNode.id, { truncate_after_tools: e.target.value.split(',').map(value => value.trim()).filter(Boolean) })} placeholder="finish, submit_result" />
                  <label>同一批只执行第一次的独占工具</label><input value={(selectedNode.exclusive_tools || []).join(', ')} onChange={(e) => onNodeUpdate(selectedNode.id, { exclusive_tools: e.target.value.split(',').map(value => value.trim()).filter(Boolean) })} placeholder="edit_file, open_file" />
                  <label>只能作为批次第一个动作的工具</label><input value={(selectedNode.only_first_tools || []).join(', ')} onChange={(e) => onNodeUpdate(selectedNode.id, { only_first_tools: e.target.value.split(',').map(value => value.trim()).filter(Boolean) })} placeholder="done" />
                  <label>终止工具执行后跳转（可选）</label><select value={selectedNode.terminal_tools_to || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { terminal_tools_to: e.target.value || undefined })}><option value="">继续普通工具流程</option>{Object.keys(config.pipeline.nodes).filter(id => id !== selectedNode.id).map(id => <option key={id} value={id}>{id}</option>)}</select>
                  <label>工具主动结束后跳转（可选）</label><select value={selectedNode.end_session_to || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { end_session_to: e.target.value || undefined })}><option value="">直接结束流程</option>{Object.keys(config.pipeline.nodes).filter(id => id !== selectedNode.id).map(id => <option key={id} value={id}>{id}</option>)}</select>
                </>
              )}
            </>
          )}

          {TEXT_OPS.includes(selectedNode.op) && (
            <>
              <label>文本处理方式</label>
              <select value={selectedNode.mode || 'agent'} onChange={(e) => onNodeUpdate(selectedNode.id, { mode: e.target.value as PipelineNode['mode'] })}>
                <option value="agent">交给 Identity 处理</option>
                <option value="thought_action">确定性 Thought / Action 协议</option>
                <option value="aider_search_replace">确定性 Aider SEARCH / REPLACE</option>
              </select>
              {!['thought_action', 'aider_search_replace', 'aider_editblock'].includes(selectedNode.mode || 'agent') && <>
                <label>Agent (slot 名)</label>
                <select value={selectedNode.agent || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { agent: e.target.value || undefined })}>
                  <option value="">-- 选择 slot --</option>{Object.keys(config.slots).map((slot) => <option key={slot} value={slot}>{slot}</option>)}
                </select>
              </>}
              {selectedNode.mode === 'thought_action' && <>
                <p style={{ fontSize: 10, color: '#94a3b8' }}>解析最后一个顶层代码块：代码块外是思考，块内是一条环境动作；普通最终回答会触发纠偏。</p>
                <label>环境工具名</label><input value={selectedNode.action_tool || 'run_command'} onChange={(e) => onNodeUpdate(selectedNode.id, { action_tool: e.target.value || 'run_command' })} />
                <label>动作参数名</label><input value={selectedNode.action_argument || 'command'} onChange={(e) => onNodeUpdate(selectedNode.id, { action_argument: e.target.value || 'command' })} />
                <label>额外固定参数</label><JsonField value={selectedNode.action_arguments || {}} onChange={(action_arguments) => onNodeUpdate(selectedNode.id, { action_arguments })} placeholder={'{"blocking":true,"timeout":120}'} />
                <label>提交命令（逗号分隔）</label><input value={(selectedNode.submission_commands || ['submit']).join(', ')} onChange={(e) => onNodeUpdate(selectedNode.id, { submission_commands: e.target.value.split(',').map(value => value.trim()).filter(Boolean) })} />
                <label>退出命令（逗号分隔）</label><input value={(selectedNode.exit_commands || ['exit']).join(', ')} onChange={(e) => onNodeUpdate(selectedNode.id, { exit_commands: e.target.value.split(',').map(value => value.trim()).filter(Boolean) })} />
                <label>格式错误最多询问次数</label><input type="number" min="1" value={selectedNode.max_requeries ?? 3} onChange={(e) => onNodeUpdate(selectedNode.id, { max_requeries: Math.max(1, Number(e.target.value) || 1) })} />
                <label>格式纠偏提示</label><textarea rows={4} value={selectedNode.format_error_prompt || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { format_error_prompt: e.target.value || undefined })} placeholder="请用一个讨论段落加最后一个 fenced code block 返回单个动作。" />
              </>}
              {['aider_search_replace', 'aider_editblock'].includes(selectedNode.mode || '') && <>
                <p style={{ fontSize: 10, color: '#94a3b8' }}>把模型文本确定性解析为带文件名的 SEARCH / REPLACE 编辑提案；文本本身不会被执行。</p>
                <label>允许的文件名</label><ValueField value={selectedNode.valid_filenames ?? '$ctx.edit_plan.files'} onChange={(valid_filenames) => onNodeUpdate(selectedNode.id, { valid_filenames })} placeholder="$ctx.edit_plan.files" />
                <label><input type="checkbox" checked={selectedNode.require_edits !== false} onChange={(e) => onNodeUpdate(selectedNode.id, { require_edits: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />没有编辑块时视为格式错误</label>
                <label>格式错误最多反思次数</label><input type="number" min="1" value={selectedNode.max_requeries ?? 3} onChange={(e) => onNodeUpdate(selectedNode.id, { max_requeries: Math.max(1, Number(e.target.value) || 1) })} />
                <label>格式纠偏提示</label><textarea rows={4} value={selectedNode.format_error_prompt || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { format_error_prompt: e.target.value || undefined })} placeholder="只返回带文件名的 <<<<<<< SEARCH / ======= / >>>>>>> REPLACE 编辑块。" />
              </>}
            </>
          )}

          {(['处理工具', '文本处理', '处理文字'].includes(selectedNode.op) || selectedNode.op === '模型' || selectedNode.op === 'llm_call') && (
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

          {selectedNode.op === '进程' && (
            <>
              <label>执行后端</label><select value={selectedNode.backend || 'local'} onChange={(e) => onNodeUpdate(selectedNode.id, { backend: e.target.value as PipelineNode['backend'] })}>
                <option value="local">本机进程</option><option value="container">隔离容器</option><option value="docker">Docker 容器</option><option value="podman">Podman 容器</option>
              </select>
              {selectedNode.backend && selectedNode.backend !== 'local' && <>
                <label>容器安全配置</label><JsonField value={selectedNode.container || { engine: 'docker', image: 'python:3.12-slim', network: 'none', read_only_root: true, workspace_access: 'rw', pids_limit: 256, memory: '512m', cpus: 1, pull_policy: 'never' }} onChange={(container) => onNodeUpdate(selectedNode.id, { container })} placeholder={'{"engine":"docker","image":"python:3.12-slim","network":"none","read_only_root":true,"workspace_access":"rw","pull_policy":"never"}'} />
                <label>容器清理超时（秒）</label><input type="number" min="1" value={selectedNode.container_cleanup_timeout_seconds ?? 10} onChange={(e) => onNodeUpdate(selectedNode.id, { container_cleanup_timeout_seconds: Math.max(1, Number(e.target.value) || 1) })} />
              </>}
              <label>可执行程序</label><ValueField value={selectedNode.command} onChange={(command) => onNodeUpdate(selectedNode.id, { command })} placeholder="python" />
              <label>参数列表</label><JsonField value={selectedNode.args || []} onChange={(args) => onNodeUpdate(selectedNode.id, { args })} placeholder={'["experiment.py", "--out_dir", "run_1"]'} />
              <label>Workspace 内工作目录</label><ValueField value={selectedNode.cwd ?? '.'} onChange={(cwd) => onNodeUpdate(selectedNode.id, { cwd })} placeholder="." />
              <label>环境变量</label><JsonField value={selectedNode.env || {}} onChange={(env) => onNodeUpdate(selectedNode.id, { env })} placeholder={'{"CUDA_VISIBLE_DEVICES":"0"}'} />
              <label>标准输入（可选）</label><ValueField value={selectedNode.stdin} onChange={(stdin) => onNodeUpdate(selectedNode.id, { stdin })} />
              <label>成功退出码</label><JsonField value={selectedNode.success_codes || [0]} onChange={(success_codes) => onNodeUpdate(selectedNode.id, { success_codes })} placeholder="[0]" />
              <label>收集产物（相对 glob）</label><JsonField value={selectedNode.artifacts || []} onChange={(artifacts) => onNodeUpdate(selectedNode.id, { artifacts })} placeholder={'["run_*/results.json", "*.pdf"]'} />
              <label>资源请求</label><JsonField value={selectedNode.resources || {}} onChange={(resources) => onNodeUpdate(selectedNode.id, { resources })} placeholder={'{"gpu":1}'} />
              <label>终止宽限时间（秒）</label><input type="number" min="0" step="0.1" value={selectedNode.termination_grace_seconds ?? 0.5} onChange={(e) => onNodeUpdate(selectedNode.id, { termination_grace_seconds: Math.max(0, Number(e.target.value) || 0) })} />
              <label><input type="checkbox" checked={selectedNode.fail_on_error !== false} onChange={(e) => onNodeUpdate(selectedNode.id, { fail_on_error: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />非成功退出码进入错误路径</label>
              <label>输出变量</label><input value={selectedNode.output_var || 'process_result'} onChange={(e) => onNodeUpdate(selectedNode.id, { output_var: e.target.value })} />
              <p style={{ fontSize: 10, color: '#888' }}>不经过 shell；命令和参数分开传入。本机后端终止整棵进程树；容器后端默认禁网、丢弃 capabilities、限制内存/CPU/PID，并在结束、超时或取消后强制清理。</p>
            </>
          )}

          {selectedNode.op === '工作区' && (
            <>
              <label>操作</label><select value={selectedNode.action || 'mkdir'} onChange={(e) => onNodeUpdate(selectedNode.id, { action: e.target.value as PipelineNode['action'] })}>
                <option value="mkdir">创建隔离目录</option><option value="copy">复制模板 / 文件</option><option value="move">移动 / 重命名文件</option><option value="delete">删除文件</option><option value="snapshot">创建快照</option><option value="restore">恢复快照</option><option value="list">列出产物</option><option value="read_text">读取有界文本</option><option value="read_json">读取 JSON</option><option value="read_binary">读取二进制（Base64）</option><option value="write_text">原子写入文本</option><option value="write_json">原子写入 JSON</option><option value="write_binary">原子写入二进制</option><option value="publish">发布 / 复制产物</option><option value="begin_transaction">开始 Agent 编辑事务</option><option value="apply_search_replace">应用 SEARCH / REPLACE 提案</option><option value="changes">读取编辑提案</option><option value="review_transaction">完成逐段审核</option><option value="rollback_transaction">回退整个编辑事务</option>
              </select>
              {selectedNode.action === 'begin_transaction' && <>
                <label>事务 ID（可选）</label><ValueField value={selectedNode.transaction_id} onChange={(transaction_id) => onNodeUpdate(selectedNode.id, { transaction_id })} placeholder="留空自动生成" />
                <label>编辑前快照路径（可选）</label><JsonField value={selectedNode.paths || []} onChange={(paths) => onNodeUpdate(selectedNode.id, { paths })} placeholder={'["src", "tests"]'} />
              </>}
              {(['changes', 'review_transaction', 'rollback_transaction'].includes(selectedNode.action || '')) && <>
                <label>事务 ID</label><ValueField value={selectedNode.transaction_id ?? '$ctx._change_transaction'} onChange={(transaction_id) => onNodeUpdate(selectedNode.id, { transaction_id })} />
              </>}
              {selectedNode.action === 'review_transaction' && <>
                <label>无人值守时处理待审段落</label><select value={selectedNode.pending_policy || 'reject'} onChange={(e) => onNodeUpdate(selectedNode.id, { pending_policy: e.target.value as PipelineNode['pending_policy'] })}><option value="reject">全部拒绝（安全默认）</option><option value="accept">全部接受</option><option value="error">保持待审并报错</option></select>
              </>}
              {['apply_search_replace', 'apply_edits'].includes(selectedNode.action || '') && <>
                <label>编辑提案</label><ValueField value={selectedNode.edits ?? '$ctx.proposed_edits'} onChange={(edits) => onNodeUpdate(selectedNode.id, { edits })} placeholder="$ctx.proposed_edits" />
                <label>可回退匹配的文件</label><ValueField value={selectedNode.allowed_paths ?? '$ctx.edit_plan.files'} onChange={(allowed_paths) => onNodeUpdate(selectedNode.id, { allowed_paths })} placeholder="$ctx.edit_plan.files" />
                <label><input type="checkbox" checked={selectedNode.fallback_to_allowed_paths !== false} onChange={(e) => onNodeUpdate(selectedNode.id, { fallback_to_allowed_paths: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />文件名不准时在允许文件中寻找唯一匹配</label>
                <label><input type="checkbox" checked={Boolean(selectedNode.atomic)} onChange={(e) => onNodeUpdate(selectedNode.id, { atomic: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />任一块失败则本轮全部不写入（更安全）</label>
                <p style={{ fontSize: 10, color: '#888' }}>关闭原子模式时与 Aider 一致：成功块保留，失败块生成修复提示；所有写入仍进入逐段 Accept / Reject 事务。</p>
              </>}
              {selectedNode.action === 'mkdir' && <><label>目标目录</label><ValueField value={selectedNode.target ?? selectedNode.path} onChange={(target) => onNodeUpdate(selectedNode.id, { target })} placeholder=".egoagent/work/run-1" /></>}
              {(['copy', 'publish'].includes(selectedNode.action || '')) && <>
                <label>来源</label><ValueField value={selectedNode.source} onChange={(source) => onNodeUpdate(selectedNode.id, { source })} placeholder="templates/base" />
                <label>目标</label><ValueField value={selectedNode.target} onChange={(target) => onNodeUpdate(selectedNode.id, { target })} placeholder=".egoagent/work/idea-1" />
                <label><input type="checkbox" checked={Boolean(selectedNode.overwrite)} onChange={(e) => onNodeUpdate(selectedNode.id, { overwrite: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />允许覆盖目标中的同名文件</label>
              </>}
              {(['move', 'rename'].includes(selectedNode.action || '')) && <>
                <label>原文件</label><ValueField value={selectedNode.source ?? selectedNode.path} onChange={(source) => onNodeUpdate(selectedNode.id, { source })} placeholder="src/old_name.py" />
                <label>新路径</label><ValueField value={selectedNode.target} onChange={(target) => onNodeUpdate(selectedNode.id, { target })} placeholder="src/new_name.py" />
                <label><input type="checkbox" checked={selectedNode.track_change !== false} onChange={(e) => onNodeUpdate(selectedNode.id, { track_change: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />记录为可撤销的文件移动</label>
              </>}
              {selectedNode.action === 'delete' && <>
                <label>文件路径</label><ValueField value={selectedNode.path ?? ''} onChange={(path) => onNodeUpdate(selectedNode.id, { path: typeof path === 'string' ? path : String(path ?? '') })} placeholder="obsolete.txt" />
                <label><input type="checkbox" checked={selectedNode.track_change !== false} onChange={(e) => onNodeUpdate(selectedNode.id, { track_change: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />保留内容并记录为可拒绝的删除</label>
              </>}
              {selectedNode.action === 'snapshot' && <>
                <label>快照路径列表</label><JsonField value={selectedNode.paths || []} onChange={(paths) => onNodeUpdate(selectedNode.id, { paths })} placeholder={'["src", "results"]'} />
                <label>快照标签</label><input value={selectedNode.label || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { label: e.target.value })} placeholder="before-experiment" />
                <label>忽略 glob</label><JsonField value={selectedNode.ignore || ['.git/**', 'node_modules/**', '.egoagent/snapshots/**']} onChange={(ignore) => onNodeUpdate(selectedNode.id, { ignore })} />
              </>}
              {selectedNode.action === 'restore' && <>
                <label>快照文件</label><ValueField value={selectedNode.path} onChange={(path) => onNodeUpdate(selectedNode.id, { path: typeof path === 'string' ? path : String(path ?? '') })} placeholder="$ctx.snapshot.path" />
                <label><input type="checkbox" checked={selectedNode.backup_before_restore !== false} onChange={(e) => onNodeUpdate(selectedNode.id, { backup_before_restore: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />恢复前自动备份当前文件</label>
              </>}
              {selectedNode.action === 'list' && <>
                <label>基础目录</label><ValueField value={selectedNode.path ?? '.'} onChange={(path) => onNodeUpdate(selectedNode.id, { path: typeof path === 'string' ? path : String(path ?? '') })} />
                <label>产物 glob</label><JsonField value={selectedNode.patterns || ['**/*']} onChange={(patterns) => onNodeUpdate(selectedNode.id, { patterns })} />
              </>}
              {['read_text', 'read_json', 'read_binary'].includes(selectedNode.action || '') && <>
                <label>文件路径</label><ValueField value={selectedNode.path ?? ''} onChange={(path) => onNodeUpdate(selectedNode.id, { path: typeof path === 'string' ? path : String(path ?? '') })} placeholder="experiment.py" />
                <label>最大读取字节数</label><input type="number" min="1" value={selectedNode.max_bytes || 1000000} onChange={(e) => onNodeUpdate(selectedNode.id, { max_bytes: Math.max(1, Number(e.target.value) || 1) })} />
                <label><input type="checkbox" checked={Boolean(selectedNode.allow_missing)} onChange={(e) => onNodeUpdate(selectedNode.id, { allow_missing: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />文件不存在时返回默认值</label>
                {selectedNode.action === 'read_text' && <label><input type="checkbox" checked={Boolean(selectedNode.truncate)} onChange={(e) => onNodeUpdate(selectedNode.id, { truncate: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />超限时截断而非报错</label>}
              </>}
              {['write_text', 'write_json', 'write_binary'].includes(selectedNode.action || '') && <>
                <label>文件路径</label><ValueField value={selectedNode.path ?? ''} onChange={(path) => onNodeUpdate(selectedNode.id, { path: typeof path === 'string' ? path : String(path ?? '') })} placeholder="reports/paper.md" />
                <label>写入内容</label><ValueField value={selectedNode.value} onChange={(value) => onNodeUpdate(selectedNode.id, { value })} placeholder="$ctx.draft" />
                {selectedNode.action === 'write_binary' && <><label>内容编码</label><select value={selectedNode.binary_encoding || 'base64'} onChange={(e) => onNodeUpdate(selectedNode.id, { binary_encoding: e.target.value as PipelineNode['binary_encoding'] })}><option value="base64">Base64</option><option value="hex">Hex</option><option value="utf8">UTF-8 文本转字节</option></select></>}
                <label>最大写入字节数</label><input type="number" min="1" value={selectedNode.max_bytes || 5000000} onChange={(e) => onNodeUpdate(selectedNode.id, { max_bytes: Math.max(1, Number(e.target.value) || 1) })} />
                <label><input type="checkbox" checked={Boolean(selectedNode.overwrite)} onChange={(e) => onNodeUpdate(selectedNode.id, { overwrite: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />允许覆盖现有文件</label>
                <label><input type="checkbox" checked={Boolean(selectedNode.append)} onChange={(e) => onNodeUpdate(selectedNode.id, { append: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />追加而非替换</label>
                <label><input type="checkbox" checked={selectedNode.track_change !== false} onChange={(e) => onNodeUpdate(selectedNode.id, { track_change: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />记录为可逐段 Accept / Reject 的差异</label>
              </>}
              <label>输出变量</label><input value={selectedNode.output_var || 'workspace_result'} onChange={(e) => onNodeUpdate(selectedNode.id, { output_var: e.target.value })} />
              <p style={{ fontSize: 10, color: '#888' }}>所有路径必须位于 Workspace 内；恢复前默认生成可回退备份。</p>
            </>
          )}

          {selectedNode.op === '工具审查' && (
            <>
              <label>审查方式</label><select value={selectedNode.review_mode || 'agent'} onChange={(e) => onNodeUpdate(selectedNode.id, { review_mode: e.target.value as PipelineNode['review_mode'] })}><option value="policy">确定性策略</option><option value="agent">Identity 判断</option><option value="both">先策略，再 Identity</option></select>
              {selectedNode.review_mode !== 'agent' && <>
                <label>默认权限</label><select value={selectedNode.default_permission || 'allow'} onChange={(e) => onNodeUpdate(selectedNode.id, { default_permission: e.target.value as PipelineNode['default_permission'] })}><option value="allow">允许</option><option value="ask">每次询问</option><option value="deny">拒绝</option></select>
                <label>规则匹配顺序</label><select value={selectedNode.policy_match || 'last'} onChange={(e) => onNodeUpdate(selectedNode.id, { policy_match: e.target.value as PipelineNode['policy_match'] })}><option value="last">最后匹配优先（EgoAgent 默认）</option><option value="first">首次匹配优先（Continue）</option></select>
                <label>工具策略（{selectedNode.policy_match === 'first' ? '首次' : '最后'}匹配优先）</label><JsonField value={selectedNode.policies || []} onChange={(policies) => onNodeUpdate(selectedNode.id, { policies })} placeholder={'[{"tool":"read*","permission":"allow"},{"tool":"run_command","permission":"ask"}]'} rows={7} />
                <label>无人值守的询问默认值</label><select value={selectedNode.ask_default || 'rejected'} onChange={(e) => onNodeUpdate(selectedNode.id, { ask_default: e.target.value as PipelineNode['ask_default'] })}><option value="rejected">拒绝</option><option value="approved">通过</option></select>
              </>}
            </>
          )}

          {selectedNode.op === '条件' && (
            <>
              <label>条件表达式</label>
              <input
                value={String(selectedNode.condition ?? '')}
                onChange={(e) => onNodeUpdate(selectedNode.id, { condition: e.target.value })}
                placeholder="ctx.score >= 0.8 and exists(ctx.answer)"
              />
              <p style={{ fontSize: 10, color: '#888' }}>使用 true / false 连线；支持 exists、len、contains，不执行 Python。</p>
              <label>保存判断结果到（可选）</label>
              <input value={selectedNode.output_var || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { output_var: e.target.value || undefined })} placeholder="decision.passed" />
            </>
          )}

          {selectedNode.op === '上下文' && (
            <>
              <label>操作</label>
              <select value={selectedNode.action || 'select'} onChange={(e) => onNodeUpdate(selectedNode.id, { action: e.target.value as PipelineNode['action'] })}>
                <option value="snapshot">Conversation Input（只读元数据）</option>
                <option value="apply">Conversation Output（提交变换）</option>
                <option value="select">筛选</option>
                <option value="last_n_observations">保留首条与最近 N 条环境观察</option>
                <option value="restore_full">恢复完整上下文</option>
                {['compact', 'auto_compact', 'curate'].includes(selectedNode.action || '') && <option value={selectedNode.action}>Legacy：旧版内置模型策略（请换成 SubDAG）</option>}
              </select>
              <label>消息来源</label><ValueField value={selectedNode.source ?? (['curate', 'restore_full'].includes(selectedNode.action || '') ? '$session.full_messages' : '$session.messages')} onChange={(source) => onNodeUpdate(selectedNode.id, { source })} />
              {selectedNode.action === 'snapshot' && <>
                <label>完整审计消息来源</label><ValueField value={(selectedNode as any).full_source ?? '$session.full_messages'} onChange={(full_source) => onNodeUpdate(selectedNode.id, { full_source } as Partial<PipelineNode>)} />
                <label>积累多少个旧轮次后标记 review_due（0 = 不检查）</label><input type="number" min="0" value={selectedNode.review_interval ?? 0} onChange={(e) => onNodeUpdate(selectedNode.id, { review_interval: Math.max(0, Number(e.target.value) || 0) })} />
                <label>保护最近轮次</label><input type="number" min="1" value={selectedNode.protect_recent_turns ?? 2} onChange={(e) => onNodeUpdate(selectedNode.id, { protect_recent_turns: Math.max(1, Number(e.target.value) || 1) })} />
                <label>上下文上限（留空则不计算压力）</label><input type="number" min="0" value={selectedNode.context_limit_tokens ?? 0} onChange={(e) => onNodeUpdate(selectedNode.id, { context_limit_tokens: Math.max(0, Number(e.target.value) || 0) })} />
                {Boolean(selectedNode.context_limit_tokens) && <>
                  <label>触发比例</label><input type="number" min="0.2" max="0.98" step="0.01" value={selectedNode.high_watermark ?? 0.82} onChange={(e) => onNodeUpdate(selectedNode.id, { high_watermark: Number(e.target.value) })} />
                  <label>压缩目标比例</label><input type="number" min="0.1" max="0.9" step="0.01" value={selectedNode.target_ratio ?? 0.62} onChange={(e) => onNodeUpdate(selectedNode.id, { target_ratio: Number(e.target.value) })} />
                  <label>预留输出 Token</label><input type="number" min="0" value={selectedNode.reserved_output_tokens ?? 4096} onChange={(e) => onNodeUpdate(selectedNode.id, { reserved_output_tokens: Math.max(0, Number(e.target.value) || 0) })} />
                </>}
                <p style={{ fontSize: 10, color: '#888' }}>只生成 turns、protocol-safe blocks、Token 压力和 JSON model_payload；不会调用模型或修改历史。</p>
              </>}
              {selectedNode.action === 'apply' && <>
                <label>变换类型</label><select value={selectedNode.apply_mode || 'turn_plan'} onChange={(e) => onNodeUpdate(selectedNode.id, { apply_mode: e.target.value as PipelineNode['apply_mode'] })}><option value="turn_plan">轮次精简计划</option><option value="block_plan">Token 压缩计划</option><option value="restore_full">恢复完整记录</option></select>
                {selectedNode.apply_mode !== 'restore_full' && <><label>普通 Model 节点生成的 JSON 计划</label><ValueField value={selectedNode.plan ?? '$ctx.context_plan'} onChange={(plan) => onNodeUpdate(selectedNode.id, { plan })} /></>}
                {selectedNode.apply_mode === 'block_plan' && <><label>目标 Token</label><ValueField value={selectedNode.target_tokens ?? '$ctx.conversation_snapshot.pressure.target_tokens'} onChange={(target_tokens) => onNodeUpdate(selectedNode.id, { target_tokens })} /></>}
                {selectedNode.apply_mode !== 'restore_full' && <><label>保护最近轮次</label><input type="number" min="1" value={selectedNode.protect_recent_turns ?? 2} onChange={(e) => onNodeUpdate(selectedNode.id, { protect_recent_turns: Math.max(1, Number(e.target.value) || 1) })} /></>}
                <label><input type="checkbox" checked={selectedNode.persist_session !== false} onChange={(e) => onNodeUpdate(selectedNode.id, { persist_session: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />提交到模型工作上下文（完整 UI 记录保留）</label>
                <p style={{ fontSize: 10, color: '#888' }}>该节点只校验并应用计划。总结内容必须由前面的普通 Model 节点生成。</p>
              </>}
              {!['last_n_observations', 'auto_compact', 'curate', 'restore_full'].includes(selectedNode.action || 'select') && <><label>只保留最近 N 条</label><input type="number" min="0" value={selectedNode.last_n ?? 20} onChange={(e) => onNodeUpdate(selectedNode.id, { last_n: Math.max(0, Number(e.target.value) || 0) })} /></>}
              {selectedNode.action === 'last_n_observations' && <>
                <label>保留最近 N 条环境观察</label><input type="number" min="1" value={selectedNode.observation_last_n ?? selectedNode.last_n ?? 5} onChange={(e) => onNodeUpdate(selectedNode.id, { observation_last_n: Math.max(1, Number(e.target.value) || 1) })} />
                <label>每隔多少条观察重算</label><input type="number" min="1" value={selectedNode.polling ?? 1} onChange={(e) => onNodeUpdate(selectedNode.id, { polling: Math.max(1, Number(e.target.value) || 1) })} />
                <p style={{ fontSize: 10, color: '#888' }}>首条实例描述永远保留；更早的环境输出替换为省略行数提示，适合长程 coding agent。</p>
              </>}
              {selectedNode.action === 'auto_compact' && <>
                <label>模型上下文上限（Token）</label><input type="number" min="1" value={selectedNode.context_limit_tokens ?? 128000} onChange={(e) => onNodeUpdate(selectedNode.id, { context_limit_tokens: Math.max(1, Number(e.target.value) || 1) })} />
                <label>为模型输出预留（Token）</label><input type="number" min="0" value={selectedNode.max_output_tokens ?? 4096} onChange={(e) => onNodeUpdate(selectedNode.id, { max_output_tokens: Math.max(0, Number(e.target.value) || 0) })} />
                <label>System / 工具定义预留（Token）</label><input type="number" min="0" value={selectedNode.reserved_tokens ?? 0} onChange={(e) => onNodeUpdate(selectedNode.id, { reserved_tokens: Math.max(0, Number(e.target.value) || 0) })} />
                <label>安全缓冲比例</label><input type="number" min="0" max="0.99" step="0.05" value={selectedNode.compaction_buffer_ratio ?? 0.2} onChange={(e) => onNodeUpdate(selectedNode.id, { compaction_buffer_ratio: Math.min(0.99, Math.max(0, Number(e.target.value) || 0)) })} />
                <label>安全缓冲上限（Token）</label><input type="number" min="0" value={selectedNode.compaction_buffer_cap ?? 15000} onChange={(e) => onNodeUpdate(selectedNode.id, { compaction_buffer_cap: Math.max(0, Number(e.target.value) || 0) })} />
                <label>摘要最长输出（Token）</label><input type="number" min="1" value={selectedNode.summary_max_tokens ?? 2048} onChange={(e) => onNodeUpdate(selectedNode.id, { summary_max_tokens: Math.max(1, Number(e.target.value) || 1) })} />
                <label>压缩 Identity</label><select value={selectedNode.agent || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { agent: e.target.value || undefined })}><option value="">-- 主 Agent --</option>{Object.keys(config.slots).map(slot => <option key={slot} value={slot}>{slot}</option>)}</select>
                <label><input type="checkbox" checked={selectedNode.persist_session !== false} onChange={(e) => onNodeUpdate(selectedNode.id, { persist_session: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />用摘要替换当前工作历史（完整审计历史仍保留）</label>
                <label>压缩状态变量</label><input value={selectedNode.compacted_var || 'context_compacted'} onChange={(e) => onNodeUpdate(selectedNode.id, { compacted_var: e.target.value || 'context_compacted' })} />
              </>}
              {selectedNode.action === 'compact' && <>
                <label>压缩后保留最近 N 条原文</label><input type="number" min="0" value={selectedNode.keep_last ?? 6} onChange={(e) => onNodeUpdate(selectedNode.id, { keep_last: Math.max(0, Number(e.target.value) || 0) })} />
                <label><input type="checkbox" checked={selectedNode.summarize !== false} onChange={(e) => onNodeUpdate(selectedNode.id, { summarize: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />使用所选 Identity 总结旧消息</label>
                <label>总结 Identity</label><select value={selectedNode.agent || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { agent: e.target.value || undefined })}><option value="">-- 主 Agent --</option>{Object.keys(config.slots).map(slot => <option key={slot} value={slot}>{slot}</option>)}</select>
              </>}
              {selectedNode.action === 'curate' && <>
                <label>每 N 个旧对话轮次检查一次</label><input type="number" min="1" value={selectedNode.review_interval ?? 5} onChange={(e) => onNodeUpdate(selectedNode.id, { review_interval: Math.max(1, Number(e.target.value) || 1) })} />
                <label>始终保护最近轮次</label><input type="number" min="1" value={selectedNode.protect_recent_turns ?? 2} onChange={(e) => onNodeUpdate(selectedNode.id, { protect_recent_turns: Math.max(1, Number(e.target.value) || 1) })} />
                <label>工具结果工作副本上限（字符）</label><input type="number" min="200" value={selectedNode.max_tool_chars ?? 1800} onChange={(e) => onNodeUpdate(selectedNode.id, { max_tool_chars: Math.max(200, Number(e.target.value) || 200) })} />
                <label>判断 Identity</label><select value={selectedNode.agent || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { agent: e.target.value || undefined })}><option value="">-- 主 Agent --</option>{Object.keys(config.slots).map(slot => <option key={slot} value={slot}>{slot}</option>)}</select>
                <label><input type="checkbox" checked={selectedNode.persist_session !== false} onChange={(e) => onNodeUpdate(selectedNode.id, { persist_session: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />更新模型工作上下文；UI 完整历史不删除</label>
                <p style={{ fontSize: 10, color: '#888' }}>旧轮次会被保留、总结或从模型视图剔除。解析失败时一律保留；文件路径、错误与未完成事项作为精确锚点保留。</p>
              </>}
              {selectedNode.action === 'restore_full' && <p style={{ fontSize: 10, color: '#888' }}>移除所有上下文标记并把完整审计记录重新作为模型工作历史。此操作不会删除聊天内容。</p>}
              <label>输出变量</label><input value={selectedNode.output_var || 'context_messages'} onChange={(e) => onNodeUpdate(selectedNode.id, { output_var: e.target.value })} />
            </>
          )}

          {selectedNode.op === '记忆' && (
            <>
              <label>操作</label><select value={selectedNode.action || 'search'} onChange={(e) => onNodeUpdate(selectedNode.id, { action: e.target.value as PipelineNode['action'] })}>
                <option value="add">写入记忆</option><option value="add_unique">去重写入</option><option value="upsert">按键更新</option><option value="search">检索</option><option value="list">列出</option><option value="delete">删除</option><option value="clear">清空</option><option value="needs_reflection">检查反思阈值</option><option value="mark_reflected">标记已反思</option>
              </select>
              <label>命名空间</label><input value={selectedNode.namespace || 'default'} onChange={(e) => onNodeUpdate(selectedNode.id, { namespace: e.target.value })} />
              <label>记忆类型</label><input value={selectedNode.memory_type || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { memory_type: e.target.value || undefined })} placeholder="episodic / semantic / skill / thought" />
              {['add', 'add_unique', 'upsert'].includes(selectedNode.action || '') && <><label>内容</label><ValueField value={selectedNode.value} onChange={(value) => onNodeUpdate(selectedNode.id, { value })} /><label>重要性（0-10）</label><input type="number" min="0" max="10" step="0.1" value={selectedNode.importance ?? 1} onChange={(e) => onNodeUpdate(selectedNode.id, { importance: Number(e.target.value) })} /></>}
              {selectedNode.action === 'add_unique' && <><label>最近去重条数</label><input type="number" min="0" value={selectedNode.retention ?? 5} onChange={(e) => onNodeUpdate(selectedNode.id, { retention: Number(e.target.value) })} /><label>去重字段</label><input value={selectedNode.dedupe_key || 'text'} onChange={(e) => onNodeUpdate(selectedNode.id, { dedupe_key: e.target.value || 'text' })} placeholder="text / metadata.event_key" /></>}
              {selectedNode.action === 'upsert' && <><label>更新键</label><input value={selectedNode.upsert_key || 'id'} onChange={(e) => onNodeUpdate(selectedNode.id, { upsert_key: e.target.value || 'id' })} placeholder="id / metadata.name" /></>}
              {selectedNode.action === 'search' && <><label>查询</label><ValueField value={selectedNode.query ?? '$ctx.request'} onChange={(query) => onNodeUpdate(selectedNode.id, { query })} /><label>返回数量</label><input type="number" min="1" value={selectedNode.top_k ?? 8} onChange={(e) => onNodeUpdate(selectedNode.id, { top_k: Math.max(1, Number(e.target.value) || 1) })} /><label>检索权重</label><JsonField value={selectedNode.weights || { relevance: 3, recency: 0.5, importance: 2 }} onChange={(weights) => onNodeUpdate(selectedNode.id, { weights })} /></>}
              {selectedNode.action === 'needs_reflection' && <><label>累计重要性阈值</label><input type="number" min="0" step="0.5" value={selectedNode.threshold ?? 20} onChange={(e) => onNodeUpdate(selectedNode.id, { threshold: Number(e.target.value) })} /></>}
              <label>输出变量</label><input value={selectedNode.output_var || 'memory_result'} onChange={(e) => onNodeUpdate(selectedNode.id, { output_var: e.target.value })} />
            </>
          )}

          {isData && (
            <>
              <label>操作</label>
              <select value={dataAction} onChange={(e) => onNodeUpdate(selectedNode.id, { action: e.target.value as PipelineNode['action'] })}>
                <optgroup label="普通数据">
                  <option value="set">保存 / 覆盖</option>
                  <option value="get">读取</option>
                  <option value="append">追加一项</option>
                  <option value="extend">追加列表</option>
                  <option value="merge">合并对象</option>
                  <option value="increment">数字递增</option>
                  <option value="range">生成整数范围</option>
                  <option value="evaluate">安全表达式计算</option>
                  <option value="slice">有界切片</option>
                  <option value="trim_words">按词数裁剪</option>
                  <option value="unique">稳定去重</option>
                  <option value="filter">筛选列表</option>
                  <option value="aggregate_fields">聚合数值字段</option>
                  <option value="topological_levels">按依赖生成并行波次</option>
                  <option value="validate_schema">按结构约束校验</option>
                  <option value="delete">删除</option>
                </optgroup>
                <optgroup label="Agent 协作（持久消息）">
                  <option value="agent_register">注册 / 更新 Agent</option>
                  <option value="agent_heartbeat">Agent 心跳</option>
                  <option value="agent_unregister">停用 Agent</option>
                  <option value="agent_list">列出 Agent</option>
                  <option value="message_publish">发布消息</option>
                  <option value="message_receive">领取消息</option>
                  <option value="message_ack">确认处理成功</option>
                  <option value="message_nack">处理失败 / 重投</option>
                  <option value="message_list">查看消息状态</option>
                </optgroup>
              </select>
              {!isBusData && <>
                <label>存储范围</label>
                <select value={selectedNode.scope || 'run'} onChange={(e) => onNodeUpdate(selectedNode.id, { scope: e.target.value as PipelineNode['scope'] })}>
                  <option value="run">本次运行</option>
                  <option value="session">当前会话</option>
                  <option value="file">Workspace JSON 文件</option>
                </select>
                {selectedNode.scope === 'file' && <><label>相对文件路径</label><input value={selectedNode.path || '.egoagent/dag-data.json'} onChange={(e) => onNodeUpdate(selectedNode.id, { path: e.target.value })} /></>}
                <label>数据路径</label>
                <input value={selectedNode.key || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { key: e.target.value })} placeholder="research.sources" />
                 {!['get', 'delete', 'increment', 'range', 'evaluate', 'slice', 'trim_words', 'unique', 'filter', 'aggregate_fields', 'topological_levels', 'validate_schema'].includes(dataAction) && <><label>值</label><ValueField value={selectedNode.value} onChange={(value) => onNodeUpdate(selectedNode.id, { value })} /></>}
                {dataAction === 'increment' && <><label>增量</label><ValueField value={selectedNode.delta ?? 1} onChange={(delta) => onNodeUpdate(selectedNode.id, { delta: Number(delta) })} /><label>初始值</label><ValueField value={selectedNode.default ?? 0} onChange={(defaultValue) => onNodeUpdate(selectedNode.id, { default: defaultValue })} /></>}
                 {dataAction === 'range' && <><label>起始整数</label><ValueField value={selectedNode.range_start ?? 0} onChange={(range_start) => onNodeUpdate(selectedNode.id, { range_start })} /><label>结束整数（不包含）</label><ValueField value={selectedNode.range_stop} onChange={(range_stop) => onNodeUpdate(selectedNode.id, { range_stop })} /><label>步长</label><ValueField value={selectedNode.range_step ?? 1} onChange={(range_step) => onNodeUpdate(selectedNode.id, { range_step })} /><label>最大条目保护</label><input type="number" min="0" value={selectedNode.max_items ?? 10000} onChange={(e) => onNodeUpdate(selectedNode.id, { max_items: Number(e.target.value) })} /></>}
                {dataAction === 'evaluate' && <><label>安全表达式</label><input value={selectedNode.expression || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { expression: e.target.value })} placeholder="ctx.depth - 1" /></>}
                {['slice', 'trim_words', 'unique'].includes(dataAction) && <><label>来源</label><ValueField value={selectedNode.source} onChange={(source) => onNodeUpdate(selectedNode.id, { source })} /></>}
                {dataAction === 'slice' && <><label>起始索引（可空）</label><ValueField value={selectedNode.start_index} onChange={(start_index) => onNodeUpdate(selectedNode.id, { start_index })} /><label>结束索引（可空）</label><ValueField value={selectedNode.end_index} onChange={(end_index) => onNodeUpdate(selectedNode.id, { end_index })} /><label>步长（可空）</label><ValueField value={selectedNode.step} onChange={(step) => onNodeUpdate(selectedNode.id, { step })} /></>}
                {dataAction === 'trim_words' && <><label>最大词数</label><ValueField value={selectedNode.max_words ?? 25000} onChange={(max_words) => onNodeUpdate(selectedNode.id, { max_words })} /></>}
                {dataAction === 'filter' && <>
                  <label>待筛选列表</label><ValueField value={selectedNode.source ?? selectedNode.value} onChange={(source) => onNodeUpdate(selectedNode.id, { source })} placeholder="$ctx.ideas" />
                  <label>筛选条件</label><input value={typeof selectedNode.condition === 'string' ? selectedNode.condition : ''} onChange={(e) => onNodeUpdate(selectedNode.id, { condition: e.target.value })} placeholder="item.novel == true" />
                  <label>当前项变量</label><input value={selectedNode.item_var || 'item'} onChange={(e) => onNodeUpdate(selectedNode.id, { item_var: e.target.value || 'item' })} />
                  <label>序号变量</label><input value={selectedNode.counter_var || 'index'} onChange={(e) => onNodeUpdate(selectedNode.id, { counter_var: e.target.value || 'index' })} />
                </>}
                {dataAction === 'aggregate_fields' && <>
                  <label>对象列表</label><ValueField value={selectedNode.source ?? selectedNode.value} onChange={(source) => onNodeUpdate(selectedNode.id, { source })} placeholder="$ctx.reviews" />
                  <label>要平均的数值字段</label><input value={(selectedNode.fields || []).join(', ')} onChange={(e) => onNodeUpdate(selectedNode.id, { fields: e.target.value.split(',').map(value => value.trim()).filter(Boolean) })} placeholder="Overall, Confidence, Soundness" />
                  <label>字段有效范围</label><JsonField value={selectedNode.limits || { Overall: [1, 10], Confidence: [1, 5] }} onChange={(limits) => onNodeUpdate(selectedNode.id, { limits: limits as Record<string, [number, number]> })} />
                  <label><input type="checkbox" checked={selectedNode.round_to_int !== false} onChange={(e) => onNodeUpdate(selectedNode.id, { round_to_int: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />平均值四舍五入为整数</label>
                </>}
                {dataAction === 'topological_levels' && <>
                  <label>带依赖的对象列表</label><ValueField value={selectedNode.source ?? selectedNode.value} onChange={(source) => onNodeUpdate(selectedNode.id, { source })} placeholder="$ctx.tasks" />
                  <label>ID 字段路径</label><input value={selectedNode.id_field || 'id'} onChange={(e) => onNodeUpdate(selectedNode.id, { id_field: e.target.value || 'id' })} />
                  <label>依赖字段路径</label><input value={selectedNode.dependency_field || 'dependencies'} onChange={(e) => onNodeUpdate(selectedNode.id, { dependency_field: e.target.value || 'dependencies' })} />
                  <label>最大条目保护</label><input type="number" min="0" value={selectedNode.max_items ?? 10000} onChange={(e) => onNodeUpdate(selectedNode.id, { max_items: Math.max(0, Number(e.target.value) || 0) })} />
                  <p style={{ fontSize: 10, color: '#888' }}>会拒绝重复 ID、未知依赖、自依赖和环；同一波次可以并行，不同波次严格按依赖顺序执行。</p>
                </>}
                {dataAction === 'validate_schema' && <>
                  <label>待校验数据</label><ValueField value={selectedNode.source ?? selectedNode.value} onChange={(source) => onNodeUpdate(selectedNode.id, { source })} placeholder="$ctx.block_result" />
                  <label>JSON Schema</label><ValueField value={selectedNode.schema ?? {}} onChange={(schema) => onNodeUpdate(selectedNode.id, { schema: schema as Record<string, unknown> })} placeholder="$ctx.task.output_schema" />
                  <p style={{ fontSize: 10, color: '#888' }}>输出 valid、errors 和原值，并通过 schema_valid / schema_invalid 显式分流。</p>
                </>}
              </>}
              {isBusData && <>
                <p style={{ fontSize: 10, color: '#94a3b8' }}>跨运行持久保存；领取采用租约，成功后必须确认，失败可重投。所有文件都限制在当前 Workspace。</p>
                <label>消息库路径</label><input value={selectedNode.path || '.egoagent/agent-bus.sqlite3'} onChange={(e) => onNodeUpdate(selectedNode.id, { path: e.target.value })} />
                {['agent_register', 'agent_heartbeat', 'agent_unregister', 'message_receive'].includes(dataAction) && <>
                  <label>Agent ID</label><ValueField value={selectedNode.agent_id} onChange={(agent_id) => onNodeUpdate(selectedNode.id, { agent_id })} placeholder="qa:${ctx._run_id}" />
                </>}
                {dataAction === 'agent_register' && <>
                  <label>Identity 名称</label><input value={typeof selectedNode.identity === 'string' ? selectedNode.identity : ''} onChange={(e) => onNodeUpdate(selectedNode.id, { identity: e.target.value })} placeholder="coder / dante / openmanus" />
                  <label>订阅主题（逗号分隔，支持 *）</label><input value={(selectedNode.subscriptions || []).join(', ')} onChange={(e) => onNodeUpdate(selectedNode.id, { subscriptions: e.target.value.split(',').map(value => value.trim()).filter(Boolean) })} placeholder="project.${ctx._run_id}.*" />
                  <label>角色元数据</label><JsonField value={selectedNode.metadata || { role: 'Worker' }} onChange={(metadata) => onNodeUpdate(selectedNode.id, { metadata })} />
                </>}
                {dataAction === 'agent_list' && <label><input type="checkbox" checked={Boolean(selectedNode.include_inactive)} onChange={(e) => onNodeUpdate(selectedNode.id, { include_inactive: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />包含已停用 Agent</label>}
                {dataAction === 'message_publish' && <>
                  <label>主题</label><ValueField value={selectedNode.topic} onChange={(topic) => onNodeUpdate(selectedNode.id, { topic })} placeholder="project.${ctx._run_id}.task" />
                  <label>发送者</label><ValueField value={selectedNode.sender} onChange={(sender) => onNodeUpdate(selectedNode.id, { sender })} placeholder="manager:${ctx._run_id}" />
                  <label>指定接收者（留空时按订阅分发）</label><input value={(selectedNode.recipients || []).join(', ')} onChange={(e) => { const recipients = e.target.value.split(',').map(value => value.trim()).filter(Boolean); onNodeUpdate(selectedNode.id, { recipients: recipients.length ? recipients : undefined }); }} placeholder="worker:${ctx._run_id}:T1" />
                  <label>消息内容</label><ValueField value={selectedNode.payload ?? selectedNode.value} onChange={(payload) => onNodeUpdate(selectedNode.id, { payload })} placeholder="$ctx.artifact" />
                  <label>消息头</label><JsonField value={selectedNode.headers || {}} onChange={(headers) => onNodeUpdate(selectedNode.id, { headers })} />
                  <label>幂等键（建议填写）</label><ValueField value={selectedNode.idempotency_key} onChange={(idempotency_key) => onNodeUpdate(selectedNode.id, { idempotency_key })} placeholder="${ctx._run_id}:artifact:T1" />
                  <label>最大处理次数</label><input type="number" min="1" value={selectedNode.max_attempts ?? 3} onChange={(e) => onNodeUpdate(selectedNode.id, { max_attempts: Math.max(1, Number(e.target.value) || 1) })} />
                  <label>延迟可领取（秒）</label><input type="number" min="0" step="0.1" value={selectedNode.delay_seconds ?? 0} onChange={(e) => onNodeUpdate(selectedNode.id, { delay_seconds: Math.max(0, Number(e.target.value) || 0) })} />
                </>}
                {dataAction === 'message_receive' && <>
                  <label>主题过滤（逗号分隔，支持 *）</label><input value={(selectedNode.topics || []).join(', ')} onChange={(e) => onNodeUpdate(selectedNode.id, { topics: e.target.value.split(',').map(value => value.trim()).filter(Boolean) })} />
                  <label>一次最多领取</label><input type="number" min="1" max="1000" value={selectedNode.limit ?? 1} onChange={(e) => onNodeUpdate(selectedNode.id, { limit: Math.max(1, Number(e.target.value) || 1) })} />
                  <label>处理租约（秒）</label><input type="number" min="0.01" step="1" value={selectedNode.lease_seconds ?? 30} onChange={(e) => onNodeUpdate(selectedNode.id, { lease_seconds: Math.max(0.01, Number(e.target.value) || 30) })} />
                </>}
                {['message_ack', 'message_nack'].includes(dataAction) && <>
                  <label>待确认消息 / receipt</label><ValueField value={selectedNode.receipts} onChange={(receipts) => onNodeUpdate(selectedNode.id, { receipts })} placeholder="$ctx.inbox" />
                  {dataAction === 'message_nack' && <><label>失败原因</label><ValueField value={selectedNode.error} onChange={(error) => onNodeUpdate(selectedNode.id, { error })} /><label>多久后重投（秒）</label><input type="number" min="0" step="0.1" value={selectedNode.delay_seconds ?? 0} onChange={(e) => onNodeUpdate(selectedNode.id, { delay_seconds: Math.max(0, Number(e.target.value) || 0) })} /></>}
                </>}
                {dataAction === 'message_list' && <>
                  <label>主题（可选）</label><ValueField value={selectedNode.topic} onChange={(topic) => onNodeUpdate(selectedNode.id, { topic })} />
                  <label>接收者（可选）</label><ValueField value={selectedNode.recipient} onChange={(recipient) => onNodeUpdate(selectedNode.id, { recipient })} />
                  <label>状态</label><select value={selectedNode.state || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { state: (e.target.value || undefined) as PipelineNode['state'] })}><option value="">全部</option><option value="pending">等待处理</option><option value="leased">处理中</option><option value="acked">已确认</option><option value="dead">死信</option></select>
                  <label>最多返回</label><input type="number" min="1" max="1000" value={selectedNode.limit ?? 100} onChange={(e) => onNodeUpdate(selectedNode.id, { limit: Math.max(1, Number(e.target.value) || 1) })} />
                </>}
              </>}
              <label>读取结果保存到（可选）</label>
              <input value={selectedNode.output_var || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { output_var: e.target.value || undefined })} placeholder="loaded_value" />
            </>
          )}

          {selectedNode.op === '循环' && (
            <>
              <label>列表数据路径</label><input value={selectedNode.list_var || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { list_var: e.target.value })} placeholder="tasks" />
              <label>当前项变量</label><input value={selectedNode.item_var || '_item'} onChange={(e) => onNodeUpdate(selectedNode.id, { item_var: e.target.value })} />
              <label>序号变量</label><input value={selectedNode.counter_var || '_i'} onChange={(e) => onNodeUpdate(selectedNode.id, { counter_var: e.target.value })} />
              <label>循环体起点</label>
              <select value={selectedNode.body_start || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { body_start: e.target.value || undefined })}><option value="">-- 选择节点 --</option>{Object.keys(config.pipeline.nodes).filter(id => id !== selectedNode.id).map(id => <option key={id} value={id}>{id}</option>)}</select>
              <label>最多循环次数</label><input type="number" min="1" value={selectedNode.max_count || 100} onChange={(e) => onNodeUpdate(selectedNode.id, { max_count: Number(e.target.value) || 100 })} />
              <label>提前结束条件（可选）</label><input value={selectedNode.break_when || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { break_when: e.target.value || undefined })} placeholder="ctx.task_success" />
              <p style={{ fontSize: 10, color: '#888' }}>满足时走 loop_break 连线；正常遍历完走 loop_done。</p>
            </>
          )}

          {selectedNode.op === '并行' && (
            <>
              <label>分支</label>
              <JsonField value={selectedNode.branches || []} onChange={(branches) => onNodeUpdate(selectedNode.id, { branches })} placeholder={'[{"name":"researcher","start":"research"}]'} rows={7} />
              <label>汇合节点</label><select value={selectedNode.join || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { join: e.target.value || undefined })}><option value="">-- 无 --</option>{Object.keys(config.pipeline.nodes).filter(id => id !== selectedNode.id).map(id => <option key={id} value={id}>{id}</option>)}</select>
              <label>最大并发数</label><input type="number" min="1" value={selectedNode.max_workers || 4} onChange={(e) => onNodeUpdate(selectedNode.id, { max_workers: Number(e.target.value) || 1 })} />
              <label><input type="checkbox" checked={selectedNode.fail_fast !== false} onChange={(e) => onNodeUpdate(selectedNode.id, { fail_fast: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />任一分支失败则失败</label>
            </>
          )}

          {selectedNode.op === '映射' && (
            <>
              <label>列表数据路径</label><ValueField value={selectedNode.source ?? `$ctx.${selectedNode.list_var || 'items'}`} onChange={(source) => onNodeUpdate(selectedNode.id, { source })} />
              <label>当前项变量</label><input value={selectedNode.item_var || '_item'} onChange={(e) => onNodeUpdate(selectedNode.id, { item_var: e.target.value })} />
              <label>序号变量</label><input value={selectedNode.counter_var || '_i'} onChange={(e) => onNodeUpdate(selectedNode.id, { counter_var: e.target.value })} />
              <label>每项执行的子图起点</label><select value={selectedNode.body_start || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { body_start: e.target.value || undefined })}><option value="">-- 选择节点 --</option>{Object.keys(config.pipeline.nodes).filter(id => id !== selectedNode.id).map(id => <option key={id} value={id}>{id}</option>)}</select>
              <label>汇合节点</label><select value={selectedNode.join || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { join: e.target.value || undefined })}><option value="">-- 无 --</option>{Object.keys(config.pipeline.nodes).filter(id => id !== selectedNode.id).map(id => <option key={id} value={id}>{id}</option>)}</select>
              <label>最大并发数</label><input type="number" min="1" value={selectedNode.max_workers || 4} onChange={(e) => onNodeUpdate(selectedNode.id, { max_workers: Number(e.target.value) || 1 })} />
              <label>最多处理项数</label><input type="number" min="0" value={selectedNode.max_count ?? 100} onChange={(e) => onNodeUpdate(selectedNode.id, { max_count: Math.max(0, Number(e.target.value) || 0) })} />
              <label>输出变量</label><input value={selectedNode.output_var || 'map_results'} onChange={(e) => onNodeUpdate(selectedNode.id, { output_var: e.target.value })} />
            </>
          )}

          {selectedNode.op === '合并' && (
            <>
              <label>来源</label><ValueField value={selectedNode.source ?? '$last.branches'} onChange={(source) => onNodeUpdate(selectedNode.id, { source })} />
              <label>合并方式</label><select value={selectedNode.strategy || 'list'} onChange={(e) => onNodeUpdate(selectedNode.id, { strategy: e.target.value as PipelineNode['strategy'] })}><option value="list">保留完整分支</option><option value="values">仅保留分支结果</option><option value="flatten">展开一层列表</option><option value="concat">拼接文本</option><option value="merge">合并对象</option><option value="first">第一项</option><option value="last">最后一项</option></select>
              <label>输出变量</label><input value={selectedNode.output_var || 'joined'} onChange={(e) => onNodeUpdate(selectedNode.id, { output_var: e.target.value })} />
            </>
          )}

          {selectedNode.op === '人工审批' && (
            <>
              <label>提示</label><textarea rows={3} value={selectedNode.prompt_text || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { prompt_text: e.target.value })} placeholder="是否允许继续执行？" />
              <label>待审数据</label><ValueField value={selectedNode.data} onChange={(data) => onNodeUpdate(selectedNode.id, { data })} placeholder="$ctx.proposed_change" />
              <label>数据名称</label><input value={selectedNode.name || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { name: e.target.value })} placeholder="代码补丁 / 部署参数 / 计划" />
              <label><input type="checkbox" checked={selectedNode.editable !== false} onChange={(e) => onNodeUpdate(selectedNode.id, { editable: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />允许审批人修改数据</label>
              <label>无人值守默认值</label><select value={String(selectedNode.default || 'rejected')} onChange={(e) => onNodeUpdate(selectedNode.id, { default: e.target.value })}><option value="rejected">拒绝</option><option value="approved">通过</option></select>
              <p style={{ fontSize: 10, color: '#888' }}>使用 approved / rejected 连线；输出包含 approved_data、rejected_data 和 review_message。</p>
            </>
          )}

          {selectedNode.op === '子流程' && (
            <>
              <label>运行方式</label><select value={selectedNode.mode === 'port_graph' ? 'port_graph' : 'subflow'} onChange={(e) => onNodeUpdate(selectedNode.id, { mode: e.target.value === 'port_graph' ? 'port_graph' : undefined })}><option value="subflow">普通子流程</option><option value="port_graph">端口事件图（重复事件 / 静态复用）</option></select>
              {selectedNode.mode !== 'port_graph' && <>
                <label>Harness</label><select value={selectedNode.harness || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { harness: e.target.value })}><option value="">-- 选择 Harness --</option>{harnessList.map(name => <option key={name} value={name}>{name}</option>)}</select>
                <label>或运行时子图</label><ValueField value={selectedNode.inline_pipeline} onChange={(inline_pipeline) => onNodeUpdate(selectedNode.id, { inline_pipeline })} placeholder="$ctx.generated_pipeline" />
                {selectedNode.inline_pipeline != null && <>
                  <label>动态图名称</label><input value={selectedNode.dynamic_name || 'dynamic_subflow'} onChange={(e) => onNodeUpdate(selectedNode.id, { dynamic_name: e.target.value })} />
                  <label>动态角色 / Identity</label><JsonField value={selectedNode.dynamic_slots || {}} onChange={(dynamic_slots) => onNodeUpdate(selectedNode.id, { dynamic_slots })} placeholder={'{"worker":"coder"}'} />
                  <label>动态 Prompt</label><JsonField value={selectedNode.dynamic_prompts || {}} onChange={(dynamic_prompts) => onNodeUpdate(selectedNode.id, { dynamic_prompts })} />
                  <label>最多节点数</label><input type="number" min="1" value={selectedNode.max_dynamic_nodes || 64} onChange={(e) => onNodeUpdate(selectedNode.id, { max_dynamic_nodes: Math.max(1, Number(e.target.value) || 1) })} />
                  <label>最多嵌套层数</label><input type="number" min="1" value={selectedNode.max_depth || 8} onChange={(e) => onNodeUpdate(selectedNode.id, { max_depth: Math.max(1, Number(e.target.value) || 1) })} />
                  <label><input type="checkbox" checked={Boolean(selectedNode.allow_unsafe)} onChange={(e) => onNodeUpdate(selectedNode.id, { allow_unsafe: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />允许动态图包含 Python / 进程 / 工作区（高风险）</label>
                </>}
                <label>初始消息</label><textarea rows={3} value={selectedNode.initial_message || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { initial_message: e.target.value })} placeholder="${ctx.current_task}" />
                <label><input type="checkbox" checked={Boolean(selectedNode.share_session)} onChange={(e) => onNodeUpdate(selectedNode.id, { share_session: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />共享父 DAG 对话（仅上下文组件需要）</label>
                <label>Component 输入端口</label>
                <MappingEditor value={selectedNode.component_inputs || {}} onChange={(component_inputs) => onNodeUpdate(selectedNode.id, { component_inputs })} mode="inputs" suggestions={variableSuggestions} expected={componentInputHints} />
                <label>Component 输出 → 父 DAG 变量</label>
                <MappingEditor value={selectedNode.component_outputs || {}} onChange={(component_outputs) => onNodeUpdate(selectedNode.id, { component_outputs: component_outputs as Record<string, string> })} mode="outputs" suggestions={variableSuggestions} expected={componentOutputHints} />
              </>}
              {selectedNode.mode === 'port_graph' && <>
                <label>端口图</label><ValueField value={selectedNode.port_graph} onChange={(port_graph) => onNodeUpdate(selectedNode.id, { port_graph })} placeholder="$ctx.compiled_port_graph" />
                <label>每个块使用的 Harness</label><select value={selectedNode.block_harness || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { block_harness: e.target.value })}><option value="">-- 选择 Harness --</option>{harnessList.map(name => <option key={name} value={name}>{name}</option>)}</select>
                <label>工作块消息模板</label><textarea rows={5} value={selectedNode.block_message || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { block_message: e.target.value })} placeholder={'任务: {block}\n已到达的端口输入: {inputs}'} />
                <label>并发工作块</label><input type="number" min="1" max="32" value={selectedNode.max_workers || 4} onChange={(e) => onNodeUpdate(selectedNode.id, { max_workers: Math.max(1, Number(e.target.value) || 1) })} />
                <label>最多执行次数</label><input type="number" min="1" value={selectedNode.max_executions || 500} onChange={(e) => onNodeUpdate(selectedNode.id, { max_executions: Math.max(1, Number(e.target.value) || 1) })} />
                <label>最多端口事件</label><input type="number" min="1" value={selectedNode.max_events || 5000} onChange={(e) => onNodeUpdate(selectedNode.id, { max_events: Math.max(1, Number(e.target.value) || 1) })} />
                <label><input type="checkbox" checked={selectedNode.fail_fast !== false} onChange={(e) => onNodeUpdate(selectedNode.id, { fail_fast: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />任一块失败时停止派发新执行</label>
                <label>敏感块无人值守默认值</label><select value={selectedNode.review_default || 'rejected'} onChange={(e) => onNodeUpdate(selectedNode.id, { review_default: e.target.value as PipelineNode['review_default'] })}><option value="rejected">拒绝</option><option value="approved">通过</option></select>
                <label>执行记录变量</label><input value={selectedNode.records_var || 'block_results'} onChange={(e) => onNodeUpdate(selectedNode.id, { records_var: e.target.value })} />
                <label>端口事件变量</label><input value={selectedNode.events_var || 'port_events'} onChange={(e) => onNodeUpdate(selectedNode.id, { events_var: e.target.value })} />
                <label>运行快照文件</label><input value={selectedNode.state_path || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { state_path: e.target.value })} placeholder=".egoagent/port-graphs/${ctx._run_id}.json" />
                <label><input type="checkbox" checked={selectedNode.resume_state !== false} onChange={(e) => onNodeUpdate(selectedNode.id, { resume_state: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />中断后从端口级快照继续</label>
                <p style={{ fontSize: 10, color: '#888' }}>动态图仍由“子流程”承载：动态端口每次事件创建/补全一次执行，静态端口值会自动供后续执行复用；循环受执行数和事件数双重限制。</p>
              </>}
              <label>Identity 映射</label><JsonField value={selectedNode.identity_map || {}} onChange={(identity_map) => onNodeUpdate(selectedNode.id, { identity_map })} placeholder={'{"worker":"dante"}'} />
              <label>继承父流程 Agent 槽位</label><JsonField value={selectedNode.agent_map || {}} onChange={(agent_map) => onNodeUpdate(selectedNode.id, { agent_map })} placeholder={'{"coder":"editor"}'} />
              <label>结果形式</label><select value={selectedNode.result_mode || 'text'} onChange={(e) => onNodeUpdate(selectedNode.id, { result_mode: e.target.value as PipelineNode['result_mode'] })}><option value="text">最后文本</option><option value="result">最终结果（保留类型）</option><option value="data">完整运行数据</option><option value="messages">消息列表</option></select>
              <label>输出变量</label><input value={selectedNode.output_var || (selectedNode.mode === 'port_graph' ? 'port_graph_result' : '_sub_result')} onChange={(e) => onNodeUpdate(selectedNode.id, { output_var: e.target.value })} />
            </>
          )}

          {selectedNode.op === '检查点' && (
            <>
              <label>操作</label><select value={selectedNode.action || 'save'} onChange={(e) => onNodeUpdate(selectedNode.id, { action: e.target.value as PipelineNode['action'] })}><option value="save">保存运行状态</option><option value="load">恢复运行状态</option><option value="replay">读取事件日志</option></select>
              {selectedNode.action !== 'replay' && <><label>标签或文件</label><input value={(selectedNode.action === 'load' ? selectedNode.path : selectedNode.label) || ''} onChange={(e) => onNodeUpdate(selectedNode.id, selectedNode.action === 'load' ? { path: e.target.value } : { label: e.target.value })} placeholder={selectedNode.action === 'load' ? '留空读取最新' : 'before-edit'} /></>}
              {selectedNode.action === 'replay' && <>
                <label>JSONL 事件文件</label><ValueField value={selectedNode.path ?? '$ctx._event_log_path'} onChange={(path) => onNodeUpdate(selectedNode.id, { path: typeof path === 'string' ? path : String(path ?? '') })} />
                <label>从序号开始</label><input type="number" min="0" value={selectedNode.from_sequence ?? 0} onChange={(e) => onNodeUpdate(selectedNode.id, { from_sequence: Math.max(0, Number(e.target.value) || 0) })} />
                <label>只读事件类型（空为全部）</label><JsonField value={selectedNode.event_types || []} onChange={(event_types) => onNodeUpdate(selectedNode.id, { event_types })} placeholder={'["tool", "process", "output"]'} />
                <label>输出变量</label><input value={selectedNode.output_var || 'replayed_events'} onChange={(e) => onNodeUpdate(selectedNode.id, { output_var: e.target.value })} />
              </>}
            </>
          )}

          {(['输出', '结束'].includes(selectedNode.op)) && (
            <>
              <label>输出值</label><ValueField value={selectedNode.value} onChange={(value) => onNodeUpdate(selectedNode.id, { value })} placeholder="$ctx.final_answer" />
              <label><input type="checkbox" checked={Boolean(selectedNode.record)} onChange={(e) => onNodeUpdate(selectedNode.id, { record: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />写入对话记录</label>
            </>
          )}

          {PYTHON_OPS.includes(selectedNode.op) && (
            <>
              <label>脚本名称</label>
              <input
                value={selectedNode.script || ''}
                onChange={(e) => onNodeUpdate(selectedNode.id, { script: e.target.value })}
                placeholder="format_fixer (不含 .py)"
              />
              <label>输入变量 (逗号分隔)</label>
              <input
                value={(selectedNode.input_vars || []).join(', ')}
                onChange={(e) => onNodeUpdate(selectedNode.id, {
                  input_vars: e.target.value.split(',').map(s => s.trim()).filter(Boolean)
                })}
                placeholder="response, question"
              />
              <label>输出变量 (逗号分隔)</label>
              <input
                value={(selectedNode.output_vars || []).join(', ')}
                onChange={(e) => onNodeUpdate(selectedNode.id, {
                  output_vars: e.target.value.split(',').map(s => s.trim()).filter(Boolean)
                })}
                placeholder="response"
              />
              <p style={{ fontSize: 10, color: '#f59e0b' }}>高级逃生口：常见条件、数据和流程逻辑优先使用原生节点。</p>
              <label>脚本代码</label>
              <ScriptEditor
                harnessName={config.name}
                scriptName={selectedNode.script || ''}
              />
            </>
          )}

          {MODEL_OPS.includes(selectedNode.op) && (
            <>
              <label>输入变量 (逗号分隔)</label>
              <input
                value={(selectedNode.input_vars || []).join(', ')}
                onChange={(e) => onNodeUpdate(selectedNode.id, {
                  input_vars: e.target.value.split(',').map(s => s.trim()).filter(Boolean)
                })}
                placeholder="response, question"
              />
              <label>输出变量名</label>
              <input
                value={selectedNode.output_var || ''}
                onChange={(e) => onNodeUpdate(selectedNode.id, { output_var: e.target.value })}
                placeholder="response"
              />
              <label>解析方式</label>
              <select
                value={selectedNode.parse_as || 'text'}
                onChange={(e) => onNodeUpdate(selectedNode.id, { parse_as: e.target.value as PipelineNode['parse_as'] })}
              >
                <option value="text">text (纯文本)</option>
                <option value="json">json (严格解析)</option>
                <option value="json_object">json_object (从回复中提取对象)</option>
              </select>
              {selectedNode.parse_as === 'json_object' && <>
                <label>解析失败时的保守值（可选）</label>
                <JsonField value={selectedNode.json_fallback || {}} onChange={(json_fallback) => onNodeUpdate(selectedNode.id, { json_fallback })} placeholder={'{"complete":false,"score":0,"missing":"Judge verdict could not be parsed."}'} />
              </>}
            </>
          )}

          <details style={{ marginTop: 12 }}>
            <summary style={{ cursor: 'pointer', fontSize: 12, color: '#9ca3af' }}>数据端口与可靠性</summary>
            <label>输入端口</label>
            <MappingEditor value={selectedNode.inputs || {}} onChange={(inputs) => onNodeUpdate(selectedNode.id, { inputs })} mode="inputs" suggestions={variableSuggestions} expected={nodeContract?.inputs} />
            <label>输出端口 → 全局上下文</label>
            <MappingEditor value={selectedNode.outputs || {}} onChange={(outputs) => onNodeUpdate(selectedNode.id, { outputs })} mode="outputs" suggestions={variableSuggestions} expected={nodeContract?.outputs} />
            <label>超时（秒，留空表示不限）</label>
            <input type="number" min="0" value={selectedNode.timeout_seconds || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { timeout_seconds: Number(e.target.value) || undefined })} />
            <label>最多尝试次数</label>
            <input type="number" min="1" value={maxAttempts} onChange={(e) => onNodeUpdate(selectedNode.id, { retry: { ...retry, max_attempts: Math.max(1, Number(e.target.value) || 1) } })} />
            <label>重试间隔（秒）</label>
            <input type="number" min="0" step="0.1" value={retry.delay_seconds || 0} onChange={(e) => onNodeUpdate(selectedNode.id, { retry: { ...retry, max_attempts: maxAttempts, delay_seconds: Number(e.target.value) || 0 } })} />
            <label>失败后跳转</label>
            <select value={selectedNode.error_to || ''} onChange={(e) => onNodeUpdate(selectedNode.id, { error_to: e.target.value || undefined })}><option value="">使用 error 连线 / 抛出错误</option>{Object.keys(config.pipeline.nodes).filter(id => id !== selectedNode.id).map(id => <option key={id} value={id}>{id}</option>)}</select>
            <label><input type="checkbox" checked={Boolean(selectedNode.checkpoint)} onChange={(e) => onNodeUpdate(selectedNode.id, { checkpoint: e.target.checked })} style={{ width: 'auto', marginRight: 6 }} />节点成功后自动检查点</label>
            <label>结构化输出 Schema（可选）</label>
            <SchemaEditor value={selectedNode.output_schema || {}} onChange={(output_schema) => onNodeUpdate(selectedNode.id, { output_schema })} />
          </details>

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
            {selectedEdge.source}.{selectedEdge.sourcePort} → {selectedEdge.target}.{selectedEdge.targetPort}
          </p>
          <div className={`edge-kind-badge ${selectedEdge.kind}`}>{selectedEdge.kind === 'data' ? '数据连接 · 自动写入目标 inputs' : '控制连接 · 根据事件选择下一节点'}</div>
          {selectedEdge.kind === 'control' && <>
            <label>事件 / 条件</label>
            <input
              list="edge-conditions"
              value={selectedEdge.condition}
              onChange={(e) => onEdgeUpdate(selectedEdge.id, { condition: e.target.value as EdgeCondition })}
              placeholder="default 或 expr: ctx.score > 0.8"
            />
            <datalist id="edge-conditions">
              <option value="default" /><option value="input" /><option value="true" /><option value="false" />
              <option value="has_tool_calls" /><option value="no_tool_calls" /><option value="has_text" />
              <option value="loop_continue" /><option value="loop_done" /><option value="approved" />
              <option value="rejected" /><option value="error" /><option value="timeout" />
              <option value="retry_exhausted" /><option value="parallel_done" />
            </datalist>
          </>}
          <label>连线路径</label>
          <select value={selectedEdge.route} onChange={(e) => onEdgeUpdate(selectedEdge.id, { route: e.target.value })}>
            <option value="bezier">平滑贝塞尔（推荐）</option>
            <option value="straight">直线</option>
          </select>
          <p className="edge-routing-help">
            端点固定在命名 socket 上。选中连线后使用画布上的“＋转接点”，再拖动小菱形绕开节点；这与 Blender 的 Reroute 节点一致，不支持双击任意修改曲线。选中转接点按 Delete 删除。
          </p>
          <label>曲线弧度</label>
          <input type="range" min="0.2" max="1.2" step="0.05" value={selectedEdge.curvature} onChange={(e) => onEdgeUpdate(selectedEdge.id, { curvature: Number(e.target.value) })} />
          <div className="edge-route-summary">
            <span>{selectedEdge.reroutes.length ? `${selectedEdge.reroutes.length} 个 Bezier 控制点` : '直接 Bezier 连线'}</span>
            {selectedEdge.reroutes.length > 0 && <button type="button" className="btn btn-secondary btn-sm" onClick={() => onEdgeUpdate(selectedEdge.id, { reroutes: [], channelOffset: 0 })}>清除控制点</button>}
          </div>
          <p className="edge-routing-help">双击或右键连线可在鼠标位置精确插入控制点。拖动圆点会平滑调整整条线；Shift+拖动只改当前点；Alt+拖动让控制点沿原曲线滑动。拖动方形手柄旋转切线，Shift 可禁止其他控制点联动。</p>
          <label>条件标签偏移</label>
          <input type="range" min="-120" max="120" step="5" value={selectedEdge.labelOffset} onChange={(e) => onEdgeUpdate(selectedEdge.id, { labelOffset: Number(e.target.value) })} />
          {selectedEdge.kind === 'control' && <p style={{ fontSize: 10, color: '#888' }}>高级条件可写 expr: ctx.score &gt;= 0.8，运行时使用安全表达式，不执行 Python。</p>}
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
          aria-label="Flow 名称"
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

        <label>运行模式</label>
        <select value={config.pipeline.mode || 'agent'} onChange={(e) => onConfigChange({ ...config, pipeline: { ...config.pipeline, mode: e.target.value } })}>
          <option value="agent">Agent：可按权限调用工具</option>
          <option value="ask">Ask：只读分析</option>
          <option value="plan">Plan：只读规划</option>
          <option value="chat">Chat：禁止写入和进程</option>
          <option value="evaluate">Evaluate：隔离评测</option>
          <option value="evolve">Evolve：允许受控自进化</option>
        </select>

        <details className="panel-disclosure" style={{ margin: '8px 0' }}>
          <summary><span>初始上下文</span><small>{Object.keys(config.pipeline.context || {}).length}</small></summary>
          <MappingEditor value={config.pipeline.context || {}} onChange={(context) => onConfigChange({ ...config, pipeline: { ...config.pipeline, context } })} mode="context" suggestions={variableSuggestions} title="启动时写入 $ctx" />
          <p className="dag-editor-help">后续节点可直接选择 <code>$ctx.变量名</code>；端口下拉会自动收集这些变量。</p>
        </details>

        <details style={{ margin: '8px 0' }} open={Boolean(config.component)}>
          <summary style={{ cursor: 'pointer', fontSize: 12, color: '#9ca3af' }}>SubDAG 组件接口</summary>
          <label><input type="checkbox" checked={Boolean(config.component)} onChange={(e) => onConfigChange({
            ...config,
            component: e.target.checked ? {
              name: config.name,
              display_name: config.name,
              category: 'General',
              description: config.description,
              icon: '◫',
              share_session: false,
              inputs: {},
              outputs: {},
            } : undefined,
          })} style={{ width: 'auto', marginRight: 6 }} />可拖入其他 DAG 复用</label>
          {config.component && <>
            <label>组件显示名称</label><input value={config.component.display_name || ''} onChange={(e) => onConfigChange({ ...config, component: { ...config.component!, display_name: e.target.value } })} />
            <label>分类</label><input value={config.component.category || 'General'} onChange={(e) => onConfigChange({ ...config, component: { ...config.component!, category: e.target.value } })} placeholder="Conversation / Evolution / Research" />
            <label>图标</label><input value={config.component.icon || '◫'} onChange={(e) => onConfigChange({ ...config, component: { ...config.component!, icon: e.target.value } })} />
            <label>组件说明</label><textarea rows={3} value={config.component.description || ''} onChange={(e) => onConfigChange({ ...config, component: { ...config.component!, description: e.target.value } })} />
            <label><input type="checkbox" checked={Boolean(config.component.share_session)} onChange={(e) => onConfigChange({ ...config, component: { ...config.component!, share_session: e.target.checked } })} style={{ width: 'auto', marginRight: 6 }} />默认共享父对话（仅 Conversation / Evolution 效果需要）</label>
            <label>输入端口契约</label><ComponentPortsEditor direction="inputs" value={config.component.inputs} onChange={(inputs) => onConfigChange({ ...config, component: { ...config.component!, inputs } })} portTypes={dagContracts?.port_types} suggestions={variableSuggestions} />
            <label>输出端口契约</label><ComponentPortsEditor direction="outputs" value={config.component.outputs} onChange={(outputs) => onConfigChange({ ...config, component: { ...config.component!, outputs } })} portTypes={dagContracts?.port_types} suggestions={variableSuggestions} />
            <p style={{ fontSize: 10, color: '#888' }}>保存后会出现在左侧“SubDAG 组件”中；拖入时自动带上默认输入、输出映射和共享对话声明。</p>
          </>}
        </details>

        <label>最大步数</label>
        <input
          type="number"
          value={config.pipeline.max_steps}
          onChange={(e) => onConfigChange({
            ...config,
            pipeline: { ...config.pipeline, max_steps: parseInt(e.target.value) || 100 }
          })}
        />

        <label>最多节点执行次数（含并行与子路径）</label>
        <input type="number" min="1" value={config.pipeline.max_node_steps ?? ''} onChange={(e) => onConfigChange({ ...config, pipeline: { ...config.pipeline, max_node_steps: Number(e.target.value) || undefined } })} placeholder="自动：max_steps × 10" />

        <label>整条流程超时（秒）</label>
        <input
          type="number"
          min="0"
          value={config.pipeline.timeout_seconds || ''}
          onChange={(e) => onConfigChange({
            ...config,
            pipeline: { ...config.pipeline, timeout_seconds: Number(e.target.value) || undefined }
          })}
          placeholder="不限"
        />

        <details style={{ margin: '8px 0' }}>
          <summary style={{ cursor: 'pointer', fontSize: 12, color: '#9ca3af' }}>运行预算</summary>
          <label>最多模型调用</label>
          <input type="number" min="0" value={config.pipeline.budget?.max_model_calls ?? ''} onChange={(e) => onConfigChange({ ...config, pipeline: { ...config.pipeline, budget: { ...config.pipeline.budget, max_model_calls: Number(e.target.value) || undefined } } })} placeholder="不限" />
          <label>最多工具调用</label>
          <input type="number" min="0" value={config.pipeline.budget?.max_tool_calls ?? ''} onChange={(e) => onConfigChange({ ...config, pipeline: { ...config.pipeline, budget: { ...config.pipeline.budget, max_tool_calls: Number(e.target.value) || undefined } } })} placeholder="不限" />
          <label>最多进程调用</label>
          <input type="number" min="0" value={config.pipeline.budget?.max_process_calls ?? ''} onChange={(e) => onConfigChange({ ...config, pipeline: { ...config.pipeline, budget: { ...config.pipeline.budget, max_process_calls: Number(e.target.value) || undefined } } })} placeholder="不限" />
          <label>估算 Token 上限</label>
          <input type="number" min="0" value={config.pipeline.budget?.max_tokens ?? ''} onChange={(e) => onConfigChange({ ...config, pipeline: { ...config.pipeline, budget: { ...config.pipeline.budget, max_tokens: Number(e.target.value) || undefined } } })} placeholder="不限" />
          <label>估算费用上限</label>
          <input type="number" min="0" step="0.01" value={config.pipeline.budget?.max_cost ?? ''} onChange={(e) => onConfigChange({ ...config, pipeline: { ...config.pipeline, budget: { ...config.pipeline.budget, max_cost: Number(e.target.value) || undefined } } })} placeholder="不限" />
          <label>预算计时上限（秒）</label>
          <input type="number" min="0" value={config.pipeline.budget?.max_elapsed_seconds ?? ''} onChange={(e) => onConfigChange({ ...config, pipeline: { ...config.pipeline, budget: { ...config.pipeline.budget, max_elapsed_seconds: Number(e.target.value) || undefined } } })} placeholder="不限" />
          <label>预算 / 超时后安全收尾节点</label>
          <select value={config.pipeline.budget_exceeded_to || config.pipeline.limit_exceeded_to || ''} onChange={(e) => onConfigChange({ ...config, pipeline: { ...config.pipeline, budget_exceeded_to: e.target.value || undefined, limit_exceeded_to: undefined } })}><option value="">直接报错终止</option>{Object.keys(config.pipeline.nodes).map(id => <option key={id} value={id}>{id}</option>)}</select>
          <label>安全收尾最多节点数</label>
          <input type="number" min="1" value={config.pipeline.limit_finalizer_max_steps ?? 20} onChange={(e) => onConfigChange({ ...config, pipeline: { ...config.pipeline, limit_finalizer_max_steps: Math.max(1, Number(e.target.value) || 1) } })} />
          <p style={{ fontSize: 10, color: '#888' }}>收尾阶段仅允许条件、数据、只读/回滚工作区、审批、检查点和输出节点，不能继续调用模型或工具。</p>
          <label>输入价格 / 百万 Token</label>
          <input type="number" min="0" step="0.01" value={config.pipeline.budget?.prices?.input_per_million ?? ''} onChange={(e) => onConfigChange({ ...config, pipeline: { ...config.pipeline, budget: { ...config.pipeline.budget, prices: { ...config.pipeline.budget?.prices, input_per_million: Number(e.target.value) || 0 } } } })} />
          <label>输出价格 / 百万 Token</label>
          <input type="number" min="0" step="0.01" value={config.pipeline.budget?.prices?.output_per_million ?? ''} onChange={(e) => onConfigChange({ ...config, pipeline: { ...config.pipeline, budget: { ...config.pipeline.budget, prices: { ...config.pipeline.budget?.prices, output_per_million: Number(e.target.value) || 0 } } } })} />
        </details>

        <details className="panel-disclosure" style={{ margin: '8px 0' }}>
          <summary><span>状态、回放与检查点</span><small>可选</small></summary>
          <label className="dag-inline-check"><input type="checkbox" checked={Boolean(config.pipeline.event_log)} onChange={(e) => onConfigChange({ ...config, pipeline: { ...config.pipeline, event_log: e.target.checked ? { path: '.egoagent/events/{run_id}.jsonl' } : false } })} />记录可回放事件流</label>
          {Boolean(config.pipeline.event_log) && <><label>事件日志路径</label><input value={typeof config.pipeline.event_log === 'object' ? config.pipeline.event_log.path || '' : typeof config.pipeline.event_log === 'string' ? config.pipeline.event_log : '.egoagent/events/{run_id}.jsonl'} onChange={(e) => onConfigChange({ ...config, pipeline: { ...config.pipeline, event_log: { path: e.target.value } } })} placeholder=".egoagent/events/{run_id}.jsonl" /></>}
          <label className="dag-inline-check"><input type="checkbox" checked={Boolean(config.pipeline.auto_checkpoint)} onChange={(e) => onConfigChange({ ...config, pipeline: { ...config.pipeline, auto_checkpoint: e.target.checked } })} />副作用节点前后自动创建检查点</label>
          <label>检查点目录</label><input value={config.pipeline.checkpoint_dir || ''} onChange={(e) => onConfigChange({ ...config, pipeline: { ...config.pipeline, checkpoint_dir: e.target.value || undefined } })} placeholder=".egoagent/checkpoints" />
          <label>允许读取的密钥名称</label><StringListEditor value={config.pipeline.secret_names || []} onChange={(secret_names) => onConfigChange({ ...config, pipeline: { ...config.pipeline, secret_names } })} placeholder="例如 DEEPSEEK_API_KEY" />
        </details>

        <details className="panel-disclosure" style={{ margin: '8px 0' }}>
          <summary><span>Harness 权限</span><small>{Object.keys(config.pipeline.permissions?.defaults || {}).length}</small></summary>
          <PermissionEditor value={config.pipeline.permissions || {}} onChange={(permissions) => onConfigChange({ ...config, pipeline: { ...config.pipeline, permissions } })} />
          <p className="dag-editor-help">Workspace 的安全设置仍是最低边界；Harness 只能进一步收紧，不能绕过用户的沙箱与审批设置。</p>
        </details>

        <details className="panel-disclosure" style={{ margin: '8px 0' }}>
          <summary><span>并发资源与合并策略</span><small>高级</small></summary>
          <label>资源上限</label><MappingEditor value={config.pipeline.resource_limits || {}} onChange={(resource_limits) => onConfigChange({ ...config, pipeline: { ...config.pipeline, resource_limits: resource_limits as Record<string, number> } })} mode="context" title="例如 gpu = 1" />
          <label>并行结果 Reducer</label><MappingEditor value={config.pipeline.reducers || {}} onChange={(reducers) => onConfigChange({ ...config, pipeline: { ...config.pipeline, reducers } })} mode="context" title="变量 → replace / append / merge" />
        </details>

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
      <details className="panel-section panel-disclosure">
        <summary><span>Agent Slots</span><small>{Object.keys(config.slots).length}</small></summary>
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
      </details>

      {/* Identity 拖放区 */}
      <details className="panel-section panel-disclosure">
        <summary><span>Identity 绑定</span><small>{identityList.length}</small></summary>
        <p style={{ fontSize: 11, color: '#888', marginBottom: 8 }}>
          从 Identity 管理页拖放 identity 到上方 slot 即可绑定
        </p>
        <div className="identity-picker-toolbar">
          <input
            type="search"
            value={identityQuery}
            onChange={(event) => { setIdentityQuery(event.target.value); setShowAllIdentities(false); }}
            placeholder="搜索 Identity…"
            aria-label="搜索 Identity"
          />
          <button className="btn btn-secondary btn-sm" onClick={onRefreshIdentities} title="刷新 Identity">↻</button>
        </div>
        <div className="identity-chip-list">
          {visibleIdentities.map((id) => (
            <span
              key={id}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData('application/egoagent-identity', id);
                e.dataTransfer.effectAllowed = 'link';
              }}
              title={`拖放到 slot 绑定 ${id}`}
            >
              {id}
            </span>
          ))}
          {filteredIdentities.length === 0 && <em className="identity-picker-empty">没有匹配的 Identity</em>}
        </div>
        {filteredIdentities.length > 10 && <button className="identity-picker-more" onClick={() => setShowAllIdentities((value) => !value)}>
          {showAllIdentities ? '收起' : `再显示 ${filteredIdentities.length - 10} 个`}
        </button>}
      </details>

      {/* Prompts */}
      <details className="panel-section panel-disclosure">
        <summary><span>Prompts</span><small>{Object.keys(config.prompts).length}</small></summary>
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
      </details>
    </div>
  );
}
