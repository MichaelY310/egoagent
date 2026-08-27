/**
 * EvolutionPanel - 自进化控制面板
 * 显示进化历史、原则库、启动进化周期。
 */
import { useState, useEffect, useRef } from "react";
import * as api from "../api/client";
import { API_BASE, WORKSPACE } from "../api/runtime";
import { loadWorkbenchSession, publishWorkbenchEvent, updateWorkbenchSession } from "../workbenchSession";
import ProofEvolutionLab from "./ProofEvolutionLab";

interface ArchiveEntry {
  id: string;
  timestamp: string;
  target: string;
  action: string;
  score_before: number;
  score_after: number;
  accepted: boolean;
}

interface Principle {
  id: string;
  type: string;
  description: string;
  score: number;
  usage_count: number;
  success_count: number;
}

interface EvolutionReport {
  target_harness: string;
  target_identity: string;
  initial_score: number;
  final_score: number;
  total_accepted: number;
  total_rejected: number;
  total_rollbacks: number;
  iterations: { iteration: number; score_before: number; score_after: number; action: string; decision: string }[];
}

interface CapabilityRecommendation {
  kind: string;
  pack?: string;
  recipe?: string;
  confidence: number;
  reason: string;
  suggested_steps?: string[];
}

export default function EvolutionPanel() {
  const restoredSelection = useRef(loadWorkbenchSession().evolution || {}).current;
  const [archive, setArchive] = useState<ArchiveEntry[]>([]);
  const [principles, setPrinciples] = useState<Principle[]>([]);
  const [loading, setLoading] = useState(false);
  const [evoTaskId, setEvoTaskId] = useState<string | null>(restoredSelection.taskId || null);
  const [evoStatus, setEvoStatus] = useState<string>(restoredSelection.status || "");
  const [evoReport, setEvoReport] = useState<EvolutionReport | null>((restoredSelection.report as EvolutionReport | null) || null);
  const [targetHarness, setTargetHarness] = useState(restoredSelection.harness || "react_single");
  const [targetIdentity, setTargetIdentity] = useState(restoredSelection.identity || "dante");
  const [iterations, setIterations] = useState(restoredSelection.iterations || 3);
  const [evoMode, setEvoMode] = useState<"v2_structural" | "harness" | "engine">(restoredSelection.mode || "engine");
  const [observations, setObservations] = useState(restoredSelection.observations || "");
  const [capabilityRecommendations, setCapabilityRecommendations] = useState<CapabilityRecommendation[]>([]);
  const [capabilityResult, setCapabilityResult] = useState<any>(null);
  const [capabilityBusy, setCapabilityBusy] = useState(false);
  const [lastCapabilityTransaction, setLastCapabilityTransaction] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => updateWorkbenchSession({ evolution: {
      harness: targetHarness,
      identity: targetIdentity,
      iterations,
      mode: evoMode,
      taskId: evoTaskId,
      status: evoStatus,
      observations,
      report: evoReport,
    } }), 250);
    return () => window.clearTimeout(timer);
  }, [targetHarness, targetIdentity, iterations, evoMode, evoTaskId, evoStatus, observations, evoReport]);

  useEffect(() => {
    publishWorkbenchEvent('runtime-status', {
      scope: 'evolution',
      workspace: WORKSPACE,
      running: Boolean(evoTaskId),
      status: evoStatus || (evoTaskId ? 'running' : 'idle'),
      harness: targetHarness,
      taskId: evoTaskId,
    });
  }, [evoTaskId, evoStatus, targetHarness]);

  // 加载数据
  const loadData = async () => {
    try {
      const [archRes, prinRes] = await Promise.all([
        fetch(`${API_BASE}/api/evolution/archive`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target: "", limit: 50 }),
        }),
        fetch(`${API_BASE}/api/evolution/principles`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: "all", top_k: 20 }),
        }),
      ]);
      if (archRes.ok) {
        const data = await archRes.json();
        setArchive(data.archive || []);
      }
      if (prinRes.ok) {
        const data = await prinRes.json();
        setPrinciples(data.principles || []);
      }
    } catch (e) {
      console.error("Failed to load evolution data:", e);
    }
  };

  useEffect(() => { loadData(); }, []);

  // 轮询进化状态
  useEffect(() => {
    if (!evoTaskId) return;
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/analyze-status/${evoTaskId}`);
        if (res.ok) {
          const data = await res.json();
          setEvoStatus(data.progress || data.status);
          if (data.status === "completed") {
            setEvoReport(data.result);
            setEvoTaskId(null);
            loadData(); // 刷新数据
          } else if (data.status === "error") {
            setEvoStatus(`error: ${data.error}`);
            setEvoTaskId(null);
          }
        }
      } catch (e) { /* ignore */ }
    }, 3000);
    return () => clearInterval(interval);
  }, [evoTaskId]);

  // 启动进化
  const startEvolution = async () => {
    setLoading(true);
    setEvoReport(null);
    setEvoStatus("starting...");
    try {
      const res = await fetch(`${API_BASE}/api/evolution/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          harness: targetHarness,
          identity: targetIdentity,
          iterations: iterations,
          mode: evoMode,
          workspace: WORKSPACE || undefined,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setEvoTaskId(data.task_id);
        setEvoStatus("running");
      }
    } catch (e) {
      setEvoStatus("failed to start");
    }
    setLoading(false);
  };

  const analyzeCapabilities = async () => {
    if (!observations.trim()) return;
    setCapabilityBusy(true);
    try {
      const result = await api.analyzeCapabilityEvolution(observations, WORKSPACE);
      setCapabilityRecommendations(result.recommendations || []);
      setCapabilityResult(result);
    } catch (error: any) {
      setCapabilityResult({ ok: false, error: error.message });
    } finally {
      setCapabilityBusy(false);
    }
  };

  const installCapability = async (pack: string, dryRun: boolean) => {
    setCapabilityBusy(true);
    try {
      const result = await api.installCapabilityEvolution(targetIdentity, pack, dryRun, observations.slice(0, 500));
      setCapabilityResult(result);
      if (!dryRun && result.transaction_id) setLastCapabilityTransaction(result.transaction_id);
    } catch (error: any) {
      setCapabilityResult({ ok: false, error: error.message });
    } finally {
      setCapabilityBusy(false);
    }
  };

  const rollbackCapability = async () => {
    if (!lastCapabilityTransaction) return;
    setCapabilityBusy(true);
    try {
      const result = await api.rollbackCapabilityEvolution(lastCapabilityTransaction);
      setCapabilityResult(result);
      setLastCapabilityTransaction("");
    } catch (error: any) {
      setCapabilityResult({ ok: false, error: error.message });
    } finally {
      setCapabilityBusy(false);
    }
  };

  const cardStyle: React.CSSProperties = {
    background: "var(--surface-raised)",
    borderRadius: 8,
    border: "1px solid var(--border)",
    padding: "14px 16px",
    marginBottom: 12,
  };

  return (
    <div className="evolution-workbench" style={{ padding: 20, maxWidth: 980, margin: "0 auto", color: "var(--text-primary)" }}>
      <h2 style={{ color: "var(--text-primary)", marginBottom: 4 }}>Improve</h2>
      <p style={{ color: "var(--text-muted)", fontSize: 12, marginBottom: 20 }}>
        从真实失败开始，只添加必要能力；通过 held-out、回滚与因果证书后再部署。
      </p>

      <div style={{ ...cardStyle, borderColor: "#0e7490" }}>
        <h3 style={{ margin: "0 0 5px", fontSize: 14, color: "#67e8f9" }}>🧩 Identity 能力进化诊断</h3>
        <p style={{ color: "#94a3b8", fontSize: 11, margin: "0 0 8px" }}>
          粘贴任务、失败轨迹或 Session 摘要。系统先判断应该添加知识、Skill、隔离子 Agent，还是修改 Harness；安装支持预览与精确回滚。
        </p>
        <div style={{ display: "flex", gap: 8, marginBottom: 7 }}>
          <label style={{ fontSize: 11, color: "#94a3b8", flex: "0 0 190px" }}>
            目标 Identity
            <input value={targetIdentity} onChange={(e) => setTargetIdentity(e.target.value)} style={{ display: "block", width: "100%", marginTop: 3, padding: "5px 7px", boxSizing: "border-box", background: "#0a1628", border: "1px solid #1e3a5f", borderRadius: 4, color: "#fff" }} />
          </label>
          <textarea
            value={observations}
            onChange={(event) => setObservations(event.target.value)}
            placeholder="例如：给 Agent 多篇本地 PDF；之后询问某篇内容时它忽略文件、反复上网搜索，三次失败又占满上下文……"
            rows={5}
            style={{ flex: 1, padding: 8, background: "#0a1628", border: "1px solid #1e3a5f", borderRadius: 4, color: "#e2e8f0", resize: "vertical" }}
          />
        </div>
        <button onClick={analyzeCapabilities} disabled={capabilityBusy || !observations.trim()} style={{ padding: "6px 14px", background: "#0e7490", color: "white", border: 0, borderRadius: 4, cursor: "pointer" }}>
          {capabilityBusy ? "处理中..." : "分析最小进化方案"}
        </button>
        {lastCapabilityTransaction && (
          <button onClick={rollbackCapability} disabled={capabilityBusy} style={{ marginLeft: 7, padding: "6px 14px", background: "#7f1d1d", color: "#fecaca", border: 0, borderRadius: 4, cursor: "pointer" }}>
            回滚最近安装 {lastCapabilityTransaction}
          </button>
        )}
        {capabilityRecommendations.map((recommendation, index) => (
          <div key={`${recommendation.pack || recommendation.recipe}-${index}`} style={{ marginTop: 8, padding: 9, background: "#071827", border: "1px solid #164e63", borderRadius: 6 }}>
            <div style={{ display: "flex", gap: 7, alignItems: "center" }}>
              <b style={{ color: "#a5f3fc", fontSize: 12 }}>{recommendation.pack || recommendation.recipe}</b>
              <span style={{ color: "#64748b", fontSize: 10 }}>{Math.round(recommendation.confidence * 100)}% · {recommendation.kind}</span>
            </div>
            <div style={{ color: "#cbd5e1", fontSize: 11, marginTop: 3 }}>{recommendation.reason}</div>
            {recommendation.pack && (
              <div style={{ marginTop: 6, display: "flex", gap: 6 }}>
                <button onClick={() => installCapability(recommendation.pack!, true)} disabled={capabilityBusy} style={{ padding: "4px 9px", background: "#1e3a5f", color: "#bae6fd", border: 0, borderRadius: 4, cursor: "pointer", fontSize: 10 }}>预览文件</button>
                <button onClick={() => installCapability(recommendation.pack!, false)} disabled={capabilityBusy} style={{ padding: "4px 9px", background: "#166534", color: "#bbf7d0", border: 0, borderRadius: 4, cursor: "pointer", fontSize: 10 }}>安装并记录事务</button>
              </div>
            )}
          </div>
        ))}
        {capabilityResult && (
          <details style={{ marginTop: 8 }} open={!capabilityResult.ok}>
            <summary style={{ cursor: "pointer", color: capabilityResult.ok === false ? "#fca5a5" : "#94a3b8", fontSize: 11 }}>最近结果</summary>
            <pre style={{ maxHeight: 260, overflow: "auto", padding: 8, background: "#020617", color: "#cbd5e1", fontSize: 10, whiteSpace: "pre-wrap" }}>{JSON.stringify(capabilityResult, null, 2)}</pre>
          </details>
        )}
      </div>

      <details style={{ ...cardStyle, padding: 0, overflow: "hidden" }}>
        <summary style={{ padding: "12px 16px", cursor: "pointer", color: "#c4b5fd", fontSize: 12 }}>
          Advanced · 证据协议、候选层选择与 held-out gate
        </summary>
        <div style={{ padding: "0 12px 12px" }}><ProofEvolutionLab /></div>
      </details>

      {/* 启动进化 */}
      <div style={cardStyle}>
        <h3 style={{ margin: "0 0 10px", fontSize: 14, color: "#7ecfff" }}>▶ 启动进化周期</h3>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <label style={{ fontSize: 12 }}>
            Mode:
            <select
              value={evoMode}
              onChange={(e) => setEvoMode(e.target.value as "v2_structural" | "harness" | "engine")}
              style={{ marginLeft: 4, padding: "4px 8px", background: "#0a1628", border: "1px solid #1e3a5f", borderRadius: 4, color: "#fff" }}
            >
              <option value="engine">Unified Evolution（能力 + 评估 + 回滚）</option>
              <option value="harness">Harness Pipeline（可视 DAG）</option>
              <option value="v2_structural">Structural Lab V2（实验性）</option>
            </select>
          </label>
          <label style={{ fontSize: 12 }}>
            Harness:
            <input
              value={targetHarness}
              onChange={(e) => setTargetHarness(e.target.value)}
              style={{ marginLeft: 4, padding: "4px 8px", background: "#0a1628", border: "1px solid #1e3a5f", borderRadius: 4, color: "#fff", width: 120 }}
            />
          </label>
          <label style={{ fontSize: 12 }}>
            Identity:
            <input
              value={targetIdentity}
              onChange={(e) => setTargetIdentity(e.target.value)}
              style={{ marginLeft: 4, padding: "4px 8px", background: "#0a1628", border: "1px solid #1e3a5f", borderRadius: 4, color: "#fff", width: 120 }}
            />
          </label>
          <label style={{ fontSize: 12 }}>
            Iterations:
            <input
              type="number"
              value={iterations}
              onChange={(e) => setIterations(parseInt(e.target.value) || 3)}
              min={1}
              max={10}
              style={{ marginLeft: 4, padding: "4px 8px", background: "#0a1628", border: "1px solid #1e3a5f", borderRadius: 4, color: "#fff", width: 50 }}
            />
          </label>
          <button
            onClick={startEvolution}
            disabled={loading || !!evoTaskId}
            style={{
              padding: "6px 16px",
              background: evoTaskId ? "#555" : "#2563eb",
              color: "#fff",
              border: "none",
              borderRadius: 4,
              cursor: evoTaskId ? "not-allowed" : "pointer",
              fontSize: 12,
              fontWeight: "bold",
            }}
          >
            {evoTaskId ? "⏳ Running..." : "🧬 Start Evolution"}
          </button>
        </div>
        {evoStatus && (
          <div style={{ marginTop: 8, fontSize: 11, color: evoStatus.includes("error") ? "#ff6b6b" : "#4ade80" }}>
            Status: {evoStatus}
          </div>
        )}
      </div>

      {/* 进化报告 */}
      {evoReport && (
        <div style={{ ...cardStyle, border: "1px solid #2563eb" }}>
          <h3 style={{ margin: "0 0 10px", fontSize: 14, color: "#4ade80" }}>📊 Evolution Report</h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: 10 }}>
            <div style={{ textAlign: "center", padding: 8, background: "#0a1628", borderRadius: 4 }}>
              <div style={{ fontSize: 18, fontWeight: "bold", color: "#7ecfff" }}>{(evoReport.initial_score * 100).toFixed(0)}%</div>
              <div style={{ fontSize: 10, color: "#888" }}>Initial</div>
            </div>
            <div style={{ textAlign: "center", padding: 8, background: "#0a1628", borderRadius: 4 }}>
              <div style={{ fontSize: 18, fontWeight: "bold", color: evoReport.final_score > evoReport.initial_score ? "#4ade80" : "#ff6b6b" }}>
                {(evoReport.final_score * 100).toFixed(0)}%
              </div>
              <div style={{ fontSize: 10, color: "#888" }}>Final</div>
            </div>
            <div style={{ textAlign: "center", padding: 8, background: "#0a1628", borderRadius: 4 }}>
              <div style={{ fontSize: 18, fontWeight: "bold", color: "#4ade80" }}>{evoReport.total_accepted}</div>
              <div style={{ fontSize: 10, color: "#888" }}>Accepted</div>
            </div>
            <div style={{ textAlign: "center", padding: 8, background: "#0a1628", borderRadius: 4 }}>
              <div style={{ fontSize: 18, fontWeight: "bold", color: "#ff6b6b" }}>{evoReport.total_rollbacks}</div>
              <div style={{ fontSize: 10, color: "#888" }}>Rollbacks</div>
            </div>
          </div>
          {evoReport.iterations.map((iter) => (
            <div key={iter.iteration} style={{ fontSize: 11, padding: "4px 0", borderTop: "1px solid #1e3a5f", display: "flex", gap: 8 }}>
              <span style={{ color: "#888" }}>#{iter.iteration}</span>
              <span>{(iter.score_before * 100).toFixed(0)}% → {(iter.score_after * 100).toFixed(0)}%</span>
              <span style={{ color: iter.decision === "accept" ? "#4ade80" : "#ff6b6b" }}>{iter.decision}</span>
              <span style={{ color: "#888", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{iter.action}</span>
            </div>
          ))}
        </div>
      )}

      {/* V2 Structural Evolution Report */}
      {evoReport && (evoReport as any).structural_changes && (
        <div style={{ ...cardStyle, border: "1px solid #84cc16" }}>
          <h3 style={{ margin: "0 0 10px", fontSize: 14, color: "#a3e635" }}>🔧 V2 Structural Report</h3>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginBottom: 10 }}>
            <div style={{ textAlign: "center", padding: 8, background: "#0a1628", borderRadius: 4 }}>
              <div style={{ fontSize: 18, fontWeight: "bold", color: "#a3e635" }}>{(evoReport as any).structural_changes?.length || 0}</div>
              <div style={{ fontSize: 10, color: "#888" }}>Structural Changes</div>
            </div>
            <div style={{ textAlign: "center", padding: 8, background: "#0a1628", borderRadius: 4 }}>
              <div style={{ fontSize: 18, fontWeight: "bold", color: "#7ecfff" }}>{(evoReport as any).iterations?.length || 0}</div>
              <div style={{ fontSize: 10, color: "#888" }}>Iterations</div>
            </div>
            <div style={{ textAlign: "center", padding: 8, background: "#0a1628", borderRadius: 4 }}>
              <div style={{ fontSize: 18, fontWeight: "bold", color: "#fbbf24" }}>{(evoReport as any).scripts_written?.length || 0}</div>
              <div style={{ fontSize: 10, color: "#888" }}>Scripts Written</div>
            </div>
          </div>
          {(evoReport as any).iterations?.map((iter: any, idx: number) => (
            <div key={idx} style={{ fontSize: 11, padding: "6px 0", borderTop: "1px solid #1e3a5f" }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span style={{ color: "#888" }}>Round {iter.iteration}</span>
                <span style={{ color: "#a3e635" }}>Nodes: [{iter.nodes_after?.join(", ")}]</span>
              </div>
              {iter.actions?.map((a: any, i: number) => (
                <div key={i} style={{ marginLeft: 16, fontSize: 10, color: a.action.includes("node") || a.action.includes("rewire") ? "#84cc16" : "#888" }}>
                  → {a.action}: {a.result}
                </div>
              ))}
            </div>
          ))}
          {(evoReport as any).scripts_written?.length > 0 && (
            <div style={{ marginTop: 8, padding: "6px 8px", background: "#0a1628", borderRadius: 4, fontSize: 11 }}>
              <span style={{ color: "#a3e635" }}>📜 Scripts: </span>
              {(evoReport as any).scripts_written.map((s: string, i: number) => (
                <span key={i} style={{ color: "#e0e0e0", marginRight: 8 }}>{s}</span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 原则库 */}
      <details style={cardStyle}>
        <summary style={{ cursor: "pointer", color: "#d4d4d4", fontSize: 12 }}>
          History · Principle Library ({principles.length})
        </summary>
        <div style={{ marginTop: 10 }}>
        {principles.length === 0 ? (
          <p style={{ fontSize: 11, color: "#666" }}>Empty — run evolution cycles to populate.</p>
        ) : (
          <div style={{ maxHeight: 200, overflow: "auto" }}>
            {principles.sort((a, b) => b.score - a.score).map((p) => (
              <div key={p.id} style={{ fontSize: 11, padding: "4px 0", borderBottom: "1px solid #0a1628", display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{
                  display: "inline-block",
                  width: 6, height: 6, borderRadius: "50%",
                  background: p.type === "guiding" ? "#4ade80" : "#fbbf24",
                }} />
                <span style={{ flex: 1 }}>{p.description}</span>
                <span style={{ color: "#888", fontSize: 10 }}>
                  {(p.score * 100).toFixed(0)}% ({p.usage_count}×)
                </span>
              </div>
            ))}
          </div>
        )}
        </div>
      </details>

      {/* 进化归档 */}
      <details style={cardStyle}>
        <summary style={{ cursor: "pointer", color: "#d4d4d4", fontSize: 12 }}>
          History · Evolution Archive ({archive.length} records)
        </summary>
        <div style={{ marginTop: 10 }}>
        {archive.length === 0 ? (
          <p style={{ fontSize: 11, color: "#666" }}>No evolution attempts recorded yet.</p>
        ) : (
          <div style={{ maxHeight: 250, overflow: "auto" }}>
            <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #1e3a5f", color: "#888" }}>
                  <th style={{ textAlign: "left", padding: 4 }}>Time</th>
                  <th style={{ textAlign: "left", padding: 4 }}>Target</th>
                  <th style={{ textAlign: "center", padding: 4 }}>Before</th>
                  <th style={{ textAlign: "center", padding: 4 }}>After</th>
                  <th style={{ textAlign: "center", padding: 4 }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {archive.slice().reverse().map((entry) => (
                  <tr key={entry.id} style={{ borderBottom: "1px solid #0a1628" }}>
                    <td style={{ padding: 4, color: "#888" }}>{entry.timestamp?.slice(5, 16)}</td>
                    <td style={{ padding: 4 }}>{entry.target}</td>
                    <td style={{ padding: 4, textAlign: "center" }}>{(entry.score_before * 100).toFixed(0)}%</td>
                    <td style={{ padding: 4, textAlign: "center" }}>{(entry.score_after * 100).toFixed(0)}%</td>
                    <td style={{ padding: 4, textAlign: "center" }}>
                      <span style={{
                        padding: "1px 6px",
                        borderRadius: 3,
                        fontSize: 10,
                        background: entry.accepted ? "#064e3b" : "#4c0519",
                        color: entry.accepted ? "#4ade80" : "#ff6b6b",
                      }}>
                        {entry.accepted ? "✓" : "✗"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        </div>
      </details>

      {/* 刷新按钮 */}
      <button
        onClick={loadData}
        style={{
          padding: "6px 14px",
          background: "#1e3a5f",
          color: "#7ecfff",
          border: "none",
          borderRadius: 4,
          cursor: "pointer",
          fontSize: 11,
        }}
      >
        🔄 Refresh Data
      </button>
    </div>
  );
}
