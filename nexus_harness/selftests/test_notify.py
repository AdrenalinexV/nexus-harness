"""Avisos: los canales se resuelven, el texto se recorta y un canal caido no tumba nada.

Un daemon que trabaja solo tiene que poder contarlo. Lo que se mide es la fontaneria: que el secreto
salga de la boveda y no del documento, que cada canal reciba su forma, y que un 500 de Discord sea una
fila con su motivo en vez de una excepcion que pare el bucle.
"""
from .. import notify
from ..config import HarnessConfig


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def test_channels_come_from_config_and_secrets(failures):
    config = HarnessConfig(secrets={"NEXUS_DISCORD": "https://discord.example/hook"},
                           notify={"discord_webhook": "$NEXUS_DISCORD",
                                   "telegram": {"token": "$TG_TOKEN", "chat_id": "42"},
                                   "ntfy": "nexus-pruebas"})
    config.secrets.update({"TG_TOKEN": "abc123"})
    found = notify.targets(config)
    kinds = [row["kind"] for row in found]
    check("tres canales", kinds, ["discord", "telegram", "ntfy"], failures)
    check("el webhook sale de la boveda", found[0]["url"], "https://discord.example/hook", failures)
    check("telegram compone su url", found[1]["url"].endswith("/botabc123/sendMessage"), True,
          failures)
    check("y lleva el chat", found[1]["chat_id"], "42", failures)
    empty = notify.targets(HarnessConfig(notify={}))
    check("sin canales no hay avisos", empty, [], failures)
    half = notify.targets(HarnessConfig(notify={"telegram": {"token": "$NO_EXISTE"}}))
    check("un telegram sin token no se inventa", half, [], failures)


def test_each_channel_gets_its_shape(failures):
    long_text = "x" * 5000
    discord = notify._payload({"kind": "discord"}, long_text)
    check("discord recorta a 1900", len(discord["content"]), 1900, failures)
    telegram = notify._payload({"kind": "telegram", "chat_id": "7"}, long_text)
    check("telegram recorta a 4000", len(telegram["text"]), 4000, failures)
    check("y lleva el chat", telegram["chat_id"], "7", failures)
    ntfy_body = notify._payload({"kind": "ntfy"}, long_text)
    check("ntfy viaja como texto", isinstance(ntfy_body, bytes), True, failures)


def test_a_failing_channel_is_a_row_not_an_exception(failures):
    sent = []

    def fake_post(url, payload, content_type):
        sent.append((url, content_type))
        return ("fail" not in url), "http 200" if "fail" not in url else "http 500"

    channels = [{"kind": "discord", "url": "https://ok.example/1"},
                {"kind": "discord", "url": "https://fail.example/2"}]
    rows = notify.Notifier(channels=channels, post=fake_post).send("hola")
    check("dos filas", len(rows), 2, failures)
    check("una buena", rows[0]["ok"], True, failures)
    check("una mala, declarada", rows[1]["ok"], False, failures)
    check("con su motivo", "500" in rows[1]["detail"], True, failures)
    check("y las dos se intentaron", len(sent), 2, failures)


def test_the_summary_is_short_and_says_what_happened(failures):
    text = notify.summary({"status": "trabajo", "project": "Alpha", "exit": 10,
                           "rounds": 3, "next": "revisar el rojo"})
    for needle in ("Nexus", "Alpha", "exit: 10", "rounds", "siguiente"):
        if needle.lower() not in text.lower():
            failures.append("el resumen no menciona %r: %r" % (needle, text))
    check("no se pasa de telegram", len(text) <= notify.TELEGRAM_LIMIT, True, failures)
    check("vacio no rompe", notify.summary({}).startswith("Nexus"), True, failures)


def test_no_channels_means_no_work(failures):
    notifier = notify.Notifier(channels=[])
    check("no esta listo", notifier.ready, False, failures)
    check("y no manda nada", notifier.send("hola"), [], failures)


def run():
    failures = []
    test_channels_come_from_config_and_secrets(failures)
    test_each_channel_gets_its_shape(failures)
    test_a_failing_channel_is_a_row_not_an_exception(failures)
    test_the_summary_is_short_and_says_what_happened(failures)
    test_no_channels_means_no_work(failures)
    return failures
