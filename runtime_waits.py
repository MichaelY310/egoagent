"""Cooperative node deadlines, excluding time spent waiting for a person.

The context stack includes enclosing loop/subflow deadlines. A human wait
pauses all of them, but never the run's overall budget or cancellation signal.
Expired workers retain a cancellation token so a late answer cannot execute
an operation belonging to an abandoned node attempt.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import threading
import time


@dataclass
class ActiveDeadline:
    timeout: float
    started: float = field(default_factory=time.monotonic)
    cancelled: threading.Event = field(default_factory=threading.Event)
    lock: threading.RLock = field(default_factory=threading.RLock)
    waiting: int = 0
    paused_at: float = 0.0
    paused_seconds: float = 0.0

    def pause(self):
        with self.lock:
            if not self.waiting:
                self.paused_at = time.monotonic()
            self.waiting += 1

    def resume(self):
        with self.lock:
            self.waiting -= 1
            if not self.waiting:
                self.paused_seconds += time.monotonic() - self.paused_at

    def remaining(self):
        with self.lock:
            now = self.paused_at if self.waiting else time.monotonic()
            return self.timeout - (now - self.started - self.paused_seconds)


active_deadlines = ContextVar("egoagent_active_deadlines", default=())


def deadline_cancelled():
    return any(item.cancelled.is_set() for item in active_deadlines.get())


@contextmanager
def human_wait():
    deadlines = active_deadlines.get()
    for item in deadlines:
        item.pause()
    try:
        yield
    finally:
        for item in reversed(deadlines):
            item.resume()
