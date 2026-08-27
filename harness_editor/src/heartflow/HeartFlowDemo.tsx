import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  acknowledgeHeartFlowEvents,
  focusHeartFlowProject,
  getHeartFlowStatus,
  parkHeartFlowProject,
  stopHeartFlow,
  updateHeartFlowSettings,
  listProjectSessions,
  type HeartFlowCapsule,
  type HeartFlowStatus,
  type PortfolioSession,
  type ProjectPortfolioItem,
} from '../api/client';
import { openWorkspaceInIde } from '../ideBridge';
import SessionBranchDialog from '../components/SessionBranchDialog';
import './heart-flow.css';
import './heart-flow-theme.css';

const relativeTime = (timestamp = 0) => {
  if (!timestamp) return '尚未记录';
  const seconds = Math.max(0, Date.now() / 1000 - timestamp);
  if (seconds < 60) return '刚刚';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
};

const timeLeft = (endsAt = 0) => {
  const seconds = Math.max(0, Math.ceil(endsAt - Date.now() / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
};

export default function HeartFlowDemo({ onOpenSessions }: { onOpenSessions?: () => void }) {
  const [status, setStatus] = useState<HeartFlowStatus | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [clock, setClock] = useState(Date.now());
  const [goal, setGoal] = useState('');
  const [nextAction, setNextAction] = useState('');
  const [branchAction, setBranchAction] = useState<'fork' | 'merge' | null>(null);
  const [branchSessions, setBranchSessions] = useState<PortfolioSession[]>([]);

  const refresh = useCallback(async () => {
    try {
      setStatus(await getHeartFlowStatus());
      setError('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      setClock(Date.now());
      if (!document.hidden) void refresh();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    setGoal(status?.reentry_capsule?.goal || '');
    setNextAction(status?.reentry_capsule?.next_action || '');
  }, [status?.reentry_capsule?.id, status?.reentry_capsule?.updated_at]);

  const run = async (key: string, operation: () => Promise<unknown>) => {
    setBusy(key);
    setError('');
    try {
      await operation();
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy('');
    }
  };

  const focusProject = async (project: ProjectPortfolioItem) => {
    const previous = status?.focus.project_id;
    if (previous && previous !== project.id) {
      await parkHeartFlowProject({ project_id: previous });
    }
    if (!status?.capsules[project.id]) {
      await parkHeartFlowProject({ project_id: project.id });
    }
    await focusHeartFlowProject(project.id, status?.settings.focus_minutes);
  };

  const saveCapsule = async () => {
    const projectId = status?.focus.project_id;
    if (!projectId) return;
    await parkHeartFlowProject({
      project_id: projectId,
      session: status?.reentry_capsule?.session || undefined,
      capsule: { goal, next_action: nextAction },
    });
  };

  const openBranch = async (action: 'fork' | 'merge') => {
    if (!status?.reentry_capsule?.session) {
      setError('当前续接胶囊还没有绑定 Session。先在这个 Project 中运行一次 Agent。');
      return;
    }
    setBusy(`branch:${action}`);
    setError('');
    try {
      setBranchSessions(await listProjectSessions({ limit: 1000 }));
      setBranchAction(action);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy('');
    }
  };

  const focused = status?.focused_project;
  const capsule = status?.reentry_capsule;
  const immediate = useMemo(() => status?.inbox.filter((item) => item.delivery === 'now') || [], [status]);
  const batched = useMemo(() => status?.inbox.filter((item) => item.delivery === 'batched') || [], [status]);
  void clock;

  if (!status && !error) return <div className="heart-flow-loading">正在建立 Flow Relay…</div>;
  if (status && !status.enabled) return <div className="heart-flow-shell"><div className="heart-flow-empty"><b>Heart Flow 已关闭</b><br />删除该实验不会影响 Project Portfolio；如需再次预览，请移除 `EGOAGENT_HEART_FLOW_ENABLED=0` 后重启本地 runtime。</div></div>;

  return (
    <div className="heart-flow-shell">
      <section className="heart-flow-hero">
        <div>
          <div className="heart-flow-eyebrow"><span /> OPTIONAL EXPERIMENT · 可整块删除</div>
          <h1>Heart Flow <small>Flow Relay</small></h1>
          <p>一次只把一个 Project 放在你的注意力前台；后台 Agent 继续运行，消息在自然断点批量交付，切换时用可编辑的续接胶囊接住思路。</p>
        </div>
        <div className="heart-flow-policy">
          <label>专注时长
            <select value={status?.settings.focus_minutes || 50} onChange={(event) => void run('settings', () => updateHeartFlowSettings({ focus_minutes: Number(event.target.value) }))}>
              {[25, 40, 50, 75, 90].map((value) => <option key={value} value={value}>{value} min</option>)}
            </select>
          </label>
          <label>前台 WIP
            <select value={status?.settings.wip_limit || 2} onChange={(event) => void run('settings', () => updateHeartFlowSettings({ wip_limit: Number(event.target.value) }))}>
              {[1, 2, 3, 4].map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
          <label>通知
            <select value={status?.settings.notification_policy || 'natural_breakpoints'} onChange={(event) => void run('settings', () => updateHeartFlowSettings({ notification_policy: event.target.value as HeartFlowStatus['settings']['notification_policy'] }))}>
              <option value="natural_breakpoints">自然断点</option>
              <option value="focus_end">专注结束</option>
              <option value="immediate">立即</option>
            </select>
          </label>
        </div>
      </section>

      {error && <div className="heart-flow-error"><b>Flow Relay 暂不可用</b><span>{error}</span><button onClick={() => void refresh()}>重试</button></div>}

      <section className={`heart-flow-focus ${focused ? 'active' : ''}`}>
        <div className="heart-flow-focus-mark"><span>{focused ? 'FOCUS' : 'READY'}</span><strong>{focused ? timeLeft(status?.focus.ends_at) : '— —'}</strong></div>
        <div className="heart-flow-focus-copy">
          <small>当前前台 Project</small>
          <h2>{focused?.title || '还没有开始专注'}</h2>
          <p>{focused ? capsule?.next_action || capsule?.goal || '生成一份续接胶囊，给下一次切换留下精确落点。' : '从下方选择一个 Project。开始前只做一次决定，专注期间后台结果不会挤进当前工作。'}</p>
        </div>
        <div className="heart-flow-focus-actions">
          {focused && <button className="hf-button primary" onClick={() => openWorkspaceInIde(focused.workspace, true)}>在 IDE 打开</button>}
          {focused && <button className="hf-button" disabled={Boolean(busy)} onClick={() => void run('park', () => parkHeartFlowProject({ project_id: focused.id }))}>更新胶囊</button>}
          {focused && <button className="hf-button quiet" disabled={Boolean(busy)} onClick={() => void run('stop', stopHeartFlow)}>结束专注</button>}
        </div>
      </section>

      <div className="heart-flow-layout">
        <section className="heart-flow-panel project-panel">
          <header><div><small>PORTFOLIO</small><h3>选择一个注意力前台</h3></div><span>{status?.projects.length || 0} Projects</span></header>
          <div className="heart-flow-projects">
            {status?.projects.filter((project) => project.id !== 'unknown').map((project) => {
              const isFocused = project.id === status.focus.project_id;
              const saved = status.capsules[project.id];
              return <article key={project.id} className={isFocused ? 'focused' : ''}>
                <button className="project-main" onClick={() => void run(`focus:${project.id}`, () => focusProject(project))} disabled={Boolean(busy)}>
                  <span className="project-sigil">{project.title.slice(0, 1).toUpperCase()}</span>
                  <span className="project-copy"><b>{project.title}</b><small>{project.running_count || 0} running · {project.session_count} Sessions</small></span>
                  <span className="project-action">{isFocused ? '前台' : '专注 →'}</span>
                </button>
                <div className="project-meta"><span>{saved ? `胶囊 ${relativeTime(saved.updated_at)}` : '尚无续接胶囊'}</span><button onClick={() => openWorkspaceInIde(project.workspace, true)}>↗ 打开</button></div>
              </article>;
            })}
          </div>
          {(status?.projects.length || 0) > (status?.settings.wip_limit || 2) && <p className="heart-flow-hint">WIP 是软限制：同时运行很多 Agent 没问题，但建议只让 {status?.settings.wip_limit} 个 Project 保持“需要你亲自思考”的前台状态。</p>}
        </section>

        <section className="heart-flow-panel capsule-panel">
          <header><div><small>READY-TO-RESUME CAPSULE</small><h3>把中断点变成下一步</h3></div>{capsule && <div className="capsule-session-actions"><button className="text-button" onClick={() => void openBranch('fork')}>⑂ Fork</button><button className="text-button" onClick={() => void openBranch('merge')}>⇄ Merge</button><button className="text-button" onClick={onOpenSessions}>查看 Session</button></div>}</header>
          {!focused ? <div className="heart-flow-empty">选择一个 Project 后，这里会从最近 Session 提取目标、证据、阻塞和精确下一步。</div> : <>
            <label className="capsule-field"><span>当前目标</span><textarea value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="这个 Project 现在真正要完成什么？" /></label>
            <label className="capsule-field next"><span>恢复后第一步</span><textarea value={nextAction} onChange={(event) => setNextAction(event.target.value)} placeholder="尽可能写成一个可以立即执行的动作" /></label>
            <div className="capsule-grid">
              <CapsuleList title="已完成 / 已知" values={capsule?.progress} empty="等待 Session 证据" />
              <CapsuleList title="阻塞 / 未决" values={capsule?.blockers} empty="没有识别到阻塞" tone="warning" />
              <CapsuleList title="相关文件" values={capsule?.files} empty="没有识别到文件" mono />
              <CapsuleList title="验证状态" values={capsule?.tests} empty="没有识别到测试记录" mono />
            </div>
            <div className="capsule-footer"><span>{capsule?.session ? `来源 ${capsule.session} · ${capsule.message_count} messages` : '还未绑定 Session'}</span><button className="hf-button primary" disabled={Boolean(busy)} onClick={() => void run('save', saveCapsule)}>保存续接胶囊</button></div>
          </>}
        </section>

        <section className="heart-flow-panel inbox-panel">
          <header><div><small>ATTENTION ROUTER</small><h3>只在值得打断时打断</h3></div><span>{immediate.length} now · {batched.length} batched</span></header>
          {immediate.length > 0 && <div className="inbox-section"><b>现在处理</b>{immediate.map((event) => <FlowEvent key={event.id} event={event} />)}</div>}
          <div className="inbox-section batched"><b>下一自然断点再看</b>{batched.map((event) => <FlowEvent key={event.id} event={event} />)}{!batched.length && !immediate.length && <div className="heart-flow-empty compact">后台安静。token 流和中间步骤不会制造通知。</div>}</div>
          {(status?.inbox.length || 0) > 0 && <button className="hf-button wide" disabled={Boolean(busy)} onClick={() => void run('ack', () => acknowledgeHeartFlowEvents(status?.inbox.map((item) => item.id)))}>清空已读</button>}
        </section>
      </div>
      {branchAction && capsule?.session && <SessionBranchDialog
        action={branchAction}
        source={capsule.session}
        sourceProjectId={capsule.project_id}
        sourceWorkspace={capsule.workspace}
        sessions={branchSessions.map((session) => ({
          name: session.name,
          message_count: session.message_count,
          project_id: session.project_id,
          project_title: status?.projects.find((project) => project.id === session.project_id)?.title,
          workspace: session.workspace,
        }))}
        onClose={() => setBranchAction(null)}
        onCreated={() => { setBranchAction(null); onOpenSessions?.(); }}
      />}
    </div>
  );
}

function CapsuleList({ title, values, empty, mono = false, tone = '' }: { title: string; values?: string[]; empty: string; mono?: boolean; tone?: string }) {
  return <div className={`capsule-list ${tone}`}><b>{title}</b>{values?.length ? <ul>{values.map((value, index) => <li key={`${value}-${index}`} className={mono ? 'mono' : ''}>{value}</li>)}</ul> : <span>{empty}</span>}</div>;
}

function FlowEvent({ event }: { event: NonNullable<HeartFlowStatus['inbox']>[number] }) {
  return <article className={`flow-event ${event.urgent ? 'urgent' : ''}`}><span className="event-dot" /><div><b>{event.summary}</b><small>{event.project_title} · {event.harness || event.session || event.run_id.slice(0, 8)}</small></div><time>{relativeTime(event.created_at)}</time></article>;
}
