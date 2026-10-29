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

from . import __version__, panels, runner
from .autonomy import Autopilot, model_planner
from .bridge import Bridge
from .chat import Chat
from .config import HarnessConfig
from .context.skill_router import library
from .platform.events import Bus
from .gate import Gate
from .llm.judge import judge_for
from .tools.mcp_client import McpManager
from .context.memory import Memory
from .llm.providers import Router
from .tools import default_registry
from .platform.transcripts import Transcripts


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
        self._autopilot = None
        self._autopilot_key = None
        self.mcp_manager = None
        self._mcp_started = False
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

    # -- connectors and configuration ---------------------------------------------------------
    def mcp(self):
        """The MCP manager, started once. A dead connector is reported, never fatal."""
        if not self._mcp_started:
            self._mcp_started = True
            self.mcp_manager = McpManager(root=self.root).start()
        return self.mcp_manager

    def reload_config(self, root=None):
        """Re-read `~/.nexus/harness.json` after onboarding, and drop what was built from the old one."""
        target = Path(root or self.config.default_root)
        self.config = HarnessConfig.load(root=target)
        self.root = target
        self.router = Router(self.config)
        self.chat = None
        self._catalog = (0.0, None)
        self.bus.emit("config.reloaded", str(target))
        return self.config.public()

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
        registry = default_registry(target, config, mcp=self.mcp())
        self.chat = Chat(self.router, config, registry, Gate(target, config),
                         library(target), bus=self.bus, memory=self.memory,
                         transcripts=Transcripts(target), judge=judge_for(self.router, config))
        return self.chat

    def new_chat(self, title="", project=None):
        chat = self.chat_for(self._project_root(project))
        return chat.new(title)

    def load_chat(self, session_id, project=None):
        chat = self.chat_for(self._project_root(project))
        return chat.load(session_id)

    # -- product panels ----------------------------------------------------------------------
    def onboarding_state(self):
        return panels.onboarding_status(self)

    def onboarding_apply(self, payload):
        return panels.onboarding_apply(self, payload)

    def mcp_state(self):
        return panels.mcp_status(self)

    def mcp_reload(self):
        self.mcp()
        return panels.mcp_reload(self)

    def skills_list(self):
        return panels.skills_list(self)

    def skill_read(self, name):
        return panels.skills_read(self, name)

    def skill_save(self, name, text):
        return panels.skills_save(self, name, text)

    def daemon_state(self):
        return panels.daemon_status(self)

    def daemon_toggle(self, provider=""):
        return panels.daemon_toggle(self, provider or "telegram")

    def daemon_stop(self):
        return panels.daemon_stop(self)

    def send(self, text, attachments=None):
        """Start one chat turn. Returns (accepted, payload); refuses while something is in flight."""
        text = str(text or "").strip()
        if not text:
            return False, "a message is required"
        with self._lock:
            if self._busy:
                return False, "a job is already in flight"
            self._busy = True
        # The conversation is built HERE, not inside the thread: the reply must be able to name the
        # session it went to, and a thread that has not started yet is not a session.
        chat = self.chat_for()
        thread = threading.Thread(target=self._send_worker, args=(text, attachments), daemon=True)
        try:
            thread.start()
        except RuntimeError as exc:
            with self._lock:
                self._busy = False
            return False, "could not start the turn: %s" % exc
        return True, {"text": text[:200], "session": (chat.session or {}).get("id")}

    def _send_worker(self, text, attachments=None):
        try:
            self.chat_for().send(text, attachments)
        except Exception as exc:  # the window must still show what happened
            self.bus.emit("worker.error", "%s: %s" % (type(exc).__name__, exc))
        finally:
            with self._lock:
                self._busy = False

    def stop(self):
        """Detener reaches the chat, the triad run, the autonomy loop and every process behind them."""
        stopped = False
        if self.chat is not None:
            self.chat.stop()
            stopped = True
        if self._triad is not None:
            self._triad.stop()
            stopped = True
        if self._autopilot is not None and self._autopilot.stop():
            stopped = True
        return stopped

    @property
    def busy(self):
        """Hay un turno o un run en vuelo. Publico porque la barra en vivo lo pregunta cada segundo."""
        return self._busy

    @property
    def autopilot(self):
        """El bucle autonomo, atado al router y al workspace EN VIGOR: tras un cambio se rehace.

        Nunca se rehace con un bucle corriendo: dos escritores sobre el mismo repositorio es el fallo
        que la cola existe para evitar.
        """
        key = (id(self.router), str(self.config.workspace))
        running = self._autopilot is not None and self._autopilot.state().get("running")
        if self._autopilot is None or (key != self._autopilot_key and not running):
            self._autopilot = Autopilot(self.config, runner=self.run_autonomous,
                                        planner=model_planner(self.router, self.config),
                                        bus=self.bus)
            self._autopilot_key = key
        return self._autopilot

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

    def rename_session(self, session_id, title, project=None):
        renamed = Transcripts(self._project_root(project)).rename(session_id, title)
        if renamed:
            self.bus.emit("chat.rename", "%s -> %s" % (session_id, str(title)[:60]))
        return renamed

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
        # El comando de test se resuelve por proyecto antes que por maquina (`runner.config_for`).
        try:
            result, triad = runner.run_triad(self.config, root, goal, self.router, bus=self.bus,
                                             test_command=test_command)
            self._triad = triad
            self.last = result.as_dict()
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
        return self.run_autonomous(goal, root).get("exit", 10)

    def run_autonomous(self, goal, root):
        """Un ciclo autonomo: la triada entera CON su veredicto, que es lo que decide commit o alto."""
        result, _triad = runner.run_triad(self.config, root, goal, self.router, bus=self.bus)
        self.last = result.as_dict()
        return self.last

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
