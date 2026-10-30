"""Las piezas que comparten las pantallas de configuracion: campos, formularios y notas.

Un formulario de esta pantalla es HTML de verdad (`<form method=post>`), no un `fetch` con JSON, por
dos razones que ya estan pagadas en este repositorio: funciona con el script bloqueado, y guardar
responde un 303 de vuelta al panel, asi que recargar no reenvia nada. El JavaScript que hay encima
(`settings.js`) solo hace dos cosas: Ctrl+K y filtrar el arbol.
"""
from html import escape

from .config import HarnessConfig

# Los dos campos que se escriben en PORCENTAJE y se guardan en FRACCION. El motor los consume en
# fraccion (`session_relay.py`, `triad_loop.py`), asi que la conversion vive aqui y en ningun otro
# sitio: pintar uno y guardar el otro es como se llega a un relevo al 70,0 (o sea, nunca) sin que
# nadie lo note, porque la nota de guardado sigue saliendo en verde.
PERCENT_FIELDS = ("relay_threshold", "compact_threshold")


def esc(value):
    return escape(str(value if value is not None else ""))


def option(value, label, current):
    mark = " selected" if str(value) == str(current) else ""
    return '<option value="%s"%s>%s</option>' % (esc(value), mark, esc(label))


def field(label, control, hint=""):
    return ('<label class="sfield"><span class="slabel">%s</span>%s%s</label>'
            % (esc(label), control, '<span class="shint">%s</span>' % esc(hint) if hint else ""))


def empty(what, next_step):
    """Un panel sin datos dice QUE HACER, no solo que no hay nada.

    Un «ninguno.» a secas se lee como una pantalla rota. El estado vacio es la primera pantalla de un
    operador nuevo y la ultima que ve cuando algo falla, asi que va con la accion siguiente en el
    mismo parrafo: `what` describe el hueco (sin punto final) y `next_step` empieza por un verbo y
    nombra el boton exacto que lo llena.
    """
    return ('<p class="sempty"><span class="swhat">%s</span> '
            '<span class="snext">%s</span></p>' % (esc(what), esc(next_step)))


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


def percent_to_fraction(name, raw):
    """Lo que el formulario manda en % (`70`) a la fraccion que el motor guarda (`0.70`).

    Acepta las dos formas porque un operador puede escribir `70` o `0.7`; lo que NO acepta es un
    valor fuera del presupuesto: 150 % no es un umbral, es un error, y un error se dice en la nota
    en vez de escribirse en el fichero. Devuelve `(fraccion, problema)`.
    """
    try:
        value = float(str(raw).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None, "%s: %r no es un número" % (name, raw)
    if value <= 0:
        return None, "%s: tiene que ser mayor que 0" % name
    fraction = value / 100.0 if value > 1.0 else value
    if fraction > 1.0:
        return None, "%s: %s %% se pasa del presupuesto (máximo 100 %%)" % (name, value)
    return round(fraction, 4), ""


def show_percent(value):
    """La fraccion guardada, como porcentaje para el formulario. Fuera de rango se dice, no se pinta.

    El `7000 %` de la cabina vieja era esto: un fichero que ya tenia `70.0` multiplicado otra vez por
    100. Un valor que no es una fraccion no se convierte: se declara `?` y quien lo pinta lo explica.
    """
    try:
        fraction = float(value)
    except (TypeError, ValueError):
        return "?"
    if not 0 < fraction <= 1.0:
        return "?"
    return str(int(round(fraction * 100)))


def note_from(query):
    """La nota que deja una accion: `?note=guardado&bad=1` viene de un 303, no de una sesion."""
    text = (query.get("note") or [""])[0]
    if not text:
        return ""
    tone = "bad" if (query.get("bad") or [""])[0] else "ok"
    return '<p class="snote %s">%s</p>' % (tone, esc(text))


def context_fields(config, window=0, role=""):
    """Los numeros que gobiernan un turno: presupuesto, relevo y compactacion.

    Se usan en dos paneles (Modelos y Memoria) a proposito: son los MISMOS campos del mismo fichero,
    asi que dos puertas dan a la misma habitacion y no hay dos verdades. Un ajuste duplicado en dos
    sitios solo es un problema cuando los dos sitios guardan en sitios distintos.

    `window` es la ventana que el motor declaro en vivo. Si hay dato, se dice en el propio campo
    cuanto se va a usar de verdad: prometer 60.000 tokens con un motor de 12.544 es como se llega a
    un 400 que el operador no puede explicar.
    """
    from .llm.context_window import fit
    used = fit(config.budget_limit, window, config.max_tokens)
    budget_hint = "el presupuesto de la conversación; al acercarse, el motor compacta y luego releva"
    if int(window or 0) > 0:
        budget_hint = "%s · el motor%s declara %s tokens: se usará %s" % (
            budget_hint, (" de " + role) if role else "",
            "{:,}".format(int(window)).replace(",", "."),
            "{:,}".format(int(used)).replace(",", "."))
    rows = [
        field("Límite de contexto (tokens)", *number_input(
            "budget_limit", config.budget_limit, budget_hint)),
        field("Relevo automático (%)", *number_input(
            "relay_threshold", show_percent(config.relay_threshold),
            "a qué porcentaje del presupuesto se pasa el testigo a una sesión nueva")),
        field("Compactación (%)", *number_input(
            "compact_threshold", show_percent(config.compact_threshold),
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
