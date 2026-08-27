import { useEffect, useState } from 'react';
import * as api from '../api/client';

const button: React.CSSProperties = { padding: '7px 11px', border: '1px solid var(--border)', borderRadius: 5, background: 'var(--button-bg)', color: 'var(--button-text)', cursor: 'pointer', fontSize: 11 };

export default function EgoIRWorkbench() {
  const [harnesses, setHarnesses] = useState<any[]>([]);
  const [name, setName] = useState('');
  const [text, setText] = useState('');
  const [revision, setRevision] = useState('');
  const [guide, setGuide] = useState<any>(null);
  const [operations, setOperations] = useState('[\n  {"op":"set_limits","max_steps":100}\n]');
  const [checks, setChecks] = useState('[{"type":"no_python"}]');
  const [preview, setPreview] = useState<any>(null);
  const [lastTransaction, setLastTransaction] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const load = async (nextName: string) => {
    if (!nextName) return;
    setBusy(true); setMessage(''); setPreview(null);
    try { const result = await api.loadEgoIR(nextName); setName(nextName); setText(result.text); setRevision(result.revision); }
    catch (reason: any) { setMessage(reason.message); }
    finally { setBusy(false); }
  };

  useEffect(() => {
    Promise.all([api.listHarnesses(), api.getEgoIRGuide()]).then(([items, nextGuide]) => {
      setHarnesses(items); setGuide(nextGuide);
      const first = typeof items[0] === 'string' ? items[0] : (items[0] as any)?.name; if (first) void load(first);
    }).catch((reason) => setMessage(reason.message));
  }, []);

  const validate = async () => {
    setBusy(true); setMessage('');
    try { const result = await api.validateEgoIR(text); setPreview({ validation: result }); setMessage(`Valid EgoIR · ${Object.keys(result.config.pipeline.nodes).length} nodes`); return result; }
    catch (reason: any) { setMessage(reason.message); return null; }
    finally { setBusy(false); }
  };

  const replaceFromText = async (dryRun: boolean) => {
    setBusy(true); setMessage('');
    try {
      const validated = await api.validateEgoIR(text);
      const result = await api.patchEgoIR(name, {
        expected_revision: revision, dry_run: dryRun,
        operations: [{ op: 'replace_document', document: validated.document }],
        checks: JSON.parse(checks || '[]'), reason: 'Studio EgoIR text edit', actor: 'human',
      });
      setPreview(result);
      if (!dryRun) { setRevision(result.revision); setLastTransaction(result.transaction_id); setText(result.text); }
      setMessage(dryRun ? 'Dry run passed; inspect the diff before commit.' : `Committed ${result.transaction_id}`);
    } catch (reason: any) { setMessage(reason.message); }
    finally { setBusy(false); }
  };

  const applyOps = async (dryRun: boolean) => {
    setBusy(true); setMessage('');
    try {
      const result = await api.patchEgoIR(name, {
        expected_revision: revision, dry_run: dryRun, operations: JSON.parse(operations), checks: JSON.parse(checks || '[]'),
        reason: 'Studio constrained structural mutation', actor: 'human',
      });
      setPreview(result);
      if (!dryRun) { setRevision(result.revision); setLastTransaction(result.transaction_id); setText(result.text); }
      setMessage(dryRun ? 'Mutation dry run passed.' : `Mutation committed: ${result.transaction_id}`);
    } catch (reason: any) { setMessage(reason.message); }
    finally { setBusy(false); }
  };

  const rollback = async () => {
    if (!lastTransaction || !window.confirm(`Rollback ${lastTransaction}?`)) return;
    setBusy(true);
    try { const result = await api.rollbackEgoIR(lastTransaction, revision); setRevision(result.revision); setLastTransaction(''); await load(name); setMessage('Rollback completed.'); }
    catch (reason: any) { setMessage(reason.message); }
    finally { setBusy(false); }
  };

  return <div className="egoir-workbench">
    <header><div><h2>EgoIR Workbench</h2><p>弱模型友好的逐行 Harness 表示；完整保留 runtime config，并用 revision、dry-run、检查、事务和回滚保护结构修改。</p></div><select value={name} onChange={(e) => void load(e.target.value)}>{harnesses.map((item) => { const value = item.name || item; return <option key={value}>{value}</option>; })}</select><code>{revision || 'no revision'}</code></header>
    <main>
      <section className="egoir-editor"><div className="egoir-toolbar"><button style={button} disabled={busy} onClick={() => void validate()}>Validate</button><button style={button} disabled={busy || !name} onClick={() => void replaceFromText(true)}>Preview text diff</button><button style={{ ...button, background: '#0369a1' }} disabled={busy || !name} onClick={() => void replaceFromText(false)}>Commit text</button><button style={{ ...button, color: '#fecaca' }} disabled={busy || !lastTransaction} onClick={() => void rollback()}>Undo transaction</button></div><textarea spellCheck={false} value={text} onChange={(e) => setText(e.target.value)} /></section>
      <aside>
        <details open><summary>Constrained structural operations</summary><p>Models can add/remove/update/connect/rebind/set ports, permissions and limits without Python or full-file JSON.</p><textarea spellCheck={false} value={operations} onChange={(e) => setOperations(e.target.value)} /><label>Pre-commit checks</label><textarea className="short" spellCheck={false} value={checks} onChange={(e) => setChecks(e.target.value)} /><div><button style={button} disabled={busy} onClick={() => void applyOps(true)}>Dry run</button><button style={{ ...button, background: '#0369a1' }} disabled={busy} onClick={() => void applyOps(false)}>Commit ops</button></div></details>
        <details><summary>Weak-model guide</summary><pre>{JSON.stringify(guide, null, 2)}</pre></details>
        <details open={Boolean(preview)}><summary>Validation / diff</summary><pre>{preview?.diff || JSON.stringify(preview, null, 2) || 'No preview yet.'}</pre></details>
        {message && <div className={/error|invalid|failed|conflict/i.test(message) ? 'egoir-message error' : 'egoir-message'}>{message}</div>}
      </aside>
    </main>
  </div>;
}
