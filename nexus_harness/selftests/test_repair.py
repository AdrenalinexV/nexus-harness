"""Argumentos de tool ilegibles: el turno se corrige solo, y no se pierde nada por el camino.

Un modelo que corta el JSON de sus argumentos es lo normal, no una excepcion: el caso caro no es el
error, es lo que hace el arnes con el. Las dos politicas equivocadas se ven igual desde fuera --
dejar caer el turno (y el trabajo que ya estaba hecho con el) o ejecutar la llamada con argumentos
vacios (que es peor: un `patch_replace` sin `old_string` puede tocar el fichero equivocado). Esta
suite clava cuatro promesas:

* los argumentos ilegibles se conservan TAL CUAL, con el motivo, para que el modelo pueda reenviarlos
  corregidos en vez de adivinar que mando;
* el bucle contesta esa llamada con un error legible y SIGUE: el turno no muere y el trabajo posterior
  ocurre de verdad (el fichero cambia y la puerta cierra en verde);
* una llamada mala NO arrastra a sus hermanas de la misma respuesta: las que si se pueden ejecutar se
  ejecutan, y el resultado viaja en el orden de las llamadas (el `tool_call_id` depende de eso);
* nada de esto es una excepcion: no aparece `worker.error` ni `worker.blocked` por el camino.

El bucle se mide con la puerta REAL (lint + ley de lineas + el comando de test) y un modelo con guion.
"""
from .fakes import FakeGate, FakeRouter, ScriptedProvider, ScriptedSkills, TempProject, reply
from ..chat import Chat
from ..config import HarnessConfig
from ..platform.events import Bus
from ..gate import Gate
from ..judge import Judge
from ..core.message import Reply, ToolCall, Usage, as_text
from ..tools import Observation, default_registry
from ..triad_loop import Triad
from ..platform.transcripts import Transcripts

TEST_COMMAND = 'python -c "import calc, sys; sys.exit(0 if calc.add(2, 3) == 5 else 1)"'
PATCH = reply(tools=[("c1", "patch_replace", {
    "path": "calc.py", "old_string": "return a - b", "new_string": "return a + b"})])


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def unusable(name, raw, call_id="bad1"):
    """Una respuesta con una sola llamada cuyos argumentos no se pueden leer, tal como llegan."""
    call = ToolCall.from_openai({"id": call_id, "function": {"name": name, "arguments": raw}})
    return Reply(tool_calls=[call], usage=Usage(prompt=10, completion=5))


def config_for(root, **overrides):
    values = dict(default_root=root, roles={"director": "fake:d", "worker": "fake:w",
                                            "judge": "fake:j"},
                  test_command=TEST_COMMAND, max_steps=6, max_repairs=2, lang="es",
                  temperature=0.0, secrets={})
    values.update(overrides)
    return HarnessConfig(**values)


def test_unusable_arguments_are_kept_with_their_reason(failures):
    truncated = ToolCall.from_openai({"id": "b", "function": {"name": "read_file",
                                                             "arguments": '{"path": "calc.py"'}})
    check("el JSON roto se declara", truncated.parse_error.startswith("arguments are not JSON"),
          True, failures)
    check("no se inventan argumentos", truncated.arguments, {}, failures)
    check("y se conserva lo que el modelo mando", truncated.raw_arguments, '{"path": "calc.py"',
          failures)
    array = ToolCall.from_openai({"id": "b", "function": {"name": "read_file",
                                                         "arguments": '["calc.py"]'}})
    check("un array no es un objeto de argumentos", "not an object" in array.parse_error, True,
          failures)
    check("y tampoco se ejecuta", array.arguments, {}, failures)
    good = ToolCall.from_openai({"id": "g", "function": {"name": "read_file",
                                                        "arguments": '{"path": "calc.py"}'}})
    check("el JSON bueno no lleva error", good.parse_error, "", failures)
    check("y si trae sus argumentos", good.arguments, {"path": "calc.py"}, failures)
    check("el modelo lee el fallo como fallo",
          as_text(Observation(ok=False, text="x")).startswith("ERROR:"), True, failures)


def test_the_worker_loop_answers_it_and_keeps_going(failures):
    with TempProject() as root:
        worker = ScriptedProvider([unusable("read_file", '{"path": "calc.py"'), PATCH,
                                   reply("Corregido: el test lo demuestra.")])
        config = config_for(root)
        router = FakeRouter(workers=worker)
        bus = Bus(clock=lambda: 0.0)
        triad = Triad(router, config, registry=default_registry(root, config),
                      gate=Gate(root, config), judge=Judge(router, "es"),
                      skills=ScriptedSkills(), bus=bus)
        result = triad.run("arregla add() para que sume")
        kinds = [event["kind"] for event in bus.all()]
        check("el turno no muere por una llamada ilegible", result.exit, 0, failures)
        check("y el trabajo sigue de verdad", "a + b" in (root / "calc.py").read_text(encoding="utf-8"),
              True, failures)
        failed = [event for event in bus.all() if event["kind"] == "tool.call"
                  and event["payload"].get("ok") is False]
        check("el error se registra como llamada fallida", len(failed), 1, failures)
        check("y el registro dice de que herramienta era",
              failed[0]["detail"] if failed else "", "read_file", failures)
        check("con el motivo en el evento",
              "not JSON" in (failed[0]["payload"].get("result", "") if failed else ""), True,
              failures)
        check("sin convertirlo en una excepcion", "worker.error" in kinds, False, failures)
        check("ni en un rol bloqueado", "worker.blocked" in kinds, False, failures)
        check("se le volvio a preguntar al modelo despues",
              len(worker.calls) >= 3, True, failures)
        sent = [message for call in worker.calls for message in call["messages"]
                if message.get("role") == "tool" and message.get("name") == "read_file"]
        check("y el modelo recibio el motivo, no un vacio", len(sent) >= 1, True, failures)
        check("el motivo nombra el JSON",
              "not JSON" in (sent[0]["content"] if sent else ""), True, failures)


def test_a_bad_sibling_does_not_lose_the_good_calls(failures):
    with TempProject() as root:
        config = config_for(root, max_steps=2)
        router = FakeRouter(workers=ScriptedProvider([reply("nada")]))
        chat = Chat(router, config, default_registry(root, config), FakeGate(), ScriptedSkills(),
                    bus=Bus(), transcripts=Transcripts(root))
        good = reply(tools=[("g1", "read_file", {"path": "calc.py"})]).tool_calls[0]
        bad = unusable("patch_replace", "{roto", call_id="b2").tool_calls[0]
        good2 = reply(tools=[("g3", "read_file", {"path": "calc.py"})]).tool_calls[0]
        rows = list(chat._dispatch([good, bad, good2]))
        check("una fila por llamada, en su orden", [call.id for _i, call, _o in rows],
              ["g1", "b2", "g3"], failures)
        check("las buenas se ejecutaron", [observation.ok for _i, _c, observation in rows],
              [True, False, True], failures)
        check("y la mala dice por que", "argumentos ilegibles" in rows[1][2].text, True, failures)


def run():
    failures = []
    for test in (test_unusable_arguments_are_kept_with_their_reason,
                 test_the_worker_loop_answers_it_and_keeps_going,
                 test_a_bad_sibling_does_not_lose_the_good_calls):
        test(failures)
    return failures
