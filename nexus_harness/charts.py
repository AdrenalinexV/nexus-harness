"""Graficos como SVG escrito a mano: sin libreria, sin CDN, sin JavaScript.

Por que escribirlos y no traer una libreria: la pantalla de configuracion la sirve un motor congelado
que no descarga nada, y tres dibujos no justifican 200 KB de dependencia. Estas funciones son puras
--las mismas cifras dan los mismos bytes-- asi que se pueden probar sin navegador.

Tres reglas que se aplican solas:

* **Cero no es "sin datos".** Un proyecto sin ledger no tiene anillo: se dibuja un hueco punteado que
  lo dice. Un anillo vacio con un `0` limpio se leeria como "se midio y no habia nada".
* **Nada sin medir se dibuja.** Si no hay tarifa declarada, no hay grafico de dinero: se explica por
  que en palabras, en el mismo hueco.
* **El eje es la etiqueta.** Las barras se escalan al mayor valor del conjunto; no hay rejilla
  inventada ni porcentajes con tres decimales.
"""
import html

TONE = {"ok": "#22c55e", "bad": "#ef4444", "warn": "#f59e0b", "idle": "#64748b",
        "accent": "#3b82f6", "violet": "#8b5cf6"}
FONT = "system-ui,-apple-system,'Segoe UI',Roboto,sans-serif"
MUTED = "#8b97a6"
LINE = "#2e3844"


def esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def num(value):
    """Un numero utilizable o 0.0: una cifra que no se puede leer nunca tumba un panel."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def fmt(value):
    """Cifras que se leen: separador fino de millares, coma decimal, sin `0.9389249000000002`."""
    number = num(value)
    if abs(number - round(number)) < 1e-9:
        text = "{:,}".format(int(round(number)))
    else:
        text = "{:,.2f}".format(number)
    return text.replace(",", "\u202f").replace(".", ",")


def colour(tone):
    return TONE.get(str(tone or ""), TONE["idle"])


def empty(width=320, height=120, why="sin datos"):
    """Un grafico que no tiene nada que decir lo dice, en una caja del mismo tamano."""
    return ("<svg class='vchart' viewBox='0 0 %d %d' role='img' aria-label='%s' "
            "preserveAspectRatio='xMidYMid meet'>"
            "<rect x='0.5' y='0.5' width='%d' height='%d' rx='9' fill='none' stroke='%s' "
            "stroke-dasharray='4 4' opacity='.6'/>"
            "<text x='%d' y='%d' text-anchor='middle' font-family=\"%s\" font-size='12' "
            "fill='%s'>%s</text></svg>"
            % (width, height, esc(why), width - 1, height - 1, LINE, width // 2, height // 2 + 4,
               FONT, MUTED, esc(why)))


def legend(rows):
    """Las etiquetas del grafico, con su color: el mismo orden que las series."""
    chips = []
    for row in rows:
        if num(row.get("value")) <= 0:
            continue
        chips.append("<span class='vlegend'><i style='background:%s'></i>%s <b>%s</b></span>"
                     % (colour(row.get("tone")), esc(row.get("label")),
                        esc(fmt(row.get("value")))))
    return "<div class='vlegends'>%s</div>" % "".join(chips) if chips else ""


def donut(rows, size=180, thickness=26, centre="turnos", why="sin decisiones registradas"):
    """Un anillo partido por proporcion. La suma va en el centro; lo que vale cero no se dibuja."""
    rows = [row for row in rows if num(row.get("value")) > 0]
    total = sum(num(row.get("value")) for row in rows)
    if not rows or total <= 0:
        return empty(size, size, why)
    radius = (size - thickness) / 2.0
    circumference = 2 * 3.141592653589793 * radius
    middle = size / 2.0
    arcs, offset = [], 0.0
    for row in rows:
        share = num(row.get("value")) / total
        length = share * circumference
        arcs.append("<circle cx='%s' cy='%s' r='%s' fill='none' stroke='%s' stroke-width='%s' "
                    "stroke-dasharray='%s %s' stroke-dashoffset='%s' transform='rotate(-90 %s %s)'/>"
                    % (_f(middle), _f(middle), _f(radius), colour(row.get("tone")), _f(thickness),
                       _f(max(length - 2.0, 0.4)), _f(circumference), _f(-offset),
                       _f(middle), _f(middle)))
        offset += length
    return ("<svg class='vchart' viewBox='0 0 %d %d' role='img' aria-label='%s'>"
            "<circle cx='%s' cy='%s' r='%s' fill='none' stroke='%s' stroke-width='%s' opacity='.45'/>"
            "%s<text x='%s' y='%s' text-anchor='middle' font-family=\"%s\" font-size='22' "
            "font-weight='700' fill='#e7eef6'>%s</text>"
            "<text x='%s' y='%s' text-anchor='middle' font-family=\"%s\" font-size='11' "
            "fill='%s'>%s</text></svg>"
            % (size, size, esc(why if not rows else centre), _f(middle), _f(middle), _f(radius),
               LINE, _f(thickness), "".join(arcs), _f(middle), _f(middle - 2), FONT, esc(fmt(total)),
               _f(middle), _f(middle + 15), FONT, MUTED, esc(centre)))


def bars(rows, width=580, row_height=28, unit="", label_width=176, why="nada que dibujar"):
    """Barras horizontales: la etiqueta es el eje, el numero va pegado al final de la barra."""
    rows = [row for row in rows if num(row.get("value")) > 0 or row.get("show_zero")]
    if not rows:
        return empty(width, row_height * 2, why)
    top = max(num(row.get("value")) for row in rows) or 1.0
    height = row_height * len(rows) + 12
    room = max(width - label_width - 96, 40)
    parts = []
    for index, row in enumerate(rows):
        value = num(row.get("value"))
        y = 8 + index * row_height
        span = max(room * value / top, 2.5 if value > 0 else 0)
        parts.append("<text x='0' y='%s' font-family=\"%s\" font-size='12' fill='%s'>%s</text>"
                     % (_f(y + row_height / 2 + 4), FONT, MUTED, esc(_clip(row.get("label"), 26))))
        parts.append("<rect x='%s' y='%s' width='%s' height='%s' rx='4' fill='%s'/>"
                     % (label_width, _f(y + 5), _f(max(span, 0)), row_height - 12,
                        colour(row.get("tone"))))
        parts.append("<text x='%s' y='%s' font-family=\"%s\" font-size='11.5' fill='#e7eef6'>%s%s</text>"
                     % (_f(label_width + max(span, 0) + 6), _f(y + row_height / 2 + 4), FONT,
                        esc(fmt(value)), esc(unit)))
    return ("<svg class='vchart' viewBox='0 0 %d %d' role='img' aria-label='%s'>%s</svg>"
            % (width, height, esc(why), "".join(parts)))


def columns(rows, width=580, height=214, unit="", why="nada que dibujar"):
    """Columnas agrupadas: cada categoria con sus series al lado, para comparar sin superponer."""
    if not rows:
        return empty(width, height, why)
    series = max(len(row.get("parts") or []) for row in rows) or 1
    top = max([num(part.get("value")) for row in rows for part in row.get("parts") or []] or [0.0])
    if top <= 0:
        return empty(width, height, why)
    plot_h = height - 46
    group = (width - 24) / float(len(rows))
    bar_w = max(min(group / (series + 0.8), 46.0), 6.0)
    parts = []
    for index, row in enumerate(rows):
        x0 = 12 + index * group
        for slot, one in enumerate(row.get("parts") or []):
            value = num(one.get("value"))
            bar_h = max(plot_h * value / top, 2.0 if value > 0 else 0.0)
            x = x0 + (group - bar_w * series) / 2.0 + slot * bar_w
            parts.append("<rect x='%s' y='%s' width='%s' height='%s' rx='3' fill='%s'>"
                         "<title>%s: %s%s</title></rect>"
                         % (_f(x), _f(8 + plot_h - bar_h), _f(max(bar_w - 3, 3)), _f(bar_h),
                            colour(one.get("tone")), esc(row.get("label")), esc(fmt(value)),
                            esc(unit)))
            if value > 0 and len(rows) <= 7:
                parts.append("<text x='%s' y='%s' text-anchor='middle' font-family=\"%s\" "
                             "font-size='10.5' fill='%s'>%s</text>"
                             % (_f(x + bar_w / 2), _f(4 + plot_h - bar_h), FONT, MUTED,
                                esc(fmt(value))))
        parts.append("<text x='%s' y='%s' text-anchor='middle' font-family=\"%s\" font-size='11' "
                     "fill='%s'>%s</text>"
                     % (_f(x0 + group / 2), _f(height - 14), FONT, MUTED,
                        esc(_clip(row.get("label"), 18))))
    line = ("<line x1='12' y1='%s' x2='%s' y2='%s' stroke='%s' stroke-width='1'/>"
            % (_f(8 + plot_h), width - 12, _f(8 + plot_h), LINE))
    return ("<svg class='vchart' viewBox='0 0 %d %d' role='img' aria-label='%s'>%s%s</svg>"
            % (width, height, esc(why), line, "".join(parts)))


def _clip(text, limit):
    text = str(text or "")
    return text if len(text) <= limit else text[:limit - 1] + "\u2026"


def _f(value):
    """Un decimal y sin `-0.0`: el SVG no necesita precision de coma flotante en el marcado."""
    return ("%.1f" % float(value)).rstrip("0").rstrip(".") or "0"
