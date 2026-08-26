import { useState, useEffect } from "react";
import { getAIStatus, probeAIProvider } from "../api/client";
import ModelProfiles from "./ModelProfiles";
import ProductSetupPanel from "./ProductSetupPanel";
import SecuritySettings from "./SecuritySettings";
import TrajectoryCollectionSettingsPanel from "./TrajectoryCollectionSettings";

import { API_BASE as BASE } from '../api/runtime';

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
  const [aiStatus, setAIStatus] = useState<any>(null);
  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState("");

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
    getAIStatus().then(setAIStatus).catch((error) => setProbeError(String(error)));
  }, []);

  const runProbe = async () => {
    setProbing(true);
    setProbeError("");
    try {
      await probeAIProvider();
      setAIStatus(await getAIStatus());
    } catch (error) {
      setProbeError(error instanceof Error ? error.message : String(error));
      try { setAIStatus(await getAIStatus()); } catch {}
    } finally {
      setProbing(false);
    }
  };

  const save = () => {
    localStorage.setItem("ego_settings", JSON.stringify(settings));
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div style={{ padding: 32, maxWidth: 700, margin: "0 auto" }}>
      <h2 style={{ color: "#fff", marginBottom: 24, fontSize: 18 }}>⚙️ Settings</h2>

      <div style={{
        background: "#16213e",
        borderRadius: 8,
        padding: 20,
        marginBottom: 20,
        border: `1px solid ${aiStatus?.health === false ? "#7f1d1d" : aiStatus?.health === true ? "#166534" : "#1e3a5f"}`,
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <div>
            <h3 style={{ color: "#7ecfff", fontSize: 14, margin: "0 0 5px" }}>Model provider</h3>
            <div style={{ color: "#cbd5e1", fontSize: 12 }}>
              {aiStatus ? `${aiStatus.provider} · ${aiStatus.model || "no model"}` : "Loading…"}
            </div>
          </div>
          <button
            onClick={runProbe}
            disabled={probing || !aiStatus?.configured}
            style={{ padding: "8px 13px", border: 0, borderRadius: 5, cursor: "pointer", background: "#0369a1", color: "white", opacity: probing || !aiStatus?.configured ? 0.5 : 1 }}
          >
            {probing ? "Probing…" : "Probe capabilities"}
          </button>
        </div>
        <div style={{ marginTop: 12, fontSize: 11, color: "#94a3b8", lineHeight: 1.7 }}>
          <div>Configured: <b style={{ color: aiStatus?.configured ? "#86efac" : "#fca5a5" }}>{aiStatus?.configured ? "yes" : "no"}</b></div>
          <div>API key: {aiStatus?.has_api_key ? "present (kept server-side)" : "not required / missing"}</div>
          <div>Health: {aiStatus?.health === true ? "healthy" : aiStatus?.health === false ? "failed" : "not probed"}</div>
        </div>
        {aiStatus?.capabilities && Object.keys(aiStatus.capabilities).length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
            {Object.entries(aiStatus.capabilities).map(([role, enabled]) => (
              <span key={role} style={{ padding: "3px 7px", borderRadius: 999, background: enabled ? "#14532d" : "#3f3f46", color: enabled ? "#bbf7d0" : "#a1a1aa", fontSize: 10 }}>
                {enabled ? "✓" : "–"} {role}
              </span>
            ))}
          </div>
        )}
        {aiStatus?.last_probe?.checks && (
          <details style={{ marginTop: 12 }}>
            <summary style={{ cursor: "pointer", color: "#94a3b8", fontSize: 11 }}>Protocol checks and latency</summary>
            <pre style={{ background: "#08111f", padding: 10, borderRadius: 4, color: "#cbd5e1", fontSize: 10, overflow: "auto" }}>{JSON.stringify(aiStatus.last_probe.checks, null, 2)}</pre>
          </details>
        )}
        {aiStatus?.last_request && (
          <div style={{ marginTop: 10, fontSize: 10, color: aiStatus.last_request.ok ? "#86efac" : "#fca5a5" }}>
            Last request: {aiStatus.last_request.ok ? "ok" : aiStatus.last_request.error} · {aiStatus.last_request.latency_ms} ms · retries {aiStatus.last_request.retries || 0}
          </div>
        )}
        {probeError && <div style={{ marginTop: 10, color: "#fca5a5", fontSize: 11 }}>{probeError}</div>}
      </div>

      <ProductSetupPanel />

      <TrajectoryCollectionSettingsPanel />

      <SecuritySettings />

      <ModelProfiles />

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
