import { useEffect, useId, useState } from 'react';
import type { ComponentPortSpec, HarnessConfig, PipelinePermissions } from '../types';

export type DagPortSpec = { type?: string; description?: string };
export type DagNodeContract = {
  description?: string;
  inputs?: Record<string, DagPortSpec>;
  outputs?: Record<string, DagPortSpec>;
  events?: string[];
  handler?: string;
  side_effecting?: boolean;
  aliases?: string[];
  editor?: {
    category?: string;
    icon?: string;
    css_class?: string;
    color?: string;
    defaults?: Record<string, unknown>;
    palette?: boolean;
  };
};
export type DagContractCatalog = {
  version?: string;
  port_types?: string[];
  references?: string[];
  nodes?: Record<string, DagNodeContract>;
};

const VALUE_TYPES = ['reference', 'string', 'number', 'boolean', 'null', 'json'] as const;
const SCHEMA_TYPES = ['any', 'object', 'array', 'string', 'integer', 'number', 'boolean', 'null'] as const;

function valueKind(value: unknown): typeof VALUE_TYPES[number] {
  if (value === null) return 'null';
  if (typeof value === 'string') return value.startsWith('$') ? 'reference' : 'string';
  if (typeof value === 'number') return 'number';
  if (typeof value === 'boolean') return 'boolean';
  return 'json';
}

function replacementFor(kind: typeof VALUE_TYPES[number]): unknown {
  if (kind === 'reference') return '$ctx.';
  if (kind === 'string') return '';
  if (kind === 'number') return 0;
  if (kind === 'boolean') return false;
  if (kind === 'null') return null;
  return {};
}

export function JsonTextEditor({ value, onChange, rows = 6 }: { value: unknown; onChange: (value: any) => void; rows?: number }) {
  const [text, setText] = useState(() => JSON.stringify(value ?? {}, null, 2));
  const [error, setError] = useState('');
  useEffect(() => { setText(JSON.stringify(value ?? {}, null, 2)); setError(''); }, [value]);
  const apply = () => {
    try { onChange(JSON.parse(text || '{}')); setError(''); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'JSON 格式错误'); }
  };
  return <div className="dag-json-editor">
    <textarea value={text} rows={rows} spellCheck={false} onChange={(event) => setText(event.target.value)} onBlur={apply} />
    {error && <span className="dag-field-error">{error}</span>}
  </div>;
}

export function collectVariableSuggestions(config: HarnessConfig): string[] {
  const values = new Set<string>([
    '$ctx', '$last', '$last.text', '$last.value', '$last.structured', '$last.tool_calls',
    '$session.messages', '$session.full_messages', '$session.state', '$stats', '$input',
  ]);
  Object.keys(config.pipeline.context || {}).forEach((name) => values.add(`$ctx.${name}`));
  Object.entries(config.pipeline.nodes).forEach(([nodeId, node]) => {
    values.add(`$node.${nodeId}`);
    ['text', 'value', 'structured', 'tool_calls', 'data', 'component_outputs', 'artifacts'].forEach((port) => values.add(`$node.${nodeId}.${port}`));
    Object.keys(node.outputs || {}).forEach((port) => values.add(`$node.${nodeId}.${port}`));
    Object.values(node.outputs || {}).forEach((target) => values.add(`$ctx.${String(target).replace(/^\$ctx\./, '')}`));
    if (node.output_var) values.add(`$ctx.${node.output_var}`);
  });
  return [...values].sort();
}

function SuggestionList({ id, values }: { id: string; values: string[] }) {
  return <datalist id={id}>{values.map((value) => <option key={value} value={value} />)}</datalist>;
}

export function TypedValueEditor({ value, onChange, suggestions = [] }: { value: unknown; onChange: (value: unknown) => void; suggestions?: string[] }) {
  const listId = useId().replace(/:/g, '');
  const kind = valueKind(value);
  return <div className="dag-typed-value">
    <select value={kind} aria-label="值类型" onChange={(event) => onChange(replacementFor(event.target.value as typeof VALUE_TYPES[number]))}>
      <option value="reference">变量</option><option value="string">文本</option><option value="number">数字</option>
      <option value="boolean">布尔</option><option value="null">空值</option><option value="json">对象/列表</option>
    </select>
    {(kind === 'reference' || kind === 'string') && <>
      <input list={kind === 'reference' ? listId : undefined} value={String(value ?? '')} onChange={(event) => onChange(event.target.value)} placeholder={kind === 'reference' ? '$ctx.request' : '文本'} />
      {kind === 'reference' && <SuggestionList id={listId} values={suggestions} />}
    </>}
    {kind === 'number' && <input type="number" value={Number(value ?? 0)} onChange={(event) => onChange(Number(event.target.value))} />}
    {kind === 'boolean' && <select value={String(Boolean(value))} onChange={(event) => onChange(event.target.value === 'true')}><option value="true">true</option><option value="false">false</option></select>}
    {kind === 'null' && <span className="dag-null-value">null</span>}
    {kind === 'json' && <JsonTextEditor value={value} onChange={onChange} rows={3} />}
  </div>;
}

function renamed<T>(source: Record<string, T>, oldName: string, nextName: string): Record<string, T> {
  const result: Record<string, T> = {};
  Object.entries(source).forEach(([name, value]) => { result[name === oldName ? nextName : name] = value; });
  return result;
}

export function MappingEditor({
  value, onChange, mode, suggestions = [], expected = {}, title,
}: {
  value: Record<string, any>;
  onChange: (value: Record<string, any>) => void;
  mode: 'inputs' | 'outputs' | 'context';
  suggestions?: string[];
  expected?: Record<string, DagPortSpec>;
  title?: string;
}) {
  const [advanced, setAdvanced] = useState(false);
  const entries = Object.entries(value || {});
  const missing = Object.keys(expected).filter((name) => !(name in (value || {})));
  const add = (preferred?: string) => {
    let name = preferred || (mode === 'context' ? 'variable' : 'port');
    let index = 2;
    while (name in value) name = `${preferred || (mode === 'context' ? 'variable' : 'port')}_${index++}`;
    onChange({ ...value, [name]: mode === 'outputs' ? name : '' });
  };
  return <div className="dag-structured-editor">
    {title && <div className="dag-editor-title"><span>{title}</span><small>{entries.length}</small></div>}
    {missing.length > 0 && <div className="dag-suggestions"><span>推荐：</span>{missing.map((name) => <button key={name} type="button" onClick={() => add(name)}>＋ {name}<small>{expected[name]?.type || 'any'}</small></button>)}</div>}
    {!advanced && entries.map(([name, item]) => <div className="dag-map-row" key={name}>
      <input className="dag-port-name" value={name} onChange={(event) => onChange(renamed(value, name, event.target.value))} placeholder="端口名" />
      <span className="dag-map-arrow">{mode === 'outputs' ? '→ $ctx' : mode === 'inputs' ? '←' : '='}</span>
      {mode === 'outputs'
        ? <input value={String(item ?? '')} onChange={(event) => onChange({ ...value, [name]: event.target.value.replace(/^\$ctx\./, '') })} placeholder="result.answer" />
        : <TypedValueEditor value={item} onChange={(next) => onChange({ ...value, [name]: next })} suggestions={suggestions} />}
      <button type="button" className="dag-row-remove" onClick={() => { const next = { ...value }; delete next[name]; onChange(next); }}>×</button>
    </div>)}
    {!advanced && entries.length === 0 && <div className="dag-empty-editor">还没有端口。可使用推荐项或手动添加。</div>}
    {advanced && <JsonTextEditor value={value} onChange={onChange} rows={7} />}
    <div className="dag-editor-actions"><button type="button" onClick={() => add()}>＋ 添加</button><button type="button" onClick={() => setAdvanced((current) => !current)}>{advanced ? '返回表单' : '高级 JSON'}</button></div>
  </div>;
}

export function SchemaEditor({ value, onChange }: { value: Record<string, any>; onChange: (value: Record<string, any>) => void }) {
  const [advanced, setAdvanced] = useState(false);
  const rootType = String(value?.type || (value?.properties ? 'object' : 'object'));
  const properties = (value?.properties && typeof value.properties === 'object') ? value.properties as Record<string, Record<string, any>> : {};
  const required = new Set(Array.isArray(value?.required) ? value.required.map(String) : []);
  const setRootType = (type: string) => onChange(type === 'any' ? {} : { ...value, type, ...(type === 'object' ? { properties } : {}) });
  const updateProperty = (name: string, spec: Record<string, any>) => onChange({ ...value, type: 'object', properties: { ...properties, [name]: spec } });
  const renameProperty = (name: string, nextName: string) => {
    const nextRequired = [...required].map((item) => item === name ? nextName : item);
    onChange({ ...value, type: 'object', properties: renamed(properties, name, nextName), required: nextRequired });
  };
  const addProperty = () => {
    let name = 'field'; let index = 2;
    while (name in properties) name = `field_${index++}`;
    updateProperty(name, { type: 'string', description: '' });
  };
  return <div className="dag-structured-editor">
    {!advanced && <>
      <div className="dag-schema-root"><label>结果类型</label><select value={rootType} onChange={(event) => setRootType(event.target.value)}>{SCHEMA_TYPES.map((type) => <option key={type}>{type}</option>)}</select></div>
      {rootType === 'object' && Object.entries(properties).map(([name, spec]) => <div className="dag-schema-row" key={name}>
        <input value={name} onChange={(event) => renameProperty(name, event.target.value)} placeholder="字段" />
        <select value={String(spec.type || 'any')} onChange={(event) => updateProperty(name, { ...spec, ...(event.target.value === 'any' ? { type: undefined } : { type: event.target.value }) })}>{SCHEMA_TYPES.map((type) => <option key={type}>{type}</option>)}</select>
        <label className="dag-inline-check"><input type="checkbox" checked={required.has(name)} onChange={(event) => { const next = new Set(required); event.target.checked ? next.add(name) : next.delete(name); onChange({ ...value, type: 'object', properties, required: [...next] }); }} />必填</label>
        <input value={String(spec.description || '')} onChange={(event) => updateProperty(name, { ...spec, description: event.target.value })} placeholder="说明" />
        <button type="button" className="dag-row-remove" onClick={() => { const next = { ...properties }; delete next[name]; onChange({ ...value, properties: next, required: [...required].filter((item) => item !== name) }); }}>×</button>
      </div>)}
      {rootType === 'object' && <button type="button" className="dag-add-row" onClick={addProperty}>＋ 添加字段</button>}
    </>}
    {advanced && <JsonTextEditor value={value} onChange={onChange} rows={9} />}
    <div className="dag-editor-actions"><button type="button" onClick={() => setAdvanced((current) => !current)}>{advanced ? '返回表单' : '高级 JSON Schema'}</button></div>
  </div>;
}

export function ComponentPortsEditor({
  direction, value, onChange, portTypes = [], suggestions = [],
}: {
  direction: 'inputs' | 'outputs';
  value: Record<string, ComponentPortSpec>;
  onChange: (value: Record<string, ComponentPortSpec>) => void;
  portTypes?: string[];
  suggestions?: string[];
}) {
  const [advanced, setAdvanced] = useState(false);
  const types = portTypes.length ? portTypes : [...SCHEMA_TYPES];
  const add = () => {
    let name = direction === 'inputs' ? 'input' : 'output'; let index = 2;
    while (name in value) name = `${direction === 'inputs' ? 'input' : 'output'}_${index++}`;
    onChange({ ...value, [name]: direction === 'inputs' ? { required: false, schema: { type: 'string' } } : { path: name, schema: { type: 'string' } } });
  };
  return <div className="dag-structured-editor">
    {!advanced && Object.entries(value || {}).map(([name, spec]) => {
      const type = String(spec.schema?.type || 'any');
      return <div className="dag-component-port" key={name}>
        <div className="dag-component-port-main">
          <input value={name} onChange={(event) => onChange(renamed(value, name, event.target.value))} placeholder="端口名" />
          <select value={type} onChange={(event) => onChange({ ...value, [name]: { ...spec, schema: event.target.value === 'any' ? {} : { ...(spec.schema || {}), type: event.target.value } } })}>{types.map((item) => <option key={item}>{item}</option>)}</select>
          {direction === 'inputs' && <label className="dag-inline-check"><input type="checkbox" checked={Boolean(spec.required)} onChange={(event) => onChange({ ...value, [name]: { ...spec, required: event.target.checked } })} />必填</label>}
          <button type="button" className="dag-row-remove" onClick={() => { const next = { ...value }; delete next[name]; onChange(next); }}>×</button>
        </div>
        <input value={spec.description || ''} onChange={(event) => onChange({ ...value, [name]: { ...spec, description: event.target.value } })} placeholder="端口用途说明" />
        {direction === 'outputs' && <input list={`component-path-${name}`} value={spec.path || ''} onChange={(event) => onChange({ ...value, [name]: { ...spec, path: event.target.value.replace(/^\$ctx\./, '') } })} placeholder="子 DAG 数据路径，例如 result.stats" />}
        {'default' in spec && <TypedValueEditor value={spec.default} onChange={(next) => onChange({ ...value, [name]: { ...spec, default: next } })} suggestions={suggestions} />}
        {!('default' in spec) && <button type="button" className="dag-text-action" onClick={() => onChange({ ...value, [name]: { ...spec, default: '' } })}>＋ 默认值</button>}
      </div>;
    })}
    {!advanced && Object.keys(value || {}).length === 0 && <div className="dag-empty-editor">暂无{direction === 'inputs' ? '输入' : '输出'}端口。</div>}
    {advanced && <JsonTextEditor value={value} onChange={onChange} rows={9} />}
    <div className="dag-editor-actions"><button type="button" onClick={add}>＋ 添加端口</button><button type="button" onClick={() => setAdvanced((current) => !current)}>{advanced ? '返回表单' : '高级 JSON'}</button></div>
  </div>;
}

export function ContractSummary({ contract }: { contract?: DagNodeContract }) {
  if (!contract) return null;
  return <div className="dag-contract-summary">
    <p>{contract.description}</p>
    <div><b>输入</b>{Object.entries(contract.inputs || {}).map(([name, spec]) => <span key={name}>{name}<small>{spec.type || 'any'}</small></span>)}</div>
    <div><b>输出</b>{Object.entries(contract.outputs || {}).map(([name, spec]) => <span key={name}>{name}<small>{spec.type || 'any'}</small></span>)}</div>
    <div><b>事件</b>{(contract.events || []).map((event) => <span key={event}>{event}</span>)}</div>
  </div>;
}

export function StringListEditor({ value, onChange, placeholder = '名称' }: { value: string[]; onChange: (value: string[]) => void; placeholder?: string }) {
  return <div className="dag-string-list">
    {(value || []).map((item, index) => <div key={`${item}-${index}`}>
      <input value={item} onChange={(event) => onChange(value.map((current, currentIndex) => currentIndex === index ? event.target.value : current))} placeholder={placeholder} />
      <button type="button" className="dag-row-remove" onClick={() => onChange(value.filter((_, currentIndex) => currentIndex !== index))}>×</button>
    </div>)}
    <button type="button" className="dag-add-row" onClick={() => onChange([...(value || []), ''])}>＋ 添加</button>
  </div>;
}

const PERMISSION_CLASSES = ['read', 'write', 'process', 'network', 'secret', 'mutation'] as const;
const PERMISSION_DECISIONS = ['allow', 'ask', 'deny'] as const;

export function PermissionEditor({ value, onChange }: { value: PipelinePermissions; onChange: (value: PipelinePermissions) => void }) {
  const rules = value.rules || [];
  return <div className="dag-permission-editor">
    <p className="dag-editor-help">默认策略先决定每类能力是否允许；下面的规则可以按工具名进一步收紧或放行。</p>
    <div className="dag-permission-grid">
      {PERMISSION_CLASSES.map((permission) => <label key={permission}><span>{permission}</span><select value={value.defaults?.[permission] || 'allow'} onChange={(event) => onChange({ ...value, defaults: { ...value.defaults, [permission]: event.target.value as typeof PERMISSION_DECISIONS[number] } })}>{PERMISSION_DECISIONS.map((decision) => <option key={decision}>{decision}</option>)}</select></label>)}
    </div>
    <label className="dag-inline-check"><input type="checkbox" checked={Boolean(value.allow_sensitive_files)} onChange={(event) => onChange({ ...value, allow_sensitive_files: event.target.checked })} />允许读取敏感文件</label>
    <label className="dag-inline-check"><input type="checkbox" checked={value.allow_global_mutation !== false} onChange={(event) => onChange({ ...value, allow_global_mutation: event.target.checked })} />允许修改全局 Identity / Skill / Harness</label>
    <div className="dag-editor-title"><span>精细规则</span><small>{rules.length}</small></div>
    {rules.map((rule, index) => <div className="dag-permission-rule" key={index}>
      <select value={rule.decision || 'deny'} onChange={(event) => onChange({ ...value, rules: rules.map((item, currentIndex) => currentIndex === index ? { ...item, decision: event.target.value as typeof PERMISSION_DECISIONS[number] } : item) })}>{PERMISSION_DECISIONS.map((decision) => <option key={decision}>{decision}</option>)}</select>
      <select value={rule.permission_class || ''} onChange={(event) => onChange({ ...value, rules: rules.map((item, currentIndex) => currentIndex === index ? { ...item, permission_class: (event.target.value || undefined) as any } : item) })}><option value="">任意能力</option>{PERMISSION_CLASSES.map((permission) => <option key={permission}>{permission}</option>)}</select>
      <input value={rule.tool || '*'} onChange={(event) => onChange({ ...value, rules: rules.map((item, currentIndex) => currentIndex === index ? { ...item, tool: event.target.value } : item) })} placeholder="工具名，例如 run_command" />
      <input value={rule.reason || ''} onChange={(event) => onChange({ ...value, rules: rules.map((item, currentIndex) => currentIndex === index ? { ...item, reason: event.target.value } : item) })} placeholder="原因（会进入审计记录）" />
      <button type="button" className="dag-row-remove" onClick={() => onChange({ ...value, rules: rules.filter((_, currentIndex) => currentIndex !== index) })}>×</button>
    </div>)}
    <button type="button" className="dag-add-row" onClick={() => onChange({ ...value, rules: [...rules, { decision: 'ask', tool: '*', reason: '' }] })}>＋ 添加权限规则</button>
  </div>;
}

export function contractFor(catalog: DagContractCatalog | null | undefined, op: string): DagNodeContract | undefined {
  return catalog?.nodes?.[op] || Object.values(catalog?.nodes || {}).find((contract) => contract.aliases?.includes(op));
}

export function suggestedPorts(contract: DagNodeContract | undefined, direction: 'inputs' | 'outputs'): Record<string, DagPortSpec> {
  return { ...(contract?.[direction] || {}) };
}
