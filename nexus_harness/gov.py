"""Las vistas de gobernanza: la GUI de NexusProtocol, servida DENTRO de este arnes.

Por que un proxy de loopback y no una copia
-------------------------------------------
La GUI de gobernanza son ~9.400 lineas de render (pestanas, formularios, tarjetas, graficas, i18n) y
volver a escribirla aqui seria un segundo producto que se separa del primero a la primera correccion.
NexusProtocol ya expone esa GUI como un servidor de loopback con su token, su sesion y su CSP; este
modulo lo arranca EN SU PROPIO PROCESO, en un puerto efimero, y reenvia por el las peticiones de la
vista. Una sola implementacion de la gobernanza, dos consumidores.

Lo que el arnes aporta encima, y nada mas
----------------------------------------
* **La barra de navegacion**: la misma del chat, inyectada en el HTML que sirve el protocolo, para que
  el operador no vea dos programas con dos menus.
* **El espacio de nombres**: el `/api/...` del protocolo pasa a `/gov/api/...`, porque `/api/state`
  existe en los dos y quieren decir cosas distintas. La traduccion es textual y se comprueba: si
  quedara un `/api/` sin traducir, la vista lo diria en vez de fallar en silencio.
* **El ciclo de vida**: el servidor de gobernanza vive mientras vive el arnes y muere con el
  (`down()`), en vez de quedar suelto en el puerto.
* **Los controles del arnes**: MCP, puente movil y triada de modelos se inyectan como secciones
  propias en la vista de setup, porque el operador los busca ahi y no en un modal perdido.
"""
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from html import escape
from pathlib import Path
from urllib.parse import urlencode

PROTOCOL = Path(os.environ.get("NEXUS_PROTOCOL") or r"C:\Proyectos\NexusProtocol")
WORKSPACE = Path(os.environ.get("NEXUS_WORKSPACE") or r"C:\Proyectos")
LANG = "es"
TIMEOUT_S = 180
# Vista del arnes -> pestana real del protocolo. `hive` no se ofrece aparte: el puente movil vive en
# setup, que es donde el operador lo busca.
VIEWS = (("setup", "triad", "01 Setup, Modelos & Conectores"),
         ("projects", "projects", "02 Proyectos & Auto-Spec"),
         ("skills", "skills", "03 Skills & Architect"),
         ("stats", "stats", "04 Stats, Ledger & Auditoria"))
ALIASES = {"triad": "setup", "hive": "setup", "system": "setup"}
DEFAULT_VIEW = "setup"

_lock = threading.Lock()
_boot = {"server": None, "installer": None, "reason": ""}


# -- nombres de vista ----------------------------------------------------------------------------
def resolve(view):
    """La vista que el arnes sirve, aceptando tambien los nombres del protocolo (`triad`, `hive`)."""
    name = ALIASES.get(str(view or "").strip().lower(), str(view or "").strip().lower())
    return name if name in tuple(row[0] for row in VIEWS) else DEFAULT_VIEW


def tab_of(view):
    """La pestana real del protocolo detras de una vista del arnes."""
    wanted = resolve(view)
    return next(row[1] for row in VIEWS if row[0] == wanted)


def label_of(view):
    wanted = resolve(view)
    return next(row[2] for row in VIEWS if row[0] == wanted)


# -- ciclo de vida del servidor de gobernanza ----------------------------------------------------
def _gui():
    """El modulo de la GUI del protocolo, o (None, motivo)."""
    if str(PROTOCOL) not in sys.path:
        sys.path.insert(0, str(PROTOCOL))
    try:
        from nexus import gui
    except Exception as exc:  # noqa: BLE001 -- cualquier fallo de import es "no esta", y se dice
        return None, "NexusProtocol no es importable desde %s: %s" % (PROTOCOL, exc)
    return gui, ""


def up():
    """Arranca la GUI del protocolo una vez y devuelve (base_url, ""). Un fallo devuelve ("", motivo)."""
    with _lock:
        if _boot["server"] is not None:
            return "http://127.0.0.1:%d" % _boot["server"].server_address[1], ""
        if _boot["reason"]:
            return "", _boot["reason"]
        gui, reason = _gui()
        if gui is None:
            _boot["reason"] = reason
            return "", reason
        try:
            server, installer, _url = gui.start(root=str(WORKSPACE), depth=3, lang=LANG)
        except Exception as exc:  # noqa: BLE001 -- se informa del motivo, no se adivina
            _boot["reason"] = "la GUI del protocolo no arranco: %s: %s" % (type(exc).__name__, exc)
            return "", _boot["reason"]
        _boot["server"], _boot["installer"] = server, installer
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2},
                         name="nexus-gui", daemon=True).start()
        return "http://127.0.0.1:%d" % server.server_address[1], ""


def down():
    """Para el servidor de gobernanza. Se llama al cerrar: un puerto suelto y un hilo vivo no dejan
    salir al proceso, y el motor congelado es justo el que mas lo nota."""
    with _lock:
        server = _boot["server"]
        _boot["server"], _boot["installer"] = None, None
    if server is None:
        return False
    try:
        server.shutdown()
        server.server_close()
    except OSError:
        return False
    return True


def status():
    """Lo que la vista de chat necesita saber: si la gobernanza esta disponible, y por que no."""
    base, reason = up()
    if not base:
        return {"ok": False, "reason": reason}
    return {"ok": True, "url": base, "views": [{"name": name, "label": label}
                                               for name, _tab, label in VIEWS]}


# -- transporte ----------------------------------------------------------------------------------
def _request(url, data=None, headers=None, method=None):
    """Una peticion al servidor de gobernanza. Devuelve (status, headers, body bytes)."""
    request = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()
    except (urllib.error.URLError, OSError) as exc:
        return 599, {}, ("la GUI del protocolo no contesto: %s" % exc).encode("utf-8")


def _session():
    return _boot["installer"].session_id if _boot["installer"] is not None else ""


def action(path, payload, method="POST"):
    """Reenvia una accion del navegador a la GUI del protocolo. Devuelve (status, payload).

    La sesion viaja en cookie Y en cabecera porque el servidor del protocolo exige las dos formas: la
    cookie es la credencial de un formulario sin script, y la cabecera la de un POST JSON. Las dos
    las pone este proceso, asi que el navegador no necesita ninguna llave de la gobernanza.
    """
    base, reason = up()
    if not base:
        return 503, {"ok": False, "reason": reason}
    body = None
    if method == "POST":
        body = json.dumps(payload or {}).encode("utf-8")
    elif payload:
        # Una lectura con parametros (`?since=`, `?k=`) los lleva en la URL: perderlos aqui daria una
        # respuesta plausible de otra pregunta, que es la peor clase de error.
        path = "%s?%s" % (path, urlencode({key: value for key, value in payload.items()
                                           if value not in (None, "")}))
    session = _session()
    headers = {"Cookie": "nexus_session=%s; nexus_lang=%s" % (session, LANG),
               "X-Nexus-Session": session, "Content-Type": "application/json",
               "Accept": "application/json"}
    status, _headers, raw = _request(base + path, data=body, headers=headers, method=method)
    text = raw.decode("utf-8", errors="replace")
    try:
        return status, json.loads(text)
    except ValueError:
        return status, {"ok": status < 400, "raw": text[:2000]}


# -- la vista ------------------------------------------------------------------------------------
API_REF = re.compile(r'(["\'(])/api/')


def rewrite(html):
    """`/api/...` -> `/gov/api/...`: las rutas del protocolo dentro del espacio del arnes.

    Se cuentan las sustituciones y el numero queda en un comentario del documento servido: una ruta
    sin traducir no falla aqui, falla en el navegador del operador, que es el peor sitio para
    averiguarlo.
    """
    rewritten, count = API_REF.subn(lambda match: match.group(1) + "/gov/api/", html)
    return rewritten, count


def refusal_page(reason):
    """Cuando la gobernanza no esta, la vista no se queda en blanco: dice que falta y donde se mira."""
    links = "".join('<a class="hnav-link" href="/gov?tab=%s">%s</a>' % (view, label)
                    for view, _tab, label in VIEWS)
    return ("<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Nexus-Harness &middot; gobernanza</title><style>%s%s</style></head><body>"
            "<nav class=\"hnav\"><a class=\"hnav-link\" href=\"/\">\U0001f4ac Espacio de trabajo</a>"
            "%s</nav><main class=\"hfail\"><h1>La gobernanza no esta disponible</h1><p>%s</p>"
            "<p>El arnes sirve la GUI de NexusProtocol desde <code>%s</code>. Si el repositorio vive en "
            "otro sitio, define <code>NEXUS_PROTOCOL</code> con su ruta y vuelve a abrir esta vista.</p>"
            "</main></body></html>" % (NAV_CSS, FAIL_CSS, links, escape(str(reason)), PROTOCOL))


FAIL_CSS = """
body{margin:0;background:var(--bg,#0a0c0f);color:var(--fg,#e7eef6);
  font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.hfail{max-width:44rem;margin:12vh auto;padding:0 1.5rem}
.hfail h1{font-size:1.35rem;margin:0 0 .6rem}
.hfail p{color:var(--muted,#8b97a6);margin:.5rem 0}
code{background:var(--card2,#151b23);border:1px solid var(--line,#232b35);border-radius:6px;
  padding:.1rem .35rem;font-size:.85em}
"""


def nav(active, token=""):
    """La barra del arnes dentro de una pagina del protocolo."""
    suffix = ("?token=%s" % token) if token else ""
    # El enlace al chat nunca va "activo" aqui: esta pagina ES una vista de gobernanza.
    links = ['<a class="hnav-link" href="/%s">%s</a>'
             % (suffix, "\U0001f4ac Espacio de trabajo")]
    links += ['<a class="hnav-link%s" href="/gov?tab=%s%s">%s</a>'
              % (" on" if view == resolve(active) else "", view,
                 ("&token=%s" % token) if token else "", label)
              for view, _tab, label in VIEWS]
    return ('<style>%s</style><nav class="hnav" id="hnav">%s</nav>' % (NAV_CSS, "".join(links)))


NAV_CSS = """
.hnav{display:flex;gap:.35rem;align-items:center;flex-wrap:wrap;padding:.55rem .9rem;
  background:var(--card,#11151b);border-bottom:1px solid var(--line,#232b35);
  font:500 .86rem/1.2 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;position:sticky;top:0;z-index:50}
.hnav-link{padding:.45rem .7rem;border-radius:9px;text-decoration:none;color:var(--muted,#8b97a6);
  border:1px solid transparent;white-space:nowrap}
.hnav-link:hover{color:var(--fg,#e7eef6);background:var(--card2,#151b23);border-color:var(--line,#232b35)}
.hnav-link.on{color:#fff;background:var(--accent,#3b82f6);border-color:var(--accent,#3b82f6)}
"""


def page(view, token="", extra="", lang=LANG):
    """El HTML de una vista de gobernanza: el del protocolo, con la barra del arnes y lo del arnes.

    Devuelve (html, ""). Un fallo devuelve ("", motivo): la vista no puede quedarse en blanco sin
    decir por que, y el motivo es lo unico util para arreglarlo.
    """
    base, reason = up()
    if not base:
        return "", reason
    fresh = _boot["installer"].reissue_token()
    # `t` es el nombre del token de un solo uso en la URL del protocolo (`consume_token`), y `token`
    # no existe alli: con el nombre equivocado la vista se resuelve en un 403 limpio, que es lo que
    # paso la primera vez que se probo esto.
    status, _headers, raw = _request("%s/?tab=%s&lang=%s&t=%s"
                                     % (base, tab_of(view), lang, fresh))
    if status != 200:
        return "", "la vista %s no se pudo renderizar (HTTP %s)" % (label_of(view), status)
    html = raw.decode("utf-8", errors="replace")
    html, replaced = rewrite(html)
    bar = nav(view, token) + extra
    body = html.find("<body")
    insert = html.find(">", body) + 1 if body >= 0 else 0
    html = html[:insert] + bar + html[insert:]
    html = html.replace("<title>", "<!-- %d rutas del protocolo reescritas --><title>" % replaced, 1)
    return html, ""
