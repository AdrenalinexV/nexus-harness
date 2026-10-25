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
import os
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import __version__
from .cockpit import Cockpit

# PyInstaller unpacks data under `sys._MEIPASS`; a source checkout has `web/` next to this file. One
# expression, so the frozen engine and the checkout serve the same front-end.
_FROZEN = getattr(sys, "_MEIPASS", "")
WEB = (Path(_FROZEN) / "web") if _FROZEN else (Path(__file__).resolve().parent / "web")
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
         ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json",
         ".woff2": "font/woff2"}
JSON_TYPE = "application/json; charset=utf-8"
# El contrato con el frontend. Se publica en `/api/health` para que una pagina nueva pueda DETECTAR un
# motor viejo: sin esto, un proceso lanzado antes de un cambio deja botones que no responden y el
# operador no tiene forma de saber por que (medido: las vistas de gobernanza daban 404 y no lo decia
# nadie).
API_VERSION = 2


class Handler(BaseHTTPRequestHandler):
    server_version = "NexusHarness/" + __version__

    def log_message(self, *_args):
        return

    @property
    def cockpit(self):
        return self.server.cockpit

    # -- plumbing ----------------------------------------------------------------------------
    def _send(self, code, body, content_type=JSON_TYPE, extra=()):
        data = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in extra:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _page(self, body, content_type=None):
        """Una pagina del arnes. Deja el token en una cookie: un `<form>` no puede poner cabeceras, y
        la vista de gobernanza tiene que poder tocar cosas sin script."""
        token = getattr(self.server, "token", "") or ""
        extra = ([("Set-Cookie", "nexus_token=%s; Path=/; SameSite=Strict; HttpOnly" % token)]
                 if token else [])
        return self._send(200, body, content_type or TYPES[".html"], extra)

    def _see_other(self, location):
        """303 y a otra cosa: es lo que evita que recargar reenvie el ultimo formulario."""
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return None

    def _cookie(self, name):
        for chunk in (self.headers.get("Cookie") or "").split(";"):
            key, _, value = chunk.strip().partition("=")
            if key == name:
                return value
        return ""

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
        sent = self.headers.get("X-Nexus-Token") or self._cookie("nexus_token")
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
            return self._page((WEB / "index.html").read_bytes())
        if path == "/gov":
            return self._gov((query.get("tab") or [""])[0])
        if path == "/settings":
            from . import settings
            return self._page(settings.screen(self.cockpit, query))
        if path.startswith("/api/settings/"):
            from . import settings_api
            answer = settings_api.handle(self.cockpit, "GET", path, query, {})
            if answer is not None:
                return self._json(*answer)
        if path.startswith("/gov/api/"):
            return self._forward(path, query, {})
        # Los estaticos se sirven por extension, no por lista blanca: una lista se olvida en cuanto se
        # anade un fichero, y el fallo aparece como una pagina sin estilos.
        if Path(path).suffix.lower() in TYPES:
            return self._static(path.lstrip("/"))
        if path == "/api/health":
            return self._json(200, {"ok": True, "seq": self.cockpit.bus.seq,
                                    "version": __version__, "api": API_VERSION})
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
        if path == "/api/onboarding":
            return self._json(200, self.cockpit.onboarding_state())
        if path == "/api/projects":
            from .onboarding import projects as list_projects
            workspace = (query.get("workspace") or [None])[0]
            return self._json(200, {"projects": list_projects(workspace)})
        if path == "/api/mcp":
            return self._json(200, self.cockpit.mcp_state())
        if path == "/api/skills":
            name = (query.get("name") or [""])[0]
            payload = self.cockpit.skill_read(name) if name else self.cockpit.skills_list()
            return self._json(200 if payload.get("ok", True) else 404, payload)
        if path == "/api/bridge/daemon":
            return self._json(200, self.cockpit.daemon_state())
        if path == "/api/events":
            since = int((query.get("since") or ["0"])[0] or 0)
            return self._json(200, {"events": self.cockpit.bus.since(since),
                                    "seq": self.cockpit.bus.seq})
        if path == "/api/gov":
            from . import gov
            return self._json(200, gov.status())
        return self._json(404, {"ok": False, "reason": "no route %s" % path})

    # -- la gobernanza, servida desde aqui ------------------------------------------------------
    def _gov(self, tab):
        """La vista de gobernanza: el HTML real del protocolo, con la barra del arnes dentro.

        El fallo se dice en una pagina, no en un 500 vacio: si NexusProtocol no esta donde el
        repositorio dice, el operador tiene que leerlo aqui y no en la consola del motor.
        """
        from . import gov, panels
        token = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
        extra = panels.harness_sections(self.cockpit) if gov.resolve(tab) == "setup" else ""
        html, reason = gov.page(tab, token, extra)
        return self._page(html if html else gov.refusal_page(reason))

    def _forward(self, path, query, body):
        """Reenvia una accion del navegador a la GUI del protocolo: una implementacion, dos consumidores."""
        from . import gov
        payload = dict(body or {})
        payload.update({key: values[0] for key, values in query.items() if key != "token"})
        status, answer = gov.action(path[len("/gov"):], payload,
                                    method="POST" if body else "GET")
        return self._json(status, answer)

    # -- POST --------------------------------------------------------------------------------
    def do_POST(self):  # noqa: N802
        if self._blocked():
            return None
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        # Los formularios de la pantalla de configuracion son formularios de verdad (urlencoded), asi
        # que se leen ANTES de intentar el cuerpo JSON: ese intento consume el flujo y dejaria vacio al
        # que de verdad sabe leerlo.
        if path in ("/api/settings", "/api/settings/do"):
            return self._settings_action(path)
        if path.startswith("/api/settings/"):
            from . import settings_api
            answer = settings_api.handle(self.cockpit, "POST", path, {}, self._form())
            if answer is not None:
                return self._json(*answer)
        body = self._body()
        if path.startswith("/gov/api/"):
            return self._forward(path, query, body)
        if path == "/gov/action":
            return self._gov_action(body)
        if path == "/api/chat":
            ok, payload = self.cockpit.send(body.get("text"), body.get("attachments") or [])
            if ok:
                return self._json(202, dict(payload, ok=True))
            busy = "in flight" in str(payload)
            return self._json(409 if busy else 400, {"ok": False, "reason": payload})
        if path == "/api/onboarding":
            return self._json(200, self.cockpit.onboarding_apply(body))
        if path == "/api/mcp":
            return self._json(200, self.cockpit.mcp_reload())
        if path == "/api/skills":
            saved = self.cockpit.skill_save(body.get("name"), body.get("text"))
            return self._json(200 if saved.get("ok") else 400, saved)
        if path == "/api/bridge/daemon":
            if str(body.get("action") or "toggle") == "stop":
                return self._json(200, self.cockpit.daemon_stop())
            return self._json(200, self.cockpit.daemon_toggle(body.get("provider") or ""))
        if path == "/api/stop":
            return self._json(200, {"ok": True, "stopped": self.cockpit.stop()})
        if path == "/api/shutdown":
            # The desktop shell closes the window and asks the engine to leave: without this, killing
            # PyInstaller's bootloader parent leaves the real engine running and holding its own exe,
            # which is exactly what stops the next installer from replacing it.
            self._json(200, {"ok": True, "version": __version__})
            threading.Thread(target=self.server.stop_engine, daemon=True).start()
            return None
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
        if path == "/api/chat/rename":
            done = self.cockpit.rename_session(body.get("id"), body.get("title"), body.get("project"))
            return self._json(200 if done else 404, {"ok": done})
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

    def _form(self):
        """El cuerpo de un formulario de verdad: urlencoded, o JSON si alguien lo manda asi."""
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        if "json" in (self.headers.get("Content-Type") or ""):
            try:
                payload = json.loads(raw or "{}")
            except ValueError:
                return {}
            return payload if isinstance(payload, dict) else {}
        return {key: values[0] for key, values in parse_qs(raw, keep_blank_values=True).items()}

    def _settings_action(self, path):
        """Guarda o ejecuta lo que mando la pantalla de configuracion, y vuelve al panel con la nota.

        Responde un 303 en vez de un JSON porque quien manda es un `<form>`: asi funciona sin script, y
        recargar despues no reenvia el guardado.
        """
        from . import settings
        payload = self._form()
        if path == "/api/settings":
            note, ok = settings.save(self.cockpit, payload)
        else:
            note, ok, section = settings.action(self.cockpit, payload)
            payload.setdefault("section", section)
        target = "/settings?section=%s&note=%s%s" % (quote(str(payload.get("section") or "modelos")),
                                                     quote(note), "" if ok else "&bad=1")
        sub = str(payload.get("sub") or payload.get("back") or "")
        if sub:
            target += "&sub=" + quote(sub)
        return self._see_other(target)

    def _gov_action(self, body):
        """Los controles del ARNES dentro de la vista de gobernanza (MCP, puente movil), por formulario.

        No pasa por `/api/*` a proposito: un formulario sin script no puede poner la cabecera del
        token, y estas dos cosas tienen que funcionar tambien con el script bloqueado. Responde un 303
        de vuelta a la vista, que es lo que evita reenviar la accion al recargar.
        """
        what = str(body.get("what") or "")
        if what == "bridge":
            answer = (self.cockpit.daemon_toggle(str(body.get("provider") or ""))
                      if str(body.get("on") or "") == "on" else self.cockpit.daemon_stop())
        elif what == "mcp":
            answer = self.cockpit.mcp_reload()
        else:
            answer = {"ok": False, "reason": "accion desconocida: %r" % what}
        target = str(body.get("next") or "/gov?tab=setup")
        if not answer.get("ok", True):
            target += ("&" if "?" in target else "?") + "problem=" + str(answer.get("reason"))[:120]
        return self._see_other(target)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def stop_engine(self):
        """Leave for real: close the socket, then exit the process (not just the HTTP loop)."""
        from . import gov
        try:
            gov.down()
            self.shutdown()
            self.server_close()
        finally:
            os._exit(0)

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
