"""Los graficos: SVG puro, determinista, sin red y sin mentir cuando no hay datos.

Lo que se mide aqui es lo que puede romperse en silencio: que una etiqueta con `<` no se convierta en
marcado, que un cero no dibuje un anillo vacio diciendo "0", y que la misma entrada produzca los mismos
bytes (si dos llamadas difirieran, la pantalla parpadearia en cada recarga).
"""
from .. import charts


def check(name, got, expect, failures):
    if got != expect:
        failures.append("%s: %r, esperaba %r" % (name, got, expect))


def test_empty(failures):
    svg = charts.empty(320, 120, "sin datos")
    check("an empty chart still draws", svg.startswith("<svg"), True, failures)
    check("and says why", "sin datos" in svg, True, failures)
    check("nothing is fetched", "http" in svg.lower(), False, failures)


def test_donut(failures):
    rows = [{"label": "verde", "value": 6, "tone": "ok"},
            {"label": "reparado", "value": 3, "tone": "warn"},
            {"label": "bloqueado", "value": 1, "tone": "bad"},
            {"label": "cero", "value": 0, "tone": "idle"}]
    svg = charts.donut(rows, size=180, centre="turnos")
    check("one arc per non-zero row", svg.count("<circle"), 4, failures)  # 3 arcs + the track
    check("the total is in the middle", ">10<" in svg, True, failures)
    check("and its unit", "turnos" in svg, True, failures)
    check("a zero row is not drawn", "cero" in svg, False, failures)
    check("no data is said in words, not drawn as zero",
          "sin decisiones" in charts.donut([], why="sin decisiones"), True, failures)
    twice = charts.donut(rows, size=180, centre="turnos")
    check("the same numbers give the same bytes", twice, svg, failures)


def test_bars(failures):
    rows = [{"label": "AXV-AdrenalineX", "value": 100, "tone": "ok"},
            {"label": "<script>x</script>", "value": 50, "tone": "bad"}]
    svg = charts.bars(rows, width=400, label_width=120)
    check("one bar per row", svg.count("<rect"), 2, failures)
    check("the label is escaped, never markup", "<script>" in svg, False, failures)
    check("but it is still readable", "&lt;script&gt;" in svg, True, failures)
    check("the value travels with the bar", "100" in svg, True, failures)
    bigger = svg.index("100")
    check("the largest value is drawn, not invented", bigger > 0, True, failures)
    check("a zero-value list is an empty chart, with words",
          "nada que dibujar" in charts.bars([]), True, failures)
    zero = charts.bars([{"label": "sin medida", "value": 0, "show_zero": True, "tone": "idle"}])
    check("a declared zero is shown as a zero row", "0" in zero and "<rect" in zero, True, failures)


def test_columns(failures):
    rows = [{"label": "AXV", "parts": [{"value": 4196743, "tone": "accent"},
                                       {"value": 473940, "tone": "ok"}]},
            {"label": "Nexus", "parts": [{"value": 1000, "tone": "accent"},
                                         {"value": 0, "tone": "ok"}]}]
    svg = charts.columns(rows, width=600, height=220)
    check("two bars per group", svg.count("<rect"), 4, failures)
    check("each value has its tooltip", svg.count("<title>"), 4, failures)
    check("the category is under the axis", "AXV" in svg and "Nexus" in svg, True, failures)
    check("deterministic", charts.columns(rows, width=600, height=220), svg, failures)
    check("and the size is the one asked for", "0 0 600 220" in svg, True, failures)
    check("no data says so", "nada que dibujar" in charts.columns([]), True, failures)
    flat = charts.columns([{"label": "x", "parts": [{"value": 0}]}])
    check("all-zero columns are not an empty-looking chart", "nada que dibujar" in flat, True, failures)


def test_format_and_legend(failures):
    check("thousands are readable", charts.fmt(1363752), "1\u202f363\u202f752", failures)
    check("decimals use a comma", charts.fmt(0.9389249), "0,94", failures)
    check("a broken number is zero, not a crash", charts.fmt("nope"), "0", failures)
    legend = charts.legend([{"label": "verde", "value": 4, "tone": "ok"},
                            {"label": "cero", "value": 0, "tone": "bad"}])
    # El color de la leyenda se lee de la UNICA fuente (la paleta de `charts`): fijar aqui un hex
    # convertia cada cambio de paleta en un rojo falso, y el contrato real es "la leyenda lleva el
    # color de su serie", no "lleva este verde".
    check("the legend carries the colour", charts.TONE["ok"] in legend, True, failures)
    check("and skips what was not drawn", "cero" in legend, False, failures)


def run():
    failures = []
    test_empty(failures)
    test_donut(failures)
    test_bars(failures)
    test_columns(failures)
    test_format_and_legend(failures)
    return failures
