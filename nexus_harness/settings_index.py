"""El índice del manual: once categorías en doce destinos, agrupadas y numeradas.

Vive aparte de `settings.py` por la ley de 400 líneas y por responsabilidad: aquí se decide QUÉ se
puede visitar y cómo se numera; en `settings.py` se pinta la página y se guarda lo que manda un panel.

El número de sección (`§04`) no es decoración: es lo que permite decir «mira el §04» o «folio 07» sin
describir la pantalla. Se calcula una vez y lo usan el índice, la paleta de Ctrl+K y el título.
"""
import json
from html import escape
from urllib.parse import quote

GROUPS = (
    ("Modelo", "cpu", ("modelos", "memoria")),
    ("Trabajo", "folder", ("espacio", "skills")),
    ("Operación", "plug", ("mcp", "puente", "autonomia", "vps")),
    ("Sistema", "shield", ("seguridad", "apariencia", "stats", "about")),
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
    ("apariencia", "Apariencia (pantones)", "sliders", ()),
    ("stats", "Estadísticas y auditoría", "chart", ()),
    ("about", "Acerca de", "nexus", ()),
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
    "about": "acerca de version api uptime contrato salud motor informacion comprobar",
    "apariencia": "apariencia tema color panton paleta neon cyberpunk retro fosforo synthwave "
                  "ambar riso contraste densidad compacta aire espacio tipografia modo",
}


def resolve(section, sub):
    """La sección y el submenú que se van a pintar, aceptando lo que llegue por la URL."""
    name = str(section or "").strip().lower()
    if name not in NAMES:
        name = "modelos"
    subs = SUBS_OF[name]
    chosen = str(sub or "").strip().lower()
    return name, (chosen if chosen in subs else (subs[0] if subs else ""))


def destinations():
    """Los doce destinos del manual, en orden, con su número de sección.

    El número no es decoración: es lo que permite decir «mira el §04» o «folio 07» sin describir la
    pantalla. Se calcula una vez y lo usan el índice, la paleta de Ctrl+K y el título de la página.
    """
    rows, number = [], 0
    for group, group_icon, members in GROUPS:
        for name, label, icon_name, subs in SECTIONS:
            if name not in members:
                continue
            number += 1
            rows.append({"n": number, "group": group, "icon": group_icon, "name": name,
                         "label": label, "icon_name": icon_name, "subs": subs})
    return rows


def tree(active, sub, needle, state, token=""):
    """El índice del manual, agrupado por dominio y numerado. `needle` filtra: es el buscador sin script.

    Cada enlace lleva el token (una pantalla que pierde la credencial al navegar se muere a mitad de
    camino) y el pie dice QUÉ motor se está mirando: su versión y de qué fichero salieron los ajustes.
    """
    gt = ("&token=" + quote(str(token), safe="")) if token else ""
    blocks, group = [], None
    for row in destinations():
        name, label, subs = row["name"], row["label"], row["subs"]
        hit = (not needle or needle in label.lower() or needle in name
               or any(needle in text.lower() for _value, text in subs)
               or needle in SEARCH_TERMS.get(name, ""))
        if needle and not hit:
            subs = tuple((value, text) for value, text in subs
                         if needle in text.lower() or needle in SEARCH_TERMS.get(value, ""))
            if not subs:
                continue
        if row["group"] != group:
            group = row["group"]
            blocks.append('<p class="sgroup">%s</p>' % escape(group))
        folio = '<span class="folio">%02d</span>' % row["n"]
        if subs:
            opened = " open" if name == active else ""
            items = "".join('<li class="%s"><a href="/settings?section=%s&sub=%s%s">%s</a></li>'
                            % ("on" if (name == active and value == sub) else "", escape(name),
                               escape(value), gt, escape(text)) for value, text in subs)
            blocks.append('<details class="scat%s"%s><summary>%s%s</summary>'
                          '<ul class="ssubs">%s</ul></details>'
                          % (" on" if name == active else "", opened, folio, escape(label), items))
        else:
            blocks.append('<a class="scat-leaf%s" href="/settings?section=%s%s">%s%s</a>'
                          % (" on" if name == active else "", escape(name), gt, folio, escape(label)))
    if not blocks:
        blocks.append('<p class="dim">Nada coincide con «%s».</p>' % escape(needle))
    config = state.get("config") or {}
    version = state.get("version") or "?"
    source = config.get("source") or "defaults"
    gov_link = ('<a class="tree-gov" href="/gov?tab=setup%s">'
                '<span class="sigil" aria-hidden="true">◇</span>Gobernanza (protocolo)</a>' % gt)
    return ('<nav class="settings-tree">%s%s<p class="tree-foot">'
            'motor v%s · conectado<br><code>%s</code></p></nav>'
            % ("".join(blocks), gov_link, escape(version), escape(source)))


def palette(token=""):
    """El índice de Ctrl+K: los doce destinos con su número y las palabras con las que se buscan.

    Va como JSON en el documento para que el buscador sea instantáneo y no pida nada al motor; el
    `<form>` de al lado sigue funcionando sin script, filtrando el índice en el servidor.
    """
    gt = ("&token=" + quote(str(token), safe="")) if token else ""
    rows = []
    for row in destinations():
        name, label, subs = row["name"], row["label"], row["subs"]
        entries = ([(value, "%s · %s" % (label, text)) for value, text in subs] if subs
                   else [(name, label)])
        for value, text in entries:
            href = ("/settings?section=%s&sub=%s%s" % (name, value, gt) if subs
                    else "/settings?section=%s%s" % (name, gt))
            rows.append({"folio": "%02d" % row["n"], "label": text,
                         "where": "" if not subs else label,
                         "terms": SEARCH_TERMS.get(value, ""), "href": href})
    return json.dumps(rows, ensure_ascii=False)


