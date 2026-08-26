import { useEffect, useRef, useState } from "react";
import {
  controlDurableRun,
  applyDurableRunHandoff,
  compareDurableRuns,
  createDurableRun,
  forkDurableRun,
  getDurableRunEvents,
  listDurableRuns,
  listHarnesses,
  listIdentities,
  previewDurableRunHandoff,
} from "../api/client";

type Run = {
  id: string;
  status: string;
  error?: string;
  result?: unknown;
  priority: number;
  attempts: number;
  max_attempts: number;
  pause_requested?: boolean;
  cancel_requested?: boolean;
  checkpoint_path?: string;
  created_at: number;
  updated_at: number;
  payload?: {
    harness?: string;
    identity?: string;
    workspace?: string;
    mode?: string;
    messages?: Array<{ role: string; content: string }>;
    isolation?: { strategy?: string; source_workspace?: string; workspace?: string } | null;
  };
};

const input: React.CSSProperties = {
  background: "#07111f", border: "1px solid #334155", borderRadius: 5,
  color: "#e2e8f0", padding: "7px 8px", fontSize: 11, boxSizing: "border-box",
};

const button: React.CSSProperties = {
  border: "1px solid #365270", borderRadius: 5, background: "#18314f",
  color: "#dbeafe", padding: "6px 10px", cursor: "pointer", fontSize: 11,
};

const terminal = new Set(["succeeded", "failed", "cancelled"]);

export default function BackgroundRuns() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [harnesses, setHarnesses] = useState<string[]>([]);
  const [identities, setIdentities] = useState<string[]>([]);
  const [form, setForm] = useState({
    harness: "react_single", identity: "dante", mode: "agent", workspace: "",
    task: "", mutationTargets: "", priority: 0, maxAttempts: 3, isolate: true,
  });
  const [events, setEvents] = useState<Record<string, any[]>>({});
  const [handoffs, setHandoffs] = useState<Record<string, any>>({});
  const [handoffSelections, setHandoffSelections] = useState<Record<string, string[]>>({});
  const [message, setMessage] = useState("");
  const [compareAnchor, setCompareAnchor] = useState<string | null>(null);
  const [comparison, setComparison] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const previousStatuses = useRef<Record<string, string>>({});

  const refresh = async () => {
    const response = await listDurableRuns();
    const next: Run[] = response.runs || [];
    for (const run of next) {
      const previous = previousStatuses.current[run.id];
      if (previous && previous !== run.status && terminal.has(run.status) && "Notification" in window && Notification.permission === "granted") {
        new Notification(`EgoAgent task ${run.status}`, { body: `${run.payload?.harness || "Harness"} · ${run.id.slice(0, 8)}` });
      }
      previousStatuses.current[run.id] = run.status;
    }
    setRuns(next);
  };

  useEffect(() => {
    Promise.all([listHarnesses(), listIdentities(), refresh()]).then(([hs, ids]) => {
      setHarnesses(hs || []);
      setIdentities(ids || []);
    }).catch((error) => setMessage(String(error)));
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(timer);
  }, []);

  const create = async () => {
    if (!form.task.trim() || !form.workspace.trim()) {
      setMessage("Task and workspace are required");
      return;
    }
    const mutationTargets = form.mutationTargets.split(",").map((item) => item.trim()).filter(Boolean);
    if (form.mode === "evolve" && !mutationTargets.length) {
      setMessage("Evolve mode requires explicit Identity/Harness targets");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      await createDurableRun({
        harness: form.harness,
        identity: form.identity,
        mode: form.mode,
        workspace: form.workspace,
        messages: [{ role: "user", content: form.task }],
        mutation_targets: mutationTargets,
        priority: form.priority,
        max_attempts: form.maxAttempts,
        isolate: form.isolate,
      });
      setForm((value) => ({ ...value, task: "" }));
      await refresh();
      setMessage("Background task queued");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const control = async (runId: string, action: "pause" | "resume" | "cancel") => {
    setBusy(true);
    try {
      await controlDurableRun(runId, action);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const loadEvents = async (runId: string) => {
    try {
      const response = await getDurableRunEvents(runId);
      setEvents((value) => ({ ...value, [runId]: response.events || [] }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };

  const loadHandoff = async (runId: string) => {
    try {
      const preview = await previewDurableRunHandoff(runId);
      setHandoffs((value) => ({ ...value, [runId]: preview }));
      setHandoffSelections((value) => ({
        ...value,
        [runId]: (preview.changes || []).filter((item: any) => !item.conflict).map((item: any) => item.path),
      }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };

  const applyHandoff = async (runId: string) => {
    const preview = handoffs[runId];
    const paths = handoffSelections[runId] || [];
    if (!preview || !paths.length) return;
    const hasDelete = (preview.changes || []).some((item: any) => paths.includes(item.path) && item.kind === "deleted");
    const confirmDelete = !hasDelete || window.confirm("The selected handoff deletes source files. Apply those deletions?");
    if (!confirmDelete) return;
    const result = await applyDurableRunHandoff(runId, {
      paths,
      expected_revisions: preview.expected_revisions || {},
      confirm_delete: hasDelete,
    });
    if (!result.ok) {
      setMessage(result.error || `Handoff conflicts: ${JSON.stringify(result.conflicts || [])}`);
      return;
    }
    setMessage(`${result.applied.length} background file changes applied into Agent review`);
    await loadHandoff(runId);
  };

  const fork = async (runId: string, replay = false) => {
    setBusy(true);
    try {
      const created = await forkDurableRun(runId, { replay, from_checkpoint: !replay });
      setMessage(`${replay ? "Replay" : "Checkpoint fork"} queued as ${created.id?.slice(0, 10)}`);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const selectComparison = async (runId: string) => {
    if (!compareAnchor || compareAnchor === runId) {
      setCompareAnchor(compareAnchor === runId ? null : runId);
      setComparison(null);
      return;
    }
    try {
      const result = await compareDurableRuns(compareAnchor, runId);
      setComparison(result);
      setCompareAnchor(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <div style={{ padding: 24, maxWidth: 1180, margin: "0 auto", color: "#e2e8f0" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", gap: 12 }}>
        <div>
          <h2 style={{ margin: "0 0 5px", fontSize: 18 }}>Background Agents</h2>
          <p style={{ color: "#94a3b8", fontSize: 11, margin: 0 }}>Durable queued Harness runs survive restarts, checkpoint every node, and support cooperative pause/resume/cancel.</p>
        </div>
        <button style={button} onClick={() => void refresh()}>↻ Refresh</button>
      </div>

      <section style={{ marginTop: 16, background: "#111c33", border: "1px solid #263a5a", borderRadius: 8, padding: 14 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 9 }}>
          <label style={{ fontSize: 10, color: "#94a3b8" }}>Harness<select style={{ ...input, width: "100%", display: "block", marginTop: 4 }} value={form.harness} onChange={(e) => setForm({ ...form, harness: e.target.value })}>{harnesses.map((value) => <option key={value}>{value}</option>)}</select></label>
          <label style={{ fontSize: 10, color: "#94a3b8" }}>Identity<select style={{ ...input, width: "100%", display: "block", marginTop: 4 }} value={form.identity} onChange={(e) => setForm({ ...form, identity: e.target.value })}>{identities.map((value) => <option key={value}>{value}</option>)}</select></label>
          <label style={{ fontSize: 10, color: "#94a3b8" }}>Mode<select style={{ ...input, width: "100%", display: "block", marginTop: 4 }} value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>{["chat", "plan", "agent", "debug", "evolve", "evaluate"].map((value) => <option key={value}>{value}</option>)}</select></label>
          <label style={{ fontSize: 10, color: "#94a3b8" }}>Priority<input style={{ ...input, width: "100%", display: "block", marginTop: 4 }} type="number" value={form.priority} onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })} /></label>
          <label style={{ fontSize: 10, color: "#94a3b8" }}>Attempts<input style={{ ...input, width: "100%", display: "block", marginTop: 4 }} type="number" min={1} max={100} value={form.maxAttempts} onChange={(e) => setForm({ ...form, maxAttempts: Number(e.target.value) })} /></label>
        </div>
        <label style={{ display: "block", marginTop: 9, fontSize: 10, color: "#94a3b8" }}>Workspace<input style={{ ...input, width: "100%", display: "block", marginTop: 4 }} placeholder="C:\\path\\to\\project" value={form.workspace} onChange={(e) => setForm({ ...form, workspace: e.target.value })} /></label>
        {form.mode === "evolve" && <label style={{ display: "block", marginTop: 9, fontSize: 10, color: "#94a3b8" }}>Allowed mutation targets (comma separated)<input style={{ ...input, width: "100%", display: "block", marginTop: 4 }} placeholder="my_harness, dante" value={form.mutationTargets} onChange={(e) => setForm({ ...form, mutationTargets: e.target.value })} /></label>}
        <label style={{ display: "block", marginTop: 9, fontSize: 10, color: "#cbd5e1" }}><input type="checkbox" checked={form.isolate} onChange={(e) => setForm({ ...form, isolate: e.target.checked })} /> Run in an isolated workspace copy (recommended; hand off reviewed changes later)</label>
        <label style={{ display: "block", marginTop: 9, fontSize: 10, color: "#94a3b8" }}>Task<textarea style={{ ...input, width: "100%", minHeight: 80, display: "block", marginTop: 4, resize: "vertical" }} value={form.task} onChange={(e) => setForm({ ...form, task: e.target.value })} /></label>
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10 }}>
          <button disabled={busy} style={{ ...button, background: "#0369a1" }} onClick={() => void create()}>Queue background task</button>
          <button style={button} onClick={() => { if ("Notification" in window) void Notification.requestPermission(); }}>Enable completion notifications</button>
          {message && <span style={{ color: "#93c5fd", fontSize: 11 }}>{message}</span>}
        </div>
      </section>

      {comparison && <section style={{ marginTop: 12, padding: 12, border: "1px solid #365270", borderRadius: 8, background: "#071827" }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}><b style={{ color: "#7dd3fc" }}>Run comparison</b><button style={button} onClick={() => setComparison(null)}>Close</button></div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 7, marginTop: 7, fontSize: 10, color: "#cbd5e1" }}>
          <span>{comparison.left.record.id.slice(0, 8)} ↔ {comparison.right.record.id.slice(0, 8)}</span>
          <span>same output: <b style={{ color: comparison.same_output ? "#86efac" : "#fca5a5" }}>{String(comparison.same_output)}</b></span>
          <span>common path: {comparison.path.common_prefix}</span>
          <span>Δ cost: {Number(comparison.delta.cost_actual || comparison.delta.cost_estimated || 0).toFixed(6)}</span>
          <span>Δ tokens: {Number(comparison.delta.input_tokens_actual || 0) + Number(comparison.delta.output_tokens_actual || 0)}</span>
        </div>
        <details style={{ marginTop: 7 }}><summary style={{ cursor: "pointer", fontSize: 10 }}>Path / output / mutation details</summary><pre style={{ background: "#020617", padding: 9, maxHeight: 330, overflow: "auto", fontSize: 9 }}>{JSON.stringify(comparison, null, 2)}</pre></details>
      </section>}

      <div style={{ display: "grid", gap: 10, marginTop: 14 }}>
        {runs.map((run) => (
          <details key={run.id} style={{ background: "#111c33", border: "1px solid #263a5a", borderRadius: 8, padding: 12 }}>
            <summary style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 10 }}>
              <b style={{ color: "#7dd3fc" }}>{run.id.slice(0, 10)}</b>
              <span style={{ color: terminal.has(run.status) ? run.status === "succeeded" ? "#86efac" : "#fca5a5" : "#fcd34d" }}>{run.status}{run.pause_requested ? " (pausing…)" : ""}</span>
              <span style={{ color: "#94a3b8", fontSize: 10 }}>{run.payload?.mode || "agent"} · {run.payload?.harness || "harness"} / {run.payload?.identity || "identity"} · attempt {run.attempts}/{run.max_attempts}</span>
            </summary>
            <div style={{ marginTop: 10, fontSize: 11, color: "#cbd5e1" }}>
              <div><b>Task:</b> {run.payload?.messages?.[0]?.content || "—"}</div>
              <div><b>Workspace:</b> {run.payload?.workspace || "—"}</div>
              {run.error && <div style={{ color: "#fca5a5" }}><b>Error:</b> {run.error}</div>}
              <div style={{ display: "flex", gap: 6, marginTop: 9 }}>
                {(run.status === "queued" || run.status === "running") && <button disabled={busy} style={button} onClick={() => void control(run.id, "pause")}>Pause</button>}
                {run.status === "paused" && <button disabled={busy} style={button} onClick={() => void control(run.id, "resume")}>Resume</button>}
                {!terminal.has(run.status) && <button disabled={busy} style={{ ...button, color: "#fecaca", borderColor: "#7f1d1d" }} onClick={() => window.confirm("Cancel this background task?") && void control(run.id, "cancel")}>Cancel</button>}
                <button style={button} onClick={() => void loadEvents(run.id)}>Load timeline</button>
                {run.payload?.isolation?.workspace && <button style={button} onClick={() => void loadHandoff(run.id)}>Review workspace handoff</button>}
                {(terminal.has(run.status) || run.status === "paused" || run.status === "interrupted") && <button disabled={busy} style={button} onClick={() => void fork(run.id, true)}>Replay</button>}
                {run.checkpoint_path && (terminal.has(run.status) || run.status === "paused" || run.status === "interrupted") && <button disabled={busy} style={button} onClick={() => void fork(run.id, false)}>Fork checkpoint</button>}
                <button style={{ ...button, borderColor: compareAnchor === run.id ? "#38bdf8" : "#365270" }} onClick={() => void selectComparison(run.id)}>{compareAnchor === run.id ? "Cancel compare" : compareAnchor ? "Compare with this" : "Select compare"}</button>
              </div>
              {events[run.id] && <pre style={{ background: "#020617", padding: 10, borderRadius: 5, maxHeight: 320, overflow: "auto", whiteSpace: "pre-wrap", fontSize: 10 }}>{JSON.stringify(events[run.id], null, 2)}</pre>}
              {run.result !== null && run.result !== undefined && <details><summary>Result</summary><pre style={{ background: "#020617", padding: 10, overflow: "auto", fontSize: 10 }}>{JSON.stringify(run.result, null, 2)}</pre></details>}
              {handoffs[run.id] && <div style={{ marginTop: 10, borderTop: "1px solid #334155", paddingTop: 9 }}>
                <b>Isolated workspace changes ({handoffs[run.id].changes?.length || 0})</b>
                {(handoffs[run.id].changes || []).map((item: any) => (
                  <details key={item.path} style={{ marginTop: 6, padding: 7, background: item.conflict ? "#3f151c" : "#071827", borderRadius: 5 }}>
                    <summary style={{ cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        disabled={item.conflict}
                        checked={(handoffSelections[run.id] || []).includes(item.path)}
                        onClick={(event) => event.stopPropagation()}
                        onChange={(event) => setHandoffSelections((value) => ({
                          ...value,
                          [run.id]: event.target.checked
                            ? [...(value[run.id] || []), item.path]
                            : (value[run.id] || []).filter((path) => path !== item.path),
                        }))}
                      /> {item.kind} · {item.path} {item.conflict ? "(source changed — conflict)" : ""}
                    </summary>
                    <pre style={{ whiteSpace: "pre-wrap", maxHeight: 300, overflow: "auto", fontSize: 10 }}>{item.binary ? "Binary file" : item.diff}</pre>
                  </details>
                ))}
                <button style={{ ...button, background: "#166534", marginTop: 8 }} onClick={() => void applyHandoff(run.id)}>Apply selected into Agent Changes</button>
              </div>}
            </div>
          </details>
        ))}
        {!runs.length && <div style={{ color: "#64748b", textAlign: "center", padding: 30 }}>No background tasks yet.</div>}
      </div>
    </div>
  );
}
