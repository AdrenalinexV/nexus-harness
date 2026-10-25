"""Paneles 05 a 08: skills, conectores MCP, puente movil y estadisticas.

Dos decisiones que se repiten aqui:
- Lo que se ENSEÑA es lo que el motor puede leer AHORA (el catalogo del protocolo, los servidores que
  contestan, el demonio con su PID). Un panel que presume de 215 skills y no las puede abrir es un
  panel que miente.
- Lo que se puede HACER va por `POST /api/settings/do` y contesta un 303 al panel: funciona sin script
  y recargar no reenvia la accion.
"""
from pathlib import Path

from . import gov, onboarding, panels
from . import settings_kit as kit

# La ultima respuesta de una accion (el arquitecto, el doctor). Vive en memoria del motor a proposito:
# es una respuesta para leer, no un estado que haya que sobrevivir a un reinicio.
LAST = {}
MAX_ROWS = 40


def _catalog(cockpit):
    """El catalogo de skills del protocolo, medido por su propio escaneo.

    Se le pasa el home de Hermes (su resolvedor, `skills.targets.hermes_home`, no una copia de la
    regla) y los proyectos del workspace: sin esos dos datos el escaneo no encuentra raices y el panel
    diria "0 skills" con toda la razon -- medido, con ellos encuentra 144.
    """
    module = panels._protocol("nexus.skills.user_catalog")
    if module is None:
        return {}
    targets = panels._protocol("nexus.skills.targets")
    workspace = Path(str(cockpit.config.workspace))
    projects = [workspace / name for name in onboarding.projects(workspace)]
    try:
        return module.scan(hermes_home=targets.hermes_home() if targets else None, projects=projects)
    except Exception as exc:  # noqa: BLE001 -- un catalogo que falla no puede tumbar el panel
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def _skill_rows(scan):
    rows = (scan.get("rows") or [])[:MAX_ROWS]
    body = "".join('<div class="srow"><span>%s</span><span class="chip %s">%s</span>'
                   '<span class="dim">%s</span></div>'
                   % (kit.esc(row.get("name") or row.get("label") or "?"),
                      "ok" if row.get("origin") == "own" else "off",
                      kit.esc(row.get("origin") or "?"),
                      kit.esc(row.get("description") or "")) for row in rows)
    more = ""
    if (scan.get("rows") or [])[MAX_ROWS:]:
        more = '<p class="dim">… y %d más</p>' % len(scan["rows"][MAX_ROWS:])
    return body + more


def skills(cockpit, item=""):
    scan = _catalog(cockpit)
    head = ('<p class="dim">%s skills en %s · %s propias del operador · %s del protocolo</p>'
            % (kit.esc(len(scan.get("rows") or [])), kit.esc(", ".join(scan.get("roots") or []) or "?"),
               kit.esc(scan.get("own", 0)), kit.esc(scan.get("nexus", 0))))
    catalog = _skill_rows(scan) if scan.get("rows") else (
        '<p class="snote bad">%s</p>' % kit.esc(scan["error"]) if scan.get("error") else
        '<p class="dim">El escaneo del protocolo no encontró skills en %s.</p>'
        % kit.esc(", ".join(scan.get("roots") or []) or "(ninguna raíz)"))
    body = [head, '<div class="sstack">%s</div>' % catalog]
    editable = panels.skills_list(cockpit)
    links = "".join('<a class="srow-link" href="/settings?section=skills&item=%s">%s'
                    '<span class="dim">%s líneas</span></a>'
                    % (kit.esc(row["name"]), kit.esc(row["name"]), kit.esc(row.get("lines", "?")))
                    for row in (editable.get("skills") or []))
    body.append('<h3 class="ssub">Editable ahora <span class="tag">%s</span></h3>'
                '<p class="dim">Se edita lo que vive en %s.</p><div class="slist">%s</div>'
                % (kit.esc(len(editable.get("skills") or [])), kit.esc(editable.get("root") or "?"),
                   links or '<p class="dim">nada.</p>'))
    if item:
        read = panels.skills_read(cockpit, item)
        if read.get("ok"):
            body.append('<h3 class="ssub">%s</h3>' % kit.esc(item))
            body.append('<form class="sform" method="post" action="/api/settings/do">'
                        '<input type="hidden" name="section" value="skills">'
                        '<input type="hidden" name="name" value="%s">'
                        '<textarea name="text" spellcheck="false">%s</textarea>'
                        '<div class="sactions"><button class="primary" name="what" value="save_skill">'
                        'Guardar SKILL.md</button>'
                        '<span class="dim">%s líneas · sha %s</span></div></form>'
                        % (kit.esc(item), kit.esc(read.get("body") or ""),
                           kit.esc(read.get("lines", "?")), kit.esc(str(read.get("sha256") or "")[:12])))
        else:
            body.append('<p class="snote bad">%s</p>' % kit.esc(read.get("reason") or "no se pudo leer"))
    answer = LAST.get("architect")
    body.append('<h3 class="ssub">Skill Architect <span class="tag">GitHub Scout</span></h3>')
    if answer:
        body.append('<pre class="sout">%s</pre>' % kit.esc(answer))
    body.append('<form class="sform" method="post" action="/api/settings/do">'
                '<input type="hidden" name="section" value="skills">'
                '<div class="sgrow"><input name="message" placeholder="qué skill falta, o qué mejorar">'
                '<label class="scheck"><input type="checkbox" name="github" value="1"> mirar GitHub</label>'
                '<button class="primary" name="what" value="architect">Preguntar</button></div></form>')
    return ("Skills & Skill Architect",
            "El catálogo real, el editor de SKILL.md y el arquitecto conversacional.",
            "".join(body))


def mcp(cockpit):
    state = panels.mcp_status(cockpit)
    rows = []
    for server in state.get("servers") or []:
        tools = ", ".join(server.get("tools") or []) or "sin tools"
        rows.append('<div class="srow"><span>%s</span>'
                    '<span class="chip %s">%s</span><span class="dim">pid %s · %s</span></div>'
                    % (kit.esc(server.get("name")), "ok" if server.get("ready") else "bad",
                       "conectado" if server.get("ready") else kit.esc(server.get("error") or "caído"),
                       kit.esc(server.get("pid") or "-"), kit.esc(tools)))
    body = ('<p class="dim">%s conectores · %s tools · config: <code>%s</code></p>%s'
            % (kit.esc(len(state.get("servers") or [])), kit.esc(state.get("tools") or 0),
               kit.esc(state.get("config") or "-"), "".join(rows) or '<p class="dim">ninguno.</p>'))
    body += ('<form class="sform" method="post" action="/api/settings/do">'
             '<input type="hidden" name="section" value="mcp">'
             '<div class="sactions"><button class="primary" name="what" value="mcp_reload">'
             'Recargar conectores</button></div></form>')
    return ("Conectores MCP", "Los servidores MCP que este motor puede llamar, y su estado.",
            body)


def puente(cockpit):
    state = panels.daemon_status(cockpit)
    running = bool(state.get("running"))
    tail = "\n".join((state.get("tail") or [])[-12:]) or "(sin salida todavía)"
    body = ('<p><span class="chip %s">%s</span> <span class="dim">%s</span></p>'
            % ("ok" if running else "off", "ON" if running else "OFF",
               kit.esc("PID %s desde %s · cola %s" % (state.get("pid"), state.get("since"),
                                                      state.get("queue"))
                       if running else "parado")))
    body += ('<form class="sform" method="post" action="/api/settings/do">'
             '<input type="hidden" name="section" value="puente">'
             '<div class="sgrow"><select name="provider">%s%s</select>'
             '<input type="hidden" name="on" value="%s">'
             '<button class="primary" name="what" value="bridge">%s</button></div></form>'
             % (kit.option("telegram", "telegram", state.get("provider") or "telegram"),
                kit.option("discord", "discord", state.get("provider") or "telegram"),
                "off" if running else "on", "Detener el puente" if running else "Arrancar el puente"))
    body += ('<p class="dim">Log: <code>%s</code></p><pre class="sout">%s</pre>'
             % (kit.esc(state.get("log") or "-"), kit.esc(tail)))
    return ("Puente Móvil (Bots)", "El demonio que lleva los turnos al móvil, con su PID y su cola.",
            body)


def _shorter(value, digits):
    """Un numero que se lee. `0.9389249000000002 USD` es un volcado, no una cifra de dinero."""
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return value


def stats(cockpit):
    state, reason = gov.installer_state()
    money = state.get("money") if isinstance(state.get("money"), dict) else {}
    totals = ((state.get("impact") or {}).get("totals")) or {}
    counts = state.get("fleet_counts") or {}
    lint = panels._protocol("nexus.checks.rules_lint")
    findings = len(lint.lint_repo(str(gov.PROTOCOL))["findings"]) if lint is not None else "?"
    last = (cockpit.state().get("chat") or {}).get("last") or {}
    verdict = last.get("verdict") or {}
    active = (money.get("active") or {}).get("label") or "sin tarifa declarada"
    currency = money.get("currency") or "USD"
    rows = [("Proyectos", "%s gobernados de %s" % (counts.get("governed", "?"), counts.get("workspace", "?"))),
            ("Con medición", "%s de %s proyectos tienen historial" % (
                totals.get("projects", "?"), counts.get("indexed", "?"))),
            ("Ahorro neto", "%s %s" % (_shorter(money.get("net"), 2), currency)
             if money.get("net") is not None else "sin medir"),
            ("Tokens evitados", money.get("avoided_tokens", "—")),
            ("Horas ahorradas", _shorter(money.get("hours"), 1)),
            ("Tarifa activa", active),
            ("Último gate del chat", "exit %s" % verdict.get("exit") if verdict else "sin turno todavía"),
            ("Juez del último turno", ((last.get("judgement") or {}).get("verdict") or "—")),
            ("Lint del protocolo", "%s hallazgos" % findings)]
    if reason:
        rows.append(("Gobernanza", reason))
    table = "".join('<div class="srow"><span>%s</span><span class="mono">%s</span></div>'
                    % (kit.esc(name), kit.esc(value)) for name, value in rows)
    body = ['<div class="sstack">%s</div>' % table]
    if LAST.get("doctor"):
        body.append('<pre class="sout">%s</pre>' % kit.esc(LAST["doctor"]))
    body.append('<form class="sform" method="post" action="/api/settings/do">'
                '<input type="hidden" name="section" value="stats">'
                '<div class="sactions"><button class="primary" name="what" value="doctor">'
                'Pasar el doctor del protocolo</button>'
                '<span class="dim">tarda ~1 minuto: recorre todos los self-tests del gobernador</span>'
                '</div></form>')
    return ("Estadísticas & Auditoría", "Lo que el protocolo mide de esta máquina, y el último gate.",
            "".join(body))
