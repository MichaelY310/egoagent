from __future__ import annotations

import base64
import copy
import json
import os
import queue
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import websocket


_CHROME_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]

_KEYS = {
    "enter": ("Enter", "Enter", 13),
    "tab": ("Tab", "Tab", 9),
    "escape": ("Escape", "Escape", 27),
    "esc": ("Escape", "Escape", 27),
    "backspace": ("Backspace", "Backspace", 8),
    "delete": ("Delete", "Delete", 46),
    "arrowup": ("ArrowUp", "ArrowUp", 38),
    "arrowdown": ("ArrowDown", "ArrowDown", 40),
    "arrowleft": ("ArrowLeft", "ArrowLeft", 37),
    "arrowright": ("ArrowRight", "ArrowRight", 39),
    "home": ("Home", "Home", 36),
    "end": ("End", "End", 35),
    "pageup": ("PageUp", "PageUp", 33),
    "pagedown": ("PageDown", "PageDown", 34),
    "space": (" ", "Space", 32),
}


class CDPBrowser:
    def __init__(self, workspace: Path, headless: bool = True):
        self.workspace = workspace.resolve()
        self.root = self.workspace / ".egoagent" / "browser"
        self.root.mkdir(parents=True, exist_ok=True)
        self.profile = Path(tempfile.mkdtemp(prefix="egoagent-browser-profile-"))
        self.download_root = self.root / "downloads"
        self.download_root.mkdir(parents=True, exist_ok=True)
        self.port = self._free_port()
        self.headless = bool(headless)
        executables = [path for path in _CHROME_CANDIDATES if path.is_file()]
        if not executables:
            raise RuntimeError("Chrome or Edge is not installed in a supported location")
        executable = executables[0]

        def launch_command(browser_executable: Path) -> list[str]:
            command = [
                str(browser_executable),
                "--disable-gpu",
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-extensions",
                "--disable-sync",
                "--disable-popup-blocking",
                "--metrics-recording-only",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-allow-origins=*",
                "--window-size=1280,900",
                f"--remote-debugging-port={self.port}",
                f"--user-data-dir={self.profile}",
                "about:blank",
            ]
            if self.headless:
                command.insert(1, "--headless=new")
            return command

        popen_options = {}
        if os.name == "nt":
            popen_options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        else:
            popen_options["start_new_session"] = True
        self.process = subprocess.Popen(
            launch_command(executable),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **popen_options,
        )
        self._state_lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._counter = 0
        self._observation_counter = 0
        self._pending: dict[int, queue.Queue] = {}
        self._reader_stop = None
        self._reader = None
        self._load_event = threading.Event()
        self._last_observation = None
        self.pending_dialog = None
        self.downloads_state: dict[str, dict] = {}
        self._download_file_observations: dict[str, tuple[int, int, float]] = {}
        self.target_id = ""
        self.ws = None
        try:
            self._wait_ready()
        except RuntimeError as first_error:
            # A locally installed Chrome channel can be broken or blocked by
            # enterprise policy while Edge remains usable (and vice versa).
            # Retry a different Chromium executable before failing the tool.
            if len(executables) < 2:
                raise
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            shutil.rmtree(self.profile, ignore_errors=True)
            self.profile = Path(tempfile.mkdtemp(prefix="egoagent-browser-profile-"))
            self.port = self._free_port()
            executable = executables[-1]
            self.process = subprocess.Popen(
                launch_command(executable),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **popen_options,
            )
            try:
                self._wait_ready()
            except RuntimeError as fallback_error:
                raise RuntimeError(
                    f"Neither {executables[0].name} nor {executable.name} started: "
                    f"{first_error}; fallback: {fallback_error}"
                ) from fallback_error
        try:
            self._connect_initial_target()
        except RuntimeError as connect_error:
            # A Chromium launcher can expose /json/version briefly and then
            # exit before the first page target is attachable.  Treat target
            # attachment as part of startup readiness and use the alternate
            # installed channel just as _wait_ready does.
            fallback = executables[-1]
            if len(executables) < 2 or executable == fallback:
                raise
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            shutil.rmtree(self.profile, ignore_errors=True)
            self.profile = Path(tempfile.mkdtemp(prefix="egoagent-browser-profile-"))
            self.port = self._free_port()
            executable = fallback
            self.process = subprocess.Popen(
                launch_command(executable),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **popen_options,
            )
            try:
                self._wait_ready()
                self._connect_initial_target()
            except RuntimeError as fallback_error:
                raise RuntimeError(
                    f"Neither browser channel provided a stable page target: "
                    f"{connect_error}; fallback: {fallback_error}"
                ) from fallback_error

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def _wait_ready(self) -> None:
        deadline = time.time() + 15
        last_error = None
        while time.time() < deadline:
            try:
                self._http_json("/json/version")
                return
            except Exception as error:
                last_error = error
                # On Windows chrome.exe can hand the browser off to a child
                # process and let the launcher exit.  The debugging endpoint,
                # rather than the lifetime of that launcher, is authoritative.
                time.sleep(0.1)
        state = f"exit code {self.process.poll()}" if self.process.poll() is not None else "still running"
        raise RuntimeError(f"Browser debugging endpoint did not start ({state}): {last_error}")

    def _http_json(self, path: str, method: str = "GET"):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method)
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _disconnect(self) -> None:
        stop = self._reader_stop
        reader = self._reader
        ws = self.ws
        if stop is not None:
            stop.set()
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=2)
        with self._state_lock:
            for waiter in self._pending.values():
                try:
                    waiter.put_nowait({"_transport_error": "browser target disconnected"})
                except queue.Full:
                    pass
            self._pending.clear()
        self.ws = None
        self._reader = None
        self._reader_stop = None

    def _connect_initial_target(self) -> None:
        """Attach to a stable page target, tolerating Chrome startup races."""

        last_error = None
        for attempt in range(4):
            try:
                targets = self._http_json("/json/list")
                page = next((target for target in targets if target.get("type") == "page"), None)
                if page is None or attempt > 0:
                    page = self._http_json("/json/new?about%3Ablank", method="PUT")
                self._connect(page)
                return
            except Exception as error:
                last_error = error
                self._disconnect()
                time.sleep(0.15 * (attempt + 1))
        raise RuntimeError(f"Could not attach to a stable browser page target: {last_error}")

    def _connect(self, target: dict) -> None:
        self._disconnect()
        self.target_id = str(target["id"])
        ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=2, suppress_origin=True)
        stop = threading.Event()
        self.ws = ws
        self._reader_stop = stop
        self._reader = threading.Thread(
            target=self._reader_loop,
            args=(ws, stop),
            name=f"egoagent-cdp-{self.target_id[:8]}",
            daemon=True,
        )
        self._reader.start()
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.call("DOM.enable")
        download_behavior_configured = False
        try:
            self.call(
                "Browser.setDownloadBehavior",
                {"behavior": "allow", "downloadPath": str(self.download_root), "eventsEnabled": True},
            )
            download_behavior_configured = True
        except RuntimeError:
            pass
        # Some Chromium builds accept the Browser-domain command but apply the
        # setting late or omit its events for a newly attached page target.
        # Configure the page domain too when supported; file reconciliation
        # remains authoritative, so this cannot create a false completion.
        try:
            self.call("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(self.download_root)})
            download_behavior_configured = True
        except RuntimeError:
            if not download_behavior_configured:
                raise

    def _reader_loop(self, ws, stop: threading.Event) -> None:
        transport_error = None
        while not stop.is_set():
            try:
                raw = ws.recv()
                if not raw:
                    continue
                message = json.loads(raw)
                request_id = message.get("id")
                if request_id is not None:
                    with self._state_lock:
                        waiter = self._pending.get(int(request_id))
                    if waiter is not None:
                        try:
                            waiter.put_nowait(message)
                        except queue.Full:
                            pass
                else:
                    self._handle_event(message)
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as error:
                if not stop.is_set():
                    transport_error = str(error)
                break
        if transport_error:
            with self._state_lock:
                for waiter in self._pending.values():
                    try:
                        waiter.put_nowait({"_transport_error": transport_error})
                    except queue.Full:
                        pass

    def _handle_event(self, message: dict) -> None:
        method = message.get("method", "")
        params = message.get("params") or {}
        with self._state_lock:
            if method == "Page.loadEventFired":
                self._load_event.set()
            elif method == "Page.javascriptDialogOpening":
                self.pending_dialog = {
                    "open": True,
                    "type": params.get("type", "alert"),
                    "message": params.get("message", ""),
                    "default_prompt": params.get("defaultPrompt", ""),
                    "url": params.get("url", ""),
                    "requires_decision": True,
                }
                # Chrome pauses the renderer before acknowledging the Input
                # request that opened the dialog. Wake those callers so the
                # tool can return the typed dialog state instead of hanging.
                for waiter in self._pending.values():
                    try:
                        waiter.put_nowait({"_interrupted_by_dialog": True})
                    except queue.Full:
                        pass
            elif method == "Page.javascriptDialogClosed":
                self.pending_dialog = None
            elif method == "Browser.downloadWillBegin":
                guid = str(params.get("guid", ""))
                filename = Path(str(params.get("suggestedFilename") or guid or "download")).name
                self.downloads_state[guid] = {
                    "guid": guid,
                    "url": params.get("url", ""),
                    "suggested_filename": filename,
                    "path": str((self.download_root / filename).resolve()),
                    "state": "in_progress",
                    "received_bytes": 0,
                    "total_bytes": None,
                }
            elif method == "Browser.downloadProgress":
                guid = str(params.get("guid", ""))
                entry = self.downloads_state.setdefault(guid, {"guid": guid, "state": "in_progress"})
                entry.update(
                    {
                        "state": params.get("state", entry.get("state", "in_progress")),
                        "received_bytes": params.get("receivedBytes", entry.get("received_bytes", 0)),
                        "total_bytes": params.get("totalBytes", entry.get("total_bytes")),
                    }
                )

    def call(self, method: str, params: dict | None = None, timeout: float = 30):
        with self._state_lock:
            if self.ws is None:
                raise RuntimeError("browser target is disconnected")
            self._counter += 1
            request_id = self._counter
            waiter = queue.Queue(maxsize=1)
            self._pending[request_id] = waiter
            ws = self.ws
        try:
            with self._send_lock:
                ws.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
            try:
                message = waiter.get(timeout=max(0.1, float(timeout)))
            except queue.Empty as error:
                raise TimeoutError(f"CDP {method} timed out") from error
        finally:
            with self._state_lock:
                self._pending.pop(request_id, None)
        if message.get("_transport_error"):
            raise RuntimeError(f"CDP transport failed: {message['_transport_error']}")
        if message.get("_interrupted_by_dialog"):
            if method.startswith("Input."):
                return {"interruptedByDialog": True}
            raise RuntimeError(f"CDP {method} was interrupted by a JavaScript dialog")
        if "error" in message:
            raise RuntimeError(f"CDP {method} failed: {message['error'].get('message', message['error'])}")
        return message.get("result", {})

    def evaluate(self, expression: str):
        if self.pending_dialog:
            raise RuntimeError("a JavaScript dialog is open; accept or dismiss it before evaluating the page")
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        remote = result.get("result", {})
        if remote.get("subtype") == "error":
            raise RuntimeError(remote.get("description", "JavaScript evaluation failed"))
        return remote.get("value")

    def navigate(self, url: str, wait_seconds: float = 10):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https", "data", "about"}:
            raise ValueError("Only http, https, data and about URLs are supported")
        if self._last_observation is None:
            self.observe()
        self._load_event.clear()
        self.call("Page.navigate", {"url": url})
        self._wait_page_ready(wait_seconds)
        return self.observe()

    def _wait_page_ready(self, timeout: float = 10):
        deadline = time.time() + max(0.0, min(float(timeout), 30.0))
        while time.time() < deadline:
            if self._load_event.wait(0.05):
                return True
            if self.pending_dialog:
                return False
            try:
                if self.evaluate("document.readyState") in {"interactive", "complete"}:
                    return True
            except RuntimeError:
                pass
            time.sleep(0.05)
        return False

    def wait(self, seconds: float):
        time.sleep(max(0.0, min(float(seconds), 30.0)))
        return self.observe()

    def _downloads(self):
        # Browser-domain events are the primary source, but some Chromium
        # builds occasionally omit them (notably under startup/load races or
        # when Page.setDownloadBehavior is the only supported fallback).
        # Reconcile completed files so a real, safely stored download never
        # becomes invisible to the Agent merely because an advisory event was
        # missed. Partial Chrome downloads are deliberately excluded.
        try:
            completed_files = [
                path for path in self.download_root.iterdir()
                if path.is_file() and not path.name.endswith((".crdownload", ".tmp"))
            ]
        except OSError:
            completed_files = []
        with self._state_lock:
            assigned = {
                str(Path(entry["path"]).resolve())
                for entry in self.downloads_state.values()
                if entry.get("path")
            }
            unassigned = [path for path in completed_files if str(path.resolve()) not in assigned]
            pathless = [entry for entry in self.downloads_state.values() if not entry.get("path")]
            for entry in pathless:
                suggested = Path(str(entry.get("suggested_filename") or "")).name
                candidate = next((path for path in unassigned if path.name == suggested), None) if suggested else None
                if candidate is None and entry.get("state") == "completed" and len(unassigned) == 1:
                    candidate = unassigned[0]
                if candidate is not None:
                    entry["path"] = str(candidate.resolve())
                    entry.setdefault("suggested_filename", candidate.name)
                    unassigned.remove(candidate)
            for path in unassigned:
                resolved = str(path.resolve())
                synthetic_guid = "file:" + uuid.uuid5(uuid.NAMESPACE_URL, resolved).hex
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                self.downloads_state[synthetic_guid] = {
                    "guid": synthetic_guid,
                    "url": "",
                    "suggested_filename": path.name,
                    "path": resolved,
                    "state": "in_progress",
                    "received_bytes": size,
                    "total_bytes": size,
                    "reconciled_from_file": True,
                }
            entries = copy.deepcopy(list(self.downloads_state.values()))
        for entry in entries:
            path = Path(entry.get("path", "")) if entry.get("path") else None
            entry["exists"] = bool(path and path.is_file())
            try:
                entry["size"] = path.stat().st_size if path and path.is_file() else None
            except OSError:
                entry["size"] = None
            entry["ready"] = bool(path and self._download_file_ready(path))
            if entry["ready"] and entry.get("state") != "canceled":
                # A readable and stable final file is authoritative even when
                # Chromium omitted its final progress event.
                entry["state"] = "completed"
                with self._state_lock:
                    if entry.get("guid") in self.downloads_state:
                        self.downloads_state[entry["guid"]]["state"] = "completed"
        return entries

    def _download_file_ready(self, path: Path) -> bool:
        """Require a stable, readable final file instead of mere existence."""
        try:
            stat = path.stat()
        except OSError:
            return False
        key = str(path.resolve())
        now = time.monotonic()
        observations = getattr(self, "_download_file_observations", None)
        if observations is None:
            observations = {}
            self._download_file_observations = observations
        previous = observations.get(key)
        signature = (int(stat.st_size), int(stat.st_mtime_ns))
        if previous is None or previous[:2] != signature:
            observations[key] = (*signature, now)
            return False
        if now - previous[2] < 0.1:
            return False
        try:
            with path.open("rb") as stream:
                stream.read(1)
        except OSError:
            return False
        return True

    def _dialog_observation(self):
        observation = copy.deepcopy(self._last_observation) or {
            "url": "",
            "title": "",
            "viewport": {},
            "elements": [],
            "text": "",
        }
        return self._decorate_observation(observation)

    def _decorate_observation(self, observation: dict, include_screenshot: bool = False):
        previous = copy.deepcopy(self._last_observation) or {}
        self._observation_counter += 1
        observation = dict(observation or {})
        observation["kind"] = "browser_observation"
        observation["observation_id"] = self._observation_counter
        observation["timestamp"] = time.time()
        observation["target_id"] = self.target_id
        observation["page_changed"] = bool(
            previous
            and (
                observation.get("url", "") != previous.get("url", "")
                or self.target_id != previous.get("target_id", self.target_id)
            )
        )
        observation["page"] = {
            "url": observation.get("url", ""),
            "title": observation.get("title", ""),
            "ready_state": observation.get("ready_state"),
        }
        observation["dialog"] = copy.deepcopy(self.pending_dialog)
        observation["downloads"] = self._downloads()
        captcha = observation.pop("captcha", None)
        if captcha and captcha.get("detected"):
            observation["blocked"] = {
                "type": "captcha",
                "requires_human": True,
                "evidence": captcha.get("evidence", []),
            }
        elif self.pending_dialog:
            observation["blocked"] = {
                "type": "javascript_dialog",
                "requires_human": False,
                "evidence": [self.pending_dialog.get("message", "")],
            }
        else:
            observation["blocked"] = None
        if include_screenshot:
            shot = self.screenshot()
            observation["screenshot"] = shot
            observation["path"] = shot["path"]
        self._last_observation = copy.deepcopy(observation)
        return observation

    def observe(self, max_chars: int = 12000, include_screenshot: bool = False):
        if self.pending_dialog:
            return self._dialog_observation()
        limit = max(1000, min(int(max_chars), 50000))
        expression = r"""
(() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const candidates = [...document.querySelectorAll('a,button,input,textarea,select,[role="button"],[role="link"],[role="checkbox"],[role="radio"],[role="textbox"],[tabindex]')].filter(visible).slice(0, 250);
  window.__egoagentElements = candidates;
  const elements = candidates.map((el, index) => {
    const r = el.getBoundingClientRect();
    return {
      index,
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      type: el.getAttribute('type') || '',
      text: (el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').trim().slice(0, 300),
      aria_label: el.getAttribute('aria-label') || '',
      href: el.href || '',
      disabled: Boolean(el.disabled),
      box: {x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height)}
    };
  });
  const bodyText = (document.body?.innerText || '');
  const captchaNodes = [...document.querySelectorAll('[id*="captcha" i],[class*="captcha" i],iframe[src*="captcha" i],iframe[src*="recaptcha" i],iframe[src*="hcaptcha" i]')].filter(visible);
  const captchaText = /\b(captcha|recaptcha|hcaptcha|verify you are human|人机验证|验证码)\b/i.test(bodyText);
  const active = document.activeElement;
  return {
    url: location.href,
    title: document.title,
    ready_state: document.readyState,
    viewport: {width: innerWidth, height: innerHeight, device_scale_factor: devicePixelRatio, scroll_x: scrollX, scroll_y: scrollY, page_height: document.documentElement.scrollHeight},
    active_element: active ? {tag: active.tagName.toLowerCase(), type: active.getAttribute('type') || '', aria_label: active.getAttribute('aria-label') || ''} : null,
    elements,
    text: bodyText.slice(0, LIMIT),
    captcha: {detected: captchaNodes.length > 0 || captchaText, evidence: captchaNodes.slice(0, 5).map(el => el.outerHTML.slice(0, 300)).concat(captchaText ? ['page text contains a human-verification marker'] : [])}
  };
})()
""".replace("LIMIT", str(limit))
        return self._decorate_observation(self.evaluate(expression), include_screenshot=include_screenshot)

    def _element_box(self, index: int | None, selector: str | None):
        if index is None and not selector:
            raise ValueError("An observed element index or CSS selector is required")
        lookup = (
            f"(window.__egoagentElements || [])[{int(index)}]"
            if index is not None
            else f"document.querySelector({json.dumps(selector)})"
        )
        result = self.evaluate(
            f"(() => {{ const el = {lookup}; if (!el) return null; el.scrollIntoView({{block:'center'}}); const r=el.getBoundingClientRect(); return {{x:r.x,y:r.y,width:r.width,height:r.height,disabled:Boolean(el.disabled)}}; }})()"
        )
        if not result:
            raise ValueError("element not found; observe again")
        if result.get("disabled"):
            raise ValueError("element is disabled")
        return result

    @staticmethod
    def _modifier_mask(modifiers) -> int:
        if isinstance(modifiers, str):
            modifiers = [part for part in re.split(r"[+, ]+", modifiers) if part]
        mask = 0
        for modifier in modifiers or []:
            lowered = str(modifier).lower()
            if lowered in {"alt", "option"}:
                mask |= 1
            elif lowered in {"ctrl", "control"}:
                mask |= 2
            elif lowered in {"meta", "command", "cmd", "win"}:
                mask |= 4
            elif lowered == "shift":
                mask |= 8
            else:
                raise ValueError(f"unsupported modifier: {modifier}")
        return mask

    def click_at(self, x: float, y: float, button: str = "left", click_count: int = 1, modifiers=None):
        x, y = self._validate_point(x, y)
        button = str(button).lower()
        if button not in {"left", "right", "middle"}:
            raise ValueError("mouse button must be left, right or middle")
        mask = self._modifier_mask(modifiers)
        common = {"x": x, "y": y, "button": button, "clickCount": max(1, min(int(click_count), 3)), "modifiers": mask}
        self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "modifiers": mask})
        self.call("Input.dispatchMouseEvent", {"type": "mousePressed", **common})
        self.call("Input.dispatchMouseEvent", {"type": "mouseReleased", **common})
        time.sleep(0.35)
        return {"action": "click_at", "result": {"ok": True, "x": x, "y": y}, "observation": self.observe()}

    def _validate_point(self, x: float, y: float):
        viewport = (self._last_observation or {}).get("viewport") or self.observe().get("viewport", {})
        width, height = float(viewport.get("width", 0)), float(viewport.get("height", 0))
        x, y = float(x), float(y)
        if width <= 0 or height <= 0 or x < 0 or y < 0 or x >= width or y >= height:
            raise ValueError(f"coordinates ({x}, {y}) are outside viewport {width}x{height}")
        return x, y

    def move(self, x: float, y: float):
        x, y = self._validate_point(x, y)
        self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        return {"action": "move", "result": {"ok": True, "x": x, "y": y}}

    def drag(self, x: float, y: float, end_x: float, end_y: float, button: str = "left"):
        start_x, start_y = self._validate_point(x, y)
        end_x, end_y = self._validate_point(end_x, end_y)
        button = str(button).lower()
        if button not in {"left", "right", "middle"}:
            raise ValueError("mouse button must be left, right or middle")
        self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": start_x, "y": start_y})
        self.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": start_x, "y": start_y, "button": button, "clickCount": 1})
        for step in range(1, 11):
            ratio = step / 10
            self.call(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseMoved",
                    "x": start_x + (end_x - start_x) * ratio,
                    "y": start_y + (end_y - start_y) * ratio,
                    "button": button,
                    "buttons": 1,
                },
            )
        self.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": end_x, "y": end_y, "button": button, "clickCount": 1})
        time.sleep(0.35)
        return {"action": "drag", "result": {"ok": True}, "observation": self.observe()}

    def element_action(self, action: str, index: int | None, selector: str | None, text: str = "", clear: bool = True):
        box = self._element_box(index, selector)
        center_x = box["x"] + box["width"] / 2
        center_y = box["y"] + box["height"] / 2
        if action == "click":
            result = self.click_at(center_x, center_y)
            result["action"] = "click"
            result["result"].update({"index": index, "selector": selector})
            return result
        lookup = (
            f"(window.__egoagentElements || [])[{int(index)}]"
            if index is not None
            else f"document.querySelector({json.dumps(selector)})"
        )
        clear_js = "if ('value' in el) { el.value=''; el.dispatchEvent(new Event('input',{bubbles:true})); }" if clear else ""
        self.evaluate(f"(() => {{ const el={lookup}; el.focus(); {clear_js} return true; }})()")
        self.call("Input.insertText", {"text": str(text)})
        time.sleep(0.25)
        return {"action": "type", "result": {"ok": True}, "observation": self.observe()}

    def press(self, key: str, modifiers=None):
        raw = str(key or "Enter")
        parts = [part for part in raw.split("+") if part]
        if len(parts) > 1:
            base_modifiers = [modifiers] if isinstance(modifiers, str) else list(modifiers or [])
            modifiers = [*base_modifiers, *parts[:-1]]
            raw = parts[-1]
        key_value, code, virtual = _KEYS.get(raw.lower(), (raw, f"Key{raw.upper()}" if len(raw) == 1 else raw, ord(raw.upper()) if len(raw) == 1 else 0))
        mask = self._modifier_mask(modifiers)
        params = {"key": key_value, "code": code, "windowsVirtualKeyCode": virtual, "nativeVirtualKeyCode": virtual, "modifiers": mask}
        self.call("Input.dispatchKeyEvent", {"type": "keyDown", **params})
        self.call("Input.dispatchKeyEvent", {"type": "keyUp", **params})
        time.sleep(0.3)
        return {"action": "press", "result": {"ok": True, "key": raw, "modifiers": mask}, "observation": self.observe()}

    def scroll(self, delta_x: float, delta_y: float):
        viewport = (self._last_observation or {}).get("viewport") or self.observe().get("viewport", {})
        x = float(viewport.get("width", 1280)) / 2
        y = float(viewport.get("height", 900)) / 2
        self.call(
            "Input.dispatchMouseEvent",
            {"type": "mouseWheel", "x": x, "y": y, "deltaX": float(delta_x), "deltaY": float(delta_y)},
        )
        time.sleep(0.25)
        return self.observe()

    def screenshot(self):
        result = self.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        screenshots = self.root / "screenshots"
        screenshots.mkdir(parents=True, exist_ok=True)
        path = screenshots / f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}.png"
        path.write_bytes(base64.b64decode(result["data"]))
        last = self._last_observation or {}
        return {
            "kind": "browser_screenshot",
            "path": str(path.resolve()),
            "mime_type": "image/png",
            "url": last.get("url", ""),
            "viewport": copy.deepcopy(last.get("viewport", {})),
        }

    def handle_dialog(self, accept: bool, prompt_text: str = ""):
        if not self.pending_dialog:
            raise ValueError("no JavaScript dialog is open")
        previous = copy.deepcopy(self.pending_dialog)
        self.call("Page.handleJavaScriptDialog", {"accept": bool(accept), "promptText": str(prompt_text)})
        with self._state_lock:
            self.pending_dialog = None
        time.sleep(0.25)
        return {
            "action": "accept_dialog" if accept else "dismiss_dialog",
            "result": {"ok": True, "dialog": previous},
            "observation": self.observe(),
        }

    def wait_download(self, guid: str = "", timeout: float = 30):
        deadline = time.monotonic() + max(0.1, min(float(timeout), 120.0))
        while time.monotonic() < deadline:
            downloads = self._downloads()
            candidates = [item for item in downloads if not guid or item.get("guid") == guid]
            completed = next(
                (
                    item for item in candidates
                    if item.get("ready") and item.get("state") != "canceled"
                ),
                None,
            )
            cancelled = next((item for item in candidates if item.get("state") == "canceled"), None)
            if completed:
                return {"download": completed, "downloads": downloads, "completed": True}
            if cancelled:
                return {"download": cancelled, "downloads": downloads, "completed": False}
            time.sleep(0.1)
        return {"download": None, "downloads": self._downloads(), "completed": False, "timed_out": True}

    def tabs(self):
        return [
            {
                "target_id": target.get("id"),
                "title": target.get("title", ""),
                "url": target.get("url", ""),
                "active": target.get("id") == self.target_id,
            }
            for target in self._http_json("/json/list")
            if target.get("type") == "page"
        ]

    def new_tab(self, url: str):
        encoded = urllib.parse.quote(url or "about:blank", safe="")
        target = self._http_json(f"/json/new?{encoded}", method="PUT")
        self._connect(target)
        self._wait_page_ready(5)
        return self.observe()

    def switch_tab(self, target_id: str):
        target = next((item for item in self._http_json("/json/list") if item.get("id") == target_id), None)
        if target is None:
            raise ValueError(f"Unknown target_id: {target_id}")
        self._connect(target)
        return self.observe()

    def handoff(self, reason: str = "human verification required"):
        observation = self.observe(include_screenshot=True)
        return {
            "status": "human_required",
            "requires_human": True,
            "reason": str(reason),
            "headless": self.headless,
            "observation": observation,
            "path": observation.get("path"),
            "instructions": (
                "This session is headless. Preserve the evidence, then restart the browser with headless=false and navigate back before asking a person to interact."
                if self.headless
                else "Complete the human-only step in the visible browser, then approve the DAG handoff to resume with a fresh observation."
            ),
            "resume_with": ["observe", "click_at", "type", "accept_dialog", "dismiss_dialog"],
        }

    def close(self):
        self._disconnect()
        if self.process.poll() is None:
            try:
                from pipeline_engine import _terminate_process_tree

                _terminate_process_tree(self.process, grace_seconds=0.5)
            except (ImportError, OSError, RuntimeError, subprocess.SubprocessError):
                try:
                    if os.name != "nt":
                        os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                    else:
                        self.process.kill()
                except (OSError, ProcessLookupError):
                    pass
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        deadline = time.time() + 10
        while self.profile.exists() and time.time() < deadline:
            try:
                shutil.rmtree(self.profile)
            except OSError:
                time.sleep(0.1)
        if self.profile.exists():
            shutil.rmtree(self.profile, ignore_errors=True)
        return {"closed": True, "profile_removed": not self.profile.exists(), "downloads": self._downloads()}


def _session(_context: dict | None, headless: bool = True) -> CDPBrowser:
    if _context is None:
        raise RuntimeError("browser tool requires Agent runtime context")
    current = _context.get("browser_session")
    if current is None or current.process.poll() is not None:
        workspace = Path(_context.get("workspace") or Path.cwd())
        current = CDPBrowser(workspace, headless=headless)
        _context["browser_session"] = current
    return current


def browser(
    action: str,
    url: str = "",
    index: int | None = None,
    selector: str | None = None,
    text: str = "",
    clear: bool = True,
    x: float = 0,
    y: float = 700,
    end_x: float = 0,
    end_y: float = 0,
    button: str = "left",
    click_count: int = 1,
    modifiers=None,
    target_id: str = "",
    seconds: float = 1,
    timeout: float = 30,
    max_chars: int = 12000,
    include_screenshot: bool = False,
    download_guid: str = "",
    prompt_text: str = "",
    reason: str = "human verification required",
    headless: bool = True,
    _context: dict | None = None,
):
    action = str(action).lower()
    session = _session(_context, headless=headless)
    if action == "start":
        return session.observe(max_chars, include_screenshot=include_screenshot)
    if action == "navigate":
        return session.navigate(url, wait_seconds=timeout)
    if action == "observe":
        return session.observe(max_chars, include_screenshot=include_screenshot)
    if action == "click":
        return session.element_action("click", index, selector)
    if action == "click_at":
        return session.click_at(x, y, button=button, click_count=click_count, modifiers=modifiers)
    if action == "move":
        return session.move(x, y)
    if action == "drag":
        return session.drag(x, y, end_x, end_y, button=button)
    if action == "type":
        return session.element_action("type", index, selector, text=text, clear=clear)
    if action == "press":
        return session.press(text, modifiers=modifiers)
    if action == "scroll":
        return session.scroll(x, y)
    if action == "extract":
        observation = session.observe(max_chars)
        return {"url": observation["url"], "title": observation["title"], "text": observation["text"], "observation_id": observation["observation_id"]}
    if action == "screenshot":
        return session.screenshot()
    if action == "accept_dialog":
        return session.handle_dialog(True, prompt_text=prompt_text)
    if action == "dismiss_dialog":
        return session.handle_dialog(False)
    if action == "downloads":
        return {"downloads": session._downloads()}
    if action == "wait_download":
        return session.wait_download(download_guid, timeout=timeout)
    if action == "handoff":
        return session.handoff(reason)
    if action == "back":
        session._load_event.clear()
        session.evaluate("history.back()")
        session._wait_page_ready(timeout)
        return session.observe()
    if action == "tabs":
        return {"tabs": session.tabs()}
    if action == "new_tab":
        return session.new_tab(url)
    if action == "switch_tab":
        return session.switch_tab(target_id)
    if action == "wait":
        return session.wait(seconds)
    if action == "close":
        result = session.close()
        if _context is not None:
            _context.pop("browser_session", None)
        return result
    raise ValueError(f"Unknown browser action: {action}")
