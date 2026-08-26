import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getTrajectoryEvents,
  getTrajectorySummary,
  type TrainingAnnotation,
  type TrajectoryEvent,
  type TrajectorySummary,
} from "../api/client";
import { annotationKey, TrainingFeedback, useSessionAnnotations } from "./TrainingDataControls";

type Props = { session: string };

const palette = ["#4fc1ff", "#c586c0", "#dcdcaa", "#4ec9b0", "#ce9178", "#b5cea8"];
const button: React.CSSProperties = { background: "#252526", border: "1px solid #3c3c3c", borderRadius: 4, color: "#d4d4d4", padding: "5px 9px", cursor: "pointer", fontSize: 11 };

function agentColor(agent?: string | null) {
  const value = agent || "runtime";
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) hash = ((hash << 5) - hash + value.charCodeAt(i)) | 0;
  return palette[Math.abs(hash) % palette.length];
}

function eventGroup(type: string) {
  if (type.startsWith("model.")) return "model";
  if (type.startsWith("tool.")) return "tool";
  if (type.startsWith("conversation.") || type.startsWith("context.")) return "context";
  if (type.startsWith("evolution.")) return "evolution";
  return "runtime";
}

function preview(event: TrajectoryEvent) {
  const data = event.data || {};
  if (event.type === "model.request") return `${Array.isArray(data.messages) ? data.messages.length : 0} messages → ${String(data.model || "model")}`;
  if (event.type === "model.response") return String(data.content || data.text || "(tool call / empty response)").slice(0, 120);
  if (event.type === "tool.request") return String(data.name || data.tool || "tool");
  if (event.type === "tool.result") return String(data.observation || data.result || "result").slice(0, 120);
  if (event.type === "conversation.surface.replace") return `context generation ${String(data.generation || "?")} · ${String(data.before_count || "?")} → ${String(data.after_count || "?")}`;
  if (event.type === "runtime.event") return String(data.event || data.kind || event.node_op || "runtime event");
  return JSON.stringify(data).slice(0, 120);
}

function MessageSurface({ messages }: { messages: unknown }) {
  if (!Array.isArray(messages)) return <pre style={jsonStyle}>{JSON.stringify(messages, null, 2)}</pre>;
  return <div style={{ display: "grid", gap: 6 }}>
    {messages.map((raw, index) => {
      const message = (raw && typeof raw === "object" ? raw : { content: raw }) as Record<string, unknown>;
      const role = String(message.role || "?");
      return <div key={index} style={{ borderLeft: `3px solid ${role === "system" ? "#c586c0" : role === "assistant" ? "#4fc1ff" : role === "tool" ? "#dcdcaa" : "#4ec9b0"}`, background: "#1f1f1f", borderRadius: 3, padding: "7px 9px" }}>
        <div style={{ fontSize: 10, color: "#858585", marginBottom: 4 }}>{index + 1} · {role}{message.name ? ` · ${String(message.name)}` : ""}</div>
        <pre style={{ ...jsonStyle, margin: 0 }}>{typeof message.content === "string" ? message.content : JSON.stringify(message.content, null, 2)}</pre>
        {message.tool_calls ? <pre style={{ ...jsonStyle, color: "#dcdcaa", marginTop: 6 }}>{JSON.stringify(message.tool_calls, null, 2)}</pre> : null}
      </div>;
    })}
  </div>;
}

const jsonStyle: React.CSSProperties = { color: "#d4d4d4", fontFamily: "var(--monaco-monospace-font, Consolas, monospace)", fontSize: 11, lineHeight: 1.5, whiteSpace: "pre-wrap", overflowWrap: "anywhere", margin: 0 };

function EventDetail({ event, session, annotation, onSaved }: { event?: TrajectoryEvent; session: string; annotation?: TrainingAnnotation; onSaved: (annotation: TrainingAnnotation) => void }) {
  if (!event) return <div style={{ color: "#858585", padding: 24 }}>选择一个事件查看真实输入/输出。</div>;
  const data = event.data || {};
  const isRequest = event.type === "model.request";
  const isContext = event.type === "conversation.surface.replace";
  return <div style={{ height: "100%", overflow: "auto", padding: 12 }}>
    <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 10 }}>
      <span style={{ color: agentColor(event.agent), fontWeight: 600 }}>{event.agent || "runtime"}</span>
      <code style={{ color: "#9cdcfe", fontSize: 11 }}>{event.type}</code>
      <span style={{ color: "#666", fontSize: 10 }}>#{event.sequence}</span>
      {event.model_call_id && <TrainingFeedback session={session} targetType="model_call" targetId={event.model_call_id} annotation={annotation} onSaved={onSaved} compact />}
      <button style={{ ...button, marginLeft: "auto" }} onClick={() => void navigator.clipboard?.writeText(JSON.stringify(event, null, 2))}>复制事件 JSON</button>
    </div>
    <div style={{ color: "#858585", fontSize: 10, marginBottom: 12, lineHeight: 1.7 }}>
      run {event.run_id || "–"} · parent {event.parent_run_id || "–"}<br />
      harness {event.harness || "–"} · node {event.node_id || "–"} ({event.node_op || "–"})
    </div>
    {isRequest ? <>
      <div style={{ color: "#d4d4d4", fontSize: 12, fontWeight: 600, marginBottom: 7 }}>模型在这一刻实际看到的上下文</div>
      <div style={{ color: "#858585", fontSize: 10, marginBottom: 9 }}>这是适配器调用前、已完成 system prompt、上下文压缩和协议转换后的不可变快照。SHA-256: {String(data.messages_sha256 || "–")}</div>
      <MessageSurface messages={data.messages} />
      <details style={{ marginTop: 10 }}><summary style={{ color: "#9cdcfe", cursor: "pointer", fontSize: 11 }}>Tools 与参数</summary><pre style={{ ...jsonStyle, marginTop: 8 }}>{JSON.stringify({ tools: data.tools, parameters: data.parameters, provider: data.provider, model: data.model }, null, 2)}</pre></details>
    </> : isContext ? <>
      <div style={{ color: "#d4d4d4", fontSize: 12, fontWeight: 600, marginBottom: 7 }}>上下文表面被替换</div>
      <div style={{ color: "#858585", fontSize: 10, marginBottom: 9 }}>后续模型调用会看到下面的 working history，而不是压缩前的聊天历史。</div>
      <MessageSurface messages={data.after_messages || data.after || data.messages} />
      <details style={{ marginTop: 10 }}><summary style={{ color: "#9cdcfe", cursor: "pointer", fontSize: 11 }}>压缩账本与统计</summary><pre style={{ ...jsonStyle, marginTop: 8 }}>{JSON.stringify(data, null, 2)}</pre></details>
    </> : <pre style={jsonStyle}>{JSON.stringify(data, null, 2)}</pre>}
  </div>;
}

export default function TrajectoryReplay({ session }: Props) {
  const [summary, setSummary] = useState<TrajectorySummary | null>(null);
  const [events, setEvents] = useState<TrajectoryEvent[]>([]);
  const [nextAfter, setNextAfter] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [cursor, setCursor] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [agent, setAgent] = useState("all");
  const [group, setGroup] = useState("all");
  const listRef = useRef<HTMLDivElement>(null);
  const annotationState = useSessionAnnotations(session);

  const load = useCallback(async () => {
    setLoading(true); setError(""); setPlaying(false); setCursor(0);
    try {
      const nextSummary = await getTrajectorySummary(session);
      const result = await getTrajectoryEvents(session, { after: 0, limit: 2000 });
      setSummary(nextSummary); setEvents(result.events); setNextAfter(result.next_after); setHasMore(result.has_more);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setLoading(false); }
  }, [session]);

  const loadMore = async () => {
    if (!hasMore) return;
    try {
      const result = await getTrajectoryEvents(session, { after: nextAfter, limit: 2000 });
      setEvents((currentEvents) => [...currentEvents, ...result.events]);
      setNextAfter(result.next_after); setHasMore(result.has_more);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  };

  useEffect(() => { void load(); }, [load]);

  const filtered = useMemo(() => events.filter((event) => (agent === "all" || event.agent === agent) && (group === "all" || eventGroup(event.type) === group)), [events, agent, group]);
  useEffect(() => { setCursor(0); setPlaying(false); }, [agent, group]);
  useEffect(() => {
    if (!playing || filtered.length < 2) return;
    const timer = window.setInterval(() => setCursor((value) => {
      if (value >= filtered.length - 1) { window.clearInterval(timer); setPlaying(false); return value; }
      return value + 1;
    }), Math.max(120, 900 / speed));
    return () => window.clearInterval(timer);
  }, [playing, speed, filtered.length]);
  useEffect(() => {
    const active = listRef.current?.querySelector(`[data-sequence="${filtered[cursor]?.sequence}"]`);
    active?.scrollIntoView({ block: "nearest" });
  }, [cursor, filtered]);

  const visible = useMemo(() => {
    if (filtered.length <= 300) return filtered;
    const start = Math.max(0, cursor - 140);
    return filtered.slice(start, Math.min(filtered.length, start + 300));
  }, [filtered, cursor]);
  const current = filtered[Math.min(cursor, Math.max(0, filtered.length - 1))];
  const currentAnnotation = current?.model_call_id
    ? annotationState.byTarget.get(annotationKey("model_call", current.model_call_id))
    : undefined;

  if (loading) return <div style={{ padding: 24, color: "#9cdcfe" }}>正在验证并载入原生轨迹…</div>;
  if (error) return <div style={{ padding: 24, color: "#f48771" }}>{error}</div>;
  return <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "#1e1e1e", color: "#d4d4d4" }}>
    <div style={{ padding: "8px 12px", borderBottom: "1px solid #303030", display: "flex", flexWrap: "wrap", alignItems: "center", gap: 7 }}>
      <button style={button} onClick={() => setCursor((value) => Math.max(0, value - 1))}>◀ 单步</button>
      <button style={{ ...button, background: playing ? "#0e639c" : "#252526" }} onClick={() => setPlaying((value) => !value)}>{playing ? "暂停" : "播放"}</button>
      <button style={button} onClick={() => setCursor((value) => Math.min(filtered.length - 1, value + 1))}>单步 ▶</button>
      <select style={button} value={speed} onChange={(event) => setSpeed(Number(event.target.value))}><option value={0.5}>0.5×</option><option value={1}>1×</option><option value={2}>2×</option><option value={5}>5×</option></select>
      <select style={button} value={agent} onChange={(event) => setAgent(event.target.value)}><option value="all">全部 Agent</option>{summary?.agents.map((name) => <option key={name}>{name}</option>)}</select>
      <select style={button} value={group} onChange={(event) => setGroup(event.target.value)}><option value="all">全部事件</option><option value="model">模型 I/O</option><option value="tool">工具</option><option value="context">上下文</option><option value="evolution">自进化</option><option value="runtime">运行时</option></select>
      {hasMore && <button style={button} onClick={() => void loadMore()}>再载入 2000 条（{events.length}/{summary?.events}）</button>}
      <span style={{ marginLeft: "auto", color: summary?.validation.valid ? "#89d185" : "#f48771", fontSize: 10 }}>{summary?.validation.valid ? "✓ 完整性通过" : `✕ ${summary?.validation.errors.length} 个轨迹错误`} · {cursor + 1}/{filtered.length}</span>
    </div>
    <div style={{ height: 3, background: "#252526" }}><div style={{ height: "100%", background: "#0e639c", width: `${filtered.length ? ((cursor + 1) / filtered.length) * 100 : 0}%` }} /></div>
    <div style={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "minmax(260px, 37%) minmax(360px, 1fr)", gap: 1, background: "#303030" }}>
      <div ref={listRef} style={{ overflow: "auto", background: "#181818", padding: 7 }}>
        {visible.map((event) => {
          const index = filtered.indexOf(event);
          const selected = current?.event_id === event.event_id;
          return <button key={event.event_id} data-sequence={event.sequence} onClick={() => setCursor(index)} style={{ width: "100%", display: "grid", gridTemplateColumns: "46px 1fr", textAlign: "left", border: 0, borderLeft: `3px solid ${agentColor(event.agent)}`, background: selected ? "#37373d" : "transparent", color: "#d4d4d4", padding: "7px 8px", marginBottom: 2, cursor: "pointer" }}>
            <span style={{ color: "#666", fontSize: 9 }}>#{event.sequence}</span><span><span style={{ color: agentColor(event.agent), fontSize: 10 }}>{event.agent || "runtime"}</span><span style={{ color: "#9cdcfe", fontSize: 10, marginLeft: 7 }}>{event.type}</span><div style={{ color: "#858585", fontSize: 10, marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{preview(event)}</div></span>
          </button>;
        })}
      </div>
      <div style={{ background: "#1e1e1e", minWidth: 0 }}><EventDetail event={current} session={session} annotation={currentAnnotation} onSaved={annotationState.onSaved} /></div>
    </div>
  </div>;
}
