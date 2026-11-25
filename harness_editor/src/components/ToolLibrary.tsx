import { useEffect, useMemo, useRef, useState } from 'react';
import * as api from '../api/client';
import { editCapabilityFileInIde } from '../ideBridge';
import './ToolLibrary.css';

export default function ToolLibrary({ identity = '', onSaved }: {
  identity?: string; onSaved?: (selection: api.StartupCapabilities) => void;
}) {
  const [items, setItems] = useState<api.ToolLibraryItem[]>([]);
  const [identities, setIdentities] = useState<string[]>([]);
  const [chosenIdentity, setChosenIdentity] = useState('');
  const target = identity || chosenIdentity;
  const [config, setConfig] = useState<api.IdentityCapabilities | null>(null);
  const [selection, setSelection] = useState<api.StartupCapabilities>(null);
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('all');
  const [source, setSource] = useState('');
  const [selectedOnly, setSelectedOnly] = useState(false);
  const [page, setPage] = useState(0);
  const [detail, setDetail] = useState<api.ToolLibraryItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const generation = useRef(0);
  const activeTarget = useRef(target);
  activeTarget.current = target;

  const load = async (refresh = false) => {
    const request = ++generation.current;
    setBusy(true); setError(''); setConfig(null);
    try {
      const [library, selected, names] = await Promise.all([
        api.listToolLibrary(refresh), target ? api.readIdentityCapabilities(target) : Promise.resolve(null),
        identity ? Promise.resolve([]) : api.listIdentities(),
      ]);
      if (request !== generation.current) return;
      setItems(library.items); setConfig(selected); setSelection(selected?.selection ?? null); setIdentities(names);
    } catch (e) {
      if (request === generation.current) setError(e instanceof Error ? e.message : String(e));
    } finally { if (request === generation.current) setBusy(false); }
  };
  useEffect(() => { setMessage(''); setDetail(null); void load(); return () => { ++generation.current; }; }, [target]);
  useEffect(() => setPage(0), [query, filter, source, selectedOnly, target]);
  const checked = useMemo(() => new Set(selection?.tools ?? config?.defaults ?? []), [selection, config]);
  const dirty = !!config && JSON.stringify(selection) !== JSON.stringify(config.selection);
  const sources = useMemo(() => [...new Set(items.map(item => item.source))].sort(), [items]);
  const filtered = useMemo(() => items.filter(item =>
    (filter === 'all' || item.type === filter) && (!source || item.source === source) &&
    (!selectedOnly || checked.has(item.ref)) &&
    `${item.name} ${item.description} ${item.source} ${item.ref}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  ), [items, query, filter, source, selectedOnly, checked]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / 40));
  const currentPage = Math.min(page, pageCount - 1);
  const visible = filtered.slice(currentPage * 40, (currentPage + 1) * 40);
  const missing = selection?.tools.filter(ref => !items.some(item => item.ref === ref)) || [];

  const toggle = (item: api.ToolLibraryItem, enabled: boolean) => {
    if (!selection || saving) return;
    if (enabled) {
      const conflict = items.find(other => other.name === item.name && other.ref !== item.ref && checked.has(other.ref));
      if (conflict) { setError(`已选择同名能力 ${item.name}（${conflict.source}），请先取消它，再选择这个来源。`); return; }
    }
    setError(''); setMessage('');
    setSelection({ version: 1, tools: enabled ? [...selection.tools, item.ref] : selection.tools.filter(ref => ref !== item.ref) });
  };
  const save = async () => {
    if (!config || !target) return;
    const savingTarget = target;
    setSaving(true); setError('');
    try {
      const result = await api.saveIdentityCapabilities(target, selection, config.revision);
      if (activeTarget.current !== savingTarget) return;
      setConfig(result); setSelection(result.selection); onSaved?.(result.selection);
      setMessage(`已保存 ${target}。新建 Session / 重新启动 Agent 后生效；正在运行的 Agent 不会被热替换。`);
    } catch (e) { if (activeTarget.current === savingTarget) setError(e instanceof Error ? e.message : String(e)); }
    finally { setSaving(false); }
  };
  const edit = async (path: string) => {
    if (dirty) { setError('还有未保存的能力选择，请先保存或撤销选择，再打开源码文件。'); return; }
    setError('');
    try { await editCapabilityFileInIde(path); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  };
  const reload = () => {
    if (dirty && !window.confirm('重新加载会放弃尚未保存的能力选择，继续吗？')) return;
    void load(true);
  };

  return <section className="tool-library" aria-label="工具与 Skills">
    <header className="tool-library-header"><div><h2>{identity ? '选择 Identity 的工具与 Skills' : '工具与 Skills'}</h2>
      <p>查看全部来源，点击编辑直接打开 IDE 文件。工具由 Python 执行；指令 Skill 来自 SKILL.md。</p></div>
      <button disabled={busy || saving} onClick={reload}>{busy ? '加载中…' : '刷新工具库'}</button></header>
    {!identity && <label className="tool-identity-select">为 Identity 配置能力
      <select value={chosenIdentity} disabled={saving} onChange={e => {
        if (dirty && !window.confirm('切换 Identity 会放弃尚未保存的选择，继续吗？')) return;
        setChosenIdentity(e.target.value);
      }}><option value="">仅浏览工具库</option>{identities.map(name => <option key={name}>{name}</option>)}</select>
    </label>}
    {target && <div className="tool-selection-policy">
      <div><b>{target}</b><select aria-label="能力加载方式" disabled={!config || busy || saving} value={selection ? 'custom' : 'default'} onChange={e => {
        setSelection(e.target.value === 'custom' ? { version: 1, tools: [...(config?.defaults ?? [])] } : null); setMessage(''); setError('');
      }}><option value="default">默认：继承与环境配置</option><option value="custom">自定义：只启动勾选的能力</option></select>
      <span>{checked.size} 项{dirty ? ' · 未保存' : ''}</span>
      <button className="tool-primary" disabled={!dirty || busy || saving} onClick={() => void save()}>{saving ? '保存中…' : '保存能力选择'}</button>
      {dirty && <button disabled={saving} onClick={() => { setSelection(config?.selection ?? null); setError(''); }}>撤销未保存选择</button>}</div>
      <p>{selection ? '自定义清单替代启动时的 Identity、环境与项目固定工具；空清单表示不加载工具。Knowledge 不受影响。' : '沿用现有加载规则；下方勾选展示 Identity 继承、本地与公共/项目环境的合并结果，不含 Flow 额外环境。切换到自定义后可逐项选择。'}</p>
      <p>这不是安全白名单：Superego、Flow 和工作区策略仍然生效；如果保留动态发现工具，Agent 仍可按策略加载更多能力。保存不修改公共工具源码，也不会热替换当前运行。</p>
      {missing.map(ref => <div className="tool-error" key={ref}>找不到已选来源：{ref} <button disabled={saving} onClick={() => setSelection({ version: 1, tools: selection!.tools.filter(value => value !== ref) })}>移除此引用</button></div>)}
    </div>}
    <div className="tool-library-toolbar">
      <input aria-label="搜索工具与 Skills" placeholder="搜索名称、功能、来源…" value={query} onChange={e => setQuery(e.target.value)} />
      <select aria-label="能力类型" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">全部类型</option><option value="tool">可执行工具</option><option value="skill">指令 Skills</option></select>
      <select aria-label="能力来源" value={source} onChange={e => setSource(e.target.value)}><option value="">全部来源</option>{sources.map(value => <option key={value}>{value}</option>)}</select>
      {target && <label><input type="checkbox" checked={selectedOnly} onChange={e => setSelectedOnly(e.target.checked)} />仅看已选</label>}
    </div>
    {error && <div className="tool-error" role="alert">{error}</div>}
    {message && <div className="tool-notice" role="status">{message}</div>}
    <div className="tool-table-wrap" aria-busy={busy}><table className="tool-table"><thead><tr>
      {target && <th>使用</th>}<th>名称 / 说明</th><th>类型 / 来源</th><th>操作</th>
    </tr></thead><tbody>{visible.map(item => <tr key={item.ref}>
      {target && <td><input type="checkbox" aria-label={`使用 ${item.name} · ${item.source}`} checked={checked.has(item.ref)} disabled={!selection || !config || busy || saving || !item.usable} onChange={e => toggle(item, e.target.checked)} /></td>}
      <td><button className="tool-name" onClick={() => setDetail(item)}>{item.name}</button><p>{item.description || item.problem || '暂无说明'}</p></td>
      <td><span className="tool-type">{item.type === 'tool' ? 'Tool' : 'Skill'}</span><div>{item.source}</div><small>使用 {item.usage_count} 次</small></td>
      <td><button disabled={!item.entry_file} onClick={() => void edit(item.entry_file!)}>编辑</button><button onClick={() => setDetail(item)}>详情</button></td>
    </tr>)}</tbody></table>
    {!visible.length && <p className="tool-empty">{busy ? '正在读取工具来源…' : '没有匹配的工具或 Skill。可以调整搜索条件或刷新工具库。'}</p>}</div>
    <footer className="tool-pagination"><span>{filtered.length} 个来源（同名工具分别展示） · {currentPage + 1} / {pageCount}</span>
      <button disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>上一页</button><button disabled={currentPage + 1 >= pageCount} onClick={() => setPage(currentPage + 1)}>下一页</button></footer>
    {detail && <div className="tool-detail-backdrop" onClick={() => setDetail(null)}><aside className="tool-detail" role="dialog" aria-modal="true" aria-label={`${detail.name} 详情`} onClick={e => e.stopPropagation()}>
      <header><h3>{detail.name}</h3><button aria-label="关闭工具详情" onClick={() => setDetail(null)}>关闭</button></header>
      <p>{detail.description}</p><p>{detail.source} · {detail.type === 'tool' ? '可执行工具' : '指令 Skill'}</p><code>{detail.ref}</code>
      <p className="tool-notice">编辑会修改这一来源的文件；所有引用它的 Identity 都会受影响。只想更改可用范围，请使用能力勾选。</p>
      <h4>源文件</h4>{detail.files.map(file => <button className="tool-file" key={file.path} title={file.path} onClick={() => void edit(file.path)}>{file.name} ↗</button>)}
      {detail.type === 'tool' && <><h4>输入参数</h4><pre>{JSON.stringify(detail.parameters, null, 2)}</pre></>}
      {detail.problem && <div className="tool-error">{detail.problem}</div>}
      {error && <div className="tool-error" role="alert">{error}</div>}
    </aside></div>}
  </section>;
}
