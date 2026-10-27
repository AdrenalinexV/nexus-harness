"""La pantalla de ahorro: una sola fuente por cifra, y la extrapolacion de costes declarada.

El defecto que arregla: la tarjeta «Tokens Evitados» leia el ledger de DINERO del gobernador
(3.653.208) y las barras verdes del grafico 1 leian los `impact panels` de OTRA fuente (1.091.148).
Dos numeros, dos dueños, y ninguno era el motor de este arnes -- que registraba 0 evitados porque el
libro de turnos no tenia ni un campo de ahorro.

Aqui todo sale del mismo sitio (`ledger.aggregate(rows)["savings"]`, calculado por `savings.py` request
a request) y lo del gobernador se ensena APARTE, etiquetado como suyo.

La tabla de extrapolacion NO es una cotizacion: es una proyeccion con precios DECLARADOS aqui, con el
multiplicador medido en esta maquina. El precio local no es dinero: es KV-cache y segundos de prefill,
que es lo que de verdad se ahorra cuando el modelo corre en tu GPU.
"""
from . import charts
from . import settings_kit as kit

MB_PER_TOKEN_KV = 0.25          # 27B tipico: 64 capas x 8 kv-heads x 128 dim x 2 bytes x 2 (K y V)
PREFILL_TOKENS_PER_S = 3000.0   # RTX 5070 Ti, declarado en este fichero
PRICES = (
    ("DeepSeek V4.1 Flash (declarado)", 0.25, 1.00),
    ("Claude Sonnet 4 (declarado)", 3.00, 15.00),
    ("OpenAI GPT-5 / o3 (declarado)", 2.50, 10.00),
)
LOCAL_LABEL = "LM Studio / Ollama en la RTX 5070 Ti"
NOTE = ("Precios DECLARADOS en `stats_savings.py` (USD por 1M tokens), no una cotizacion: cambian y "
        "esta tabla se lee como proyeccion de ORDEN DE MAGNITUD sobre los tokens medidos.")


def _saved_of(aggregate):
    return int(((aggregate or {}).get("savings") or {}).get("saved") or 0)


def _sent_of(aggregate):
    return int(((aggregate or {}).get("savings") or {}).get("sent") or 0)


def token_rows(cockpit, aggregate):
    """Una fila por proyecto de la cola, con la medida del motor. Misma fuente para las dos barras."""
    return rows_for(aggregate, _queue_names(cockpit)[:6])


def rows_for(aggregate, names):
    """Las barras de una lista de proyectos. Puro: se puede probar sin cockpit ni cola."""
    rows, by_project = [], ((aggregate or {}).get("by_project") or {})
    for name in names:
        bucket = by_project.get(name) or {}
        sent = int(bucket.get("tokens_sent") or 0)
        rows.append({"label": name, "parts": [
            {"value": sent, "tone": "accent"},
            # El ahorro del proyecto sale de la resta de la misma fuente: si no hay enviados medidos,
            # no se dibuja una barra verde de la nada (un 489 y un 0 al lado no significan nada).
            {"value": int(bucket.get("tokens_saved") or 0) if sent else 0, "tone": "ok"}]})
    return rows


def _queue_names(cockpit):
    from . import projects
    try:
        return [row["name"] for row in projects.queue(cockpit.config)]
    except Exception:  # noqa: BLE001 -- sin cola, la grafica dice que no hay proyectos
        return []


def cards(aggregate):
    """Los valores que van en las tarjetas, todos del mismo agregado."""
    saved, sent = _saved_of(aggregate), _sent_of(aggregate)
    return {"saved": saved, "sent": sent,
            "pct": (aggregate or {}).get("savings_pct"),
            "multiplier": (aggregate or {}).get("context_multiplier"),
            "measured": bool(sent or saved)}


def cost_table(aggregate):
    """Proyeccion de coste y de recursos locales sobre el ahorro medido."""
    saved, sent, baseline = _saved_of(aggregate), _sent_of(aggregate), \
        int(((aggregate or {}).get("savings") or {}).get("baseline") or 0)
    rows = []
    for label, price_in, price_out in PRICES:
        # El ahorro es de tokens de ENTRADA (el baseline es prompt); la salida se cobra aparte y no se
        # proyecta aqui para no inventar lo que no se midio.
        rows.append({"label": label, "value": round(saved / 1_000_000.0 * price_in, 4),
                     "tone": "ok",
                     "hint": "%s USD/1M entrada · ahorrado sobre %s tokens de baseline"
                             % (price_in, charts.fmt(baseline))})
    kv_mb = saved * MB_PER_TOKEN_KV
    rows.append({"label": LOCAL_LABEL, "value": round(saved / PREFILL_TOKENS_PER_S, 1), "tone": "violet",
                 "hint": "%s MB de KV-cache y segundos de prefill que no se pagan en la GPU"
                         % charts.fmt(round(kv_mb, 1))})
    return rows, {"saved": saved, "sent": sent, "baseline": baseline}


def block(cockpit, aggregate, money=None):
    """El bloque de ahorro: grafico de motor, componentes y tabla de extrapolacion."""
    values = cards(aggregate)
    measured = values["measured"]
    components = ((aggregate or {}).get("savings") or {})
    parts = [
        '<h3 class="ssub">Ahorro del motor · por request</h3>',
        '<p class="dim">%s</p>' % kit.esc(_caption(values)),
    ]
    if measured:
        parts.append('<div class="kpigrid four">%s%s%s%s</div>' % (
            _kpi("Tokens enviados", charts.fmt(values["sent"]), "accent", "medidos por request"),
            _kpi("Tokens evitados", charts.fmt(values["saved"]), "ok", "baseline - enviado"),
            _kpi("Ahorro real", ("%s %%" % values["pct"]) if values["pct"] is not None else "sin medir",
                 "ok", "sobre el baseline del harness tradicional"),
            _kpi("Contexto efectivo", ("x%s" % values["multiplier"])
                 if values["multiplier"] else "sin medir", "ok",
                 "cuantas veces mas cabria en la misma ventana")))
        parts.append('<p class="dim">Componentes: skills dormidas <strong>%s</strong> · poda de '
                     'herramientas <strong>%s</strong> · reparacion aislada <strong>%s</strong> · '
                     'coste del mapa AST <strong>%s</strong> · requests <strong>%s</strong></p>'
                     % (charts.fmt(components.get("dormant")), charts.fmt(components.get("pruned")),
                        charts.fmt(components.get("isolated")), charts.fmt(components.get("repomap")),
                        charts.fmt(components.get("requests"))))
    else:
        parts.append('<p class="snote warn">Sin requests medidas todavia: abre un chat con el motor '
                     "arrancado o lanza una corrida, y esta pantalla empezara a tener cifras propias "
                     "(las del gobernador no se mezclan aqui).</p>")
    table, data = cost_table(aggregate)
    parts.append('<h3 class="ssub">Extrapolacion de coste (tokens evitados medidos)</h3>'
                 '<div class="chartcard">%s<p class="dim">%s</p></div>'
                 % (charts.bars(table, width=560, label_width=250, unit=" USD" if False else " USD",
                                why="sin tokens evitados medidos no hay nada que extrapolar"),
                    kit.esc(NOTE)))
    parts.append('<p class="dim">Ledger del gobernador (su propia contabilidad, aparte): <strong>%s'
                 "</strong> tokens evitados a su manera.</p>"
                 % charts.fmt((money or {}).get("avoided_tokens")))
    return "".join(parts)


def _caption(values):
    if not values["measured"]:
        return "el motor no ha medido requests todavia"
    return ("%s enviados frente a %s de un harness tradicional: %s%% menos, contexto efectivo x%s"
            % (charts.fmt(values["sent"]), charts.fmt(
                int(((values["sent"] or 0) / max(0.0001, 1 - (values["pct"] or 0) / 100.0)))),
               values["pct"], values["multiplier"]))


def _kpi(label, value, tone="", hint=""):
    return ('<div class="kpi %s"><span class="kpi-label">%s</span>'
            '<strong class="kpi-value">%s</strong>%s</div>'
            % (kit.esc(tone), kit.esc(label), kit.esc(value),
               '<em class="kpi-hint">%s</em>' % kit.esc(hint) if hint else ""))


def selftest():
    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    aggregate = {"turns": 2, "savings": {"sent": 1000, "baseline": 5000, "saved": 4000,
                                         "dormant": 3000, "pruned": 1000, "isolated": 0,
                                         "repomap": 800, "requests": 4},
                 "savings_pct": 80.0, "context_multiplier": 5.0,
                 "by_project": {"Nexus-Harness": {"tokens_sent": 1000, "saved": 4000}}}
    values = cards(aggregate)
    check("la tarjeta sale del motor", values["saved"], 4000)
    check("y el porcentaje medido", values["pct"], 80.0)
    check("con el multiplicador", values["multiplier"], 5.0)
    empty = cards({"turns": 0})
    check("sin datos no se inventa un ahorro", empty["measured"], False)
    table, data = cost_table(aggregate)
    check("la tabla trae cuatro filas", len(table), 4)
    check("deepseek a 0.25/1M da 0.001", [row for row in table if "DeepSeek" in row["label"]][0]["value"],
          0.001)
    check("claude a 3/1M da 0.012",
          [row for row in table if "Claude" in row["label"]][0]["value"], 0.012)
    local = [row for row in table if "RTX" in row["label"]][0]
    check("local mide segundos de prefill", local["value"], round(4000 / 3000.0, 1))
    check("y avisa del KV-cache", "KV-cache" in local["hint"], True)
    check("el baseline viaja a la tabla", data["baseline"], 5000)
    node = _FakeCockpit()
    html = block(node, aggregate, {"avoided_tokens": 1234})
    check("el bloque pinta el grafico del motor", "Ahorro del motor" in html, True)
    check("y la tabla de extrapolacion", "Extrapolacion de coste" in html, True)
    check("y separa lo del gobernador", "Ledger del gobernador" in html, True)
    check("sin datos pide medida", "Sin requests medidas" in block(node, {"turns": 0}), True)
    return problems


class _FakeCockpit:
    config = type("C", (), {"workspace": ".", "project_order": []})()
    root = "."


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("stats_savings: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
