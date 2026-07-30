import { useState, useEffect, useCallback, useRef } from "react";

interface SessionInfo {
  name: string;
  path: string;
  message_count: number;
}

interface EvalReport {
  report: string;
  session_name: string;
}

interface AnalyzeMessage {
  role: string;
  content: string;
  name?: string;
}

const BASE = `http://${window.location.hostname}:8765`;

export default function SessionExplorer() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [evalReport, setEvalReport] = useState<EvalReport | null>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("");
  const [analyzeStatus, setAnalyzeStatus] = useState<string>("");
  const [analyzeResult, setAnalyzeResult] = useState<any>(null);
  // 气泡聊天面板状态
  const [showAnalyzeChat, setShowAnalyzeChat] = useState(false);
  const [analyzeChatMessages, setAnalyzeChatMessages] = useState<AnalyzeMessage[]>([]);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch(`${BASE}/api/sessions`);
      const data = await res.json();
      setSessions(data);
    } catch (e) {
      console.error("Failed to fetch sessions:", e);
    }
  }, []);

  useEffect(() => { fetchSessions(); }, [fetchSessions]);

  useEffect(() => {
    if (chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [analyzeChatMessages]);

  const selectSession = async (name: string) => {
    setSelected(name);
    setEvalReport(null);
    setMessages([]);
    setLoading(true);
    try {
      // 只加载 messages（轻量），不调 /evaluate（会触发 LLM 推理导致超时）
      const msgsRes = await fetch(`${BASE}/api/session/${encodeURIComponent(name)}/messages`);
      if (msgsRes.ok) {
        const msgsData = await msgsRes.json();
        setMessages(msgsData);
      }
      // 尝试加载缓存的评估报告（如果之前 analyze 过）
      const cachedRes = await fetch(`${BASE}/api/session/${encodeURIComponent(name)}/cached-report`);
      if (cachedRes.ok) {
        const cachedData = await cachedRes.json();
        if (cachedData.report) setEvalReport(cachedData);
      }
    } catch (e) {
      console.error("Failed to load session:", e);
    }
    setLoading(false);
  };

  const triggerAnalyze = async () => {
    if (!selected) return;
    setAnalyzeStatus("🔄 Starting analysis...");
    setAnalyzeResult(null);
    setAnalyzeChatMessages([]);
    setShowAnalyzeChat(true);
    try {
      const settings = JSON.parse(localStorage.getItem("ego_settings") || "{}");
      const harness = settings.analyzer_harness || "session_analyzer";
      const identity = settings.analyzer_identity || "dante";
      const res = await fetch(`${BASE}/api/analyze-session`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session: selected, harness: harness, identity: identity }),
      });
      const data = await res.json();
      if (!data.task_id) {
        setAnalyzeStatus(`❌ ${data.error || "Unknown error"}`);
        return;
      }
      const taskId = data.task_id;
      setAnalyzeStatus("🔄 Agent analyzing...");
      // 添加初始系统消息
      setAnalyzeChatMessages([{ role: "system", content: `开始分析 session: ${selected}...` }]);

      for (let i = 0; i < 60; i++) {
        await new Promise(r => setTimeout(r, 3000));
        try {
          const statusRes = await fetch(`${BASE}/api/analyze-status/${taskId}`);
          const statusData = await statusRes.json();
          if (statusData.status === "completed") {
            setAnalyzeResult(statusData.result);
            setAnalyzeStatus("✅ Analysis Complete");
            // 填充聊天消息
            if (statusData.result?.messages) {
              setAnalyzeChatMessages(statusData.result.messages);
            }
            if (selected) selectSession(selected);
            return;
          } else if (statusData.status === "error") {
            setAnalyzeStatus(`❌ Error: ${statusData.error}`);
            setAnalyzeChatMessages(prev => [...prev, { role: "system", content: `❌ 分析出错: ${statusData.error}` }]);
            return;
          }
          setAnalyzeStatus(`🔄 Agent analyzing${"...".slice(0, (i % 3) + 1)} (${(i + 1) * 3}s)`);
        } catch {
          // Network error during poll, keep trying
        }
      }
      setAnalyzeStatus("⚠️ Timeout (3min)");
    } catch (e: any) {
      setAnalyzeStatus(`❌ ${e.message}`);
    }
  };

  const filteredSessions = sessions.filter(
    (s) => !filter || s.name.toLowerCase().includes(filter.toLowerCase())
  );

  const getEfficiency = (report: string): number | null => {
    const match = report.match(/Efficiency score: (\d+)\/100/);
    return match ? parseInt(match[1]) : null;
  };

  const getEfficiencyColor = (score: number) => {
    if (score >= 80) return "#4ade80";
    if (score >= 50) return "#fbbf24";
    return "#f87171";
  };

  // 解析消息内容用于气泡显示
  const parseMessageContent = (msg: AnalyzeMessage) => {
    const content = msg.content || "";
    const isToolCall = msg.role === "assistant" && content.includes("<tool_call>");
    const isToolResponse = msg.role === "user" && content.includes("<tool_response>");

    if (isToolCall) {
      const nameMatch = content.match(/"name":\s*"([^"]+)"/);
      const toolName = nameMatch ? nameMatch[1] : "tool";
      const textPart = content.replace(/<tool_call>[\s\S]*?<\/tool_call>/g, "").trim();
      return { type: "tool_call" as const, toolName, text: textPart };
    }
    if (isToolResponse) {
      const toolMatch = content.match(/"tool":\s*"([^"]+)"/);
      const contentMatch = content.match(/"content":\s*("(?:[^"\\]|\\.)*"|[\s\S]*?)(?:\s*})/);
      let resultPreview = "";
      if (contentMatch) {
        try {
          resultPreview = JSON.parse(contentMatch[1]).slice(0, 150);
        } catch {
          resultPreview = contentMatch[1].slice(0, 150);
        }
      }
      return { type: "tool_result" as const, toolName: toolMatch?.[1] || "?", text: resultPreview };
    }
    return { type: "text" as const, toolName: "", text: content };
  };

  return (
    <div style={{ display: "flex", height: "100%", background: "#0d1b2a" }}>
      {/* Left: Session List */}
      <div style={{
        width: 320,
        borderRight: "1px solid #1e3a5f",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid #1e3a5f" }}>
          <h3 style={{ margin: 0, color: "#7ecfff", fontSize: 14 }}>📊 Session Explorer</h3>
          <input
            type="text"
            placeholder="Filter sessions..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{
              width: "100%",
              marginTop: 8,
              padding: "6px 10px",
              background: "#16213e",
              border: "1px solid #1e3a5f",
              borderRadius: 4,
              color: "#ccc",
              fontSize: 12,
            }}
          />
        </div>
        <div style={{ flex: 1, overflow: "auto", padding: "8px 0" }}>
          {filteredSessions.map((s) => (
            <div
              key={s.name}
              onClick={() => selectSession(s.name)}
              style={{
                padding: "8px 16px",
                cursor: "pointer",
                background: selected === s.name ? "#1e3a5f" : "transparent",
                borderLeft: selected === s.name ? "3px solid #7ecfff" : "3px solid transparent",
                transition: "all 0.15s",
              }}
              onMouseEnter={(e) => { if (selected !== s.name) e.currentTarget.style.background = "#0f2744"; }}
              onMouseLeave={(e) => { if (selected !== s.name) e.currentTarget.style.background = "transparent"; }}
            >
              <div style={{ fontSize: 12, color: "#ddd", fontFamily: "monospace" }}>
                {s.name}
              </div>
              <div style={{ fontSize: 11, color: "#888", marginTop: 2 }}>
                {s.message_count} messages
              </div>
            </div>
          ))}
          {filteredSessions.length === 0 && (
            <div style={{ padding: 16, color: "#666", fontSize: 12, textAlign: "center" }}>
              No sessions found
            </div>
          )}
        </div>
        <div style={{ padding: "8px 16px", borderTop: "1px solid #1e3a5f" }}>
          <button
            onClick={fetchSessions}
            style={{
              width: "100%",
              padding: "6px",
              background: "#1e3a5f",
              border: "none",
              borderRadius: 4,
              color: "#7ecfff",
              cursor: "pointer",
              fontSize: 12,
            }}
          >
            🔄 Refresh
          </button>
        </div>
      </div>

      {/* Middle: Detail Panel */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        {!selected ? (
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "#666" }}>
            Select a session to view details
          </div>
        ) : loading ? (
          <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "#7ecfff" }}>
            Loading...
          </div>
        ) : (
          <>
            {/* Header with actions */}
            <div style={{
              padding: "12px 20px",
              borderBottom: "1px solid #1e3a5f",
              display: "flex",
              alignItems: "center",
              gap: 12,
            }}>
              <h3 style={{ margin: 0, color: "#fff", fontSize: 14, flex: 1 }}>
                {selected}
              </h3>
              <button
                onClick={triggerAnalyze}
                style={{
                  padding: "6px 14px",
                  background: "linear-gradient(135deg, #0ea5e9, #7ecfff)",
                  border: "none",
                  borderRadius: 4,
                  color: "#fff",
                  cursor: "pointer",
                  fontSize: 12,
                  fontWeight: "bold",
                }}
              >
                🔍 Analyze
              </button>
              {analyzeStatus && (
                <span style={{ fontSize: 11, color: "#aaa" }}>{analyzeStatus}</span>
              )}
            </div>

            {/* Analysis Result Summary (collapsed) */}
            {analyzeResult && analyzeResult.status !== undefined && (
              <div style={{
                padding: "12px 20px",
                borderBottom: "1px solid #1e3a5f",
                background: "#16213e",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                  <span style={{ fontSize: 12, fontWeight: "bold", color: "#7ecfff" }}>
                    📊 Analysis Result
                  </span>
                  <span style={{ fontSize: 11, color: "#666" }}>
                    ({analyzeResult.steps} messages)
                  </span>
                  <button
                    onClick={() => setShowAnalyzeChat(true)}
                    style={{
                      marginLeft: "auto",
                      padding: "3px 10px",
                      background: "#1e3a5f",
                      border: "1px solid #2563eb",
                      borderRadius: 4,
                      color: "#7ecfff",
                      cursor: "pointer",
                      fontSize: 11,
                    }}
                  >
                    💬 查看对话过程
                  </button>
                </div>
                {analyzeResult.summary && (
                  <pre style={{
                    margin: 0,
                    padding: 10,
                    background: "#0a1628",
                    borderRadius: 4,
                    color: "#b8d4e3",
                    fontSize: 11,
                    lineHeight: 1.4,
                    whiteSpace: "pre-wrap",
                    maxHeight: 150,
                    overflow: "auto",
                    fontFamily: "monospace",
                  }}>
                    {analyzeResult.summary}
                  </pre>
                )}
              </div>
            )}

            {/* Eval Report */}
            {evalReport && (
              <div style={{ padding: "12px 20px", borderBottom: "1px solid #1e3a5f" }}>
                {(() => {
                  const eff = getEfficiency(evalReport.report);
                  return eff !== null ? (
                    <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
                      <span style={{ fontSize: 12, color: "#aaa" }}>Efficiency:</span>
                      <div style={{
                        width: 120,
                        height: 8,
                        background: "#1e3a5f",
                        borderRadius: 4,
                        overflow: "hidden",
                      }}>
                        <div style={{
                          width: `${eff}%`,
                          height: "100%",
                          background: getEfficiencyColor(eff),
                          borderRadius: 4,
                          transition: "width 0.3s",
                        }} />
                      </div>
                      <span style={{ fontSize: 12, color: getEfficiencyColor(eff), fontWeight: "bold" }}>
                        {eff}/100
                      </span>
                    </div>
                  ) : null;
                })()}
                <pre style={{
                  margin: 0,
                  padding: 12,
                  background: "#0a1628",
                  borderRadius: 6,
                  color: "#b8d4e3",
                  fontSize: 11,
                  lineHeight: 1.5,
                  overflow: "auto",
                  maxHeight: 200,
                  whiteSpace: "pre-wrap",
                  fontFamily: "monospace",
                }}>
                  {evalReport.report}
                </pre>
              </div>
            )}

            {/* Messages / Trajectory */}
            <div style={{ flex: 1, overflow: "auto", padding: "12px 20px" }}>
              <h4 style={{ margin: "0 0 8px", color: "#7ecfff", fontSize: 13 }}>
                Trajectory ({messages.length} messages)
              </h4>
              {messages.map((msg, i) => {
                const role = msg.role || "?";
                const content = msg.content || "";
                const isToolCall = role === "assistant" && content.includes("<tool_call>");
                const isToolResponse = role === "user" && content.includes("<tool_response>");

                let bgColor = "#16213e";
                let borderColor = "#1e3a5f";
                let label = role;

                if (role === "assistant") {
                  bgColor = "#1a2744";
                  borderColor = "#2563eb";
                  label = msg.name || "assistant";
                } else if (isToolResponse) {
                  bgColor = "#0f2020";
                  borderColor = "#065f46";
                  label = "tool_result";
                } else if (role === "user") {
                  bgColor = "#1e1e30";
                  borderColor = "#7c3aed";
                  label = "user";
                }

                let displayContent = content;
                if (isToolCall) {
                  const match = content.match(/"name":\s*"([^"]+)"/);
                  displayContent = `→ ${match ? match[1] : "tool_call"}(...)`;
                } else if (isToolResponse) {
                  const toolMatch = content.match(/"tool":\s*"([^"]+)"/);
                  const contentMatch = content.match(/"content":\s*"([^"]{0,100})/);
                  displayContent = `← ${toolMatch ? toolMatch[1] : "?"}: ${contentMatch ? contentMatch[1] + "..." : "(result)"}`;
                } else if (displayContent.length > 200) {
                  displayContent = displayContent.slice(0, 200) + "...";
                }

                return (
                  <div
                    key={i}
                    style={{
                      marginBottom: 6,
                      padding: "8px 12px",
                      background: bgColor,
                      borderLeft: `3px solid ${borderColor}`,
                      borderRadius: 4,
                      fontSize: 12,
                    }}
                  >
                    <span style={{ color: borderColor, fontWeight: "bold", marginRight: 8, fontSize: 11 }}>
                      [{label}]
                    </span>
                    <span style={{ color: "#ccc", fontFamily: "monospace", whiteSpace: "pre-wrap" }}>
                      {displayContent}
                    </span>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {/* Right: Analyze Chat Panel (sliding overlay) */}
      {showAnalyzeChat && (
        <div style={{
          width: 420,
          borderLeft: "1px solid #1e3a5f",
          display: "flex",
          flexDirection: "column",
          background: "#0a1628",
          position: "relative",
        }}>
          {/* Header */}
          <div style={{
            padding: "10px 16px",
            borderBottom: "1px solid #1e3a5f",
            display: "flex",
            alignItems: "center",
            gap: 8,
            background: "#16213e",
          }}>
            <span style={{ fontSize: 14 }}>💬</span>
            <span style={{ flex: 1, fontSize: 13, color: "#fff", fontWeight: "bold" }}>
              分析过程
            </span>
            <span style={{ fontSize: 11, color: "#888" }}>
              {analyzeStatus.includes("analyzing") ? "🟢 运行中" : analyzeStatus.includes("Complete") ? "✅ 完成" : ""}
            </span>
            <button
              onClick={() => setShowAnalyzeChat(false)}
              style={{
                background: "none",
                border: "none",
                color: "#888",
                cursor: "pointer",
                fontSize: 18,
                padding: "0 4px",
              }}
            >
              ✕
            </button>
          </div>

          {/* Chat Messages */}
          <div style={{ flex: 1, overflow: "auto", padding: "12px" }}>
            {analyzeChatMessages.length === 0 && (
              <div style={{ textAlign: "center", color: "#555", fontSize: 12, marginTop: 40 }}>
                等待分析开始...
              </div>
            )}
            {analyzeChatMessages.map((msg, i) => {
              const parsed = parseMessageContent(msg);
              const isAssistant = msg.role === "assistant";
              const isSystem = msg.role === "system";

              if (isSystem) {
                return (
                  <div key={i} style={{
                    textAlign: "center",
                    margin: "12px 0",
                    fontSize: 11,
                    color: "#666",
                  }}>
                    — {msg.content} —
                  </div>
                );
              }

              if (parsed.type === "tool_call") {
                return (
                  <div key={i} style={{ marginBottom: 10 }}>
                    {parsed.text && (
                      <div style={{
                        marginBottom: 6,
                        padding: "8px 12px",
                        background: "#1a2744",
                        borderRadius: "12px 12px 12px 4px",
                        color: "#e0e0e0",
                        fontSize: 12,
                        lineHeight: 1.5,
                        whiteSpace: "pre-wrap",
                        maxHeight: 200,
                        overflow: "auto",
                      }}>
                        <span style={{ fontSize: 10, color: "#7ecfff", display: "block", marginBottom: 4 }}>
                          🤖 Agent
                        </span>
                        {parsed.text}
                      </div>
                    )}
                    <div style={{
                      padding: "5px 10px",
                      background: "#0f2744",
                      border: "1px solid #1e3a5f",
                      borderRadius: 6,
                      fontSize: 11,
                      color: "#fbbf24",
                      fontFamily: "monospace",
                    }}>
                      🔧 调用 <b>{parsed.toolName}</b>
                    </div>
                  </div>
                );
              }

              if (parsed.type === "tool_result") {
                return (
                  <div key={i} style={{
                    marginBottom: 10,
                    padding: "5px 10px",
                    background: "#0f2020",
                    border: "1px solid #065f46",
                    borderRadius: 6,
                    fontSize: 11,
                    color: "#4ade80",
                    fontFamily: "monospace",
                    maxHeight: 100,
                    overflow: "auto",
                  }}>
                    ← <b>{parsed.toolName}</b>: {parsed.text || "(empty)"}
                  </div>
                );
              }

              // Regular text message
              if (isAssistant) {
                return (
                  <div key={i} style={{
                    marginBottom: 10,
                    padding: "10px 14px",
                    background: "#1a2744",
                    borderRadius: "12px 12px 12px 4px",
                    color: "#e0e0e0",
                    fontSize: 12,
                    lineHeight: 1.5,
                    whiteSpace: "pre-wrap",
                    maxHeight: 300,
                    overflow: "auto",
                  }}>
                    <span style={{ fontSize: 10, color: "#7ecfff", display: "block", marginBottom: 4 }}>
                      🤖 Agent {msg.name ? `(${msg.name})` : ""}
                    </span>
                    {parsed.text}
                  </div>
                );
              }

              // User message (initial prompt)
              return (
                <div key={i} style={{
                  marginBottom: 10,
                  padding: "10px 14px",
                  background: "#1e1e30",
                  borderRadius: "12px 12px 4px 12px",
                  color: "#d0d0ff",
                  fontSize: 12,
                  lineHeight: 1.5,
                  whiteSpace: "pre-wrap",
                  maxHeight: 150,
                  overflow: "auto",
                  marginLeft: "auto",
                  maxWidth: "85%",
                }}>
                  <span style={{ fontSize: 10, color: "#a78bfa", display: "block", marginBottom: 4 }}>
                    📋 Task
                  </span>
                  {parsed.text.slice(0, 200)}{parsed.text.length > 200 ? "..." : ""}
                </div>
              );
            })}
            <div ref={chatEndRef} />
          </div>

          {/* Footer info */}
          <div style={{
            padding: "8px 16px",
            borderTop: "1px solid #1e3a5f",
            background: "#16213e",
            fontSize: 11,
            color: "#666",
            textAlign: "center",
          }}>
            只读模式 · Agent 自动运行分析
          </div>
        </div>
      )}
    </div>
  );
}
