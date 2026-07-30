"""
EgoAgent Harness Editor 后端 API 服务器

提供：
  Harness:
    GET  /api/harnesses           列出所有 harness
    GET  /api/harness/<name>      加载 harness config
    PUT  /api/harness/<name>      保存 harness config

  Identity:
    GET  /api/identities                    列出所有 identity
    GET  /api/identity/<name>               获取完整 identity
    PUT  /api/identity/<name>               保存 id.json
    PUT  /api/identity/<name>/superego      保存 superego/config.json
    GET  /api/identity/<name>/skill/<sname> 获取 skill 详情
    PUT  /api/identity/<name>/skill/<sname> 保存 skill
    DELETE /api/identity/<name>/skill/<sname> 删除 skill
    GET  /api/identity/<name>/knowledge/<kname> 获取 knowledge 详情
    PUT  /api/identity/<name>/knowledge/<kname> 保存 knowledge
    DELETE /api/identity/<name>/knowledge/<kname> 删除 knowledge
    POST /api/identity/<name>/clone         克隆 identity
    DELETE /api/identity/<name>             删除 identity

  Environment:
    GET  /api/environments                   列出所有 environment
    GET  /api/environment/<path_base64>      获取 environment 详情
    PUT  /api/environment/<path_base64>/tool/<tname>     保存 tool
    DELETE /api/environment/<path_base64>/tool/<tname>   删除 tool
    PUT  /api/environment/<path_base64>/knowledge/<kname> 保存 knowledge
    DELETE /api/environment/<path_base64>/knowledge/<kname> 删除 knowledge

  Execution:
    GET  /api/execution/state     获取执行状态
    POST /api/execution/start     启动执行
    POST /api/execution/stop      停止执行
    POST /api/execution/input     发送用户输入
    WS   ws://localhost:8766      实时执行状态推送 + 输出流
"""

import json
import os
import sys
import shutil
import threading
import base64
import queue
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
from urllib.parse import urlparse, unquote

HARNESS_DIR = Path(__file__).resolve().parent.parent / "harness"
IDENTITY_DIR = Path(__file__).resolve().parent.parent / "identity"
SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"
ENVIRONMENT_DIR = Path(__file__).resolve().parent.parent / "environment"

# 确保 environment 根目录存在
ENVIRONMENT_DIR.mkdir(parents=True, exist_ok=True)

# 额外兼容的旧 environment 路径（会被扫描但新建不走这里）
_LEGACY_ENV_DIRS = [
    Path("/home/tiger/.environment"),
    Path(__file__).resolve().parent.parent / "playground_malkuth" / ".environment",
    Path(__file__).resolve().parent.parent / "playground" / ".environment",
]

execution_state = {
    "running": False,
    "current_node": None,
    "step_count": 0,
    "messages_count": 0,
    "_tick": 0,
}

accumulated_outputs: list = []

ws_clients = set()
exec_input_queue = None
exec_ws_client = None

import uuid as _uuid
_async_tasks = {}  # task_id -> {"status": "running"|"completed"|"error", "result": {}, "error": ""}


def notify_clients(state):
    for client in list(ws_clients):
        try:
            client.send(json.dumps(state))
        except Exception:
            ws_clients.discard(client)


def notify_output(msg_type, data):
    """向所有 WebSocket 客户端推送输出，并递增 _tick 强制重渲染"""
    global exec_ws_client, accumulated_outputs
    execution_state["_tick"] = (execution_state.get("_tick", 0) + 1) % 1000000

    if msg_type == "token":
        agent = data.get("agent", "unknown")
        text = data.get("text", "")
        if accumulated_outputs and accumulated_outputs[-1]["agent"] == agent and not accumulated_outputs[-1].get("tools") and not accumulated_outputs[-1].get("blocked") and not accumulated_outputs[-1].get("sub_harness"):
            accumulated_outputs[-1]["text"] += text
        else:
            accumulated_outputs.append({"id": len(accumulated_outputs), "agent": agent, "text": text, "tools": [], "blocked": []})
    elif msg_type == "tool":
        agent = data.get("agent", "system")
        tool_entry = {"name": data.get("name", ""), "result": data.get("result", "")}
        if accumulated_outputs and accumulated_outputs[-1]["agent"] == agent:
            accumulated_outputs[-1].setdefault("tools", []).append(tool_entry)
        else:
            accumulated_outputs.append({"id": len(accumulated_outputs), "agent": agent, "text": "", "tools": [tool_entry], "blocked": []})
    elif msg_type == "blocked":
        agent = data.get("agent", "system")
        blocked_entry = {"name": data.get("tool", ""), "reason": data.get("reason", "")}
        if accumulated_outputs and accumulated_outputs[-1]["agent"] == agent:
            accumulated_outputs[-1].setdefault("blocked", []).append(blocked_entry)
        else:
            accumulated_outputs.append({"id": len(accumulated_outputs), "agent": agent, "text": "", "tools": [], "blocked": [blocked_entry]})
    elif msg_type == "error":
        accumulated_outputs.append({"id": len(accumulated_outputs), "agent": "system", "text": f"\u274c {data.get('message', '')}", "tools": [], "blocked": []})
    elif msg_type == "sub_harness_start":
        # 子 Harness 开始：创建一个新气泡，包含嵌套子 session
        accumulated_outputs.append({
            "id": len(accumulated_outputs),
            "agent": data.get("parent_agent", "system"),
            "text": "",
            "tools": [],
            "blocked": [],
            "sub_harness": {
                "harness_id": data.get("harness_id", ""),
                "harness_name": data.get("harness_name", ""),
                "slots": data.get("slots", {}),
                "messages": [],
                "status": "running",
            }
        })
    elif msg_type == "sub_token":
        # 子 Harness token：追加到最近的 sub_harness 气泡中
        harness_id = data.get("harness_id", "")
        agent = data.get("agent", "unknown")
        text = data.get("text", "")
        # 找到对应的 sub_harness 气泡
        for output in reversed(accumulated_outputs):
            sh = output.get("sub_harness")
            if sh and sh["harness_id"] == harness_id:
                msgs = sh["messages"]
                if msgs and msgs[-1]["agent"] == agent and not msgs[-1].get("tools"):
                    msgs[-1]["text"] += text
                else:
                    msgs.append({"agent": agent, "text": text, "tools": []})
                break
    elif msg_type == "sub_tool":
        # 子 Harness 工具调用
        harness_id = data.get("harness_id", "")
        agent = data.get("agent", "system")
        tool_entry = {"name": data.get("name", ""), "result": data.get("result", "")}
        for output in reversed(accumulated_outputs):
            sh = output.get("sub_harness")
            if sh and sh["harness_id"] == harness_id:
                msgs = sh["messages"]
                if msgs and msgs[-1]["agent"] == agent:
                    msgs[-1].setdefault("tools", []).append(tool_entry)
                else:
                    msgs.append({"agent": agent, "text": "", "tools": [tool_entry]})
                break
    elif msg_type == "sub_harness_end":
        # 子 Harness 结束
        harness_id = data.get("harness_id", "")
        for output in reversed(accumulated_outputs):
            sh = output.get("sub_harness")
            if sh and sh["harness_id"] == harness_id:
                sh["status"] = "completed"
                break

    msg = json.dumps({"type": msg_type, "data": data})
    for client in list(ws_clients):
        try:
            client.send(msg)
        except Exception:
            ws_clients.discard(client)


def _find_env_dirs():
    """扫描所有 environment 目录：统一目录 + 兼容旧路径"""
    result = []
    # 统一目录：environment/<name>/ 每个子目录就是一个 environment
    if ENVIRONMENT_DIR.exists():
        for d in sorted(ENVIRONMENT_DIR.iterdir()):
            if d.is_dir() and (d / "tools").exists():
                result.append(str(d))
    # 兼容旧的 .environment 路径
    for d in _LEGACY_ENV_DIRS:
        if d.exists() and str(d) not in result:
            result.append(str(d))
    return result


def _get_identity_skills(identity_name):
    skills_dir = IDENTITY_DIR / identity_name / "ego" / "skills"
    if not skills_dir.exists():
        return []
    result = []
    for sd in sorted(skills_dir.iterdir()):
        if sd.is_dir() and (sd / "meta.json").exists():
            result.append(sd.name)
    return result


def _get_identity_knowledge(identity_name):
    knowledge_dir = IDENTITY_DIR / identity_name / "ego" / "knowledge"
    if not knowledge_dir.exists():
        return []
    result = []
    for kd in sorted(knowledge_dir.iterdir()):
        if kd.is_dir() and (kd / "meta.json").exists():
            result.append(kd.name)
    return result


def _get_env_tools(env_path_str):
    tools_dir = Path(env_path_str) / "tools"
    if not tools_dir.exists():
        return []
    result = []
    for td in sorted(tools_dir.iterdir()):
        if td.is_dir() and (td / "meta.json").exists():
            result.append(td.name)
    return result


def _get_env_knowledge(env_path_str):
    knowledge_dir = Path(env_path_str) / "knowledge"
    if not knowledge_dir.exists():
        return []
    result = []
    for kd in sorted(knowledge_dir.iterdir()):
        if kd.is_dir() and (kd / "meta.json").exists():
            result.append(kd.name)
    return result


class APIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, msg, status=400):
        self._send_json({"error": msg}, status)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ==================== GET ====================

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/api/harnesses":
            harnesses = [
                d.name for d in HARNESS_DIR.iterdir()
                if d.is_dir() and (d / "config.json").exists()
            ]
            self._send_json(sorted(harnesses))

        elif path.startswith("/api/harness/"):
            name = unquote(path.split("/api/harness/", 1)[1])
            config_path = HARNESS_DIR / name / "config.json"
            if not config_path.exists():
                self._send_error(f"Harness not found: {name}", 404)
                return
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self._send_json(config)

        elif path == "/api/identities":
            identities = [
                d.name for d in IDENTITY_DIR.iterdir()
                if d.is_dir() and (d / "id.json").exists()
            ]
            self._send_json(sorted(identities))

        elif path.startswith("/api/identity/") and not any(
            x in path for x in ["/skill/", "/knowledge/", "/superego"]
        ):
            name = unquote(path.split("/api/identity/", 1)[1])
            id_path = IDENTITY_DIR / name / "id.json"
            if not id_path.exists():
                self._send_error(f"Identity not found: {name}", 404)
                return

            id_data = json.loads(id_path.read_text(encoding="utf-8"))

            superego_path = IDENTITY_DIR / name / "superego" / "config.json"
            superego = None
            if superego_path.exists():
                superego = json.loads(superego_path.read_text(encoding="utf-8"))

            self._send_json({
                "name": name,
                "id": id_data,
                "superego": superego,
                "skills": _get_identity_skills(name),
                "knowledge": _get_identity_knowledge(name),
            })

        elif "/superego" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            name = parts[name_idx]
            superego_path = IDENTITY_DIR / name / "superego" / "config.json"
            if superego_path.exists():
                self._send_json(json.loads(superego_path.read_text(encoding="utf-8")))
            else:
                self._send_json({})

        elif "/skill/" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            skill_idx = parts.index("skill") + 1
            name = parts[name_idx]
            sname = parts[skill_idx]

            meta_path = IDENTITY_DIR / name / "ego" / "skills" / sname / "meta.json"
            if not meta_path.exists():
                self._send_error(f"Skill not found: {sname}", 404)
                return

            meta = json.loads(meta_path.read_text(encoding="utf-8"))

            scripts = {}
            scripts_dir = IDENTITY_DIR / name / "ego" / "skills" / sname / "scripts"
            if scripts_dir.exists():
                for sf in scripts_dir.iterdir():
                    if sf.suffix == ".py":
                        scripts[sf.name] = sf.read_text(encoding="utf-8")

            self._send_json({"meta": meta, "scripts": scripts})

        elif "/knowledge/" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            know_idx = parts.index("knowledge") + 1
            name = parts[name_idx]
            kname = parts[know_idx]

            meta_path = IDENTITY_DIR / name / "ego" / "knowledge" / kname / "meta.json"
            if not meta_path.exists():
                self._send_error(f"Knowledge not found: {kname}", 404)
                return

            meta = json.loads(meta_path.read_text(encoding="utf-8"))

            content = ""
            content_dir = IDENTITY_DIR / name / "ego" / "knowledge" / kname
            for cf in content_dir.iterdir():
                if cf.suffix == ".txt":
                    content = cf.read_text(encoding="utf-8")
                    break

            self._send_json({"meta": meta, "content": content})

        elif path == "/api/environments":
            envs = _find_env_dirs()
            result = []
            for ep in envs:
                epath = Path(ep)
                result.append({
                    "path": ep,
                    "path_b64": base64.urlsafe_b64encode(ep.encode()).decode(),
                    "name": epath.parent.name if epath.name == ".environment" else epath.name,
                    "tools": _get_env_tools(ep),
                    "knowledge": _get_env_knowledge(ep),
                })
            self._send_json(result)

        elif "/tool/" in path and path.startswith("/api/environment/"):
            parts = path.split("/")
            env_idx = parts.index("environment") + 1
            tool_idx = parts.index("tool") + 1
            path_b64 = unquote(parts[env_idx])
            tname = unquote(parts[tool_idx])

            try:
                ep = base64.urlsafe_b64decode(path_b64.encode()).decode()
            except Exception:
                self._send_error("Invalid path encoding", 400)
                return

            meta_path = Path(ep) / "tools" / tname / "meta.json"
            if not meta_path.exists():
                self._send_error(f"Tool not found: {tname}", 404)
                return

            meta = json.loads(meta_path.read_text(encoding="utf-8"))

            scripts = {}
            scripts_dir = Path(ep) / "tools" / tname / "scripts"
            if scripts_dir.exists():
                for sf in scripts_dir.iterdir():
                    if sf.suffix == ".py":
                        scripts[sf.name] = sf.read_text(encoding="utf-8")

            self._send_json({"meta": meta, "scripts": scripts})

        elif "/knowledge/" in path and path.startswith("/api/environment/"):
            parts = path.split("/")
            env_idx = parts.index("environment") + 1
            know_idx = parts.index("knowledge") + 1
            path_b64 = unquote(parts[env_idx])
            kname = unquote(parts[know_idx])

            try:
                ep = base64.urlsafe_b64decode(path_b64.encode()).decode()
            except Exception:
                self._send_error("Invalid path encoding", 400)
                return

            kdir = Path(ep) / "knowledge" / kname
            if not kdir.exists():
                self._send_error(f"Knowledge not found: {kname}", 404)
                return

            meta = {}
            meta_path = kdir / "meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))

            content = ""
            for cf in kdir.iterdir():
                if cf.suffix in (".md", ".txt"):
                    content = cf.read_text(encoding="utf-8")
                    break

            self._send_json({"meta": meta, "content": content})

        elif path.startswith("/api/environment/"):
            path_b64 = unquote(path.split("/api/environment/", 1)[1])
            try:
                ep = base64.urlsafe_b64decode(path_b64.encode()).decode()
            except Exception:
                self._send_error("Invalid path encoding", 400)
                return

            epath = Path(ep)
            if not epath.exists():
                self._send_error(f"Environment not found: {ep}", 404)
                return

            self._send_json({
                "path": ep,
                "path_b64": path_b64,
                "tools": _get_env_tools(ep),
                "knowledge": _get_env_knowledge(ep),
            })

        elif path == "/api/sessions":
            sessions = []
            if SESSIONS_DIR.is_dir():
                for d in sorted(SESSIONS_DIR.iterdir(), key=lambda x: x.name, reverse=True):
                    if not d.is_dir():
                        continue
                    info = {"name": d.name, "path": str(d)}
                    msgs_file = d / "messages.json"
                    if msgs_file.exists():
                        try:
                            msgs = json.loads(msgs_file.read_text(encoding="utf-8"))
                            info["message_count"] = len(msgs)
                        except:
                            info["message_count"] = 0
                    else:
                        info["message_count"] = 0
                    sessions.append(info)
            self._send_json(sessions[:50])

        elif path.startswith("/api/session/") and path.endswith("/cached-report"):
            name = path.split("/api/session/", 1)[1].rsplit("/cached-report", 1)[0]
            name = unquote(name)
            # 查找 sessions 目录中是否有对该 session 的分析结果
            # 分析结果保存在 session_analyzer 的 session 目录下
            report = None
            for sd in sorted(SESSIONS_DIR.iterdir(), key=lambda x: x.name, reverse=True):
                if not sd.is_dir():
                    continue
                msgs_file = sd / "messages.json"
                if msgs_file.exists():
                    try:
                        msgs = json.loads(msgs_file.read_text(encoding="utf-8"))
                        # 检查是否有对目标 session 的分析（第一条 user 消息包含 session 名）
                        if len(msgs) >= 2 and name in str(msgs[0].get("content", "")):
                            # 找最后一条 assistant 消息作为 report
                            for m in reversed(msgs):
                                if m.get("role") == "assistant" and m.get("content") and len(m["content"]) > 50:
                                    report = m["content"]
                                    break
                            if report:
                                break
                    except:
                        pass
            if report:
                self._send_json({"report": report, "session_name": name})
            else:
                self._send_json({})

        elif path.startswith("/api/session/") and path.endswith("/evaluate"):
            name = path.split("/api/session/", 1)[1].rsplit("/evaluate", 1)[0]
            name = unquote(name)
            session_dir = SESSIONS_DIR / name
            if not session_dir.is_dir():
                self._send_error(f"Session not found: {name}", 404)
                return
            import sys
            eval_script = IDENTITY_DIR / "dante" / "ego" / "skills" / "evaluate_session" / "scripts"
            sys.path.insert(0, str(eval_script))
            try:
                from evaluate_session import evaluate_session
                report = evaluate_session(str(session_dir))
                self._send_json({"report": report, "session_name": name})
            finally:
                sys.path.pop(0)

        elif path.startswith("/api/session/") and path.endswith("/messages"):
            name = path.split("/api/session/", 1)[1].rsplit("/messages", 1)[0]
            name = unquote(name)
            msgs_file = SESSIONS_DIR / name / "messages.json"
            if not msgs_file.exists():
                self._send_error(f"Session messages not found: {name}", 404)
                return
            msgs = json.loads(msgs_file.read_text(encoding="utf-8"))
            self._send_json(msgs)

        elif path == "/api/execution/state":
            self._send_json({
                **execution_state,
                "outputs": accumulated_outputs,
            })

        elif path.startswith("/api/analyze-status/"):
            task_id = path.split("/")[-1]
            if task_id not in _async_tasks:
                self._send_error("Task not found", 404)
                return
            task = _async_tasks[task_id]
            response = {"task_id": task_id, "status": task["status"]}
            if task.get("progress"):
                response["progress"] = task["progress"]
            if task["status"] == "completed":
                response["result"] = task["result"]
            elif task["status"] == "error":
                response["error"] = task["error"]
            self._send_json(response)

        else:
            # Serve static files from dist/
            dist_dir = Path(__file__).resolve().parent / "dist"
            # Map / to /index.html
            file_path = path.lstrip("/") or "index.html"
            full_path = dist_dir / file_path
            # SPA fallback: if not found, serve index.html
            if not full_path.exists() or not full_path.is_file():
                full_path = dist_dir / "index.html"
            if full_path.exists() and full_path.is_file():
                content = full_path.read_bytes()
                content_type = "text/html"
                suffix = full_path.suffix.lower()
                mime_map = {
                    ".js": "application/javascript",
                    ".css": "text/css",
                    ".json": "application/json",
                    ".svg": "image/svg+xml",
                    ".png": "image/png",
                    ".ico": "image/x-icon",
                    ".woff2": "font/woff2",
                    ".woff": "font/woff",
                    ".ttf": "font/ttf",
                }
                content_type = mime_map.get(suffix, "text/html")
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(content)
            else:
                self._send_error("Not found", 404)

    # ==================== PUT ====================

    def do_PUT(self):
        path = urlparse(self.path).path

        if path.startswith("/api/harness/"):
            name = unquote(path.split("/api/harness/", 1)[1])
            config_dir = HARNESS_DIR / name
            config_dir.mkdir(parents=True, exist_ok=True)
            config_path = config_dir / "config.json"

            data = self._read_body()
            config_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._send_json({"ok": True, "name": name})

        elif path.startswith("/api/identity/") and not any(
            x in path for x in ["/skill/", "/knowledge/", "/superego", "/clone"]
        ):
            name = unquote(path.split("/api/identity/", 1)[1])
            identity_dir = IDENTITY_DIR / name
            identity_dir.mkdir(parents=True, exist_ok=True)
            (identity_dir / "ego" / "skills").mkdir(parents=True, exist_ok=True)
            (identity_dir / "ego" / "knowledge").mkdir(parents=True, exist_ok=True)
            (identity_dir / "superego").mkdir(parents=True, exist_ok=True)

            data = self._read_body()
            id_path = identity_dir / "id.json"
            id_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._send_json({"ok": True, "name": name})

        elif "/superego" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            name = parts[name_idx]

            identity_dir = IDENTITY_DIR / name
            identity_dir.mkdir(parents=True, exist_ok=True)
            (identity_dir / "superego").mkdir(parents=True, exist_ok=True)

            data = self._read_body()
            superego_path = identity_dir / "superego" / "config.json"
            superego_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self._send_json({"ok": True})

        elif "/skill/" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            skill_idx = parts.index("skill") + 1
            name = parts[name_idx]
            sname = parts[skill_idx]

            skill_dir = IDENTITY_DIR / name / "ego" / "skills" / sname
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)

            data = self._read_body()
            meta = data.get("meta", {})
            scripts = data.get("scripts", {})

            (skill_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            for script_name, script_content in scripts.items():
                (skill_dir / "scripts" / script_name).write_text(
                    script_content, encoding="utf-8"
                )

            self._send_json({"ok": True})

        elif "/knowledge/" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            know_idx = parts.index("knowledge") + 1
            name = parts[name_idx]
            kname = parts[know_idx]

            know_dir = IDENTITY_DIR / name / "ego" / "knowledge" / kname
            know_dir.mkdir(parents=True, exist_ok=True)

            data = self._read_body()
            meta = data.get("meta", {})
            content = data.get("content", "")

            (know_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (know_dir / f"{kname}.txt").write_text(content, encoding="utf-8")

            self._send_json({"ok": True})

        elif "/tool/" in path and path.startswith("/api/environment/"):
            parts = path.split("/")
            env_idx = parts.index("environment") + 1
            tool_idx = parts.index("tool") + 1
            path_b64 = parts[env_idx]
            tname = parts[tool_idx]

            try:
                ep = base64.urlsafe_b64decode(path_b64.encode()).decode()
            except Exception:
                self._send_error("Invalid path encoding", 400)
                return

            tool_dir = Path(ep) / "tools" / tname
            tool_dir.mkdir(parents=True, exist_ok=True)
            (tool_dir / "scripts").mkdir(parents=True, exist_ok=True)

            data = self._read_body()
            meta = data.get("meta", {})
            scripts = data.get("scripts", {})

            (tool_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            for script_name, script_content in scripts.items():
                (tool_dir / "scripts" / script_name).write_text(
                    script_content, encoding="utf-8"
                )

            self._send_json({"ok": True})

        elif "/knowledge/" in path and path.startswith("/api/environment/"):
            parts = path.split("/")
            env_idx = parts.index("environment") + 1
            know_idx = parts.index("knowledge") + 1
            path_b64 = parts[env_idx]
            kname = parts[know_idx]

            try:
                ep = base64.urlsafe_b64decode(path_b64.encode()).decode()
            except Exception:
                self._send_error("Invalid path encoding", 400)
                return

            know_dir = Path(ep) / "knowledge" / kname
            know_dir.mkdir(parents=True, exist_ok=True)

            data = self._read_body()
            meta = data.get("meta", {})
            content = data.get("content", "")

            (know_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (know_dir / f"{kname}.txt").write_text(content, encoding="utf-8")

            self._send_json({"ok": True})

        else:
            self._send_error("Not found", 404)

    # ==================== POST ====================

    def do_POST(self):
        global exec_input_queue
        path = urlparse(self.path).path

        if path == "/api/execution/start":
            data = self._read_body()
            harness_name = data.get("harness", "")
            agents = data.get("agents", {})

            config_path = HARNESS_DIR / harness_name / "config.json"
            if not config_path.exists():
                self._send_error(f"Harness not found: {harness_name}", 404)
                return

            if execution_state["running"]:
                self._send_error("Already running", 409)
                return

            execution_state["running"] = True
            execution_state["current_node"] = None
            execution_state["step_count"] = 0
            execution_state["messages_count"] = 0
            accumulated_outputs.clear()
            notify_clients(execution_state)

            thread = threading.Thread(
                target=_run_harness_in_thread,
                args=(harness_name, agents),
                daemon=True,
            )
            thread.start()

            self._send_json({"ok": True})

        elif path == "/api/execution/stop":
            execution_state["running"] = False
            execution_state["current_node"] = None
            # 清空 input queue 防止残留消息污染下次执行
            if exec_input_queue is not None:
                while not exec_input_queue.empty():
                    try:
                        exec_input_queue.get_nowait()
                    except Exception:
                        break
            notify_clients(execution_state)
            self._send_json({"ok": True})

        elif path == "/api/execution/input":
            data = self._read_body()
            text = data.get("text", "")
            if exec_input_queue is not None:
                exec_input_queue.put(text)
                self._send_json({"ok": True})
            else:
                self._send_error("No execution running", 400)

        elif path == "/api/environments":
            data = self._read_body()
            name = data.get("name", "").strip()
            if not name:
                self._send_error("名称不能为空", 400)
                return
            # 在统一的 environment/ 目录下创建
            env_dir = ENVIRONMENT_DIR / name
            if env_dir.exists():
                self._send_error(f"Environment 已存在: {name}", 409)
                return
            env_dir.mkdir(parents=True, exist_ok=True)
            (env_dir / "tools").mkdir(exist_ok=True)
            (env_dir / "knowledge").mkdir(exist_ok=True)
            self._send_json({"ok": True, "name": name, "path": str(env_dir)})

        elif "/clone" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            name = parts[name_idx]

            data = self._read_body()
            new_name = data.get("new_name", f"{name}_copy")

            src = IDENTITY_DIR / name
            dst = IDENTITY_DIR / new_name

            if dst.exists():
                self._send_error(f"Identity already exists: {new_name}", 409)
                return

            shutil.copytree(str(src), str(dst))
            self._send_json({"ok": True, "name": new_name})

        elif path.startswith("/api/identity/") and path.endswith("/modify"):
            name = path.split("/api/identity/", 1)[1].rsplit("/modify", 1)[0]
            name = unquote(name)
            body = self._read_body()
            field = body.get("field", "")
            value = body.get("value", "")
            if not field or not value:
                self._send_error("Missing 'field' or 'value'")
                return
            import sys
            mod_script = IDENTITY_DIR / "dante" / "ego" / "skills" / "modify_identity" / "scripts"
            sys.path.insert(0, str(mod_script))
            try:
                from modify_identity import modify_identity
                result = modify_identity(name, field, value)
                self._send_json({"result": result})
            finally:
                sys.path.pop(0)

        elif path == "/api/analyze-session":
            body = self._read_body()
            target_session = body.get("session", "")
            target_harness = body.get("harness", "session_analyzer")
            target_identity = body.get("identity", "dante")
            
            if not target_session:
                self._send_error("Missing 'session' field")
                return

            harness_path = HARNESS_DIR / target_harness
            if not harness_path.exists():
                self._send_error(f"Harness '{target_harness}' not found")
                return

            identity_path = IDENTITY_DIR / target_identity
            if not identity_path.exists():
                self._send_error(f"Identity '{target_identity}' not found")
                return

            task_id = str(_uuid.uuid4())[:8]
            _async_tasks[task_id] = {"status": "running", "result": None, "error": None}

            def _run_analyze():
                import sys
                project_root = Path(__file__).resolve().parent.parent
                sys.path.insert(0, str(project_root))
                try:
                    from agent import Agent
                    from harness import Harness, set_current_harness
                    import json as _json

                    hconfig = _json.loads((harness_path / "config.json").read_text())
                    slots = hconfig.get("slots", {})
                    slot_name = list(slots.keys())[0] if slots else "agent"

                    agent = Agent(str(identity_path), name=slot_name)
                    harness = Harness(str(harness_path), agents={slot_name: agent})
                    harness._non_interactive = True
                    set_current_harness(harness)

                    initial_msg = {
                        "role": "user",
                        "content": (
                            f"Analyze the session at sessions/{target_session}. "
                            f"Use evaluate_session to get metrics, then provide a structured analysis report "
                            f"covering: what the agent attempted, what went well, what went wrong, root causes, "
                            f"and concrete improvement suggestions."
                        )
                    }
                    harness.session.record(initial_msg)
                    harness.session.record_full(initial_msg)

                    harness.run_func(harness)
                    set_current_harness(None)

                    messages = harness.session.messages
                    final_summary = ""
                    for msg in reversed(messages):
                        if msg.get("role") == "assistant" and "<tool_call>" not in msg.get("content", ""):
                            final_summary = msg.get("content", "")
                            break

                    harness.session.save()

                    _async_tasks[task_id] = {
                        "status": "completed",
                        "result": {
                            "steps": len(messages),
                            "summary": final_summary,
                            "target_session": target_session,
                            "harness_used": target_harness,
                            "identity_used": target_identity,
                            "saved_to": str(harness.session.save_dir),
                            "messages": messages,
                        },
                        "error": None,
                    }
                except Exception as e:
                    try:
                        set_current_harness(None)
                    except:
                        pass
                    _async_tasks[task_id] = {
                        "status": "error",
                        "result": None,
                        "error": str(e),
                    }
                finally:
                    if str(project_root) in sys.path:
                        sys.path.remove(str(project_root))

            t = threading.Thread(target=_run_analyze, daemon=True)
            t.start()
            self._send_json({"task_id": task_id, "status": "running"})

        elif path == "/api/evolution/start":
            body = self._read_body()
            target_harness = body.get("harness", "react_single")
            target_identity = body.get("identity", "dante")
            max_iterations = body.get("iterations", 3)
            mode = body.get("mode", "engine")

            task_id = str(_uuid.uuid4())[:8]
            _async_tasks[task_id] = {"status": "running", "result": None, "error": None}

            def _run_evolution():
                import sys as _sys
                project_root = Path(__file__).resolve().parent.parent
                _sys.path.insert(0, str(project_root))

                def _progress_cb(step, detail):
                    _async_tasks[task_id]["progress"] = step + (f" — {detail}" if detail else "")

                try:
                    if mode == "harness":
                        _run_evolution_harness(task_id, target_harness, target_identity, int(max_iterations), _progress_cb)
                    else:
                        from self_evolution.engine import run_evolution_cycle
                        report = run_evolution_cycle(
                            target_harness=target_harness,
                            target_identity=target_identity,
                            max_iterations=int(max_iterations),
                            verbose=True,
                            progress_callback=_progress_cb,
                        )
                        _async_tasks[task_id] = {"status": "completed", "result": report, "error": None}
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    _async_tasks[task_id] = {"status": "error", "result": None, "error": str(e)}

            t = threading.Thread(target=_run_evolution, daemon=True)
            t.start()
            self._send_json({"task_id": task_id, "status": "running"})

        elif path == "/api/evolution/principles":
            body = self._read_body()
            query = body.get("query", "general improvement")
            top_k = body.get("top_k", 5)
            import sys as _sys
            project_root = Path(__file__).resolve().parent.parent
            _sys.path.insert(0, str(project_root))
            from self_evolution.engine import retrieve_principles, _load_json, PRINCIPLES_FILE
            principles = _load_json(PRINCIPLES_FILE)
            self._send_json({"principles": principles})

        elif path == "/api/evolution/archive":
            body = self._read_body()
            target = body.get("target", "")
            limit = body.get("limit", 20)
            import sys as _sys
            project_root = Path(__file__).resolve().parent.parent
            _sys.path.insert(0, str(project_root))
            from self_evolution.engine import get_history, get_best_configs, _load_json, ARCHIVE_FILE
            archive = _load_json(ARCHIVE_FILE)
            self._send_json({"archive": archive, "total": len(archive)})

        else:
            self._send_error("Not found", 404)

    # ==================== DELETE ====================

    def do_DELETE(self):
        path = urlparse(self.path).path

        if path.startswith("/api/identity/") and not any(
            x in path for x in ["/skill/", "/knowledge/"]
        ):
            name = unquote(path.split("/api/identity/", 1)[1])
            identity_dir = IDENTITY_DIR / name
            if not identity_dir.exists():
                self._send_error(f"Identity not found: {name}", 404)
                return
            shutil.rmtree(str(identity_dir))
            self._send_json({"ok": True})

        elif "/skill/" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            skill_idx = parts.index("skill") + 1
            name = parts[name_idx]
            sname = parts[skill_idx]

            skill_dir = IDENTITY_DIR / name / "ego" / "skills" / sname
            if skill_dir.exists():
                shutil.rmtree(str(skill_dir))
            self._send_json({"ok": True})

        elif "/knowledge/" in path and path.startswith("/api/identity/"):
            parts = path.split("/")
            name_idx = parts.index("identity") + 1
            know_idx = parts.index("knowledge") + 1
            name = parts[name_idx]
            kname = parts[know_idx]

            know_dir = IDENTITY_DIR / name / "ego" / "knowledge" / kname
            if know_dir.exists():
                shutil.rmtree(str(know_dir))
            self._send_json({"ok": True})

        elif "/tool/" in path and path.startswith("/api/environment/"):
            parts = path.split("/")
            env_idx = parts.index("environment") + 1
            tool_idx = parts.index("tool") + 1
            path_b64 = parts[env_idx]
            tname = parts[tool_idx]

            try:
                ep = base64.urlsafe_b64decode(path_b64.encode()).decode()
            except Exception:
                self._send_error("Invalid path encoding", 400)
                return

            tool_dir = Path(ep) / "tools" / tname
            if tool_dir.exists():
                shutil.rmtree(str(tool_dir))
            self._send_json({"ok": True})

        elif "/knowledge/" in path and path.startswith("/api/environment/"):
            parts = path.split("/")
            env_idx = parts.index("environment") + 1
            know_idx = parts.index("knowledge") + 1
            path_b64 = parts[env_idx]
            kname = parts[know_idx]

            try:
                ep = base64.urlsafe_b64decode(path_b64.encode()).decode()
            except Exception:
                self._send_error("Invalid path encoding", 400)
                return

            know_dir = Path(ep) / "knowledge" / kname
            if know_dir.exists():
                shutil.rmtree(str(know_dir))
            self._send_json({"ok": True})

        else:
            self._send_error("Not found", 404)


def _run_evolution_harness(task_id, target_harness, target_identity, max_iterations, progress_cb):
    """Run evolution cycle using the harness pipeline (DAG mode)."""
    import sys as _sys
    project_root = Path(__file__).resolve().parent.parent
    _sys.path.insert(0, str(project_root))
    os.chdir(str(project_root))

    from agent import Agent
    from harness import Harness
    from pipeline_engine import run_pipeline

    progress_cb("[1/3] Loading evolution_cycle harness...", "")

    # Load the evolution_cycle harness
    evo_harness_dir = HARNESS_DIR / "evolution_cycle"
    harness = Harness(str(evo_harness_dir))

    # Override context with user parameters
    pipeline = harness.config["pipeline"]
    ctx = pipeline.get("context", {})
    ctx["target_harness"] = target_harness
    ctx["target_identity"] = target_identity
    ctx["max_iterations"] = max_iterations
    pipeline["context"] = ctx

    # Assign a minimal evolver agent (provides LLM access for llm_call nodes)
    identity_dir = project_root / "identity" / target_identity
    if identity_dir.exists():
        agent = Agent(str(identity_dir), name="evolver")
    else:
        # Fallback: use first available identity
        identity_dir = project_root / "identity" / "dante"
        agent = Agent(str(identity_dir), name="evolver")
    harness.agents["evolver"] = agent

    # Run non-interactively
    harness._non_interactive = True
    progress_cb("[2/3] Running evolution pipeline...", f"target={target_harness}/{target_identity}")

    run_pipeline(harness)

    progress_cb("[3/3] Collecting report...", "")

    # Extract the report from the final context
    # The pipeline stores results in context via scripts;
    # we need to read the latest report file from DATA_DIR
    from self_evolution.engine import DATA_DIR, _load_json
    import glob as _glob

    report_files = sorted(_glob.glob(str(DATA_DIR / "report_*.json")), reverse=True)
    if report_files:
        report = _load_json(Path(report_files[0]))
    else:
        # Fallback: construct minimal report
        report = {
            "target_harness": target_harness,
            "target_identity": target_identity,
            "initial_score": 0.0,
            "final_score": 0.0,
            "total_accepted": 0,
            "total_rejected": 0,
            "total_rollbacks": 0,
            "iterations": [],
        }

    _async_tasks[task_id] = {"status": "completed", "result": report, "error": None}


def _run_harness_in_thread(harness_name, agents_dict):
    global execution_state, exec_input_queue, exec_ws_client

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    # 切换工作目录到项目根，确保工具中的相对路径正确解析
    os.chdir(str(Path(__file__).resolve().parent.parent))

    from agent import Agent
    from harness import Harness, set_output_callback, set_current_harness
    from pipeline_engine import run_pipeline_stream

    # 设置全局 output 回调，子 harness 也能通过此推送事件
    set_output_callback(notify_output)

    exec_input_queue = queue.Queue()
    print(f"[exec] exec_input_queue created, starting pipeline for harness={harness_name}, agents={agents_dict}")

    try:
        root = Path(__file__).resolve().parent.parent
        agents = {}
        for slot_name, identity_path in agents_dict.items():
            full_path = str(root / identity_path)
            agents[slot_name] = Agent(full_path, name=slot_name)
            print(f"[exec] Agent loaded: {slot_name} -> {full_path}")

        harness = Harness(str(HARNESS_DIR / harness_name), agents)
        # 覆盖 session save_dir 到项目根的 sessions/ 目录
        import time as _time
        session_dir = root / "sessions" / f"{harness_name}_{_time.strftime('%Y%m%d_%H%M%S')}"
        harness.session.save_dir = session_dir
        # 设置为当前 harness，使 LLM IO 日志能自动记录
        set_current_harness(harness)
        print(f"[exec] Harness loaded, pipeline start={harness.config['pipeline']['start']}")

        def on_output(msg_type, data):
            notify_output(msg_type, data)
            if msg_type == "node_enter":
                execution_state["current_node"] = data.get("node_id", "")
                execution_state["step_count"] = execution_state.get("step_count", 0) + 1
                notify_clients(execution_state)

        def get_input():
            try:
                return exec_input_queue.get(timeout=3600)
            except queue.Empty:
                return None

        def is_running():
            return execution_state["running"]

        run_pipeline_stream(harness, on_output, get_input, is_running)

    except Exception as e:
        notify_output("error", {"message": str(e)})
        import traceback
        traceback.print_exc()
    finally:
        # 保存 session 记录
        try:
            harness.session.save()
            print(f"[exec] Session saved to {harness.session.save_dir}")
        except Exception:
            pass
        set_current_harness(None)
        execution_state["running"] = False
        execution_state["current_node"] = None
        exec_input_queue = None
        exec_ws_client = None
        notify_output("done", {})
        notify_clients(execution_state)


class WebSocketHandler:
    def __init__(self, sock):
        self.sock = sock

    def send(self, data):
        try:
            frame = data.encode("utf-8")
            header = bytearray()
            header.append(0x81)
            length = len(frame)
            if length < 126:
                header.append(length)
            elif length < 65536:
                header.append(126)
                header.extend(length.to_bytes(2, "big"))
            else:
                header.append(127)
                header.extend(length.to_bytes(8, "big"))
            self.sock.send(bytes(header) + frame)
        except Exception:
            pass

    def recv(self):
        try:
            data = self.sock.recv(4096)
            if not data:
                return None
            if len(data) < 2:
                return None
            opcode = data[0] & 0x0F
            if opcode == 0x8:
                return None
            if opcode == 0x9:
                pong = bytearray([0x8A, 0])
                self.sock.send(bytes(pong))
                return None
            mask = data[1] & 0x80
            length = data[1] & 0x7F
            offset = 2
            if length == 126:
                length = int.from_bytes(data[2:4], "big")
                offset = 4
            elif length == 127:
                length = int.from_bytes(data[2:10], "big")
                offset = 10
            if mask:
                mask_key = data[offset:offset + 4]
                offset += 4
                payload = bytearray(data[offset:offset + length])
                for i in range(len(payload)):
                    payload[i] ^= mask_key[i % 4]
                return bytes(payload).decode("utf-8", errors="ignore")
            return data[offset:offset + length].decode("utf-8", errors="ignore")
        except Exception:
            return None


def handle_ws(conn):
    global ws_clients, exec_ws_client
    client = WebSocketHandler(conn)
    ws_clients.add(client)

    exec_ws_client = client

    try:
        client.send(json.dumps(execution_state))
        while True:
            msg = client.recv()
            if msg is None:
                break
            try:
                data = json.loads(msg)
                print(f"[WS] received: {data}")
                if data.get("type") == "input" and exec_input_queue is not None:
                    print(f"[WS] putting input into queue: {data.get('text', '')}")
                    exec_input_queue.put(data.get("text", ""))
            except Exception as e:
                print(f"[WS] error parsing message: {e}")
    except Exception as e:
        print(f"[WS] connection error: {e}")
    finally:
        ws_clients.discard(client)
        if exec_ws_client is client:
            exec_ws_client = None
        conn.close()


def main():
    import socket
    import subprocess
    import signal

    http_port = 8765
    ws_port = 8766

    # Kill any process occupying our ports (works even without fuser/lsof)
    for port in [http_port, ws_port]:
        try:
            # Use /proc/net/tcp to find processes on the port
            port_hex = f"{port:04X}"
            pids_to_kill = set()
            with open("/proc/net/tcp") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 10:
                        local_addr = parts[1]
                        if local_addr.endswith(f":{port_hex}") and parts[3] == "0A":  # LISTEN state
                            inode = parts[9]
                            # Find pid by scanning /proc/*/fd
                            import glob
                            for fd_link in glob.glob("/proc/[0-9]*/fd/*"):
                                try:
                                    target = os.readlink(fd_link)
                                    if f"socket:[{inode}]" in target:
                                        pid = int(fd_link.split("/")[2])
                                        if pid != os.getpid():
                                            pids_to_kill.add(pid)
                                except (PermissionError, FileNotFoundError, ValueError):
                                    pass
            for pid in pids_to_kill:
                try:
                    os.kill(pid, signal.SIGKILL)
                    print(f"[API Server] Killed stale process {pid} on port {port}")
                except ProcessLookupError:
                    pass
            if pids_to_kill:
                import time
                time.sleep(0.5)
        except Exception:
            pass

    httpd = ThreadingHTTPServer(("0.0.0.0", http_port), APIHandler)

    ws_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ws_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ws_sock.bind(("0.0.0.0", ws_port))
    ws_sock.listen(5)

    print(f"[API Server] HTTP: http://localhost:{http_port}")
    print(f"[API Server] WS:   ws://localhost:{ws_port}")
    print(f"[API Server] Harness dir: {HARNESS_DIR}")
    print(f"[API Server] Identity dir: {IDENTITY_DIR}")

    def run_ws():
        while True:
            try:
                conn, addr = ws_sock.accept()
                request = conn.recv(4096).decode("utf-8", errors="ignore")
                if "Upgrade: websocket" in request:
                    key = ""
                    for line in request.split("\r\n"):
                        if line.lower().startswith("sec-websocket-key:"):
                            key = line.split(":", 1)[1].strip()
                            break
                    if key:
                        import hashlib
                        accept = base64.b64encode(
                            hashlib.sha1(
                                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
                            ).digest()
                        ).decode()
                        response = (
                            "HTTP/1.1 101 Switching Protocols\r\n"
                            "Upgrade: websocket\r\n"
                            "Connection: Upgrade\r\n"
                            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                        )
                        conn.send(response.encode())
                        handle_ws(conn)
                    else:
                        conn.close()
                else:
                    conn.close()
            except Exception:
                pass

    ws_thread = threading.Thread(target=run_ws, daemon=True)
    ws_thread.start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[API Server] Shutting down...")


if __name__ == "__main__":
    main()
