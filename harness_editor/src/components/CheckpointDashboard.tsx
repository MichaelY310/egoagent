import { useCallback, useEffect, useMemo, useState } from 'react';
import * as api from '../api/client';
import { openFileInIde } from '../ideBridge';

type RestoreImpact = {
  path: string;
  relative_path?: string;
  artifact_type: 'file' | 'harness' | 'identity' | 'environment';
  action: 'unchanged' | 'restore' | 'recreate' | 'delete';
  binary: boolean;
  checkpoint_revision: string;
  current_revision: string;
  checkpoint_size?: number | null;
  current_size?: number | null;
  requires_delete_confirmation?: boolean;
};

type Checkpoint = {
  id: string;
  label: string;
  timestamp: number;
  trigger: string;
  workspace?: string;
  file_count: number;
  changed_count: number;
  mutation_counts?: Record<string, number>;
  changed_files?: RestoreImpact[];
  metadata?: Record<string, unknown>;
};

type Preview = {
  ok: boolean;
  checkpoint_id: string;
  impacts: RestoreImpact[];
  changed: number;
  expected_revisions: Record<string, string>;
};

const actionLabel: Record<string, string> = {
  unchanged: '无变化',
  restore: '恢复旧内容',
  recreate: '重新创建',
  delete: '删除',
};

function shortRevision(value?: string) {
  if (!value || value === 'missing') return '不存在';
  return value.replace('sha256:', '').slice(0, 10);
}

export default function CheckpointDashboard() {
  const [workspace, setWorkspace] = useState('');
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());
  const [label, setLabel] = useState('手动检查点');
  const [filesText, setFilesText] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const refresh = useCallback(async (workspaceOverride?: string) => {
    const target = workspaceOverride ?? workspace;
    try {
      setError('');
      const list = await api.listCheckpoints(target);
      setCheckpoints(Array.isArray(list) ? list : []);
      if (selectedId && !list.some((item: Checkpoint) => item.id === selectedId)) {
        setSelectedId('');
        setPreview(null);
      }
    } catch (reason) {
      setError(String((reason as Error).message || reason));
    }
  }, [workspace, selectedId]);

  useEffect(() => {
    api.getWorkspace().then((result) => {
      const value = String(result?.workspace || '');
      setWorkspace(value);
      void refresh(value);
    }).catch((reason) => setError(String(reason?.message || reason)));
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    setBusy(true);
    api.previewCheckpointRestore(selectedId).then((result) => {
      setPreview(result);
      setSelectedFiles(new Set((result.impacts || []).filter((item: RestoreImpact) => item.action !== 'unchanged').map((item: RestoreImpact) => item.path)));
      setError('');
    }).catch((reason) => setError(String(reason?.message || reason))).finally(() => setBusy(false));
  }, [selectedId]);

  const selectedCheckpoint = useMemo(
    () => checkpoints.find((item) => item.id === selectedId),
    [checkpoints, selectedId],
  );

  const create = async () => {
    const files = filesText.split(/\r?\n|,/).map((value) => value.trim()).filter(Boolean);
    if (!workspace.trim()) return setError('请先填写工作区绝对路径');
    if (!files.length) return setError('请至少填写一个要快照的文件路径；可以使用相对工作区路径');
    setBusy(true);
    try {
      const created = await api.createCheckpoint({
        label: label.trim() || '手动检查点',
        workspace: workspace.trim(),
        files,
        metadata: { source: 'workbench' },
      });
      setMessage(`已创建 ${created.label} · ${created.file_count} 个文件`);
      setFilesText('');
      await refresh();
      setSelectedId(created.id);
    } catch (reason) {
      setError(String((reason as Error).message || reason));
    } finally {
      setBusy(false);
    }
  };

  const toggleFile = (path: string) => {
    setSelectedFiles((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;
    });
  };

  const restore = async () => {
    if (!preview || !selectedId || !selectedFiles.size) return;
    const files = [...selectedFiles];
    const selectedImpacts = preview.impacts.filter((item) => selectedFiles.has(item.path));
    const needsDelete = selectedImpacts.some((item) => item.action === 'delete');
    if (needsDelete && !window.confirm('选择的恢复操作会删除检查点时不存在的文件。确认删除吗？')) return;
    setBusy(true);
    setError('');
    try {
      const result = await api.restoreCheckpoint({
        checkpoint_id: selectedId,
        files,
        expected_revisions: Object.fromEntries(files.map((path) => [path, preview.expected_revisions[path]])),
        confirm_delete: needsDelete,
      });
      if (!result.ok) {
        const conflicts = (result.conflicts || []).map((item: { path: string }) => item.path).join(', ');
        const pending = (result.pending_deletes || []).join(', ');
        setError(result.error || (conflicts ? `文件在预览后又被修改：${conflicts}` : pending ? `仍需确认删除：${pending}` : (result.errors || []).join('; ') || '恢复未完成'));
      } else {
        setMessage(`已安全恢复 ${result.restored_files} 个文件；恢复本身也可在“Agent 改动”中逐段审阅`);
      }
      const nextPreview = await api.previewCheckpointRestore(selectedId);
      setPreview(nextPreview);
      setSelectedFiles(new Set((nextPreview.impacts || []).filter((item: RestoreImpact) => item.action !== 'unchanged').map((item: RestoreImpact) => item.path)));
      await refresh();
    } catch (reason) {
      setError(String((reason as Error).message || reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="checkpoint-dashboard">
      <header className="checkpoint-header">
        <div>
          <h2>检查点时间线</h2>
          <p>保存文件、Harness、Identity 与 Environment 快照；恢复前显示精确影响并检查预览后的手动修改。</p>
        </div>
        <button className="btn btn-secondary" onClick={() => refresh()} disabled={busy}>↻ 刷新</button>
      </header>

      {(message || error) && <div className={`checkpoint-notice ${error ? 'error' : 'success'}`}>{error || message}</div>}

      <section className="checkpoint-create">
        <label>工作区<input value={workspace} onChange={(event) => setWorkspace(event.target.value)} onBlur={() => refresh()} /></label>
        <label>名称<input value={label} onChange={(event) => setLabel(event.target.value)} /></label>
        <label className="checkpoint-files-input">文件（每行一个，支持相对路径）<textarea rows={3} value={filesText} onChange={(event) => setFilesText(event.target.value)} placeholder={'src/app.ts\nharness/my_agent/config.json\nidentity/coder/id.json'} /></label>
        <button className="btn btn-exec" onClick={create} disabled={busy}>＋ 创建检查点</button>
      </section>

      <div className="checkpoint-layout">
        <aside className="checkpoint-timeline" aria-label="检查点时间线">
          {!checkpoints.length && <div className="checkpoint-empty">还没有检查点。先选择重要文件创建一个。</div>}
          {checkpoints.map((checkpoint) => (
            <button key={checkpoint.id} className={`checkpoint-card ${selectedId === checkpoint.id ? 'selected' : ''}`} onClick={() => setSelectedId(checkpoint.id)}>
              <span className="checkpoint-dot" />
              <strong>{checkpoint.label}</strong>
              <time>{new Date(checkpoint.timestamp * 1000).toLocaleString()}</time>
              <span>{checkpoint.file_count} 个快照 · 当前 {checkpoint.changed_count || 0} 个变化</span>
              <div className="checkpoint-chips">
                {Object.entries(checkpoint.mutation_counts || {}).filter(([, count]) => count > 0).map(([kind, count]) => <em key={kind}>{kind} {count}</em>)}
              </div>
            </button>
          ))}
        </aside>

        <main className="checkpoint-preview">
          {!selectedCheckpoint && <div className="checkpoint-empty">选择时间线中的检查点以预览恢复影响。</div>}
          {selectedCheckpoint && (
            <>
              <div className="checkpoint-preview-title">
                <div><h3>{selectedCheckpoint.label}</h3><span>{selectedCheckpoint.trigger} · {selectedCheckpoint.id}</span></div>
                <button className="btn btn-exec" disabled={busy || !selectedFiles.size} onClick={restore}>恢复所选 {selectedFiles.size || ''}</button>
              </div>
              {busy && !preview && <div className="checkpoint-empty">正在计算文件修订…</div>}
              {preview?.impacts.map((impact) => (
                <label key={impact.path} className={`checkpoint-impact ${impact.action}`}>
                  <input type="checkbox" checked={selectedFiles.has(impact.path)} disabled={impact.action === 'unchanged'} onChange={() => toggleFile(impact.path)} />
                  <span className="checkpoint-impact-main">
                    <button className="checkpoint-open-file" onClick={(event) => { event.preventDefault(); openFileInIde(impact.path); }} title="在 Void 编辑器打开"><strong>{impact.relative_path || impact.path}</strong></button>
                    <small>{impact.artifact_type}{impact.binary ? ' · binary' : ''} · {actionLabel[impact.action]}</small>
                  </span>
                  <code>{shortRevision(impact.current_revision)} → {shortRevision(impact.checkpoint_revision)}</code>
                </label>
              ))}
              {preview && !preview.impacts.length && <div className="checkpoint-empty">这个旧检查点没有可恢复的快照内容。</div>}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
