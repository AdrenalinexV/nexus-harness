"""Panel 01: la triada de modelos -- quien escribe, quien juzga, y con que numeros.

El proveedor se elige de lo que este motor SABE hablar (`onboarding.VENDORS`) y el modelo se escribe o
se elige de la lista de lo que hay EN ESTA MAQUINA ahora mismo (LM Studio, Ollama, Orca). Un modelo de
nube se escribe a mano a proposito: un id de modelo es un identificador, y adivinarlo desde una lista
que no se puede sondear seria inventarselo.
"""
from . import onboarding, panels
from . import settings_kit as kit

SUBS = (("principal", "Modelo Principal (Director)"),
        ("obrero", "Obrero (Worktree Repair)"),
        ("juez", "Juez & Auditoría"),
        ("subagentes", "Subagentes"))
ROLE_OF = {"principal": "director", "obrero": "worker", "juez": "judge"}
TITLE = dict(SUBS)


def _servers(state):
    rows = []
    for vendor, row in sorted((state.get("local") or {}).items()):
        live = bool(row.get("ready"))
        models = row.get("models") or []
        rows.append('<span class="chip %s">%s · %s</span>'
                    % ("ok" if live else "off", kit.esc(vendor),
                       kit.esc("%d modelos" % len(models) if live else (row.get("reason") or "apagado"))))
    return '<div class="chips">%s</div>' % ("".join(rows) or '<span class="chip off">sin servidores locales</span>')


def _spec_datalist(state):
    seen = []
    for vendor, row in sorted((state.get("local") or {}).items()):
        for model in row.get("models") or []:
            seen.append("%s:%s" % (vendor, model))
    body = "".join('<option value="%s"></option>' % kit.esc(spec) for spec in seen)
    return '<datalist id="spec-options">%s</datalist>' % body


def _role(cockpit, sub):
    state = panels.onboarding_status(cockpit)
    role = ROLE_OF[sub]
    info = (state.get("roles") or {}).get(role) or {}
    vendors = "".join(kit.option(name, "%s%s" % (name, "" if cfg.get("local") else "  (nube)"),
                                 info.get("vendor"))
                      for name, cfg in sorted((onboarding.VENDORS or {}).items()))
    body = "<div class=\"sgrid\">"
    body += kit.field("Proveedor", '<select name="vendor">%s</select>' % vendors,
                      "los locales se detectan solos; los de nube piden su clave en Seguridad")
    body += kit.field("Modelo", '<input name="model" list="spec-options" value="%s">' % kit.esc(info.get("model")),
                      "elige de la lista o escribe el id exacto")
    body += "</div>"
    body += _spec_datalist(state)
    if info.get("error"):
        body += '<p class="snote bad">%s</p>' % kit.esc(info["error"])
    body += "<p class=\"dim\">Espec en uso: <code>%s</code></p>" % kit.esc(_spec_of(info) or "(sin espec)")
    body += _servers(state)
    body += ("<h3 class=\"ssub\">Números del turno</h3><div class=\"sgrid\">%s</div>"
             % kit.context_fields(cockpit.config))
    return (TITLE[sub], "Quién escribe, quién juzga, y el presupuesto del turno.",
            kit.form("/api/settings", "modelos", body, hidden_extra="".join(
                [kit.hidden("role", role), kit.hidden("back", sub)])))


def _spec_of(info):
    return str(info.get("spec") or "").strip()


def _subagents(cockpit):
    config = cockpit.config
    body = "<div class=\"sgrid\">"
    body += kit.field("Subagentes en paralelo", *kit.number_input("max_children", config.max_children))
    body += kit.field("Pasos por subagente", *kit.number_input("subagent_steps", config.subagent_steps))
    body += kit.field("Profundidad (1 = sin nietos)", *kit.number_input("subagent_depth", config.subagent_depth))
    body += kit.field("Herramientas en paralelo", *kit.number_input("tool_workers", config.tool_workers))
    body += kit.field("Pasos del obrero por turno", *kit.number_input("max_steps", config.max_steps))
    body += kit.field("Reparaciones por turno", *kit.number_input("max_repairs", config.max_repairs))
    body += "</div>"
    body += ("<p class=\"dim\">Un subagente no puede delegar a su vez: la profundidad se declara aquí y "
             "no la elige el modelo.</p>")
    return (TITLE["subagentes"], "Cuántos hijos abre el director y cuánto dura cada uno.",
            kit.form("/api/settings", "modelos", body, hidden_extra=kit.hidden("back", "subagentes")))


def panel(cockpit, sub=""):
    """Devuelve (titulo, subtitulo, html) para una vista del panel de modelos."""
    chosen = sub if sub in TITLE else "principal"
    return _subagents(cockpit) if chosen == "subagentes" else _role(cockpit, chosen)
