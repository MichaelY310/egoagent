import { useEffect, useState } from 'react';
import * as api from '../api/client';
import FlowRunViewer from './FlowRunViewer';

export default function ObservationRoom({ initialRootId = '' }: { initialRootId?: string }) {
  const [runs, setRuns] = useState<any[]>([]);
  const [album, setAlbum] = useState<any[]>([]);
  const [selected, setSelected] = useState<{root: string; recording?: string} | null>(initialRootId ? { root: initialRootId } : null);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [libraryOpen, setLibraryOpen] = useState(false);
  useEffect(() => { if (initialRootId) { setSelected({ root: initialRootId }); setLibraryOpen(false); } }, [initialRootId]);
  const refresh = async () => {
    try { const [r, a] = await Promise.all([api.listFlowObservations(), api.listFlowRecordings()]); setRuns(r); setAlbum(a); setError(''); }
    catch (reason) { setError((reason as Error).message); }
  };
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 4000); return () => window.clearInterval(timer); }, []);
  const matches = (value: unknown) => JSON.stringify(value).toLowerCase().includes(query.toLowerCase());
  return <div className={`observation-room ${selected ? 'has-selection' : ''} ${libraryOpen ? 'library-open' : ''}`}>
    <aside className="observation-sidebar">
      <header><strong>运行相簿</strong><button onClick={() => void refresh()}>刷新</button></header>
      <input aria-label="搜索运行与录制" placeholder="搜索项目、Flow 或录制…" value={query} onChange={event => setQuery(event.target.value)} />
      {error && <p role="alert">{error}</p>}
      <h4>已保存的录制 · {album.length}</h4>
      {!album.length && <p>在任何运行中点击“开始录制”或“保存完整运行到相簿”。</p>}
      {album.filter(matches).map(item => <button className={`observation-card ${selected?.recording === item.id ? 'active' : ''}`} key={item.id}
        onClick={() => { setSelected({ root: item.root_id, recording: item.id }); setLibraryOpen(false); }}>
        <strong>{item.title}</strong><small>{item.end_sequence == null ? '● 正在录制' : '◷ 点击回放'} · {new Date(item.created * 1000).toLocaleString()}</small>
      </button>)}
      <h4>所有入口的运行 · {runs.length}</h4>
      {runs.filter(matches).map(item => <button className={`observation-card ${selected?.root === item.root_id && !selected?.recording ? 'active' : ''}`} key={item.root_id}
        onClick={() => { setSelected({ root: item.root_id }); setLibraryOpen(false); }}>
        <strong>{item.metadata.harness || item.root_id}</strong><small>{item.metadata.entry_type} · {item.status} · {item.run_count} 个 Flow</small>
        <small>{item.metadata.workspace}</small><small>{new Date(item.created * 1000).toLocaleString()}</small>
      </button>)}
    </aside>
    <main className="observation-main">{selected && <button className="observation-library-toggle" aria-expanded={libraryOpen} onClick={() => setLibraryOpen(value => !value)}>{libraryOpen ? '收起相簿列表' : '☷ 相簿列表 / 切换运行'}</button>}{selected ? <FlowRunViewer rootId={selected.root} recordingId={selected.recording} />
      : <div className="observer-empty"><h2>同一张 Flow，从实时执行到逐步回放</h2><p>从左侧选择 Chat、Task、Build、CLI 或 API 的运行。可以随时加入观察，无需重新启动 Agent。</p><p>相簿中的回放是只读记录，不执行命令、不消耗模型额度。</p></div>}</main>
  </div>;
}
