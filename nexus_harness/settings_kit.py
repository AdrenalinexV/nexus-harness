"""Las piezas que comparten las pantallas de configuracion: campos, formularios y notas.

Un formulario de esta pantalla es HTML de verdad (`<form method=post>`), no un `fetch` con JSON, por
dos razones que ya estan pagadas en este repositorio: funciona con el script bloqueado, y guardar
responde un 303 de vuelta al panel, asi que recargar no reenvia nada. El JavaScript que hay encima
(`settings.js`) solo hace dos cosas: Ctrl+K y filtrar el arbol.
"""
from html import escape

from .config import HarnessConfig


def esc(value):
    return escape(str(value if value is not None else ""))


def option(value, label, current):
    mark = " selected" if str(value) == str(current) else ""
    return '<option value="%s"%s>%s</option>' % (esc(value), mark, esc(label))


def field(label, control, hint=""):
    return ('<label class="sfield"><span class="slabel">%s</span>%s%s</label>'
            % (esc(label), control, '<span class="shint">%s</span>' % esc(hint) if hint else ""))


def text_input(name, value, kind="text", hint=""):
    control = '<input type="%s" name="%s" value="%s">' % (esc(kind), esc(name), esc(value if value is not None else ""))
    return control, hint


def number_input(name, value, hint="", step="1"):
    control = ('<input type="number" step="%s" name="%s" value="%s">'
               % (esc(step), esc(name), esc(value if value is not None else "")))
    return control, hint


def select_input(name, options, current, hint=""):
    body = "".join(option(value, label, current) for value, label in options)
    return '<select name="%s">%s</select>' % (esc(name), body), hint


def hidden(name, value):
    return '<input type="hidden" name="%s" value="%s">' % (esc(name), esc(value))


def form(action, section, body, submit="Aplicar", hidden_extra=""):
    """Un formulario del panel. `section` viaja siempre: es lo que dice quien lo mando."""
    return ('<form class="sform" method="post" action="%s">%s%s%s'
            '<div class="sactions"><button class="primary">%s</button></div></form>'
            % (esc(action), hidden("section", section), hidden_extra, body, esc(submit)))


def note_from(query):
    """La nota que deja una accion: `?note=guardado&bad=1` viene de un 303, no de una sesion."""
    text = (query.get("note") or [""])[0]
    if not text:
        return ""
    tone = "bad" if (query.get("bad") or [""])[0] else "ok"
    return '<p class="snote %s">%s</p>' % (tone, esc(text))


def context_fields(config):
    """Los numeros que gobiernan un turno: presupuesto, relevo y compactacion.

    Se usan en dos paneles (Modelos y Memoria) a proposito: son los MISMOS campos del mismo fichero,
    asi que dos puertas dan a la misma habitacion y no hay dos verdades. Un ajuste duplicado en dos
    sitios solo es un problema cuando los dos sitios guardan en sitios distintos.
    """
    rows = [
        field("Límite de contexto (tokens)", *number_input(
            "budget_limit", config.budget_limit,
            "el presupuesto de la conversación; al acercarse, el motor compacta y luego releva")),
        field("Relevo automático (%)", *number_input(
            "relay_threshold", round(float(config.relay_threshold) * 100),
            "a qué porcentaje del presupuesto se pasa el testigo a una sesión nueva")),
        field("Compactación (%)", *number_input(
            "compact_threshold", round(float(config.compact_threshold) * 100),
            "antes del relevo, el hilo se comprime en su sitio")),
        field("Temperatura", *number_input("temperature", config.temperature, step="0.05",
                                          hint="0.2 = obedece; 0.7 = improvisa")),
        field("Máximo de tokens por respuesta", *number_input("max_tokens", config.max_tokens)),
        field("Techo de coste por turno (USD)", *number_input(
            "cost_limit", config.cost_limit, step="0.01",
            hint="0 = sin tope declarado; con un modelo de nube esto es lo único que corta")),
    ]
    return "".join(rows)


def current_config():
    return HarnessConfig.load()
