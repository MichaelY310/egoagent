import { useState, useEffect } from "react";

const BASE = `http://${window.location.hostname}:8765`;

interface SettingsData {
  analyzer_harness: string;
  analyzer_identity: string;
}

const DEFAULTS: SettingsData = {
  analyzer_harness: "session_analyzer",
  analyzer_identity: "dante",
};

export default function Settings() {
  const [settings, setSettings] = useState<SettingsData>(DEFAULTS);
  const [harnesses, setHarnesses] = useState<string[]>([]);
  const [identities, setIdentities] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    // Load saved settings from localStorage
    const stored = localStorage.getItem("ego_settings");
    if (stored) {
      try { setSettings(JSON.parse(stored)); } catch {}
    }
    // Fetch available harnesses and identities
    fetch(`${BASE}/api/harnesses`).then(r => r.json()).then(data => {
      setHarnesses(data.map((h: any) => h.name || h));
    }).catch(() => {});
    fetch(`${BASE}/api/identities`).then(r => r.json()).then(data => {
      setIdentities(data.map((i: any) => i.name || i));
    }).catch(() => {});
  }, []);

  const save = () => {
    localStorage.setItem("ego_settings", JSON.stringify(settings));
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div style={{ padding: 32, maxWidth: 700, margin: "0 auto" }}>
      <h2 style={{ color: "#fff", marginBottom: 24, fontSize: 18 }}>⚙️ Settings</h2>

      {/* Session Analyzer Config */}
      <div style={{
        background: "#16213e",
        borderRadius: 8,
        padding: 20,
        marginBottom: 20,
        border: "1px solid #1e3a5f",
      }}>
        <h3 style={{ color: "#7ecfff", fontSize: 14, margin: "0 0 16px" }}>
          Session Analyzer Configuration
        </h3>
        <p style={{ color: "#888", fontSize: 12, marginBottom: 16 }}>
          Configure which harness and identity to use when analyzing sessions from the Sessions tab.
        </p>

        <div style={{ marginBottom: 12 }}>
          <label style={{ display: "block", color: "#aaa", fontSize: 12, marginBottom: 4 }}>
            Analyzer Harness
          </label>
          <select
            value={settings.analyzer_harness}
            onChange={(e) => setSettings({ ...settings, analyzer_harness: e.target.value })}
            style={{
              width: "100%",
              padding: "8px 12px",
              background: "#0d1b2a",
              border: "1px solid #1e3a5f",
              borderRadius: 4,
              color: "#ddd",
              fontSize: 13,
            }}
          >
            {harnesses.map(h => (
              <option key={h} value={h}>{h}</option>
            ))}
          </select>
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={{ display: "block", color: "#aaa", fontSize: 12, marginBottom: 4 }}>
            Analyzer Identity (Agent)
          </label>
          <select
            value={settings.analyzer_identity}
            onChange={(e) => setSettings({ ...settings, analyzer_identity: e.target.value })}
            style={{
              width: "100%",
              padding: "8px 12px",
              background: "#0d1b2a",
              border: "1px solid #1e3a5f",
              borderRadius: 4,
              color: "#ddd",
              fontSize: 13,
            }}
          >
            {identities.map(i => (
              <option key={i} value={i}>{i}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Improver Config */}
      <div style={{
        background: "#16213e",
        borderRadius: 8,
        padding: 20,
        marginBottom: 20,
        border: "1px solid #1e3a5f",
      }}>
        <h3 style={{ color: "#7ecfff", fontSize: 14, margin: "0 0 16px" }}>
          Improver Agent
        </h3>
        <p style={{ color: "#888", fontSize: 12, marginBottom: 8 }}>
          The Improver is a specialized harness that iteratively improves other harnesses.
          It generates test tasks, runs them, analyzes results, and modifies prompts/pipelines.
        </p>
        <p style={{ color: "#666", fontSize: 12 }}>
          Harness: <code style={{ color: "#7ecfff" }}>improver</code> &nbsp;|&nbsp;
          Identity: <code style={{ color: "#7ecfff" }}>dante</code>
        </p>
        <p style={{ color: "#666", fontSize: 11, marginTop: 8 }}>
          To use: Go to Harness 编排 tab → load "improver" → assign dante to the improver slot → run with instructions like "Improve the react_single harness"
        </p>
      </div>

      {/* Save Button */}
      <button
        onClick={save}
        style={{
          padding: "10px 24px",
          background: saved ? "#065f46" : "linear-gradient(135deg, #0ea5e9, #7ecfff)",
          border: "none",
          borderRadius: 6,
          color: "#fff",
          cursor: "pointer",
          fontSize: 13,
          fontWeight: "bold",
          transition: "all 0.2s",
        }}
      >
        {saved ? "✓ Saved!" : "Save Settings"}
      </button>
    </div>
  );
}
