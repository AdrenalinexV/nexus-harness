"""Paneles 06 a 08: conectores MCP, puente movil y estadisticas.

Dos decisiones que se repiten aqui:
- Lo que se ENSEÑA es lo que el motor puede leer AHORA (el catalogo del protocolo, los servidores que
  contestan, el demonio con su PID). Un panel que presume de 215 skills y no las puede abrir es un
  panel que miente.
- Lo que se puede HACER va por `POST /api/settings/do` y contesta un 303 al panel: funciona sin script
  y recargar no reenvia la accion.

Las estadisticas llevan tres graficos, y son SVG escritos por `charts.py`: el motor congelado no
descarga nada, asi que una libreria de graficos seria una pantalla en blanco en cuanto no hubiera red.
Cada grafico declara su fuente; si no hay medida, se dice con palabras en el mismo hueco.
"""
from . import charts, gov, ledger, panels, projects, stats_savings
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
    from . import settings_vps
    body += settings_vps.block(cockpit)
    return ("Puente Móvil & Deploy VPS (Hive 24/7)",
            "Los dos modos de tener la colmena encendida: el demonio de este PC o el nodo 24/7 en el VPS.",
            body)


def _fmt_int(value):
    """Numeros con separador de miles: una cifra de ahorro sin separador no se lee."""
    try:
        return "{:,}".format(int(value or 0)).replace(",", ".")
    except (TypeError, ValueError):
        return str(value)


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


# -- las graficas ---------------------------------------------------------------------------------
def _gate_panels(state):
    """Los proyectos con registro de gates, por nombre. Un panel `present: False` no se dibuja."""
    rows = {}
    for panel in ((state.get("impact") or {}).get("panels") or []):
        name = str(panel.get("name") or "")
        if name and panel.get("present"):
            rows[name] = panel
    return rows


def _queue_names(cockpit):
    return [row["name"] for row in projects.queue(cockpit.config)]


def _token_rows(cockpit, state, aggregate):
    """Tokens consumidos y tokens que el gate evito, por proyecto. Dos fuentes, cada una declarada."""
    panels = _gate_panels(state)
    rows = []
    for name in _queue_names(cockpit)[:6]:
        panel = panels.get(name) or {}
        measured = panel.get("tokens_total")
        if measured is None:
            measured = ((aggregate.get("by_project") or {}).get(name) or {}).get("tokens", 0)
        rows.append({"label": name, "parts": [
            {"value": measured or 0, "tone": "accent"},
            {"value": panel.get("tokens_blocked") or 0, "tone": "ok"}]})
    return rows


def _triad_rows(aggregate, state):
    """La eficacia de la triada: primero el libro del arnes; si esta vacio, el registro de gates."""
    if aggregate.get("turns"):
        return ([{"label": "Aprobado a la primera (Director)", "value": aggregate["first_pass"],
                  "tone": "ok"},
                 {"label": "Reparado por el Obrero", "value": aggregate["repaired"], "tone": "warn"},
                 {"label": "Bloqueado por Gate/Juez", "value": aggregate["blocked"], "tone": "bad"}],
                "turnos", "libro de turnos del arnés · %d turnos" % aggregate["turns"])
    tally = {"0": 0, "10": 0, "20": 0}
    for panel in _gate_panels(state).values():
        for code, count in (panel.get("by_exit") or {}).items():
            if str(code) in tally:
                tally[str(code)] += int(count or 0)
    rows = [{"label": "Verde (exit 0)", "value": tally["0"], "tone": "ok"},
            {"label": "Bloqueado (exit 10)", "value": tally["10"], "tone": "bad"},
            {"label": "Sin verificar (exit 20)", "value": tally["20"], "tone": "warn"}]
    return rows, "runs", "registro de gates del gobernador (el libro del arnés aún no tiene turnos)"


def _minutes_per_block(money):
    """Los minutos por cierre bloqueado, derivados del propio ledger: la misma constante declarada."""
    hours = money.get("hours")
    blocked = money.get("blocked")
    if not hours or not blocked:
        return 0.0
    return float(hours) / float(blocked) * 60.0


def _health_charts(cockpit, state, aggregate=None):
    """Las tres barras horizontales del grafico 3: criterios, runs verdes y horas por proyecto.

    Los "runs verdes" salen del LIBRO DEL ARNES cuando ese proyecto tiene turnos medidos, y si no del
    registro del gobernador. Antes leian siempre los `impact panels`, asi que un turno verde medido hoy
    en el arnes no aparecia: dos fuentes otra vez, con el mismo defecto que la tarjeta de tokens.
    """
    queue = projects.queue(cockpit.config)[:8]
    panels = _gate_panels(state)
    buckets = (aggregate or {}).get("by_project") or {}
    minutes = _minutes_per_block(state.get("money") or {})
    criteria, green, hours = [], [], []
    for row in queue:
        name = row["name"]
        panel = panels.get(name) or {}
        bucket = buckets.get(name) or {}
        criteria.append({"label": name, "value": (row.get("spec") or {}).get("criteria") or 0,
                         "tone": "accent", "show_zero": True})
        measured_green = bucket.get("green")
        green.append({"label": name,
                      "value": (measured_green if measured_green is not None
                                else (panel.get("by_exit") or {}).get("0") or 0),
                      "tone": "ok", "show_zero": True})
        blocked = int(panel.get("blocked") or 0)
        hours.append({"label": name, "value": round(blocked * minutes / 60.0, 1),
                      "tone": "violet", "show_zero": True})
    blocks = (("Criterios de Spec congelados", criteria, ""),
              ("Runs verdes (libro del arnés · registro del gobernador)", green, ""),
              ("Horas ahorradas (bloqueos × minutos)", hours, " h"))
    return '<div class="chartgrid">%s</div>' % "".join(
        '<div class="chartcard"><h4>%s</h4>%s</div>'
        % (kit.esc(title),
           charts.bars(rows, width=430, label_width=140, unit=unit,
                       why="sin medidas todavía"))
        for title, rows, unit in blocks)


def _charts(cockpit, state, aggregate):
    """Los tres graficos nativos, con su fuente escrita al lado. Sin CDN, sin script, sin adivinar."""
    money = state.get("money") or {}
    currency = money.get("currency") or "USD"
    net = money.get("net")
    avoided = money.get("avoided_tokens")
    tokens = charts.columns(stats_savings.token_rows(cockpit, aggregate), width=600, height=220,
                            why="sin requests medidas por el motor en los proyectos de la cola")
    triad_rows, centre, source = _triad_rows(aggregate, state)
    donut = charts.donut(triad_rows, size=200, centre=centre)
    price = (money.get("active") or {}).get("label") or "sin tarifa declarada"
    # La tarjeta y estas barras leen el MISMO agregado del motor. Lo del gobernador se nombra como
    # suyo, con su cifra, en su linea: mezclar las dos fuentes en un grafico fue el defecto original.
    values = stats_savings.cards(aggregate)
    caption = ("Motor (libro del arnés): <strong>%s</strong> enviados · <strong>%s</strong> evitados "
               "· ahorro <strong>%s%%</strong>. Gobernador (su ledger, aparte): %s tokens evitados · "
               "ahorro neto %s %s a la tarifa «%s»."
               % (charts.fmt(values["sent"]), charts.fmt(values["saved"]),
                  values["pct"] if values["pct"] is not None else "sin medir",
                  charts.fmt(avoided) if avoided is not None else "sin medir",
                  charts.fmt(net) if net is not None else "sin medir", kit.esc(currency),
                  kit.esc(price)))
    return ('<h3 class="ssub">Gráfico 1 · Tokens consumidos vs evitados por proyecto</h3>'
            '<div class="chartcard">%s<div class="vlegends">'
            '<span class="vlegend"><i style="background:#3b82f6"></i>consumidos</span>'
            '<span class="vlegend"><i style="background:#22c55e"></i>evitados por el gate</span></div>'
            '<p class="dim">%s</p></div>'
            '<h3 class="ssub">Gráfico 2 · Eficacia de la tríada y del gate</h3>'
            '<div class="chartcard chartrow">%s<div class="chartside">%s'
            '<p class="dim">%s</p></div></div>'
            '<h3 class="ssub">Gráfico 3 · Actividad y salud por proyecto gobernado</h3>%s'
            % (tokens, caption, donut, charts.legend(triad_rows), kit.esc(source),
               _health_charts(cockpit, state, aggregate)))


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
    rows = ledger.history(cockpit.config.workspace, _queue_names(cockpit), extra=[cockpit.root])
    aggregate = ledger.aggregate(rows)
    cards = [
        _kpi("Proyectos Gobernados", "%s / %s" % (counts.get("governed", "?"),
                                                  counts.get("workspace", "?")),
             "ok" if counts.get("governed") else "off", "con .ai/CURRENT_SPEC.json"),
        _kpi("Tokens Evitados (motor)", _fmt_int(stats_savings.cards(aggregate)["saved"]), "ok",
             "baseline - enviado, medido por request"),
        _kpi("Ahorro real", ("%s %%" % stats_savings.cards(aggregate)["pct"])
             if stats_savings.cards(aggregate)["pct"] is not None else "sin medir",
             "ok" if stats_savings.cards(aggregate)["measured"] else "off",
             "sobre el baseline tradicional · x%s de contexto"
             % (stats_savings.cards(aggregate)["multiplier"] or "?")),
        _kpi("Ahorro del gobernador", ("%s %s" % (_shorter(net, 2), currency)) if net is not None
             else "sin medir", "off", "su ledger, contado aparte"),
        _kpi("Horas Ahorradas", _shorter(money.get("hours"), 1), "ok", "estimadas del ledger"),
        _kpi("Lint del Protocolo", "%s hallazgos" % findings, "ok" if findings == 0 else "bad",
             "el gobernador, medido ahora"),
        _doctor_kpi(),
        _kpi("Último Gate", ("exit %s" % verdict.get("exit")) if verdict else "sin turno",
             "ok" if verdict.get("ok") else ("bad" if verdict else "off"),
             "del último turno del chat"),
        _kpi("Último Juez", judgement,
             "ok" if judgement == "approve" else ("warn" if judgement == "—" else "bad"),
             "veredicto del modelo juez"),
        _kpi("Turnos Medidos", "%d" % aggregate.get("turns", 0),
             "ok" if aggregate.get("turns") else "off", "libro de turnos del arnés"),
        _kpi("Tarifa Activa", active, "ok", "precio por turno declarado"),
    ]
    if reason:
        cards.append(_kpi("Gobernanza", "no disponible", "warn", reason))
    body = ['<div class="kpigrid four">%s</div>' % "".join(cards)]
    body.append(_charts(cockpit, state, aggregate))
    body.append(stats_savings.block(cockpit, aggregate, money))
    assumptions = money.get("assumptions") or []
    if assumptions:
        body.append('<details class="sources"><summary>De dónde sale cada cifra</summary>'
                    '<ul class="dim">%s</ul></details>'
                    % "".join("<li>%s</li>" % kit.esc(one) for one in assumptions))
    if LAST.get("doctor"):
        body.append('<h3 class="ssub">Última pasada del doctor</h3>')
        body.append('<pre class="sout">%s</pre>' % kit.esc(LAST["doctor"]))
    body.append('<form class="sform" method="post" action="/api/settings/do">'
                + kit.hidden("section", "stats")
                + '<div class="sactions"><button class="primary" name="what" value="doctor">'
                'Pasar el doctor del protocolo</button>'
                '<span class="dim">tarda ~1 minuto: recorre todos los self-tests del gobernador</span>'
                '</div></form>')
    return ("Estadísticas & Auditoría",
            "Lo que el protocolo mide de esta máquina, el último gate y tres gráficos con datos reales.",
            "".join(body))
