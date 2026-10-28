"""Avisos: que el trabajo autonomo se pueda seguir desde el movil sin abrir la cabina.

Un daemon que trabaja de noche y no dice nada es indistinguible de un daemon roto. Este modulo manda
un resumen corto a los canales que el operador declare (Discord por webhook, Telegram por bot, ntfy por
topic), con la misma regla que el resto del arnes: **sin dependencias, sin SDK y sin inventar**.

* Los destinos salen de `notify` en `~/.nexus/harness.json`; un valor que empieza por `$` se resuelve
  de la boveda (una URL de webhook es un secreto y no se escribe en un documento).
* Un canal que falla **no tumba el turno**: se devuelve `{ok: False, reason}` y se sigue. El trabajo ya
  esta hecho; el aviso es una cortesia.
* El texto se recorta por canal (Discord 2.000 caracteres, Telegram 4.096) para que no se pierda el
  final del mensaje en un 400.
"""
import json
import os
import urllib.request

TIMEOUT = 6
DISCORD_LIMIT = 1900
TELEGRAM_LIMIT = 4000


def _secret(value, secrets=None):
    """`$NAME` -> el secreto de la boveda o del entorno. Un valor literal se respeta."""
    text = str(value or "")
    if not text.startswith("$"):
        return text
    name = text[1:]
    if secrets and secrets.get(name):
        return str(secrets[name])
    return str(os.environ.get(name) or "")


def targets(config):
    """Los canales declarados, ya resueltos. Vacio es un resultado valido: no hay avisos."""
    declared = getattr(config, "notify", None) or {}
    if not isinstance(declared, dict):
        return []
    secrets = getattr(config, "secrets", {}) or {}
    found = []
    discord = _secret(declared.get("discord_webhook"), secrets)
    if discord:
        found.append({"kind": "discord", "url": discord})
    telegram = declared.get("telegram") or {}
    token = _secret(telegram.get("token"), secrets)
    chat = _secret(telegram.get("chat_id"), secrets)
    if token and chat:
        found.append({"kind": "telegram", "url": "https://api.telegram.org/bot%s/sendMessage" % token,
                      "chat_id": chat})
    topic = _secret(declared.get("ntfy"), secrets)
    if topic:
        found.append({"kind": "ntfy", "url": "https://ntfy.sh/%s" % topic.lstrip("/")})
    return found


def _payload(target, text):
    kind = target.get("kind")
    if kind == "discord":
        return {"content": text[:DISCORD_LIMIT]}
    if kind == "telegram":
        return {"chat_id": target.get("chat_id"), "text": text[:TELEGRAM_LIMIT],
                "disable_web_page_preview": True}
    return text[:TELEGRAM_LIMIT].encode("utf-8")


def _post(url, payload, content_type):
    """POST minimo con urllib. Devuelve `(ok, detalle)`; nunca lanza hacia el daemon."""
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": content_type,
                                              "User-Agent": "Nexus-Harness/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return 200 <= response.status < 300, "http %s" % response.status
    except Exception as exc:  # noqa: BLE001 -- un aviso roto se declara, no se propaga
        return False, "%s: %s" % (type(exc).__name__, str(exc)[:160])


class Notifier:
    """Manda el mismo texto a todos los canales. Devuelve una fila por canal."""

    def __init__(self, channels=None, config=None, post=None):
        self.channels = list(channels if channels is not None else targets(config) if config else [])
        self._post = post or _post

    @property
    def ready(self):
        return bool(self.channels)

    def send(self, text, kind="info"):
        body = str(text or "").strip()
        if not body:
            return []
        rows = []
        for target in self.channels:
            payload = _payload(target, body)
            content_type = ("text/plain; charset=utf-8" if target.get("kind") == "ntfy"
                            else "application/json")
            ok, detail = self._post(target.get("url"), payload, content_type)
            rows.append({"ok": bool(ok), "channel": target.get("kind"), "detail": detail,
                         "kind": kind})
        return rows


def summary(payload):
    """El texto de un aviso a partir del estado del daemon. Corto, con numeros y sin adornos."""
    payload = payload or {}
    lines = ["Nexus · %s" % (payload.get("status") or "informe")]
    for key in ("project", "task", "exit", "rounds", "criteria", "note"):
        value = payload.get(key)
        if value not in (None, "", []):
            lines.append("%s: %s" % (key, value))
    if payload.get("next"):
        lines.append("siguiente: %s" % payload["next"])
    return "\n".join(lines)[:TELEGRAM_LIMIT]
