"""Panel 05: las skills como tarjetas de verdad, y el arquitecto que las forja.

Por que tarjetas y no una lista: 144 skills en filas de ancho completo son una sábana que nadie lee.
Una tarjeta compacta dice lo mismo (nombre, de donde viene, si viaja o duerme) en un tercio del alto y
se puede filtrar sin scroll.

Lo que se ENSEÑA es medido: el catalogo sale del escaneo del protocolo (sus raices reales), el estado
`ACTIVA EN RAM` del ultimo turno de verdad, y el modo (`auto`/`always`/`off`) de lo que el operador
declaró en el gobernador. Lo que no se puede hacer se dice con su motivo, no se disimula con un boton
que no hace nada.
"""
from pathlib import Path

from . import onboarding, panels
from . import settings_kit as kit

CATALOG_MAX = 400
# 24 tarjetas por pagina: con 188 skills, una rejilla completa es un scroll de tres metros y el
# arquitecto (que es lo que se viene a usar) queda a dos pantallas de distancia.
PAGE = 24
ORIGIN_LABEL = {"shipped": "protocol", "prefixed": "protocol", "own": "operator"}


def _origin_of(module, name):
    """`protocol` o `operator`, con la MISMA regla que usa el escaneo del protocolo.

    Las filas del editor no traen `origin` (traen nombre, ruta, lineas...), asi que se calcula con su
    funcion en vez de adivinar por el prefijo: una copia de la regla se desvia el dia que cambie.
    """
    if module is not None:
        try:
            return str(module.origin_of(str(name)))
        except Exception:  # noqa: BLE001 -- la regla del gobernador no se pudo consultar
            module = None
    return "shipped" if str(name).startswith("nexus-") else "own"


def roots(cockpit):
    """Las raices que el protocolo escanea, con su etiqueta. Es la misma lista que su GUI."""
    module = panels._protocol("nexus.skills.user_catalog")
    targets = panels._protocol("nexus.skills.targets")
    workspace = Path(str(cockpit.config.workspace))
    projects = [workspace / name for name in onboarding.projects(workspace)]
    if module is None:
        return []
    try:
        return module.roots(hermes_home=targets.hermes_home() if targets else None, projects=projects)
    except Exception:  # noqa: BLE001 -- un escaneo que falla no puede tumbar el panel
        return []


def catalog(cockpit):
    """Una fila por skill, con su raiz. Se fusiona por nombre: gana la primera que aparece."""
    editor = panels._protocol("nexus.skills.editor")
    origins = panels._protocol("nexus.skills.user_catalog")
    if editor is None:
        return []
    merged, seen = [], set()
    for label, root in roots(cockpit):
        try:
            rows = editor.list_skills(str(root))
        except Exception:  # noqa: BLE001
            continue
        for row in rows or []:
            name = str(row.get("name") or "")
            if not name or name in seen:
                continue
            seen.add(name)
            row = dict(row)
            row["root"] = str(root)
            row["source"] = label
            row["origin"] = _origin_of(origins, name)
            merged.append(row)
    return merged[:CATALOG_MAX]


def _protocol_path():
    """Mete el repositorio del gobernador en `sys.path` y devuelve su ruta, o None.

    Se usaba `gov.NEXUS_SOURCE`, que NO existe (la constante se llama `PROTOCOL`): el AttributeError
    lo tragaba el `except` de abajo y las dos funciones devolvian "nada" en silencio -- por eso los
    botones de modo no aparecian y los modos guardados se leian como vacios. Un `except` que devuelve
    el valor neutro sin decir nada es un bug con buenos modales.
    """
    import sys
    from . import gov
    if gov.PROTOCOL is None:
        return None
    if str(gov.PROTOCOL) not in sys.path:
        sys.path.insert(0, str(gov.PROTOCOL))
    return str(gov.PROTOCOL)


def _modes():
    """`(always, off)` tal como los declaro el operador. Vacios si el gobernador no esta."""
    if _protocol_path() is None:
        return set(), set()
    try:
        from nexus import fleet
        skills = (fleet.settings() or {}).get("skills") or {}
        return ({str(n) for n in (skills.get("always") or [])},
                {str(n) for n in (skills.get("off") or [])})
    except Exception:  # noqa: BLE001 -- sin gobernador no hay declaracion que obedecer
        return set(), set()


def _routable_names():
    """Los nombres que el paquete de routing conoce: solo esos pueden viajar con `always`."""
    if _protocol_path() is None:
        return set()
    try:
        from nexus.skills import catalog as protocol_catalog
        return {str(entry.get("name")) for entry in protocol_catalog.pack() or []}
    except Exception:  # noqa: BLE001 -- se dice en el panel, no se finge que no hay skills
        return set()


def _active(cockpit):
    last = (cockpit.state().get("chat") or {}).get("last") or {}
    return {str(name) for name in (last.get("skills") or [])}


def _kind(row):
    """`protocol` o `operator`, con la etiqueta ya traducida. Una sola puerta para la regla."""
    return ORIGIN_LABEL.get(str(row.get("origin"))) or "operator"


def _counts(rows, active, always, off):
    laws = sum(1 for row in rows if _kind(row) == "protocol")
    return {"all": len(rows), "ram": len(active), "dormant": max(0, len(rows) - len(active)),
            "laws": laws, "own": len(rows) - laws, "always": len(always), "off": len(off)}


def _filter(rows, chosen, needle, active):
    if chosen == "ram":
        rows = [row for row in rows if row.get("name") in active]
    elif chosen == "dormant":
        rows = [row for row in rows if row.get("name") not in active]
    elif chosen == "laws":
        rows = [row for row in rows if _kind(row) == "protocol"]
    elif chosen == "own":
        rows = [row for row in rows if _kind(row) == "operator"]
    if needle:
        rows = [row for row in rows
                if needle in str(row.get("name") or "").lower()
                or needle in str(row.get("description") or "").lower()]
    return rows


def _mode_buttons(name, always, off, routable):
    """Los tres modos, con el actual marcado. `what` viaja oculto y el boton manda el modo."""
    if not routable:
        return '<span class="dim">fuera del paquete de routing: se edita, no se inyecta</span>'
    state = "always" if name in always else ("off" if name in off else "auto")
    buttons = ['<input type="hidden" name="what" value="skill_mode">']
    for value, label in (("always", "Activar siempre"), ("auto", "Auto"), ("off", "Dormir")):
        buttons.append('<button class="modebtn%s" name="mode" value="%s">%s</button>'
                       % (" on" if state == value else "", value, label))
    return "".join(buttons)


def _card(row, active, always, off, routable):
    name = str(row.get("name") or "?")
    kind = _kind(row)
    in_ram = name in active
    state = "ACTIVA EN RAM" if in_ram else "DORMIDA 0-TOKEN"
    badge = "ok" if kind == "protocol" else "warn"
    broken = ("" if row.get("valid", True) else
              '<span class="chip bad" title="sin frontmatter válido">sin contrato</span>')
    return ('<article class="skcard">'
            '<header class="skhead"><strong>%s</strong>'
            '<span class="chip %s">%s</span><span class="chip %s">%s</span>%s</header>'
            '<p class="skdesc">%s</p>'
            '<footer class="skfoot">'
            '<form class="sform" method="post" action="/api/settings/do">%s%s%s'
            '<div class="modes">%s</div></form>'
            '<button class="ghost" data-skill="%s" data-root="%s">Ver / Editar SKILL.md</button>'
            '</footer></article>'
            % (kit.esc(name), badge, kit.esc(kind), "ok" if in_ram else "off", kit.esc(state), broken,
               kit.esc(str(row.get("description") or "")[:160]), kit.hidden("section", "skills"),
               kit.hidden("name", name), kit.hidden("root", str(row.get("root") or "")),
               _mode_buttons(name, always, off, routable), kit.esc(name), kit.esc(str(row.get("root") or ""))))


def _pills(counts, chosen, needle=""):
    """Las cinco pastillas, en UNA fila. El buscador viaja en cada enlace para no perderlo al filtrar."""
    tail = ("&q=" + kit.esc(needle)) if needle else ""

    def pill(value, label):
        return ('<a class="fpill%s" href="/settings?section=skills&f=%s%s">%s</a>'
                % (" on" if chosen == value else "", value, tail, kit.esc(label)))
    return "".join([
        pill("all", "Todas (%d)" % counts["all"]),
        pill("ram", "Activas en Proyecto (%d)" % counts["ram"]),
        pill("dormant", "Dormidas 0-Token (%d)" % counts["dormant"]),
        pill("laws", "Leyes Globales (%d)" % counts["laws"]),
        pill("own", "Propias del Operador (%d)" % counts["own"]),
    ])


def _pager(page, pages, chosen, needle):
    """Paginacion de verdad: 24 tarjetas por pagina, no un corte mudo a las 120."""
    if pages <= 1:
        return ""

    def link(target, label, cls=""):
        return ('<a class="fpill%s" href="/settings?section=skills&f=%s%s&p=%d">%s</a>'
                % (cls, chosen, ("&q=" + kit.esc(needle)) if needle else "", target, kit.esc(label)))
    parts = [link(page - 1, "← Anterior") if page > 1 else ""]
    parts.append('<span class="dim">página %d de %d</span>' % (page, pages))
    parts.append(link(page + 1, "Siguiente →") if page < pages else "")
    return '<div class="pager">%s</div>' % "".join(parts)


def _architect():
    """El Skill Architect: describe la skill, opcionalmente busca referencias, y forja."""
    return ('<div class="arch">'
            '<p class="dim">Describe la skill que te falta; el arquitecto del protocolo la diseña '
            '(y con GitHub Scout busca referencias reales antes de escribirla).</p>'
            '<form class="sform" method="post" action="/api/settings/do">'
            + kit.hidden("section", "skills") + kit.hidden("what", "architect")
            + '<div class="sgrow"><input name="message" placeholder="p. ej. Especialista en Rust + Tauri v2" '
              'class="wide"></div>'
            + '<label class="check"><input type="checkbox" name="github" value="on"> '
              'Buscar referencias reales en GitHub (GitHub Scout)</label>'
            + '<div class="sactions"><button class="primary">Diseñar y Forjar Skill</button></div>'
              '</form></div>')


def _preview():
    from . import settings_tools
    text = settings_tools.LAST.get("architect")
    if not text:
        return ""
    return ('<h3 class="ssub">Previsualización generada</h3>'
            '<pre class="sout">%s</pre>' % kit.esc(text))


def skills(cockpit, query):
    """La pantalla entera de skills: arquitecto ARRIBA, filtros en una fila, rejilla legible."""
    needle = str((query.get("q") or [""])[0]).strip().lower()
    chosen = str((query.get("f") or ["all"])[0]).strip().lower()
    if chosen not in ("all", "ram", "dormant", "laws", "own"):
        chosen = "all"
    try:
        page = max(1, int(str((query.get("p") or ["1"])[0] or 1)))
    except ValueError:
        page = 1
    rows = catalog(cockpit)
    active = _active(cockpit)
    always, off = _modes()
    routable = _routable_names()
    # Las que el motor PUEDE inyectar van primero: son las que se tocan, y enterrarlas detras de 170
    # filas de skills del operador hace que su boton de modo no exista en la practica (medido: 0
    # botones visibles con 188 skills, porque las 8 del paquete caian mas alla del corte).
    rows.sort(key=lambda row: (0 if str(row.get("name")) in routable else 1,
                               0 if _kind(row) == "protocol" else 1,
                               str(row.get("name") or "")))
    counts = _counts(rows, active, always, off)
    shown = _filter(rows, chosen, needle, active)
    pages = max(1, -(-len(shown) // PAGE))
    page = min(page, pages)
    window = shown[(page - 1) * PAGE: page * PAGE]
    cards = "".join(_card(row, active, always, off, str(row.get("name")) in routable)
                    for row in window)
    # Sin paquete de routing no hay botones de modo, y eso se dice: un boton ausente sin explicacion
    # se lee como una funcionalidad que falta, no como un motor al que le falta el gobernador.
    pack_note = ("" if routable else
                 '<p class="snote bad">No se pudo leer el paquete de routing del protocolo: los modos '
                 '(siempre / auto / dormir) no se pueden cambiar ahora mismo.</p>')
    # El buscador se arma aparte: mezclar `+` con `%` en la misma expresion hace que el `%` se aplique
    # solo al ultimo literal (lo que paso aqui una vez, y se vio en la pantalla, no en un test).
    search = ('<form method="get" action="/settings">' + kit.hidden("section", "skills")
              + kit.hidden("f", chosen)
              + '<input class="search" name="q" type="search" value="%s" '
                'placeholder="Buscar por nombre o descripción…">'
                '<button class="ghost">Buscar</button></form>' % kit.esc(needle))
    body = ('<div class="sstack">'
            '<section class="archtop">%s%s</section>'
            '<div class="filters">%s<div class="fpills">%s</div></div>'
            '<p class="dim">%d skills en %d raíces · %d en el paquete de routing · %d declaradas '
            'siempre · %d apagadas · mostrando %d–%d</p>'
            '<div class="skillgrid">%s</div>%s%s</div>'
            % (_architect(), _preview(), search, _pills(counts, chosen, needle),
               counts["all"], len(roots(cockpit)), len(routable), counts["always"], counts["off"],
               (page - 1) * PAGE + 1 if window else 0, (page - 1) * PAGE + len(window),
               cards, _pager(page, pages, chosen, needle), pack_note))
    return ("Skills & Skill Architect",
            "El catálogo medido, con su modo real, y el arquitecto que forja las que faltan.", body)
