"""Paneles 02, 03 y 04: espacio de trabajo, seguridad y memoria.

Los tres tienen la misma forma: se enseña lo que HAY (medido, no recordado), se cambia lo que se puede
cambiar, y lo que no se puede cambiar desde aquí se dice con su motivo en vez de esconderse.
"""
import json
from pathlib import Path

from . import onboarding, vault
from . import settings_kit as kit

SPEC_RELATIVE = Path(".ai") / "CURRENT_SPEC.json"
KEY_NAMES = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY",
             "TYPESAFE_API_KEY", "GITHUB_TOKEN", "DISCORD_BOT_TOKEN", "TELEGRAM_BOT_TOKEN")


# -- 02 espacio de trabajo y proyectos -----------------------------------------------------------
def _spec_summary(project):
    """Lo que el proyecto tiene congelado, tal cual esta en disco. `None` si no hay nada congelado."""
    path = Path(project) / SPEC_RELATIVE
    if not path.is_file():
        return None
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"error": "ilegible"}
    return {"goal": spec.get("goal") or "", "cas": spec.get("cas_count"),
            "sha": str(spec.get("cas_sha256") or "")[:12], "id": spec.get("id") or ""}


def _project_card(name, spec, config):
    """Un proyecto gobernado: sus criterios congelados, su comando de test y sus tres acciones."""
    root = Path(config.workspace) / name
    criteria = spec.get("cas") if spec.get("cas") is not None else "?"
    tone = "ok" if spec.get("cas") else "warn"
    command = (config.project_tests or {}).get(name, "")
    raw = ""
    path = root / SPEC_RELATIVE
    if path.is_file():
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            raw = ""
    return ('<article class="projcard">'
            '<header class="skhead"><strong>%s</strong>'
            '<span class="chip %s">%s criterios · sha %s</span></header>'
            '<p class="dim">%s</p>'
            '<form class="sform" method="post" action="/api/settings">%s'
            '<div class="sgrow"><input name="test:%s" value="%s" '
            'placeholder="comando de test (pytest, npm test…)">'
            '<button class="primary">Guardar comando de test</button></div></form>'
            '<details class="specview"><summary>Ver Spec JSON (qué exige el Gate)</summary>'
            '<pre class="sout">%s</pre></details>'
            '<footer class="skfoot">'
            '<form class="sform" method="post" action="/api/settings/do">%s%s'
            '<button class="ghost">Regenerar Auto-Spec</button></form>'
            '<a class="chip" href="/?project=%s">Abrir en el Chat</a>'
            '</footer></article>'
            % (kit.esc(name), tone, kit.esc(criteria), kit.esc(str(spec.get("sha") or "—")),
               kit.esc(spec.get("goal") or "sin objetivo declarado"),
               kit.hidden("section", "espacio"), kit.esc(name), kit.esc(command),
               kit.esc(raw or "(no se pudo leer el spec)"),
               kit.hidden("section", "espacio"), kit.hidden("what", "auto_spec")
               + kit.hidden("project", name), kit.esc(name)))


def _plain_card(name):
    """Un proyecto sin gobernanza: se dice, y se ofrece el unico paso que falta."""
    return ('<article class="projcard plain"><header class="skhead"><strong>%s</strong>'
            '<span class="chip off">sin gobernanza</span></header>'
            '<p class="dim">Sin <code>.ai/CURRENT_SPEC.json</code>: el gate no tiene criterios que '
            'exigir aquí.</p>'
            '<footer class="skfoot"><form class="sform" method="post" action="/api/settings/do">%s%s'
            '<button class="primary">Activar Gobernanza + Generar Auto-Spec</button></form>'
            '<a class="chip" href="/?project=%s">Abrir en el Chat</a></footer></article>'
            % (kit.esc(name), kit.hidden("section", "espacio"), kit.hidden("what", "auto_spec")
               + kit.hidden("project", name), kit.esc(name)))


def espacio(cockpit):
    """Gobernados y no gobernados, en dos bloques. Una lista plana mezcla dos estados distintos."""
    config = cockpit.config
    governed, others = [], []
    for name in onboarding.projects(config.workspace):
        spec = _spec_summary(Path(config.workspace) / name)
        (governed if spec and not spec.get("error") else others).append((name, spec or {}))
    blocks = ('<div class="sgrid">%s</div>'
              % ("".join(_project_card(name, spec, config) for name, spec in governed)
                 or '<p class="dim">Ningún proyecto tiene criterios congelados todavía.</p>'))
    plain = ('<div class="sgrid">%s</div>'
             % ("".join(_plain_card(name) for name, _spec in others)
                or '<p class="dim">Todas las carpetas del workspace están gobernadas.</p>'))
    body = ('<h3 class="ssub">1 · Proyectos gobernados activos <span class="tag">%d</span></h3>'
            '%s'
            '<h3 class="ssub">2 · Otras carpetas del workspace <span class="tag">%d</span></h3>'
            '%s'
            '<h3 class="ssub">Carpeta de proyectos (workspace)</h3>%s'
            % (len(governed), blocks, len(others), plain,
               kit.form("/api/settings", "espacio",
                        kit.field("Workspace", '<input name="workspace" value="%s">'
                                  % kit.esc(config.workspace),
                                  "donde viven los proyectos y de donde salen las conversaciones"),
                        submit="Guardar workspace")))
    return ("Espacio de trabajo & Proyectos",
            "Qué se gobierna, qué tiene congelado cada proyecto y con qué se prueba.", body)


# -- 03 seguridad y boveda ----------------------------------------------------------------------
# Los tres modos, con el nombre que un operador entiende. El detalle fino de que patron rechaza cada
# nivel vive en `policy.py` (que es quien lo aplica); aqui se dice QUE hace cada modo en una linea, no
# una tabla de 25 filas que nadie lee y que ademas se queda vieja en cuanto se toca una regla.
POLICY_MODES = (
    ("read_only", "Solo lectura", "no escribe nada en el árbol: mira y contesta"),
    ("standard", "Estándar Seguro", "bloquea lo destructivo y lo temerario"),
    ("unrestricted", "Autónomo Worktree", "permite todo menos lo catastrófico"),
)


def _key_card(name, stored, is_sealed):
    """Una clave, su estado real y sus dos botones. Nunca su valor: no se puede leer, solo reemplazar."""
    if name in stored:
        badge = ('<span class="chip ok">🟢 Guardada en DPAPI</span>' if is_sealed else
                 '<span class="chip warn">🟠 Guardada sin cifrar</span>')
        placeholder = "guardada — escribe para reemplazarla"
    else:
        badge = '<span class="chip off">⚪ No configurada</span>'
        placeholder = "pega la clave y guarda"
    save = ('<form class="sform" method="post" action="/api/settings">'
            + kit.hidden("section", "seguridad")
            + '<div class="sgrow"><input type="password" name="key:%s" placeholder="%s">'
              '<button class="primary">Guardar en Bóveda DPAPI</button></div></form>'
            % (kit.esc(name), kit.esc(placeholder)))
    delete = ('<form class="sform" method="post" action="/api/settings/do">'
              + kit.hidden("section", "seguridad") + kit.hidden("key_name", name)
              + '<button class="ghost danger" name="what" value="key_delete" '
                'onclick="return confirm(\'¿Borrar %s de la bóveda?\')">Borrar clave</button></form>'
              % kit.esc(name))
    return ('<div class="keycard"><div class="sgrow"><strong>%s</strong>%s</div>%s%s</div>'
            % (kit.esc(name), badge, save, delete))


def seguridad(cockpit):
    config = cockpit.config
    stored = vault.names()
    is_sealed = vault.sealed()
    cards = "".join(_key_card(name, stored, is_sealed) for name in KEY_NAMES)
    options = "".join(
        '<label class="modeopt%s"><input type="radio" name="shell_policy" value="%s"%s>'
        '<span><strong>%s</strong><em>%s</em></span></label>'
        % (" on" if config.shell_policy == value else "", kit.esc(value),
           " checked" if config.shell_policy == value else "",
           kit.esc(title), kit.esc(desc))
        for value, title, desc in POLICY_MODES)
    body = ('<h3 class="ssub">Bóveda de claves <span class="tag">%s/%s</span></h3>'
            '<p class="dim">%s Un valor guardado no se enseña nunca, ni aquí: solo se reemplaza.</p>'
            '<div class="keygrid">%s</div>'
            '<h3 class="ssub">Permisos de comandos destructivos</h3>'
            '<p class="dim">Tiempo máximo por comando: %s s.</p>'
            % (kit.esc(len([n for n in stored if n in KEY_NAMES])), kit.esc(len(KEY_NAMES)),
               "Cifrado con DPAPI (atado a tu cuenta de Windows)." if is_sealed
               else "El cofre NO está cifrado en esta máquina: permisos de propietario solamente.",
               cards, kit.esc(config.shell_timeout)))
    # Los modos van DENTRO del formulario que los guarda: fuera no se enviarian y el panel diria
    # "sin cambios" con toda la razon (el mismo defecto que ya se midio en el panel de memoria).
    return ("Seguridad & Bóveda (DPAPI Vault)",
            "Claves cifradas y hasta dónde puede llegar un comando.",
            '<div class="sstack">%s</div>%s'
            % (body, kit.form("/api/settings", "seguridad",
                              '<div class="modes">%s</div>' % options, submit="Guardar permisos")))


# -- 04 memoria y contexto ----------------------------------------------------------------------
def _memory_rows(cockpit):
    state = cockpit.memory_state()
    entries = state.get("entries") or []
    if not entries:
        return '<p class="dim">Nada en memoria todavía.</p>'
    return "".join('<div class="srow"><span>%s</span>'
                   '<button class="ghost" formaction="/api/settings/do" name="what" value="memory_remove">'
                   'Quitar</button><input type="hidden" name="entry" value="%s"></div>'
                   % (kit.esc(entry), kit.esc(entry)) for entry in entries)


def memoria(cockpit):
    state = cockpit.memory_state()
    body = ['<h3 class="ssub">Hechos duraderos <span class="tag">%s/%s</span></h3>'
            % (kit.esc(state.get("count", 0)), kit.esc(state.get("limit_entries", "?")))]
    body.append('<form class="sform" method="post" action="/api/settings/do">'
                '<input type="hidden" name="section" value="memoria">'
                '<div class="sgrow"><input name="text" placeholder="un hecho que debe viajar en cada prompt">'
                '<button class="primary" name="what" value="memory_add">Añadir</button></div></form>')
    body.append(_memory_rows(cockpit))
    # Los campos de contexto van DENTRO del formulario que los guarda. Fuera no se enviaban y el panel
    # contestaba "sin cambios" con toda la razon: el formulario no llevaba nada que guardar. Medido en
    # el navegador con un clic de verdad.
    fields = ('<h3 class="ssub">Contexto del turno</h3><div class="sgrid">%s</div>'
              % kit.context_fields(cockpit.config))
    return ("Memoria y contexto",
            "Lo que el motor recuerda entre sesiones y cuánto contexto se le da a cada turno.",
            "<div class=\"sstack\">%s</div>%s"
            % ("".join(body), kit.form("/api/settings", "memoria", fields, submit="Guardar contexto")))
