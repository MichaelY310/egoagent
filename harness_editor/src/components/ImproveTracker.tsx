/**
 * ImproveTracker - 实时变更追踪面板
 * 当 improver agent 修改 harness/identity 时，实时展示变化。
 */
import { useState, useEffect, useRef } from "react";

export interface ChangeEntry {
  timestamp: number;
  type: "harness" | "identity";
  target: string; // harness 名或 identity 名
  action: string;
  field?: string;
  oldValue?: string;
  newValue?: string;
  nodes?: string[];
  pipelineStart?: string;
  diff?: any;
}

interface Props {
  changes: ChangeEntry[];
  onClose: () => void;
}

export default function ImproveTracker({ changes, onClose }: Props) {
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [changes.length]);

  // 获取目标摘要
  const targets = new Set(changes.map(c => `${c.type === "harness" ? "🔗" : "🤖"} ${c.target}`));
  const latestNodes = changes.filter(c => c.nodes).slice(-1)[0]?.nodes;

  return (
    <div style={{
      width: 360,
      borderLeft: "1px solid #1e3a5f",
      display: "flex",
      flexDirection: "column",
      background: "#0a1628",
      overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{
        padding: "10px 14px",
        borderBottom: "1px solid #1e3a5f",
        background: "#16213e",
        display: "flex",
        alignItems: "center",
        gap: 8,
      }}>
        <span style={{ fontSize: 15 }}>🔬</span>
        <span style={{ flex: 1, fontSize: 13, fontWeight: "bold", color: "#fff" }}>
          实时变更追踪
        </span>
        <span style={{
          fontSize: 10,
          padding: "2px 6px",
          background: "#065f46",
          borderRadius: 8,
          color: "#4ade80",
        }}>
          {changes.length} 次修改
        </span>
        <button onClick={onClose} style={{
          background: "none",
          border: "none",
          color: "#888",
          cursor: "pointer",
          fontSize: 16,
          padding: "0 4px",
        }}>✕</button>
      </div>

      {/* Target Summary */}
      <div style={{
        padding: "8px 14px",
        borderBottom: "1px solid #1e3a5f",
        background: "#0f1e36",
      }}>
        <div style={{ fontSize: 11, color: "#888", marginBottom: 4 }}>修改目标</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {Array.from(targets).map((t, i) => (
            <span key={i} style={{
              padding: "2px 8px",
              background: "#1e3a5f",
              borderRadius: 4,
              fontSize: 11,
              color: "#7ecfff",
            }}>{t}</span>
          ))}
        </div>
      </div>

      {/* Mini Pipeline View */}
      {latestNodes && (
        <div style={{
          padding: "10px 14px",
          borderBottom: "1px solid #1e3a5f",
          background: "#0d1b2a",
        }}>
          <div style={{ fontSize: 11, color: "#888", marginBottom: 6 }}>Pipeline 结构</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
            {latestNodes.map((node, i) => {
              // 判断是否是新增的节点（在最近一次操作中被 add）
              const latestChange = changes[changes.length - 1];
              const isNew = latestChange?.action === "add_node" && latestChange?.diff?.target === node;
              const isModified = latestChange?.action === "update_node" && latestChange?.field === node;
              return (
                <span key={i} style={{ display: "flex", alignItems: "center", gap: 2 }}>
                  <span style={{
                    padding: "3px 8px",
                    background: isNew ? "#065f46" : isModified ? "#92400e" : "#1e3a5f",
                    border: isNew ? "1px solid #4ade80" : isModified ? "1px solid #fbbf24" : "1px solid #2563eb",
                    borderRadius: 4,
                    fontSize: 10,
                    color: isNew ? "#4ade80" : isModified ? "#fbbf24" : "#7ecfff",
                    fontFamily: "monospace",
                    transition: "all 0.3s",
                  }}>
                    {node}
                  </span>
                  {i < latestNodes.length - 1 && (
                    <span style={{ color: "#444", fontSize: 10 }}>→</span>
                  )}
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* Change Timeline */}
      <div style={{ flex: 1, overflow: "auto", padding: "8px 0" }}>
        {changes.length === 0 && (
          <div style={{ textAlign: "center", color: "#555", fontSize: 12, marginTop: 40 }}>
            等待 agent 进行修改...
          </div>
        )}
        {changes.map((c, i) => {
          const time = new Date(c.timestamp).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
          const isExpanded = expandedIdx === i;
          const actionColor = c.action === "add_node" ? "#4ade80"
            : c.action === "remove_node" ? "#f87171"
            : c.action === "update_node" ? "#fbbf24"
            : "#7ecfff";
          const actionIcon = c.action === "add_node" ? "+"
            : c.action === "remove_node" ? "−"
            : c.action === "update_node" ? "✎"
            : c.action === "set_field" ? "⚙"
            : "⟳";

          return (
            <div
              key={i}
              onClick={() => setExpandedIdx(isExpanded ? null : i)}
              style={{
                padding: "8px 14px",
                cursor: "pointer",
                borderLeft: `3px solid ${actionColor}`,
                marginLeft: 10,
                marginBottom: 2,
                background: isExpanded ? "#16213e" : "transparent",
                transition: "background 0.15s",
              }}
            >
              {/* Timeline header */}
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 10, color: "#666", fontFamily: "monospace", minWidth: 60 }}>
                  {time}
                </span>
                <span style={{
                  width: 18,
                  height: 18,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  background: actionColor + "22",
                  border: `1px solid ${actionColor}`,
                  borderRadius: "50%",
                  fontSize: 10,
                  color: actionColor,
                  fontWeight: "bold",
                }}>{actionIcon}</span>
                <span style={{ fontSize: 11, color: "#ddd" }}>
                  {c.type === "harness" ? "🔗" : "🤖"} <b>{c.target}</b>
                </span>
                <span style={{ fontSize: 10, color: actionColor, marginLeft: "auto" }}>
                  {c.action}
                </span>
              </div>

              {/* Expanded detail */}
              {isExpanded && (
                <div style={{ marginTop: 8, paddingLeft: 24 }}>
                  {c.field && (
                    <div style={{ fontSize: 11, color: "#888", marginBottom: 4 }}>
                      字段: <code style={{ background: "#1e3a5f", padding: "1px 4px", borderRadius: 3, color: "#7ecfff" }}>{c.field}</code>
                    </div>
                  )}
                  {/* Prompt diff view */}
                  {c.oldValue && c.newValue && (
                    <div style={{ marginTop: 4 }}>
                      <div style={{
                        padding: "6px 8px",
                        background: "#1a0a0a",
                        borderRadius: "4px 4px 0 0",
                        border: "1px solid #7f1d1d",
                        fontSize: 11,
                        color: "#f87171",
                        fontFamily: "monospace",
                        whiteSpace: "pre-wrap",
                        maxHeight: 80,
                        overflow: "auto",
                        textDecoration: "line-through",
                        opacity: 0.7,
                      }}>
                        {c.oldValue.length > 200 ? c.oldValue.slice(0, 200) + "..." : c.oldValue}
                      </div>
                      <div style={{
                        padding: "6px 8px",
                        background: "#0a1a0a",
                        borderRadius: "0 0 4px 4px",
                        border: "1px solid #065f46",
                        borderTop: "none",
                        fontSize: 11,
                        color: "#4ade80",
                        fontFamily: "monospace",
                        whiteSpace: "pre-wrap",
                        maxHeight: 120,
                        overflow: "auto",
                      }}>
                        {c.newValue.length > 300 ? c.newValue.slice(0, 300) + "..." : c.newValue}
                      </div>
                    </div>
                  )}
                  {/* Node info */}
                  {c.diff?.node_after && (
                    <div style={{ marginTop: 4 }}>
                      <div style={{ fontSize: 10, color: "#666", marginBottom: 2 }}>节点配置:</div>
                      <pre style={{
                        margin: 0,
                        padding: "4px 8px",
                        background: "#0a1628",
                        borderRadius: 4,
                        border: "1px solid #1e3a5f",
                        color: "#b8d4e3",
                        fontSize: 10,
                        maxHeight: 100,
                        overflow: "auto",
                        whiteSpace: "pre-wrap",
                      }}>
                        {JSON.stringify(c.diff.node_after, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {/* Footer stats */}
      <div style={{
        padding: "6px 14px",
        borderTop: "1px solid #1e3a5f",
        background: "#16213e",
        display: "flex",
        alignItems: "center",
        gap: 8,
        fontSize: 10,
        color: "#666",
      }}>
        <span>📊 {changes.filter(c => c.type === "harness").length} harness修改</span>
        <span>•</span>
        <span>🤖 {changes.filter(c => c.type === "identity").length} identity修改</span>
        {latestNodes && (
          <>
            <span>•</span>
            <span>🔗 {latestNodes.length} 节点</span>
          </>
        )}
      </div>
    </div>
  );
}
