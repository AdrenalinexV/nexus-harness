"""Paneles 02, 03 y 04: espacio de trabajo, seguridad y memoria.

Los tres tienen la misma forma: se enseña lo que HAY (medido, no recordado), se cambia lo que se puede
cambiar, y lo que no se puede cambiar desde aquí se dice con su motivo en vez de esconderse.
"""
import json
from pathlib import Path

from . import onboarding, policy, vault
from . import settings_kit as kit

SPEC_RELATIVE = Path(".ai") / "CURRENT_SPEC.json"
KEY_NAMES = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY",
             "GITHUB_TOKEN", "DISCORD_BOT_TOKEN", "TELEGRAM_BOT_TOKEN")


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


def _project_row(project, config):
    root = Path(config.workspace) / project
    spec = _spec_summary(root)
    if spec is None:
        state = '<span class="chip off">sin gobernanza (.ai/CURRENT_SPEC.json)</span>'
        goal = "sin criterios congelados"
    elif spec.get("error"):
        state = '<span class="chip bad">spec %s</span>' % kit.esc(spec["error"])
        goal = ""
    else:
        state = ('<span class="chip ok">%s criterios · sha %s</span>'
                 % (kit.esc(spec.get("cas") if spec.get("cas") is not None else "?"), kit.esc(spec["sha"])))
        goal = spec.get("goal") or ""
    command = (config.project_tests or {}).get(project, "")
    return ('<div class="srow">'
            '<div class="sgrow"><strong>%s</strong>%s<span class="dim">%s</span></div>'
            '<div class="sgrow"><input name="test:%s" value="%s" '
            'placeholder="comando de test (opcional: pytest, npm test…)"></div>'
            '<div class="sgrow">'
            '<button class="ghost" formaction="/api/settings/do" name="what" value="auto_spec">'
            'Regenerar Auto-Spec</button>'
            '<input type="hidden" name="project" value="%s">'
            '</div></div>'
            % (kit.esc(project), state, kit.esc(goal), kit.esc(project), kit.esc(command),
               kit.esc(project)))


def espacio(cockpit):
    config = cockpit.config
    projects = onboarding.projects(config.workspace)
    rows = "".join(_project_row(name, config) for name in projects) or \
        '<p class="dim">No hay proyectos en %s.</p>' % kit.esc(config.workspace)
    body = ('<div class="sgrid">%s</div><h3 class="ssub">Proyectos gobernados</h3>%s'
            % (kit.field("Carpeta de proyectos (workspace)",
                         '<input name="workspace" value="%s">' % kit.esc(config.workspace),
                         "donde viven y de donde salen las conversaciones"),
               rows))
    return ("Espacio de trabajo & Proyectos",
            "Qué se gobierna, qué tiene congelado cada proyecto y con qué se prueba.",
            kit.form("/api/settings", "espacio", body, submit="Guardar"))


# -- 03 seguridad y boveda ----------------------------------------------------------------------
def _policy_table():
    rows = []
    for level, table, allowed_in in policy.LEVELS:
        for _pattern, description in table:
            rows.append('<tr><td><code>%s</code></td><td>%s</td></tr>'
                        % (kit.esc(level), kit.esc(description)))
    return ('<table class="stable"><thead><tr><th>nivel</th><th>qué rechaza</th></tr></thead>'
            '<tbody>%s</tbody></table>' % "".join(rows))


def seguridad(cockpit):
    config = cockpit.config
    names = vault.names()
    stored = "".join('<span class="chip ok">%s</span>' % kit.esc(name) for name in names) \
        or '<span class="chip off">ninguna clave guardada</span>'
    body = ['<h3 class="ssub">Bóveda (DPAPI, por usuario)</h3><div class="chips">%s</div>' % stored]
    body.append('<div class="sgrid">')
    for name in KEY_NAMES:
        body.append(kit.field(name, '<input type="password" name="key:%s" placeholder="%s">'
                              % (kit.esc(name),
                                 "guardada — escribe para reemplazarla" if name in names else "vacía"),
                              ""))
    body.append("</div>")
    body.append('<p class="dim">Un valor guardado no se enseña nunca, ni aquí: solo se reemplaza. '
                'La clave viaja al motor desde el cofre, no desde este formulario.</p>')
    body.append('<h3 class="ssub">Política de comandos (zero-trust)</h3><div class="sgrid">')
    body.append(kit.field("Modo", *kit.select_input(
        "shell_policy", [(mode, mode) for mode in policy.MODES], config.shell_policy,
        "read_only no escribe nada; standard rechaza lo catastrófico y lo temerario; unrestricted lo "
        "permite todo menos lo catastrófico")))
    body.append("</div>")
    body.append(_policy_table())
    body.append('<p class="dim">Tiempo máximo por comando: %s s.</p>' % kit.esc(config.shell_timeout))
    return ("Seguridad & Bóveda (DPAPI Vault)",
            "Claves cifradas y hasta dónde puede llegar un comando.",
            kit.form("/api/settings", "seguridad", "".join(body), submit="Guardar"))


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
