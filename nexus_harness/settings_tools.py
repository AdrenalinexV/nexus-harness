"""Paneles 06 a 08: conectores MCP, puente movil y estadisticas.

Dos decisiones que se repiten aqui:
- Lo que se ENSEÑA es lo que el motor puede leer AHORA (el catalogo del protocolo, los servidores que
  contestan, el demonio con su PID). Un panel que presume de 215 skills y no las puede abrir es un
  panel que miente.
- Lo que se puede HACER va por `POST /api/settings/do` y contesta un 303 al panel: funciona sin script
  y recargar no reenvia la accion.
"""
from pathlib import Path

from . import gov, panels
from . import settings_kit as kit

# La ultima respuesta de una accion (el arquitecto, el doctor). Vive en memoria del motor a proposito:
# es una respuesta para leer, no un estado que haya que sobrevivir a un reinicio.
LAST = {}
MAX_ROWS = 40


def mcp(cockpit):
    """Lista de conectores CONFIGURADOS, no solo los que ya arrancaron, con su estado en vivo.

    `describe()` del cliente solo habla de los servidores que corren o fallaron; un conector apagado
    no aparecia en ningun sitio, asi que no se podia encender desde la interfaz. La lista sale del
    fichero del operador y el estado en vivo se cruza por nombre.
    """
    from . import mcp_client
    config = mcp_client.load_config()
    state = panels.mcp_status(cockpit)
    live = {str(row.get("name")): row for row in state.get("servers") or []}
    cards = []
    for name, spec in sorted((config.get("servers") or {}).items()):
        row = live.get(name) or {}
        enabled = spec.get("enabled") is not False
        if not enabled:
            badge = '<span class="chip off">desactivado</span>'
        elif row.get("ready"):
            badge = '<span class="chip ok">conectado · %d tools</span>' % len(row.get("tools") or [])
        else:
            badge = '<span class="chip bad">%s</span>' % kit.esc(row.get("error") or "no arrancó")
        command = " ".join([str(spec.get("command") or "?"), *[str(a) for a in spec.get("args") or []]])
        detail = [command]
        if spec.get("cwd"):
            detail.append("cwd: %s" % spec["cwd"])
        if spec.get("env"):
            detail.append("env: %s" % ", ".join(sorted(spec["env"])))
        if row.get("tools"):
            detail.append("tools: %s" % ", ".join(row["tools"]))
        cards.append(
            '<div class="mcpserver"><header class="skhead"><strong>%s</strong>%s</header>'
            '<p class="dim mono">%s</p><footer class="skfoot">'
            '<form class="sform" method="post" action="/api/settings/do">%s%s%s'
            '<button class="ghost">%s</button></form>'
            '<form class="sform" method="post" action="/api/settings/do">%s%s'
            '<button class="ghost danger" onclick="return confirm(\'¿Eliminar %s?\')">Eliminar</button>'
            '</form></footer></div>'
            % (kit.esc(name), badge, kit.esc(" · ".join(detail)),
               kit.hidden("section", "mcp"), kit.hidden("what", "mcp_toggle"), kit.hidden("name", name),
               "Desactivar" if enabled else "Activar",
               kit.hidden("section", "mcp"), kit.hidden("what", "mcp_delete") + kit.hidden("name", name),
               kit.esc(name)))
    body = ('<h3 class="ssub">Conectores <span class="tag">%d</span></h3>'
            '<p class="dim">%s tools en total · fichero: <code>%s</code></p>'
            '<div class="mcpgrid">%s</div>'
            '<h3 class="ssub">Añadir o editar un servidor MCP</h3>'
            '<form class="sform" method="post" action="/api/settings/do">'
            % (len(config.get("servers") or {}), kit.esc(state.get("tools") or 0),
               kit.esc(str(mcp_client.CONFIG)), "".join(cards) or '<p class="dim">ninguno.</p>'))
    body += (kit.hidden("section", "mcp") + kit.hidden("what", "mcp_add")
             + '<div class="sgrid">'
             + kit.field("Nombre", '<input name="name" placeholder="p. ej. filesystem">')
             + kit.field("Comando", '<input name="command" placeholder="npx / python / node">')
             + kit.field("Argumentos", '<input name="args" placeholder="-y @modelcontextprotocol/server-filesystem C:\\ruta">')
             + kit.field("Directorio de trabajo (opcional)", '<input name="cwd" placeholder="c:\\ruta\\del\\servidor">')
             + "</div>"
             + kit.field("Variables de entorno (una por línea, CLAVE=valor)",
                         '<textarea name="env" rows="3" placeholder="API_KEY=…"></textarea>')
             + '<div class="sactions"><button class="primary">Guardar conector y recargar</button></div>'
               '</form>')
    return ("Conectores MCP", "Los servidores MCP configurados, su estado en vivo y sus tools.", body)


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


def _kpi(label, value, tone="", hint=""):
    """Una tarjeta KPI: el numero grande, la etiqueta, y de donde sale. Nada mas."""
    return ('<div class="kpi %s"><span class="kpi-label">%s</span>'
            '<strong class="kpi-value">%s</strong>%s</div>'
            % (kit.esc(tone), kit.esc(label), kit.esc(value),
               '<em class="kpi-hint">%s</em>' % kit.esc(hint) if hint else ""))


def _doctor_kpi():
    """El doctor no deja estado en disco: o lo has pasado en esta sesion, o no esta medido."""
    tail = LAST.get("doctor")
    if not tail:
        return _kpi("Estado del Doctor", "no medido", "off", "pásalo abajo (~1 min)")
    verdict = "verde" if "green" in tail.lower() else "revisar"
    return _kpi("Estado del Doctor", verdict, "ok" if verdict == "verde" else "warn",
                "última pasada de esta sesión")


def stats(cockpit):
    state, reason = gov.installer_state()
    money = state.get("money") if isinstance(state.get("money"), dict) else {}
    counts = state.get("fleet_counts") or {}
    lint = panels._protocol("nexus.checks.rules_lint")
    findings = len(lint.lint_repo(str(gov.PROTOCOL))["findings"]) if lint is not None else "?"
    last = (cockpit.state().get("chat") or {}).get("last") or {}
    verdict = last.get("verdict") or {}
    judgement = (last.get("judgement") or {}).get("verdict") or "—"
    active = (money.get("active") or {}).get("label") or "sin tarifa declarada"
    currency = money.get("currency") or "USD"
    net = money.get("net")
    cards = [
        _kpi("Proyectos Gobernados", "%s / %s" % (counts.get("governed", "?"),
                                                  counts.get("workspace", "?")),
             "ok" if counts.get("governed") else "off", "con .ai/CURRENT_SPEC.json"),
        _kpi("Tokens Evitados", money.get("avoided_tokens", "—"), "ok", "podados por el motor durmiente"),
        _kpi("Ahorro", ("%s %s" % (_shorter(net, 2), currency)) if net is not None else "sin medir",
             "ok" if net else "off", "neto, con la tarifa activa"),
        _kpi("Horas Ahorradas", _shorter(money.get("hours"), 1), "ok", "estimadas del ledger"),
        _kpi("Lint del Protocolo", "%s hallazgos" % findings, "ok" if findings == 0 else "bad",
             "el gobernador, medido ahora"),
        _doctor_kpi(),
        _kpi("Último Gate", ("exit %s" % verdict.get("exit")) if verdict else "sin turno",
             "ok" if verdict.get("ok") else ("bad" if verdict else "off"), "del último turno del chat"),
        _kpi("Último Juez", judgement,
             "ok" if judgement == "approve" else ("warn" if judgement == "—" else "bad"),
             "veredicto del modelo juez"),
        _kpi("Tarifa Activa", active, "ok", "precio por turno declarado"),
    ]
    if reason:
        cards.append(_kpi("Gobernanza", "no disponible", "warn", reason))
    body = ['<div class="kpigrid">%s</div>' % "".join(cards)]
    if LAST.get("doctor"):
        body.append('<h3 class="ssub">Última pasada del doctor</h3>')
        body.append('<pre class="sout">%s</pre>' % kit.esc(LAST["doctor"]))
    body.append('<form class="sform" method="post" action="/api/settings/do">'
                + kit.hidden("section", "stats")
                + '<div class="sactions"><button class="primary" name="what" value="doctor">'
                'Pasar el doctor del protocolo</button>'
                '<span class="dim">tarda ~1 minuto: recorre todos los self-tests del gobernador</span>'
                '</div></form>')
    return ("Estadísticas & Auditoría", "Lo que el protocolo mide de esta máquina, y el último gate.",
            "".join(body))
