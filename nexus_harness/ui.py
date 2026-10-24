"""The local API and the page it serves: standard library only, one window or one tab.

Two guards, because "localhost" is not a security boundary:

* **Cross-site requests are refused.** A page on the internet can POST to 127.0.0.1 without reading the
  answer, so `Sec-Fetch-Site: cross-site` is a 403. Browsers send that header; curl and the desktop
  webview do not.
* **A token, when one is configured.** The desktop app starts the engine with `NEXUS_HARNESS_TOKEN` and
  loads the page with `?token=...`; every `/api/*` call must carry it in `X-Nexus-Token`. Running the
  CLI without a token leaves the API open to local processes only -- a documented choice for a
  developer machine, not a default for a shipped app.

Static files come from `web/` next to this module (and are bundled by PyInstaller), so there is one
front-end, not one per shell.
"""
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from .cockpit import Cockpit

WEB = Path(__file__).resolve().parent / "web"
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
         ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json",
         ".woff2": "font/woff2"}
JSON_TYPE = "application/json; charset=utf-8"


class Handler(BaseHTTPRequestHandler):
    server_version = "NexusHarness/" + __version__

    def log_message(self, *_args):
        return

    @property
    def cockpit(self):
        return self.server.cockpit

    # -- plumbing ----------------------------------------------------------------------------
    def _send(self, code, body, content_type=JSON_TYPE):
        data = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, payload):
        self._send(code, json.dumps(payload, ensure_ascii=False), JSON_TYPE)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _token_ok(self):
        expected = getattr(self.server, "token", "") or ""
        if not expected:
            return True
        sent = self.headers.get("X-Nexus-Token") or ""
        if not sent:
            sent = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
        return secrets.compare_digest(str(sent), str(expected))

    def _blocked(self):
        """True when the request must not be answered. Refuses cross-site and a missing token."""
        if (self.headers.get("Sec-Fetch-Site") or "").lower() == "cross-site":
            self._json(403, {"ok": False, "reason": "cross-site request refused"})
            return True
        if self.path.startswith("/api/") and not self._token_ok():
            self._json(401, {"ok": False, "reason": "missing or wrong X-Nexus-Token"})
            return True
        return False

    def _static(self, name):
        target = (WEB / name).resolve()
        root = WEB.resolve()
        if root not in target.parents and target != root:
            return self._json(404, {"reason": "no route"})
        if not target.is_file():
            return self._json(404, {"reason": "no route %s" % name})
        return self._send(200, target.read_bytes(), TYPES.get(target.suffix.lower(), "text/plain"))

    # -- GET ---------------------------------------------------------------------------------
    def do_GET(self):  # noqa: N802 -- BaseHTTPRequestHandler's contract
        if self._blocked():
            return None
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path in ("/app.css", "/app.js", "/favicon.ico"):
            return self._static(path.lstrip("/"))
        if path == "/api/health":
            return self._json(200, {"ok": True, "seq": self.cockpit.bus.seq,
                                    "version": __version__})
        if path == "/api/state":
            return self._json(200, self.cockpit.state())
        if path == "/api/chat":
            return self._json(200, self.cockpit.chat_state())
        if path == "/api/sessions":
            return self._json(200, {"sessions": self.cockpit.sessions()})
        if path == "/api/memory":
            return self._json(200, self.cockpit.memory_state())
        if path == "/api/models":
            return self._json(200, self.cockpit.catalog())
        if path == "/api/relay":
            return self._json(200, self.cockpit.relay_status())
        if path == "/api/events":
            since = int((query.get("since") or ["0"])[0] or 0)
            return self._json(200, {"events": self.cockpit.bus.since(since),
                                    "seq": self.cockpit.bus.seq})
        return self._json(404, {"ok": False, "reason": "no route %s" % path})

    # -- POST --------------------------------------------------------------------------------
    def do_POST(self):  # noqa: N802
        if self._blocked():
            return None
        path = urlparse(self.path).path
        body = self._body()
        if path == "/api/chat":
            ok, payload = self.cockpit.send(body.get("text"))
            if ok:
                return self._json(202, dict(payload, ok=True))
            busy = "in flight" in str(payload)
            return self._json(409 if busy else 400, {"ok": False, "reason": payload})
        if path == "/api/stop":
            return self._json(200, {"ok": True, "stopped": self.cockpit.stop()})
        if path == "/api/chat/new":
            session = self.cockpit.new_chat(body.get("title") or "", body.get("project"))
            return self._json(200, {"ok": True, "session": session})
        if path == "/api/chat/load":
            session = self.cockpit.load_chat(body.get("id"), body.get("project"))
            if session is None:
                return self._json(404, {"ok": False, "reason": "no such conversation"})
            return self._json(200, {"ok": True, "session": session})
        if path == "/api/chat/delete":
            gone = self.cockpit.delete_session(body.get("id"), body.get("project"))
            return self._json(200 if gone else 404, {"ok": gone})
        if path == "/api/memory":
            if "remove" in body:
                return self._json(200, self.cockpit.memory_remove(body.get("remove")))
            return self._json(200, self.cockpit.memory_add(body.get("text")))
        if path == "/api/run":
            ok, payload = self.cockpit.start(body.get("goal"), body.get("project"),
                                             body.get("test_command"))
            if ok:
                return self._json(202, dict(payload, ok=True))
            busy = "in flight" in str(payload)
            return self._json(409 if busy else 400, {"ok": False, "reason": payload})
        if path == "/api/roles":
            ok, payload = self.cockpit.swap(body.get("role"), body.get("spec"))
            return self._json(200 if ok else 400,
                              {"ok": ok, "info": payload} if ok else {"ok": False, "reason": payload})
        if path == "/api/bridge":
            rows = self.cockpit.tick_bridge()
            return self._json(200, {"ok": True, "ran": len(rows), "rows": rows})
        return self._json(404, {"ok": False, "reason": "no route %s" % path})


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, cockpit, token=""):
        super().__init__(address, Handler)
        self.cockpit = cockpit
        self.token = token or ""


def build(cockpit, host=None, port=None, token=""):
    """Bind the cockpit's config, or an explicit host/port (port 0 = any free port)."""
    host = host or cockpit.config.host
    port = int(port if port is not None else cockpit.config.port)
    return Server((host, port), cockpit, token)


def serve(cockpit=None, host=None, port=None, token=None, block=True, out=print):
    cockpit = cockpit or Cockpit()
    server = build(cockpit, host, port, token or "")
    address, actual = server.server_address[0], server.server_address[1]
    suffix = ("/?token=%s" % server.token) if server.token else "/"
    out("Nexus-Harness on http://%s:%s%s" % (address, actual, suffix))
    cockpit.config.port = actual
    if block:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            out("stopped")
        finally:
            server.server_close()
    return server
