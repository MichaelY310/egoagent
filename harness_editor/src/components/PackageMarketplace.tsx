import { useEffect, useMemo, useState } from 'react';
import * as api from '../api/client';

type CatalogItem = {
  name: string; version: string; description: string; trust: 'untrusted' | 'local' | 'verified';
  signature_status: string; install_count: number; rating?: { count: number; average: number };
  manifest: { components: Array<{ kind: string; name: string }>; permissions?: string[]; compatibility?: Record<string, unknown>; dependencies?: Record<string, string>; examples?: Array<Record<string, unknown>> };
};

const field: React.CSSProperties = { width: '100%', boxSizing: 'border-box', border: '1px solid #334155', borderRadius: 6, padding: '7px 8px', background: '#07111f', color: '#e2e8f0', fontSize: 11 };
const button: React.CSSProperties = { border: '1px solid #365270', borderRadius: 6, padding: '5px 9px', background: '#18314f', color: '#dbeafe', cursor: 'pointer', fontSize: 10 };

export default function PackageMarketplace() {
  const [packages, setPackages] = useState<CatalogItem[]>([]);
  const [installed, setInstalled] = useState<any[]>([]);
  const [harnesses, setHarnesses] = useState<string[]>([]);
  const [identities, setIdentities] = useState<string[]>([]);
  const [tasks, setTasks] = useState<any[]>([]);
  const [query, setQuery] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [archive, setArchive] = useState('');
  const [form, setForm] = useState({ name: '', version: '0.1.0', description: '', kind: 'harness', component: '', permissions: ['read'] as string[], components: [] as Array<{ kind: string; name: string }> });

  const refresh = async () => {
    const [catalog, current] = await Promise.all([api.listPackages(query), api.listInstalledPackages()]);
    setPackages(catalog.packages || []);
    setInstalled(current.packages || []);
  };
  useEffect(() => {
    Promise.all([api.listHarnesses(), api.listIdentities(), api.listTaskBenchTasks(), refresh()]).then(([hs, ids, taskResult]) => {
      setHarnesses(hs || []); setIdentities(ids || []); setTasks(taskResult.tasks || taskResult || []);
    }).catch((error) => setMessage(String(error)));
  }, []);
  const options = useMemo(() => form.kind === 'harness' ? harnesses : form.kind === 'identity' ? identities : form.kind === 'task' ? tasks.map((task) => `${task.id || task.name}.json`) : [], [form.kind, harnesses, identities, tasks]);
  const installedNames = useMemo(() => new Set(installed.map((item) => item.manifest?.package?.name)), [installed]);

  const act = async (operation: () => Promise<any>, success: string) => {
    setBusy(true); setMessage('');
    try { await operation(); setMessage(success); await refresh(); } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); } finally { setBusy(false); }
  };
  const addComponent = () => {
    if (!form.component || form.components.some((item) => item.kind === form.kind && item.name === form.component)) return;
    setForm({ ...form, components: [...form.components, { kind: form.kind, name: form.component }], component: '' });
  };
  const create = () => act(() => api.packAgentPackage({ name: form.name, version: form.version, description: form.description, components: form.components, permissions: form.permissions, sign: true, add_to_registry: true, trust: 'local' }), 'Signed package created and added to the local registry');

  return <div className="package-marketplace">
    <header><div><h2>Agent Packages</h2><p>Bundle Identity, Ego knowledge/skills, Harness, environment, tasks, tests and permissions into one versioned, recoverable package.</p></div><button style={button} onClick={() => void refresh()}>↻ Refresh</button></header>
    {message && <div className="package-message">{message}</div>}
    <section className="package-builder">
      <h3>Create signed package</h3>
      <div className="package-form-grid"><label>Name<input style={field} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="my-agent" /></label><label>Semantic version<input style={field} value={form.version} onChange={(event) => setForm({ ...form, version: event.target.value })} /></label><label>Description<input style={field} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label></div>
      <div className="package-component-picker"><select style={field} value={form.kind} onChange={(event) => setForm({ ...form, kind: event.target.value, component: '' })}>{['harness', 'identity', 'task'].map((kind) => <option key={kind}>{kind}</option>)}</select><select style={field} value={form.component} onChange={(event) => setForm({ ...form, component: event.target.value })}><option value="">Select component…</option>{options.map((name) => <option key={name}>{name}</option>)}</select><button style={button} onClick={addComponent}>Add</button></div>
      <div className="package-chips">{form.components.map((item, index) => <button key={`${item.kind}-${item.name}`} onClick={() => setForm({ ...form, components: form.components.filter((_, itemIndex) => itemIndex !== index) })}>{item.kind}/{item.name} ×</button>)}</div>
      <div className="permission-chips">{['read', 'write', 'process', 'network', 'mutation', 'secrets'].map((permission) => <label key={permission}><input type="checkbox" checked={form.permissions.includes(permission)} onChange={(event) => setForm({ ...form, permissions: event.target.checked ? [...form.permissions, permission] : form.permissions.filter((value) => value !== permission) })} />{permission}</label>)}</div>
      <button disabled={busy || !form.name || !form.components.length} style={{ ...button, background: '#0369a1' }} onClick={() => void create()}>Pack, sign & add locally</button>
    </section>
    <section className="package-import"><input style={field} value={archive} onChange={(event) => setArchive(event.target.value)} placeholder="Repository-local .egoagentpkg path" /><button style={button} disabled={!archive || busy} onClick={() => void act(() => api.addPackageArchive(archive, 'untrusted'), 'Archive inspected and added as untrusted')}>Import archive</button></section>
    <div className="package-search"><input style={field} value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && void refresh()} placeholder="Search names, components or examples" /><button style={button} onClick={() => void refresh()}>Search</button></div>
    <div className="package-grid">{packages.map((item) => <article key={`${item.name}-${item.version}`}>
      <header><div><b>{item.name}</b><span>v{item.version}</span></div><em className={`trust-${item.trust}`}>{item.trust}</em></header><p>{item.description || 'No description'}</p>
      <div className="package-chips">{item.manifest.components.map((component) => <span key={`${component.kind}-${component.name}`}>{component.kind}/{component.name}</span>)}</div>
      <small>signature: {item.signature_status} · rating {item.rating?.average || 0}/5 ({item.rating?.count || 0}) · installs {item.install_count}</small>
      {!!Object.keys(item.manifest.dependencies || {}).length && <code>deps: {JSON.stringify(item.manifest.dependencies)}</code>}
      <details><summary>Permissions & compatibility</summary><pre>{JSON.stringify({ permissions: item.manifest.permissions, compatibility: item.manifest.compatibility, examples: item.manifest.examples }, null, 2)}</pre></details>
      <footer><button style={button} disabled={busy} onClick={() => void act(() => api.installRegistryPackage(item.name, item.version, { allow_update: installedNames.has(item.name), allow_untrusted: false }), installedNames.has(item.name) ? 'Package updated transactionally' : 'Package installed')}>{installedNames.has(item.name) ? 'Update' : 'Install'}</button>
        {item.trust === 'untrusted' && <button style={button} onClick={() => void act(() => api.setPackageTrust(item.name, item.version, 'local'), 'Package trusted locally')}>Trust locally</button>}
        <button style={button} onClick={() => { const name = window.prompt('Fork package name', `${item.name}-fork`); if (name) void act(() => api.forkRegistryPackage(item.name, item.version, name), 'Fork created'); }}>Fork</button>
        <button style={button} onClick={() => void act(() => api.ratePackage(item.name, item.version, 5, 'Local verification'), 'Rated 5 stars')}>★</button>
        {installedNames.has(item.name) && <button style={{ ...button, color: '#fecaca' }} onClick={() => window.confirm('Uninstall? Local modifications will stop the operation.') && void act(() => api.uninstallAgentPackage(item.name), 'Package moved to recoverable uninstall storage')}>Uninstall</button>}
      </footer>
    </article>)}</div>
    {!packages.length && <div className="package-empty">No packages match the current search.</div>}
  </div>;
}
