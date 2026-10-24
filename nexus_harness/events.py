"""What happened, in order, for whoever is watching.

The cockpit polls; it does not stream. That is a decision, not a limitation: a WebSocket would add a
dependency or a handshake, and the one thing a local UI needs is a monotonically increasing sequence
it can ask for by number. `Bus.since(seq)` is that question.

A bus with no listener still records, because the CLI wants the transcript and the tests want to
assert on it.
"""
import threading
import time
from collections import deque
from dataclasses import dataclass, field

MAX_EVENTS = 600


@dataclass
class Event:
    seq: int
    at: float
    kind: str
    detail: str = ""
    payload: dict = field(default_factory=dict)

    def as_dict(self):
        return {"seq": self.seq, "at": self.at, "kind": self.kind, "detail": self.detail,
                "payload": self.payload}


class Bus:
    """A bounded, thread-safe log. Old events fall off the front; the sequence keeps counting."""

    def __init__(self, limit=MAX_EVENTS, clock=None):
        self._events = deque(maxlen=limit)
        self._lock = threading.Lock()
        self._seq = 0
        self._clock = clock or time.time

    def emit(self, kind, detail="", **payload):
        with self._lock:
            self._seq += 1
            event = Event(self._seq, self._clock(), kind, str(detail)[:2000], payload)
            self._events.append(event)
            return event

    def since(self, seq=0):
        with self._lock:
            return [event.as_dict() for event in self._events if event.seq > int(seq or 0)]

    def last(self):
        with self._lock:
            return self._events[-1].as_dict() if self._events else None

    def all(self):
        with self._lock:
            return [event.as_dict() for event in self._events]

    def find(self, kind):
        return [event for event in self.all() if event["kind"] == kind]

    @property
    def seq(self):
        return self._seq
