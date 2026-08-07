/**
 * EvolutionPanel - 自进化控制面板
 * 显示进化历史、原则库、启动进化周期。
 */
import { useState, useEffect } from "react";

const API_BASE = `http://${window.location.hostname}:8765`;

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

export default function EvolutionPanel() {
  const [archive, setArchive] = useState<ArchiveEntry[]>([]);
  const [principles, setPrinciples] = useState<Principle[]>([]);
  const [loading, setLoading] = useState(false);
  const [evoTaskId, setEvoTaskId] = useState<string | null>(() => {
    return localStorage.getItem("evo_task_id") || null;
  });
  const [evoStatus, setEvoStatus] = useState<string>(() => {
    return localStorage.getItem("evo_status") || "";
  });
  const [evoReport, setEvoReport] = useState<EvolutionReport | null>(() => {
    const saved = localStorage.getItem("evo_report");
    return saved ? JSON.parse(saved) : null;
  });
  const [targetHarness, setTargetHarness] = useState("react_single");
  const [targetIdentity, setTargetIdentity] = useState("dante");
  const [iterations, setIterations] = useState(3);
  const [evoMode, setEvoMode] = useState<"v2_structural" | "harness" | "engine">("v2_structural");

  // 持久化进化状态
  useEffect(() => {
    if (evoTaskId) localStorage.setItem("evo_task_id", evoTaskId);
    else localStorage.removeItem("evo_task_id");
  }, [evoTaskId]);
  useEffect(() => {
    if (evoStatus) localStorage.setItem("evo_status", evoStatus);
    else localStorage.removeItem("evo_status");
  }, [evoStatus]);
  useEffect(() => {
    if (evoReport) localStorage.setItem("evo_report", JSON.stringify(evoReport));
    else localStorage.removeItem("evo_report");
  }, [evoReport]);

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

  const cardStyle: React.CSSProperties = {
    background: "#16213e",
    borderRadius: 8,
    border: "1px solid #1e3a5f",
    padding: "14px 16px",
    marginBottom: 12,
  };

  return (
    <div style={{ padding: 20, maxWidth: 900, margin: "0 auto", color: "#e0e0e0" }}>
      <h2 style={{ color: "#7ecfff", marginBottom: 4 }}>🧬 Self-Evolution Engine</h2>
      <p style={{ color: "#888", fontSize: 12, marginBottom: 20 }}>
        自主进化循环：生成前沿任务 → 评估基线 → 分析失败 → 文本梯度优化 → 门控决策 → 归档
      </p>

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
              <option value="v2_structural">V2 Structural (DAG + Script)</option>
              <option value="harness">Harness Pipeline (DAG)</option>
              <option value="engine">Engine (legacy)</option>
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
      <div style={cardStyle}>
        <h3 style={{ margin: "0 0 10px", fontSize: 14, color: "#7ecfff" }}>
          📚 Principle Library ({principles.length})
        </h3>
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

      {/* 进化归档 */}
      <div style={cardStyle}>
        <h3 style={{ margin: "0 0 10px", fontSize: 14, color: "#7ecfff" }}>
          📜 Evolution Archive ({archive.length} records)
        </h3>
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
