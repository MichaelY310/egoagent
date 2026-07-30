import { useState, useEffect, useCallback } from "react";
import * as api from "../api/client";

interface EnvInfo {
  path: string;
  path_b64: string;
  name: string;
  tools: string[];
  knowledge: string[];
}

interface ToolDetail {
  meta: Record<string, unknown>;
  scripts: Record<string, string>;
}

interface KnowledgeDetail {
  meta: Record<string, unknown>;
  content: string;
}

export default function EnvironmentManager() {
  const [envs, setEnvs] = useState<EnvInfo[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [tab, setTab] = useState<"tools" | "knowledge">("tools");
  const [editingTool, setEditingTool] = useState<string>("");
  const [toolDetail, setToolDetail] = useState<ToolDetail>({ meta: {}, scripts: {} });
  const [editingKnowledge, setEditingKnowledge] = useState<string>("");
  const [knowledgeDetail, setKnowledgeDetail] = useState<KnowledgeDetail>({ meta: {}, content: "" });
  const [status, setStatus] = useState("");
  const [newEnvName, setNewEnvName] = useState("");
  const [newToolName, setNewToolName] = useState("");
  const [newKnowledgeName, setNewKnowledgeName] = useState("");

  const refreshList = useCallback(async () => {
    const list = await api.listEnvironments();
    setEnvs(list);
  }, []);

  useEffect(() => { refreshList(); }, [refreshList]);

  const selectedEnv = envs.find((e) => e.path_b64 === selected);

  const loadToolDetail = async (tname: string) => {
    if (!selected) return;
    setEditingTool(tname);
    setEditingKnowledge("");
    try {
      const d = await api.loadEnvTool(selected, tname);
      setToolDetail(d);
    } catch (e: unknown) {
      setStatus(`加载失败: ${(e as Error).message}`);
    }
  };

  const saveToolFn = async () => {
    if (!selected || !editingTool) return;
    setStatus("保存中...");
    try {
      await api.saveEnvTool(selected, editingTool, toolDetail);
      setStatus("已保存 tool");
      refreshList();
    } catch (e: unknown) {
      setStatus(`保存失败: ${(e as Error).message}`);
    }
  };

  const deleteToolFn = async (tname: string) => {
    if (!selected || !confirm(`删除 tool "${tname}"？`)) return;
    setStatus("删除中...");
    try {
      await api.deleteEnvTool(selected, tname);
      setStatus(`已删除 ${tname}`);
      setEditingTool("");
      refreshList();
    } catch (e: unknown) {
      setStatus(`删除失败: ${(e as Error).message}`);
    }
  };

  const newTool = () => {
    const name = newToolName.trim();
    if (!name) { setStatus("请输入 Tool 名称"); return; }
    setEditingTool(name);
    setEditingKnowledge("");
    setNewToolName("");
    setToolDetail({
      meta: { type: "function", title: name, name, description: "", parameters: { type: "object", properties: {}, required: [] }, tags: [], author: "admin" },
      scripts: { [`${name}.py`]: "# 在此编写工具实现\n\ndef main(**kwargs):\n    return {\"result\": \"ok\"}\n" },
    });
  };

  const loadKnowledgeDetail = async (kname: string) => {
    if (!selected) return;
    setEditingKnowledge(kname);
    setEditingTool("");
    try {
      const d = await api.loadEnvKnowledge(selected, kname);
      setKnowledgeDetail(d);
    } catch (e: unknown) {
      setStatus(`加载失败: ${(e as Error).message}`);
    }
  };

  const saveKnowledgeFn = async () => {
    if (!selected || !editingKnowledge) return;
    setStatus("保存中...");
    try {
      await api.saveEnvKnowledge(selected, editingKnowledge, knowledgeDetail);
      setStatus("已保存 knowledge");
      refreshList();
    } catch (e: unknown) {
      setStatus(`保存失败: ${(e as Error).message}`);
    }
  };

  const deleteKnowledgeFn = async (kname: string) => {
    if (!selected || !confirm(`删除 knowledge "${kname}"？`)) return;
    setStatus("删除中...");
    try {
      await api.deleteEnvKnowledge(selected, kname);
      setStatus(`已删除 ${kname}`);
      setEditingKnowledge("");
      refreshList();
    } catch (e: unknown) {
      setStatus(`删除失败: ${(e as Error).message}`);
    }
  };

  const newKnowledge = () => {
    const name = newKnowledgeName.trim();
    if (!name) { setStatus("请输入 Knowledge 名称"); return; }
    setEditingKnowledge(name);
    setEditingTool("");
    setNewKnowledgeName("");
    setKnowledgeDetail({
      meta: { name, description: "" },
      content: "# 在此编写知识内容\n",
    });
  };

  const createNewEnv = async () => {
    const name = newEnvName.trim();
    if (!name) { setStatus("请输入 Environment 名称"); return; }
    setStatus("创建中...");
    try {
      await api.createEnvironment(name);
      setStatus(`已创建 ${name}`);
      setNewEnvName("");
      refreshList();
    } catch (e: unknown) {
      setStatus(`创建失败: ${(e as Error).message}`);
    }
  };

  return (
    <div style={{ display: "flex", height: "100%", gap: 0 }}>
      {/* 左侧环境列表 */}
      <div style={{ width: 240, borderRight: "1px solid #333", padding: 12, overflowY: "auto", flexShrink: 0 }}>
        <h3 style={{ margin: "0 0 8px", fontSize: 14, color: "#aaa" }}>🌍 Environments</h3>
        <div style={{ marginBottom: 8 }}>
          <input
            placeholder="新 environment 名称"
            value={newEnvName}
            onChange={(e) => setNewEnvName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && createNewEnv()}
            style={{ width: "100%", padding: "4px 6px", fontSize: 12, background: "#1a1a2e", border: "1px solid #444", color: "#ddd", borderRadius: 4, marginBottom: 4, boxSizing: "border-box" }}
          />
          <button onClick={createNewEnv} style={btnStyle}>+ 新建 Environment</button>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {envs.map((env) => (
            <div
              key={env.path_b64}
              onClick={() => { setSelected(env.path_b64); setEditingTool(""); setEditingKnowledge(""); }}
              style={{
                padding: "8px",
                borderRadius: 4,
                cursor: "pointer",
                background: selected === env.path_b64 ? "#2a3f5f" : "transparent",
                color: selected === env.path_b64 ? "#7ecfff" : "#ccc",
                fontSize: 12,
              }}
            >
              <div style={{ fontWeight: "bold", marginBottom: 2 }}>{env.name}</div>
              <div style={{ fontSize: 10, color: "#666", wordBreak: "break-all" }}>{env.path}</div>
              <div style={{ fontSize: 10, color: "#888", marginTop: 4 }}>
                🔧 {env.tools.length} tools · 📚 {env.knowledge.length} knowledge
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 右侧编辑区 */}
      <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
        {!selectedEnv ? (
          <div style={{ color: "#666", textAlign: "center", marginTop: 80 }}>
            选择一个 Environment 开始管理
          </div>
        ) : (
          <>
            <div style={{ marginBottom: 8, fontSize: 13, color: "#aaa" }}>
              📂 {selectedEnv.path}
            </div>

            <div style={{ display: "flex", gap: 8, marginBottom: 12, borderBottom: "1px solid #333", paddingBottom: 8 }}>
              {(["tools", "knowledge"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  style={{
                    padding: "6px 14px",
                    border: "none",
                    borderRadius: 4,
                    cursor: "pointer",
                    background: tab === t ? "#3a5f8f" : "transparent",
                    color: tab === t ? "#fff" : "#888",
                    fontSize: 13,
                  }}
                >
                  {t === "tools" ? "🔧 Tools" : "📚 Knowledge"}
                </button>
              ))}
            </div>

            {status && (
              <div style={{ padding: "4px 8px", marginBottom: 8, background: status.includes("失败") ? "#522" : "#252", borderRadius: 4, fontSize: 12, color: "#aaa" }}>
                {status}
              </div>
            )}

            {/* Tools */}
            {tab === "tools" && (
              <div style={{ display: "flex", gap: 12 }}>
                <div style={{ width: 200, borderRight: "1px solid #333", paddingRight: 8 }}>
                  <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
                    <input
                      placeholder="Tool 名称"
                      value={newToolName}
                      onChange={(e) => setNewToolName(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && newTool()}
                      style={{ flex: 1, padding: "4px 6px", fontSize: 11, background: "#1a1a2e", border: "1px solid #444", color: "#ddd", borderRadius: 4 }}
                    />
                    <button onClick={newTool} style={btnStyle}>+</button>
                  </div>
                  {selectedEnv.tools.map((t) => (
                    <div
                      key={t}
                      onClick={() => loadToolDetail(t)}
                      style={{
                        padding: "4px 8px", cursor: "pointer", borderRadius: 4, fontSize: 12,
                        background: editingTool === t ? "#2a3f5f" : "transparent",
                        color: editingTool === t ? "#7ecfff" : "#aaa",
                        display: "flex", justifyContent: "space-between",
                      }}
                    >
                      <span>{t}</span>
                      <button onClick={(e) => { e.stopPropagation(); deleteToolFn(t); }} style={{ background: "none", border: "none", color: "#f66", cursor: "pointer", fontSize: 11 }}>✕</button>
                    </div>
                  ))}
                </div>
                <div style={{ flex: 1 }}>
                  {editingTool ? (
                    <>
                      <h4 style={{ color: "#7ecfff", margin: "0 0 8px" }}>编辑: {editingTool}</h4>
                      <div style={{ marginBottom: 8 }}>
                        <label style={labelStyle}>Meta JSON</label>
                        <textarea
                          value={JSON.stringify(toolDetail.meta, null, 2)}
                          onChange={(e) => { try { setToolDetail({ ...toolDetail, meta: JSON.parse(e.target.value) }); } catch {} }}
                          rows={12}
                          style={{ ...textareaStyle, fontFamily: "monospace", fontSize: 11 }}
                        />
                      </div>
                      <h4 style={{ color: "#aaa", fontSize: 13, margin: "8px 0" }}>脚本</h4>
                      {Object.entries(toolDetail.scripts).map(([fname, content]) => (
                        <div key={fname} style={{ marginBottom: 8 }}>
                          <label style={labelStyle}>{fname}</label>
                          <textarea
                            value={content}
                            onChange={(e) => setToolDetail({ ...toolDetail, scripts: { ...toolDetail.scripts, [fname]: e.target.value } })}
                            rows={10}
                            style={{ ...textareaStyle, fontFamily: "monospace", fontSize: 11 }}
                          />
                        </div>
                      ))}
                      <button onClick={saveToolFn} style={{ ...btnStyle, padding: "8px 20px", fontSize: 14 }}>💾 保存 Tool</button>
                    </>
                  ) : (
                    <div style={{ color: "#555", textAlign: "center", marginTop: 40 }}>选择一个 tool 编辑，或新建一个</div>
                  )}
                </div>
              </div>
            )}

            {/* Knowledge */}
            {tab === "knowledge" && (
              <div style={{ display: "flex", gap: 12 }}>
                <div style={{ width: 200, borderRight: "1px solid #333", paddingRight: 8 }}>
                  <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
                    <input
                      placeholder="Knowledge 名称"
                      value={newKnowledgeName}
                      onChange={(e) => setNewKnowledgeName(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && newKnowledge()}
                      style={{ flex: 1, padding: "4px 6px", fontSize: 11, background: "#1a1a2e", border: "1px solid #444", color: "#ddd", borderRadius: 4 }}
                    />
                    <button onClick={newKnowledge} style={btnStyle}>+</button>
                  </div>
                  {selectedEnv.knowledge.map((k) => (
                    <div
                      key={k}
                      onClick={() => loadKnowledgeDetail(k)}
                      style={{
                        padding: "4px 8px", cursor: "pointer", borderRadius: 4, fontSize: 12,
                        background: editingKnowledge === k ? "#2a3f5f" : "transparent",
                        color: editingKnowledge === k ? "#7ecfff" : "#aaa",
                        display: "flex", justifyContent: "space-between",
                      }}
                    >
                      <span>{k}</span>
                      <button onClick={(e) => { e.stopPropagation(); deleteKnowledgeFn(k); }} style={{ background: "none", border: "none", color: "#f66", cursor: "pointer", fontSize: 11 }}>✕</button>
                    </div>
                  ))}
                </div>
                <div style={{ flex: 1 }}>
                  {editingKnowledge ? (
                    <>
                      <h4 style={{ color: "#7ecfff", margin: "0 0 8px" }}>编辑: {editingKnowledge}</h4>
                      <div style={{ marginBottom: 8 }}>
                        <label style={labelStyle}>Meta JSON</label>
                        <textarea
                          value={JSON.stringify(knowledgeDetail.meta, null, 2)}
                          onChange={(e) => { try { setKnowledgeDetail({ ...knowledgeDetail, meta: JSON.parse(e.target.value) }); } catch {} }}
                          rows={6}
                          style={{ ...textareaStyle, fontFamily: "monospace", fontSize: 11 }}
                        />
                      </div>
                      <div style={{ marginBottom: 8 }}>
                        <label style={labelStyle}>内容 (Markdown)</label>
                        <textarea
                          value={knowledgeDetail.content}
                          onChange={(e) => setKnowledgeDetail({ ...knowledgeDetail, content: e.target.value })}
                          rows={16}
                          style={{ ...textareaStyle, fontFamily: "monospace", fontSize: 12 }}
                        />
                      </div>
                      <button onClick={saveKnowledgeFn} style={{ ...btnStyle, padding: "8px 20px", fontSize: 14 }}>💾 保存 Knowledge</button>
                    </>
                  ) : (
                    <div style={{ color: "#555", textAlign: "center", marginTop: 40 }}>选择一个 knowledge 编辑，或新建一个</div>
                  )}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

const labelStyle: React.CSSProperties = { display: "block", fontSize: 11, color: "#888", marginBottom: 2 };
const textareaStyle: React.CSSProperties = { width: "100%", padding: "6px 8px", fontSize: 12, background: "#1a1a2e", border: "1px solid #444", color: "#ddd", borderRadius: 4, boxSizing: "border-box", resize: "vertical" };
const btnStyle: React.CSSProperties = { padding: "4px 10px", fontSize: 12, background: "#2a5f3f", color: "#cfc", border: "none", borderRadius: 4, cursor: "pointer" };
