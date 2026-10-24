"""The cockpit: a local HTTP server with one page and six endpoints, standard library only.

The shape is OpenCode's (server owns the session, the browser is a thin client that polls) at the size
this project can defend: `http.server` + `json` instead of a framework.

    GET  /                 the page
    GET  /api/state        config, roles, models, projects, last run, relay, bridge
    GET  /api/events?since=N  the transcript, by sequence number
    GET  /api/models       local model ids and current role specs
    POST /api/run          {goal, project} -> 202, or 409 while a run is in flight
    POST /api/roles        {role, spec} -> swap a model without restarting
    POST /api/bridge       run what the phone queued in .nexus/hive/queue.json

One run at a time is a deliberate cap: two triads on one repository is the failure mode this cap
exists for, and a lock is cheaper than a scheduler.
"""
import json
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .bridge import Bridge
from .config import HarnessConfig
from .context_router import ContextRouter
from .events import Bus
from .gate import Gate
from .judge import Judge
from .providers import Router
from .session_relay import SessionRelay
from .tools import default_registry
from .triad_loop import Triad
from .ui_css import CSS
from .ui_html import page
from .ui_js import JS

JSON_HEADERS = {"Content-Type": "application/json; charset=utf-8"}


def _dirs(workspace):
    try:
        return sorted(path.name for path in workspace.iterdir()
                      if path.is_dir() and not path.name.startswith(("_", ".")))
    except OSError:
        return []


class Cockpit:
    """The server's brain: one run at a time, and everything the page needs to see it happen."""

    def __init__(self, config=None, bus=None, runner=None, bridge=None):
        self.config = config or HarnessConfig.load()
        self.bus = bus or Bus()
        self.router = Router(self.config)
        self.bridge = bridge or Bridge(self.config.workspace, bus=self.bus)
        self._runner = runner
        self._lock = threading.Lock()
        self._running = False
        self.last = None
        self._catalog = (0.0, None)

    def projects(self):
        return _dirs(self.config.workspace)

    def catalog(self):
        """The model catalogue, cached for 15 s: the page polls, and a probe per poll would hammer two
        local servers to answer a question whose answer changes when the operator loads a model."""
        stamp, value = self._catalog
        if value is not None and time.time() - stamp < 15:
            return value
        value = dict(self.router.catalog(), projects=self.projects())
        self._catalog = (time.time(), value)
        return value

    def refresh_catalog(self):
        self._catalog = (0.0, None)
        return self.catalog()

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

    def state(self):
        pending = self.bridge.pending()
        return {"running": self._running,
                "config": dict(self.config.public(), root=str(self.config.default_root)),
                "roles": self.router.describe(), "models": self.catalog(),
                "run": self.run_payload(), "relay": self._relay_status(),
                "bridge": {"pending": len(pending), "items": pending},
                "seq": self.bus.seq, "port": self.config.port}

    def _relay_status(self):
        root = self.config.default_root
        prompt = root / ".nexus" / "NEXT_SESSION_PROMPT.md"
        sessions_dir = root / ".nexus" / "harness" / "sessions"
        started = self._latest("session.start")
        budget = self._latest("budget")
        return {"session": (started or {}).get("payload", {}).get("session"),
                "sessions": sorted(path.stem for path in sessions_dir.glob("session_*.json"))
                if sessions_dir.is_dir() else [],
                "handovers": [event["payload"].get("handover") for event in self.bus.all()
                              if event["kind"] == "session.relay"],
                "prompt_exists": prompt.is_file(),
                "budget": (budget or {}).get("payload", {}).get("budget", {})}

    def swap(self, role, spec):
        if role not in ("director", "worker", "judge"):
            return False, "role must be director, worker or judge"
        try:
            info = self.router.swap(role, spec)
        except Exception as exc:
            return False, str(exc)
        self.refresh_catalog()
        return True, info.__dict__

    def start(self, goal, project=None, test_command=None):
        """Start a run in a thread. Refuses while one is in flight, which is the cap.

        `test_command` is per run because it belongs to the project, not to the harness: the cockpit
        lets the operator declare it next to the goal, so a project without one is a visible gap
        (`tests = not configured`) instead of a silent green.
        """
        goal = str(goal or "").strip()
        if not goal:
            return False, "a goal is required"
        with self._lock:
            if self._running:
                return False, "a run is already in flight"
            self._running = True
        root = self.config.default_root
        if project:
            candidate = self.config.workspace / str(project)
            if not candidate.is_dir():
                with self._lock:
                    self._running = False
                return False, "project not found under %s: %s" % (self.config.workspace, project)
            root = candidate
        thread = threading.Thread(target=self._execute, args=(goal, root, test_command), daemon=True)
        try:
            thread.start()
        except RuntimeError as exc:  # the thread could not start: never leave the cap held
            with self._lock:
                self._running = False
            return False, "could not start the run: %s" % exc
        return True, {"goal": goal, "root": str(root)}

    def _execute(self, goal, root, test_command=None):
        run_config = replace(self.config, default_root=root,
                             test_command=test_command or self.config.test_command)
        relay = SessionRelay(root, goal=goal, config=run_config, bus=self.bus)
        relay.start()
        triad = Triad(self.router, run_config, registry=default_registry(root, run_config),
                      gate=Gate(root, run_config), judge=Judge(self.router, run_config.lang),
                      skills=ContextRouter(run_config.lang), bus=self.bus, relay=relay)
        try:
            self.last = triad.run(goal).as_dict()
        except Exception as exc:  # the cockpit must still show what happened
            self.bus.emit("worker.error", "%s: %s" % (type(exc).__name__, exc))
            self.last = {"goal": goal, "ok": False, "exit": 10,
                         "summary": "%s: %s" % (type(exc).__name__, exc)}
        finally:
            with self._lock:
                self._running = False

    def run_project(self, goal, root):
        """Synchronous entry used by the bridge: returns the exit code the gate produced."""
        if self._runner is not None:
            return self._runner(goal, root)
        run_config = replace(self.config, default_root=root)
        relay = SessionRelay(root, goal=goal, config=run_config, bus=self.bus)
        relay.start()
        triad = Triad(self.router, run_config, registry=default_registry(root, run_config),
                      gate=Gate(root, run_config), judge=Judge(self.router, run_config.lang),
                      skills=ContextRouter(run_config.lang), bus=self.bus, relay=relay)
        result = triad.run(goal)
        self.last = result.as_dict()
        return result.exit

    def tick_bridge(self):
        return self.bridge.tick(self.run_project)


class Handler(BaseHTTPRequestHandler):
    server_version = "NexusHarness/0.1"

    def log_message(self, *_args):
        return

    @property
    def cockpit(self):
        return self.server.cockpit

    def _send(self, code, body, content_type="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, payload):
        self._send(code, json.dumps(payload, ensure_ascii=False), JSON_HEADERS["Content-Type"])

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except ValueError:
            return {}

    def do_GET(self):  # noqa: N802 -- BaseHTTPRequestHandler's contract
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path in ("/", "/index.html"):
            return self._send(200, page(CSS, JS), "text/html; charset=utf-8")
        if parsed.path == "/api/state":
            return self._json(200, self.cockpit.state())
        if parsed.path == "/api/events":
            since = int((query.get("since") or ["0"])[0] or 0)
            return self._json(200, {"events": self.cockpit.bus.since(since),
                                    "seq": self.cockpit.bus.seq})
        if parsed.path == "/api/models":
            return self._json(200, self.cockpit.router.catalog())
        if parsed.path == "/api/relay":
            return self._json(200, self.cockpit._relay_status())
        if parsed.path == "/api/health":
            return self._json(200, {"ok": True, "seq": self.cockpit.bus.seq})
        return self._json(404, {"reason": "no route %s" % parsed.path})

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        body = self._body()
        if parsed.path == "/api/run":
            ok, payload = self.cockpit.start(body.get("goal"), body.get("project"),
                                             body.get("test_command"))
            if ok:
                return self._json(202, dict(payload, ok=True))
            busy = "in flight" in str(payload)
            return self._json(409 if busy else 400, {"ok": False, "reason": payload})
        if parsed.path == "/api/roles":
            ok, payload = self.cockpit.swap(body.get("role"), body.get("spec"))
            return self._json(200 if ok else 400,
                              {"ok": ok, "info": payload} if ok else {"ok": False, "reason": payload})
        if parsed.path == "/api/bridge":
            rows = self.cockpit.tick_bridge()
            return self._json(200, {"ok": True, "ran": len(rows), "rows": rows})
        return self._json(404, {"reason": "no route %s" % parsed.path})


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, cockpit):
        super().__init__(address, Handler)
        self.cockpit = cockpit


def build(cockpit, host=None, port=None):
    """A server bound to the cockpit's config, or to an explicit host/port (port 0 = any)."""
    host = host or cockpit.config.host
    port = int(port if port is not None else cockpit.config.port)
    return Server((host, port), cockpit)


def serve(cockpit=None, host=None, port=None, block=True, out=print):
    cockpit = cockpit or Cockpit()
    server = build(cockpit, host, port)
    actual = server.server_address[1]
    out("Nexus-Harness cockpit on http://%s:%s" % (server.server_address[0], actual))
    if block:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            out("stopped")
        finally:
            server.server_close()
    return server
