"""El contrato de la cabina, medido por HTTP: credencial, unidades y veredictos.

Tres defectos que ninguna captura enseña, porque los tres salen en verde:

* **U1** el 303 de guardado devolvia al panel sin `?token=`, asi que la pantalla se quedaba sin
  credencial al primer guardado,
* **U3** un campo en porcentaje se escribia tal cual sobre una fraccion: guardar «Memoria» ponia
  `relay_threshold: 70.0` y desactivaba el relevo y la compactacion sin decir nada,
* **U5** el tercer final del gate («no verificable», exit 20/30) no tenia tono propio y se confundia
  con «sin registro».

Lo que se afirma aqui es el valor GUARDADO y la cabecera del 303, no el texto de una nota: una nota
verde solo dice que el POST se acepto.
"""
import json
import shutil
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .fakes import FakeRouter, ScriptedProvider
from .. import activity, onboarding
from ..cockpit import Cockpit
from ..config import HarnessConfig
from ..ui import build

TOKEN = "ui-contract-7"


def check(name, got, expect, failures):
    if got != expect:
        failures.append("%s: %r, esperaba %r" % (name, got, expect))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Un cliente que NO sigue el 303: seguir la redireccion contestaria 200 y no se afirmaria nada."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _post(base, path, fields):
    """POST de formulario (urlencoded) sin seguir redirecciones. Devuelve `(status, location)`."""
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(base + path, data=body, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded", "X-Nexus-Token": TOKEN})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, response.headers.get("Location", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Location", "")


def _get(base, path):
    request = urllib.request.Request(base + path, headers={"X-Nexus-Token": TOKEN})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, response.read().decode("utf-8", "replace")



def _serve(root):
    config = HarnessConfig(workspace=root, default_root=root, test_command=None,
                           roles={"director": "fake:d", "worker": "fake:w", "judge": "fake:j"},
                           host="127.0.0.1", port=0, lang="es", secrets={})
    cockpit = Cockpit(config)
    cockpit.router = FakeRouter(director=ScriptedProvider([]), workers=ScriptedProvider([]),
                                judge=ScriptedProvider([]))
    server = build(cockpit, port=0, token=TOKEN)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return cockpit, server, "http://127.0.0.1:%d" % server.server_address[1]


def _stored(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_token_travels(base, failures):
    """U1: el 303 y la navegacion conservan la credencial."""
    status, location = _post(base, "/api/settings",
                             {"section": "memoria", "budget_limit": "60000"})
    check("el guardado responde 303", status, 303, failures)
    check("y el destino lleva el token", "token=" + TOKEN in location, True, failures)

    status, page = _get(base, "/settings?section=memoria")
    check("la pantalla de configuracion se sirve", status, 200, failures)
    hrefs = [chunk.split('"')[0] for chunk in page.split('href="')[1:]]
    internal = [href for href in hrefs if href.startswith("/")]
    check("navega con al menos las 13 entradas", len([h for h in internal if "/settings?" in h]) >= 13,
          True, failures)
    check("y ninguna pierde el token",
          [href for href in internal if "token=" not in href], [], failures)

    status, index = _get(base, "/")
    check("el chat se sirve", status, 200, failures)
    check("con el token en una meta", 'name="nexus-token" content="%s"' % TOKEN in index, True,
          failures)
    check("y el enlace a configuracion lo lleva", "/settings?token=" + TOKEN in index, True, failures)


def test_units_are_normalised(base, failures):
    """U3: el formulario habla % y el fichero guarda fraccion; 150 % se rechaza."""
    status, location = _post(base, "/api/settings",
                             {"section": "memoria", "relay_threshold": "70",
                              "compact_threshold": "55"})
    check("guardar 70 y 55 responde 303", status, 303, failures)
    check("y la nota es verde", "bad=1" in location, False, failures)
    stored = _stored(onboarding.CONFIG_FILE)
    check("el relevo se guarda en fraccion", stored.get("relay_threshold"), 0.7, failures)
    check("y la compactacion tambien", stored.get("compact_threshold"), 0.55, failures)

    status, location = _post(base, "/api/settings",
                             {"section": "memoria", "relay_threshold": "150"})
    check("un 150 % responde 303", status, 303, failures)
    check("pero se declara en rojo", "bad=1" in location, True, failures)
    check("y NO toca el fichero", _stored(onboarding.CONFIG_FILE).get("relay_threshold"), 0.7,
          failures)

    status, page = _get(base, "/settings?section=memoria")
    check("el formulario vuelve a pintar el porcentaje",
          'name="relay_threshold" value="70"' in page, True, failures)
    check("y no un 7000", "7000" in page, False, failures)


def test_verdict_classes(failures):
    """U5: verde, rojo y «no verificable» son tres finales; «sin registro» es el cuarto estado."""
    green = activity.summary({"steps": 2, "verdict": {"ok": True, "exit": 0, "checks": []}})
    check("gate verde -> tono ok", green["tone"], "ok", failures)
    check("con su frase de siempre", green["text"].endswith("Gate OK"), True, failures)

    red = activity.summary({"steps": 2, "verdict": {"ok": False, "exit": 10, "checks": []}})
    check("gate rojo -> tono bad", red["tone"], "bad", failures)
    check("y lo dice con el exit", "Gate ROJO (exit 10)" in red["text"], True, failures)

    unknown = activity.summary({"steps": 2, "verdict": {"ok": False, "exit": 20, "checks": []}})
    check("no verificable -> tono warn", unknown["tone"], "warn", failures)
    check("y su propia frase", "NO VERIFICABLE (exit 20)" in unknown["text"], True, failures)
    check("que no es la de rojo", "ROJO" in unknown["text"], False, failures)

    for code in (20, 30):
        check("exit %d es no verificable" % code, activity.verdict_class(
            {"ok": False, "exit": code}), "unavailable", failures)
    check("sin gate no hay veredicto", activity.verdict_class({}), "none", failures)


def test_401_is_not_a_dead_engine(base, failures):
    """U2: el 401 tiene su rama; el consejo de relanzar queda para el fallo de verdad."""
    status, js = _get(base, "/app.js")
    check("app.js se sirve", status, 200, failures)
    check("con una rama explicita para el 401", "status === 401" in js, True, failures)
    check("que habla de credencial y no de reiniciar", "pide token" in js, True, failures)


def test_aborted_client_does_not_kill_the_engine(base, failures):
    """Una pestaña cerrada a mitad de respuesta no puede tumbar el motor ni llenar el log.

    Se manda una peticion por socket y se cierra sin leer: el `sendall` del servidor falla con
    `ConnectionAborted`/`BrokenPipe`. El handler lo descarta; lo que se afirma es que el siguiente
    cliente sigue siendo atendido.
    """
    import socket
    from urllib.parse import urlparse
    host, port = urlparse(base).hostname, urlparse(base).port
    for _attempt in range(3):
        sock = socket.create_connection((host, port), timeout=5)
        sock.sendall(b"GET /api/health HTTP/1.0\r\nHost: x\r\n\r\n")
        sock.close()
    status, body = _get(base, "/api/health")
    check("el motor sigue atendiendo tras un cliente abortado", status, 200, failures)
    check("y su contrato sigue intacto", "api" in body, True, failures)


def _emoji(text):
    """Los caracteres que no son un sistema de iconos: pictogramas y dingbats."""
    return sorted({ch for ch in text if 0x1F300 <= ord(ch) <= 0x1FAFF or 0x2600 <= ord(ch) <= 0x27BF})


def test_iconography_is_svg(base, failures):
    """Cero emojis y cero assets externos en las tres pantallas y en sus scripts.

    Un emoji cambia de forma por sistema operativo, no se alinea con el texto ni hereda el color: no
    es un icono, es el slop mas reconocible que existe. El sprite vive en `ui_icons.py` y se sirve
    inline; una pagina que necesita la red para verse bien esta rota en un avion.
    """
    status, index = _get(base, "/")
    check("el chat se sirve", status, 200, failures)
    check("el chat no tiene emojis", _emoji(index), [], failures)
    check("el chat no carga nada de fuera", ('src="http' in index) or ('href="http' in index), False,
          failures)
    check("y trae el sprite inline", '<symbol id="i-search"' in index, True, failures)
    for name in ("modelos", "espacio", "seguridad", "memoria", "skills", "mcp", "puente",
                 "autonomia", "kanvas", "vps", "apariencia", "stats", "about"):
        status, page = _get(base, "/settings?section=" + name)
        check("settings/%s se sirve" % name, status, 200, failures)
        check("settings/%s no tiene emojis" % name, _emoji(page), [], failures)
    for asset in ("app.js", "chat_stream.js", "export.js", "sessions.js", "composer.js", "activity.js",
                  "settings.js", "token.js"):
        status, body = _get(base, "/" + asset)
        check("%s se sirve" % asset, status, 200, failures)
        check("%s no tiene emojis" % asset, _emoji(body), [], failures)


def test_the_navigation_has_one_door(base, failures):
    """Una sola puerta en la cabina: Configuración. El chat no repite el indice del manual.

    Antes habia un bloque «Puertas» en la barra lateral con tres enlaces que ya vivian (o deben vivir)
    dentro de Configuración; y el arbol del manual desplegaba un submenú anidado de la triada que no se
    abria bien y repetia las tarjetas del propio panel.
    """
    status, index = _get(base, "/")
    check("el chat se sirve", status, 200, failures)
    check("el chat no repite el indice (sin bloque Puertas)", "Puertas" in index, False, failures)
    check("y lleva Configuración en la cabecera", 'id="settings"' in index, True, failures)
    status, page = _get(base, "/settings?section=kanvas")
    check("el manual se sirve", status, 200, failures)
    check("sin submenus anidados", "<details" in page, False, failures)
    check("con el tablero como seccion propia", "Tablero (Kanvas)" in page, True, failures)
    check("y las trece secciones planas", page.count('class="scat-leaf'), 13, failures)


def run():
    failures = []
    root = Path(tempfile.mkdtemp(prefix="nexus-uicontract-"))
    original_config = onboarding.CONFIG_FILE
    onboarding.CONFIG_FILE = root / "harness.json"
    _cockpit, server, base = _serve(root)
    try:
        test_token_travels(base, failures)
        test_units_are_normalised(base, failures)
        test_verdict_classes(failures)
        test_401_is_not_a_dead_engine(base, failures)
        test_iconography_is_svg(base, failures)
        test_the_navigation_has_one_door(base, failures)
        test_aborted_client_does_not_kill_the_engine(base, failures)
    finally:
        server.shutdown()
        server.server_close()
        onboarding.CONFIG_FILE = original_config
        shutil.rmtree(root, ignore_errors=True)
    return failures
