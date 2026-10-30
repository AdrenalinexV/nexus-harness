"""§ Acerca de: qué motor es este, medido — no supuesto.

Un «Acerca de» que copia la versión en el HTML es una mentira que envejece sola: cambia el binario y
la página sigue diciendo lo mismo. Aquí no hay ni una cifra escrita a mano: todas salen de
`cockpit.state()` (motor en marcha) y de `/api/health` (el contrato con el frontend), y el botón
`Comprobar` vuelve a pedir la salud del motor y pinta su respuesta tal cual.

El botón es un `<form>` de verdad, no un `fetch`: funciona con el script bloqueado, y el panel dueño de
la sección (`settings_about.action`) usa la MISMA función que sirve la ruta `/api/health` — una
implementación, dos consumidores.
"""
from . import settings_kit as kit

TITLE = "Acerca de"


def health(cockpit):
    """La respuesta de `/api/health`, por su propia función de ruta. `{}` si el motor no contesta."""
    from . import api
    answer = api.get(cockpit, "/api/health")
    return dict(answer[1]) if answer and isinstance(answer[1], dict) else {}


def _duration(seconds):
    """Los segundos de vida del motor, en horas y minutos. Un dato que no es un número se declara `?`."""
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "?"
    if total < 0:
        return "?"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "%d h %02d min" % (hours, minutes)
    if minutes:
        return "%d min %02d s" % (minutes, secs)
    return "%d s" % secs


def _table(rows):
    """Dos columnas: qué es y cuánto vale. Tabla de manual, sin tarjeta ni relleno."""
    body = "".join('<tr><td>%s</td><td class="num"><code>%s</code></td></tr>' % (kit.esc(label), kit.esc(value))
                   for label, value in rows)
    return '<table class="stable"><tbody>%s</tbody></table>' % body


def _facts(cockpit, payload):
    """Lo que el panel sabe del motor, cada renglón con su procedencia."""
    state = cockpit.state() if cockpit is not None else {}
    config = state.get("config") or {}
    host = "%s:%s" % (config.get("host") or "?", config.get("port") or "?")
    rows = [
        ("motor", payload.get("version") or state.get("version") or "?"),
        ("contrato de la API", payload.get("api") or "?"),
        ("escucha en", host),
        ("raíz de trabajo", config.get("root") or "?"),
        ("ajustes desde", config.get("source") or "defaults"),
        ("encendido desde", _duration(payload.get("uptime"))),
    ]
    return rows


def _result(payload):
    """La respuesta de `/api/health`, con su palabra de veredicto: nunca un color sin su palabra.

    «Sin respuesta» es tan informativo como «responde»: un panel de salud que solo sabe pintar verde
    cuando todo va bien es un adorno.
    """
    tone = "ok" if payload.get("ok") else ("bad" if payload else "off")
    word = "responde" if payload.get("ok") else ("sin respuesta" if not payload else "contestó que no")
    rows = [("ok", payload.get("ok")), ("seq", payload.get("seq")), ("version", payload.get("version")),
            ("api", payload.get("api")), ("uptime", _duration(payload.get("uptime")))]
    return ('<p><span class="chip %s">%s</span> <span class="dim">respuesta de '
            '<code>/api/health</code></span></p>%s' % (tone, kit.esc(word), _table(rows)))


def page(cockpit=None):
    """La sección propia: las cifras del motor y el botón que las vuelve a pedir.

    No hay estado guardado: cada vez que se pinta esta sección se le pregunta al motor, así que el
    `uptime` que se lee es el de ahora y no el de la última visita.
    """
    payload = health(cockpit) if cockpit is not None else {}
    form = ('<form class="sform" method="post" action="/api/settings/do">'
            + kit.hidden("section", "about")
            + '<div class="sactions"><button class="primary" name="what" value="about_probe">'
              'Comprobar</button><span class="dim">pide <code>/api/health</code> al motor que sirve '
              'esta pantalla y deja su resultado en la nota de arriba</span></div></form>')
    body = ('<p class="dim">El motor de este documento no se describe de memoria: la versión, el '
            'contrato de la API, dónde escucha y cuánto lleva encendido se leen en vivo. Si una cifra '
            'no está, se dice <code>?</code> en vez de inventarla.</p>'
            '<h3 class="ssub">El motor</h3>%s'
            '<h3 class="ssub">Comprobación</h3>%s%s'
            % (_table(_facts(cockpit, payload)), form, _result(payload)))
    return (TITLE, "Qué está sirviendo esta pantalla, medido ahora mismo.", body)


def action(cockpit, body):
    """El botón `Comprobar`. Devuelve `(nota, ok, seccion)` como el resto de la pantalla."""
    what = str(body.get("what") or "")
    if what != "about_probe":
        return ("acción desconocida: %s" % what, False, "about")
    payload = health(cockpit)
    ok = bool(payload.get("ok"))
    note = "salud: %s" % ("responde" if ok else "sin respuesta")
    if payload:
        note += " · contrato v%s · secuencia %s · encendido %s" % (
            payload.get("api"), payload.get("seq"), _duration(payload.get("uptime")))
    return (note, ok, "about")
