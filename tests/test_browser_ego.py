from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import Agent
from identity.browser_operator.ego.skills.browser.scripts.browser import CDPBrowser


class BrowserEgoTests(unittest.TestCase):
    def test_download_reconciliation_survives_a_missing_cdp_event(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temp:
            session = CDPBrowser.__new__(CDPBrowser)
            session.download_root = Path(temp)
            session.downloads_state = {}
            session._state_lock = threading.RLock()
            downloaded = session.download_root / "eventless.txt"
            downloaded.write_text("landed", encoding="utf-8")

            first = session._downloads()
            time.sleep(0.12)
            entries = session._downloads()

            self.assertFalse(first[0]["ready"])
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["state"], "completed")
            self.assertTrue(entries[0]["ready"])
            self.assertTrue(entries[0]["reconciled_from_file"])
            self.assertEqual(entries[0]["path"], str(downloaded.resolve()))

    def test_browser_tool_observes_interacts_and_captures_evidence(self):
        (ROOT / "tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temp:
            workspace = Path(temp)
            agent = Agent(ROOT / "identity" / "browser_operator", workspace=workspace)
            tool = next(value for name, value in agent.tools.items() if agent._short_name(name) == "browser")
            context = agent._runtime_context
            html = """
              <title>Browser Test</title>
              <input aria-label='name'>
              <button onclick="document.body.dataset.done='yes';this.innerText='Done'">Go</button>
              <button onclick="this.innerText='Coordinate Done'">Coordinate</button>
              <button onclick="alert('confirm browser action')">Alert</button>
              <a href='/download' download='evidence.txt'>Download</a>
            """

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, _format, *_args):
                    pass

                def do_GET(self):
                    if self.path == "/download":
                        content = b"download-evidence"
                        self.send_response(200)
                        self.send_header("Content-Type", "text/plain")
                        self.send_header("Content-Disposition", 'attachment; filename="evidence.txt"')
                        self.send_header("Content-Length", str(len(content)))
                        self.end_headers()
                        self.wfile.write(content)
                        return
                    content = html.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            url = f"http://127.0.0.1:{server.server_address[1]}/"
            try:
                state = tool.func(action="navigate", url=url, _context=context)
                self.assertEqual(state["title"], "Browser Test")
                self.assertEqual(state["kind"], "browser_observation")
                self.assertGreater(state["observation_id"], 0)
                self.assertTrue(state["page_changed"])
                self.assertTrue(state["target_id"])
                input_index = next(item["index"] for item in state["elements"] if item["tag"] == "input")
                button_index = next(item["index"] for item in state["elements"] if item["text"] == "Go")

                typed = tool.func(action="type", index=input_index, text="Alice", _context=context)
                self.assertTrue(typed["result"]["ok"])
                self.assertFalse(typed["observation"]["page_changed"])
                clicked = tool.func(action="click", index=button_index, _context=context)
                self.assertTrue(clicked["result"]["ok"])
                self.assertTrue(any(item["text"] == "Done" for item in clicked["observation"]["elements"]))

                coordinate = next(item for item in clicked["observation"]["elements"] if item["text"] == "Coordinate")
                box = coordinate["box"]
                coordinate_click = tool.func(
                    action="click_at",
                    x=box["x"] + box["width"] / 2,
                    y=box["y"] + box["height"] / 2,
                    _context=context,
                )
                self.assertTrue(any(item["text"] == "Coordinate Done" for item in coordinate_click["observation"]["elements"]))

                alert_index = next(item["index"] for item in coordinate_click["observation"]["elements"] if item["text"] == "Alert")
                dialog = tool.func(action="click", index=alert_index, _context=context)
                self.assertEqual(dialog["observation"]["dialog"]["message"], "confirm browser action")
                self.assertEqual(dialog["observation"]["blocked"]["type"], "javascript_dialog")
                dismissed = tool.func(action="dismiss_dialog", _context=context)
                self.assertIsNone(dismissed["observation"]["dialog"])

                download_index = next(item["index"] for item in dismissed["observation"]["elements"] if item["text"] == "Download")
                tool.func(action="click", index=download_index, _context=context)
                # Chrome can defer the final rename/event while the full suite
                # is CPU-bound; exercise the product's normal 30-second wait.
                download = tool.func(action="wait_download", timeout=30, _context=context)
                self.assertTrue(download["completed"])
                downloaded_path = Path(download["download"]["path"])
                self.assertTrue(downloaded_path.is_file())
                self.assertEqual(downloaded_path.read_text(encoding="utf-8"), "download-evidence")
                self.assertTrue(workspace.resolve() in downloaded_path.resolve().parents)

                shot = tool.func(action="screenshot", _context=context)
                self.assertTrue(Path(shot["path"]).is_file())

                captcha_url = "data:text/html," + urllib.parse.quote("<title>Blocked</title><div id='captcha'>Verify you are human</div>")
                blocked = tool.func(action="navigate", url=captcha_url, _context=context)
                self.assertEqual(blocked["blocked"]["type"], "captcha")
                handoff = tool.func(action="handoff", reason="CAPTCHA requires a person", _context=context)
                self.assertTrue(handoff["requires_human"])
                self.assertTrue(Path(handoff["path"]).is_file())
            finally:
                if context.get("browser_session") is not None:
                    tool.func(action="close", _context=context)
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
