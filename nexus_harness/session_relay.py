"""Auto-relay: a session that fills up hands its own work to a clean one.

Every harness today ends when the window ends, and the next session starts from a summary somebody
wrote from memory. The protocol already solved this part (`nexus/hive/relay.py`): the plan and the
proofs live on disk, a phase closes with the exit codes that observed it, and the prompt for the next
session is generated from that state. What this module adds is the trigger and the swap:

1. **Measure.** Every reply's usage goes into `BudgetMeter`. A budget nobody measured is `unmeasured`,
   never `0 %`.
2. **Trigger** at `threshold` (70 % by default) or on an explicit checkpoint.
3. **Hand over**: record the budget in the protocol's state, generate `NEXT_SESSION_PROMPT.md`, archive
   the current session, open `session_NN+1` with that prompt as its first user message.
4. **Continue.** The loop is not restarted; it is re-pointed. Same run, new session, no human.

The session files are the harness's own (`~/.nexus/harness` is engine state; a project's sessions live
under `<root>/.nexus/harness/sessions/` so a relay is visible next to the work it describes).
"""
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .relay_state import RelayState

PROTOCOL = "nexus.harness.session/1"
MAX_PROMPT_CHARS = 12000
SESSIONS_REL = Path(".nexus") / "harness" / "sessions"
PROMPT_REL = Path(".nexus") / "NEXT_SESSION_PROMPT.md"
NEXUS_SOURCE = Path(os.environ.get("NEXUS_PROTOCOL") or r"C:\Proyectos\NexusProtocol")


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _protocol_relay():
    """`nexus.hive.relay`, or `None` on a machine without the protocol."""
    if str(NEXUS_SOURCE) not in sys.path:
        sys.path.insert(0, str(NEXUS_SOURCE))
    try:
        from nexus.hive import relay
        return relay
    except ImportError:
        return None


@dataclass
class BudgetMeter:
    """Tokens against a limit. `unmeasured` is a state, and it is not headroom."""

    limit: int = 60000
    threshold: float = 0.70
    used: int = 0
    measured: bool = False
    turns: int = 0

    def observe(self, usage):
        """Add one reply's cost. A reply with no usage data does not become a zero."""
        if usage is None:
            return self.state()
        total = int(getattr(usage, "total", 0) or 0)
        self.turns += 1
        if total > 0:
            self.used += total
            self.measured = True
        return self.state()

    @property
    def ratio(self):
        if not self.measured or self.limit <= 0:
            return None
        return self.used / float(self.limit)

    def state(self):
        ratio = self.ratio
        return {"used": self.used, "limit": self.limit, "turns": self.turns,
                "ratio": ratio, "threshold": self.threshold,
                "state": "unmeasured" if ratio is None else "measured",
                "should_relay": bool(ratio is not None and ratio >= self.threshold)}


class SessionStore:
    """Sessions as files: one JSON each, archived by moving them, numbered by scanning."""

    def __init__(self, root):
        self.root = Path(root)
        self.dir = self.root / SESSIONS_REL
        self.archive_dir = self.dir / "archive"

    def ensure(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        return self

    def path(self, session_id):
        return self.dir / ("%s.json" % session_id)

    def ids(self):
        if not self.dir.is_dir():
            return []
        return sorted(path.stem for path in self.dir.glob("session_*.json"))

    def all_ids(self):
        """Live AND archived: a number is never reused, or a completed session would overwrite one."""
        names = set(self.ids())
        if self.archive_dir.is_dir():
            names.update(path.stem for path in self.archive_dir.glob("session_*.json"))
        return sorted(names)

    def next_id(self):
        numbers = [int(name.split("_")[-1]) for name in self.all_ids()
                   if name.split("_")[-1].isdigit()]
        return "session_%02d" % (max(numbers) + 1 if numbers else 1)

    def save(self, session):
        self.ensure()
        self.path(session["id"]).write_text(json.dumps(session, indent=2, sort_keys=True),
                                            encoding="utf-8")
        return session

    def load(self, session_id):
        path = self.path(session_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def archive(self, session_id):
        self.ensure()
        source = self.path(session_id)
        if not source.is_file():
            return None
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        target = self.archive_dir / source.name
        if target.exists():
            # Never overwrite an archived session: an id is unique, and a lost transcript is a lost
            # relay. A timestamp keeps both instead of choosing.
            target = self.archive_dir / ("%s.%s.json" % (source.stem,
                                                         utc_now().replace(":", "")))
        session = self.load(session_id) or {}
        session["status"] = "archived"
        session["closed_at"] = utc_now()
        target.write_text(json.dumps(session, indent=2, sort_keys=True), encoding="utf-8")
        source.unlink()
        return target


@dataclass
class Handover:
    ok: bool
    from_session: str = ""
    to_session: str = ""
    prompt: str = ""
    prompt_path: str = ""
    ratio: object = None
    reason: str = ""

    def as_dict(self):
        return {"ok": self.ok, "from": self.from_session, "to": self.to_session,
                "prompt_path": self.prompt_path, "ratio": self.ratio, "reason": self.reason,
                "prompt_chars": len(self.prompt)}


class SessionRelay:
    """Owns the active session, the meter, and the moment the session is replaced."""

    def __init__(self, root, goal="", config=None, bus=None, phases=None, store=None):
        self.root = Path(root)
        self.goal = goal
        self.config = config
        self.bus = bus
        self.meter = BudgetMeter(limit=int(getattr(config, "budget_limit", 60000) or 60000),
                                 threshold=float(getattr(config, "relay_threshold", 0.70) or 0.70))
        self.store = store or SessionStore(self.root)
        self.session = {}
        self.phases = list(phases or [])
        self.handovers = []
        self.last_warning = ""
        self.state = RelayState.load(self.root)

    def _emit(self, kind, detail="", **payload):
        if self.bus is not None:
            self.bus.emit(kind, detail, **payload)

    def start(self):
        self.store.ensure()
        self._plan()
        session = {"protocol": PROTOCOL, "id": self.store.next_id(), "goal": self.goal,
                   "created_at": utc_now(), "closed_at": None, "status": "active",
                   "tokens": {"used": 0, "limit": self.meter.limit}, "turns": 0,
                   "handovers": 0}
        self.session = self.store.save(session)
        self._emit("session.start", self.session["id"], session=self.session["id"])
        return self.session

    def _plan(self):
        if not self.phases:
            return
        relay = _protocol_relay()
        if relay is None:
            return
        relay.plan(str(self.root), [{"id": str(p.get("id")), "title": str(p.get("title") or p.get("id")),
                                     "items": list(p.get("items") or [])} for p in self.phases],
                   goal=self.goal)

    def observe(self, usage):
        state = self.meter.observe(usage)
        if self.session:
            self.session["tokens"]["used"] = self.meter.used
            self.session["turns"] = self.meter.turns
            self.store.save(self.session)
        self._emit("budget", "%s/%s" % (self.meter.used, self.meter.limit), budget=state)
        return state

    def should_hand_over(self):
        return self.meter.state()["should_relay"]

    def checkpoint(self, phase_id, evidence=(), note=""):
        """Close a phase in the protocol's state with the exits the gate observed."""
        relay = _protocol_relay()
        if relay is None:
            return {"ok": False, "reason": "nexus relay unavailable"}
        result = relay.checkpoint(str(self.root), str(phase_id), evidence=list(evidence), note=note)
        self._emit("phase.checkpoint", str(phase_id), result=result)
        return result

    def _protocol_prompt(self):
        """The protocol's prompt, or "" when it cannot be had. `last_warning` says which it was."""
        relay = _protocol_relay()
        if relay is None:
            self.last_warning = "nexus relay not importable"
            return ""
        try:
            recorded = relay.session(str(self.root), used=self.meter.used, limit=self.meter.limit)
            if not recorded.get("ok"):
                self.last_warning = "relay.session refused: %s" % recorded.get("reason", "?")
                self._emit("relay.warning", self.last_warning)
                return ""
            state = relay.load(str(self.root))
            if state is None:
                self.last_warning = "relay state unreadable after session()"
                self._emit("relay.warning", self.last_warning)
                return ""
            return relay.build_prompt(str(self.root), state)
        except Exception as exc:  # resilience is the point: hand over even when the protocol fails
            self.last_warning = "%s: %s" % (type(exc).__name__, exc)
            self._emit("relay.warning", self.last_warning)
            return ""

    def hand_over(self, reason="budget", summary="", files=()):
        """Archive this session and open a clean one carrying the prompt. Returns a `Handover`."""
        if not self.session:
            self.start()
        # El estado verificado se escribe ANTES del prompt: la sesion hija tiene que poder leer de disco
        # lo mismo que dice su primer mensaje, sin depender de que el protocolo este importable.
        state = RelayState.load(self.root)
        state.own["goal"] = state.own.get("goal") or self.goal
        state.next(str(summary or "")[:400] or state.own.get("next_step") or "")
        state.touched(files)
        state.session(self.session.get("id", ""), self.store.next_id(), reason)
        state.own["tokens"] = {"used": self.meter.used, "limit": self.meter.limit}
        state.save()
        self.state = state
        prompt = self._protocol_prompt()
        if not prompt.strip():
            prompt = state.prompt()
            if summary:
                prompt += "\n## Trabajo hasta ahora\n%s\n" % str(summary)[:2000]
            if files:
                prompt += "\n## Ficheros tocados\n%s\n" % ", ".join(sorted(set(files))[:40])
        if len(prompt) > MAX_PROMPT_CHARS:
            # A prompt that does not fit the next session's window would start it truncated by the
            # provider, which is worse than starting it with a declared cut.
            prompt = (prompt[:MAX_PROMPT_CHARS]
                      + "\n\n... (prompt recortado en %d caracteres: lee .nexus/RELAY_STATE.json para "
                        "el plan completo)\n" % (len(prompt) - MAX_PROMPT_CHARS))
        path = self.root / PROMPT_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(prompt, encoding="utf-8")
        previous = self.session["id"]
        self.store.archive(previous)
        session = {"protocol": PROTOCOL, "id": self.store.next_id(), "goal": self.goal,
                   "created_at": utc_now(), "closed_at": None, "status": "active",
                   "tokens": {"used": 0, "limit": self.meter.limit}, "turns": 0,
                   "handovers": int(self.session.get("handovers", 0)) + 1,
                   "relay_from": previous, "reason": str(reason)}
        self.session = self.store.save(session)
        self.meter = BudgetMeter(limit=self.meter.limit, threshold=self.meter.threshold)
        handover = Handover(ok=True, from_session=previous, to_session=session["id"],
                            prompt=prompt, prompt_path=str(path), ratio=None, reason=str(reason))
        self.handovers.append(handover)
        self._emit("session.relay", "%s -> %s" % (previous, session["id"]),
                   handover=handover.as_dict())
        return handover

    def finish(self, exit_code):
        """Close the active session with the exit the run produced. A session is not "active" forever:
        a file that still says `active` after the run ended is the harness lying to its own cockpit."""
        if not self.session:
            return None
        self.session["status"] = "closed"
        self.session["closed_at"] = utc_now()
        self.session["exit"] = int(exit_code)
        self.store.save(self.session)
        self._emit("session.finish", self.session["id"], exit=int(exit_code))
        return self.session

    def status(self):
        return {"session": self.session, "budget": self.meter.state(),
                "sessions": self.store.ids(), "warning": self.last_warning,
                "handovers": [item.as_dict() for item in self.handovers],
                "prompt": str(self.root / PROMPT_REL),
                "relay_state": self.state.as_dict(),
                "prompt_exists": (self.root / PROMPT_REL).is_file()}
