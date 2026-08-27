import { useCallback, useEffect, useMemo, useState } from "react";
import {
  assignModelRole,
  deleteModelProfile,
  getModelProfiles,
  previewModelRoute,
  saveModelProfile,
} from "../api/client";

const MODEL_ROLES = [
  "chat", "tool_use", "edit", "apply", "autocomplete", "embedding",
  "rerank", "vision", "reasoning", "judge", "evolver",
] as const;

type ModelRole = typeof MODEL_ROLES[number];

interface ModelProfile {
  id: string;
  name: string;
  provider: string;
  base_url: string;
  model: string;
  api_key_env: string;
  has_api_key?: boolean;
  enabled: boolean;
  priority: number;
  roles: string[];
  context_window: number;
  max_tokens: number;
  temperature: number;
  input_cost_per_m: number;
  output_cost_per_m: number;
  enable_thinking?: boolean;
  health?: {
    success_rate?: number;
    ewma_latency_ms?: number;
    consecutive_failures?: number;
    circuit_open_until?: number;
    last_error?: string | null;
  };
}

const EMPTY_PROFILE: ModelProfile = {
  id: "",
  name: "",
  provider: "openai_compatible",
  base_url: "",
  model: "",
  api_key_env: "EGOAGENT_LLM_API_KEY",
  enabled: true,
  priority: 50,
  roles: ["chat"],
  context_window: 128000,
  max_tokens: 4096,
  temperature: 0.2,
  input_cost_per_m: 0,
  output_cost_per_m: 0,
};

const card: React.CSSProperties = {
  background: "var(--surface-raised)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: 14,
};

const field: React.CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  background: "var(--input-background)",
  border: "1px solid var(--border)",
  color: "var(--text-primary)",
  borderRadius: 5,
  padding: "7px 8px",
  fontSize: 11,
};

const button: React.CSSProperties = {
  border: "1px solid var(--border)",
  borderRadius: 5,
  background: "var(--button-bg)",
  color: "var(--button-text)",
  padding: "6px 9px",
  cursor: "pointer",
  fontSize: 11,
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "grid", gap: 5, color: "#94a3b8", fontSize: 10 }}>
      <span>{label}</span>
      {children}
    </label>
  );
}

export default function ModelProfiles() {
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [assignments, setAssignments] = useState<Record<string, string[]>>({});
  const [selectedRole, setSelectedRole] = useState<ModelRole>("chat");
  const [draft, setDraft] = useState<ModelProfile>({ ...EMPTY_PROFILE });
  const [routeInput, setRouteInput] = useState({ context_tokens: 12000, expected_output_tokens: 2000 });
  const [route, setRoute] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    const data = await getModelProfiles();
    setProfiles(data.profiles || []);
    setAssignments(data.roles || {});
  }, []);

  useEffect(() => {
    refresh().catch((error) => setMessage(error instanceof Error ? error.message : String(error)));
  }, [refresh]);

  const ordered = useMemo(() => assignments[selectedRole] || [], [assignments, selectedRole]);

  const mutate = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true);
    setMessage("");
    try {
      await action();
      await refresh();
      setMessage(success);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const saveDraft = () => mutate(async () => {
    if (!draft.name.trim() || !draft.base_url.trim() || !draft.model.trim()) {
      throw new Error("Name, base URL, and model are required");
    }
    await saveModelProfile({ ...draft, id: draft.id || undefined });
    setDraft({ ...EMPTY_PROFILE });
  }, "Model profile saved");

  const updateRole = (profileId: string, enabled: boolean) => {
    const next = enabled ? [...ordered, profileId] : ordered.filter((id) => id !== profileId);
    void mutate(() => assignModelRole(selectedRole, next), `${selectedRole} fallback order saved`);
  };

  const moveRole = (profileId: string, direction: -1 | 1) => {
    const next = [...ordered];
    const index = next.indexOf(profileId);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    void mutate(() => assignModelRole(selectedRole, next), `${selectedRole} fallback order saved`);
  };

  const preview = async () => {
    setBusy(true);
    setMessage("");
    try {
      setRoute(await previewModelRoute({ role: selectedRole, ...routeInput }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const numberField = (key: keyof ModelProfile) => (event: React.ChangeEvent<HTMLInputElement>) => {
    setDraft((value) => ({ ...value, [key]: Number(event.target.value) }));
  };

  return (
    <section style={{ background: "var(--surface-raised)", border: "1px solid var(--border)", borderRadius: 8, padding: 20, marginBottom: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "start" }}>
        <div>
          <h3 style={{ color: "#7ecfff", fontSize: 14, margin: "0 0 5px" }}>Role-aware model routing</h3>
          <p style={{ color: "#94a3b8", fontSize: 11, margin: 0, lineHeight: 1.6 }}>
            Assign independent models and ordered fallbacks to chat, editing, autocomplete, judging, and evolution.
            Secret values are read from server environment variables and are never stored here.
          </p>
        </div>
        <button style={button} disabled={busy} onClick={() => void refresh()}>Refresh</button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: 10, marginTop: 14 }}>
        {profiles.map((profile) => {
          const health = profile.health || {};
          const circuitOpen = Number(health.circuit_open_until || 0) * 1000 > Date.now();
          return (
            <div key={profile.id} style={card}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <div style={{ minWidth: 0 }}>
                  <b style={{ color: "#e2e8f0", fontSize: 12 }}>{profile.name}</b>
                  <div style={{ color: "#7dd3fc", fontSize: 10, overflow: "hidden", textOverflow: "ellipsis" }}>{profile.provider} · {profile.model}</div>
                </div>
                <span title={circuitOpen ? health.last_error || "Circuit open" : "Available"} style={{ color: circuitOpen ? "#fca5a5" : profile.has_api_key || profile.provider === "ollama" ? "#86efac" : "#fcd34d", fontSize: 10 }}>
                  {circuitOpen ? "circuit open" : profile.has_api_key || profile.provider === "ollama" ? "ready" : "key missing"}
                </span>
              </div>
              <div style={{ color: "#94a3b8", fontSize: 10, marginTop: 8, lineHeight: 1.6 }}>
                <div>{profile.context_window.toLocaleString()} ctx · priority {profile.priority}</div>
                <div>¥/M input {profile.input_cost_per_m} · output {profile.output_cost_per_m}</div>
                <div>{health.ewma_latency_ms ? `${Math.round(health.ewma_latency_ms)} ms · ` : ""}{health.success_rate !== undefined ? `${Math.round(health.success_rate * 100)}% success` : "not probed"}</div>
                <div title={profile.api_key_env}>secret: {profile.api_key_env || "local provider"}</div>
              </div>
              <div style={{ display: "flex", gap: 6, marginTop: 9 }}>
                <button style={button} onClick={() => setDraft({ ...profile })}>Edit</button>
                <button style={{ ...button, color: "#fecaca", borderColor: "#7f1d1d" }} onClick={() => {
                  if (window.confirm(`Delete model profile “${profile.name}”?`)) {
                    void mutate(() => deleteModelProfile(profile.id), "Model profile deleted");
                  }
                }}>Delete</button>
              </div>
            </div>
          );
        })}
      </div>

      <details style={{ ...card, marginTop: 12 }} open={profiles.length === 0}>
        <summary style={{ color: "#dbeafe", cursor: "pointer", fontSize: 12 }}>{draft.id ? `Edit ${draft.name}` : "Add model profile"}</summary>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 10, marginTop: 12 }}>
          <Field label="Display name"><input style={field} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></Field>
          <Field label="Provider"><input style={field} value={draft.provider} onChange={(e) => setDraft({ ...draft, provider: e.target.value })} /></Field>
          <Field label="Model ID"><input style={field} value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} /></Field>
          <Field label="Base URL"><input style={field} value={draft.base_url} onChange={(e) => setDraft({ ...draft, base_url: e.target.value })} /></Field>
          <Field label="Secret environment variable (name only)"><input style={field} value={draft.api_key_env} onChange={(e) => setDraft({ ...draft, api_key_env: e.target.value })} /></Field>
          <Field label="Priority"><input style={field} type="number" value={draft.priority} onChange={numberField("priority")} /></Field>
          <Field label="Context window"><input style={field} type="number" min={1} value={draft.context_window} onChange={numberField("context_window")} /></Field>
          <Field label="Maximum output tokens"><input style={field} type="number" min={1} value={draft.max_tokens} onChange={numberField("max_tokens")} /></Field>
          <Field label="Temperature"><input style={field} type="number" min={0} max={2} step={0.1} value={draft.temperature} onChange={numberField("temperature")} /></Field>
          <Field label="Input cost / M tokens"><input style={field} type="number" min={0} step={0.01} value={draft.input_cost_per_m} onChange={numberField("input_cost_per_m")} /></Field>
          <Field label="Output cost / M tokens"><input style={field} type="number" min={0} step={0.01} value={draft.output_cost_per_m} onChange={numberField("output_cost_per_m")} /></Field>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
          {MODEL_ROLES.map((roleName) => (
            <label key={roleName} style={{ color: "#cbd5e1", fontSize: 10 }}>
              <input type="checkbox" checked={draft.roles.includes(roleName)} onChange={(e) => setDraft({ ...draft, roles: e.target.checked ? [...draft.roles, roleName] : draft.roles.filter((role) => role !== roleName) })} /> {roleName}
            </label>
          ))}
          <label style={{ color: "#cbd5e1", fontSize: 10 }}><input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} /> enabled</label>
          <label style={{ color: "#cbd5e1", fontSize: 10 }}><input type="checkbox" checked={Boolean(draft.enable_thinking)} onChange={(e) => setDraft({ ...draft, enable_thinking: e.target.checked })} /> thinking</label>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <button disabled={busy} style={{ ...button, background: "#0369a1" }} onClick={() => void saveDraft()}>Save profile</button>
          {draft.id && <button style={button} onClick={() => setDraft({ ...EMPTY_PROFILE })}>Cancel edit</button>}
        </div>
      </details>

      <div style={{ ...card, marginTop: 12 }}>
        <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 9 }}>
          <b style={{ color: "#dbeafe", fontSize: 12 }}>Role fallback order</b>
          <select style={{ ...field, width: 150 }} value={selectedRole} onChange={(e) => { setSelectedRole(e.target.value as ModelRole); setRoute(null); }}>
            {MODEL_ROLES.map((roleName) => <option key={roleName}>{roleName}</option>)}
          </select>
          <span style={{ color: "#64748b", fontSize: 10 }}>First eligible model wins after health, context, cost, and budget scoring.</span>
        </div>
        <div style={{ display: "grid", gap: 6, marginTop: 10 }}>
          {profiles.map((profile) => {
            const index = ordered.indexOf(profile.id);
            return (
              <div key={profile.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 8px", background: "var(--surface-sunken)", borderRadius: 5 }}>
                <input type="checkbox" checked={index >= 0} onChange={(e) => updateRole(profile.id, e.target.checked)} />
                <span style={{ color: "#cbd5e1", fontSize: 11, flex: 1 }}>{index >= 0 ? `${index + 1}. ` : ""}{profile.name}</span>
                <button style={button} disabled={index <= 0} onClick={() => moveRole(profile.id, -1)}>↑</button>
                <button style={button} disabled={index < 0 || index === ordered.length - 1} onClick={() => moveRole(profile.id, 1)}>↓</button>
              </div>
            );
          })}
        </div>

        <div style={{ display: "flex", alignItems: "end", flexWrap: "wrap", gap: 8, marginTop: 12 }}>
          <Field label="Estimated input tokens"><input style={{ ...field, width: 130 }} type="number" min={0} value={routeInput.context_tokens} onChange={(e) => setRouteInput({ ...routeInput, context_tokens: Number(e.target.value) })} /></Field>
          <Field label="Estimated output tokens"><input style={{ ...field, width: 130 }} type="number" min={0} value={routeInput.expected_output_tokens} onChange={(e) => setRouteInput({ ...routeInput, expected_output_tokens: Number(e.target.value) })} /></Field>
          <button disabled={busy} style={{ ...button, background: "#0369a1" }} onClick={() => void preview()}>Preview route</button>
        </div>
        {route && (
          <div style={{ marginTop: 10, padding: 9, borderRadius: 5, background: route.error ? "#3f151c" : "#0b2e24", color: route.error ? "#fecaca" : "#bbf7d0", fontSize: 11 }}>
            {route.error || <>Selected <b>{route.name}</b> · {route.model} · estimated cost {Number(route.selection?.estimated_cost || 0).toFixed(6)}</>}
          </div>
        )}
      </div>
      {message && <div style={{ color: message.toLowerCase().includes("error") || message.toLowerCase().includes("required") ? "#fca5a5" : "#93c5fd", fontSize: 11, marginTop: 10 }}>{message}</div>}
    </section>
  );
}
