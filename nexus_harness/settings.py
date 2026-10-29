"""La pantalla de configuración: ocho secciones, una pantalla, un solo sitio que cambia cosas.

Por qué una pantalla y no un modal: ocho secciones con submenús, búsqueda y vuelta atrás no caben en un
modal, y además así el chat se queda limpio y de lado a lado, que es lo que se pidió.

Cómo funciona cada sección: el árbol de la izquierda son `<details>` nativos (desplegables sin script),
el panel de la derecha lo escribe el módulo dueño de esa sección, y guardar es un `POST /api/settings`
que contesta un **303 de vuelta** con una nota. `settings.js` solo añade Ctrl+K y el filtro del árbol:
si ese script no corre, navegar y guardar siguen funcionando.
"""
import json
from html import escape
from urllib.parse import quote

from .platform import vault
from . import gov, onboarding, panels, triad_balance
from . import settings_kit as kit
from . import (settings_models, settings_projects, settings_skills, settings_tools, settings_vps,
               settings_work)

TITLE = "Configuración"

# Diez categorías, trece destinos (las cuatro sub-vistas de la tríada). Agrupadas por dominio: trece
# entradas planas no son un árbol, son una lista larga donde no se encuentra nada.
GROUPS = (
    ("Modelo", "cpu", ("modelos", "memoria")),
    ("Trabajo", "folder", ("espacio", "skills")),
    ("Operación", "plug", ("mcp", "puente", "autonomia", "vps")),
    ("Sistema", "shield", ("seguridad", "stats")),
)
SECTIONS = (
    ("modelos", "Modelos (tríada)", "cpu",
     (("principal", "Modelo principal (Director)"),
      ("obrero", "Obrero (worktree repair)"),
      ("juez", "Juez y auditoría"),
      ("subagentes", "Subagentes"))),
    ("espacio", "Espacio de trabajo", "folder", ()),
    ("seguridad", "Seguridad y bóveda", "shield", ()),
    ("memoria", "Memoria y contexto", "layers", ()),
    ("skills", "Skills", "bolt", ()),
    ("mcp", "Conectores MCP", "plug", ()),
    ("puente", "Puente móvil", "plug", ()),
    ("autonomia", "Autonomía y preguntas", "bolt", ()),
    ("vps", "VPS 24/7", "cpu", ()),
    ("stats", "Estadísticas y auditoría", "chart", ()),
)
NAMES = tuple(name for name, _label, _icon, _subs in SECTIONS)
SUBS_OF = {name: tuple(value for value, _text in subs) for name, _label, _icon, subs in SECTIONS}
# Lo que un operador escribe cuando busca cada panel, en sus palabras y no en las del codigo: la
# busqueda de la cabina tiene que encontrar «relevo» sin que el panel se llame asi.
SEARCH_TERMS = {
    "modelos": "modelo director obrero juez triada ia llm temperatura proveedor",
    "principal": "director razonamiento planifica modelo principal",
    "obrero": "worker obrero codigo edicion worktree reparacion",
    "juez": "juez judge auditoria verdict adversario",
    "subagentes": "subagentes hijos paralelo profundidad",
    "espacio": "proyectos workspace cola orden spec carpetas",
    "seguridad": "claves boveda dpapi api key secretos politica comandos",
    "memoria": "memoria contexto tokens presupuesto relevo compactacion",
    "skills": "skills architect forjar rutas modo",
    "mcp": "mcp conectores tools servidores",
    "puente": "puente bots telegram discord movil daemon",
    "autonomia": "autonomia autopilot preguntas pendientes bucle",
    "vps": "vps deploy 24/7 servidor remoto colmena",
    "stats": "estadisticas auditoria ledger graficos ahorro coste",
}


def resolve(section, sub):
    """La sección y el submenú que se van a pintar, aceptando lo que llegue por la URL."""
    name = str(section or "").strip().lower()
    if name not in NAMES:
        name = "modelos"
    subs = SUBS_OF[name]
    chosen = str(sub or "").strip().lower()
    return name, (chosen if chosen in subs else (subs[0] if subs else ""))


def _render(name, cockpit, sub, item, query):
    if name == "modelos":
        return settings_models.panel(cockpit, sub)
    if name == "espacio":
        return settings_projects.espacio(cockpit)
    if name == "seguridad":
        return settings_work.seguridad(cockpit)
    if name == "memoria":
        return settings_work.memoria(cockpit)
    if name == "skills":
        return settings_skills.skills(cockpit, query or {})
    if name == "mcp":
        return settings_tools.mcp(cockpit)
    if name == "puente":
        return settings_tools.puente(cockpit)
    if name == "autonomia":
        from . import settings_autonomy
        return (settings_autonomy.TITLE,
                "Qu\\u00e9 decidi\\u00f3 el bucle solo, qu\\u00e9 te est\\u00e1 preguntando y por d\\u00f3nde puede o\\u00edrte.",
                settings_autonomy.block(cockpit))
    if name == "vps":
        from . import settings_vps
        return settings_vps.page(cockpit)
    return settings_tools.stats(cockpit)


def _icon(name, cls=""):
    from . import ui_icons
    return ui_icons.icon(name, cls)


def _tree(active, sub, needle, state, token=""):
    """El árbol de categorías, agrupado por dominio. `needle` filtra: es el buscador sin script.

    Cada enlace lleva el token (una pantalla que pierde la credencial al navegar se muere a mitad de
    camino) y el pie dice QUÉ motor se está mirando: su versión y de qué fichero salieron los ajustes.
    """
    from . import ui_icons
    gt = ("&token=" + quote(str(token), safe="")) if token else ""
    found = []
    for group, group_icon, members in GROUPS:
        blocks = []
        for name, label, _icon_name, subs in SECTIONS:
            if name not in members:
                continue
            hit = (not needle or needle in label.lower() or needle in name
                   or any(needle in text.lower() for _value, text in subs)
                   or needle in SEARCH_TERMS.get(name, ""))
            if needle and not hit:
                # Un submenú puede coincidir aunque el título de la categoría no.
                subs = tuple((value, text) for value, text in subs
                             if needle in text.lower() or needle in SEARCH_TERMS.get(value, ""))
                if not subs:
                    continue
            if subs:
                opened = " open" if name == active else ""
                items = "".join('<li class="%s"><a href="/settings?section=%s&sub=%s%s">%s</a></li>'
                                % ("on" if (name == active and value == sub) else "", escape(name),
                                   escape(value), gt, escape(text)) for value, text in subs)
                blocks.append('<details class="scat%s"%s><summary>%s%s</summary>'
                              '<ul class="ssubs">%s</ul></details>'
                              % (" on" if name == active else "", opened, _icon(_icon_name), escape(label),
                                 items))
            else:
                blocks.append('<a class="scat-leaf%s" href="/settings?section=%s%s">%s%s</a>'
                              % (" on" if name == active else "", escape(name), gt,
                                 _icon(_icon_name), escape(label)))
        if blocks:
            found.append('<p class="sgroup">%s%s</p>%s'
                         % (_icon(group_icon), escape(group), "".join(blocks)))
    if not found:
        found.append('<p class="dim">Nada coincide con «%s».</p>' % escape(needle))
    config = state.get("config") or {}
    version = state.get("version") or "?"
    source = config.get("source") or "defaults"
    gov = ('<a class="tree-gov" href="/gov?tab=setup%s">%s%s</a>'
           % (gt.replace("&token=", "&token="), _icon("shield"), "Gobernanza (protocolo)"))
    return ('<nav class="settings-tree">%s%s<p class="tree-foot">'
            '<span class="dot ok"></span>Motor v%s · conectado<br><code>%s</code></p></nav>'
            % ("".join(found), gov, escape(version), escape(source)))


def _palette(token=""):
    """El índice de Ctrl+K: los trece destinos, con las palabras con las que se buscan.

    Va como JSON en el documento para que el buscador sea instantáneo y no pida nada al motor; el
    `<form>` de al lado sigue funcionando sin script, filtrando el árbol en el servidor.
    """
    gt = ("&token=" + quote(str(token), safe="")) if token else ""
    rows = []
    for name, label, _icon_name, subs in SECTIONS:
        entries = ([(value, "%s · %s" % (label, text)) for value, text in subs] if subs
                   else [(name, label)])
        for value, text in entries:
            href = ("/settings?section=%s&sub=%s%s" % (name, value, gt) if subs
                    else "/settings?section=%s%s" % (name, gt))
            rows.append({"label": text, "where": label if subs else "",
                         "terms": SEARCH_TERMS.get(value, ""), "href": href})
    return json.dumps(rows, ensure_ascii=False)


def screen(cockpit, query, token=""):
    """El HTML de la pantalla entera, con la sección pedida ya pintada."""
    section, sub = resolve((query.get("section") or [""])[0], (query.get("sub") or [""])[0])
    item = str((query.get("item") or [""])[0])
    needle = str((query.get("q") or [""])[0]).strip().lower()
    title, subtitle, body = _render(section, cockpit, sub, item, query)
    note = kit.note_from(query)
    state = cockpit.state()
    from . import ui_icons
    return LAYOUT % {
        "note": note,
        "tree": _tree(section, sub, needle, state, token),
        "token": escape(str(token), quote=True),
        "sprite": ui_icons.sprite(),
        "close_icon": ui_icons.icon("close"),
        "palette": _palette(token),
        "title": escape(title),
        "subtitle": escape(subtitle),
        "body": body,
        "query": escape((query.get("q") or [""])[0]),
        "section": escape(section),
        "sub": escape(sub),
    }


LAYOUT = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="nexus-token" content="%(token)s">
<title>Nexus Harness · Configuración</title>
<link rel="stylesheet" href="tokens.css">
<link rel="stylesheet" href="app.css">
<link rel="stylesheet" href="settings.css">
</head>
<body class="settings-body">
%(sprite)s
<header class="settings-top">
  <a class="brand" href="/?token=%(token)s">NEXUS<span>·</span>HARNESS</a>
  <form class="settings-search" method="get" action="/settings" id="settings-form">
    <input id="settings-search" name="q" type="search" value="%(query)s" autocomplete="off"
           placeholder="Buscar en la configuración…  (Ctrl+K)"
           aria-label="Buscar en la configuración" aria-controls="sk-palette">
    <input type="hidden" name="section" value="%(section)s">
    <input type="hidden" name="sub" value="%(sub)s">
    <input type="hidden" name="token" value="%(token)s">
    <ul id="sk-palette" class="palette" role="listbox" aria-label="Destinos" hidden></ul>
  </form>
  <a class="settings-close" id="settings-close" href="/?token=%(token)s"
     title="Volver al chat (Esc)">%(close_icon)s</a>
</header>
%(note)s
<div class="settings-app">
  %(tree)s
  <section class="settings-panel">
    <h1>%(title)s</h1>
    <p class="dim">%(subtitle)s</p>
    %(body)s
  </section>
</div>
<script type="application/json" id="sk-index">%(palette)s</script>
<script src="token.js"></script>
<script src="settings.js"></script>
</body>
</html>
"""


# -- guardar -------------------------------------------------------------------------------------
def _numbers(body):
    """Los campos de contexto que comparten dos paneles, ya normalizados. Devuelve `(cambios, problemas)`.

    Es el UNICO sitio donde un porcentaje se convierte en fraccion. Un valor imposible (`150`) no se
    escribe: se devuelve como problema y el panel lo dice en rojo, porque un guardado que corrompe
    el umbral del relevo y aun asi sale en verde es peor que un guardado que falla.
    """
    changes, problems = {}, []
    for name in ("budget_limit", "relay_threshold", "compact_threshold", "temperature", "max_tokens",
                 "cost_limit", "max_steps", "max_repairs", "max_children", "subagent_steps",
                 "subagent_depth", "tool_workers", "shell_timeout", "test_command", "workspace",
                 "shell_policy", "hardware_ceiling", "triad_bias"):
        if name in body and str(body.get(name)).strip() != "":
            if name in kit.PERCENT_FIELDS:
                value, problem = kit.percent_to_fraction(name, body[name])
                if problem:
                    problems.append(problem)
                else:
                    changes[name] = value
                continue
            changes[name] = body[name]
    return changes, problems


def save(cockpit, body):
    """Guarda lo que mandó un panel. Devuelve `(nota, ok)`."""
    section = str(body.get("section") or "")
    notes, ok = [], True
    if section == "modelos":
        role = str(body.get("role") or "")
        vendor = str(body.get("vendor") or "").strip()
        # El id libre manda sobre el `<select>`: un catalogo propone, no encierra.
        model = (str(body.get("model_free") or "").strip() or str(body.get("model") or "").strip())
        if role in ("director", "worker", "judge") and vendor and model:
            before = triad_balance.class_of(cockpit.config.role_spec(role))
            result = onboarding.apply(cockpit.config, {"roles": {role: "%s:%s" % (vendor, model)}})
            notes += result.get("notes") or []
            if result.get("saved", {}).get("roles"):
                notes.append("%s → %s:%s" % (role, vendor, model))
            cockpit.reload_config()
            if before != triad_balance.class_of("%s:%s" % (vendor, model)):
                notes += triad_balance.auto_adapt(cockpit, role)
        # Los numeros del turno viajan en el MISMO panel (son parte de la triada: con que presupuesto
        # y con cuanta temperatura). Se guardaban en la vista de memoria y aqui se perdian en silencio.
        numbers, rejected = _numbers(body)
        if rejected:
            ok = False
            notes += rejected
        if "judge_mode" in body:
            numbers["judge_mode"] = body.get("judge_mode")
        if "worker_resident" in body:
            numbers["worker_resident"] = body.get("worker_resident")
        if "triad_auto_adapt" in body:
            numbers["triad_auto_adapt"] = body.get("triad_auto_adapt")
        if numbers:
            saved, problems = onboarding.save_settings(numbers)
            notes += problems
            if saved:
                names = [name for name in ("judge_mode", "worker_resident") if name in saved]
                notes.append("guardado: %s" % ", ".join(names or ["números del turno"]))
        cockpit.reload_config()
        notes += _pin_worker(cockpit)
    elif section == "espacio":
        # La cola, el alta y el workspace los sabe guardar su propio panel: una seccion, un dueno.
        note, ok = settings_projects.save(cockpit, body)
        return (note, ok)
    elif section == "seguridad":
        keys = {str(key)[4:]: str(value) for key, value in body.items()
                if str(key).startswith("key:") and str(value).strip()}
        if keys:
            result = onboarding.apply(cockpit.config, {"keys": keys})
            notes += result.get("notes") or []
            notes.append("guardadas: %s" % ", ".join(result.get("saved", {}).get("keys") or []))
        numbers, rejected = _numbers(body)
        ok = ok and not rejected
        notes += rejected
        saved, problems = onboarding.save_settings(numbers)
        notes += problems
        if "shell_policy" in saved:
            notes.append("política de comandos → %s" % saved["shell_policy"])
        cockpit.reload_config()
    elif section == "autonomia":
        from . import settings_autonomy
        note, ok = settings_autonomy.save(cockpit, body)
        return (note, ok)
    elif section == "memoria":
        numbers, rejected = _numbers(body)
        ok = ok and not rejected
        notes += rejected
        saved, problems = onboarding.save_settings(numbers)
        notes += problems
        if saved:
            notes.append("contexto guardado")
        cockpit.reload_config()
    else:
        ok = False
        notes.append("esa sección no guarda nada por formulario")
    return (" · ".join(note for note in notes if note) or "sin cambios", ok)


def _pin_worker(cockpit):
    """`worker_resident`: el obrero usa el MISMO spec que el director cuando ese spec es local.

    Es la unica forma de garantizar cero recargas entre fases: dos modelos locales distintos no caben a
    la vez en una GPU de 8-16 GB, y el que paga es el turno. Se aplica al guardar y se declara.
    """
    if not getattr(cockpit.config, "worker_resident", False):
        return []
    from .triad_presets import split_spec
    director = str(cockpit.config.roles.get("director") or "")
    vendor, model = split_spec(director)
    if vendor not in ("lmstudio", "ollama"):
        return ["worker_resident: el director no es local, no se toca el obrero"]
    if str(cockpit.config.roles.get("worker") or "") == director:
        return []
    result = onboarding.apply(cockpit.config, {"roles": {"worker": director}})
    cockpit.reload_config()
    return (result.get("notes") or []) + (["obrero fijado al residente: %s" % model]
                                          if result.get("saved", {}).get("roles") else [])
# -- acciones ------------------------------------------------------------------------------------
# Las que no son «guardar» viven en su modulo: `settings.action` se queda como la puerta, para que
# `ui.py` no sepa donde esta la implementacion.
from .settings_actions import action  # noqa: E402,F401  (reapertura deliberada: una sola puerta)
