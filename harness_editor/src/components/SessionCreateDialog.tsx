import { useEffect, useMemo, useState } from 'react';
import { createPortfolioSession, listHarnesses, listIdentities, loadHarness, type ProjectPortfolioItem } from '../api/client';

type Props = {
  projects: ProjectPortfolioItem[];
  preferredProjectId?: string;
  onClose: () => void;
  onCreated: (session: string) => void;
};

const fieldStyle = {
  width: '100%', boxSizing: 'border-box' as const, padding: '7px 9px', marginTop: 5,
  color: 'var(--text-primary)', background: 'var(--input-background)',
  border: '1px solid var(--border-strong)', borderRadius: 4, fontSize: 12,
};

export default function SessionCreateDialog({ projects, preferredProjectId, onClose, onCreated }: Props) {
  const available = useMemo(() => projects.filter((project) => project.available && project.workspace), [projects]);
  const [projectId, setProjectId] = useState(() => {
    if (preferredProjectId && preferredProjectId !== 'all' && available.some((project) => project.id === preferredProjectId)) return preferredProjectId;
    return available.find((project) => project.current)?.id || available[0]?.id || '';
  });
  const [title, setTitle] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [harnesses, setHarnesses] = useState<string[]>([]);
  const [identities, setIdentities] = useState<string[]>([]);
  const [harness, setHarness] = useState('code_agent_auto');
  const [identity, setIdentity] = useState('adaptive_deepseek_coder');
  const [mode, setMode] = useState('agent');
  const [slots, setSlots] = useState<string[]>(['agent']);
  const [bindings, setBindings] = useState<Record<string, string>>({});
  const project = available.find((item) => item.id === projectId);

  useEffect(() => {
    Promise.all([listHarnesses(), listIdentities()]).then(([nextHarnesses, nextIdentities]) => {
      setHarnesses(nextHarnesses);
      setIdentities(nextIdentities);
      if (!nextHarnesses.includes(harness)) setHarness(nextHarnesses.includes('code_agent_auto') ? 'code_agent_auto' : nextHarnesses[0] || '');
      if (!nextIdentities.includes(identity)) setIdentity(nextIdentities.includes('adaptive_deepseek_coder') ? 'adaptive_deepseek_coder' : nextIdentities[0] || '');
    }).catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, []);

  useEffect(() => {
    if (!harness) return;
    loadHarness(harness).then((config) => {
      const names = Object.keys(config?.slots || {});
      setSlots(names.length ? names : ['agent']);
      setBindings((current) => Object.fromEntries((names.length ? names : ['agent']).map((slot) => [slot, current[slot] || config?.slots?.[slot]?.identity || identity])));
    }).catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, [harness, identity]);

  const submit = async () => {
    if (!project) return;
    setBusy(true);
    setError('');
    try {
      const result = await createPortfolioSession({
        name: name.trim() || undefined,
        title: title.trim() || undefined,
        workspace: project.workspace,
        agent_config: harness && identity ? {
          harness,
          mode,
          debug_mode: mode === 'debug' ? 'paused' : 'auto',
          agents: Object.fromEntries(slots.map((slot) => [slot, `identity/${bindings[slot] || identity}`])),
        } : undefined,
      });
      onCreated(String(result.session));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  return <div role="dialog" aria-modal="true" aria-label="Create session" style={{ position: 'absolute', inset: 0, zIndex: 35, display: 'grid', placeItems: 'center', padding: 20, background: 'rgba(0,0,0,.58)', backdropFilter: 'blur(2px)' }} onMouseDown={(event) => { if (event.currentTarget === event.target && !busy) onClose(); }}>
    <div style={{ width: 470, maxWidth: '100%', background: 'var(--surface-raised)', border: '1px solid var(--border-strong)', borderRadius: 8, color: 'var(--text)', boxShadow: '0 18px 60px var(--shadow-color)' }}>
      <div style={{ display: 'flex', alignItems: 'center', padding: '13px 16px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ flex: 1 }}>
          <div style={{ color: 'var(--text-primary)', fontSize: 14, fontWeight: 600 }}>New Session</div>
          <div style={{ marginTop: 3, color: 'var(--text-dim)', fontSize: 11 }}>先创建可持久化 Session；显示名以后可以双击修改，稳定 ID 不会改变。</div>
        </div>
        <button type="button" onClick={onClose} disabled={busy} style={{ border: 0, color: 'var(--text-dim)', background: 'transparent', fontSize: 18, cursor: 'pointer' }}>×</button>
      </div>
      <div style={{ display: 'grid', gap: 13, padding: 16 }}>
        <label style={{ color: 'var(--text-dim)', fontSize: 11 }}>所属 Project
          <select value={projectId} onChange={(event) => setProjectId(event.target.value)} style={fieldStyle}>
            {available.map((item) => <option key={item.id} value={item.id}>{item.title} · {item.workspace}</option>)}
          </select>
        </label>
        <label style={{ color: 'var(--text-dim)', fontSize: 11 }}>显示名
          <input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void submit(); }} placeholder="例如：修复登录流程" style={fieldStyle} />
        </label>
        <label style={{ color: 'var(--text-dim)', fontSize: 11 }}>稳定 ID（可留空自动生成）
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如 fix-login；创建后不随重命名改变" style={fieldStyle} />
        </label>
        <div style={{ padding: 11, border: '1px solid var(--border)', borderRadius: 5, background: 'var(--surface-sunken)' }}>
          <div style={{ color: 'var(--text-primary)', fontSize: 11, fontWeight: 600 }}>此 Session 的 Agent 配置</div>
          <div style={{ marginTop: 3, color: 'var(--text-dim)', fontSize: 10 }}>配置会随 Session 保存；切换到其他 Session 时不会被全局选择覆盖。</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 9, marginTop: 9 }}>
            <label style={{ color: 'var(--text-dim)', fontSize: 10 }}>模式
              <select value={mode} onChange={(event) => setMode(event.target.value)} style={fieldStyle}>
                <option value="chat">Chat · 只读问答</option><option value="plan">Plan · 只读规划</option><option value="agent">Agent · 执行任务</option><option value="debug">Debug · 单步调试</option><option value="evolve">Evolve · 限域进化</option><option value="evaluate">Evaluate · 隔离评测</option>
              </select>
            </label>
            <label style={{ color: 'var(--text-dim)', fontSize: 10 }}>Harness
              <select value={harness} onChange={(event) => setHarness(event.target.value)} style={fieldStyle}>{harnesses.map((item) => <option key={item} value={item}>{item}</option>)}</select>
            </label>
          </div>
          <div style={{ display: 'grid', gap: 7, marginTop: 8 }}>
            {slots.map((slot) => <label key={slot} style={{ display: 'grid', gridTemplateColumns: 'minmax(80px,.55fr) minmax(130px,1fr)', alignItems: 'center', gap: 8, color: 'var(--text-dim)', fontSize: 10 }}><span>{slot} Identity</span><select value={bindings[slot] || identity} onChange={(event) => { setBindings((current) => ({ ...current, [slot]: event.target.value })); if (slot === slots[0]) setIdentity(event.target.value); }} style={{ ...fieldStyle, marginTop: 0 }}>{identities.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>)}
          </div>
        </div>
        {!available.length && <div style={{ color: '#f48771', fontSize: 11 }}>没有可用 Project。请先创建或注册一个 Project。</div>}
        {error && <div style={{ padding: '8px 10px', color: '#f48771', background: 'var(--surface-2)', border: '1px solid #8b3a3a', borderRadius: 4, fontSize: 11 }}>{error}</div>}
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '12px 16px', borderTop: '1px solid var(--border)' }}>
        <button type="button" onClick={onClose} disabled={busy} style={{ padding: '6px 13px', color: 'var(--button-text)', background: 'var(--button-bg)', border: '1px solid var(--border)', borderRadius: 4, cursor: 'pointer' }}>取消</button>
        <button type="button" onClick={() => void submit()} disabled={busy || !project} style={{ padding: '6px 14px', color: 'white', background: busy || !project ? '#59636e' : 'var(--focus)', border: 0, borderRadius: 4, cursor: busy || !project ? 'default' : 'pointer', fontWeight: 600 }}>{busy ? '创建中…' : '创建 Session'}</button>
      </div>
    </div>
  </div>;
}
