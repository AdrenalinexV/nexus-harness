"""La consulta: preguntar, esperar, contestar y no bloquearse cuando no hay a quien preguntar.

Lo que se mide es lo que puede romper la autonomia de verdad: que una respuesta tardia llegue a su
pregunta, que la primera gane, que un plazo vencido aplique el DEFECTO declarado y no una invencion,
que sin canales el turno no espere a nadie, y que el offset de Telegram se persista para no releer.
"""
import json
import tempfile
from pathlib import Path

from .. import consult, consult_channels
from ..config import HarnessConfig


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def _root():
    return Path(tempfile.mkdtemp(prefix="consult-"))


def test_ask_records_and_describes(failures):
    root = _root()
    row = consult.ask(root, "¿Revertir el turno rojo?", ["revertir", "seguir"], "seguir",
                      project="Demo", deadline_s=600, now=1000.0)
    check("la pregunta existe", row["id"] in consult.questions(root), True, failures)
    check("queda pendiente", [item["id"] for item in consult.pending(root)], [row["id"]], failures)
    check("el plazo se calcula una vez", row["expires"], 1600.0, failures)
    text = consult.describe(row)
    check("lleva las opciones numeradas", "1) revertir" in text and "2) seguir" in text, True,
          failures)
    check("lleva el id para contestar", "/answer %s" % row["id"] in text, True, failures)
    check("y el plazo en minutos", "10 min" in text, True, failures)


def test_first_answer_wins(failures):
    root = _root()
    row = consult.ask(root, "¿Sigo?", ["si", "no"], "no", now=1000.0)
    first = consult.answer(root, row["id"], "si", "telegram")
    second = consult.answer(root, row["id"], "no", "discord")
    check("la primera entra", first.get("ok"), True, failures)
    check("la segunda no pisa", second.get("already"), True, failures)
    check("y no cambia el valor", second.get("answer"), "si", failures)
    check("queda una sola respuesta", consult.get(root, row["id"])["state"], "answered", failures)
    check("una pregunta inexistente no se inventa", consult.answer(root, "zzz", "x").get("ok"),
          False, failures)


def test_wait_returns_the_late_answer(failures):
    root = _root()
    row = consult.ask(root, "¿Sigo?", ["si", "no"], "no", now=1000.0, deadline_s=600)
    ticks = {"n": 0}

    def poll():
        ticks["n"] += 1
        return [{"id": row["id"], "text": "si", "source": "telegram"}] if ticks["n"] == 2 else []

    outcome = consult.wait(root, row["id"], poll=poll, sleep=lambda _s: None,
                           clock=lambda: 1001.0, max_polls=10)
    check("contesta el canal", outcome["state"], "answered", failures)
    check("con el texto del operador", outcome["answer"], "si", failures)
    check("y su procedencia", outcome["source"], "telegram", failures)
    check("sin dormir de verdad dos veces", ticks["n"] >= 2, True, failures)


def test_silence_applies_the_declared_default(failures):
    root = _root()
    row = consult.ask(root, "¿Sigo?", ["si", "no"], "no", now=1000.0, deadline_s=60)
    outcome = consult.wait(root, row["id"], sleep=lambda _s: None, clock=lambda: 5000.0,
                           max_polls=3)
    check("vence el plazo", outcome["state"], "expired", failures)
    check("aplica el defecto declarado", outcome["answer"], "no", failures)
    check("y lo dice", outcome["source"], "default", failures)
    check("queda cerrada, no pendiente", consult.pending(root), [], failures)


def test_without_channels_nothing_waits(failures):
    root = _root()
    slept = []
    result = consult_channels.ask_operator(root, HarnessConfig(notify={}), "¿Sigo?",
                                           ["si", "no"], "no", sleep=slept.append,
                                           clock=lambda: 1.0)
    check("no hay canal", result["state"], "no_channel", failures)
    check("aplica el defecto", result["answer"], "no", failures)
    check("no espera ni un tick", slept, [], failures)
    check("y no deja basura pendiente", consult.pending(root), [], failures)


def test_a_webhook_cannot_be_heard(failures):
    root = _root()
    sent = []

    def post(url, payload, content_type):
        sent.append(url)
        return True, "http 204"

    config = HarnessConfig(notify={"discord_webhook": "https://discord.example/hook"})
    result = consult_channels.ask_operator(root, config, "¿Sigo?", ["si", "no"], "si", post=post,
                                           sleep=lambda _s: None, clock=lambda: 1.0)
    check("se manda", len(sent), 1, failures)
    check("pero se declara sorda", result["state"], "sent_unreadable", failures)
    check("y el bucle sigue con el defecto", result["answer"], "si", failures)
    check("la pregunta sigue abierta para la cabina", len(consult.pending(root)), 1, failures)


def test_telegram_answers_reach_their_question(failures):
    root = _root()
    config = HarnessConfig(secrets={"TG": "tok"},
                           notify={"telegram": {"token": "$TG", "chat_id": "7"}})
    asked = {}

    def post(url, payload, content_type):
        asked["body"] = payload
        asked["url"] = url
        return True, "http 200"

    def get(url, headers):
        row = consult.pending(root)[0]
        return True, {"ok": True, "result": [
            {"update_id": 41, "message": {"chat": {"id": 7},
                                          "text": "/answer %s 2" % row["id"]}},
            {"update_id": 42, "message": {"chat": {"id": 99}, "text": "/answer x 1"}}]}

    result = consult_channels.ask_operator(root, config, "¿Sigo?", ["revertir", "seguir"],
                                           "parar", post=post, get=get,
                                           sleep=lambda _s: None, clock=lambda: 1.0,
                                           max_polls=4)
    check("el mensaje lleva la pregunta", "¿Sigo?" in json.dumps(asked["body"], ensure_ascii=False),
          True, failures)
    check("contesta por telegram", result["source"], "telegram", failures)
    check("con el texto tal cual", result["answer"], "2", failures)
    cursors = consult_channels.load_cursors(root)
    check("el offset se persiste", cursors.get("telegram"), 43, failures)
    check("y el chat ajeno se ignora", consult.questions(root)[result["id"]]["answer"], "2",
          failures)


def test_replies_have_a_shape(failures):
    check("con id explicito", consult.parse_reply("/answer ab12 2", ["ab12"]), ("ab12", "2"),
          failures)
    check("texto suelto con una abierta", consult.parse_reply("seguir", ["ab12"]),
          ("ab12", "seguir"), failures)
    check("sin pregunta abierta no se casa", consult.parse_reply("hola", []), (None, "hola"),
          failures)
    check("el numero se traduce a la opcion", consult.match(["revertir", "seguir"], "2"),
          "seguir", failures)
    check("una palabra se casa sin distinguir caja", consult.match(["Revertir"], "revertir"),
          "Revertir", failures)
    check("lo que no casa se devuelve crudo", consult.match(["si", "no"], "otra cosa"),
          "otra cosa", failures)


def test_secrets_never_travel(failures):
    root = _root()
    row = consult.ask(root, "El token tok-es-secreto fallo, ¿sigo?",
                      secrets=["tok-es-secreto"], now=1000.0)
    check("el secreto va redactado", "tok-es-secreto" in row["text"], False, failures)
    check("y se ve donde estaba", "***" in row["text"], True, failures)


def test_purge_keeps_what_is_open(failures):
    root = _root()
    live = consult.ask(root, "¿Sigo?", now=1000.0)
    for index in range(12):
        closed = consult.ask(root, "vieja %d" % index, now=1000.0)
        consult.answer(root, closed["id"], "si", "test")
    removed = consult.purge(root, keep=4)
    check("quita lineas viejas", removed > 0, True, failures)
    check("pero no la abierta", live["id"] in consult.questions(root), True, failures)
    check("que sigue pendiente", len(consult.pending(root)), 1, failures)


def test_the_loop_asks_before_giving_up(failures):
    """Un rojo no arreglado deja una pregunta escrita y NO se inventa la decision."""
    import json
    import shutil
    from .. import autonomy, autonomy_ask
    from ..config import HarnessConfig as _Config
    from ..platform.events import Bus

    workspace = Path(tempfile.mkdtemp(prefix="consult-loop-"))
    try:
        root = workspace / "Alpha"
        (root / ".ai").mkdir(parents=True)
        (root / ".ai" / "CURRENT_SPEC.json").write_text(
            json.dumps({"format": "nexus.spec/1", "id": "spec-x", "goal": "g",
                        "cas_count": 2, "cas_sha256": "c" * 64}), encoding="utf-8")

        def runner(goal, project):
            return {"ok": False, "exit": 10, "repairs": 2, "steps": 3,
                    "verdict": {"ok": False, "exit": 10, "checks": []},
                    "judgement": {"verdict": "reject"}, "touched": ["a.py"]}

        config = _Config(workspace=workspace, default_root=workspace, notify={})
        pilot = autonomy.Autopilot(config, runner=runner,
                                   planner=lambda r, g, p: {"step": "paso", "done": False},
                                   bus=Bus(),
                                   snapshot=lambda r, reason="": {"ok": True, "kind": "tag",
                                                                  "ref": "x", "reason": ""})
        finished = pilot.run_project("Alpha", "objetivo", iterations=2)
        check("el proyecto no se da por bueno", finished.get("ok"), False, failures)
        rows = list(consult.questions(root).values())
        check("queda la pregunta escrita", len(rows), 1, failures)
        check("con las tres salidas", rows[0]["options"], ["seguir", "revertir", "parar"],
              failures)
        check("sin canal, el defecto es parar", rows[0]["default"], "parar", failures)
        check("y se cierra como no_channel", rows[0].get("source"), "no_channel", failures)
        check("no se queda colgada", consult.pending(root), [], failures)

        seen = {}

        def fake_asker(root_, config_, text, options, default, project, deadline):
            seen.update({"text": text, "options": list(options)})
            return {"state": "answered", "answer": "seguir", "source": "telegram", "id": "q1",
                    "delivered": True}

        ask = autonomy_ask.ask_about_red(root, "Alpha", "gate rojo tras 2 reparaciones", config,
                                         asker=fake_asker)
        check("obedece al operador", ask["decision"], "seguir", failures)
        check("y lo apunta", ask["source"], "telegram", failures)
        check("la pregunta lleva el motivo", "gate rojo" in seen["text"], True, failures)
        stays, _note = autonomy_ask.act(root, "seguir")
        check("seguir mantiene el bucle vivo", stays, True, failures)
        quiet = autonomy_ask.ask_about_red(root, "Alpha", "x",
                                           _Config(consult_enabled=False))
        check("apagado no pregunta", quiet["state"], "disabled", failures)
        check("y su decision es parar", quiet["decision"], "parar", failures)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_revert_undoes_the_turn(failures):
    """`revertir` no es una palabra: restaura los bytes que el turno tenia antes."""
    import shutil
    from .. import autonomy_ask, checkpoint

    workspace = Path(tempfile.mkdtemp(prefix="consult-undo-"))
    try:
        target = workspace / "calc.py"
        target.write_text("original\n", encoding="utf-8")
        journal = checkpoint.begin(workspace, "turno-rojo")
        checkpoint.set_active(journal)
        try:
            journal.record(target, target.read_bytes())
            target.write_text("roto\n", encoding="utf-8")
        finally:
            checkpoint.set_active(None)
        stays, note = autonomy_ask.act(workspace, "revertir")
        check("revertir para el bucle", stays, False, failures)
        check("deja el fichero como estaba", target.read_text(encoding="utf-8"), "original\n",
              failures)
        check("y lo cuenta", "revertido" in note, True, failures)
        empty = Path(tempfile.mkdtemp(prefix="consult-nothing-"))
        stays, note = autonomy_ask.act(empty, "revertir")
        check("sin instantanea no finge", "no hay instantanea" in note, True, failures)
        shutil.rmtree(empty, ignore_errors=True)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_the_cockpit_can_answer_without_a_console(failures):
    """La pregunta tiene que poder contestarse desde la pantalla: botones por opcion y campo libre."""
    import shutil
    from .. import settings, settings_autonomy
    from ..cockpit import Cockpit
    from ..config import HarnessConfig as _Config

    root = Path(tempfile.mkdtemp(prefix="consult-gui-"))
    cockpit = None
    try:
        cockpit = Cockpit(_Config(workspace=root, default_root=root, notify={}))
        row = consult.ask(root, "Demo quedo rojo", ["seguir", "revertir", "parar"], "parar", "Demo")
        body = settings_autonomy.block(cockpit)
        check("el id viaja en el formulario", 'value="%s"' % row["id"] in body, True, failures)
        check("cada opcion es un boton", body.count('name="answer"'), 4, failures)
        check("y hay campo libre", 'placeholder="o escribe la respuesta"' in body, True, failures)
        title, _sub, html = settings._render("autonomia", cockpit, "", {}, {})
        check("la seccion existe en la cabina", title, "Autonomía & Preguntas", failures)
        check("y no revienta al pintar", bool(html), True, failures)
        note, ok, section = settings_autonomy.action(cockpit, {"id": row["id"], "answer": "2"})
        check("contestar desde la cabina funciona", ok, True, failures)
        check("vuelve a su seccion", section, "autonomia", failures)
        check("y la pregunta queda cerrada", consult.pending(root), [], failures)
        check("la nota dice el id", row["id"] in note, True, failures)
    finally:
        if cockpit is not None:
            cockpit.stop()
        shutil.rmtree(root, ignore_errors=True)


def test_the_stop_button_interrupts_the_wait(failures):
    """Un turno esperando una respuesta no puede ignorar a quien pulsa Detener."""
    root = _root()
    row = consult.ask(root, "¿Sigo?", ["si", "no"], "no", now=1000.0, deadline_s=3600)
    outcome = consult.wait(root, row["id"], sleep=lambda _s: None, clock=lambda: 1001.0,
                           max_polls=500, should_stop=lambda: True)
    check("se detiene", outcome["state"], "stopped", failures)
    check("sin inventarse una respuesta", outcome["answer"], "", failures)
    check("y la pregunta sigue abierta", len(consult.pending(root)), 1, failures)


def run():
    failures = []
    for test in (test_ask_records_and_describes, test_first_answer_wins,
                 test_wait_returns_the_late_answer, test_silence_applies_the_declared_default,
                 test_without_channels_nothing_waits, test_a_webhook_cannot_be_heard,
                 test_telegram_answers_reach_their_question, test_replies_have_a_shape,
                 test_secrets_never_travel, test_purge_keeps_what_is_open,
                 test_the_loop_asks_before_giving_up, test_revert_undoes_the_turn,
                 test_the_cockpit_can_answer_without_a_console,
                 test_the_stop_button_interrupts_the_wait):
        try:
            test(failures)
        except Exception as exc:  # noqa: BLE001 -- una suite que revienta es un fallo con nombre
            failures.append("%s crash: %s: %s" % (test.__name__, type(exc).__name__, exc))
    return failures
