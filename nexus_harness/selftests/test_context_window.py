"""La ventana del motor: lo que el arnes cree que cabe y lo que el motor dice que cabe.

El fallo que cierra, tal como se midio: LM Studio con 64.256 tokens cargados, `budget_limit` en
60.000, y un prompt de 66.889. El motor contesto

    400 Engine protocol predict request returned 400: request (68052 tokens) exceeds the available
    context size (64256 tokens)

y el turno se perdio con un error crudo en el panel. Una suite que no cubra esto deja el arnes
prometiendo sitio que no tiene.

Se prueba el modulo real (`nexus_harness.context_window` y `nexus_harness.turn_engine`) con un motor
falso: sin red, sin LM Studio, sin reloj.
"""
from .fakes import FakeRouter, ScriptedSkills, TempProject
from .. import context_window
from ..compaction import Compactor
from ..config import HarnessConfig
from ..context_window import fit, overflow, shrink
from ..platform.events import Bus
from ..message import Message, Reply
from ..platform.tokenizer import count_messages
from ..transports import http
from ..turn_engine import TurnEngine

OVERFLOW_BODY = ('{"error":"Engine protocol predict request returned 400: {\\"error\\":{\\"code\\":400,'
                 '\\"message\\":\\"request (68052 tokens) exceeds the available context size (64256 '
                 'tokens), try increasing it\\",\\"type\\":\\"exceed_context_size_error\\"}}"}')
BLOCKED = "relleno de una salida de herramienta que ocupa sitio de verdad en la ventana " * 900


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def tool_turn(index, size=BLOCKED):
    return [Message(role="assistant", content="", tool_calls=[]),
            Message(role="tool", content=size, tool_call_id="c%d" % index, name="read_file")]


def battery():
    """Un transcript como el del turno que fallo: muchas salidas grandes y un prefijo fijo."""
    messages = [Message(role="system", content="reglas del arnes " * 200),
                Message(role="user", content="arregla el bug de calc.py")]
    for index in range(6):
        messages += tool_turn(index)
    return messages


class Engine:
    """Un motor que rechaza por tamano la primera vez y cuenta cuantas veces le hablaron."""

    kind = "openai"
    base_url = "http://127.0.0.1:1234/v1"
    model = "m"

    def __init__(self, window=64256):
        self.window = window
        self.calls = []
        self.refuse = True

    def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        self.calls.append(list(messages))
        if self.refuse:
            self.refuse = False
            raise http.TransportError("400", status=400, body=OVERFLOW_BODY)
        return Reply(text="hecho")

    def info(self, role):
        return type("Info", (), {"model": self.model})()

    def role(self, role):
        return self

    def window_of(self, role="worker"):
        return self.window


class Config:
    budget_limit = 60000
    max_tokens = 4096
    temperature = 0.2


def test_module_selftests(failures):
    for problem in context_window.selftest():
        failures.append("context_window.selftest: %s" % problem)
    for problem in __import__("nexus_harness.turn_engine", fromlist=["selftest"]).selftest():
        failures.append("turn_engine.selftest: %s" % problem)


def test_the_budget_fits_the_engine(failures):
    check("el presupuesto deja sitio a la respuesta", fit(60000, 64256, 4096) < 64256 - 4096 + 1,
          True, failures)
    check("y nunca sube de lo configurado", fit(60000, 64256, 4096) <= 60000, True, failures)
    check("una ventana pequena recorta de verdad", fit(60000, 8192, 2048) < 8192, True, failures)
    check("sin dato no se inventa recorte", fit(60000, 0, 4096), 60000, failures)


def test_the_overflow_is_read_from_the_engine(failures):
    exc = http.TransportError("400", status=400, body=OVERFLOW_BODY)
    check("la ventana sale del propio 400", overflow(exc), 64256, failures)
    check("un error de otra clase no es ventana",
          overflow(http.TransportError("x", status=500, body='{"error":"boom"}')), 0, failures)


def test_a_late_prompt_still_gets_an_answer(failures):
    """El caso real: el prompt no cabe, y el turno termina igual."""
    router = Engine()
    bus = Bus(clock=lambda: 0.0)
    compactor = Compactor(limit=60000, threshold=0.55, model="m")
    engine = TurnEngine(router, Config, compactor, emit=bus.emit)
    engine.fit()
    messages = battery()
    before = sum(len(str(m.content)) for m in messages)
    reply = engine.ask(messages, None)
    check("el turno contesta", reply.text, "hecho", failures)
    check("hubo un reintento", len(router.calls), 2, failures)
    check("el reintento lleva menos texto",
          sum(len(str(m.content)) for m in router.calls[1]) < before,
          True, failures)
    check("aprende la ventana del motor", engine.window, 64256, failures)
    check("el presupuesto se reajusta", compactor.limit, fit(60000, 64256, 4096), failures)
    kinds = [event["kind"] for event in bus.all()]
    check("el panel lo ve", "context.overflow" in kinds, True, failures)
    check("y dice cuanto cabe", bus.find("context.overflow")[0]["payload"].get("window"), 64256,
          failures)


def test_another_failure_is_not_disguised(failures):
    """Un fallo que no es de tamano sube intacto: el arnes no se inventa respuestas."""
    class Roto(Engine):
        def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
            self.calls.append(list(messages))
            raise http.TransportError("model not found", status=404, body='{"error":"no"}')

    router = Roto()
    engine = TurnEngine(router, Config, Compactor(limit=60000), emit=lambda *a, **k: None)
    raised = ""
    try:
        engine.ask([Message(role="user", content="hola")], None)
    except http.TransportError as exc:
        raised = str(exc)
    check("el fallo sube", bool(raised), True, failures)
    check("y no se reintenta a lo tonto", len(router.calls), 1, failures)


def test_the_chat_survives_the_window(failures):
    """El mismo caso por el bucle del chat: se comprueba que no se pierde el turno ni la historia."""
    from ..chat import Chat
    from .fakes import FakeGate

    with TempProject({"calc.py": "def add(a, b):\n    return a + b\n"}) as root:
        config = HarnessConfig(default_root=root, test_command="python -c \"pass\"", max_steps=4,
                               max_repairs=1, budget_limit=60000, compact_threshold=0.55,
                               roles={"director": "fake:d", "worker": "fake:w", "judge": "fake:j"},
                               lang="es", temperature=0.0, secrets={})
        router = Engine()
        chat = Chat(router, config, type("R", (), {"schemas": lambda self: []})(), FakeGate(ok=True),
                    ScriptedSkills(), bus=Bus(clock=lambda: 0.0))
        chat.new("ventana")
        chat.history = [Message(role="assistant", content="", tool_calls=[])] + [
            Message(role="tool", content=BLOCKED, tool_call_id="c%d" % index, name="read_file")
            for index in range(6)]
        turn = chat.send("sigue")
        check("el turno termina", turn["reply"], "hecho", failures)
        check("y el chat sabe que ventana tiene", chat.window_tokens, 64256, failures)
        check("la historia no se pierde", bool(chat.history), True, failures)


def test_z_the_window_is_asked_not_typed(failures):
    """`Router.window` pregunta a los endpoints reales; con un servidor que no contesta, 0."""
    from ..context_window import lmstudio_window, ollama_window
    payload = {"data": [{"id": "m", "state": "loaded", "loaded_context_length": 64256,
                         "max_context_length": 262144},
                        {"id": "otro", "state": "loaded", "loaded_context_length": 32768}]}
    check("LM Studio publica la ventana cargada", lmstudio_window(payload, "m"), 64256, failures)
    check("y el modelo se respeta", lmstudio_window(payload, "otro"), 32768, failures)
    check("un modelo sin cargar no promete nada",
          lmstudio_window({"data": [{"id": "m", "state": "not-loaded",
                                     "max_context_length": 262144}]}, "m"), 0, failures)
    check("Ollama publica la suya",
          ollama_window({"models": [{"model": "q", "context_length": 8192}]}, "q"), 8192, failures)


def test_the_shrink_never_touches_the_contract(failures):
    messages = battery()
    shrunk = shrink(messages, 4000, "m")
    check("el system viaja entero", shrunk[0].content, messages[0].content, failures)
    check("la peticion viaja entera", shrunk[1].content, messages[1].content, failures)
    check("y el total cabe", count_messages(shrunk, "m") <= 4000, True, failures)


def run():
    failures = []
    for test in (test_module_selftests, test_the_budget_fits_the_engine,
                 test_the_overflow_is_read_from_the_engine, test_a_late_prompt_still_gets_an_answer,
                 test_another_failure_is_not_disguised, test_the_chat_survives_the_window,
                 test_z_the_window_is_asked_not_typed, test_the_shrink_never_touches_the_contract):
        test(failures)
    return failures
