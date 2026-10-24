"""The application's brain: one job at a time, over the same core.

Two ways to work, one engine:

* **chat** -- a conversation with tools, memory and a gate that runs only when a turn touched files;
* **run**  -- a one-shot goal with phases, the triad's repair loop and the session relay.

Both are capped to one in flight. That is not a limitation to apologise for: two jobs writing the same
repository is the failure mode the cap exists for, and a lock is cheaper and more honest than a queue
that pretends to schedule.

The class owns the bus, so the page and the desktop window watch the same transcript by sequence
number, and closing a window does not lose what happened.
"""
import threading
import time
from dataclasses import replace
from pathlib import Path

from . import __version__
from .bridge import Bridge
from .chat import Chat
from .config import HarnessConfig
from .context_router import ContextRouter
from .events import Bus
from .gate import Gate
from .judge import Judge
from .memory import Memory
from .providers import Router
from .session_relay import SessionRelay
from .tools import default_registry
from .transcripts import Transcripts
from .triad_loop import Triad


def _dirs(workspace):
    try:
        return sorted(path.name for path in Path(workspace).iterdir()
                      if path.is_dir() and not path.name.startswith(("_", ".")))
    except OSError:
        return []


class Cockpit:
    def __init__(self, config=None, bus=None, runner=None, bridge=None, memory=None):
        self.config = config or HarnessConfig.load()
        self.bus = bus or Bus()
        self.router = Router(self.config)
        self.bridge = bridge or Bridge(self.config.workspace, bus=self.bus)
        self.memory = memory or Memory()
        self.root = Path(self.config.default_root)
        self._runner = runner
        self._lock = threading.Lock()
        self._busy = False
        self.last = None
        self.chat = None
        self._triad = None
        self._catalog = (0.0, None)

    # -- catalogue ---------------------------------------------------------------------------
    def projects(self):
        return _dirs(self.config.workspace)

    def catalog(self):
        """Cached 15 s: the page polls, and a probe per poll would hammer two local servers."""
        stamp, value = self._catalog
        if value is not None and time.time() - stamp < 15:
            return value
        value = dict(self.router.catalog(), projects=self.projects())
        self._catalog = (time.time(), value)
        return value

    def refresh_catalog(self):
        self._catalog = (0.0, None)
        return self.catalog()

    def swap(self, role, spec):
        if role not in ("director", "worker", "judge"):
            return False, "role must be director, worker or judge"
        try:
            info = self.router.swap(role, spec)
        except Exception as exc:
            return False, str(exc)
        self.refresh_catalog()
        return True, info.__dict__

    # -- chat --------------------------------------------------------------------------------
    def chat_for(self, root=None):
        """The conversation for a project. Switching project starts a different conversation.

        With no explicit root, an existing conversation is returned as it is: re-targeting it to the
        default project on every `state()` call would throw away the conversation the operator just
        opened in another repository (a bug this line exists to keep fixed).
        """
        if root is None and self.chat is not None:
            return self.chat
        target = Path(root or self.root)
        if self.chat is not None and Path(self.chat.config.default_root) == target:
            return self.chat
        config = replace(self.config, default_root=target)
        self.chat = Chat(self.router, config, default_registry(target, config), Gate(target, config),
                         ContextRouter(config.lang), bus=self.bus, memory=self.memory,
                         transcripts=Transcripts(target), judge=Judge(self.router, config.lang))
        return self.chat

    def new_chat(self, title="", project=None):
        chat = self.chat_for(self._project_root(project))
        return chat.new(title)

    def load_chat(self, session_id, project=None):
        chat = self.chat_for(self._project_root(project))
        return chat.load(session_id)

    def send(self, text):
        """Start one chat turn. Returns (accepted, payload); refuses while something is in flight."""
        text = str(text or "").strip()
        if not text:
            return False, "a message is required"
        with self._lock:
            if self._busy:
                return False, "a job is already in flight"
            self._busy = True
        thread = threading.Thread(target=self._send_worker, args=(text,), daemon=True)
        try:
            thread.start()
        except RuntimeError as exc:
            with self._lock:
                self._busy = False
            return False, "could not start the turn: %s" % exc
        return True, {"text": text[:200], "session": (self.chat.session or {}).get("id")}

    def _send_worker(self, text):
        try:
            self.chat_for().send(text)
        except Exception as exc:  # the window must still show what happened
            self.bus.emit("worker.error", "%s: %s" % (type(exc).__name__, exc))
        finally:
            with self._lock:
                self._busy = False

    def stop(self):
        """Detener reaches the chat, the triad run and every process behind them."""
        stopped = False
        if self.chat is not None:
            self.chat.stop()
            stopped = True
        if self._triad is not None:
            self._triad.stop()
            stopped = True
        return stopped

    def chat_state(self):
        chat = self.chat if self.chat is not None else self.chat_for(self.root)
        state = chat.state()
        state["project"] = str(chat.config.default_root)
        state["busy"] = self._busy
        return state

    def sessions(self, project=None):
        return Transcripts(self._project_root(project)).listing()

    def delete_session(self, session_id, project=None):
        return Transcripts(self._project_root(project)).delete(session_id)

    def memory_state(self):
        return self.memory.as_dict()

    def memory_add(self, text):
        result = self.memory.add(text)
        if result.get("ok"):
            self.bus.emit("memory.add", str(text)[:120])
        return result

    def memory_remove(self, needle):
        result = self.memory.remove(needle)
        if result.get("ok"):
            self.bus.emit("memory.remove", str(needle)[:120])
        return result

    def _project_root(self, project=None):
        if not project:
            return self.root
        candidate = Path(project)
        if not candidate.is_absolute():
            candidate = self.config.workspace / str(project)
        return candidate if candidate.is_dir() else self.root

    # -- one-shot run (the triad) ------------------------------------------------------------
    def start(self, goal, project=None, test_command=None):
        """Start a one-shot run in a thread. Refuses while a job is in flight, which is the cap."""
        goal = str(goal or "").strip()
        if not goal:
            return False, "a goal is required"
        root = self.root
        if project:
            candidate = Path(project)
            if not candidate.is_absolute():
                candidate = Path(self.config.workspace) / str(project)
            if not candidate.is_dir():
                return False, "project not found: %s" % project
            root = candidate
        with self._lock:
            if self._busy:
                return False, "a job is already in flight"
            self._busy = True
        thread = threading.Thread(target=self._execute, args=(goal, root, test_command), daemon=True)
        try:
            thread.start()
        except RuntimeError as exc:
            with self._lock:
                self._busy = False
            return False, "could not start the run: %s" % exc
        return True, {"goal": goal, "root": str(root)}

    def _execute(self, goal, root, test_command=None):
        config = replace(self.config, default_root=root,
                         test_command=test_command or self.config.test_command)
        relay = SessionRelay(root, goal=goal, config=config, bus=self.bus)
        relay.start()
        triad = Triad(self.router, config, registry=default_registry(root, config),
                      gate=Gate(root, config), judge=Judge(self.router, config.lang),
                      skills=ContextRouter(config.lang), bus=self.bus, relay=relay)
        self._triad = triad
        try:
            self.last = triad.run(goal).as_dict()
        except Exception as exc:
            self.bus.emit("worker.error", "%s: %s" % (type(exc).__name__, exc))
            self.last = {"goal": goal, "ok": False, "exit": 10,
                         "summary": "%s: %s" % (type(exc).__name__, exc)}
        finally:
            self._triad = None
            with self._lock:
                self._busy = False

    def run_project(self, goal, root):
        """Synchronous entry used by the bridge: returns the exit code the gate produced."""
        if self._runner is not None:
            return self._runner(goal, root)
        config = replace(self.config, default_root=Path(root))
        relay = SessionRelay(root, goal=goal, config=config, bus=self.bus)
        relay.start()
        triad = Triad(self.router, config, registry=default_registry(root, config),
                      gate=Gate(root, config), judge=Judge(self.router, config.lang),
                      skills=ContextRouter(config.lang), bus=self.bus, relay=relay)
        result = triad.run(goal)
        self.last = result.as_dict()
        return result.exit

    def tick_bridge(self):
        return self.bridge.tick(self.run_project)

    # -- state -------------------------------------------------------------------------------
    def _latest(self, kind):
        for event in reversed(self.bus.all()):
            if event["kind"] == kind:
                return event
        return None

    def run_payload(self):
        if not self.last:
            return None
        payload = dict(self.last)
        plan = self._latest("director.plan")
        skills = self._latest("skills.injected")
        budget = self._latest("budget")
        if plan:
            payload["plan"] = plan["detail"]
        if skills:
            payload["skills"] = skills["payload"]
        payload.setdefault("budget", (budget or {}).get("payload", {}).get("budget", {}))
        return payload

    def relay_status(self):
        prompt = self.root / ".nexus" / "NEXT_SESSION_PROMPT.md"
        sessions_dir = self.root / ".nexus" / "harness" / "sessions"
        started = self._latest("session.start")
        budget = self._latest("budget")
        return {"session": (started or {}).get("payload", {}).get("session"),
                "sessions": sorted(path.stem for path in sessions_dir.glob("session_*.json"))
                if sessions_dir.is_dir() else [],
                "handovers": [event["payload"].get("handover") for event in self.bus.all()
                              if event["kind"] == "session.relay"],
                "prompt_exists": prompt.is_file(),
                "budget": (budget or {}).get("payload", {}).get("budget", {})}

    def state(self):
        pending = self.bridge.pending()
        chat = self.chat_state() if self.chat is not None else {
            "session": None, "last": None, "project": str(self.root), "messages": []}
        return {"version": __version__, "running": self._busy,
                "config": dict(self.config.public(), root=str(self.root)),
                "roles": self.router.describe(), "models": self.catalog(),
                "run": self.run_payload(), "relay": self.relay_status(),
                "chat": {"session": chat.get("session"), "last": chat.get("last"),
                         "project": chat.get("project"), "budget": chat.get("budget"),
                         "turns": len([m for m in chat.get("messages", [])
                                       if m.get("role") == "user"])},
                "sessions": self.sessions(),
                "memory": {"count": len(self.memory.entries())},
                "bridge": {"pending": len(pending), "items": pending},
                "seq": self.bus.seq, "port": self.config.port}
