const BASE = `http://${window.location.hostname}:8765`;

async function request(method: string, path: string, body?: unknown) {
  const opts: RequestInit = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(`${BASE}${path}`, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error || res.statusText);
  }
  return res.json();
}

// ============ Harness ============

export async function listHarnesses(): Promise<string[]> {
  return request("GET", "/api/harnesses");
}

export async function loadHarness(name: string) {
  return request("GET", `/api/harness/${encodeURIComponent(name)}`);
}

export async function saveHarness(name: string, config: unknown) {
  return request("PUT", `/api/harness/${encodeURIComponent(name)}`, config);
}

// ============ Identity ============

export async function listIdentities(): Promise<string[]> {
  return request("GET", "/api/identities");
}

export async function loadIdentity(name: string) {
  return request("GET", `/api/identity/${encodeURIComponent(name)}`);
}

export async function saveIdentity(name: string, idData: unknown) {
  return request("PUT", `/api/identity/${encodeURIComponent(name)}`, idData);
}

export async function saveSuperego(name: string, data: unknown) {
  return request("PUT", `/api/identity/${encodeURIComponent(name)}/superego`, data);
}

export async function loadSkill(identityName: string, skillName: string) {
  return request("GET", `/api/identity/${encodeURIComponent(identityName)}/skill/${encodeURIComponent(skillName)}`);
}

export async function saveSkill(identityName: string, skillName: string, data: { meta: unknown; scripts: Record<string, string> }) {
  return request("PUT", `/api/identity/${encodeURIComponent(identityName)}/skill/${encodeURIComponent(skillName)}`, data);
}

export async function deleteSkill(identityName: string, skillName: string) {
  return request("DELETE", `/api/identity/${encodeURIComponent(identityName)}/skill/${encodeURIComponent(skillName)}`);
}

export async function loadKnowledge(identityName: string, knowledgeName: string) {
  return request("GET", `/api/identity/${encodeURIComponent(identityName)}/knowledge/${encodeURIComponent(knowledgeName)}`);
}

export async function saveKnowledge(identityName: string, knowledgeName: string, data: { meta: unknown; content: string }) {
  return request("PUT", `/api/identity/${encodeURIComponent(identityName)}/knowledge/${encodeURIComponent(knowledgeName)}`, data);
}

export async function deleteKnowledge(identityName: string, knowledgeName: string) {
  return request("DELETE", `/api/identity/${encodeURIComponent(identityName)}/knowledge/${encodeURIComponent(knowledgeName)}`);
}

export async function cloneIdentity(name: string, newName: string) {
  return request("POST", `/api/identity/${encodeURIComponent(name)}/clone`, { new_name: newName });
}

export async function deleteIdentity(name: string) {
  return request("DELETE", `/api/identity/${encodeURIComponent(name)}`);
}

// ============ Environment ============

export async function listEnvironments() {
  return request("GET", "/api/environments");
}

export async function createEnvironment(name: string) {
  return request("POST", "/api/environments", { name });
}

export async function loadEnvironment(pathB64: string) {
  return request("GET", `/api/environment/${encodeURIComponent(pathB64)}`);
}

export async function loadEnvTool(pathB64: string, toolName: string) {
  return request("GET", `/api/environment/${encodeURIComponent(pathB64)}/tool/${encodeURIComponent(toolName)}`);
}

export async function saveEnvTool(pathB64: string, toolName: string, data: { meta: unknown; scripts: Record<string, string> }) {
  return request("PUT", `/api/environment/${encodeURIComponent(pathB64)}/tool/${encodeURIComponent(toolName)}`, data);
}

export async function deleteEnvTool(pathB64: string, toolName: string) {
  return request("DELETE", `/api/environment/${encodeURIComponent(pathB64)}/tool/${encodeURIComponent(toolName)}`);
}

export async function loadEnvKnowledge(pathB64: string, knowledgeName: string) {
  return request("GET", `/api/environment/${encodeURIComponent(pathB64)}/knowledge/${encodeURIComponent(knowledgeName)}`);
}

export async function saveEnvKnowledge(pathB64: string, knowledgeName: string, data: { meta: unknown; content: string }) {
  return request("PUT", `/api/environment/${encodeURIComponent(pathB64)}/knowledge/${encodeURIComponent(knowledgeName)}`, data);
}

export async function deleteEnvKnowledge(pathB64: string, knowledgeName: string) {
  return request("DELETE", `/api/environment/${encodeURIComponent(pathB64)}/knowledge/${encodeURIComponent(knowledgeName)}`);
}

// ============ Execution ============

let _ws: WebSocket | null = null;
let _wsCallbacks: Array<(msg: any) => void> = [];

export async function getExecutionState() {
  return request("GET", "/api/execution/state");
}

export async function startExecution(harness: string, agents: Record<string, string>) {
  return request("POST", "/api/execution/start", { harness, agents });
}

export async function stopExecution() {
  return request("POST", "/api/execution/stop");
}

export function hasWebSocket(): boolean {
  return _ws !== null && _ws.readyState === WebSocket.OPEN;
}

export function sendInputViaWs(text: string) {
  console.log("[sendInputViaWs] text:", text, "ws:", _ws, "readyState:", _ws?.readyState);
  if (_ws && _ws.readyState === WebSocket.OPEN) {
    _ws.send(JSON.stringify({ type: "input", text }));
    console.log("[sendInputViaWs] sent successfully via WS");
  } else {
    console.warn("[sendInputViaWs] WebSocket not open, falling back to HTTP POST");
    fetch(`${BASE}/api/execution/input`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }).catch((e) => console.error("[sendInputViaWs] HTTP fallback failed:", e));
  }
}

export function subscribeExecution(callback: (msg: any) => void): () => void {
  _wsCallbacks.push(callback);

  const connect = () => {
    if (_ws && _ws.readyState === WebSocket.OPEN) return;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    _ws = new WebSocket(`${protocol}//${window.location.hostname}:8766`);

    _ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        for (const cb of _wsCallbacks) {
          cb(msg);
        }
      } catch {}
    };

    _ws.onclose = () => {
      _ws = null;
      setTimeout(connect, 2000);
    };
  };

  connect();

  return () => {
    _wsCallbacks = _wsCallbacks.filter((c) => c !== callback);
  };
}
