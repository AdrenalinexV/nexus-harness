"""The four product surfaces, kept out of the cockpit so neither file has to grow a second job.

Each function is a thin, testable seam over a module that does the work:

* `onboarding_*` -> `onboarding.py` (probe, apply, governance)
* `mcp_*` -> `mcp_client.py` (servers, tools, reload)
* `skills_*` -> NexusProtocol's `nexus.skills.editor` (read/validate/save a SKILL.md)
* `daemon_*` -> NexusProtocol's `nexus.hive.daemon_control` (the mobile bridge ON/OFF)

The pattern is the same in all four: **the UI gets facts, never secrets**, every failure comes back as
text the operator can act on, and nothing here raises into the HTTP handler.
"""
import os
import sys
from html import escape
from pathlib import Path

from .platform import vault
from . import onboarding, settings_kit

NEXUS_SOURCE = Path(os.environ.get("NEXUS_PROTOCOL") or r"C:\Proyectos\NexusProtocol")


def _protocol(module_path):
    """Import a module from NexusProtocol, or `None` with the reason in the caller's text."""
    if str(NEXUS_SOURCE) not in sys.path:
        sys.path.insert(0, str(NEXUS_SOURCE))
    try:
        module = __import__(module_path, fromlist=["*"])
        return module
    except ImportError:
        return None


# -- onboarding ------------------------------------------------------------------------------
def onboarding_status(cockpit):
    payload = onboarding.status(cockpit.config, root=cockpit.root)
    payload["projects"] = onboarding.projects(cockpit.config.workspace)
    payload["mcp"] = mcp_status(cockpit)
    return payload


def onboarding_apply(cockpit, payload):
    result = onboarding.apply(cockpit.config, payload)
    if result.get("ok") and (result.get("saved") or {}).get("config_file"):
        cockpit.reload_config()
    return result


# -- MCP -------------------------------------------------------------------------------------
def mcp_write(cockpit, action, payload):
    """Alta, edicion, borrado y encendido de conectores. Devuelve `(ok, nota)`.

    El fichero (`~/.nexus/mcp.json`) es la fuente de verdad del operador y lo escribe `mcp_client`;
    aqui solo se decide QUE cambia. Despues se recarga en caliente para que el cambio se note sin
    reiniciar el motor: un `Guardar` que exige reiniciar no es un producto, es una tarea pendiente.
    """
    from .tools import mcp_client
    action = str(action or "")
    payload = payload or {}
    config = mcp_client.load_config()
    servers = dict(config.get("servers") or {})
    name = str(payload.get("name") or "").strip()
    if action in ("add", "save"):
        if not name:
            return False, "el conector necesita un nombre"
        command = str(payload.get("command") or "").strip()
        if not command:
            return False, "el conector necesita un comando ejecutable"
        args = [part for part in str(payload.get("args") or "").split() if part]
        env = {}
        for line in str(payload.get("env") or "").splitlines():
            key, _, value = line.partition("=")
            if key.strip() and value.strip():
                env[key.strip()] = value.strip()
        spec = {"command": command, "args": args, "enabled": True}
        if payload.get("cwd"):
            spec["cwd"] = str(payload["cwd"]).strip()
        if env:
            spec["env"] = env
        if payload.get("description"):
            spec["description"] = str(payload["description"]).strip()[:120]
        servers[name] = spec
    elif action == "delete":
        if name not in servers:
            return False, "ese conector no existe"
        servers.pop(name, None)
    elif action == "toggle":
        if name not in servers:
            return False, "ese conector no existe"
        want = payload.get("enabled")
        current = servers[name].get("enabled") is not False
        servers[name]["enabled"] = (not current) if want is None else bool(want)
    else:
        return False, "acción desconocida: %r" % action
    location = mcp_client.save_config({"servers": servers})
    reloaded = mcp_reload(cockpit)
    note = "%s: %s · %d conectores en %s" % (action, name or "-", len(servers),
                                             location.name)
    if not reloaded.get("ok"):
        note += " (recarga: %s)" % reloaded.get("reason")
    return True, note


def mcp_status(cockpit):
    """The panel asks for connectors, so the connectors are what it gets: start them if nobody has.

    Deferring start-up to the first chat meant the sidebar showed "sin conectores" on a machine whose
    connectors were fine, which is a lie the operator cannot debug.
    """
    manager = getattr(cockpit, "mcp_manager", None)
    if manager is None:
        manager = cockpit.mcp()
    return manager.describe()


def mcp_reload(cockpit):
    manager = getattr(cockpit, "mcp_manager", None)
    if manager is None:
        return {"ok": False, "reason": "MCP is not enabled in this session"}
    described = manager.reload()
    registry = getattr(getattr(cockpit, "chat", None), "registry", None)
    if registry is not None:
        registry.refresh_mcp()
    return dict(described, ok=True)


# -- skills ----------------------------------------------------------------------------------
def _editor():
    return _protocol("nexus.skills.editor")


def skills_list(cockpit):
    editor = _editor()
    if editor is None:
        return {"ok": False, "reason": "NexusProtocol is not importable", "skills": []}
    rows = editor.list_skills(str(NEXUS_SOURCE))
    last = getattr(getattr(cockpit, "chat", None), "last_turn", None)
    live = set(getattr(last, "skills", None) or [])
    for row in rows:
        row["in_ram"] = row["name"] in live
    return {"ok": True, "skills": rows, "root": str(NEXUS_SOURCE)}


def skills_read(cockpit, name):
    editor = _editor()
    if editor is None:
        return {"ok": False, "reason": "NexusProtocol is not importable"}
    try:
        return editor.read_skill(str(name or ""), str(NEXUS_SOURCE))
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}


def skills_save(cockpit, name, text):
    editor = _editor()
    if editor is None:
        return {"ok": False, "reason": "NexusProtocol is not importable"}
    try:
        result = editor.save_skill(str(name or ""), str(text or ""), str(NEXUS_SOURCE))
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    cockpit.bus.emit("skills.saved", "%s (%s)" % (name, result.get("sha256", "")[:12]))
    return dict(result, ok=True)


# -- mobile bridge daemon --------------------------------------------------------------------
def _daemon():
    return _protocol("nexus.hive.daemon_control")


def daemon_status(cockpit):
    module = _daemon()
    if module is None:
        return {"ok": False, "running": False, "reason": "NexusProtocol is not importable"}
    rows = module.status(str(cockpit.root))
    rows["ok"] = True
    rows["toggle"] = "detener" if rows.get("running") else "arrancar"
    return rows


def daemon_toggle(cockpit, provider="telegram"):
    module = _daemon()
    if module is None:
        return {"ok": False, "running": False, "reason": "NexusProtocol is not importable"}
    result = module.toggle(str(cockpit.root), provider=provider or "telegram")
    cockpit.bus.emit("daemon.toggle", "ON" if result.get("running") else "OFF",
                     running=result.get("running"), pid=result.get("pid"))
    return result


def daemon_stop(cockpit):
    module = _daemon()
    if module is None:
        return {"ok": False, "running": False, "reason": "NexusProtocol is not importable"}
    result = module.stop(str(cockpit.root))
    cockpit.bus.emit("daemon.toggle", "OFF", running=False)
    return result


def keys_state():
    """Only names: the modal must be able to say what is saved without ever showing a value."""
    return {"names": vault.names()}


# -- los controles del arnes dentro de la vista de gobernanza ---------------------------------
SECTION_CSS = """
/* Las tarjetas del arnes dentro de la vista del protocolo. Van con COLORES LITERALES a proposito: este
   HTML se inyecta en un documento ajeno que define sus propios `--accent`/`--line` (azul, gris azulado),
   y una tarjeta que hereda el tema del vecino parece otro producto. La ley es la de la cabina:
   papel calido, tinta calida, un solo sello, reglas de 1px, ningun radio. */
.hsec{margin:0 0 1.1rem;padding:.75rem 0 .8rem;background:transparent;border:0;
  border-top:1px solid #2b2926;max-width:1100px}
.hsec h3{margin:0 0 .35rem;font:600 10.5px/1.2 ui-monospace,monospace;letter-spacing:.16em;
  text-transform:uppercase;color:#a8a29a}
.hsec p{margin:.3rem 0;color:#ece7dd;font-size:13px;line-height:1.6}
.hsec .row{display:flex;flex-wrap:wrap;gap:.15rem 1.2rem;align-items:baseline;margin-top:.35rem}
.hsec .cell{padding:0;background:none;border:0;border-radius:0;
  font:400 11.5px/1.6 ui-monospace,monospace;color:#a8a29a}
.hsec .cell b{font-weight:600}
.hsec button,.hsec select{font:400 10.5px/1.2 ui-monospace,monospace;letter-spacing:.1em;
  text-transform:uppercase;padding:.3rem .55rem;border:1px solid #3a3733;border-radius:0;
  background:#171614;color:#ece7dd;appearance:none}
.hsec button:hover{border-color:#ece7dd}
.hsec button.primary{background:#d4502e;border-color:#d4502e;color:#17110d;font-weight:700}
.hsec .ok{color:#7fae6a} .hsec .bad{color:#cc5b45}
.hsec .warn{color:#c99a3f} .hsec .dim{color:#a8a29a}
"""


def _esc(value):
    return escape(str(value if value is not None else ""))


def sections_css():
    return SECTION_CSS


def _triad_card(cockpit):
    roles = (cockpit.state().get("roles") or {})
    budget = cockpit.relay_status().get("budget") or {}
    cells = []
    for role in ("director", "worker", "judge"):
        info = roles.get(role) or {}
        tone = "ok" if info.get("ready") else "bad"
        cells.append('<span class="cell">%s: <b class="%s">%s</b>%s</span>'
                     % (_esc(role), tone, _esc(info.get("model") or "sin modelo"),
                        "" if info.get("ready") else
                        ' <span class="bad">(%s)</span>' % _esc(info.get("why_not_ready") or "no ready")))
    limit = budget.get("limit") or cockpit.config.budget_limit
    used = budget.get("used")
    # La fraccion se pinta con el mismo conversor que el formulario. Aqui vivia el `7000 %`: leer un
    # `70.0` ya corrompido y multiplicarlo otra vez por 100. Un valor fuera de rango se declara.
    relay = settings_kit.show_percent(getattr(cockpit.config, "relay_threshold", 0.7))
    if relay == "?":
        relay_text = 'relevo automático: <span class="bad">umbral fuera de rango en la config</span>'
    else:
        relay_text = "relevo automático al %s%%" % relay
    return ('<section class="hsec"><h3>Tríada de modelos</h3>'
            '<p class="dim">Autodetectados en esta máquina. Los selectores completos, la temperatura y '
            'el juez adversario viven en la vista del protocolo, más abajo.</p>'
            '<div class="row">%s</div>'
            '<p class="dim">Presupuesto: %s de %s tokens · %s</p></section>'
            % ("".join(cells), _esc(used if used is not None else "sin medir"), _esc(limit), relay_text))


def _mcp_card(cockpit):
    state = mcp_status(cockpit)
    rows = []
    for server in state.get("servers") or []:
        tone = "ok" if server.get("ready") else "bad"
        tools = ", ".join(server.get("tools") or []) or "sin tools"
        rows.append('<div class="row"><span class="cell">%s <b class="%s">%s</b> · pid %s · %s</span>'
                    % (_esc(server.get("name")), tone,
                       "conectado" if server.get("ready") else "caído",
                       _esc(server.get("pid") or "-"), _esc(tools)))
    if not rows:
        rows.append('<p class="warn">Sin conectores configurados en %s</p>'
                    % _esc(state.get("config") or "-"))
    return ('<section class="hsec"><h3>Conectores MCP <span class="dim">(%s tools)</span></h3>'
            '%s<form method="post" action="/gov/action"><input type="hidden" name="what" value="mcp">'
            '<input type="hidden" name="next" value="/gov?tab=setup">'
            '<div class="row"><button>Recargar conectores</button>'
            '<span class="dim">config: %s</span></div></form></section>'
            % (_esc(state.get("tools") or 0), "".join(rows), _esc(state.get("config") or "-")))


def _vault_card(cockpit):
    """El cofre, visto desde el arnes: QUE claves hay guardadas, nunca sus valores.

    Los nombres son lo que un operador necesita para saber si le falta una; escribirla y probarla es
    de la vista de setup del protocolo, que es quien tiene el formulario y el sondeo de conexion.
    """
    names = keys_state().get("names") or []
    if names:
        rows = "".join('<span class="cell">%s</span>' % _esc(name) for name in names)
    else:
        rows = '<p class="warn">Ninguna clave guardada todavia (el cofre es DPAPI, por usuario)</p>'
    return ('<section class="hsec"><h3>Cofre de claves <span class="dim">'
            '(%d guardadas)</span></h3>'
            '<p class="dim">Solo nombres: un valor no sale del cofre ni para pintarlo.</p>'
            '<div class="row">%s</div></section>' % (len(names), rows))


def _bridge_card(cockpit):
    state = daemon_status(cockpit)
    running = bool(state.get("running"))
    tone = "ok" if running else "dim"
    detail = ("PID %s desde %s" % (_esc(state.get("pid") or "-"), _esc(state.get("since") or "-"))
              if running else "parado")
    provider = _esc(state.get("provider") or "telegram")
    forms = ('<form method="post" action="/gov/action"><input type="hidden" name="what" value="bridge">'
             '<input type="hidden" name="next" value="/gov?tab=setup">'
             '<div class="row"><input type="hidden" name="on" value="%s">'
             '<select name="provider"><option value="telegram"%s>telegram</option>'
             '<option value="discord"%s>discord</option></select>'
             '<button class="primary">%s</button>'
             '<span class="dim">cola: %s mensajes</span></div></form>'
             % ("off" if running else "on",
                " selected" if provider == "telegram" else "",
                " selected" if provider == "discord" else "",
                "Detener el puente" if running else "Arrancar el puente",
                _esc(state.get("queue") if state.get("queue_known") else "?")))
    return ('<section class="hsec"><h3>Puente móvil <span class="%s">%s</span></h3>'
            '<p class="%s">%s</p>%s</section>'
            % (tone, "ON" if running else "OFF", tone, detail, forms))


def harness_sections(cockpit):
    """Las tarjetas del ARNES dentro de la vista de gobernanza, servidas sin una linea de script.

    Un formulario no puede poner cabeceras, asi que estas acciones van por `/gov/action` (que responde
    un 303 a la vista) y no por `/api/*`: la vista de setup tiene que funcionar tambien con el script
    bloqueado, y el estado de MCP y del puente es justo lo que el operador viene a mirar.
    """
    try:
        return ("<style>%s</style><div class=\"hsec-wrap\">%s%s%s%s</div>"
                % (SECTION_CSS, _triad_card(cockpit), _vault_card(cockpit), _mcp_card(cockpit),
                   _bridge_card(cockpit)))
    except Exception as exc:  # noqa: BLE001 -- un panel roto no puede tumbar la vista: se dice
        return ('<section class="hsec"><h3>Controles del harness</h3>'
                '<p class="bad">No se pudieron leer: %s: %s</p></section>'
                % (type(exc).__name__, _esc(exc)))
