import { useMemo, useState } from 'react';
import { forkSession, mergeSessions } from '../api/client';

export type BranchableSession = {
  name: string;
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
  sessions: BranchableSession[];
  onClose: () => void;
  onCreated: (session: string) => void;
};

const fieldStyle = {
  width: '100%',
  boxSizing: 'border-box' as const,
  padding: '7px 9px',
  color: '#e7e7e7',
  background: '#1f1f1f',
  border: '1px solid #454545',
  borderRadius: 4,
  fontSize: 12,
};

const modeDescriptions = {
  auto: '新增内容较短时原样拼接；超过阈值后分别摘要两个分支。',
  direct: '保留左侧当前上下文，并原样追加右侧分支点后的消息；不调用模型。',
  summary: '分别压缩两个分支的新增消息，再组成干净的新上下文。',
  dialogue: '分支 A、分支 B 轮流校对信息，最后由综合 Agent 生成带冲突说明的记忆。',
};

export default function SessionBranchDialog({ action, source, sourceProjectId, sourceWorkspace, sessions, onClose, onCreated }: Props) {
  const candidates = useMemo(
    () => sessions.filter((session) => session.name !== source && !session.name.includes('/')),
    [sessions, source],
  );
  const [target, setTarget] = useState(candidates[0]?.name || '');
  const [name, setName] = useState('');
  const [mode, setMode] = useState<'auto' | 'direct' | 'summary' | 'dialogue'>('auto');
  const [threshold, setThreshold] = useState(12000);
  const [rounds, setRounds] = useState(2);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const targetSession = candidates.find((session) => session.name === target);
  const crossProject = Boolean(action === 'merge' && sourceProjectId && targetSession?.project_id && sourceProjectId !== targetSession.project_id);

  const submit = async () => {
    setBusy(true);
    setError('');
    try {
      const result = action === 'fork'
        ? await forkSession(source, name.trim() || undefined, sourceWorkspace)
        : await mergeSessions({
          left: source,
          right: target,
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

  const disabled = busy || (action === 'merge' && !target);
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
      <div style={{ width: 520, maxWidth: '100%', maxHeight: '90%', overflow: 'auto', background: '#181818', border: '1px solid #4b4b4b', borderRadius: 8, boxShadow: '0 18px 60px rgba(0,0,0,.5)' }}>
        <div style={{ display: 'flex', alignItems: 'center', padding: '13px 16px', borderBottom: '1px solid #333' }}>
          <div style={{ flex: 1 }}>
            <div style={{ color: '#f2f2f2', fontSize: 14, fontWeight: 600 }}>{action === 'fork' ? 'Fork Session' : 'Merge Sessions'}</div>
            <div style={{ color: '#8f8f8f', fontSize: 11, marginTop: 3 }}>来源始终只读；结果会保存为一个带血缘记录的新 Session。</div>
          </div>
          <button onClick={onClose} disabled={busy} style={{ color: '#aaa', background: 'transparent', border: 0, cursor: 'pointer', fontSize: 18 }}>×</button>
        </div>

        <div style={{ padding: 16, display: 'grid', gap: 13 }}>
          <label style={{ color: '#aaa', fontSize: 11 }}>
            左侧来源
            <input value={source} disabled style={{ ...fieldStyle, marginTop: 5, color: '#999' }} />
          </label>

          {action === 'merge' && <>
            <label style={{ color: '#aaa', fontSize: 11 }}>
              要合并的另一个 Session
              <select value={target} onChange={(event) => {
                const next = event.target.value;
                setTarget(next);
                const candidate = candidates.find((session) => session.name === next);
                if (mode === 'direct' && sourceProjectId && candidate?.project_id !== sourceProjectId) setMode('summary');
              }} style={{ ...fieldStyle, marginTop: 5 }}>
                {candidates.map((session) => <option key={session.name} value={session.name}>{session.project_title ? `${session.project_title} / ` : ''}{session.name} · {session.message_count} messages</option>)}
              </select>
            </label>
            <label style={{ color: '#aaa', fontSize: 11 }}>
              合并方法
              <select value={mode} onChange={(event) => setMode(event.target.value as typeof mode)} style={{ ...fieldStyle, marginTop: 5 }}>
                <option value="auto">Auto · 长度自适应</option>
                <option value="direct" disabled={crossProject}>Direct · 原样追加{crossProject ? '（仅同项目）' : ''}</option>
                <option value="summary">Summary · 双分支独立摘要</option>
                <option value="dialogue">Dialogue · 两分支 Agent 对话</option>
              </select>
            </label>
            <div style={{ padding: '9px 11px', color: '#bdbdbd', background: '#202020', borderLeft: '2px solid #3794ff', fontSize: 11, lineHeight: 1.45 }}>
              {crossProject
                ? '跨项目合并会把结果保存到左侧项目。为避免旧文件路径污染新项目，只允许分别摘要或 Agent 对话；Auto 会自动使用 Summary。'
                : modeDescriptions[mode]}
            </div>
            {mode === 'auto' && <label style={{ color: '#aaa', fontSize: 11 }}>
              Auto 摘要阈值（估算 tokens）
              <input type="number" min={256} max={1000000} value={threshold} onChange={(event) => setThreshold(Number(event.target.value) || 12000)} style={{ ...fieldStyle, marginTop: 5 }} />
            </label>}
            {mode === 'dialogue' && <label style={{ color: '#aaa', fontSize: 11 }}>
              A/B 对话轮数（1–4）
              <input type="number" min={1} max={4} value={rounds} onChange={(event) => setRounds(Math.max(1, Math.min(4, Number(event.target.value) || 2)))} style={{ ...fieldStyle, marginTop: 5 }} />
            </label>}
          </>}

          <label style={{ color: '#aaa', fontSize: 11 }}>
            新 Session 名称（留空自动生成）
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如 feature-a-merged" style={{ ...fieldStyle, marginTop: 5 }} />
          </label>
          {error && <div style={{ padding: '8px 10px', color: '#f48771', background: '#301b1b', border: '1px solid #6d3030', borderRadius: 4, fontSize: 11 }}>{error}</div>}
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '12px 16px', borderTop: '1px solid #333' }}>
          <button onClick={onClose} disabled={busy} style={{ padding: '6px 13px', color: '#ddd', background: '#2a2a2a', border: '1px solid #444', borderRadius: 4, cursor: 'pointer' }}>取消</button>
          <button onClick={submit} disabled={disabled} style={{ padding: '6px 14px', color: 'white', background: disabled ? '#3d3d3d' : '#0e639c', border: 0, borderRadius: 4, cursor: disabled ? 'default' : 'pointer', fontWeight: 600 }}>
            {busy ? '处理中…' : action === 'fork' ? '创建 Fork' : '创建 Merged Session'}
          </button>
        </div>
      </div>
    </div>
  );
}
