import { useEffect, useMemo, useState } from 'react';
import * as api from '../api/client';

type Destination = 'harness' | 'tasks' | 'evolution' | 'packages' | 'changes' | 'sessions' | 'coc';

interface StudioHomeProps {
  onNavigate: (destination: Destination) => void;
  onOpenHarness: (name: string) => void;
}

interface RecentRun {
  id?: string;
  task_id?: string;
  status?: string;
  created_at?: number;
  completed_at?: number;
  evaluation?: { score?: number; pass_score?: number; checks?: Array<{ id?: string; passed?: boolean; summary?: string }> };
  selection?: { harness?: string; identity?: string };
}

export default function StudioHome({ onNavigate, onOpenHarness }: StudioHomeProps) {
  const [runs, setRuns] = useState<RecentRun[]>([]);
  const [proposals, setProposals] = useState<Array<Record<string, any>>>([]);
  const [workspace, setWorkspace] = useState<{ workspace?: string; name?: string }>({});
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([api.listTaskBenchRuns(), api.listEvolutionProposals(), api.getWorkspace()])
      .then(([loadedRuns, loadedProposals, currentWorkspace]) => {
        setRuns(Array.isArray(loadedRuns) ? loadedRuns.slice(0, 8) : []);
        setProposals(Array.isArray(loadedProposals) ? loadedProposals : []);
        setWorkspace(currentWorkspace || {});
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, []);

  const terminalRuns = useMemo(() => runs.filter((run) => ['passed', 'failed', 'error', 'timeout', 'stopped'].includes(run.status || '')), [runs]);
  const failedRuns = useMemo(() => terminalRuns.filter((run) => run.status !== 'passed'), [terminalRuns]);
  const passedRuns = terminalRuns.filter((run) => run.status === 'passed');
  const trusted = proposals.filter((proposal) => proposal.status === 'trusted').length;
  const experimental = proposals.filter((proposal) => ['experimental', 'quarantined'].includes(proposal.status)).length;
  const latestFailure = failedRuns[0];

  const evolveLatestFailure = () => {
    if (latestFailure) {
      const failedChecks = latestFailure.evaluation?.checks?.filter((check) => !check.passed) || [];
      localStorage.setItem('evolution_observations', [
        `Task Bench run ${latestFailure.id || 'unknown'} failed.`,
        `Task: ${latestFailure.task_id || 'unknown'}.`,
        `Harness: ${latestFailure.selection?.harness || 'unknown'}; Identity: ${latestFailure.selection?.identity || 'unknown'}.`,
        ...failedChecks.map((check) => `Failed check ${check.id || 'unknown'}: ${check.summary || 'no summary'}`),
      ].join('\n'));
    }
    onNavigate('evolution');
  };

  return <main className="studio-home">
    <section className="studio-home-hero">
      <div>
        <span className="studio-eyebrow">{workspace.name || 'Local workspace'}</span>
        <h1>Build an agent. Prove it works. Put it to work.</h1>
        <p>日常使用保持简单；只有观察到失败时，才把一次运行提升为可复现实验，再决定是否进化与发布。</p>
      </div>
      <div className="studio-home-actions">
        <button className="primary" onClick={() => onNavigate('harness')}>打开 Agent Builder</button>
        <button onClick={() => onNavigate('tasks')}>运行一个 Task</button>
      </div>
    </section>

    <section className="studio-journey" aria-label="Agent lifecycle">
      <button onClick={() => onNavigate('harness')}><span>1</span><b>Build</b><small>Identity + EGO + DAG</small></button>
      <i>→</i>
      <button onClick={() => onNavigate('tasks')}><span>2</span><b>Evaluate</b><small>数据集、回放、确定性评分</small></button>
      <i>→</i>
      <button onClick={evolveLatestFailure}><span>3</span><b>Improve</b><small>仅对真实失败提出最小改动</small></button>
      <i>→</i>
      <button onClick={() => onNavigate('packages')}><span>4</span><b>Deploy</b><small>版本化能力包与回滚</small></button>
    </section>

    {error && <div className="studio-home-error">Runtime 暂不可用：{error}</div>}

    <section className="studio-home-grid">
      <article className="studio-home-card run-card">
        <header><div><span className="studio-eyebrow">Evidence</span><h2>最近评测</h2></div><button onClick={() => onNavigate('tasks')}>全部运行</button></header>
        <div className="studio-metrics">
          <div><strong>{terminalRuns.length}</strong><span>已完成</span></div>
          <div className="good"><strong>{passedRuns.length}</strong><span>通过</span></div>
          <div className={failedRuns.length ? 'bad' : ''}><strong>{failedRuns.length}</strong><span>需调查</span></div>
        </div>
        {runs.length ? <div className="studio-run-list">{runs.slice(0, 4).map((run) => <button key={run.id} onClick={() => onNavigate('tasks')}>
          <span className={`studio-run-dot ${run.status || ''}`} />
          <div><b>{run.task_id || 'Untitled task'}</b><small>{run.selection?.harness || 'harness'} · {run.selection?.identity || 'identity'}</small></div>
          <em>{run.evaluation?.score == null ? run.status : `${Math.round(run.evaluation.score * 100)}%`}</em>
        </button>)}</div> : <div className="studio-empty-state">还没有评测记录。先跑一个 starter task，DAG 轨迹、分数和产物会留在这里。</div>}
      </article>

      <article className="studio-home-card signal-card">
        <header><div><span className="studio-eyebrow">Evolution signal</span><h2>{latestFailure ? '有一个失败值得调查' : '暂时无需进化'}</h2></div><span className={`studio-signal ${latestFailure ? 'attention' : ''}`}>{latestFailure ? 'Review' : 'Stable'}</span></header>
        {latestFailure ? <>
          <p><b>{latestFailure.task_id}</b> 在 {latestFailure.selection?.harness || 'selected harness'} 上未通过。先复现和诊断；系统不会因一次失败自动永久修改 Agent。</p>
          <div className="studio-card-actions"><button className="primary" onClick={evolveLatestFailure}>从这次失败创建实验</button><button onClick={() => onNavigate('sessions')}>查看证据</button></div>
        </> : <>
          <p>继续正常使用 Agent。失败、回归或重复的人工纠正出现时，Studio 会把它变成候选实验，而不是偷偷改写你的 Agent。</p>
          <div className="studio-card-actions"><button onClick={() => onNavigate('tasks')}>建立基线</button></div>
        </>}
      </article>

      <article className="studio-home-card compact-card">
        <header><div><span className="studio-eyebrow">Promotion</span><h2>演进状态</h2></div><button onClick={() => onNavigate('evolution')}>进入实验室</button></header>
        <div className="studio-metrics two"><div><strong>{experimental}</strong><span>隔离实验</span></div><div className="good"><strong>{trusted}</strong><span>已验证</span></div></div>
        <p>只有 validation、held-out 与 regression 证据都通过的候选才进入 trusted；其余保持隔离或回滚。</p>
      </article>

      <article className="studio-home-card play-card">
        <header><div><span className="studio-eyebrow">Play · Multi-agent</span><h2>CoC 跑团实验桌</h2></div><span className="studio-signal">2 scenarios</span></header>
        <p>先车一张可跨团复用的人物卡 Identity。KP 与两名 AI 调查员在 DAG 中协作；数值与物品 Tool 由受限事务持久更新。</p>
        <div className="studio-card-actions"><button className="primary" onClick={() => onNavigate('coc')}>人物卡与开团</button><button onClick={() => onOpenHarness('coc_lightless_beacon')}>快速打开模组</button></div>
      </article>

      <article className="studio-home-card compact-card">
        <header><div><span className="studio-eyebrow">Review</span><h2>可逆是默认行为</h2></div><button onClick={() => onNavigate('changes')}>审阅改动</button></header>
        <p>文件修改、Identity/Skill 安装、Harness 结构变化和能力包发布都有单独的审阅、版本与恢复路径。</p>
      </article>
    </section>
  </main>;
}
