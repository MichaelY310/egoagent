import { useEffect, useState } from 'react';
import * as api from '../api/client';

const button: React.CSSProperties = { padding: '6px 10px', border: '1px solid #365270', borderRadius: 5, background: '#18314f', color: '#dbeafe', cursor: 'pointer', fontSize: 10 };
const area: React.CSSProperties = { boxSizing: 'border-box', width: '100%', minHeight: 120, padding: 8, border: '1px solid #334155', borderRadius: 5, background: '#060b14', color: '#dbeafe', font: '9px/1.45 Consolas, monospace', resize: 'vertical' };

const PROPOSAL = {
  format: 'ego.evolution-proposal.v1', id: 'proposal_example', target: 'react_single',
  artifact: { kind: 'harness', name: 'bounded-loop' },
  evidence: [
    { source: 'task_run', lineage_id: 'run-a', artifact_ref: 'run-a/trace.json', observation: 'A repeated failure is visible in this trace.' },
    { source: 'verified_test', lineage_id: 'checker-b', artifact_ref: 'checks/replay.json', observation: 'An independent deterministic replay reproduced it.' },
  ],
  scope: { paths: ['harness/react_single/config.json'], permissions: ['harness_patch'] },
  change: { expected_revision: 'LOAD_FROM_EGOIR', operations: [{ op: 'set_limits', max_steps: 50 }], checks: [{ type: 'no_python' }] },
  hypothesis: { description: 'Bound the observed repeated loop.', metric: 'success', minimum_delta: 0.05 },
  evaluation: { train: ['train-1'], validation: ['valid-1'], heldout: ['hidden-1'], regression: ['regression-1'] },
  cost: { before: 1, after: 1 }, rollback: { strategy: 'transaction', required: true },
  confidence: 0.7, expected_reuse: 0.6, expected_benefit: 0.5, maintenance_cost: 0.1, regression_risk: 0.1,
};

const empiricalEvidence = [
  { source: 'task_run', lineage_id: 'production-run-a', observation: 'The same bounded failure recurred.' },
  { source: 'verified_test', lineage_id: 'independent-check-b', observation: 'A deterministic replay reproduced it.' },
];
const measured = (gain: number) => [
  { task_id: 'valid-1', split: 'validation', baseline: { success: 0.4, tokens: 1000, cost: 1 }, candidate: { success: 0.4 + gain, tokens: 800, cost: 0.9, within_budget: true } },
  { task_id: 'heldout-1', split: 'heldout', baseline: { success: 0.5, tokens: 1000, cost: 1 }, candidate: { success: 0.5 + gain, tokens: 800, cost: 0.9, within_budget: true } },
  { task_id: 'regression-1', split: 'regression', baseline: { success: 0.8, tokens: 1000, cost: 1 }, candidate: { success: 0.8, tokens: 800, cost: 0.9, within_budget: true } },
];
const EMPIRICAL_CANDIDATES = [
  { kind: 'knowledge', maintenance_cost: 0.05, regression_risk: 0.02, evidence: empiricalEvidence, measurements: measured(0.10) },
  { kind: 'harness', maintenance_cost: 0.05, regression_risk: 0.02, evidence: empiricalEvidence, measurements: measured(0.11) },
];

const CERTIFICATE_EXAMPLE = {
  update_id: 'multi-artifact-example',
  artifacts: [{ id: 'skill', kind: 'skill' }, { id: 'harness', kind: 'harness' }],
  measurements: ['validation', 'heldout', 'protected'].flatMap((split) => Array.from({ length: 6 }, (_, index) => {
    const task_id = `${split}-${index}`;
    const baseline = split === 'protected' ? .9 : .5;
    return [
      { split, task_id, active_artifacts: [], success: baseline },
      { split, task_id, active_artifacts: ['skill'], success: split === 'protected' ? .9 : .62 },
      { split, task_id, active_artifacts: ['harness'], success: split === 'protected' ? .9 : .58 },
      { split, task_id, active_artifacts: ['harness', 'skill'], success: split === 'protected' ? .895 : .75 },
    ];
  }).flat()),
  evidence: [
    { source: 'task_run', lineage_id: 'run-a', observation: 'failure reproduced' },
    { source: 'verified_test', lineage_id: 'checker-b', observation: 'independent deterministic replay' },
  ],
  activation: { skill: 12, harness: 12 },
  portability: Array.from({ length: 6 }, (_, index) => ({ target: `fresh-${index}`, baseline: { success: .4 }, candidate: { success: .5 } })),
  verifier_mutants: Array.from({ length: 10 }, (_, index) => ({ id: `m${index}`, relevant: true, killed: index < 9 })),
};

export default function ProofEvolutionLab() {
  const [proposals, setProposals] = useState<any[]>([]);
  const [proposalText, setProposalText] = useState(JSON.stringify(PROPOSAL, null, 2));
  const [candidatesText, setCandidatesText] = useState(JSON.stringify([
    { kind: 'none', expected_reuse: 0, expected_benefit: 0, confidence: 1, implementation_cost: 0, maintenance_cost: 0, regression_risk: 0 },
    { kind: 'knowledge', expected_reuse: 0.8, expected_benefit: 0.5, confidence: 0.7, implementation_cost: 0.1, maintenance_cost: 0.05, regression_risk: 0.05, token_saving: 0.4 },
  ], null, 2));
  const [empiricalText, setEmpiricalText] = useState(JSON.stringify(EMPIRICAL_CANDIDATES, null, 2));
  const [baseline, setBaseline] = useState(JSON.stringify({ validation: { success: 0.5 }, heldout: { success: 0.5 } }, null, 2));
  const [candidate, setCandidate] = useState(JSON.stringify({ validation: { success: 0.6, within_budget: true }, heldout: { success: 0.57, within_budget: true }, regression: { passed: true } }, null, 2));
  const [certificateText, setCertificateText] = useState(JSON.stringify(CERTIFICATE_EXAMPLE, null, 2));
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => setProposals(await api.listEvolutionProposals());
  useEffect(() => { refresh().catch((error) => setResult({ error: error.message })); }, []);
  const run = async (action: () => Promise<any>) => { setBusy(true); try { setResult(await action()); await refresh(); } catch (error: any) { setResult({ error: error.message }); } finally { setBusy(false); } };

  return <div style={{ background: '#101b31', border: '1px solid #6d28d9', borderRadius: 8, padding: 14, marginBottom: 12 }}>
    <h3 style={{ margin: '0 0 5px', color: '#d8b4fe', fontSize: 14 }}>Proof-carrying Evolution Lab</h3>
    <p style={{ margin: '0 0 10px', color: '#94a3b8', fontSize: 10, lineHeight: 1.55 }}>不根据关键词强迫进化。先用相同 shadow tasks 实测每个候选层；在性能近似最优者中选择最小改动层。来自同一来源的重复轨迹只算一条证据，永久进化还需要独立可信验证。变更必须在 validation + held-out + regression 全部通过后才进入 trusted。</p>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 9 }}>
      <details open style={{ padding: 9, border: '1px solid #273755', borderRadius: 6 }}><summary style={{ color: '#c4b5fd', cursor: 'pointer', fontSize: 11 }}>1. Fast prior selector (estimates)</summary><textarea style={{ ...area, marginTop: 7 }} value={candidatesText} onChange={(e) => setCandidatesText(e.target.value)} /><button style={button} disabled={busy} onClick={() => void run(() => api.selectEvolutionArtifact(JSON.parse(candidatesText)))}>Rank estimates</button></details>
      <details open style={{ padding: 9, border: '1px solid #273755', borderRadius: 6 }}><summary style={{ color: '#c4b5fd', cursor: 'pointer', fontSize: 11 }}>2. Minimal sufficient layer (matched shadow runs)</summary><textarea style={{ ...area, minHeight: 220, marginTop: 7 }} value={empiricalText} onChange={(e) => setEmpiricalText(e.target.value)} /><button style={button} disabled={busy} onClick={() => void run(() => api.selectEmpiricalEvolutionArtifact(JSON.parse(empiricalText)))}>Select from evidence</button></details>
      <details open style={{ padding: 9, border: '1px solid #273755', borderRadius: 6 }}><summary style={{ color: '#c4b5fd', cursor: 'pointer', fontSize: 11 }}>3. Evidence-bound proposal</summary><textarea style={{ ...area, minHeight: 220, marginTop: 7 }} value={proposalText} onChange={(e) => setProposalText(e.target.value)} /><button style={button} disabled={busy} onClick={() => void run(() => api.registerEvolutionProposal(JSON.parse(proposalText)))}>Validate & quarantine/register</button></details>
    </div>
    <details style={{ marginTop: 9, padding: 9, border: '1px solid #273755', borderRadius: 6 }} open={proposals.length > 0}><summary style={{ color: '#c4b5fd', cursor: 'pointer', fontSize: 11 }}>4. Experimental → held-out gate → trusted / rollback ({proposals.length})</summary>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 7, marginTop: 7 }}><label style={{ color: '#94a3b8', fontSize: 9 }}>Baseline<textarea style={area} value={baseline} onChange={(e) => setBaseline(e.target.value)} /></label><label style={{ color: '#94a3b8', fontSize: 9 }}>Candidate measured evidence<textarea style={area} value={candidate} onChange={(e) => setCandidate(e.target.value)} /></label></div>
      {proposals.map((item) => <div key={item.id} style={{ display: 'flex', alignItems: 'center', gap: 7, marginTop: 6, padding: 7, borderRadius: 5, background: '#070d19', fontSize: 10 }}><b style={{ color: '#e2e8f0' }}>{item.id}</b><span style={{ color: item.status === 'trusted' ? '#86efac' : item.status === 'rejected' ? '#fca5a5' : '#fcd34d' }}>{item.status}</span><span style={{ flex: 1, color: '#64748b' }}>{item.artifact?.kind} → {item.target}</span>{item.status === 'experimental' && <><button style={button} disabled={busy} onClick={() => void run(() => api.applyEvolutionProposal(item.id, true))}>Dry run</button><button style={button} disabled={busy} onClick={() => void run(() => api.applyEvolutionProposal(item.id, false))}>Apply experimental</button><button style={{ ...button, background: '#166534' }} disabled={busy} onClick={() => void run(() => api.gateEvolutionProposal(item.id, JSON.parse(baseline), JSON.parse(candidate)))}>Gate evidence</button></>}</div>)}
    </details>
    <details style={{ marginTop: 9, padding: 9, border: '1px solid #273755', borderRadius: 6 }}><summary style={{ color: '#c4b5fd', cursor: 'pointer', fontSize: 11 }}>5. EvoCert · 多 Artifact 因果签发（research preview）</summary>
      <p style={{ margin: '7px 0', color: '#94a3b8', fontSize: 9, lineHeight: 1.5 }}>从 paired knockout / graft / protected-distribution / semantic-mutant 数据签发 accept、abstain 或 reject。这里不运行模型，只审计外部实验测量。</p>
      <textarea style={{ ...area, minHeight: 260 }} value={certificateText} onChange={(event) => setCertificateText(event.target.value)} />
      <button style={button} disabled={busy} onClick={() => void run(() => api.issueEvolutionCertificate(JSON.parse(certificateText)))}>Issue causal certificate</button>
    </details>
    {result && <details open style={{ marginTop: 9 }}><summary style={{ color: result.error ? '#fca5a5' : '#94a3b8', cursor: 'pointer', fontSize: 10 }}>Latest selector / proposal / gate result</summary><pre style={{ maxHeight: 300, overflow: 'auto', padding: 8, background: '#020617', color: '#cbd5e1', whiteSpace: 'pre-wrap', fontSize: 9 }}>{JSON.stringify(result, null, 2)}</pre></details>}
  </div>;
}
