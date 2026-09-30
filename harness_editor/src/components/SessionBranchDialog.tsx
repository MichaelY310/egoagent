import { useMemo, useState } from 'react';
import { forkSession, mergeManySessions } from '../api/client';

export type BranchableSession = {
  name: string;
  title?: string;
  message_count: number;
  project_id?: string;
  project_title?: string;
  workspace?: string;
};

type Props = {
  action: 'fork' | 'merge';
  source: string;
  sourceProjectId?: string;
  sourceWorkspace?: string;
  initialSources?: string[];
  sessions: BranchableSession[];
  onClose: () => void;
  onCreated: (session: string) => void;
};

const fieldStyle = {
  width: '100%',
  boxSizing: 'border-box' as const,
  padding: '7px 9px',
  color: 'var(--text-primary)',
  background: 'var(--input-background)',
  border: '1px solid var(--border-strong)',
  borderRadius: 4,
  fontSize: 12,
};

const modeDescriptions = {
  auto: '同项目且新增内容较短时走规则合并；跨项目或过长时自动分别摘要。',
  direct: 'Rule-based：按选择顺序合并公共历史后的独有消息，去除完全重复项；不调用模型。',
  summary: '分别压缩每个 Session 的新增消息，再组成干净的新上下文。',
  dialogue: '每个 Session 由一个独立 Agent 代表，轮流交换事实和冲突，最后综合为继续工作所需的记忆。',
};

export default function SessionBranchDialog({ action, source, sourceWorkspace, initialSources, sessions, onClose, onCreated }: Props) {
  const candidates = useMemo(
    () => sessions.filter((session) => session.name !== source && !session.name.includes('/')),
    [sessions, source],
  );
  const [mergeSources, setMergeSources] = useState<string[]>(() => {
    const requested = (initialSources || []).filter((name) => sessions.some((session) => session.name === name));
    if (requested.length >= 2) return Array.from(new Set(requested));
    return candidates[0] ? [source, candidates[0].name] : [source];
  });
  const [name, setName] = useState('');
  const [mode, setMode] = useState<'auto' | 'direct' | 'summary' | 'dialogue'>('auto');
  const [threshold, setThreshold] = useState(12000);
  const [rounds, setRounds] = useState(2);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const selectedSessions = sessions.filter((session) => mergeSources.includes(session.name));
  const selectedProjects = new Set(selectedSessions.map((session) => session.project_id || 'unknown'));
  const crossProject = action === 'merge' && selectedProjects.size > 1;

  const submit = async () => {
    setBusy(true);
    setError('');
    try {
      const result = action === 'fork'
        ? await forkSession(source, name.trim() || undefined, sourceWorkspace)
        : await mergeManySessions({
          sessions: mergeSources,
          mode,
          name: name.trim() || undefined,
          threshold_tokens: threshold,
          dialogue_rounds: rounds,
          target_workspace: sourceWorkspace,
        });
      onCreated(String(result.session));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const disabled = busy || (action === 'merge' && mergeSources.length < 2);
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={action === 'fork' ? 'Fork session' : 'Merge sessions'}
      style={{
        position: 'absolute', inset: 0, zIndex: 30, display: 'grid', placeItems: 'center',
        background: 'rgba(0,0,0,.58)', backdropFilter: 'blur(2px)', padding: 20,
      }}
      onMouseDown={(event) => { if (event.currentTarget === event.target && !busy) onClose(); }}
    >
      <div style={{ width: 520, maxWidth: '100%', maxHeight: '90%', overflow: 'auto', background: 'var(--surface-raised)', color: 'var(--text)', border: '1px solid var(--border-strong)', borderRadius: 8, boxShadow: '0 18px 60px var(--shadow-color)' }}>
        <div style={{ display: 'flex', alignItems: 'center', padding: '13px 16px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ flex: 1 }}>
            <div style={{ color: 'var(--text-primary)', fontSize: 14, fontWeight: 600 }}>{action === 'fork' ? 'Fork Session' : 'Merge Sessions'}</div>
            <div style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 3 }}>来源始终只读；结果会保存为一个带血缘记录的新 Session。</div>
          </div>
          <button onClick={onClose} disabled={busy} style={{ color: 'var(--text-dim)', background: 'transparent', border: 0, cursor: 'pointer', fontSize: 18 }}>×</button>
        </div>

        <div style={{ padding: 16, display: 'grid', gap: 13 }}>
          <label style={{ color: 'var(--text-dim)', fontSize: 11 }}>
            左侧来源
            <input value={source} disabled style={{ ...fieldStyle, marginTop: 5, color: '#999' }} />
          </label>

          {action === 'merge' && <>
            <fieldset style={{ margin: 0, padding: 10, border: '1px solid var(--border-strong)', borderRadius: 5 }}>
              <legend style={{ color: 'var(--text-dim)', fontSize: 11, padding: '0 5px' }}>选择 2–8 个 Session · 当前 {mergeSources.length} 个</legend>
              <div style={{ maxHeight: 170, overflow: 'auto', display: 'grid', gap: 4 }}>
                {sessions.filter((session) => !session.name.includes('/')).map((session) => {
                  const checked = mergeSources.includes(session.name);
                  return <label key={session.name} style={{ display: 'flex', gap: 7, alignItems: 'center', padding: '5px 6px', color: 'var(--text-secondary)', background: checked ? 'var(--surface-2)' : 'transparent', borderRadius: 4, fontSize: 11, cursor: 'pointer' }}>
                    <input type="checkbox" checked={checked} disabled={!checked && mergeSources.length >= 8} onChange={() => {
                      const next = checked ? mergeSources.filter((name) => name !== session.name) : [...mergeSources, session.name];
                      setMergeSources(next);
                      const projectIds = new Set(sessions.filter((item) => next.includes(item.name)).map((item) => item.project_id || 'unknown'));
                      if (mode === 'direct' && projectIds.size > 1) setMode('summary');
                    }} />
                    <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{session.project_title ? `${session.project_title} / ` : ''}{session.title || session.name}</span>
                    <small>{session.message_count}</small>
                  </label>;
                })}
              </div>
            </fieldset>
            <label style={{ color: 'var(--text-dim)', fontSize: 11 }}>
              合并方法
              <select value={mode} onChange={(event) => setMode(event.target.value as typeof mode)} style={{ ...fieldStyle, marginTop: 5 }}>
                <option value="auto">Auto · 长度自适应</option>
                <option value="direct" disabled={crossProject}>Rule-based · 确定性合并{crossProject ? '（仅同项目）' : ''}</option>
                <option value="summary">Summary · 各 Session 独立摘要</option>
                <option value="dialogue">Agent Communication · 多 Agent 交流</option>
              </select>
            </label>
            <div style={{ padding: '9px 11px', color: 'var(--text-secondary)', background: 'var(--surface-2)', borderLeft: '2px solid var(--focus)', fontSize: 11, lineHeight: 1.45 }}>
              {crossProject
                ? '跨项目合并会把结果保存到第一个 Session 的项目。为避免旧路径污染，只允许分别摘要或 Agent Communication；Auto 会自动使用 Summary。'
                : modeDescriptions[mode]}
            </div>
            {mode === 'auto' && <label style={{ color: 'var(--text-dim)', fontSize: 11 }}>
              Auto 摘要阈值（估算 tokens）
              <input type="number" min={256} max={1000000} value={threshold} onChange={(event) => setThreshold(Number(event.target.value) || 12000)} style={{ ...fieldStyle, marginTop: 5 }} />
            </label>}
            {mode === 'dialogue' && <label style={{ color: 'var(--text-dim)', fontSize: 11 }}>
              每个 Session 的交流轮数（1–4）
              <input type="number" min={1} max={4} value={rounds} onChange={(event) => setRounds(Math.max(1, Math.min(4, Number(event.target.value) || 2)))} style={{ ...fieldStyle, marginTop: 5 }} />
            </label>}
          </>}

          <label style={{ color: 'var(--text-dim)', fontSize: 11 }}>
            新 Session 名称（留空自动生成）
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如 feature-a-merged" style={{ ...fieldStyle, marginTop: 5 }} />
          </label>
          {error && <div style={{ padding: '8px 10px', color: '#f48771', background: '#301b1b', border: '1px solid #6d3030', borderRadius: 4, fontSize: 11 }}>{error}</div>}
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '12px 16px', borderTop: '1px solid var(--border)' }}>
          <button onClick={onClose} disabled={busy} style={{ padding: '6px 13px', color: 'var(--button-text)', background: 'var(--button-bg)', border: '1px solid var(--border)', borderRadius: 4, cursor: 'pointer' }}>取消</button>
          <button onClick={submit} disabled={disabled} style={{ padding: '6px 14px', color: 'white', background: disabled ? '#3d3d3d' : '#0e639c', border: 0, borderRadius: 4, cursor: disabled ? 'default' : 'pointer', fontWeight: 600 }}>
            {busy ? '处理中…' : action === 'fork' ? '创建 Fork' : '创建 Merged Session'}
          </button>
        </div>
      </div>
    </div>
  );
}
