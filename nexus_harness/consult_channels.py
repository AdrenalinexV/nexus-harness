"""Los canales de la consulta: preguntar por donde el operador ya recibe avisos, y ESCUCHAR la respuesta.

Tres decisiones que no son cosmeticas:

* **Telegram se lee de verdad.** `getUpdates` con un `offset` persistido en disco: sin offset, cada
  tick vuelve a leer las mismas respuestas y contesta preguntas que ya estaban contestadas (inofensivo
  pero ruidoso), o peor, se salta la que llego en medio. El offset es estado, no un detalle.
* **Discord se lee solo con bot.** Un webhook escribe; no escucha. Se dice en el canal (`readable:
  False`) en vez de ofrecer una pregunta que nadie puede contestar por ahi.
* **Cualquier otro puente contesta por HTTP.** WhatsApp (Baileys/Cloud API), n8n o un bot propio
  mandan `POST /api/consult/answer`; ese camino no necesita ni SDK ni gateway, y es el mismo registro
  que usa el movil.
"""
import json
import urllib.parse
import urllib.request
from pathlib import Path

from . import consult
from .notify import _payload, _post, _secret

TIMEOUT = 10
CURSORS = Path(".nexus") / "harness" / "channel-cursors.json"


def _telegram_channel(declared, secrets):
    telegram = declared.get("telegram") or {}
    token = _secret(telegram.get("token"), secrets)
    chat = _secret(telegram.get("chat_id"), secrets)
    if not (token and chat):
        return None
    return {"kind": "telegram", "token": token, "chat_id": str(chat), "readable": True,
            "url": "https://api.telegram.org/bot%s/sendMessage" % token}


def _discord_channel(declared, secrets):
    webhook = _secret(declared.get("discord_webhook"), secrets)
    bot = _secret(declared.get("discord_bot_token") or declared.get("discord_token"), secrets)
    channel = _secret(declared.get("discord_channel_id"), secrets)
    if webhook:
        return {"kind": "discord", "url": webhook, "bot_token": bot or "",
                "channel_id": str(channel or ""), "readable": bool(bot and channel)}
    if bot and channel:
        return {"kind": "discord", "url": "", "bot_token": bot, "channel_id": str(channel),
                "readable": True}
    return None


def channels(config):
    """Los canales declarados, con lo que cada uno puede hacer. Un canal de solo escritura se declara."""
    declared = getattr(config, "notify", None) or {}
    secrets = getattr(config, "secrets", None) or {}
    if not isinstance(declared, dict):
        return []
    found = []
    for build in (_telegram_channel, _discord_channel):
        channel = build(declared, secrets)
        if channel:
            found.append(channel)
    topic = _secret(declared.get("ntfy"), secrets)
    if topic:
        found.append({"kind": "ntfy", "url": "https://ntfy.sh/%s" % str(topic).lstrip("/"),
                      "readable": False})
    return found


def readable(channels_list):
    return [channel for channel in channels_list or [] if channel.get("readable")]


def announce(channels_list, text, post=None):
    """Manda la pregunta por todos los canales que escriben. Devuelve una fila por canal."""
    sender = post or _post
    rows = []
    for channel in channels_list or []:
        if not channel.get("url"):
            rows.append({"ok": False, "channel": channel.get("kind"), "detail": "sin url de envio"})
            continue
        payload = _payload(channel, str(text or ""))
        content_type = ("text/plain; charset=utf-8" if channel.get("kind") == "ntfy"
                        else "application/json")
        ok, detail = sender(channel.get("url"), payload, content_type)
        rows.append({"ok": bool(ok), "channel": channel.get("kind"), "detail": detail})
    return rows


def _get_json(url, headers=None, get=None):
    """GET con cabeceras y timeout. Devuelve `(ok, cuerpo_o_error)`; nunca lanza."""
    if get:
        return get(url, headers or {})
    request = urllib.request.Request(url, headers=dict(headers or {},
                                                       **{"User-Agent": "Nexus-Harness/1.0"}))
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return True, json.loads(response.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 -- un canal caido es una observacion, no una excepcion
        return False, "%s: %s" % (type(exc).__name__, str(exc)[:160])


def load_cursors(root):
    path = Path(root) / CURSORS
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cursors(root, cursors):
    path = Path(root) / CURSORS
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cursors, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _telegram_messages(channel, cursor, get):
    url = ("https://api.telegram.org/bot%s/getUpdates?timeout=0&limit=20%s"
           % (channel.get("token"), ("&offset=%s" % int(cursor)) if str(cursor).isdigit() else ""))
    ok, body = _get_json(url, {}, get)
    if not ok or not isinstance(body, dict) or not body.get("ok"):
        return [], cursor, str(body)[:120]
    texts, last = [], cursor
    for update in body.get("result") or []:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            last = max(int(last or 0), update_id + 1)
        message = update.get("message") or update.get("edited_message") or {}
        chat = (message.get("chat") or {}).get("id")
        text = message.get("text")
        if text and str(chat) == str(channel.get("chat_id")):
            texts.append(text)
    return texts, last, ""


def _discord_messages(channel, cursor, get):
    query = "?limit=20" + (("&after=%s" % urllib.parse.quote(str(cursor))) if cursor else "")
    url = ("https://discord.com/api/v10/channels/%s/messages%s"
           % (channel.get("channel_id"), query))
    ok, body = _get_json(url, {"Authorization": "Bot %s" % channel.get("bot_token")}, get)
    if not ok or not isinstance(body, list):
        return [], cursor, str(body)[:120]
    texts, last = [], cursor
    for message in body:
        message_id = message.get("id")
        if isinstance(message_id, str) and message_id.isdigit():
            last = max(int(last or 0), int(message_id))
        content = message.get("content")
        if content and not (message.get("author") or {}).get("bot"):
            texts.append(content)
    return texts, last, ""


READERS = {"telegram": _telegram_messages, "discord": _discord_messages}


def poll(root, channels_list, cursors=None, get=None):
    """Lo que el operador ha contestado desde la ultima vez, ya casado con su pregunta.

    Devuelve `[{id, text, source}]`. Un canal ilegible o caido se salta y se informa en `errors`, que
    el llamante puede ignorar: la consulta tiene su propio plazo.
    """
    seen = dict(cursors if cursors is not None else load_cursors(root))
    open_ids = [row["id"] for row in consult.pending(root)]
    found, errors = [], []
    for channel in readable(channels_list):
        kind = channel.get("kind")
        reader = READERS.get(kind)
        if not reader:
            continue
        texts, cursor, error = reader(channel, seen.get(kind), get)
        if error:
            errors.append("%s: %s" % (kind, error))
        if cursor != seen.get(kind):
            seen[kind] = cursor
        for text in texts:
            qid, body = consult.parse_reply(text, open_ids)
            if qid and body:
                found.append({"id": qid, "text": body, "source": kind})
    if cursors is None:
        save_cursors(root, seen)
    return found


def broadcast(root, question, channels_list=None, post=None):
    """Anuncia una pregunta ya registrada. Sin canales legibles devuelve `delivered: False`."""
    targets = channels_list or []
    text = consult.describe(question)
    rows = announce(targets, text, post)
    return {"ok": any(row.get("ok") for row in rows), "rows": rows,
            "readable": bool(readable(targets))}


def default_on_silence(question):
    """Lo que se hace si nadie contesta: el defecto DECLARADO, y `parar` cuando no hay ninguno."""
    declared = str((question or {}).get("default") or "").strip()
    return declared or "parar"


def ask_operator(root, config, text, options=(), default="parar", project="",
                 deadline_s=consult.DEFAULT_DEADLINE, max_polls=None, post=None, get=None,
                 sleep=None, clock=None, should_stop=None):
    """Preguntar y esperar, en una llamada. Es lo que usan el daemon, el CLI y la herramienta.

    Cuatro finales posibles, y todos se nombran:

    * `answered`  -- el operador contesto por un canal legible.
    * `expired`   -- nadie contesto y se aplica el defecto declarado.
    * `no_channel` -- no hay ni un canal configurado: el defecto, al instante, sin esperar.
    * `sent_unreadable` -- se mando, pero nadie puede contestar por ahi (webhook sin bot). La pregunta
      queda abierta para la cabina y el bucle sigue con el defecto: no se finge que hubo respuesta.
    """
    question = consult.ask(root, text, options, default, project, deadline_s,
                           secrets=(getattr(config, "secrets", None) or {}).values())
    if not question.get("ok", True):
        return {"state": "invalid", "answer": default_on_silence({"default": default}),
                "source": "none", "reason": question.get("reason")}
    targets = channels(config)
    if not targets:
        consult.answer(root, question["id"], default_on_silence(question), "no_channel")
        return {"state": "no_channel", "answer": default_on_silence(question), "source": "no_channel",
                "id": question["id"]}
    delivery = broadcast(root, question, targets, post)
    if not delivery.get("readable"):
        return {"state": "sent_unreadable", "answer": default_on_silence(question),
                "source": "none", "id": question["id"], "delivered": delivery.get("ok")}
    def poller():
        # `None` hace que `poll` lea y PERSISTA los cursores: un diccionario compartido se copiaria en
        # cada lectura y el offset de Telegram volveria al principio en cada tick.
        return poll(root, targets, None, get)

    outcome = consult.wait(root, question["id"], poll=poller, sleep=sleep, clock=clock,
                           max_polls=max_polls or max(1, int(deadline_s // 2) + 5),
                           should_stop=should_stop)
    return {"state": outcome.get("state"), "answer": outcome.get("answer"),
            "source": outcome.get("source"), "id": question["id"],
            "delivered": bool(delivery.get("ok"))}



