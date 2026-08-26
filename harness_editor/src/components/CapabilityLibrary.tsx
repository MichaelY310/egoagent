import { useEffect, useMemo, useState } from 'react';
import * as api from '../api/client';
import type { CapabilityItem } from '../api/client';
import { WORKSPACE } from '../api/runtime';
import { publishWorkbenchEvent } from '../workbenchSession';

const KINDS = ['all', 'skill', 'tool', 'knowledge', 'identity', 'harness'] as const;
const KIND_LABELS: Record<string, string> = {
  all: '全部', skill: 'Skills', tool: 'Tools', knowledge: 'Knowledge', identity: 'Identities', harness: 'DAG / Harness',
};
const KIND_MARKS: Record<string, string> = {
  skill: 'S', tool: 'T', knowledge: 'K', identity: 'ID', harness: 'DAG',
};

function compactNumber(value: number | undefined): string {
  const amount = Number(value || 0);
  if (amount >= 10_000) return `${(amount / 10_000).toFixed(amount >= 100_000 ? 0 : 1)}万`;
  if (amount >= 1_000) return `${(amount / 1_000).toFixed(1)}k`;
  return String(amount);
}

export default function CapabilityLibrary() {
  const [items, setItems] = useState<CapabilityItem[]>([]);
  const [stats, setStats] = useState<Record<string, any>>({});
  const [pinned, setPinned] = useState<Set<string>>(new Set());
  const [kind, setKind] = useState<(typeof KINDS)[number]>('all');
  const [query, setQuery] = useState('');
  const [searchMode, setSearchMode] = useState<'auto' | 'semantic' | 'lexical'>('auto');
  const [searchInfo, setSearchInfo] = useState<Record<string, any>>({});
  const [selected, setSelected] = useState<CapabilityItem | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    setBusy(true);
    try {
      const result = await api.listCapabilities(kind === 'all' ? '' : kind);
      setItems(result.items || []);
      setStats(result.stats || {});
      setPinned(new Set(result.pinned || []));
      setMessage('');
      setSearchInfo({});
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!query.trim()) {
      void refresh();
      return;
    }
    const timer = window.setTimeout(() => {
      setBusy(true);
      api.searchCapabilities(query, kind === 'all' ? [] : [kind], 50, searchMode)
        .then((result) => {
          setItems(result.results || []);
          setSearchInfo({ retrieval: result.retrieval, embedding: result.embedding, fusion: result.fusion });
          setMessage(result.guidance || '');
        })
        .catch((error) => setMessage(error instanceof Error ? error.message : String(error)))
        .finally(() => setBusy(false));
    }, 220);
    return () => window.clearTimeout(timer);
  }, [query, kind, searchMode]);

  const kindCounts = useMemo(() => stats.kinds || {}, [stats]);

  const togglePin = async (item: CapabilityItem) => {
    const enabled = !pinned.has(item.id);
    try {
      const result = await api.pinCapability(item.id, enabled);
      setPinned(new Set(result.pinned || []));
      setMessage(enabled
        ? `${item.name} 已固定到当前 workspace；新启动的 Agent 会按需加载它。`
        : `${item.name} 已从当前 workspace 移除。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };

  const useStructuralCapability = async (item: CapabilityItem) => {
    await api.recordCapabilityEvent(item.id, 'activate');
    publishWorkbenchEvent('capability-selected', { id: item.id, kind: item.kind, name: item.name, path: item.path });
    await navigator.clipboard?.writeText(item.name).catch(() => undefined);
    const modes = item.reuse?.modes?.join(' / ');
    setMessage(`${item.name} 已复制并发送到 Workbench。可在 ${item.kind === 'identity' ? 'Identity 槽位' : 'Build 的 SubDAG / Evaluate'} 中选择${modes ? `；可复用方式：${modes}` : ''}。`);
  };

  return <div className="capability-library">
    <header className="capability-hero">
      <div><span className="eyebrow">LOCAL CAPABILITY NETWORK</span><h2>能力库</h2><p>先发现、再激活、最后才创建。Agent 只看到少量入口工具，需要时再加载能力正文与 schema。</p></div>
      <div className="capability-summary">
        <b>{compactNumber(stats.capabilities)}</b><span>个能力</span>
        <b>{compactNumber(stats.activations)}</b><span>次使用</span>
        <b>{compactNumber(stats.searches)}</b><span>次检索</span>
      </div>
    </header>

    <div className="capability-toolbar">
      <label className="capability-search"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索任务、能力名称、标签或简介…" /></label>
      <select aria-label="搜索模式" value={searchMode} onChange={(event) => setSearchMode(event.target.value as typeof searchMode)}>
        <option value="auto">混合搜索</option><option value="semantic">仅语义</option><option value="lexical">仅关键词</option>
      </select>
      <button disabled={busy} onClick={async () => { await api.reindexCapabilities(); await refresh(); }}>{busy ? '索引中…' : '重新索引'}</button>
    </div>
    <nav className="capability-filters">
      {KINDS.map((value) => <button key={value} className={kind === value ? 'active' : ''} onClick={() => setKind(value)}>{KIND_LABELS[value]} <span>{value === 'all' ? stats.capabilities || 0 : kindCounts[value] || 0}</span></button>)}
    </nav>
    {WORKSPACE && <div className="capability-workspace"><span>Workspace 优先</span><code>{WORKSPACE}</code><small>本项目内能力会获得排序加权；固定项只影响本项目。</small></div>}
    <div className="capability-search-status">
      <b>{query ? (searchInfo.retrieval || '准备检索') : (stats.embedding?.available ? 'Hybrid ready' : 'Lexical ready')}</b>
      <span>{query && searchInfo.embedding?.available
        ? `${searchInfo.embedding.provider} · ${searchInfo.embedding.model} · ${searchInfo.embedding.cached_documents ?? searchInfo.embedding.cached_vectors ?? 0} cached`
        : (searchInfo.embedding?.fallback_reason || stats.embedding?.fallback_reason || '关键词检索始终可用')}</span>
    </div>
    {message && <div className="capability-message">{message}</div>}

    <section className="capability-grid" aria-busy={busy}>
      {items.map((item, index) => {
        const canPin = ['skill', 'tool', 'knowledge'].includes(item.kind);
        const isPinned = pinned.has(item.id);
        return <article className={`capability-card kind-${item.kind}`} key={item.id} onClick={() => setSelected(item)}>
          <div className="capability-cover">
            <span>{KIND_MARKS[item.kind] || '?'}</span>
            <div><b>{item.scope === 'workspace' ? 'WORKSPACE' : item.kind.toUpperCase()}</b><small>#{String(index + 1).padStart(2, '0')}</small></div>
            {isPinned && <em>已固定</em>}
          </div>
          <div className="capability-card-body">
            <h3>{item.display_name || item.name}</h3>
            <p>{item.description || '暂无简介；建议补充元数据以改善 Agent 检索。'}</p>
            <div className="capability-tags">{(item.tags || []).slice(0, 4).map((tag) => <span key={tag}>#{tag}</span>)}</div>
            <footer><span>▶ {compactNumber(item.usage_count)}</span><span>◎ {compactNumber(item.impressions)}</span><span>{item.success_rate == null ? '未验证' : `✓ ${Math.round(item.success_rate * 100)}%`}</span><b>{item.owner || item.scope}</b></footer>
          </div>
          <div className="capability-card-actions" onClick={(event) => event.stopPropagation()}>
            {canPin
              ? <button className={isPinned ? 'active' : ''} onClick={() => void togglePin(item)}>{isPinned ? '取消固定' : '用于此项目'}</button>
              : <button onClick={() => void useStructuralCapability(item)}>选择并复制名称</button>}
            <button onClick={() => setSelected(item)}>详情</button>
          </div>
        </article>;
      })}
    </section>
    {!items.length && !busy && <div className="capability-empty"><b>没有匹配项</b><span>Agent 的检索工具也会看到“建议创建”信号，并可通过 create_skill / create_knowledge / manage_harness 补齐缺口。</span></div>}

    {selected && <div className="capability-drawer-backdrop" onClick={() => setSelected(null)}>
      <aside className="capability-drawer" onClick={(event) => event.stopPropagation()}>
        <button className="capability-drawer-close" onClick={() => setSelected(null)}>×</button>
        <div className={`capability-detail-mark kind-${selected.kind}`}>{KIND_MARKS[selected.kind]}</div>
        <span className="eyebrow">{selected.kind} · {selected.scope}</span>
        <h2>{selected.display_name || selected.name}</h2><code>{selected.name}</code>
        <p>{selected.description || '暂无简介'}</p>
        <dl>
          <div><dt>使用</dt><dd>{selected.usage_count || 0}</dd></div>
          <div><dt>成功率</dt><dd>{selected.success_rate == null ? '未验证' : `${Math.round(selected.success_rate * 100)}%`}</dd></div>
          <div><dt>平均耗时</dt><dd>{selected.average_runtime_ms == null ? '—' : `${selected.average_runtime_ms} ms`}</dd></div>
          <div><dt>所有者</dt><dd>{selected.owner || 'local'}</dd></div>
        </dl>
        {selected.match_reason && <div className="capability-match">为什么匹配：{selected.match_reason}</div>}
        {selected.semantic_score != null && <div className="capability-match">语义相似度：{selected.semantic_score.toFixed(3)} · 关键词分：{(selected.lexical_score || 0).toFixed(2)}</div>}
        {selected.path && <label>来源路径<code>{selected.path}</code></label>}
        {selected.reuse && <div className="capability-match">
          <b>复用契约</b>
          <div>{selected.reuse.modes?.join(' · ')}</div>
          {selected.reuse.binding && <code>{selected.reuse.binding}</code>}
          {selected.reuse.invoke?.arguments && <code>{JSON.stringify(selected.reuse.invoke.arguments)}</code>}
          {selected.reuse.subflow && <code>{JSON.stringify(selected.reuse.subflow)}</code>}
        </div>}
        <div className="capability-tags">{(selected.tags || []).map((tag) => <span key={tag}>#{tag}</span>)}</div>
        {['skill', 'tool', 'knowledge'].includes(selected.kind)
          ? <button className="capability-primary" onClick={() => void togglePin(selected)}>{pinned.has(selected.id) ? '从当前项目移除' : '固定到当前项目'}</button>
          : <button className="capability-primary" onClick={() => void useStructuralCapability(selected)}>选择并复制名称</button>}
      </aside>
    </div>}
  </div>;
}
