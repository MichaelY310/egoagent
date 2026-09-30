import { useState, useEffect, useCallback, useRef } from "react";
import { API_BASE as BASE } from '../api/runtime';
import TrajectoryReplay from "./TrajectoryReplay";
import SessionBranchDialog from "./SessionBranchDialog";
import SessionCreateDialog from "./SessionCreateDialog";
import ProjectDialog from './ProjectDialog';
import { annotationKey, TrainingDataPanel, TrainingFeedback, useSessionAnnotations } from "./TrainingDataControls";
import {
  getTrainingAnnotations,
  listProjects,
  listProjectSessions,
  trashPortfolioSession,
  updatePortfolioSession,
  updateProject,
  type ProjectPortfolioItem,
  type TrainingAnnotation,
} from "../api/client";
import { WORKSPACE } from "../api/runtime";
import { openWorkspaceInIde } from "../ideBridge";

interface SessionInfo {
  name: string;
  title?: string;
  path: string;
  message_count: number;
  has_trajectory?: boolean;
  trajectory_events?: number;
  trajectory_agents?: string[];
  trajectory_valid?: boolean;
  health?: {
    status: 'healthy' | 'degraded' | 'incomplete' | 'invalid' | 'empty' | string;
    replayable?: boolean;
    training_ready?: boolean;
    blockers?: string[];
    warnings?: string[];
  } | null;
  lineage?: {
    operation?: 'fork' | 'merge';
    merge_mode?: 'direct' | 'summary' | 'dialogue';
    parents?: string[];
    created_at?: number;
  } | null;
  workspace?: string;
  project_id?: string;
  project_title?: string;
  timestamp?: number;
  summary?: string;
  harness?: string;
  identity?: string;
  agent_config?: {
    harness?: string;
    mode?: string;
    debug_mode?: string;
    agents?: Record<string, string>;
  };
  pinned?: boolean;
  archived?: boolean;
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

export default function SessionExplorer() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [projects, setProjects] = useState<ProjectPortfolioItem[]>([]);
  const [selectedProject, setSelectedProject] = useState<string>('');
  const [selected, setSelected] = useState<string>("");
  const [openSessions, setOpenSessions] = useState<string[]>(() => {
    try {
      const value = JSON.parse(localStorage.getItem(`egoagent.session-tabs:${WORKSPACE || 'global'}`) || '[]');
      return Array.isArray(value) ? value.filter((item) => typeof item === 'string').slice(0, 12) : [];
    } catch { return []; }
  });
  const [evalReport, setEvalReport] = useState<EvalReport | null>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [filter, setFilter] = useState("");
  const [sessionAnnotations, setSessionAnnotations] = useState<TrainingAnnotation[]>([]);
  const [detailMode, setDetailMode] = useState<"replay" | "messages" | "training">("replay");
  const [analyzeStatus, setAnalyzeStatus] = useState<string>("");
  const [analyzeResult, setAnalyzeResult] = useState<any>(null);
  const [branchAction, setBranchAction] = useState<'fork' | 'merge' | null>(null);
  const [branchSources, setBranchSources] = useState<string[]>([]);
  const [showProjectDialog, setShowProjectDialog] = useState(false);
  const [showSessionDialog, setShowSessionDialog] = useState(false);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [checkedSessions, setCheckedSessions] = useState<Set<string>>(() => new Set());
  const [renaming, setRenaming] = useState<string>('');
  const [renameValue, setRenameValue] = useState('');
  const [contextMenu, setContextMenu] = useState<{ name: string; x: number; y: number } | null>(null);
  const [pendingTrash, setPendingTrash] = useState<SessionInfo | null>(null);
  const [notice, setNotice] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const [visibleSessionLimit, setVisibleSessionLimit] = useState(60);
  // 气泡聊天面板状态
  const [showAnalyzeChat, setShowAnalyzeChat] = useState(false);
  const [analyzeChatMessages, setAnalyzeChatMessages] = useState<AnalyzeMessage[]>([]);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const annotationState = useSessionAnnotations(selected);

  const fetchSessions = useCallback(async () => {
    setCatalogLoading(true);
    try {
      const [projectData, sessionData] = await Promise.all([
        listProjects(includeArchived),
        listProjectSessions({ limit: 1000, include_archived: includeArchived }),
      ]);
      const projectById = new Map(projectData.map((project) => [project.id, project]));
      setProjects(projectData);
      setSessions(sessionData.map((session) => ({
        ...session,
        project_title: projectById.get(session.project_id)?.title || 'Unassigned',
      })) as SessionInfo[]);
      setSelectedProject((current) => current || projectData.find((project) => project.current)?.id || 'all');
      try {
        const marked = await getTrainingAnnotations({ target_type: "session" });
        setSessionAnnotations(marked.annotations);
      } catch (reason) {
        console.warn("Failed to fetch session annotations:", reason);
      }
    } catch (e) {
      console.error("Failed to fetch sessions:", e);
      setNotice({ kind: 'error', text: e instanceof Error ? e.message : String(e) });
    } finally {
      setCatalogLoading(false);
    }
  }, [includeArchived]);

  useEffect(() => { fetchSessions(); }, [fetchSessions]);
  useEffect(() => {
    const close = () => setContextMenu(null);
    window.addEventListener('click', close);
    window.addEventListener('blur', close);
    return () => { window.removeEventListener('click', close); window.removeEventListener('blur', close); };
  }, []);
  useEffect(() => {
    localStorage.setItem(`egoagent.session-tabs:${WORKSPACE || 'global'}`, JSON.stringify(openSessions.slice(0, 12)));
  }, [openSessions]);

  const onAnnotationSaved = useCallback((annotation: TrainingAnnotation) => {
    annotationState.onSaved(annotation);
    if (annotation.target_type === "session") {
      setSessionAnnotations((current) => [...current.filter((item) => item.id !== annotation.id), annotation]);
    }
  }, [annotationState.onSaved]);

  const sessionAnnotationByName = new Map(sessionAnnotations.map((item) => [item.target_id, item]));

  const handleProjectCreated = async (project: ProjectPortfolioItem, openNow: boolean) => {
    setShowProjectDialog(false);
    setSelectedProject(project.id);
    setProjects((current) => [project, ...current.filter((item) => item.id !== project.id)]);
    await fetchSessions();
    if (openNow) openWorkspaceInIde(project.workspace, true);
  };

  useEffect(() => {
    if (chatEndRef.current) {
      chatEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [analyzeChatMessages]);

  const selectSession = async (name: string) => {
    setSelected(name);
    setOpenSessions((current) => [...current.filter((item) => item !== name), name].slice(-12));
    void updatePortfolioSession(name, { last_opened_at: Date.now() / 1000 }).catch(() => undefined);
    setDetailMode(sessions.find((item) => item.name === name)?.has_trajectory ? "replay" : "messages");
    setEvalReport(null);
    setMessages([]);
    setLoading(true);
    try {
      // 只加载 messages（轻量），不调 /evaluate（会触发 LLM 推理导致超时）
      const msgsRes = await fetch(`${BASE}/api/session/${encodeURIComponent(name)}/messages`);
      if (msgsRes.ok) {
        const msgsData = await msgsRes.json();
        setMessages(Array.isArray(msgsData) ? msgsData : (msgsData.messages || []));
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

  const filteredSessions = sessions.filter((s) => (
    (selectedProject === 'all' || !selectedProject || s.project_id === selectedProject)
    && (!filter || `${s.name} ${s.summary || ''} ${s.project_title || ''}`.toLowerCase().includes(filter.toLowerCase()))
  ));
  const visibleSessions = filteredSessions.slice(0, visibleSessionLimit);
  useEffect(() => setVisibleSessionLimit(60), [selectedProject, filter]);
  const selectedInfo = sessions.find((session) => session.name === selected);
  const selectedProjectInfo = projects.find((project) => project.id === selectedInfo?.project_id);
  const contextInfo = sessions.find((session) => session.name === contextMenu?.name);

  const closeSessionTab = (name: string) => {
    setOpenSessions((current) => current.filter((item) => item !== name));
    if (selected === name) {
      const remaining = openSessions.filter((item) => item !== name);
      const next = remaining.length ? remaining[remaining.length - 1] : '';
      setSelected(next);
      if (next) void selectSession(next);
    }
  };

  const toggleProjectPin = async (project: ProjectPortfolioItem) => {
    await updateProject(project.id, { pinned: !project.pinned });
    await fetchSessions();
  };

  const toggleSessionPin = async (session: SessionInfo) => {
    try {
      await updatePortfolioSession(session.name, { pinned: !session.pinned });
      setNotice({ kind: 'ok', text: session.pinned ? '已取消置顶' : 'Session 已置顶' });
      await fetchSessions();
    } catch (reason) {
      setNotice({ kind: 'error', text: reason instanceof Error ? reason.message : String(reason) });
    }
  };

  const handleSessionCreated = async (name: string) => {
    setBranchAction(null);
    setBranchSources([]);
    setShowSessionDialog(false);
    setCheckedSessions(new Set());
    await fetchSessions();
    await selectSession(name);
    setNotice({ kind: 'ok', text: `已创建并打开 Session：${name}` });
  };

  const beginRename = (session: SessionInfo) => {
    setRenaming(session.name);
    setRenameValue(session.title || session.name);
    setContextMenu(null);
  };

  const saveRename = async (session: SessionInfo) => {
    const title = renameValue.trim();
    setRenaming('');
    if (!title || title === (session.title || session.name)) return;
    try {
      await updatePortfolioSession(session.name, { title });
      setNotice({ kind: 'ok', text: `已重命名为“${title}”；稳定 ID 保持不变` });
      await fetchSessions();
    } catch (reason) {
      setNotice({ kind: 'error', text: reason instanceof Error ? reason.message : String(reason) });
    }
  };

  const setSessionArchived = async (names: string[], archived: boolean) => {
    try {
      await Promise.all(names.map((name) => updatePortfolioSession(name, { archived })));
      setCheckedSessions(new Set());
      setNotice({ kind: 'ok', text: `${names.length} 个 Session 已${archived ? '归档' : '恢复'}` });
      await fetchSessions();
    } catch (reason) {
      setNotice({ kind: 'error', text: reason instanceof Error ? reason.message : String(reason) });
    }
  };

  const pinSessions = async (names: string[]) => {
    try {
      await Promise.all(names.map((name) => updatePortfolioSession(name, { pinned: true })));
      setCheckedSessions(new Set());
      setNotice({ kind: 'ok', text: `${names.length} 个 Session 已置顶` });
      await fetchSessions();
    } catch (reason) {
      setNotice({ kind: 'error', text: reason instanceof Error ? reason.message : String(reason) });
    }
  };

  const trashSession = async (session: SessionInfo) => {
    setContextMenu(null);
    try {
      await trashPortfolioSession(session.name);
      setPendingTrash(null);
      closeSessionTab(session.name);
      setCheckedSessions((current) => { const next = new Set(current); next.delete(session.name); return next; });
      setNotice({ kind: 'ok', text: 'Session 已移到本地回收站' });
      await fetchSessions();
    } catch (reason) {
      setNotice({ kind: 'error', text: reason instanceof Error ? reason.message : String(reason) });
    }
  };

  const toggleChecked = (name: string) => {
    setCheckedSessions((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  };

  const openMerge = (names: string[]) => {
    const unique = Array.from(new Set(names));
    if (!unique.length) return;
    setSelected(unique[0]);
    setBranchSources(unique);
    setBranchAction('merge');
    setContextMenu(null);
  };

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
    <div className="session-explorer" style={{ display: "flex", height: "100%", background: "var(--portfolio-bg)", color: 'var(--portfolio-text)', position: "relative" }}>
      {/* Left: Session List */}
      <div className="session-explorer-list" style={{
        width: 320,
        borderRight: "1px solid var(--portfolio-border)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--portfolio-border)" }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <h3 style={{ margin: 0, color: "var(--portfolio-accent)", fontSize: 14, flex: 1 }}>Project &amp; Session Portfolio</h3>
            <button type="button" className="portfolio-add-project" onClick={() => setShowSessionDialog(true)}>＋ Session</button>
            <button type="button" className="portfolio-add-project" onClick={() => setShowProjectDialog(true)}>＋ Project</button>
          </div>
          <div style={{ marginTop: 3, color: 'var(--portfolio-muted)', fontSize: 10 }}>Project = workspace 文件夹 · 双击重命名 · 右键管理/Fork · 勾选 2–8 个后批量 Merge</div>
          <input
            type="text"
            placeholder="Filter sessions..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{
              width: "100%",
              boxSizing: "border-box",
              marginTop: 8,
              padding: "6px 10px",
              background: "var(--input-background)",
              border: "1px solid var(--portfolio-border)",
              borderRadius: 4,
              color: "var(--portfolio-text)",
              fontSize: 12,
            }}
          />
          <label style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 7, color: 'var(--portfolio-muted)', fontSize: 10, cursor: 'pointer' }}>
            <input type="checkbox" checked={includeArchived} onChange={(event) => setIncludeArchived(event.target.checked)} /> 显示已归档 Session
          </label>
        </div>
        <div style={{ maxHeight: 190, overflow: 'auto', padding: '7px 8px', borderBottom: '1px solid var(--portfolio-border)', background: 'var(--portfolio-deep)' }}>
          <button
            type="button"
            onClick={() => setSelectedProject('all')}
            style={{ width: '100%', display: 'flex', justifyContent: 'space-between', padding: '6px 8px', color: selectedProject === 'all' ? 'var(--text-primary)' : 'var(--text-secondary)', background: selectedProject === 'all' ? 'var(--portfolio-panel)' : 'transparent', border: 0, borderRadius: 4, cursor: 'pointer', fontSize: 11 }}
          ><span>全部项目</span><small>{sessions.length}</small></button>
          {projects.map((project) => <div key={project.id} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
            <button
              type="button"
              onClick={() => setSelectedProject(project.id)}
              title={`${project.workspace || '无法归属'}\n${project.running_count || 0} running · ${project.session_count} Sessions`}
              style={{ flex: 1, minWidth: 0, display: 'grid', gridTemplateColumns: 'minmax(0,1fr) auto', gap: 7, padding: '6px 8px', color: selectedProject === project.id ? 'var(--text-primary)' : 'var(--text-secondary)', background: selectedProject === project.id ? 'var(--portfolio-panel)' : 'transparent', border: 0, borderRadius: 4, cursor: 'pointer', textAlign: 'left', fontSize: 11 }}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{project.current ? '● ' : ''}{project.title}</span>
              <small style={{ color: project.running_count ? '#4ade80' : '#718096' }}>{project.running_count ? `${project.running_count} live` : project.session_count}</small>
            </button>
            {project.id !== 'unknown' && <button type="button" title={project.pinned ? '取消项目置顶' : '置顶项目'} onClick={() => void toggleProjectPin(project)} style={{ padding: '4px', border: 0, color: project.pinned ? '#e2c08d' : '#53657a', background: 'transparent', cursor: 'pointer' }}>{project.pinned ? '★' : '☆'}</button>}
            {project.available && !project.current && <button type="button" title="在新的 IDE 窗口打开 Project" onClick={() => openWorkspaceInIde(project.workspace, true)} style={{ padding: '4px', border: 0, color: '#7ecfff', background: 'transparent', cursor: 'pointer' }}>↗</button>}
          </div>)}
        </div>
        {notice && <div role="status" onClick={() => setNotice(null)} title="点击关闭" style={{ padding: '7px 10px', color: notice.kind === 'error' ? '#f48771' : '#89d185', background: 'var(--portfolio-panel)', borderBottom: '1px solid var(--portfolio-border)', fontSize: 10, cursor: 'pointer' }}>{notice.kind === 'error' ? '⚠ ' : '✓ '}{notice.text}</div>}
        {checkedSessions.size > 0 && <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '7px 8px', background: 'var(--portfolio-panel)', borderBottom: '1px solid var(--portfolio-border)', fontSize: 10 }}>
          <strong style={{ flex: 1, color: 'var(--portfolio-accent)' }}>{checkedSessions.size} 已选择</strong>
          <button type="button" disabled={checkedSessions.size < 2} onClick={() => openMerge(Array.from(checkedSessions))} className="portfolio-batch-action">⇄ Merge</button>
          <button type="button" onClick={() => void pinSessions(Array.from(checkedSessions))} className="portfolio-batch-action">Pin</button>
          <button type="button" onClick={() => void setSessionArchived(Array.from(checkedSessions), true)} className="portfolio-batch-action">Archive</button>
          <button type="button" onClick={() => setCheckedSessions(new Set())} className="portfolio-batch-action">Clear</button>
        </div>}
        <div style={{ flex: 1, overflow: "auto", padding: "8px 0" }}>
          {visibleSessions.map((s) => {
            const mark = sessionAnnotationByName.get(s.name);
            const agentConfig = s.agent_config || {};
            const configuredIdentities = Object.values(agentConfig.agents || {}).map((value) => String(value).replace(/\\/g, '/').split('/').filter(Boolean).pop()).filter(Boolean);
            return (
            <div
              key={s.name}
              onClick={() => selectSession(s.name)}
              onDoubleClick={(event) => { event.preventDefault(); event.stopPropagation(); beginRename(s); }}
              onContextMenu={(event) => {
                event.preventDefault();
                void selectSession(s.name);
                setContextMenu({ name: s.name, x: event.clientX, y: event.clientY });
              }}
              style={{
                padding: "8px 16px",
                cursor: "pointer",
                background: selected === s.name ? "var(--portfolio-panel)" : "transparent",
                borderLeft: selected === s.name ? "3px solid var(--portfolio-accent)" : "3px solid transparent",
                transition: "all 0.15s",
              }}
              onMouseEnter={(e) => { if (selected !== s.name) e.currentTarget.style.background = "var(--portfolio-hover)"; }}
              onMouseLeave={(e) => { if (selected !== s.name) e.currentTarget.style.background = "transparent"; }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, color: "var(--portfolio-text)", fontFamily: "monospace" }}>
                <input type="checkbox" checked={checkedSessions.has(s.name)} aria-label={`Select ${s.name}`} onClick={(event) => event.stopPropagation()} onChange={() => toggleChecked(s.name)} />
                {renaming === s.name
                  ? <input autoFocus value={renameValue} aria-label={`Rename ${s.name}`} onClick={(event) => event.stopPropagation()} onChange={(event) => setRenameValue(event.target.value)} onBlur={() => void saveRename(s)} onKeyDown={(event) => {
                    if (event.key === 'Enter') void saveRename(s);
                    if (event.key === 'Escape') setRenaming('');
                  }} style={{ minWidth: 0, flex: 1, padding: '2px 4px', color: 'var(--portfolio-text)', background: 'var(--input-background)', border: '1px solid var(--portfolio-accent)', borderRadius: 3, font: 'inherit' }} />
                  : <span title={`显示名：${s.title || s.name}\n稳定 ID：${s.name}\n双击重命名，右键打开操作菜单`} style={{ minWidth: 0, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: 'nowrap' }}>{s.title || s.name}</span>}
                <button type="button" title={s.pinned ? '取消 Session 置顶' : '置顶 Session'} onClick={(event) => { event.stopPropagation(); void toggleSessionPin(s); }} style={{ marginLeft: 'auto', padding: 0, border: 0, color: s.pinned ? '#e2c08d' : '#53657a', background: 'transparent', cursor: 'pointer', flexShrink: 0 }}>{s.pinned ? '★' : '☆'}</button>
                <button type="button" className="portfolio-session-action" title="Session 操作菜单" aria-label={`More actions for ${s.name}`} onClick={(event) => { event.stopPropagation(); setContextMenu({ name: s.name, x: event.clientX, y: event.clientY }); }}>⋯</button>
                {mark?.rating === "up" && <span title="已点赞" style={{ color: "#89d185", flexShrink: 0 }}>👍</span>}
                {mark?.rating === "down" && <span title="已点踩" style={{ color: "#f48771", flexShrink: 0 }}>👎</span>}
                {mark?.important && <span title="重要 Session" style={{ color: "#e2c08d", flexShrink: 0 }}>★</span>}
                {mark?.include_in_training && <span title="已加入训练集" style={{ color: "#4fc1ff", flexShrink: 0 }}>◆</span>}
              </div>
              <div style={{ fontSize: 11, color: "#888", marginTop: 2 }}>
                {s.message_count} messages{s.archived ? <span style={{ marginLeft: 6, color: '#c586c0' }}>Archived</span> : null}
                {s.has_trajectory && <span
                  title={s.health ? `${s.health.status}${s.health.training_ready ? ' · training ready' : ''}${s.health.blockers?.length ? ` · ${s.health.blockers.join('; ')}` : ''}` : 'Health is calculated when the session is saved or opened'}
                  style={{ marginLeft: 7, color: s.health?.status === 'invalid' ? "#f48771" : s.health?.status === 'incomplete' ? '#e2c08d' : s.health?.status === 'healthy' ? "#89d185" : "#858585" }}
                >● {s.trajectory_events || "…"} events{s.health ? ` · ${s.health.status}` : ''}</span>}
              </div>
              {selectedProject === 'all' && <div style={{ marginTop: 3, color: '#569cd6', fontSize: 10 }}>{s.project_title}</div>}
              {s.summary && <div style={{ marginTop: 3, color: '#6f7f91', fontSize: 10, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.summary}</div>}
              {(agentConfig.harness || s.harness) && <div title="此配置属于该 Session；切换 Session 不会覆盖它" style={{ marginTop: 4, color: 'var(--portfolio-accent)', fontSize: 10, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                ◈ {agentConfig.mode || 'agent'} · {agentConfig.harness || s.harness}{configuredIdentities.length ? ` · ${configuredIdentities.join(', ')}` : s.identity ? ` · ${s.identity}` : ''}
              </div>}
              {s.lineage && <div title={`Parents: ${(s.lineage.parents || []).join(', ')}`} style={{ marginTop: 4, color: '#c586c0', fontSize: 10 }}>
                {s.lineage.operation === 'fork' ? '⑂ fork' : `⇄ ${s.lineage.merge_mode || 'merge'}`} · {(s.lineage.parents || []).join(' + ')}
              </div>}
            </div>
            );
          })}
          {catalogLoading && <div className="portfolio-loading" role="status">正在载入项目与 Session…</div>}
          {!catalogLoading && filteredSessions.length === 0 && (
            <div className="portfolio-empty">
              <b>没有匹配的 Session</b>
              <span>{filter ? '清除筛选条件后再试。' : '在 Chat 中发送第一条消息后，Session 会自动出现在这里。'}</span>
            </div>
          )}
          {filteredSessions.length > visibleSessions.length && <button
            type="button"
            onClick={() => setVisibleSessionLimit((current) => current + 60)}
            style={{ width: 'calc(100% - 24px)', margin: '6px 12px 10px', padding: '6px', border: '1px solid var(--portfolio-border)', borderRadius: 4, background: 'var(--portfolio-panel)', color: 'var(--portfolio-accent)', cursor: 'pointer', fontSize: 10 }}
          >再显示 {Math.min(60, filteredSessions.length - visibleSessions.length)} 个 · 还有 {filteredSessions.length - visibleSessions.length} 个</button>}
        </div>
        <div style={{ padding: "8px 16px", borderTop: "1px solid var(--portfolio-border)" }}>
          <button
            onClick={fetchSessions}
            style={{
              width: "100%",
              padding: "6px",
              background: "var(--portfolio-panel)",
              border: "none",
              borderRadius: 4,
              color: "var(--portfolio-accent)",
              cursor: "pointer",
              fontSize: 12,
            }}
          >
            🔄 Refresh
          </button>
        </div>
      </div>

      {/* Middle: Detail Panel */}
      <div className="session-explorer-detail" style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
        <div style={{ minHeight: 35, display: 'flex', alignItems: 'end', gap: 3, padding: '5px 8px 0', overflowX: 'auto', borderBottom: '1px solid var(--portfolio-border)', background: 'var(--portfolio-deep)' }}>
          {openSessions.map((name) => {
            const info = sessions.find((item) => item.name === name);
            if (!info) return null;
            return <div key={name} title={`${info.project_title || ''}\n${name}`} style={{ display: 'flex', alignItems: 'center', minWidth: 110, maxWidth: 230, height: 29, padding: '0 5px 0 9px', border: '1px solid var(--portfolio-border)', borderBottom: selected === name ? '1px solid var(--portfolio-bg)' : undefined, borderRadius: '5px 5px 0 0', background: selected === name ? 'var(--portfolio-bg)' : 'var(--portfolio-tab)', color: selected === name ? 'var(--text-primary)' : 'var(--portfolio-muted)', fontSize: 10 }}>
              <button type="button" onClick={() => void selectSession(name)} style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', padding: 0, border: 0, color: 'inherit', background: 'transparent', textAlign: 'left', cursor: 'pointer' }}>{info.title || name}</button>
              <button type="button" onClick={() => closeSessionTab(name)} title="关闭标签（不会删除 Session）" style={{ padding: '1px 3px', border: 0, color: '#718096', background: 'transparent', cursor: 'pointer' }}>×</button>
            </div>;
          })}
          {!openSessions.length && <span style={{ alignSelf: 'center', padding: '0 8px 6px', color: '#53657a', fontSize: 10 }}>从左侧打开一个或多个 Session</span>}
        </div>
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
              borderBottom: "1px solid var(--portfolio-border)",
              display: "flex",
              alignItems: "center",
              flexWrap: "wrap",
              gap: 12,
            }}>
              <h3 title={selected} style={{ margin: 0, color: "var(--text-primary)", fontSize: 14, flex: "1 1 220px", minWidth: 120, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {selectedProjectInfo?.title ? `${selectedProjectInfo.title} / ` : ''}{selectedInfo?.title || selected}
              </h3>
              {selectedInfo?.agent_config?.harness && <span title="该 Session 的独立 Agent 配置" style={{ padding: '3px 7px', border: '1px solid var(--portfolio-border)', borderRadius: 10, color: 'var(--portfolio-accent)', background: 'var(--portfolio-panel)', fontSize: 9, whiteSpace: 'nowrap' }}>
                {selectedInfo.agent_config.mode || 'agent'} · {selectedInfo.agent_config.harness}
              </span>}
              <TrainingFeedback
                session={selected}
                targetType="session"
                targetId={selected}
                annotation={annotationState.byTarget.get(annotationKey("session", selected))}
                onSaved={onAnnotationSaved}
                compact
              />
              {!selected.includes('/') && <button type="button" onClick={() => { setBranchSources([]); setBranchAction('fork'); }} title="复制完整上下文到一个独立分支" style={{ padding: '5px 9px', border: '1px solid var(--border-strong)', borderRadius: 4, cursor: 'pointer', color: 'var(--button-text)', background: 'var(--button-bg)', fontSize: 10, flexShrink: 0 }}>⑂ Fork</button>}
              {!selected.includes('/') && sessions.some((session) => session.name !== selected && !session.name.includes('/')) && <button type="button" onClick={() => openMerge(checkedSessions.size >= 2 ? Array.from(checkedSessions) : [selected])} title="选择两个或多个 Session 合并" style={{ padding: '5px 9px', border: '1px solid var(--border-strong)', borderRadius: 4, cursor: 'pointer', color: 'var(--button-text)', background: 'var(--button-bg)', fontSize: 10, flexShrink: 0 }}>⇄ Merge</button>}
              <div style={{ display: "flex", flexShrink: 0, background: "var(--surface-raised)", border: "1px solid var(--border)", borderRadius: 4, overflow: "hidden" }}>
                {selectedInfo?.has_trajectory && <button type="button" onClick={() => setDetailMode("replay")} style={{ padding: "5px 9px", border: 0, cursor: "pointer", color: detailMode === "replay" ? "white" : "var(--text-dim)", background: detailMode === "replay" ? "var(--focus)" : "transparent", fontSize: 10, whiteSpace: "nowrap", flexShrink: 0 }}>精确回放</button>}
                <button type="button" onClick={() => setDetailMode("messages")} style={{ padding: "5px 9px", border: 0, cursor: "pointer", color: detailMode === "messages" ? "white" : "var(--text-dim)", background: detailMode === "messages" ? "var(--focus)" : "transparent", fontSize: 10, whiteSpace: "nowrap", flexShrink: 0 }}>审计聊天</button>
                <button type="button" onClick={() => setDetailMode("training")} style={{ padding: "5px 9px", border: 0, cursor: "pointer", color: detailMode === "training" ? "white" : "var(--text-dim)", background: detailMode === "training" ? "var(--focus)" : "transparent", fontSize: 10, whiteSpace: "nowrap", flexShrink: 0 }}>训练数据</button>
              </div>
              <button
                type="button"
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
                  flexShrink: 0,
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
                borderBottom: "1px solid var(--portfolio-border)",
                background: "var(--portfolio-panel)",
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
                      background: "var(--portfolio-panel)",
                      border: "1px solid var(--focus)",
                      borderRadius: 4,
                      color: "var(--portfolio-accent)",
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
                    background: "var(--portfolio-deep)",
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
              <div style={{ padding: "12px 20px", borderBottom: "1px solid var(--portfolio-border)" }}>
                {(() => {
                  const eff = getEfficiency(evalReport.report);
                  return eff !== null ? (
                    <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
                      <span style={{ fontSize: 12, color: "#aaa" }}>Efficiency:</span>
                      <div style={{
                        width: 120,
                        height: 8,
                        background: "var(--portfolio-border)",
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
                  background: "var(--portfolio-deep)",
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
            {detailMode === "training" ? (
              <div style={{ flex: 1, minHeight: 0 }}><TrainingDataPanel session={selected} availableSessions={sessions.map((item) => item.name)} annotations={annotationState.annotations} onSaved={onAnnotationSaved} /></div>
            ) : detailMode === "replay" && selectedInfo?.has_trajectory ? (
              <div style={{ flex: 1, minHeight: 0 }}><TrajectoryReplay session={selected} /></div>
            ) : <div style={{ flex: 1, overflow: "auto", padding: "12px 20px" }}>
              <h4 style={{ margin: "0 0 8px", color: "#7ecfff", fontSize: 13 }}>
                Trajectory ({messages.length} messages)
              </h4>
              {messages.map((msg, i) => {
                const role = msg.role || "?";
                const content = msg.content || "";
                const contextStatus = msg._context?.status as string | undefined;
                const contextReason = msg._context?.reason as string | undefined;
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
                      opacity: contextStatus === "elided" || contextStatus === "summarized" ? 0.64 : 1,
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 4 }}>
                      <span style={{ color: borderColor, fontWeight: "bold", fontSize: 11 }}>[{label}]</span>
                      {msg._training?.target_id && <span style={{ marginLeft: "auto" }}><TrainingFeedback
                        session={selected}
                        targetType="message"
                        targetId={msg._training.target_id}
                        sourceHash={msg._training.source_hash}
                        annotation={annotationState.byTarget.get(annotationKey("message", msg._training.target_id))}
                        onSaved={annotationState.onSaved}
                        compact
                      /></span>}
                    </div>
                    {contextStatus && contextStatus !== "active" && (
                      <span
                        title={contextReason || contextStatus}
                        style={{
                          display: "inline-block",
                          marginRight: 8,
                          border: `1px solid ${contextStatus === "compressed" ? "#d29922" : "#6e7681"}`,
                          borderRadius: 8,
                          padding: "1px 6px",
                          color: contextStatus === "compressed" ? "#e3b341" : "#a5a5a5",
                          fontSize: 8,
                        }}
                      >
                        {contextStatus === "elided" ? "已从模型上下文移除" : contextStatus === "summarized" ? "已由摘要替代" : "工具输出已压缩"}
                      </span>
                    )}
                    <span style={{ color: "#ccc", fontFamily: "monospace", whiteSpace: "pre-wrap" }}>
                      {displayContent}
                    </span>
                  </div>
                );
              })}
            </div>}
          </>
        )}
      </div>

      {/* Right: Analyze Chat Panel (sliding overlay) */}
      {showAnalyzeChat && (
        <div style={{
          width: 420,
          borderLeft: "1px solid var(--portfolio-border)",
          display: "flex",
          flexDirection: "column",
          background: "var(--portfolio-deep)",
          position: "relative",
        }}>
          {/* Header */}
          <div style={{
            padding: "10px 16px",
            borderBottom: "1px solid var(--portfolio-border)",
            display: "flex",
            alignItems: "center",
            gap: 8,
            background: "var(--portfolio-panel)",
          }}>
            <span style={{ fontSize: 14 }}>💬</span>
            <span style={{ flex: 1, fontSize: 13, color: "var(--text-primary)", fontWeight: "bold" }}>
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
                        background: "var(--portfolio-panel)",
                        borderRadius: "12px 12px 12px 4px",
                        color: "var(--portfolio-text)",
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
                      background: "var(--portfolio-hover)",
                      border: "1px solid var(--portfolio-border)",
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
                    background: "var(--portfolio-panel)",
                    borderRadius: "12px 12px 12px 4px",
                    color: "var(--portfolio-text)",
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
            borderTop: "1px solid var(--portfolio-border)",
            background: "var(--portfolio-panel)",
            fontSize: 11,
            color: "#666",
            textAlign: "center",
          }}>
            只读模式 · Agent 自动运行分析
          </div>
        </div>
      )}
      {contextMenu && contextInfo && <div
        role="menu"
        aria-label={`Actions for ${contextInfo.name}`}
        onClick={(event) => event.stopPropagation()}
        style={{ position: 'fixed', zIndex: 60, left: Math.max(8, Math.min(contextMenu.x, window.innerWidth - 225)), top: Math.max(8, Math.min(contextMenu.y, window.innerHeight - 330)), width: 215, padding: 5, color: 'var(--portfolio-text)', background: 'var(--surface-raised)', border: '1px solid var(--portfolio-border)', borderRadius: 7, boxShadow: '0 12px 34px var(--shadow-color)' }}
      >
        <div style={{ padding: '6px 8px 7px', borderBottom: '1px solid var(--portfolio-border)', marginBottom: 4 }}>
          <strong style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 11 }}>{contextInfo.title || contextInfo.name}</strong>
          <small title={contextInfo.name} style={{ display: 'block', marginTop: 2, color: 'var(--portfolio-muted)', overflow: 'hidden', textOverflow: 'ellipsis' }}>ID · {contextInfo.name}</small>
        </div>
        <button role="menuitem" className="portfolio-context-action" onClick={() => { setContextMenu(null); void selectSession(contextInfo.name); }}>Open <kbd>Enter</kbd></button>
        <button role="menuitem" className="portfolio-context-action" onClick={() => beginRename(contextInfo)}>Rename <kbd>Double-click</kbd></button>
        <button role="menuitem" className="portfolio-context-action" onClick={() => { setContextMenu(null); setSelected(contextInfo.name); setBranchSources([]); setBranchAction('fork'); }}>⑂ Fork Session</button>
        {sessions.some((session) => session.name !== contextInfo.name && !session.name.includes('/')) && <button role="menuitem" className="portfolio-context-action" onClick={() => openMerge(checkedSessions.size ? Array.from(new Set([contextInfo.name, ...checkedSessions])) : [contextInfo.name])}>⇄ Merge Sessions…</button>}
        <div className="portfolio-context-separator" />
        <button role="menuitem" className="portfolio-context-action" onClick={() => { setContextMenu(null); void toggleSessionPin(contextInfo); }}>{contextInfo.pinned ? '☆ Unpin' : '★ Pin'}</button>
        <button role="menuitem" className="portfolio-context-action" onClick={() => { setContextMenu(null); void setSessionArchived([contextInfo.name], !contextInfo.archived); }}>{contextInfo.archived ? 'Restore from Archive' : 'Archive'}</button>
        <div className="portfolio-context-separator" />
        <button role="menuitem" className="portfolio-context-action danger" onClick={() => { setContextMenu(null); setPendingTrash(contextInfo); }}>Move to Trash…</button>
      </div>}
      {pendingTrash && <div role="dialog" aria-modal="true" aria-label="Move session to trash" style={{ position: 'absolute', inset: 0, zIndex: 70, display: 'grid', placeItems: 'center', padding: 20, background: 'rgba(0,0,0,.58)' }}>
        <div style={{ width: 430, maxWidth: '100%', padding: 16, color: 'var(--portfolio-text)', background: 'var(--surface-raised)', border: '1px solid var(--portfolio-border)', borderRadius: 8, boxShadow: '0 18px 60px var(--shadow-color)' }}>
          <strong style={{ display: 'block', color: '#f48771', fontSize: 13 }}>Move Session to Trash?</strong>
          <p style={{ margin: '9px 0 4px', fontSize: 11, lineHeight: 1.5 }}>“{pendingTrash.title || pendingTrash.name}”会从 Portfolio 消失，但不会立即永久删除。</p>
          <p style={{ margin: 0, color: 'var(--portfolio-muted)', fontSize: 10 }}>可从 <code>.egoagent/session_trash</code> 恢复；稳定 ID：{pendingTrash.name}</p>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 15 }}>
            <button type="button" onClick={() => setPendingTrash(null)} className="portfolio-batch-action">Cancel</button>
            <button type="button" onClick={() => void trashSession(pendingTrash)} className="portfolio-batch-action" style={{ color: 'white', background: '#b42318', borderColor: '#b42318' }}>Move to Trash</button>
          </div>
        </div>
      </div>}
      {branchAction && selected && <SessionBranchDialog
        action={branchAction}
        source={selected}
        sourceProjectId={selectedInfo?.project_id}
        sourceWorkspace={selectedInfo?.workspace}
        initialSources={branchSources}
        sessions={sessions.map((session) => ({
          name: session.name,
          title: session.title,
          message_count: session.message_count,
          project_id: session.project_id,
          project_title: session.project_title,
          workspace: session.workspace,
        }))}
        onClose={() => setBranchAction(null)}
        onCreated={handleSessionCreated}
      />}
      {showSessionDialog && <SessionCreateDialog projects={projects} preferredProjectId={selectedProject} onClose={() => setShowSessionDialog(false)} onCreated={(name) => void handleSessionCreated(name)} />}
      {showProjectDialog && <ProjectDialog onClose={() => setShowProjectDialog(false)} onCreated={(project, openNow) => void handleProjectCreated(project, openNow)} />}
    </div>
  );
}
