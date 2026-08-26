import { useCallback, useEffect, useMemo, useState } from 'react';
import * as api from '../api/client';
import { openFileInIde, reviewAgentChangeInIde } from '../ideBridge';

type ReviewHunk = {
  id: string;
  ordinal: number;
  tag: string;
  old_start: number;
  old_lines: string[];
  new_lines: string[];
  status: 'pending' | 'accepted' | 'rejected';
  can_undo: boolean;
};

type ReviewChange = {
  id: string;
  index: number;
  transaction_id: string;
  file_path: string;
  source_path?: string;
  materialized_path?: string;
  change_type: 'text' | 'binary' | 'move';
  status: 'pending' | 'partial' | 'accepted' | 'rejected' | 'conflict';
  tool_name: string;
  is_new_file: boolean;
  is_deleted_file: boolean;
  old_size?: number;
  new_size?: number;
  base_revision?: string;
  proposed_revision?: string;
  materialized_revision?: string;
  conflict?: { message?: string; expected_revision?: string; current_revision?: string };
  hunks: ReviewHunk[];
};

const clean = (line: string) => line.replace(/\r?\n$/, '');

export default function ChangeDashboard() {
  const [changes, setChanges] = useState<ReviewChange[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    try {
      const currentWorkspace = await api.getWorkspace().catch(() => null);
      const response = await api.listAgentChanges(undefined, currentWorkspace?.workspace || undefined);
      setChanges(Array.isArray(response) ? response : []);
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const tick = () => { if (!document.hidden && !busy) void refresh(); };
    const timer = window.setInterval(tick, 4000);
    document.addEventListener('visibilitychange', tick);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', tick);
    };
  }, [busy, refresh]);

  const pending = useMemo(
    () => changes.reduce((total, change) => total + change.hunks.filter((hunk) => hunk.status === 'pending').length, 0),
    [changes],
  );

  const apply = useCallback(async (
    change: ReviewChange,
    action: 'accept' | 'reject' | 'undo',
    hunkId?: string,
    deleteAlreadyConfirmed = false,
  ) => {
    let confirmDelete = deleteAlreadyConfirmed;
    if (action === 'reject' && change.is_new_file && !confirmDelete) {
      confirmDelete = window.confirm(`拒绝这个新文件会将其删除：\n${change.file_path}\n\n继续吗？`);
      if (!confirmDelete) return;
    }
    setBusy(`${change.id}:${hunkId || 'all'}`);
    try {
      const handledByIde = await reviewAgentChangeInIde(action, change.id, hunkId, confirmDelete);
      if (!handledByIde) {
        await api.reviewAgentChange(action, change.id, {
          hunk_id: hunkId,
          reason: action === 'reject' ? 'Rejected in Agent Workbench' : undefined,
          confirm_delete: confirmDelete,
        });
      }
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }, [refresh]);

  const applyGlobal = useCallback(async (action: 'accept' | 'reject') => {
    const targets = changes.filter((change) => change.hunks.some((hunk) => hunk.status === 'pending'));
    if (!targets.length) return;
    const newFiles = targets.filter((change) => change.is_new_file);
    let confirmed = false;
    if (action === 'reject' && newFiles.length) {
      confirmed = window.confirm(`全部拒绝会删除 ${newFiles.length} 个 Agent 新建文件。继续吗？`);
      if (!confirmed) return;
    }
    setBusy('global');
    try {
      for (const change of targets) {
        const handledByIde = await reviewAgentChangeInIde(action, change.id, undefined, confirmed && change.is_new_file);
        if (!handledByIde) {
          await api.reviewAgentChange(action, change.id, {
            reason: action === 'reject' ? 'Global rejection in Agent Workbench' : undefined,
            confirm_delete: confirmed && change.is_new_file,
          });
        }
      }
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  }, [changes, refresh]);

  return (
    <main className="change-dashboard">
      <header className="change-dashboard-header">
        <div><h2>Agent 代码改动</h2><p>改动已经写入 Workspace；这里与 Void 编辑器使用同一个持久事务。</p></div>
        <div className="change-dashboard-actions">
          <span className={pending ? 'pending' : ''}>{pending} 段待审</span>
          <button onClick={refresh} disabled={!!busy}>刷新</button>
          <button className="accept" onClick={() => applyGlobal('accept')} disabled={!pending || !!busy}>全部接受</button>
          <button className="reject" onClick={() => applyGlobal('reject')} disabled={!pending || !!busy}>全部拒绝</button>
        </div>
      </header>
      {error && <div className="change-dashboard-error">{error}</div>}
      {!changes.length && <div className="change-dashboard-empty">当前没有 Agent 文件改动。运行会写文件的 DAG 后，此处会自动出现逐段审阅。</div>}
      <div className="change-dashboard-list">
        {changes.map((change) => {
          const filePending = change.hunks.some((hunk) => hunk.status === 'pending');
          return <section className={`change-dashboard-file ${change.status}`} key={change.id}>
            <div className="change-dashboard-file-head">
              <div>
                <button className="change-open-file" onClick={() => openFileInIde(change.file_path)} title="在 Void 编辑器打开"><strong>{change.change_type === 'move' ? `${change.source_path} → ${change.file_path}` : change.file_path}</strong></button>
                <span>{change.tool_name} · {change.change_type}{change.is_new_file ? ' · 新文件' : ''}{change.is_deleted_file ? ' · 删除文件' : ''}</span>
              </div>
              <div>
                <span className="change-status">{change.status}</span>
                {filePending && <><button className="accept" onClick={() => apply(change, 'accept')} disabled={!!busy}>接受文件</button><button className="reject" onClick={() => apply(change, 'reject')} disabled={!!busy}>拒绝文件</button></>}
              </div>
            </div>
            {change.conflict && <div className="change-conflict"><b>文件发生外部修改</b><span>{change.conflict.message}</span><code>{change.conflict.expected_revision} → {change.conflict.current_revision}</code></div>}
            <details className="change-revisions"><summary>事务与 revision</summary><code>{change.transaction_id}</code><code>base {change.base_revision}</code><code>live {change.materialized_revision}</code><code>proposed {change.proposed_revision}</code></details>
            {change.hunks.map((hunk) => <article className={`change-dashboard-hunk ${hunk.status}`} key={hunk.id}>
              <div className="change-dashboard-hunk-head">
                <button className="change-open-hunk" onClick={() => openFileInIde(change.file_path, hunk.old_start + 1)}>#{hunk.ordinal + 1} · {hunk.tag} · L{hunk.old_start + 1}</button>
                <div>{hunk.status === 'pending' ? <><button className="accept" onClick={() => apply(change, 'accept', hunk.id)} disabled={!!busy}>接受</button><button className="reject" onClick={() => apply(change, 'reject', hunk.id)} disabled={!!busy}>拒绝</button></> : <><span>{hunk.status}</span>{hunk.can_undo && <button onClick={() => apply(change, 'undo', hunk.id)} disabled={!!busy}>撤销决定</button>}</>}</div>
              </div>
              {change.change_type === 'binary'
                ? <div className="binary-change">二进制整文件改动：{change.old_size ?? '不存在'} B → {change.new_size ?? '不存在'} B</div>
                : change.change_type === 'move'
                  ? <div className="binary-change">文件移动不改变内容；拒绝会恢复原路径。</div>
                  : <pre className="change-inline-diff">{hunk.old_lines.map((line, index) => <span className="removed" key={`o-${index}`}>− {clean(line)}{`\n`}</span>)}{hunk.new_lines.map((line, index) => <span className="added" key={`n-${index}`}>+ {clean(line)}{`\n`}</span>)}</pre>}
            </article>)}
          </section>;
        })}
      </div>
    </main>
  );
}
