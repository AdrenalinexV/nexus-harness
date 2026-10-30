"""Panel de autonomía: lo que el bucle decidió solo, lo que pidió decidir y quién puede contestar.

Tres cosas que el operador necesita ver en una pantalla y que hasta ahora solo estaban en ficheros:

* **Qué canales escuchan.** Un webhook de Discord escribe pero no lee; decirlo aquí evita la tarde
  perdida esperando una respuesta que nunca iba a llegar.
* **Qué preguntas están abiertas**, con sus opciones como botones y un campo libre: contestar no puede
  exigir recordar un id.
* **Qué se decidió y con qué origen** (`telegram`, `api`, `default`), porque una autonomía sin rastro
  de sus decisiones es indistinguible de una caja negra.
"""
from . import consult, consult_channels, settings_kit as kit

TITLE = "Autonomía & Preguntas"


def _chip(on, text):
    return '<span class="chip %s">%s</span>' % ("ok" if on else "warn", kit.esc(text))


def _channels_ready(config):
    found = consult_channels.channels(config)
    rows = "".join("<li><strong>%s</strong> %s %s</li>"
                   % (kit.esc(channel.get("kind")),
                      _chip(bool(channel.get("url")), "escribe" if channel.get("url")
                            else "no escribe"),
                      _chip(bool(channel.get("readable")), "escucha" if channel.get("readable")
                            else "solo recibe"))
                   for channel in found)
    if not found:
        return ('<p><span class="chip warn">sin canales</span> <span class="dim">declara '
                '<code>notify</code> en <code>~/.nexus/harness.json</code> para que la autonomía pueda '
                'preguntar en vez de pararse.</span></p>')
    return "<ul class=\"plain\">%s</ul>" % rows


def _question_form(row):
    options = "".join(
        '<button class="primary" name="answer" value="%s">%s</button>' % (kit.esc(value), kit.esc(value))
        for value in (row.get("options") or []))
    return ('<div class="card qitem"><p class="qtext">%s</p>'
            '<p class="dim">%s · plazo %s min · si no hay respuesta: %s</p>'
            '<form class="sform" method="post" action="/api/settings/do">%s%s'
            '<div class="sactions">%s<input name="answer" placeholder="o escribe la respuesta" '
            'class="wide"><button class="ghost" name="what" value="consult_answer">Enviar</button>'
            '</div></form></div>'
            % (kit.esc(row.get("text") or ""),
               kit.esc("%s · %s" % (row.get("project") or "sin proyecto", row.get("id"))),
               int(row.get("deadline_s") or 0) // 60, kit.esc(row.get("default") or "parar"),
               kit.hidden("section", "autonomia"),
               kit.hidden("id", row.get("id") or ""), options))


def _recent(rows):
    if not rows:
        return kit.empty("Todavía no se ha contestado ninguna pregunta",
                         "las decisiones aparecerán aquí en cuanto la autonomía pregunte algo y lo "
                         "respondas desde el móvil o desde aquí arriba.")
    body = "".join("<li><strong>%s</strong> <span class=\"dim\">%s · %s · %s</span></li>"
                   % (kit.esc((row.get("text") or "")[:80]), kit.esc(row.get("answer") or "?"),
                      kit.esc(row.get("source") or "?"), kit.esc(row.get("answered_at") or ""))
                   for row in rows)
    return "<ul class=\"plain\">%s</ul>" % body


def block(cockpit, limit=6):
    """El cuerpo del panel. Sin cockpit no hay preguntas que enseñar: el panel lo dice, no finge."""
    config = getattr(cockpit, "config", None)
    root = getattr(cockpit, "root", None)
    if config is None or root is None:
        return kit.empty("Sin motor: no hay preguntas que mostrar",
                         "arranca el motor y recarga, o comprueba su salud en «Acerca de».")
    enabled = bool(getattr(config, "consult_enabled", True))
    open_rows = consult.pending(root)[:limit]
    recent = [row for row in consult.questions(root).values() if row.get("state") != "pending"]
    recent.sort(key=lambda row: str(row.get("answered_at") or row.get("at") or ""), reverse=True)
    state = _chip(enabled, "pregunta activa" if enabled else "apagada: para sin preguntar")
    body = ('<p>%s <span class="dim">plazo %s min · defecto si nadie contesta: parar</span></p>'
            '<h4 class="ssub">Quién puede contestar</h4>%s'
            % (state, int(getattr(config, "ask_deadline", 900) or 900) // 60,
               _channels_ready(config)))
    body += ('<h4 class="ssub">Preguntas abiertas (%d)</h4>%s'
             % (len(open_rows), "".join(_question_form(row) for row in open_rows)
                if open_rows else kit.empty(
                    "Ninguna pregunta abierta: el bucle no está esperando nada tuyo",
                    "cuando la autonomía necesite una decisión aparecerá aquí con su plazo y su "
                    "defecto; hasta entonces no hay nada que contestar.")))
    body += '<h4 class="ssub">Últimas decisiones</h4>%s' % _recent(recent[:limit])
    body += ('<form class="sform" method="post" action="/api/settings">%s'
             '<label class="check"><input type="checkbox" name="consult_enabled" value="on"%s> '
             'Permitir que la autonomía pregunte antes de pararse</label>'
             '<div class="sgrid">%s</div><div class="sactions">'
             '<button class="primary" name="what" value="save">Guardar</button></div></form>'
             % (kit.hidden("section", "autonomia"), " checked" if enabled else "",
                kit.field("Plazo por pregunta (segundos)",
                          kit.text_input("ask_deadline", getattr(config, "ask_deadline", 900))[0])))
    return body


def action(cockpit, body):
    """Contesta una pregunta desde la cabina. Devuelve `(nota, ok, seccion)`."""
    qid = str(body.get("id") or "").strip()
    answer = str(body.get("answer") or "").strip()
    if not qid:
        return ("falta la pregunta a contestar", False, "autonomia")
    result = consult.answer(cockpit.root, qid, answer, "cabina")
    if not result.get("ok"):
        return (str(result.get("reason") or "no se pudo contestar"), False, "autonomia")
    return ("contestada %s: %s%s" % (qid, result.get("answer") or "",
                                     " (ya estaba)" if result.get("already") else ""), True,
            "autonomia")


def save(cockpit, body):
    """Guarda el interruptor y el plazo. Un formulario no escribe nada que no este en la lista."""
    from . import onboarding
    changes = {"consult_enabled": "on" if body.get("consult_enabled") else "off",
               "ask_deadline": str(body.get("ask_deadline") or 900)}
    saved, problems = onboarding.save_settings(changes)
    if saved:
        cockpit.reload_config()
        return ("autonomía: %s · plazo %s s"
                % ("pregunta" if saved.get("consult_enabled") else "para sin preguntar",
                   saved.get("ask_deadline")), True)
    return ("no se guardó: %s" % ("; ".join(problems) or "sin cambios"), False)

