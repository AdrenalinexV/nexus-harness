"""La pantalla de configuración: ocho secciones, una pantalla, un solo sitio que cambia cosas.

Por qué una pantalla y no un modal: ocho secciones con submenús, búsqueda y vuelta atrás no caben en un
modal, y además así el chat se queda limpio y de lado a lado, que es lo que se pidió.

Cómo funciona cada sección: el árbol de la izquierda son `<details>` nativos (desplegables sin script),
el panel de la derecha lo escribe el módulo dueño de esa sección, y guardar es un `POST /api/settings`
que contesta un **303 de vuelta** con una nota. `settings.js` solo añade Ctrl+K y el filtro del árbol:
si ese script no corre, navegar y guardar siguen funcionando.
"""
import json
import subprocess
import sys
from html import escape

from .platform import vault
from . import gov, onboarding, panels, triad_balance
from . import settings_kit as kit
from . import (settings_models, settings_projects, settings_skills, settings_tools, settings_vps,
               settings_work)

TITLE = "Configuración"
SECTIONS = (
    ("modelos", "\u2699 Modelos (Tr\u00edada IA)", tuple(settings_models.SUBS)),
    ("espacio", "\U0001f4c1 Espacio de trabajo & Proyectos", ()),
    ("seguridad", "\U0001f6e1 Seguridad & B\u00f3veda", ()),
    ("memoria", "\U0001f9e0 Memoria y contexto", ()),
    ("skills", "\u26a1 Skills & Skill Architect", ()),
    ("mcp", "\U0001f50c Conectores MCP", ()),
    ("puente", "\U0001f4f1 Puente M\u00f3vil (Bots)", ()),
    ("autonomia", "\U0001f916 Autonom\u00eda & Preguntas", ()),
    ("vps", "\U0001f5a5 VPS 24/7 (Deploy)", ()),
    ("stats", "\U0001f4ca Estad\u00edsticas & Auditor\u00eda", ()),
)
NAMES = tuple(name for name, _label, _subs in SECTIONS)
SUBS_OF = {name: tuple(value for value, _text in subs) for name, _label, subs in SECTIONS}


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
                "Qu\u00e9 decidi\u00f3 el bucle solo, qu\u00e9 te est\u00e1 preguntando y por d\u00f3nde puede o\u00edrte.",
                settings_autonomy.block(cockpit))
    if name == "vps":
        from . import settings_vps
        return settings_vps.page(cockpit)
    return settings_tools.stats(cockpit)


def _tree(active, sub, needle, state):
    """El árbol de categorías. `needle` filtra por título: es el buscador de arriba, sin script.

    El pie lleva lo que el operador necesita para saber QUE motor esta mirando: su version, que
    responde, y de que fichero de configuracion salieron los ajustes. Antes leia `version` del bloque
    `config`, donde no vive, y el pie decia literalmente `Motor ? · config ?` -- un marcador de
    plantilla sin sustituir es peor que no poner nada.
    """
    out = []
    for name, label, subs in SECTIONS:
        hit = (not needle or needle in label.lower()
               or any(needle in text.lower() for _value, text in subs)
               or needle in name)
        if not hit and needle:
            continue
        opened = " open" if name == active else ""
        items = "".join('<li class="%s"><a href="/settings?section=%s&sub=%s">%s</a></li>'
                        % ("on" if (name == active and value == sub) else "", escape(name),
                           escape(value), escape(text)) for value, text in subs)
        # Una categoría SIN submenús tiene que ser un enlace: si su etiqueta solo despliega, el panel
        # no se abre con un clic y parece que la pantalla no responde (medido en el navegador: siete de
        # las ocho categorías no llevaban a ningún sitio).
        head = (escape(label) if subs else
                '<a href="/settings?section=%s">%s</a>' % (escape(name), escape(label)))
        out.append('<details class="scat%s"%s><summary class="%s">%s</summary>'
                   '<ul class="ssubs">%s</ul></details>'
                   % (" on" if name == active else "", opened,
                      "on" if name == active else "", head, items))
    if not out:
        out.append('<p class="dim">Nada coincide con «%s».</p>' % escape(needle))
    config = state.get("config") or {}
    version = state.get("version") or "?"
    source = config.get("source") or "defaults"
    return ('<nav class="settings-tree">%s<p class="tree-foot">'
            '<span class="dot ok"></span>Motor v%s · Conectado<br><code>%s</code></p></nav>'
            % ("".join(out), escape(version), escape(source)))


def screen(cockpit, query):
    """El HTML de la pantalla entera, con la sección pedida ya pintada."""
    section, sub = resolve((query.get("section") or [""])[0], (query.get("sub") or [""])[0])
    item = str((query.get("item") or [""])[0])
    needle = str((query.get("q") or [""])[0]).strip().lower()
    title, subtitle, body = _render(section, cockpit, sub, item, query)
    note = kit.note_from(query)
    state = cockpit.state()
    return LAYOUT % {
        "note": note,
        "tree": _tree(section, sub, needle, state),
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
<title>Nexus Harness · Configuración</title>
<link rel="stylesheet" href="app.css">
<link rel="stylesheet" href="settings.css">
</head>
<body class="settings-body">
<header class="settings-top">
  <div class="brand">NEXUS<span>·</span>HARNESS <span class="dim">Configuración</span></div>
  <form class="settings-search" method="get" action="/settings">
    <input id="settings-search" name="q" type="search" value="%(query)s"
           placeholder="Buscar en la configuración…  (Ctrl+K)">
    <input type="hidden" name="section" value="%(section)s">
    <input type="hidden" name="sub" value="%(sub)s">
    <button class="ghost">Buscar</button>
  </form>
  <a class="settings-close" id="settings-close" href="/" title="Volver al chat (Esc)">✕</a>
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
<script src="settings.js"></script>
</body>
</html>
"""


# -- guardar -------------------------------------------------------------------------------------
def _numbers(body):
    """Los campos de contexto que comparten dos paneles, tal como llegan del formulario."""
    changes = {}
    for name in ("budget_limit", "relay_threshold", "compact_threshold", "temperature", "max_tokens",
                 "cost_limit", "max_steps", "max_repairs", "max_children", "subagent_steps",
                 "subagent_depth", "tool_workers", "shell_timeout", "test_command", "workspace",
                 "shell_policy", "hardware_ceiling", "triad_bias"):
        if name in body and str(body.get(name)).strip() != "":
            changes[name] = body[name]
    return changes


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
        numbers = _numbers(body)
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
        saved, problems = onboarding.save_settings(_numbers(body))
        notes += problems
        if "shell_policy" in saved:
            notes.append("política de comandos → %s" % saved["shell_policy"])
        cockpit.reload_config()
    elif section == "autonomia":
        from . import settings_autonomy
        note, ok = settings_autonomy.save(cockpit, body)
        return (note, ok)
    elif section == "memoria":
        saved, problems = onboarding.save_settings(_numbers(body))
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
def action(cockpit, body):
    """Las acciones que no son «guardar». Devuelve `(nota, ok, seccion)`."""
    what = str(body.get("what") or "")
    section = str(body.get("section") or "modelos")
    if what.startswith("vps_"):
        return settings_vps.action(cockpit, body)
    if what.startswith("consult_"):
        from . import settings_autonomy
        return settings_autonomy.action(cockpit, body)
    if what in ("auto_spec", "project_new", "project_move", "autonomy_start", "autonomy_stop"):
        # Las acciones del panel de proyectos las ejecuta su dueno, con su propia validacion.
        return settings_projects.action(cockpit, body)
    if what == "memory_add":
        answer = cockpit.memory_add(body.get("text"))
        return ("memoria: %s" % ("añadido" if answer.get("ok") else answer.get("reason")),
                bool(answer.get("ok")), "memoria")
    if what == "memory_remove":
        answer = cockpit.memory_remove(body.get("entry"))
        return ("memoria: %s" % ("quitado" if answer.get("ok") else "no estaba"),
                bool(answer.get("ok")), "memoria")
    if what == "mcp_reload":
        answer = panels.mcp_reload(cockpit)
        return ("conectores: %s tools" % answer.get("tools"), bool(answer.get("ok")), "mcp")
    if what == "bridge":
        provider = str(body.get("provider") or "telegram")
        answer = (panels.daemon_toggle(cockpit, provider) if str(body.get("on") or "") == "on"
                  else panels.daemon_stop(cockpit))
        return ("puente: %s" % ("ON" if answer.get("running") else "OFF"),
                bool(answer.get("ok", True)), "puente")
    if what == "optimize":
        note, ok = triad_balance.apply(cockpit)
        return (note, ok, "modelos")
    if what == "recommend":
        from . import triad_recommend
        note, ok = triad_recommend.apply_recommended(cockpit)
        return (note, ok, "modelos")
    if what == "preset":
        from . import triad_presets
        note, ok = triad_presets.apply(cockpit, str(body.get("preset") or ""))
        return (note, ok, "modelos")
    if what == "detect_models":
        found = onboarding.probe_local()
        live = {vendor: len(row.get("models") or [])
                for vendor, row in found.items() if row.get("ready")}
        detail = ", ".join("%s: %d" % (name, count) for name, count in sorted(live.items()))
        return ("detectados %d modelos (%s)" % (sum(live.values()), detail or "ningún servidor respondió"),
                bool(live), "modelos")
    if what == "skill_mode":
        name = str(body.get("name") or "").strip()
        mode = str(body.get("mode") or "").strip()
        if not name or mode not in ("always", "auto", "off"):
            return ("modo inválido para %r" % name, False, "skills")
        if name not in settings_skills._routable_names():
            return ("%s no está en el paquete de routing: no viaja con los turnos" % name,
                    False, "skills")
        always, off = settings_skills._modes()
        always.discard(name)
        off.discard(name)
        if mode == "always":
            always.add(name)
        elif mode == "off":
            off.add(name)
        saved, reason = gov.save_skill_modes(always, off)
        return ("%s → %s%s" % (name, mode, "" if saved else " (no se pudo: %s)" % reason),
                saved, "skills")
    if what in ("mcp_add", "mcp_delete", "mcp_toggle"):
        ok, note = panels.mcp_write(cockpit, what[4:], body)
        return (note, ok, "mcp")
    if what == "key_delete":
        name = str(body.get("key_name") or "").strip()
        if not vault.looks_like_key(name):
            return ("%r no es una clave de la bóveda" % name, False, "seguridad")
        answer = vault.save({name: ""})
        left = answer.get("names") or []
        return ("bóveda: %s borrada (%d claves quedan)" % (name, len(left)),
                name not in left, "seguridad")
    if what == "save_skill":
        answer = panels.skills_save(cockpit, body.get("name"), body.get("text"))
        return ("SKILL.md de %s: %s" % (body.get("name"),
                                        "guardado" if answer.get("ok") else answer.get("reason")),
                bool(answer.get("ok")), "skills")
    if what == "architect":
        return _architect(cockpit, body)
    if what == "doctor":
        return _doctor()
    return ("acción desconocida: %s" % what, False, section)


def _architect(cockpit, body):
    message = str(body.get("message") or "").strip()
    if len(message) < 3:
        return ("escribe qué skill falta o qué mejorar", False, "skills")
    ok, answer = gov.action("/api/architect", {"message": message,
                                               "github": bool(body.get("github"))})
    text = ""
    if isinstance(answer, dict):
        text = str(answer.get("reply") or answer.get("answer") or answer.get("text") or "")
        if not text:
            text = json.dumps(answer, indent=2, ensure_ascii=False)[:4000]
    else:
        text = str(answer)[:4000]
    settings_tools.LAST["architect"] = text or "(sin respuesta)"
    return ("arquitecto: %s" % ("contestó" if ok else "no pudo contestar"), bool(ok), "skills")


def _doctor():
    """Pasa el doctor del protocolo y guarda su cola para el panel. Es lento (~1 min) y se dice."""
    command = [sys.executable, str(gov.PROTOCOL / "nexus" / "cli.py"), "doctor"]
    try:
        done = subprocess.run(command, capture_output=True, text=True, errors="replace",
                              timeout=300, cwd=str(gov.PROTOCOL))
    except (OSError, subprocess.SubprocessError) as exc:
        return ("el doctor no se pudo ejecutar: %s" % exc, False, "stats")
    tail = ((done.stdout or "") + (done.stderr or "")).strip().splitlines()[-14:]
    settings_tools.LAST["doctor"] = "\n".join(tail)
    green = done.returncode == 0 and "green" in (done.stdout or "").lower()
    return ("doctor: %s" % ("verde" if green else "revisar"), green, "stats")
