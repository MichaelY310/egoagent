import { useEffect, useState } from 'react';
import * as api from '../api/client';

const card: React.CSSProperties = { background: '#111c33', border: '1px solid #263a5a', borderRadius: 8, padding: 14 };
const input: React.CSSProperties = { width: '100%', boxSizing: 'border-box', padding: '7px 8px', border: '1px solid #334155', borderRadius: 5, background: '#08111f', color: '#e2e8f0', fontSize: 11 };
const button: React.CSSProperties = { padding: '7px 10px', border: '1px solid #365270', borderRadius: 5, background: '#18314f', color: '#dbeafe', cursor: 'pointer', fontSize: 11 };

const PRESETS: Record<string, { base_url: string; model: string; api_key_env: string }> = {
  deepseek: { base_url: 'https://api.deepseek.com', model: 'deepseek-chat', api_key_env: 'DEEPSEEK_API_KEY' },
  siliconflow: { base_url: 'https://api.siliconflow.cn/v1', model: 'Qwen/Qwen3-8B', api_key_env: 'SILICONFLOW_API_KEY' },
  openai: { base_url: 'https://api.openai.com/v1', model: 'gpt-4.1-mini', api_key_env: 'OPENAI_API_KEY' },
  ollama: { base_url: 'http://127.0.0.1:11434/v1', model: 'qwen3:8b', api_key_env: '' },
  openai_compatible: { base_url: '', model: '', api_key_env: 'EGOAGENT_LLM_API_KEY' },
};

function Label({ title, children }: { title: string; children: React.ReactNode }) {
  return <label style={{ display: 'grid', gap: 4, color: '#94a3b8', fontSize: 10 }}><span>{title}</span>{children}</label>;
}

export default function ProductSetupPanel() {
  const [settings, setSettings] = useState<any>(null);
  const [diagnostics, setDiagnostics] = useState<any>(null);
  const [rollbacks, setRollbacks] = useState<any[]>([]);
  const [provider, setProvider] = useState('deepseek');
  const [providerDraft, setProviderDraft] = useState({ ...PRESETS.deepseek, api_key: '' });
  const [updateArchive, setUpdateArchive] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const refresh = async () => {
    const [nextSettings, nextDiagnostics, nextRollbacks] = await Promise.all([
      api.getProductSettings(), api.getProductDiagnostics(), api.listProductRollbacks(),
    ]);
    setSettings(nextSettings); setDiagnostics(nextDiagnostics); setRollbacks(nextRollbacks);
  };

  useEffect(() => { refresh().catch((reason) => setMessage(reason.message)); }, []);

  const act = async (work: () => Promise<any>, success: (result: any) => string) => {
    setBusy(true); setMessage('');
    try { const result = await work(); await refresh(); setMessage(success(result)); }
    catch (reason: any) { setMessage(reason.message); }
    finally { setBusy(false); }
  };

  const selectProvider = (value: string) => {
    setProvider(value); setProviderDraft({ ...PRESETS[value], api_key: '' });
  };

  if (!settings) return <section style={{ ...card, marginBottom: 20, color: '#94a3b8' }}>Loading product diagnostics…</section>;
  const checks = diagnostics?.checks || {};

  return (
    <section style={{ background: '#16213e', border: '1px solid #1e3a5f', borderRadius: 8, padding: 20, marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
        <div><h3 style={{ color: '#7ecfff', fontSize: 14, margin: '0 0 5px' }}>First-run setup & product health</h3><p style={{ color: '#94a3b8', fontSize: 11, margin: 0 }}>Secrets stay in the gitignored server-side .env.local. Diagnostics never return them.</p></div>
        <span style={{ color: diagnostics?.healthy ? '#86efac' : '#fca5a5', fontSize: 11 }}>{diagnostics?.healthy ? '✓ ready' : '● attention needed'}</span>
      </div>

      <details style={{ ...card, marginTop: 12 }} open>
        <summary style={{ color: '#dbeafe', cursor: 'pointer', fontSize: 12 }}>1. Provider quick setup</summary>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 9, marginTop: 10 }}>
          <Label title="Provider"><select style={input} value={provider} onChange={(event) => selectProvider(event.target.value)}>{Object.keys(PRESETS).map((name) => <option key={name}>{name}</option>)}</select></Label>
          <Label title="Base URL"><input style={input} value={providerDraft.base_url} onChange={(event) => setProviderDraft({ ...providerDraft, base_url: event.target.value })} /></Label>
          <Label title="Model ID"><input style={input} value={providerDraft.model} onChange={(event) => setProviderDraft({ ...providerDraft, model: event.target.value })} /></Label>
          {provider !== 'ollama' && <Label title="API key (saved once, never echoed)"><input style={input} type="password" autoComplete="new-password" value={providerDraft.api_key} onChange={(event) => setProviderDraft({ ...providerDraft, api_key: event.target.value })} /></Label>}
          {provider !== 'ollama' && <Label title="Secret variable"><input style={input} value={providerDraft.api_key_env} onChange={(event) => setProviderDraft({ ...providerDraft, api_key_env: event.target.value })} /></Label>}
        </div>
        <button disabled={busy || !providerDraft.model || !providerDraft.base_url} style={{ ...button, marginTop: 10, background: '#0369a1' }} onClick={() => void act(
          () => api.configureProductProvider({ provider, ...providerDraft }),
          (result) => `Provider ready: ${result.profile?.name || provider}. The key was not returned to the browser.`,
        )}>Save and assign to AI roles</button>
      </details>

      <details style={{ ...card, marginTop: 12 }}>
        <summary style={{ color: '#dbeafe', cursor: 'pointer', fontSize: 12 }}>2. Network, mirrors, offline & privacy</summary>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 9, marginTop: 10 }}>
          <Label title="HTTP proxy"><input style={input} value={settings.proxy.http} placeholder="http://127.0.0.1:7890" onChange={(e) => setSettings({ ...settings, proxy: { ...settings.proxy, http: e.target.value } })} /></Label>
          <Label title="HTTPS proxy"><input style={input} value={settings.proxy.https} placeholder="http://127.0.0.1:7890" onChange={(e) => setSettings({ ...settings, proxy: { ...settings.proxy, https: e.target.value } })} /></Label>
          <Label title="pip mirror"><input style={input} value={settings.mirrors.pip_index_url} placeholder="https://pypi.tuna.tsinghua.edu.cn/simple" onChange={(e) => setSettings({ ...settings, mirrors: { ...settings.mirrors, pip_index_url: e.target.value } })} /></Label>
          <Label title="npm registry"><input style={input} value={settings.mirrors.npm_registry} placeholder="https://registry.npmmirror.com" onChange={(e) => setSettings({ ...settings, mirrors: { ...settings.mirrors, npm_registry: e.target.value } })} /></Label>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 10, color: '#cbd5e1', fontSize: 10 }}>
          <label><input type="checkbox" checked={settings.offline_mode} onChange={(e) => setSettings({ ...settings, offline_mode: e.target.checked })} /> strict offline mode (local models only)</label>
          <label><input type="checkbox" checked={settings.privacy.diagnostic_logs} onChange={(e) => setSettings({ ...settings, privacy: { ...settings.privacy, diagnostic_logs: e.target.checked } })} /> include redacted logs in diagnostics</label>
          <label><input type="checkbox" checked={settings.privacy.telemetry} onChange={(e) => setSettings({ ...settings, privacy: { ...settings.privacy, telemetry: e.target.checked } })} /> telemetry (off by default)</label>
        </div>
        <button disabled={busy} style={{ ...button, marginTop: 10 }} onClick={() => void act(() => api.saveProductSettings(settings), () => 'Product settings saved and applied to new requests/processes.')}>Save product settings</button>
      </details>

      <details style={{ ...card, marginTop: 12 }}>
        <summary style={{ color: '#dbeafe', cursor: 'pointer', fontSize: 12 }}>3. Dependency health & diagnostics bundle</summary>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 6, marginTop: 10 }}>
          {['python', 'node', 'npm', 'git', 'docker', 'void_runtime', 'studio_dependencies'].map((name) => <div key={name} style={{ padding: 7, borderRadius: 5, background: '#08111f', color: checks[name]?.available ? '#86efac' : '#fca5a5', fontSize: 10 }}><b>{checks[name]?.available ? '✓' : '×'} {name}</b><div style={{ color: '#64748b', marginTop: 3 }}>{checks[name]?.version || checks[name]?.reason || checks[name]?.path || 'not found'}</div></div>)}
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}><button style={button} disabled={busy} onClick={() => void refresh()}>Run checks again</button><button style={button} disabled={busy} onClick={() => void act(api.createDiagnosticsBundle, (result) => `Redacted diagnostics created: ${result.path}`)}>Create diagnostics ZIP</button></div>
      </details>

      <details style={{ ...card, marginTop: 12 }}>
        <summary style={{ color: '#dbeafe', cursor: 'pointer', fontSize: 12 }}>4. Offline update & rollback</summary>
        <p style={{ color: '#94a3b8', fontSize: 10, lineHeight: 1.5 }}>Updates are explicit local archives with an ego.update.v1 manifest. Runtime data and secrets are protected. Every update creates a rollback snapshot first.</p>
        <div style={{ display: 'flex', gap: 7 }}><input style={input} value={updateArchive} onChange={(e) => setUpdateArchive(e.target.value)} placeholder="Absolute path to update .zip" /><button disabled={busy || !updateArchive.trim()} style={button} onClick={() => { if (window.confirm('Apply this local update and restart services afterwards?')) void act(() => api.applyProductUpdate(updateArchive.trim()), (result) => `Updated ${result.files} files. Rollback: ${result.rollback_id}`); }}>Apply update</button></div>
        <div style={{ display: 'grid', gap: 5, marginTop: 9 }}>{rollbacks.map((item) => <div key={item.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 7, background: '#08111f', borderRadius: 5, fontSize: 10 }}><span style={{ flex: 1, color: '#94a3b8' }}>{item.id} · {item.version || 'unknown version'} · {item.replaced?.length || 0} replaced</span><button style={{ ...button, color: '#fecaca' }} disabled={busy || item.rolled_back_at} onClick={() => { if (window.confirm(`Rollback ${item.id}?`)) void act(() => api.rollbackProductUpdate(item.id), () => `Rollback restored. Restart services to load the previous version.`); }}>{item.rolled_back_at ? 'rolled back' : 'Rollback'}</button></div>)}</div>
      </details>
      {message && <div style={{ marginTop: 10, color: /error|missing|failed|not found/i.test(message) ? '#fca5a5' : '#93c5fd', fontSize: 11, wordBreak: 'break-word' }}>{message}</div>}
    </section>
  );
}
