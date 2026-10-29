"""Panel 01: la tríada de modelos, como una decisión de MÁQUINA además de una de gusto.

Tres barras antes de las tarjetas, en este orden y por una razón:

1. **Hardware** -- qué GPU, cuánta VRAM y cuánta libre hay ahora (`hardware_probe`). Sin este número,
   "Director 27B + Obrero 35B" parece gratis y no lo es: en 16 GB no caben a la vez.
2. **Alerta de swapping** -- si los roles usan más de un peso local, LM Studio los descarga y carga en
   cada cambio de fase. Con dos botones de un clic: unificar el peso residente, o mandar obrero y juez
   a la nube.
3. **Perfiles** -- los tres presets (`triad_presets`) ya resueltos contra lo que esta máquina tiene de
   verdad (servidores vivos, claves en la bóveda). Un preset que necesita una clave que no existe lo
   dice en sus notas en vez de guardar una configuración que fallará al primer turno.

Las tarjetas mantienen el `<select>` real: los locales se listan en vivo y marcan los que ya están
cargados en VRAM; los de nube, el catálogo curado del rol con su aviso si falta la clave. Un campo de
texto al lado acepta cualquier id escrito a mano, porque un catálogo no es una jaula.
"""
from .platform import hardware_probe
from .llm import provider_discovery
from . import onboarding, panels, triad_balance, triad_presets
from . import settings_kit as kit

# (rol interno, ancla, titulo, que es)
ROLES = (
    ("director", "principal", "Director", "Modelo principal del chat: planifica y responde"),
    ("worker", "obrero", "Obrero", "obrero.py — repara en un Git worktree hasta que el gate pasa"),
    ("judge", "juez", "Juez", "Juez independiente: gate local $0, o la auditoría cruzada de nube"),
)
SUBS = (("principal", "Modelo Principal (Director)"), ("obrero", "Obrero (Worktree Repair)"),
        ("juez", "Juez & Auditoría"), ("subagentes", "Subagentes"))
TITLE = dict(SUBS)
CEILINGS = ((75, "75 % · por defecto (deja el 25 % al PC, al juego o al coach)"),
            (50, "50 % · modo ligero (la GPU a medias, el resto para ti)"),
            (0, "0 % · todo en cloud (ni un MB de VRAM)"))
BIASES = (("ahorro", "Ahorro: lo local que quepa en el techo ($0 por turno)"),
          ("velocidad", "Velocidad: nube flash barata, GPU libre"))
MODE_LABELS = (
    ("gate", "Solo Gate Determinista · $0 · 0 ms (reglas, ley de 400, AST y tests)"),
    ("fast", "Gate + Juez IA Rápido (local $0 o Cloud Flash)"),
    ("adversary", "Gate + Juez Adversario Estricto (lógica y seguridad)"),
)


def _live_badge(state):
    """Un chip por servidor local: encendido con sus modelos y cuantos estan en VRAM."""
    rows = []
    for vendor, row in sorted((state.get("local") or {}).items()):
        live = bool(row.get("ready"))
        detail = ("%d modelos · %d en VRAM" % (len(row.get("models") or []),
                                               len(row.get("loaded") or []))
                  if live else (row.get("error") and "apagado" or row.get("reason") or "apagado"))
        rows.append('<span class="chip %s" data-vendor-chip="%s">%s · %s</span>'
                    % ("ok" if live else "off", kit.esc(vendor), kit.esc(vendor), kit.esc(detail)))
    return '<div class="chips">%s</div>' % ("".join(rows)
                                            or '<span class="chip off">sin servidores locales</span>')


def _hardware_bar(hardware, info):
    """La frase de la maquina, con el veredicto de la triada pegado al final."""
    tone = "ok" if not info["swapping"] else ("bad" if info["oversize"] else "warn")
    return ('<div class="hwbar"><span data-hw="summary">%s</span>'
            '<span class="chip %s" data-hw="state">%s</span></div>'
            % (kit.esc(hardware_probe.headline(hardware)), tone,
               kit.esc(triad_presets.state_text(info, hardware))))


def _action_form(what, label, extra="", primary=False):
    """Un boton que ejecuta una accion del panel: misma ruta que los demas formularios."""
    return ('<form class="inlineform" method="post" action="/api/settings/do">%s%s%s'
            '<button class="%s">%s</button></form>'
            % (kit.hidden("section", "modelos"), kit.hidden("what", what), extra,
               "primary" if primary else "ghost", kit.esc(label)))


def _swap_alert(info):
    """El aviso de VRAM con sus dos salidas de un clic. Vacio cuando no hay nada que avisar."""
    if not info["swapping"]:
        return ""
    return ('<div class="snote bad"><strong>Swapping de VRAM.</strong> Los roles usan %d pesos locales '
            'distintos (%s GB en total) en un motor de %s GB: se descarga uno y se carga otro en cada '
            'cambio de fase, ≈%d s por fase. Elige una salida:'
            '<div class="sactions">%s%s</div></div>'
            % (len(info["models"]), kit.esc(info["local_gb"]), kit.esc(info["vram_gb"]),
               int(info["seconds"]),
               _action_form("preset", "Unificar modelo local residente (0 s de swapping)",
                            kit.hidden("preset", "local"), primary=True),
               _action_form("preset", "Pasar obrero y juez a Cloud Flash",
                            kit.hidden("preset", "cloud"))))


def _recommend_card(cockpit, hardware, state):
    """La tríada que esta máquina puede sostener, ya decidida: elegir es un clic, no un examen."""
    from . import triad_recommend
    info = triad_recommend.recommend(cockpit.config, state, hardware)
    if not info.get("ok"):
        return ('<div class="card"><p><span class="chip warn">sin tríada posible</span> '
                '<span class="dim">%s</span></p></div>' % kit.esc(info.get("reason") or ""))
    return ('<div class="card"><p><strong>%s</strong> <span class="dim">%s</span></p>'
            '<p class="dim">%s</p>%s</div>'
            % (kit.esc(info.get("title") or info.get("id")),
               kit.esc(info.get("reason") or ""),
               kit.esc(" · ".join("%s = %s" % (role, spec)
                                  for role, spec in sorted(info["roles"].items()))),
               _action_form("recommend", "Aplicar la recomendada", "", primary=True)))


def _preset_bar(rows):
    """Los tres perfiles, ya resueltos contra esta maquina."""
    cards = []
    for row in rows:
        plan = row["plan"]
        resolved = ", ".join("%s=%s" % (role, spec) for role, spec in sorted(plan["roles"].items()))
        notes = " ".join(plan["notes"])
        cards.append('<div class="preset%s"><strong>%s</strong><p class="dim">%s</p>'
                     '<p class="mono">%s</p>%s%s</div>'
                     % ("" if plan["ok"] else " off", kit.esc(row["title"]), kit.esc(row["detail"]),
                        kit.esc(resolved or "(no resuelve ningún rol con lo que hay)"),
                        '<p class="snote%s">%s</p>' % ("" if plan["ok"] else " bad", kit.esc(notes))
                        if notes else "",
                        _action_form("preset", "Aplicar %s" % row["id"],
                                     kit.hidden("preset", row["id"]), primary=plan["ok"])))
    return '<div class="presets">%s</div>' % "".join(cards)


def _model_field(role, vendor, info, state, config):
    """El `<select>` real del rol + un campo libre para cualquier id."""
    rows = triad_presets.catalog(vendor, role, state, config)
    options = "".join(kit.option(value, label, str(info.get("model") or "")) for value, label in rows)
    control = ('<select name="model" data-role="%s" data-live="1">%s</select>'
               '<input class="freeid" name="model_free" value="" placeholder="o escribe cualquier id">'
               % (kit.esc(role), options))
    hint = ("los modelos que responden ahora mismo; los cargados en VRAM van marcados"
            if vendor in triad_presets.LOCAL else
            "catálogo curado del rol; el id libre de la derecha manda si lo rellenas")
    return kit.field("Modelo", control, hint)


def _judge_extras(cockpit, info, roles):
    """Modo del juez y el aviso de auditoria cruzada imposible."""
    mode = str(getattr(cockpit.config, "judge_mode", "fast") or "fast")
    control = ('<select name="judge_mode">%s</select>'
               % "".join(kit.option(value, label, mode) for value, label in MODE_LABELS))
    extras = kit.field("Modo del Juez", control,
                       "gate = sin llamada al modelo; adversary = busca el fallo, no el aprobado")
    director = str((roles.get("director") or {}).get("spec") or "")
    judge = str(info.get("spec") or "")
    if director and judge and director == judge:
        extras += ('<p class="snote warn">El juez es el MISMO modelo que el director: se aprueba a sí '
                   'mismo. Para auditoría cruzada de verdad, cámbialo a otro proveedor o modelo — o '
                   'deja el modo en «gate», que al menos no finge.</p>')
    return extras


def _worker_extras(cockpit, info, roles):
    """El toggle anti-recarga del obrero."""
    resident = bool(getattr(cockpit.config, "worker_resident", False))
    director = str((roles.get("director") or {}).get("spec") or "")
    vendor, _model = triad_presets.split_spec(director)
    control = ('<label class="switch"><input type="checkbox" name="worker_resident" value="on"%s> '
               'usar el mismo modelo residente que el director/juez</label>'
               % (" checked" if resident else ""))
    hint = ("un solo peso en VRAM: el obrero no dispara una recarga entre fases"
            if vendor in triad_presets.LOCAL else
            "solo tiene efecto si el director es local (%s)" % (director or "sin director"))
    return kit.field("VRAM del obrero", control, hint)


def _role_card(cockpit, role, anchor, title, what, info, focused, state, roles):
    vendor_names = sorted((onboarding.VENDORS or {}).keys())
    vendor = str(info.get("vendor") or "")
    vendors = "".join(kit.option(name, "%s%s" % (
        name, "" if (onboarding.VENDORS or {}).get(name, {}).get("local") else "  (nube)"), vendor)
        for name in vendor_names)
    tone = "ok" if info.get("ready") else ("bad" if info.get("error") else "warn")
    body = ('<div class="rolegrid">'
            + kit.field("Proveedor", '<select name="vendor" data-role="%s">%s</select>'
                        % (kit.esc(role), vendors),
                        "los locales se detectan solos; los de nube piden su clave en Seguridad")
            + _model_field(role, vendor, info, state, cockpit.config)
            + "</div>")
    if role == "judge":
        body += _judge_extras(cockpit, info, roles)
    if role == "worker":
        body += _worker_extras(cockpit, info, roles)
    if info.get("error"):
        body += '<p class="snote bad">%s</p>' % kit.esc(info["error"])
    return ('<div class="rolecard%s" id="rol-%s">'
            '<div class="rolehead"><strong>%s</strong><span class="chip %s">%s</span></div>'
            '<p class="dim">%s</p>%s'
            '<form class="sform" method="post" action="/api/settings">%s'
            '<div class="sactions"><button class="primary">Aplicar cambios</button>'
            '<button class="ghost" formaction="/api/settings/do" name="what" value="detect_models">'
            'Detectar modelos en vivo</button></div></form></div>'
            % (" focus" if focused else "", kit.esc(anchor), kit.esc(title), tone,
               kit.esc(info.get("model") or "sin modelo"), kit.esc(what), body,
               kit.hidden("section", "modelos") + kit.hidden("role", role) + kit.hidden("back", anchor)))


def _subagent_card(cockpit):
    """Los subagentes no tienen modelo propio: usan el del obrero. Se dice, no se disimula."""
    config = cockpit.config
    fields = (kit.field("Subagentes en paralelo", *kit.number_input("max_children", config.max_children))
              + kit.field("Pasos por subagente", *kit.number_input("subagent_steps", config.subagent_steps))
              + kit.field("Profundidad (1 = sin nietos)", *kit.number_input("subagent_depth", config.subagent_depth))
              + kit.field("Herramientas en paralelo", *kit.number_input("tool_workers", config.tool_workers))
              + kit.field("Pasos del obrero por turno", *kit.number_input("max_steps", config.max_steps))
              + kit.field("Reparaciones por turno", *kit.number_input("max_repairs", config.max_repairs)))
    return ('<div class="rolecard" id="rol-subagentes">'
            '<div class="rolehead"><strong>Subagentes</strong>'
            '<span class="chip off">heredan el modelo del obrero</span></div>'
            '<p class="dim">Un subagente trabaja en su propio worktree con el modelo del Obrero: no se '
            'le elige uno aparte, y un subagente no puede delegar a su vez.</p>'
            '<form class="sform" method="post" action="/api/settings">'
            + kit.hidden("section", "modelos") + kit.hidden("back", "subagentes")
            + '<div class="sgrid">%s</div>'
              '<div class="sactions"><button class="primary">Aplicar cambios</button></div>'
              '</form></div>' % fields)


def _worker_window(cockpit):
    """La ventana que el motor del obrero declara ahora mismo. 0 si no la publica o no esta."""
    try:
        return int(cockpit.router.window("worker") or 0)
    except Exception:  # noqa: BLE001 -- un panel de ajustes no puede caerse por un motor apagado
        return 0


def _ceiling_form(cockpit):
    """El techo de hardware y el sesgo del reparto. Se guarda con los demas numeros del turno."""
    config = cockpit.config
    ceiling = ('<select name="hardware_ceiling">%s</select>'
               % "".join(kit.option(value, label, int(getattr(config, "hardware_ceiling", 75)))
                         for value, label in CEILINGS))
    bias = ('<select name="triad_bias">%s</select>'
            % "".join(kit.option(value, label, str(getattr(config, "triad_bias", "ahorro")))
                      for value, label in BIASES))
    auto = ('<label class="switch"><input type="checkbox" name="triad_auto_adapt" value="on"%s> '
            'reajustar obrero y juez al cambiar el director entre local y nube</label>'
            % (" checked" if getattr(config, "triad_auto_adapt", True) else ""))
    fields = (kit.field("Techo máximo de hardware", ceiling,
                        "cuánta VRAM puede tocar el arnés; lo demás es del PC")
              + kit.field("Sesgo del reparto", bias,
                          "ahorro = modelos locales dentro del techo; velocidad = nube barata")
              + kit.field("Reacción automática", auto, ""))
    return kit.form("/api/settings", "modelos", '<div class="sgrid">%s</div>' % fields,
                    submit="Guardar reparto")


def _vram_bar(plan):
    """`[ Director/Obrero X GB | Juez Y GB | Reserva Z GB ]`, en % y en GB."""
    parts, legend = [], []
    for seg in plan["segments"]:
        width = max(0.0, min(100.0, seg["pct"]))
        parts.append('<span class="vseg %s" style="width:%.1f%%" title="%s: %s GB (%s %%)"></span>'
                     % (seg["key"], width, kit.esc(seg["label"]), kit.esc(seg["gb"]),
                        kit.esc(seg["pct"])))
        legend.append('<span class="vkey"><i class="vseg %s"></i>%s: %s GB (%s %%)</span>'
                      % (seg["key"], kit.esc(seg["label"]), kit.esc(seg["gb"]), kit.esc(seg["pct"])))
    room = plan["budget"]
    return ('<div class="vbar" data-vram="1">%s</div><div class="vlegend">%s</div>'
            '<p class="dim">Presupuesto del arnés: %s GB de %s GB (techo %s %%) · te quedan %s GB '
            'para el PC</p>'
            % ("".join(parts), "".join(legend), kit.esc(room["harness_gb"]), kit.esc(room["vram_gb"]),
               kit.esc(room["ceiling"]), kit.esc(room["reserve_gb"])))


def _plan_card(plan):
    """El plan auto-adaptativo: lo que el balanceador propone ahora mismo, con su boton."""
    resolved = ", ".join("%s=%s" % (role, spec) for role, spec in sorted(plan["roles"].items()))
    notes = " ".join(plan["notes"])
    return ('<div class="snote%s"><strong>Tríada equilibrada para tu hardware</strong>'
            '<p class="mono">%s</p><p class="dim">juez: %s%s</p>%s'
            '<div class="sactions">%s</div></div>'
            % ("" if plan["ok"] else " bad", kit.esc(resolved or "(sin resolver)"),
               kit.esc(plan["judge_mode"]), kit.esc(" · " + notes if notes else ""),
               _vram_bar(plan),
               _action_form("optimize", "Auto-optimizar la tríada para mi hardware", primary=plan["ok"])))


def _providers_bar(cockpit):
    """Los proveedores que esta maquina ya usa y los que estan a falta de una clave."""
    rows = provider_discovery.candidates(cockpit.config)
    if not rows:
        return ""
    chips, pending = [], []
    for row in rows:
        ready = bool(row["secret"]) or row.get("builtin")
        chips.append('<span class="chip %s" data-provider="%s">%s · %s</span>'
                     % ("ok" if ready else "warn", kit.esc(row["name"]), kit.esc(row["name"]),
                        kit.esc(row["base_url"])))
        if not ready:
            pending.append(row["name"])
    detail = ("Falta la clave de %s: pégala una vez en Seguridad y los perfiles cloud e híbrido "
              "funcionan al primer clic." % ", ".join(pending)) if pending else              "Detectados en tu configuración de Hermes; se usan sin copiar la clave a otro sitio."
    return '<div class="chips">%s</div><p class="dim">%s</p>' % ("".join(chips), kit.esc(detail))


def _hardware():
    """El sondeo, con su propia red: la cabina se pinta aunque `nvidia-smi` no exista."""
    try:
        return hardware_probe.report()
    except Exception:  # noqa: BLE001
        return {"gpus": [], "memory": {}, "cpu": {}}


def panel(cockpit, sub="", state=None, hardware=None):
    """La vista completa de modelos: hardware, alerta, perfiles y las cuatro tarjetas.

    `state`/`hardware` se pueden inyectar: es lo que permite probar el panel sin GPU y sin servidores
    encendidos, y lo que impide que una suite dependa de la maquina de quien la lanza.
    """
    state = state if state is not None else panels.onboarding_status(cockpit)
    roles = state.get("roles") or {}
    hardware = hardware if hardware is not None else _hardware()
    loaded = [model for row in (state.get("local") or {}).values() for model in row.get("loaded") or ()]
    info = triad_presets.collision(cockpit.config.roles, hardware, loaded)
    plan = triad_balance.optimize(cockpit.config, state, hardware)
    focused = sub if sub in TITLE else ""
    anchor = focused or "principal"
    cards = "".join(_role_card(cockpit, role, an, title, what, roles.get(role) or {},
                               anchor == an, state, roles) for role, an, title, what in ROLES)
    cards += _subagent_card(cockpit)
    body = ('<h3 class="ssub">Diagnóstico de hardware</h3>%s%s%s'
            '<h3 class="ssub">Tríada auto-adaptativa</h3>%s'
            '<h3 class="ssub">Recomendación para esta máquina</h3>%s'
            '<h3 class="ssub">Perfiles recomendados de la tríada (1 clic)</h3>%s'
            '<h3 class="ssub">Servidores y proveedores</h3>%s%s'
            '<div class="rolegrid2">%s</div>'
            '<h3 class="ssub">Números del turno</h3>%s'
            % (_hardware_bar(hardware, info), _swap_alert(info), _ceiling_form(cockpit),
               _plan_card(plan),
               _recommend_card(cockpit, hardware, state),
               _preset_bar(triad_presets.presets(cockpit, hardware, state)), _live_badge(state),
               _providers_bar(cockpit), cards,
               kit.form("/api/settings", "modelos", '<div class="sgrid">%s</div>'
                        % kit.context_fields(cockpit.config, _worker_window(cockpit), "obrero"),
                        submit="Guardar números")))
    return (TITLE.get(focused, "Modelos (Tríada IA)"),
            "Qué hardware hay, qué cabe en él y quién escribe, juzga y repara. Se sondea en vivo al "
            "abrir la vista.", body)
