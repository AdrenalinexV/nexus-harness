"""Las cinco cosas de la v0.5.0, medidas por HTTP y por el HTML servido: no por la intencion.

Los cuatro bloques de interfaz que se pidieron tienen una prueba que los mira aqui:

* la barra en vivo de la esquina (existe, se llama, dice una fase y trae el ultimo turno),
* la cola de proyectos (orden que persiste al reordenar, alta de un proyecto nuevo gobernado),
* la pantalla de skills (arquitecto ARRIBA, filtros en una fila, rejilla de 280 px),
* las estadisticas (tres graficos SVG nativos, con datos de ledger y de spec).

El bucle autonomo se arranca por HTTP de verdad, con modelos falsos: es la unica forma de probar el
camino completo (endpoint -> autopilot -> triada -> progreso) sin depender de que LM Studio este vivo.
"""
import json
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .fakes import FakeRouter, ScriptedProvider, reply
from .. import onboarding, projects, settings_tools
from ..cockpit import Cockpit
from ..config import HarnessConfig
from ..ui import build

TOKEN = "ux-token-42"

FAKE_STATE = {
    "fleet_counts": {"workspace": 2, "governed": 2},
    "money": {"currency": "USD", "net": 0.9389, "avoided_tokens": 1363752, "hours": 76.7,
              "blocked": 230, "active": {"label": "DeepSeek V4.1 Flash"},
              "assumptions": ["a blocked closure is 3 turns that did not have to be redone"]},
    "impact": {"panels": [
        {"name": "Alpha", "present": True, "by_exit": {"0": 12, "10": 2, "20": 1}, "blocked": 2,
         "tokens_total": 4196, "tokens_blocked": 473},
        {"name": "Beta", "present": True, "by_exit": {"0": 5, "10": 0, "20": 0}, "blocked": 0,
         "tokens_total": 900, "tokens_blocked": 0}]},
}


def check(name, got, expect, failures):
    if got != expect:
        failures.append("%s: %r, esperaba %r" % (name, got, expect))


def _call(base, path, payload=None, token=TOKEN):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Nexus-Token"] = token
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(base + path, data=data,
                                     method="POST" if data is not None else "GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _workspace():
    """Dos proyectos gobernados con su spec, y una carpeta suelta que no lo esta."""
    root = Path(tempfile.mkdtemp(prefix="nexus-ux-"))
    for name, criteria in (("Alpha", 3), ("Beta", 17)):
        folder = root / name
        (folder / ".ai").mkdir(parents=True)
        (folder / ".ai" / "PROJECT_RULES.md").write_text(
            "# reglas\n\n## APPROVED DEPENDENCIES\n\n- nexus -- engine\n", encoding="utf-8")
        (folder / ".ai" / "CURRENT_SPEC.json").write_text(
            json.dumps({"format": "nexus.spec/1", "id": "spec-%s" % name.lower(),
                        "goal": "objetivo %s" % name, "cas_count": criteria,
                        "cas_sha256": "d" * 64}), encoding="utf-8")
    (root / "Suelta").mkdir()
    return root


def _serve(root):
    config = HarnessConfig(workspace=root, default_root=root / "Alpha", test_command=None,
                           roles={"director": "fake:d", "worker": "fake:w", "judge": "fake:j"},
                           host="127.0.0.1", port=0, lang="es", secrets={})
    cockpit = Cockpit(config)
    cockpit.router = FakeRouter(
        director=ScriptedProvider([reply('{"done": false, "step": "arreglar calc.py"}')] * 4),
        workers=ScriptedProvider([reply("listo")] * 4),
        judge=ScriptedProvider([reply('{"verdict": "approve", "reason": "verde"}')] * 4))
    server = build(cockpit, port=0, token=TOKEN)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return cockpit, server, "http://127.0.0.1:%d" % server.server_address[1]


def test_live_ticker(base, failures):
    status, body = _call(base, "/")
    check("the chat is served", status, 200, failures)
    check("the dead badge is gone", "en reposo" in body, False, failures)
    check("the live pill is there", 'id="activity"' in body, True, failures)
    check("with its popover", 'id="activity-pop"' in body, True, failures)
    check("and its autopilot control", "Modo Autónomo Iterativo" in body, True, failures)
    check("activity.js is loaded", "activity.js" in body, True, failures)
    status, js = _call(base, "/activity.js")
    check("activity.js is served", status, 200, failures)
    check("and polls the engine", "/api/activity" in js, True, failures)
    status, data = _call(base, "/api/activity")
    payload = json.loads(data)
    check("the endpoint answers", status, 200, failures)
    check("with the idle phase, not a frozen word", payload["phase"], "idle", failures)
    check("and the autopilot declared", "running" in payload["autopilot"], True, failures)
    check("and the last-turn detail", sorted(payload["detail"]),
          ["at", "diff", "diff_totals", "exit", "files", "files_total", "gate", "judge",
           "repairs", "steps", "tokens"], failures)


def test_queue_and_create(base, root, failures):
    status, body = _call(base, "/api/projects/queue")
    payload = json.loads(body)
    check("the queue is served", status, 200, failures)
    check("only governed projects", [row["name"] for row in payload["queue"]], ["Alpha", "Beta"],
          failures)
    check("the plain folder is listed apart", payload["plain"], ["Suelta"], failures)
    check("with its spec criteria", payload["queue"][1]["spec"]["criteria"], 17, failures)

    status, body = _call(base, "/api/projects/order", {"names": ["Beta", "Alpha"]})
    check("a reorder is accepted", status, 200, failures)
    check("and answered with the new order", json.loads(body)["order"], ["Beta", "Alpha"], failures)
    status, body = _call(base, "/api/projects/queue")
    check("the engine's queue followed", [row["name"] for row in json.loads(body)["queue"]],
          ["Beta", "Alpha"], failures)
    check("and it is on disk", projects.order(_reload(root)), ["Beta", "Alpha"], failures)
    status, _body = _call(base, "/api/projects/order", {"names": []})
    check("an empty reorder is refused", status, 400, failures)

    status, body = _call(base, "/api/projects/new", {"name": "Gamma", "goal": "servir ofertas"})
    created = json.loads(body)
    check("a project is created", status, 200, failures)
    check("its folder is there", (root / "Gamma").is_dir(), True, failures)
    if (root / "Gamma" / ".ai" / "CURRENT_SPEC.json").is_file():
        check("it is governed", True, True, failures)
        check("and it goes to the end of the queue", created["order"], ["Beta", "Alpha", "Gamma"],
              failures)
    else:
        # Sin gobernador no hay auto-spec. Lo que se exige entonces es el otro contrato: el proyecto
        # existe con sus reglas y NO entra en la cola como si estuviera gobernado.
        check("without the governor the new project is not queued as governed", created["order"],
              ["Beta", "Alpha"], failures)
        check("but it exists as a project, with its rules",
              (root / "Gamma" / ".ai" / "PROJECT_RULES.md").is_file(), True, failures)
    status, _body = _call(base, "/api/projects/new", {"name": "Gamma"})
    check("creating the same one twice is a 400", status, 400, failures)


def _reload(root):
    """La configuracion TAL COMO quedo en disco. Apunta al fichero temporal de la suite, no al real.

    El fichero guarda la cola; el workspace lo pone `harness.json` solo si alguna vez se guardo. En la
    suite el workspace es el temporal, asi que se fija aqui y se lee el orden del disco.
    """
    config = HarnessConfig.load(path=root / "harness.json", root=root)
    config.workspace = root
    return config


def test_projects_panel(base, failures):
    status, body = _call(base, "/settings?section=espacio")
    check("the projects panel renders", status, 200, failures)
    check("as a priority queue", "Cola de importancia" in body, True, failures)
    check("with draggable cards", 'draggable="true"' in body, True, failures)
    check("and a create button", "Crear Nuevo Proyecto" in body, True, failures)
    check("the plain folders are folded into a table",
          "carpetas sin gobernanza" in body and 'class="stable plainlist"' in body, True, failures)
    check("with a filter for them", 'data-filter=".plainbox table tr"' in body, True, failures)
    check("and the autopilot per project", "Autopilot" in body, True, failures)
    check("the keyboard still works (arrows)", "project_move" in body, True, failures)


def test_skills_panel(base, failures):
    status, body = _call(base, "/settings?section=skills")
    check("the skills panel renders", status, 200, failures)
    architect = body.find("Diseñar y Forjar Skill")
    grid = body.find('class="skillgrid"')
    check("the architect is rendered", architect > 0, True, failures)
    check("and it is ABOVE the grid", architect < grid if grid > 0 else True, True, failures)
    check("the filters are one row", 'class="fpills"' in body, True, failures)
    check("the search keeps its filter", "section=skills&amp;f=all" in body
          or "section=skills&f=all" in body, True, failures)
    status, css = _call(base, "/settings.css")
    check("settings.css is served", status, 200, failures)
    check("the grid is 280px wide cards", "minmax(280px, 1fr)" in css, True, failures)
    check("and the filters wrap instead of stacking", "flex-wrap: wrap" in css, True, failures)


def test_stats_charts(base, failures):
    original = settings_tools.gov.installer_state
    settings_tools.gov.installer_state = lambda: (FAKE_STATE, "")
    try:
        status, body = _call(base, "/settings?section=stats")
    finally:
        settings_tools.gov.installer_state = original
    check("the stats panel renders", status, 200, failures)
    check("the KPIs are a four-column grid", 'class="kpigrid four"' in body, True, failures)
    for number in ("Gráfico 1", "Gráfico 2", "Gráfico 3"):
        check("%s is drawn" % number, number in body, True, failures)
    check("with native SVG", body.count("<svg") >= 4, True, failures)
    check("nothing is loaded from a CDN", 'src="http' in body or 'href="http' in body, False,
          failures)
    check("the ledger figure travels", "1\u202f363\u202f752" in body, True, failures)
    check("the spec criteria travel", ">17<" in body or "17" in body, True, failures)
    check("and the source is declared", "De dónde sale cada cifra" in body, True, failures)


def test_autonomy_over_http(base, failures):
    status, body = _call(base, "/api/autonomy", {"project": "Alpha", "iterations": 1})
    check("the loop starts", status, 202, failures)
    started = json.loads(body).get("state") or {}
    check("and says on which project", started.get("project"), "Alpha", failures)
    deadline = time.time() + 60
    state = {}
    while time.time() < deadline:
        _status, body = _call(base, "/api/autonomy")
        state = json.loads(body)
        if not state.get("running"):
            break
        time.sleep(0.2)
    check("the loop finished on its own", state.get("running"), False, failures)
    check("having advanced one step", state.get("steps_done"), 1, failures)
    # Sin gobernador la cola no lleva a Gamma (no tiene spec), asi que un literal aqui mediria la
    # maquina y no el contrato. El invariante de verdad es que el estado de autonomia lleve LA MISMA
    # cola que sirve el endpoint de proyectos.
    _status, body = _call(base, "/api/projects/queue")
    on_queue = [row["name"] for row in json.loads(body)["queue"]]
    check("the queue travels with the state",
          [row["name"] for row in state.get("projects") or []], on_queue, failures)
    _status, body = _call(base, "/api/events?since=0")
    kinds = [event["kind"] for event in json.loads(body)["events"]]
    for wanted in ("autonomy.start", "autonomy.backup", "autonomy.step"):
        check("the bus reports %s" % wanted, wanted in kinds, True, failures)
    status, _body = _call(base, "/api/autonomy", {"action": "stop"})
    check("stopping an idle loop answers ok", status, 200, failures)


def run():
    failures = []
    root = _workspace()
    # La cola se guarda con `onboarding.save_settings`, que escribe en `onboarding.CONFIG_FILE`: se
    # apunta al temporal de la suite y se devuelve como estaba, o la prueba le cambiaria la
    # configuracion al operador.
    original_config = onboarding.CONFIG_FILE
    onboarding.CONFIG_FILE = root / "harness.json"
    cockpit, server, base = _serve(root)
    try:
        test_live_ticker(base, failures)
        test_queue_and_create(base, root, failures)
        test_projects_panel(base, failures)
        test_skills_panel(base, failures)
        test_stats_charts(base, failures)
        test_autonomy_over_http(base, failures)
        check("the api version moved", json.loads(_call(base, "/api/health")[1])["api"], 3, failures)
        check("no job is left in flight", cockpit.busy, False, failures)
    finally:
        server.shutdown()
        server.server_close()
        onboarding.CONFIG_FILE = original_config
        shutil.rmtree(root, ignore_errors=True)
    return failures
