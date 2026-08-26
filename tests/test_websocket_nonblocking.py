from __future__ import annotations

import threading
import time
import unittest

from harness_editor.server import WebSocketHandler


class _SlowSocket:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.payloads = []

    def sendall(self, payload):
        self.entered.set()
        self.release.wait(timeout=2)
        self.payloads.append(payload)


class WebSocketNonBlockingTests(unittest.TestCase):
    def test_slow_browser_does_not_block_model_event_producer(self):
        sock = _SlowSocket()
        client = WebSocketHandler(sock)
        started = time.perf_counter()
        client.send('{"type":"token","data":{"text":"hello"}}')
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 0.1)
        self.assertTrue(sock.entered.wait(timeout=1))
        self.assertFalse(sock.payloads)
        sock.release.set()
        deadline = time.time() + 1
        while not sock.payloads and time.time() < deadline:
            time.sleep(0.01)
        client.close()
        self.assertTrue(sock.payloads)


if __name__ == "__main__":
    unittest.main()
