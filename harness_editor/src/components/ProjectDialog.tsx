import { useState } from 'react';
import { createProject, registerProject, type ProjectPortfolioItem } from '../api/client';
import { pickProjectFolderFromIde } from '../ideBridge';

type Props = {
  onClose: () => void;
  onCreated: (project: ProjectPortfolioItem, openNow: boolean) => void;
};

export default function ProjectDialog({ onClose, onCreated }: Props) {
  const [mode, setMode] = useState<'existing' | 'create'>('existing');
  const [workspace, setWorkspace] = useState('');
  const [parent, setParent] = useState('');
  const [name, setName] = useState('');
  const [title, setTitle] = useState('');
  const [openNow, setOpenNow] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const pick = async (target: 'workspace' | 'parent') => {
    setError('');
    try {
      const value = await pickProjectFolderFromIde(
        target === 'workspace' ? '选择要加入 Portfolio 的 Project 文件夹' : '选择新 Project 的父文件夹',
        target === 'workspace' ? '加入 Project' : '选择父文件夹',
      );
      if (value === null) {
        setError('独立浏览器不能打开系统文件夹选择器，请在输入框粘贴绝对路径。');
      } else if (value) {
        if (target === 'workspace') setWorkspace(value);
        else setParent(value);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const submit = async () => {
    setBusy(true);
    setError('');
    try {
      const result = mode === 'existing'
        ? await registerProject(workspace.trim(), title.trim() || undefined)
        : await createProject(parent.trim(), name.trim(), title.trim() || undefined);
      onCreated(result.project as ProjectPortfolioItem, openNow);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const valid = mode === 'existing' ? Boolean(workspace.trim()) : Boolean(parent.trim() && name.trim());
  return <div className="project-dialog-backdrop" role="dialog" aria-modal="true" aria-label="添加 Project" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <section className="project-dialog">
      <header><div><b>添加 Project</b><small>Project 就是一个 workspace 文件夹；Session 是这个文件夹里的对话与运行记录。</small></div><button onClick={onClose} disabled={busy}>×</button></header>
      <div className="project-dialog-tabs">
        <button className={mode === 'existing' ? 'active' : ''} onClick={() => setMode('existing')}>选择已有文件夹</button>
        <button className={mode === 'create' ? 'active' : ''} onClick={() => setMode('create')}>创建新文件夹</button>
      </div>
      <div className="project-dialog-body">
        {mode === 'existing' ? <label><span>Project 文件夹</span><div className="project-path-row"><input value={workspace} onChange={(event) => setWorkspace(event.target.value)} placeholder="例如 C:\\Users\\me\\Desktop\\my-project" /><button onClick={() => void pick('workspace')}>浏览…</button></div><small>不会移动或复制文件，只会把这个 workspace 加入 Portfolio。</small></label> : <>
          <label><span>父文件夹</span><div className="project-path-row"><input value={parent} onChange={(event) => setParent(event.target.value)} placeholder="例如 C:\\Users\\me\\Desktop" /><button onClick={() => void pick('parent')}>浏览…</button></div></label>
          <label><span>新文件夹名称</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder="my-new-project" /><small>只创建一个空文件夹并加入 Portfolio，不会自动生成代码。</small></label>
        </>}
        <label><span>显示名称（可选）</span><input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={name || '默认使用文件夹名'} /></label>
        <label className="project-open-choice"><input type="checkbox" checked={openNow} onChange={(event) => setOpenNow(event.target.checked)} /> 完成后在新的 IDE 窗口打开</label>
        {error && <div className="project-dialog-error">{error}</div>}
      </div>
      <footer><button onClick={onClose} disabled={busy}>取消</button><button className="primary" disabled={!valid || busy} onClick={() => void submit()}>{busy ? '处理中…' : mode === 'existing' ? '加入 Portfolio' : '创建 Project'}</button></footer>
    </section>
  </div>;
}
