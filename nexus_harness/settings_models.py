"""Panel 01: la triada de modelos, en una vista — quien escribe, quien juzga y con que numeros.

Los cuatro papeles se ven a la vez (grid 2x2) porque son una decision, no cuatro pantallas: quien
elige el obrero quiere ver contra que director y que juez lo esta emparejando. Los submenus del arbol
siguen llevando a cada tarjeta, pero no esconden las otras tres.

El proveedor sale de lo que este motor SABE hablar (`providers.VENDORS`): seis, y ninguno inventado.
No hay proveedor "custom" porque el motor no tiene un campo de URL por rol, y un selector que no
cambia nada es peor que no tenerlo. El modelo se escribe o se elige de lo que hay EN ESTA MAQUINA
ahora mismo; la lista se sondea en vivo en cada render (y el boton de detectar lo dice con numeros).
"""
from . import onboarding, panels
from . import settings_kit as kit

# (rol interno, ancla, titulo, que es)
ROLES = (
    ("director", "principal", "Director", "Modelo principal del chat: planifica y responde"),
    ("worker", "obrero", "Obrero", "obrero.py — repara en un Git worktree hasta que el gate pasa"),
    ("judge", "juez", "Juez", "Juez independiente: gate local $0, o el Jev de nube"),
)
SUBS = (("principal", "Modelo Principal (Director)"), ("obrero", "Obrero (Worktree Repair)"),
        ("juez", "Juez & Auditoría"), ("subagentes", "Subagentes"))
TITLE = dict(SUBS)


def _live_badge(state):
    """Un chip por servidor local: encendido con su numero de modelos, o apagado con su motivo."""
    rows = []
    for vendor, row in sorted((state.get("local") or {}).items()):
        live = bool(row.get("ready"))
        count = len(row.get("models") or [])
        rows.append('<span class="chip %s" data-vendor-chip="%s">%s · %s</span>'
                    % ("ok" if live else "off", kit.esc(vendor), kit.esc(vendor),
                       kit.esc("%d modelos" % count if live else (row.get("reason") or "apagado"))))
    return '<div class="chips">%s</div>' % ("".join(rows)
                                            or '<span class="chip off">sin servidores locales</span>')


def _datalist(state):
    """Todo lo detectado, con su proveedor en el valor y su nombre a la vista."""
    options = []
    for vendor, row in sorted((state.get("local") or {}).items()):
        for model in row.get("models") or []:
            options.append('<option data-vendor="%s" value="%s">%s</option>'
                           % (kit.esc(vendor), kit.esc("%s:%s" % (vendor, model)), kit.esc(model)))
    return '<datalist id="model-options">%s</datalist>' % "".join(options)


def _role_card(cockpit, role, anchor, title, what, info, focused):
    vendor_names = sorted((onboarding.VENDORS or {}).keys())
    vendors = "".join(kit.option(name, "%s%s" % (name, "" if (onboarding.VENDORS or {}).get(
        name, {}).get("local") else "  (nube)"), info.get("vendor")) for name in vendor_names)
    spec = str(info.get("spec") or "").strip()
    tone = "ok" if info.get("ready") else ("bad" if info.get("error") else "warn")
    body = ('<div class="rolegrid">'
            + kit.field("Proveedor", '<select name="vendor" data-role="%s">%s</select>' % (kit.esc(role), vendors),
                        "los locales se detectan solos; los de nube piden su clave en Seguridad")
            + kit.field("Modelo", '<input name="model" list="model-options" value="%s" '
                                  'placeholder="elige de la lista o escribe el id">' % kit.esc(info.get("model")),
                        "la lista son los modelos que responden ahora mismo")
            + "</div>")
    if info.get("error"):
        body += '<p class="snote bad">%s</p>' % kit.esc(info["error"])
    return ('<div class="rolecard%s" id="rol-%s">'
            '<div class="rolehead"><strong>%s</strong><span class="chip %s">%s</span></div>'
            '<p class="dim">%s</p>%s'
            '<form class="sform" method="post" action="/api/settings">%s'
            '<div class="sactions"><button class="primary">Aplicar cambios</button>'
            '<button class="ghost" formaction="/api/settings/do" name="what" value="detect_models">'
            '🔄 Detectar modelos en vivo</button></div></form></div>'
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


def panel(cockpit, sub=""):
    """La vista completa de modelos: los cuatro papeles y los numeros del turno."""
    state = panels.onboarding_status(cockpit)
    roles = state.get("roles") or {}
    focused = sub if sub in TITLE else ""
    anchor = focused or "principal"
    cards = "".join(_role_card(cockpit, role, an, title, what, roles.get(role) or {},
                               anchor == an) for role, an, title, what in ROLES)
    cards += _subagent_card(cockpit)
    body = ('<h3 class="ssub">Servidores locales</h3>%s%s'
            '<div class="rolegrid2">%s</div>'
            '<h3 class="ssub">Números del turno</h3>%s'
            % (_live_badge(state), _datalist(state), cards,
               kit.form("/api/settings", "modelos", '<div class="sgrid">%s</div>'
                        % kit.context_fields(cockpit.config), submit="Guardar números")))
    return (TITLE.get(focused, "Modelos (Tríada IA)"),
            "Quién escribe, quién juzga, y con qué presupuesto. Se sondea en vivo al abrir la vista.",
            body)
