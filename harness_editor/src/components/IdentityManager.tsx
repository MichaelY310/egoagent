import { useState, useEffect, useCallback } from "react";
import * as api from "../api/client";

interface IdData {
  name: string;
  personality: { traits: string[]; tone: string; language: string };
  role: string;
  description: string;
  llm: {
    type: string;
    base_url: string;
    model: string;
    api_key: string;
    temperature: number;
    max_tokens: number;
  };
}

interface SuperegoData {
  task_prompt?: string;
  tool_access?: { whitelist: string[]; blacklist: string[] };
  knowledge_access?: { whitelist: string[]; blacklist: string[] };
  allow_create_agent?: boolean;
  allow_create_identity?: boolean;
  allow_modify_agent?: boolean;
  allow_modify_identity?: boolean;
  allow_add_skill_to_self?: boolean;
  allow_add_knowledge_to_self?: boolean;
  allow_add_skill_to_other?: boolean;
  allow_add_knowledge_to_other?: boolean;
  allow_add_tool_to_environment?: boolean;
  allow_add_knowledge_to_environment?: boolean;
}

interface SkillDetail {
  meta: Record<string, unknown>;
  scripts: Record<string, string>;
}

interface KnowledgeDetail {
  meta: Record<string, unknown>;
  content: string;
}

const defaultId: IdData = {
  name: "",
  personality: { traits: [], tone: "", language: "zh" },
  role: "",
  description: "",
  llm: {
    type: "custom_llm",
    base_url: "",
    model: "",
    api_key: "",
    temperature: 0.2,
    max_tokens: 4096,
  },
};

const defaultSuperego: SuperegoData = {
  task_prompt: "",
  tool_access: { whitelist: [], blacklist: [] },
  knowledge_access: { whitelist: [], blacklist: [] },
  allow_create_agent: false,
  allow_create_identity: false,
  allow_modify_agent: false,
  allow_modify_identity: false,
  allow_add_skill_to_self: false,
  allow_add_knowledge_to_self: false,
  allow_add_skill_to_other: false,
  allow_add_knowledge_to_other: false,
  allow_add_tool_to_environment: false,
  allow_add_knowledge_to_environment: false,
};

export default function IdentityManager() {
  const [identities, setIdentities] = useState<string[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [idData, setIdData] = useState<IdData>(defaultId);
  const [superego, setSuperego] = useState<SuperegoData>(defaultSuperego);
  const [skills, setSkills] = useState<string[]>([]);
  const [knowledge, setKnowledge] = useState<string[]>([]);
  const [tab, setTab] = useState<"id" | "superego" | "skills" | "knowledge">("id");
  const [editingSkill, setEditingSkill] = useState<string>("");
  const [skillDetail, setSkillDetail] = useState<SkillDetail>({ meta: {}, scripts: {} });
  const [editingKnowledge, setEditingKnowledge] = useState<string>("");
  const [knowledgeDetail, setKnowledgeDetail] = useState<KnowledgeDetail>({ meta: {}, content: "" });
  const [newName, setNewName] = useState("");
  const [cloneTarget, setCloneTarget] = useState("");
  const [newSkillName, setNewSkillName] = useState("");
  const [newKnowledgeName, setNewKnowledgeName] = useState("");
  const [status, setStatus] = useState("");
  const [agentDescription, setAgentDescription] = useState("");
  const [agentSystemName, setAgentSystemName] = useState("");
  const [createdHarness, setCreatedHarness] = useState("");

  const refreshList = useCallback(async () => {
    const list = await api.listIdentities();
    setIdentities(list);
  }, []);

  useEffect(() => { refreshList(); }, [refreshList]);

  const loadFull = async (name: string) => {
    setSelected(name);
    setStatus("加载中...");
    try {
      const data = await api.loadIdentity(name);
      setIdData(data.id);
      setSuperego(data.superego || defaultSuperego);
      setSkills(data.skills || []);
      setKnowledge(data.knowledge || []);
      setEditingSkill("");
      setEditingKnowledge("");
      setStatus("");
    } catch (e: unknown) {
      setStatus(`加载失败: ${(e as Error).message}`);
    }
  };

  const saveId = async () => {
    if (!selected) return;
    setStatus("保存中...");
    try {
      await api.saveIdentity(selected, idData);
      setStatus("已保存 id.json");
      refreshList();
    } catch (e: unknown) {
      setStatus(`保存失败: ${(e as Error).message}`);
    }
  };

  const saveSuperegoFn = async () => {
    if (!selected) return;
    setStatus("保存中...");
    try {
      await api.saveSuperego(selected, superego);
      setStatus("已保存 superego/config.json");
    } catch (e: unknown) {
      setStatus(`保存失败: ${(e as Error).message}`);
    }
  };

  const createNew = async () => {
    const name = newName.trim();
    if (!name) { setStatus("请输入名称"); return; }
    setStatus("创建中...");
    try {
      await api.saveIdentity(name, { ...defaultId, name });
      setStatus(`已创建 ${name}`);
      setNewName("");
      refreshList();
      loadFull(name);
    } catch (e: unknown) {
      setStatus(`创建失败: ${(e as Error).message}`);
    }
  };

  const createFullAgent = async () => {
    if (!agentDescription.trim()) { setStatus("请先描述 Agent 要做什么"); return; }
    setStatus("正在创建有效 Identity、真实 Skills 和可视化 Harness...");
    try {
      const result = await api.createAgentSystem(agentDescription.trim(), agentSystemName.trim() || undefined);
      const identityName = result.identity?.name || "";
      setCreatedHarness(result.harness || result.recommended_harness || "");
      setAgentDescription("");
      setAgentSystemName("");
      await refreshList();
      if (identityName) await loadFull(identityName);
      setStatus(`完整 Agent ${identityName} 已创建；专属 Harness: ${result.harness}`);
    } catch (e: unknown) {
      setStatus(`完整 Agent 创建失败: ${(e as Error).message}`);
    }
  };

  const doClone = async () => {
    if (!cloneTarget || !newName.trim()) { setStatus("请选择源和目标名称"); return; }
    setStatus("克隆中...");
    try {
      await api.cloneIdentity(cloneTarget, newName.trim());
      setStatus(`已克隆 ${cloneTarget} → ${newName.trim()}`);
      setNewName("");
      refreshList();
    } catch (e: unknown) {
      setStatus(`克隆失败: ${(e as Error).message}`);
    }
  };

  const doDelete = async (name: string) => {
    if (!confirm(`确定删除 identity "${name}"？此操作不可撤销。`)) return;
    setStatus("删除中...");
    try {
      await api.deleteIdentity(name);
      setStatus(`已删除 ${name}`);
      if (selected === name) setSelected("");
      refreshList();
    } catch (e: unknown) {
      setStatus(`删除失败: ${(e as Error).message}`);
    }
  };

  const loadSkillDetail = async (sname: string) => {
    if (!selected) return;
    setEditingSkill(sname);
    setEditingKnowledge("");
    try {
      const d = await api.loadSkill(selected, sname);
      setSkillDetail(d);
    } catch (e: unknown) {
      setStatus(`加载 skill 失败: ${(e as Error).message}`);
    }
  };

  const saveSkillFn = async () => {
    if (!selected || !editingSkill) return;
    setStatus("保存中...");
    try {
      await api.saveSkill(selected, editingSkill, skillDetail);
      setStatus("已保存 skill");
      refreshList();
    } catch (e: unknown) {
      setStatus(`保存失败: ${(e as Error).message}`);
    }
  };

  const deleteSkillFn = async (sname: string) => {
    if (!selected || !confirm(`删除 skill "${sname}"？`)) return;
    setStatus("删除中...");
    try {
      await api.deleteSkill(selected, sname);
      setStatus(`已删除 ${sname}`);
      setEditingSkill("");
      setSkills(skills.filter((s) => s !== sname));
    } catch (e: unknown) {
      setStatus(`删除失败: ${(e as Error).message}`);
    }
  };

  const newSkill = () => {
    const name = newSkillName.trim();
    if (!name) { setStatus("请输入 Skill 名称"); return; }
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) { setStatus("Skill 名称必须是可用的 Python 函数名（英文、数字、下划线）"); return; }
    setNewSkillName("");
    setEditingSkill(name);
    setEditingKnowledge("");
    setSkillDetail({
      meta: { type: "tool", title: name, name, description: "", parameters: { type: "object", properties: {}, required: [] }, tags: [], author: "admin" },
      scripts: { [`${name}.py`]: `# 在此编写工具实现\n\ndef ${name}(**kwargs):\n    return {"result": "ok"}\n` },
    });
  };

  const loadKnowledgeDetail = async (kname: string) => {
    if (!selected) return;
    setEditingKnowledge(kname);
    setEditingSkill("");
    try {
      const d = await api.loadKnowledge(selected, kname);
      setKnowledgeDetail(d);
    } catch (e: unknown) {
      setStatus(`加载 knowledge 失败: ${(e as Error).message}`);
    }
  };

  const saveKnowledgeFn = async () => {
    if (!selected || !editingKnowledge) return;
    setStatus("保存中...");
    try {
      await api.saveKnowledge(selected, editingKnowledge, knowledgeDetail);
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
      await api.deleteKnowledge(selected, kname);
      setStatus(`已删除 ${kname}`);
      setEditingKnowledge("");
      setKnowledge(knowledge.filter((k) => k !== kname));
    } catch (e: unknown) {
      setStatus(`删除失败: ${(e as Error).message}`);
    }
  };

  const newKnowledge = () => {
    const name = newKnowledgeName.trim();
    if (!name) { setStatus("请输入 Knowledge 名称"); return; }
    setNewKnowledgeName("");
    setEditingKnowledge(name);
    setEditingSkill("");
    setKnowledgeDetail({
      meta: { type: "knowledge", name, title: name.split("_").join(" "), description: "" },
      content: "# 在此编写知识内容\n",
    });
  };

  return (
    <div className="identity-manager" style={{ display: "flex", height: "100%", gap: 0 }}>
      {/* 左侧列表 */}
      <div style={{ width: 280, borderRight: "1px solid #333", padding: 12, overflowY: "auto", flexShrink: 0 }}>
        <h3 style={{ margin: "0 0 8px", fontSize: 14, color: "#aaa" }}>🤖 Identities</h3>

        <div style={{ padding: 9, marginBottom: 10, border: "1px solid #0ea5e955", background: "#082f4933", borderRadius: 7 }}>
          <div style={{ color: "#7dd3fc", fontSize: 12, fontWeight: 700, marginBottom: 5 }}>✨ 一句话创建完整 Agent</div>
          <textarea
            value={agentDescription}
            onChange={(event) => setAgentDescription(event.target.value)}
            placeholder="例如：一个会检查 Python 补丁、运行测试并解释风险的代码审查 Agent"
            rows={4}
            style={{ ...textareaStyle, fontSize: 11, marginBottom: 5 }}
          />
          <input
            value={agentSystemName}
            onChange={(event) => setAgentSystemName(event.target.value)}
            placeholder="可选英文名，如 review_bot"
            style={{ ...inputStyle, marginBottom: 5 }}
          />
          <button onClick={createFullAgent} style={{ ...btnStyle, width: "100%", background: "#0369a1", color: "#e0f2fe" }}>
            创建 Identity + Skills + Harness
          </button>
          {createdHarness && <div style={{ color: "#86efac", fontSize: 10, marginTop: 5 }}>可在 Harness 编排中加载：{createdHarness}</div>}
        </div>

        <div style={{ marginBottom: 8 }}>
          <input
            placeholder="新 identity 名称"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && createNew()}
            style={{ width: "100%", padding: "4px 6px", fontSize: 12, background: "#1a1a2e", border: "1px solid #444", color: "#ddd", borderRadius: 4, marginBottom: 4, boxSizing: "border-box" }}
          />
          <div style={{ display: "flex", gap: 4 }}>
            <button onClick={createNew} style={btnStyle}>新建</button>
            <select value={cloneTarget} onChange={(e) => setCloneTarget(e.target.value)} style={{ flex: 1, padding: "4px 6px", fontSize: 12, background: "#1a1a2e", border: "1px solid #444", color: "#ddd", borderRadius: 4 }}>
              <option value="">克隆源...</option>
              {identities.map((id) => <option key={id} value={id}>{id}</option>)}
            </select>
            <button onClick={doClone} style={btnStyle}>克隆</button>
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {identities.map((id) => (
            <div
              key={id}
              onClick={() => loadFull(id)}
              style={{
                padding: "6px 8px",
                borderRadius: 4,
                cursor: "pointer",
                background: selected === id ? "#2a3f5f" : "transparent",
                color: selected === id ? "#7ecfff" : "#ccc",
                fontSize: 13,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <span>{id}</span>
              <button
                onClick={(e) => { e.stopPropagation(); doDelete(id); }}
                style={{ background: "none", border: "none", color: "#f66", cursor: "pointer", fontSize: 12, padding: "0 4px" }}
                title="删除"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* 右侧编辑区 */}
      <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
        {!selected ? (
          <div style={{ color: "#666", textAlign: "center", marginTop: 80 }}>
            选择一个 identity 开始编辑，或新建一个
          </div>
        ) : (
          <>
            <div style={{ display: "flex", gap: 8, marginBottom: 12, borderBottom: "1px solid #333", paddingBottom: 8 }}>
              {(["id", "superego", "skills", "knowledge"] as const).map((t) => (
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
                  {t === "id" ? "📋 ID" : t === "superego" ? "🛡 Superego" : t === "skills" ? "🔧 Skills" : "📚 Knowledge"}
                </button>
              ))}
            </div>

            {status && (
              <div style={{ padding: "4px 8px", marginBottom: 8, background: status.includes("失败") ? "#522" : "#252", borderRadius: 4, fontSize: 12, color: "#aaa" }}>
                {status}
              </div>
            )}

            {/* ID 编辑 */}
            {tab === "id" && (
              <div>
                <Field label="名称" value={idData.name} onChange={(v) => setIdData({ ...idData, name: v })} />
                <Field label="角色 (role)" value={idData.role} onChange={(v) => setIdData({ ...idData, role: v })} />
                <div style={{ marginBottom: 8 }}>
                  <label style={labelStyle}>描述 (description)</label>
                  <textarea
                    value={idData.description}
                    onChange={(e) => setIdData({ ...idData, description: e.target.value })}
                    rows={4}
                    style={textareaStyle}
                  />
                </div>

                <h4 style={{ color: "#aaa", fontSize: 13, margin: "12px 0 4px" }}>性格 (personality)</h4>
                <Field label="语气 (tone)" value={idData.personality.tone} onChange={(v) => setIdData({ ...idData, personality: { ...idData.personality, tone: v } })} />
                <Field label="语言 (language)" value={idData.personality.language} onChange={(v) => setIdData({ ...idData, personality: { ...idData.personality, language: v } })} />
                <div style={{ marginBottom: 8 }}>
                  <label style={labelStyle}>特质 (traits)，逗号分隔</label>
                  <input
                    value={idData.personality.traits.join(", ")}
                    onChange={(e) => setIdData({ ...idData, personality: { ...idData.personality, traits: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) } })}
                    style={inputStyle}
                  />
                </div>

                <h4 style={{ color: "#aaa", fontSize: 13, margin: "12px 0 4px" }}>LLM 配置</h4>
                <Field label="类型 (type)" value={idData.llm.type} onChange={(v) => setIdData({ ...idData, llm: { ...idData.llm, type: v } })} />
                <Field label="Base URL" value={idData.llm.base_url} onChange={(v) => setIdData({ ...idData, llm: { ...idData.llm, base_url: v } })} />
                <Field label="模型 (model)" value={idData.llm.model} onChange={(v) => setIdData({ ...idData, llm: { ...idData.llm, model: v } })} />
                <p style={{ margin: "0 0 8px", color: "#777", fontSize: 11, lineHeight: 1.5 }}>
                  API Key 不写入 Identity。请在 Settings 配置服务端模型档案；Base URL 与模型留空时使用当前全局档案。
                </p>
                <Field label="Temperature" value={String(idData.llm.temperature)} onChange={(v) => setIdData({ ...idData, llm: { ...idData.llm, temperature: parseFloat(v) || 0 } })} />
                <Field label="Max Tokens" value={String(idData.llm.max_tokens)} onChange={(v) => setIdData({ ...idData, llm: { ...idData.llm, max_tokens: parseInt(v) || 0 } })} />

                <button onClick={saveId} style={{ ...btnStyle, marginTop: 12, padding: "8px 20px", fontSize: 14 }}>
                  💾 保存 id.json
                </button>
              </div>
            )}

            {/* Superego 编辑 */}
            {tab === "superego" && (
              <div>
                <div style={{ marginBottom: 8 }}>
                  <label style={labelStyle}>Task Prompt</label>
                  <textarea
                    value={superego.task_prompt || ""}
                    onChange={(e) => setSuperego({ ...superego, task_prompt: e.target.value })}
                    rows={6}
                    style={textareaStyle}
                  />
                </div>

                <h4 style={{ color: "#aaa", fontSize: 13, margin: "12px 0 4px" }}>工具访问控制</h4>
                <div style={{ display: "flex", gap: 12 }}>
                  <div style={{ flex: 1 }}>
                    <label style={labelStyle}>白名单 (逗号分隔)</label>
                    <input
                      value={(superego.tool_access?.whitelist || []).join(", ")}
                      onChange={(e) => setSuperego({ ...superego, tool_access: { whitelist: e.target.value.split(",").map((s: string) => s.trim()).filter(Boolean), blacklist: superego.tool_access?.blacklist || [] } })}
                      style={inputStyle}
                    />
                  </div>
                  <div style={{ flex: 1 }}>
                    <label style={labelStyle}>黑名单 (逗号分隔)</label>
                    <input
                      value={(superego.tool_access?.blacklist || []).join(", ")}
                      onChange={(e) => setSuperego({ ...superego, tool_access: { whitelist: superego.tool_access?.whitelist || [], blacklist: e.target.value.split(",").map((s: string) => s.trim()).filter(Boolean) } })}
                      style={inputStyle}
                    />
                  </div>
                </div>

                <h4 style={{ color: "#aaa", fontSize: 13, margin: "12px 0 4px" }}>知识访问控制</h4>
                <div style={{ display: "flex", gap: 12 }}>
                  <div style={{ flex: 1 }}>
                    <label style={labelStyle}>白名单 (逗号分隔)</label>
                    <input
                      value={(superego.knowledge_access?.whitelist || []).join(", ")}
                      onChange={(e) => setSuperego({ ...superego, knowledge_access: { whitelist: e.target.value.split(",").map((s: string) => s.trim()).filter(Boolean), blacklist: superego.knowledge_access?.blacklist || [] } })}
                      style={inputStyle}
                    />
                  </div>
                  <div style={{ flex: 1 }}>
                    <label style={labelStyle}>黑名单 (逗号分隔)</label>
                    <input
                      value={(superego.knowledge_access?.blacklist || []).join(", ")}
                      onChange={(e) => setSuperego({ ...superego, knowledge_access: { whitelist: superego.knowledge_access?.whitelist || [], blacklist: e.target.value.split(",").map((s: string) => s.trim()).filter(Boolean) } })}
                      style={inputStyle}
                    />
                  </div>
                </div>

                <h4 style={{ color: "#aaa", fontSize: 13, margin: "12px 0 4px" }}>权限开关</h4>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
                  {([
                    ["allow_create_agent", "创建 agent"],
                    ["allow_create_identity", "创建 identity"],
                    ["allow_modify_agent", "修改 agent"],
                    ["allow_modify_identity", "修改 identity"],
                    ["allow_add_skill_to_self", "给自己加 skill"],
                    ["allow_add_knowledge_to_self", "给自己加 knowledge"],
                    ["allow_add_skill_to_other", "给别人加 skill"],
                    ["allow_add_knowledge_to_other", "给别人加 knowledge"],
                    ["allow_add_tool_to_environment", "给 environment 加 tool"],
                    ["allow_add_knowledge_to_environment", "给 environment 加 knowledge"],
                  ] as [keyof SuperegoData, string][]).map(([key, label]) => (
                    <label key={key} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#bbb", cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={!!superego[key]}
                        onChange={(e) => setSuperego({ ...superego, [key]: e.target.checked })}
                      />
                      {label}
                    </label>
                  ))}
                </div>

                <button onClick={saveSuperegoFn} style={{ ...btnStyle, marginTop: 12, padding: "8px 20px", fontSize: 14 }}>
                  💾 保存 superego/config.json
                </button>
              </div>
            )}

            {/* Skills 管理 */}
            {tab === "skills" && (
              <div style={{ display: "flex", gap: 12 }}>
                <div style={{ width: 200, borderRight: "1px solid #333", paddingRight: 8 }}>
                  <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
                    <input
                      placeholder="新 skill 名称"
                      value={newSkillName}
                      onChange={(e) => setNewSkillName(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && newSkill()}
                      style={{ flex: 1, padding: "4px 6px", fontSize: 11, background: "#1a1a2e", border: "1px solid #444", color: "#ddd", borderRadius: 4 }}
                    />
                    <button onClick={newSkill} style={btnStyle}>+</button>
                  </div>
                  {skills.map((s) => (
                    <div
                      key={s}
                      onClick={() => loadSkillDetail(s)}
                      style={{
                        padding: "4px 8px", cursor: "pointer", borderRadius: 4, fontSize: 12,
                        background: editingSkill === s ? "#2a3f5f" : "transparent",
                        color: editingSkill === s ? "#7ecfff" : "#aaa",
                        display: "flex", justifyContent: "space-between",
                      }}
                    >
                      <span>{s}</span>
                      <button onClick={(e) => { e.stopPropagation(); deleteSkillFn(s); }} style={{ background: "none", border: "none", color: "#f66", cursor: "pointer", fontSize: 11 }}>✕</button>
                    </div>
                  ))}
                </div>
                <div style={{ flex: 1 }}>
                  {editingSkill ? (
                    <>
                      <h4 style={{ color: "#7ecfff", margin: "0 0 8px" }}>编辑: {editingSkill}</h4>
                      <div style={{ marginBottom: 8 }}>
                        <label style={labelStyle}>Meta JSON</label>
                        <textarea
                          value={JSON.stringify(skillDetail.meta, null, 2)}
                          onChange={(e) => { try { setSkillDetail({ ...skillDetail, meta: JSON.parse(e.target.value) }); } catch {} }}
                          rows={12}
                          style={{ ...textareaStyle, fontFamily: "monospace", fontSize: 11 }}
                        />
                      </div>
                      <h4 style={{ color: "#aaa", fontSize: 13, margin: "8px 0" }}>脚本</h4>
                      {Object.entries(skillDetail.scripts).map(([fname, content]) => (
                        <div key={fname} style={{ marginBottom: 8 }}>
                          <label style={labelStyle}>{fname}</label>
                          <textarea
                            value={content}
                            onChange={(e) => setSkillDetail({ ...skillDetail, scripts: { ...skillDetail.scripts, [fname]: e.target.value } })}
                            rows={10}
                            style={{ ...textareaStyle, fontFamily: "monospace", fontSize: 11 }}
                          />
                        </div>
                      ))}
                      <button onClick={saveSkillFn} style={{ ...btnStyle, padding: "8px 20px", fontSize: 14 }}>💾 保存 Skill</button>
                    </>
                  ) : (
                    <div style={{ color: "#555", textAlign: "center", marginTop: 40 }}>选择一个 skill 编辑，或新建一个</div>
                  )}
                </div>
              </div>
            )}

            {/* Knowledge 管理 */}
            {tab === "knowledge" && (
              <div style={{ display: "flex", gap: 12 }}>
                <div style={{ width: 200, borderRight: "1px solid #333", paddingRight: 8 }}>
                  <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
                    <input
                      placeholder="新 knowledge 名称"
                      value={newKnowledgeName}
                      onChange={(e) => setNewKnowledgeName(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && newKnowledge()}
                      style={{ flex: 1, padding: "4px 6px", fontSize: 11, background: "#1a1a2e", border: "1px solid #444", color: "#ddd", borderRadius: 4 }}
                    />
                    <button onClick={newKnowledge} style={btnStyle}>+</button>
                  </div>
                  {knowledge.map((k) => (
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

function Field({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div style={{ marginBottom: 6 }}>
      <label style={labelStyle}>{label}</label>
      <input value={value} onChange={(e) => onChange(e.target.value)} style={inputStyle} />
    </div>
  );
}

const labelStyle: React.CSSProperties = { display: "block", fontSize: 11, color: "#888", marginBottom: 2 };
const inputStyle: React.CSSProperties = { width: "100%", padding: "4px 8px", fontSize: 12, background: "var(--input-background)", border: "1px solid var(--border)", color: "var(--text-primary)", borderRadius: 4, boxSizing: "border-box" };
const textareaStyle: React.CSSProperties = { width: "100%", padding: "6px 8px", fontSize: 12, background: "var(--input-background)", border: "1px solid var(--border)", color: "var(--text-primary)", borderRadius: 4, boxSizing: "border-box", resize: "vertical" };
const btnStyle: React.CSSProperties = { padding: "4px 10px", fontSize: 12, background: "#2a5f3f", color: "#cfc", border: "none", borderRadius: 4, cursor: "pointer" };
