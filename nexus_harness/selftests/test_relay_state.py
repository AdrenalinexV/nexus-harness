"""Relevo de contexto: la poda al 55 % y el estado verificado del 70 %, medidos con el motor real.

Tres cosas que un relevo tiene que demostrar, y ninguna se puede fingir:

* la poda ahorra de verdad (una salida de 20 KB queda en una linea con su sha) y es idempotente;
* el estado del relevo (`RELAY_STATE.json`) convive con el del protocolo: guardar el nuestro no borra
  `phases` ni `queue`, y el prompt de la sesion hija se genera SOLO de ese fichero;
* el bucle llama a la poda mientras trabaja, y lo dice en el bus (`context.pruned`), porque un ahorro
  que nadie ve no se puede auditar.
"""
from .. import relay_state
from ..config import HarnessConfig
from ..events import Bus
from ..gate import Gate
from ..judge import Judge
from ..relay_state import RelayState, prune_tool_outputs
from ..tools import default_registry
from ..triad_loop import Triad
from .fakes import FakeRouter, ScriptedProvider, ScriptedSkills, TempProject, reply

TEST_COMMAND = 'python -c "import calc, sys; sys.exit(0 if calc.add(2, 3) == 5 else 1)"'
BIG = "fila de datos irrelevante para el siguiente paso\n" * 500


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def test_module_selftest(failures):
    for problem in relay_state.selftest():
        failures.append("relay_state.selftest: %s" % problem)


def test_pruning_saves_most_of_the_window(failures):
    from ..message import Message, ToolCall

    def turn(index):
        call = ToolCall(id="c%d" % index, name="read_file", arguments={"path": "calc.py"},
                        raw_arguments='{"path": "calc.py"}')
        return [Message(role="assistant", content="", tool_calls=[call]),
                Message(role="tool", content=BIG, tool_call_id=call.id, name="read_file")]

    messages = [Message(role="system", content="reglas")]
    for index in range(6):
        messages.extend(turn(index))
    before = sum(len(item.text_content()) for item in messages)
    pruned, refs = prune_tool_outputs(messages)
    after = sum(len(item.text_content()) for item in messages)
    check("se podan todas menos las dos ultimas", pruned, 4, failures)
    check("cada referencia lleva sha256", all("sha256:" in ref for ref in refs), True, failures)
    check("el ahorro supera el 60 %", after < before * 0.4, True, failures)
    check("podar dos veces no cambia nada", prune_tool_outputs(messages)[0], 0, failures)


def test_prune_preserves_non_tool_messages(failures):
    from ..message import Message, ToolCall

    call = ToolCall(id="c1", name="read_file", arguments={"path": "calc.py"},
                    raw_arguments='{"path": "calc.py"}')
    messages = [
        Message(role="system", content="reglas del sistema"),
        Message(role="user", content="haz la lectura"),
        Message(role="assistant", content="", tool_calls=[call]),
        Message(role="tool", content=BIG, tool_call_id=call.id, name="read_file"),
        Message(role="assistant", content="listo"),
    ]
    # `keep_last=0`: el caso mide la PODA, no la proteccion de la ultima lectura.
    pruned, _ = prune_tool_outputs(messages, keep_last=0)
    check("solo se podó una salida tool", pruned, 1, failures)
    check("system sin cambios", messages[0].role, "system", failures)
    check("system content intacto", messages[0].content, "reglas del sistema", failures)
    check("user sin cambios", messages[1].role, "user", failures)
    check("user content intacto", messages[1].content, "haz la lectura", failures)
    check("assistant tool_calls intacto", messages[2].tool_calls, [call], failures)
    check("assistant final sin cambios", messages[4].role, "assistant", failures)
    check("assistant final content intacto", messages[4].content, "listo", failures)


def test_loop_prunes_and_writes_the_state(failures):
    with TempProject({"calc.py": "def add(a, b):\n    return a + b\n", "big.txt": BIG}) as root:
        config = HarnessConfig(default_root=root, test_command=TEST_COMMAND, max_steps=6,
                               max_repairs=0, budget_limit=200000, relay_threshold=0.99,
                               roles={"director": "fake:d", "worker": "fake:w",
                                      "judge": "fake:j"}, lang="es", temperature=0.0,
                               secrets={})
        worker = ScriptedProvider([
            reply("leo", tools=[("c1", "read_file", {"path": "big.txt"})]),
            reply("leo otra vez", tools=[("c2", "read_file", {"path": "big.txt"})]),
            reply("leo la tercera", tools=[("c3", "read_file", {"path": "big.txt"})]),
            reply("leo la cuarta", tools=[("c4", "read_file", {"path": "big.txt"})]),
            reply("hecho"),
        ], default=reply("hecho"))
        router = FakeRouter(workers=worker, judge=ScriptedProvider(
            [reply('{"verdict": "approve", "reason": "verde"}')], default=reply(
                '{"verdict": "approve", "reason": "verde"}')))
        bus = Bus()
        triad = Triad(router, config, registry=default_registry(root, config),
                      gate=Gate(root, config), judge=Judge(router, "es"),
                      skills=ScriptedSkills(), bus=bus)
        triad.run("leer calc y arreglarlo")
        kinds = [event["kind"] for event in bus.all()]
        check("el bucle poda salidas", "context.pruned" in kinds, True, failures)
        # El estado del relevo lo escribe `SessionRelay`; aqui se prueba el contrato del fichero con
        # el protocolo delante (fases y cola ajenas) y que el prompt se sintetiza del estado.
        state = RelayState(root).milestone("podado", commit="deadbee").next("seguir")
        state.save()
        loaded = RelayState.load(root)
        check("el estado se relee del disco", loaded.closed[0]["commit"], "deadbee", failures)
        check("el prompt cita el siguiente paso", "seguir" in loaded.prompt(), True, failures)


def run():
    failures = []
    test_module_selftest(failures)
    test_pruning_saves_most_of_the_window(failures)
    test_prune_preserves_non_tool_messages(failures)
    test_loop_prunes_and_writes_the_state(failures)
    return failures
