"""La API JSON del arnes, en un sitio: `(status, payload)` o `None` si la ruta no es de aqui.

Existia dentro de `ui.py`, entre el transporte (socket, token, cabeceras, estaticos) y las paginas. Al
anadir la barra en vivo, la cola de proyectos y el bucle autonomo, el fichero pasaba de la ley de 400
lineas por culpa de rutas que no tienen nada que ver con HTTP. Separarlo tiene ademas una ventaja
medible: se puede probar la API sin abrir un puerto.

Lo que NO vive aqui: `/api/shutdown` (necesita cerrar el servidor, y eso es transporte) y el editor de
skills (`settings_api.py`, que tiene su propia validacion de rutas).
"""
import time
from pathlib import Path

from .platform import ledger
from . import __version__, activity, gov, projects

API_VERSION = 3
NAME = "Nexus-Harness"
# Cuando arranco este proceso. `/api/health` lo publica como `uptime`, que es la unica forma honesta de
# que un panel diga «este motor lleva encendido X»: leerlo del reloj del navegador seria inventarlo.
STARTED = time.time()


def _one(query, key, default=""):
    values = (query or {}).get(key)
    if isinstance(values, list):
        return values[0] if values else default
    return default if values is None else values


# -- lecturas ------------------------------------------------------------------------------------
def activity_payload(cockpit):
    """Lo que pinta la pildora de la esquina: fase viva, progreso, autopilot y el ultimo resultado."""
    chat = cockpit.chat_state()
    root = Path(chat.get("project") or cockpit.root)
    return activity.state(cockpit.bus.all(), running=cockpit.busy, config=cockpit.config,
                          last=chat.get("last"), budget=chat.get("budget"),
                          autopilot=cockpit.autopilot.state(),
                          criteria=projects.spec_of(root).get("criteria") or 0, root=root)


def get(cockpit, path, query=None):
    query = query or {}
    if path == "/api/consult":
        from . import consult_api
        return consult_api.get(cockpit)
    if path == "/api/health":
        return 200, {"ok": True, "seq": cockpit.bus.seq, "version": __version__, "api": API_VERSION,
                     "uptime": int(time.time() - STARTED)}
    if path == "/api/state":
        return 200, cockpit.state()
    if path == "/api/activity":
        return 200, activity_payload(cockpit)
    if path == "/api/chat":
        return 200, cockpit.chat_state()
    if path == "/api/sessions":
        return 200, {"sessions": cockpit.sessions()}
    if path == "/api/memory":
        return 200, cockpit.memory_state()
    if path == "/api/models":
        return 200, cockpit.catalog()
    if path == "/api/relay":
        return 200, cockpit.relay_status()
    if path == "/api/onboarding":
        return 200, cockpit.onboarding_state()
    if path == "/api/projects":
        from .onboarding import projects as listing
        return 200, {"projects": listing(_one(query, "workspace") or None)}
    if path == "/api/projects/queue":
        return 200, {"queue": projects.queue(cockpit.config),
                     "governed": projects.order(cockpit.config),
                     "plain": projects.plain(cockpit.config.workspace)}
    if path == "/api/autonomy":
        return 200, autonomy_payload(cockpit)
    if path == "/api/mcp":
        return 200, cockpit.mcp_state()
    if path == "/api/skills":
        name = _one(query, "name")
        payload = cockpit.skill_read(name) if name else cockpit.skills_list()
        return (200 if payload.get("ok", True) else 404), payload
    if path == "/api/bridge/daemon":
        return 200, cockpit.daemon_state()
    if path == "/api/events":
        since = int(_one(query, "since", "0") or 0)
        return 200, {"events": cockpit.bus.since(since), "seq": cockpit.bus.seq}
    if path == "/api/gov":
        return 200, gov.status()
    if path == "/api/ledger":
        rows = ledger.history(cockpit.config.workspace, projects.order(cockpit.config),
                              extra=[cockpit.root])
        return 200, {"aggregate": ledger.aggregate(rows), "rows": len(rows),
                     "projects": sorted(projects.order(cockpit.config))}
    return None


def autonomy_payload(cockpit):
    """El estado del bucle mas lo que necesita su panel: cola, progreso por proyecto y backups."""
    state = cockpit.autopilot.state()
    rows = projects.queue(cockpit.config)
    return dict(state, projects=rows, criteria=projects.spec_of(cockpit.root).get("criteria") or 0,
                workspace=str(cockpit.config.workspace))


# -- escrituras ----------------------------------------------------------------------------------
def post(cockpit, path, body=None, query=None):
    body = body if isinstance(body, dict) else {}
    if path == "/api/consult":
        from . import consult_api
        return consult_api.post(cockpit, body)
    if path == "/api/chat":
        ok, payload = cockpit.send(body.get("text"), body.get("attachments") or [])
        if ok:
            return 202, dict(payload, ok=True)
        return (409 if "in flight" in str(payload) else 400), {"ok": False, "reason": payload}
    if path == "/api/onboarding":
        return 200, cockpit.onboarding_apply(body)
    if path == "/api/mcp":
        return 200, cockpit.mcp_reload()
    if path == "/api/skills":
        saved = cockpit.skill_save(body.get("name"), body.get("text"))
        return (200 if saved.get("ok") else 400), saved
    if path == "/api/bridge/daemon":
        if str(body.get("action") or "toggle") == "stop":
            return 200, cockpit.daemon_stop()
        return 200, cockpit.daemon_toggle(body.get("provider") or "")
    if path == "/api/stop":
        return 200, {"ok": True, "stopped": cockpit.stop()}
    if path == "/api/chat/new":
        return 200, {"ok": True, "session": cockpit.new_chat(body.get("title") or "",
                                                             body.get("project"))}
    if path == "/api/chat/load":
        session = cockpit.load_chat(body.get("id"), body.get("project"))
        if session is None:
            return 404, {"ok": False, "reason": "no such conversation"}
        return 200, {"ok": True, "session": session}
    if path == "/api/chat/delete":
        gone = cockpit.delete_session(body.get("id"), body.get("project"))
        return (200 if gone else 404), {"ok": gone}
    if path == "/api/chat/rename":
        done = cockpit.rename_session(body.get("id"), body.get("title"), body.get("project"))
        return (200 if done else 404), {"ok": done}
    if path == "/api/memory":
        if "remove" in body:
            return 200, cockpit.memory_remove(body.get("remove"))
        return 200, cockpit.memory_add(body.get("text"))
    if path == "/api/run":
        ok, payload = cockpit.start(body.get("goal"), body.get("project"),
                                    body.get("test_command"))
        if ok:
            return 202, dict(payload, ok=True)
        return (409 if "in flight" in str(payload) else 400), {"ok": False, "reason": payload}
    if path == "/api/roles":
        ok, payload = cockpit.swap(body.get("role"), body.get("spec"))
        return (200 if ok else 400), ({"ok": True, "info": payload} if ok
                                      else {"ok": False, "reason": payload})
    if path == "/api/bridge":
        rows = cockpit.tick_bridge()
        return 200, {"ok": True, "ran": len(rows), "rows": rows}
    if path == "/api/projects/order":
        return order_projects(cockpit, body)
    if path == "/api/projects/new":
        return create_project(cockpit, body)
    if path == "/api/autonomy":
        if str(body.get("action") or "start") == "stop":
            return 200, {"ok": cockpit.autopilot.stop(), "state": autonomy_payload(cockpit)}
        return start_autonomy(cockpit, body)
    return None


def order_projects(cockpit, body):
    """Reordena la cola. Es lo que llama el arrastrar y soltar; devuelve el orden que quedo."""
    names = body.get("names")
    if not isinstance(names, list) or not names:
        return 400, {"ok": False, "reason": "se esperaba {\"names\": [...]} con al menos un nombre"}
    saved, notes = projects.save_order(cockpit.config, names)
    cockpit.config.project_order = list(saved)
    return (200 if saved else 400), {"ok": bool(saved), "order": saved, "notes": notes}


def create_project(cockpit, body):
    result = projects.create(cockpit.config, body.get("name"), body.get("goal") or "")
    if not result.get("ok"):
        return 400, result
    cockpit.config.project_order = list(result.get("order") or [])
    cockpit.bus.emit("project.created", result["name"], root=result["root"])
    return 200, result


def start_autonomy(cockpit, body):
    """Arranca el bucle: proyecto, objetivo y limite de iteraciones. Se niega si ya hay un turno."""
    if cockpit.busy:
        return 409, {"ok": False, "reason": "hay un turno en marcha: el bucle espera"}
    try:
        iterations = int(body.get("iterations") or 3)
    except (TypeError, ValueError):
        iterations = 3
    ok, payload = cockpit.autopilot.start(
        project=str(body.get("project") or ""), goal=str(body.get("goal") or ""),
        iterations=iterations,
        queue=body.get("queue") if isinstance(body.get("queue"), list) else None)
    if not ok:
        return 409, {"ok": False, "reason": payload}
    cockpit.bus.emit("autonomy.started", str(body.get("project") or "cola"),
                     iterations=int(body.get("iterations") or 3))
    return 202, {"ok": True, "state": autonomy_payload(cockpit)}
