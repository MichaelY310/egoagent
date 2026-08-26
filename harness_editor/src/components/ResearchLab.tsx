import { useEffect, useMemo, useState } from 'react';
import * as api from '../api/client';

const STAGES = ['retrieve', 'hypothesis', 'plan', 'implement', 'execute', 'analyze', 'repair', 'independent_review', 'report'];

type ProjectSummary = { id: string; objective: string; status: string; current_stage?: string; updated_at: number; revision: number };
type ScienceProject = ProjectSummary & {
  creator: string;
  evidence: Record<string, { id: string; type: string; kind?: string; title?: string; url?: string; path?: string }>;
  experiments: Record<string, { id: string; command: string[]; expected_observation: string }>;
  claims: Record<string, { id: string; text: string; evidence_refs: string[] }>;
  stages: Record<string, { actor: string; at: number; payload: Record<string, unknown> }>;
};

const card: React.CSSProperties = { background: '#151521', border: '1px solid #303044', borderRadius: 10, padding: 16 };
const input: React.CSSProperties = { width: '100%', boxSizing: 'border-box', background: '#0d0d16', color: '#eee', border: '1px solid #3a3a50', borderRadius: 6, padding: '9px 10px' };
const button: React.CSSProperties = { border: '1px solid #4a6a83', borderRadius: 6, padding: '8px 12px', color: '#dff4ff', background: '#193348', cursor: 'pointer' };

function stageTemplate(project: ScienceProject | null): string {
  if (!project?.current_stage) return '{}';
  const evidence = Object.keys(project.evidence || {});
  const first = evidence[0] || 'artifact:ADD_EVIDENCE_FIRST';
  const stage = project.current_stage;
  const templates: Record<string, unknown> = {
    retrieve: { evidence_refs: evidence },
    hypothesis: { hypotheses: [{ id: 'h1', statement: 'A falsifiable statement', falsification: 'Observation that would refute it', evidence_refs: [first] }] },
    plan: { experiments: [{ id: 'e1', command: ['python', 'experiment.py'], expected_observation: 'A measurable result' }] },
    implement: { summary: 'What was implemented', artifact_refs: [first] },
    execute: { results: Object.values(project.experiments || {}).map((item) => ({ experiment_id: item.id, command: item.command, exit_code: 0, artifact_refs: [first] })) },
    analyze: { claims: [{ id: 'c1', text: 'Evidence-supported conclusion', evidence_refs: [first] }] },
    repair: { decision: 'not_needed', reason: 'All planned experiments produced valid evidence' },
    independent_review: { approved: false, claim_ids: Object.keys(project.claims || {}), evidence_refs: evidence },
    report: { summary: 'Final evidence-bound report', claim_ids: Object.keys(project.claims || {}), artifact_refs: [first] },
  };
  return JSON.stringify(templates[stage] || {}, null, 2);
}

export default function ResearchLab() {
  const [view, setView] = useState<'science' | 'conformance'>('science');
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<ScienceProject | null>(null);
  const [objective, setObjective] = useState('');
  const [creator, setCreator] = useState('researcher');
  const [actor, setActor] = useState('researcher');
  const [payload, setPayload] = useState('{}');
  const [artifactPath, setArtifactPath] = useState('');
  const [artifactKind, setArtifactKind] = useState('experiment-output');
  const [sourceUrl, setSourceUrl] = useState('');
  const [sourceTitle, setSourceTitle] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [conformance, setConformance] = useState<any>(null);
  const [benchmark, setBenchmark] = useState<any>(null);

  const refresh = async () => setProjects(await api.listScienceProjects());
  const open = async (id: string) => {
    const value = await api.getScienceProject(id);
    setProject(value);
    setActor(value.current_stage === 'independent_review' ? 'independent-reviewer' : value.creator || 'researcher');
  };
  useEffect(() => { refresh().catch((error) => setMessage(String(error))); }, []);
  useEffect(() => { setPayload(stageTemplate(project)); }, [project?.id, project?.current_stage, project?.revision]);

  const completed = useMemo(() => new Set(Object.keys(project?.stages || {})), [project]);

  const create = async () => {
    setBusy(true); setMessage('');
    try { const value = await api.createScienceProject(objective, creator); setProject(value); setObjective(''); await refresh(); }
    catch (error) { setMessage(String(error)); } finally { setBusy(false); }
  };
  const addArtifact = async () => {
    if (!project) return;
    setBusy(true); setMessage('');
    try { await api.addScienceArtifact(project.id, artifactPath, artifactKind, actor); await open(project.id); setArtifactPath(''); }
    catch (error) { setMessage(String(error)); } finally { setBusy(false); }
  };
  const addSource = async () => {
    if (!project) return;
    setBusy(true); setMessage('');
    try { await api.addScienceSource(project.id, sourceUrl, sourceTitle, actor); await open(project.id); setSourceUrl(''); setSourceTitle(''); }
    catch (error) { setMessage(String(error)); } finally { setBusy(false); }
  };
  const submit = async () => {
    if (!project?.current_stage) return;
    setBusy(true); setMessage('');
    try {
      const parsed = JSON.parse(payload);
      const value = await api.submitScienceStage(project.id, project.current_stage, actor, parsed, project.revision);
      setProject(value); await refresh(); setMessage(`阶段 ${project.current_stage} 已由 ${actor} 提交并通过确定性校验。`);
    } catch (error) { setMessage(String(error)); } finally { setBusy(false); }
  };
  const loadConformance = async () => {
    setBusy(true); setMessage('');
    try { const [contracts, data] = await Promise.all([api.getHarnessConformance(), api.getTranslationBenchmark()]); setConformance(contracts); setBenchmark(data); }
    catch (error) { setMessage(String(error)); } finally { setBusy(false); }
  };
  useEffect(() => { if (view === 'conformance' && !conformance) loadConformance(); }, [view]);
  const runBehavior = async () => {
    setBusy(true); setMessage('正在执行全部离线行为契约…');
    try { const report = await api.runHarnessConformance(true); setConformance((old: any) => ({ ...(old || {}), structural_report: report })); setMessage(`完成：${report.summary.core_passed}/${report.summary.contracts} 个核心契约通过。`); }
    catch (error) { setMessage(String(error)); } finally { setBusy(false); }
  };

  return <div style={{ height: '100%', overflow: 'auto', background: '#0b0b12', color: '#ddd', padding: 20, boxSizing: 'border-box' }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18 }}>
      <h2 style={{ margin: 0, color: '#9bddff' }}>Research Lab</h2>
      <button style={button} onClick={() => setView('science')}>证据科学循环</button>
      <button style={button} onClick={() => setView('conformance')}>Harness Conformance</button>
      <span style={{ color: '#7f8796', marginLeft: 'auto' }}>不接受无工件的模型自述作为实验结果</span>
    </div>
    {message && <div style={{ ...card, borderColor: message.includes('Error') ? '#7d3434' : '#375c70', marginBottom: 14 }}>{message}</div>}

    {view === 'science' && <div style={{ display: 'grid', gridTemplateColumns: '280px minmax(0, 1fr)', gap: 16 }}>
      <aside style={card}>
        <h3 style={{ marginTop: 0 }}>科学项目</h3>
        <textarea style={{ ...input, minHeight: 80 }} placeholder="可证伪的研究目标" value={objective} onChange={(e) => setObjective(e.target.value)} />
        <input style={{ ...input, marginTop: 8 }} value={creator} onChange={(e) => setCreator(e.target.value)} placeholder="创建者 / Identity" />
        <button style={{ ...button, width: '100%', marginTop: 8 }} disabled={busy || !objective.trim()} onClick={create}>创建项目</button>
        <div style={{ marginTop: 18, display: 'grid', gap: 7 }}>
          {projects.map((item) => <button key={item.id} onClick={() => open(item.id)} style={{ ...button, textAlign: 'left', background: project?.id === item.id ? '#274963' : '#121e29' }}>
            <b>{item.id}</b><br/><small>{item.status} · {item.current_stage || 'complete'}</small>
          </button>)}
        </div>
      </aside>
      <main style={{ display: 'grid', gap: 14 }}>
        {!project ? <div style={card}>创建或选择一个项目。所有阶段按固定顺序推进，工件采用 SHA-256 校验。</div> : <>
          <section style={card}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}><div><h3 style={{ margin: 0 }}>{project.objective}</h3><small>{project.id} · revision {project.revision} · creator {project.creator}</small></div><b style={{ color: project.status === 'complete' ? '#7ee2a8' : '#ffd27e' }}>{project.status}</b></div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(9, minmax(72px, 1fr))', gap: 5, marginTop: 16 }}>
              {STAGES.map((stage, index) => <div key={stage} style={{ borderRadius: 6, padding: 7, textAlign: 'center', fontSize: 11, background: completed.has(stage) ? '#17452f' : project.current_stage === stage ? '#2d5470' : '#22222f', color: completed.has(stage) ? '#8ef2b6' : '#bbc2cd' }}><b>{index + 1}</b><br/>{stage}</div>)}
            </div>
          </section>
          <section style={{ ...card, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <div><h4 style={{ marginTop: 0 }}>注册本地工件</h4><input style={input} value={artifactPath} onChange={(e) => setArtifactPath(e.target.value)} placeholder="仓库内文件的绝对路径"/><input style={{ ...input, marginTop: 8 }} value={artifactKind} onChange={(e) => setArtifactKind(e.target.value)} placeholder="paper / code / output / report"/><button style={{ ...button, marginTop: 8 }} disabled={busy || !artifactPath} onClick={addArtifact}>复制、哈希并注册</button></div>
            <div><h4 style={{ marginTop: 0 }}>注册外部来源</h4><input style={input} value={sourceUrl} onChange={(e) => setSourceUrl(e.target.value)} placeholder="https://…"/><input style={{ ...input, marginTop: 8 }} value={sourceTitle} onChange={(e) => setSourceTitle(e.target.value)} placeholder="来源标题"/><button style={{ ...button, marginTop: 8 }} disabled={busy || !sourceUrl} onClick={addSource}>注册引用</button></div>
            <div style={{ gridColumn: '1 / -1' }}><small style={{ color: '#8d96a5' }}>Evidence ledger</small><pre style={{ background: '#090911', padding: 10, overflow: 'auto', maxHeight: 180 }}>{JSON.stringify(project.evidence, null, 2)}</pre></div>
          </section>
          {project.current_stage && <section style={card}>
            <h3 style={{ marginTop: 0 }}>当前阶段：{project.current_stage}</h3>
            <p style={{ color: '#949cab' }}>模板只是可编辑输入。后端会重新校验顺序、证据引用、实验命令和 reviewer 独立性。</p>
            <input style={input} value={actor} onChange={(e) => setActor(e.target.value)} placeholder="执行此阶段的 Identity / actor"/>
            <textarea spellCheck={false} style={{ ...input, minHeight: 300, marginTop: 8, fontFamily: 'monospace' }} value={payload} onChange={(e) => setPayload(e.target.value)} />
            <button style={{ ...button, marginTop: 8 }} disabled={busy} onClick={submit}>校验并提交阶段</button>
          </section>}
          {project.status === 'complete' && <section style={{ ...card, borderColor: '#286444' }}><h3 style={{ marginTop: 0, color: '#82e5aa' }}>研究记录已闭环</h3><button style={button} onClick={async () => setMessage(JSON.stringify(await api.auditScienceProject(project.id), null, 2))}>重新执行完整性审计</button></section>}
        </>}
      </main>
    </div>}

    {view === 'conformance' && <div style={{ display: 'grid', gap: 14 }}>
      <section style={{ ...card, display: 'flex', alignItems: 'center', gap: 14 }}><div><h3 style={{ margin: 0 }}>15 个 pinned open-source harness</h3><p style={{ marginBottom: 0, color: '#9ba4b2' }}>结构检查读取当前 DAG；行为检查执行真实 offline contract tests；外部服务缺口单独列出。</p></div><button style={{ ...button, marginLeft: 'auto' }} disabled={busy} onClick={runBehavior}>运行全部行为契约</button></section>
      {conformance?.structural_report?.contracts?.map((item: any) => <details key={item.contract_id} style={card}>
        <summary style={{ cursor: 'pointer' }}><b style={{ color: item.core_passed ? '#7ee2a8' : '#ff8e8e' }}>{item.core_passed ? 'PASS' : 'FAIL'}</b>　{item.project}　<small>{item.source.revision}</small></summary>
        <p>{item.source_contract}</p><pre style={{ background: '#090911', padding: 10, overflow: 'auto' }}>{JSON.stringify({ structural: item.structural, behavioral: item.behavioral, parity_status: item.parity_status, external_blockers: item.external_blockers }, null, 2)}</pre>
      </details>)}
      {benchmark && <section style={card}><h3>EgoIR translation benchmark</h3><p>{benchmark.examples.length} 个 source-contract → EgoIR 配对样本。完整最小 operation vocabulary：</p><code>{benchmark.vocabulary.minimum_complete_operation_vocabulary.join(' · ')}</code></section>}
    </div>}
  </div>;
}
