import { useEffect, useState } from "react";
import {
  getTrajectoryCollectionSettings,
  saveTrajectoryCollectionSettings,
  type TrajectoryCollectionSettings,
} from "../api/client";

const box: React.CSSProperties = { background: "#181818", border: "1px solid #303030", borderRadius: 6, padding: 16, marginBottom: 18 };
const input: React.CSSProperties = { width: "100%", boxSizing: "border-box", background: "#1e1e1e", border: "1px solid #3c3c3c", borderRadius: 3, color: "#d4d4d4", padding: "7px 9px", fontSize: 12 };

export default function TrajectoryCollectionSettingsPanel() {
  const [settings, setSettings] = useState<TrajectoryCollectionSettings | null>(null);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getTrajectoryCollectionSettings().then((result) => setSettings(result.settings)).catch((error) => setStatus(String(error)));
  }, []);

  if (!settings) return <div style={box}><span style={{ color: "#858585", fontSize: 11 }}>正在载入轨迹收集设置… {status}</span></div>;

  const save = async () => {
    setSaving(true); setStatus("");
    try {
      const result = await saveTrajectoryCollectionSettings(settings);
      setSettings(result.settings);
      setStatus("✓ 已保存；正在运行的 Session 会在最多 2 秒内开始镜像。原生轨迹始终保留。");
    } catch (error) { setStatus(`保存失败：${error instanceof Error ? error.message : String(error)}`); }
    finally { setSaving(false); }
  };

  return <section style={box}>
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
      <div><h3 style={{ color: "#d4d4d4", fontSize: 13, margin: "0 0 5px" }}>训练轨迹额外收集</h3><p style={{ color: "#858585", fontSize: 11, margin: 0, lineHeight: 1.55 }}>原生轨迹始终写入 Session 目录。此开关只控制是否将每个不可变事件同步复制到你指定的数据集目录。</p></div>
      <label style={{ color: settings.enabled ? "#89d185" : "#aaa", fontSize: 11, whiteSpace: "nowrap" }}><input type="checkbox" checked={settings.enabled} onChange={(event) => setSettings({ ...settings, enabled: event.target.checked })} /> {settings.enabled ? "镜像开启" : "镜像关闭"}</label>
    </div>
    <label style={{ display: "block", marginTop: 13, color: "#aaa", fontSize: 11 }}>数据集目录<input style={{ ...input, marginTop: 5 }} value={settings.destination} onChange={(event) => setSettings({ ...settings, destination: event.target.value })} placeholder="例如 D:\egoagent-datasets（不能是磁盘根目录）" /></label>
    <div style={{ display: "flex", gap: 16, marginTop: 10, color: "#aaa", fontSize: 10 }}>
      <label><input type="checkbox" checked={settings.partition_by_date} onChange={(event) => setSettings({ ...settings, partition_by_date: event.target.checked })} /> 按 UTC 日期分目录</label>
      <label><input type="checkbox" checked={settings.partition_by_project} onChange={(event) => setSettings({ ...settings, partition_by_project: event.target.checked })} /> 按项目分目录</label>
    </div>
    <button onClick={() => void save()} disabled={saving} style={{ marginTop: 12, background: "#0e639c", color: "white", border: 0, borderRadius: 3, padding: "7px 12px", cursor: saving ? "default" : "pointer", opacity: saving ? 0.6 : 1, fontSize: 11 }}>{saving ? "保存中…" : "保存轨迹设置"}</button>
    {status && <div style={{ color: status.startsWith("保存失败") ? "#f48771" : "#89d185", fontSize: 10, marginTop: 8 }}>{status}</div>}
  </section>;
}
