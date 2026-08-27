import { useEffect, useState, type CSSProperties } from 'react';
import {
  getSecuritySettings,
  saveSecuritySettings,
  type WorkspaceSecuritySettings,
} from '../api/client';

const panel: CSSProperties = {
  background: 'var(--surface-raised)', border: '1px solid var(--border)', borderRadius: 8,
  padding: 20, marginBottom: 20,
};
const row: CSSProperties = { display: 'grid', gridTemplateColumns: '210px 1fr', gap: 14, alignItems: 'center', margin: '11px 0' };
const control: CSSProperties = { width: '100%', boxSizing: 'border-box', padding: '8px 10px', background: 'var(--input-background)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 5 };

export default function SecuritySettings() {
  const [settings, setSettings] = useState<WorkspaceSecuritySettings | null>(null);
  const [sandbox, setSandbox] = useState<any>(null);
  const [effective, setEffective] = useState<any>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      const result = await getSecuritySettings();
      setSettings(result.settings);
      setSandbox(result.sandbox);
      setEffective(result.effective_policy);
      setMessage('');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally { setBusy(false); }
  };

  useEffect(() => { void load(); }, []);

  const save = async () => {
    if (!settings) return;
    setBusy(true);
    try {
      const result = await saveSecuritySettings(settings);
      setSettings(result.settings);
      setSandbox(result.sandbox);
      setEffective(result.effective_policy);
      setMessage('✓ 已保存；新策略从下一次 Agent 运行开始生效。');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally { setBusy(false); }
  };

  if (!settings) return <section style={panel}><h3 style={{ color: '#7ecfff', marginTop: 0 }}>安全与审批</h3><p style={{ color: '#94a3b8' }}>{busy ? '正在读取当前工作区策略…' : message || '无法读取安全设置。'}</p></section>;

  const set = <K extends keyof WorkspaceSecuritySettings>(key: K, value: WorkspaceSecuritySettings[K]) => setSettings({ ...settings, [key]: value });
  const setSandboxField = (key: string, value: unknown) => setSettings({ ...settings, sandbox: { ...settings.sandbox, [key]: value } });
  const profileHelp: Record<string, string> = {
    strict: '写文件和命令都询问，网络与密钥默认拒绝。',
    balanced: '工作区写入自动允许；宿主机命令、高风险动作和网络需要审批。',
    trusted: '常规工具自动运行，但高风险和密钥操作仍受控。',
    unrestricted: '可关闭边界；仅用于你完全信任的 Harness，界面会持续警告。',
  };

  return <section style={panel}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', gap: 12 }}>
      <div><h3 style={{ color: '#7ecfff', margin: '0 0 5px' }}>安全、审批与沙箱</h3><p style={{ color: '#94a3b8', fontSize: 12, margin: 0 }}>策略按工作区保存。Harness 只能进一步收紧，不能静默放宽这里的边界。</p></div>
      <span style={{ color: sandbox?.available ? '#86efac' : '#fca5a5', fontSize: 11 }}>{sandbox?.label || '检测中'} · {sandbox?.strong_isolation ? '强隔离可用' : '非强隔离'}</span>
    </div>

    <label style={row}><span>安全档位</span><span><select style={control} value={settings.profile} onChange={(event) => set('profile', event.target.value as WorkspaceSecuritySettings['profile'])}><option value="strict">Strict</option><option value="balanced">Balanced（推荐）</option><option value="trusted">Trusted</option><option value="unrestricted">Unrestricted</option></select><small style={{ color: '#94a3b8' }}>{profileHelp[settings.profile]}</small></span></label>
    <label style={row}><span>高风险动作必须审批</span><input type="checkbox" checked={settings.require_dangerous_approval} onChange={(event) => set('require_dangerous_approval', event.target.checked)} /></label>
    <label style={row}><span>网络访问</span><select style={control} value={settings.network_decision} onChange={(event) => set('network_decision', event.target.value as any)}><option value="deny">拒绝</option><option value="ask">每次询问</option><option value="allow">允许</option></select></label>
    <label style={row}><span>未声明权限的第三方 Tool</span><select style={control} value={settings.unknown_tool_decision} onChange={(event) => set('unknown_tool_decision', event.target.value as any)}><option value="deny">拒绝</option><option value="ask">第一次使用时询问</option><option value="allow">允许</option></select></label>
    <label style={row}><span>密钥/凭据访问</span><select style={control} value={settings.secret_decision} onChange={(event) => set('secret_decision', event.target.value as any)}><option value="deny">拒绝</option><option value="ask">每次询问</option><option value="allow">允许</option></select></label>
    <label style={row}><span>限制文件到当前工作区</span><input type="checkbox" disabled={settings.profile !== 'unrestricted'} checked={settings.workspace_only} onChange={(event) => set('workspace_only', event.target.checked)} /></label>

    <label style={row}><span>命令执行边界</span><span><select style={control} value={settings.sandbox.mode} onChange={(event) => setSandboxField('mode', event.target.value)}><option value="workspace">Workspace guard（兼容性最好）</option><option value="container">Docker / Podman 容器（强隔离）</option><option value="off" disabled={settings.profile !== 'unrestricted'}>关闭（高风险）</option></select><small style={{ color: '#94a3b8' }}>{settings.sandbox.mode === 'workspace' ? '文件 Tool 有路径边界；命令仍使用当前 Windows 用户权限，因此每条宿主机命令默认要审批。' : settings.sandbox.mode === 'container' ? '命令在一次性容器中运行；默认断网、只读根目录、降权并限制 CPU/内存/进程数。' : '命令和文件没有产品级隔离。'}</small></span></label>
    {settings.sandbox.mode === 'container' && <div style={{ borderLeft: '2px solid #334155', paddingLeft: 14 }}>
      <label style={row}><span>容器引擎</span><select style={control} value={settings.sandbox.engine} onChange={(event) => setSandboxField('engine', event.target.value)}><option value="docker">Docker</option><option value="podman">Podman</option></select></label>
      <label style={row}><span>镜像</span><input style={control} value={settings.sandbox.image} onChange={(event) => setSandboxField('image', event.target.value)} /></label>
      <label style={row}><span>容器网络</span><select style={control} value={settings.sandbox.network} onChange={(event) => setSandboxField('network', event.target.value)}><option value="none">禁用</option><option value="bridge">Bridge（仍受审批策略约束）</option></select></label>
      <label style={row}><span>镜像拉取</span><select style={control} value={settings.sandbox.pull_policy} onChange={(event) => setSandboxField('pull_policy', event.target.value)}><option value="never">从不自动拉取</option><option value="missing">缺少时拉取</option><option value="always">每次检查</option></select></label>
      {!sandbox?.available && <p style={{ color: '#fca5a5', fontSize: 11 }}>当前容器后端不可用。Fail-closed 已启用：Agent 命令会被阻止，不会退回宿主机。{sandbox?.reason ? ` ${sandbox.reason}` : ''}</p>}
    </div>}

    {settings.profile === 'unrestricted' && <div style={{ border: '1px solid #7f1d1d', color: '#fecaca', background: '#450a0a55', padding: 10, borderRadius: 5, fontSize: 12 }}>Unrestricted 会扩大提示注入、误删文件和凭据外传的影响范围。请只对可信工作区短时使用。</div>}
    {message && <p style={{ color: message.startsWith('✓') ? '#86efac' : '#fca5a5', fontSize: 11 }}>{message}</p>}
    <details style={{ margin: '10px 0', color: 'var(--text-muted)', fontSize: 11 }}><summary>查看当前有效后端策略</summary><pre style={{ maxHeight: 230, overflow: 'auto', background: 'var(--surface-sunken)', color: 'var(--text-secondary)', padding: 10 }}>{JSON.stringify(effective, null, 2)}</pre></details>
    <button disabled={busy} onClick={() => void save()} style={{ padding: '9px 16px', border: 0, borderRadius: 5, color: '#fff', background: '#0369a1', cursor: 'pointer' }}>{busy ? '保存中…' : '保存安全设置'}</button>
  </section>;
}
