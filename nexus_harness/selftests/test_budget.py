"""Presupuesto de coste: el techo en dolares, la parada dura y el hueco que deja.

The suite measures the real module (`nexus_harness.budget`) and the two real loops:

* la tabla de precios empareja por la clave MAS LARGA (`gpt-4o-mini` no es `gpt-4o`), un motor local
  cuesta 0 **declarado** y un modelo que no esta en la tabla no cuesta cero: queda `unpriced`;
* el coste separa entrada de salida -- si no, el numero no vale para decidir nada;
* `limit_usd=0` es `unbounded`, no un techo de cero: nadie declaro un techo que cruzar;
* y la parada es dura de verdad: se mide que el bucle hace UNA llamada menos que sin techo, y esa
  comparacion es la falsificacion dentro de la propia suite -- si la parada fuese un aviso, el
  segundo caso (sin techo) y el primero (con techo) llamarian igual.
"""
from .fakes import FakeGate, FakeRouter, ScriptedProvider, ScriptedSkills, TempProject, reply
from ..core.budget import CostBudget, cost_of, price_of
from ..chat import Chat
from ..config import HarnessConfig
from ..platform.events import Bus
from ..judge import Judge
from ..core.message import Usage
from ..tools import default_registry
from ..platform.transcripts import Transcripts
from ..triad_loop import Triad

CARO = 1_000_000          # un millon de tokens de entrada: el coste sale en USD legibles
TECHO = 0.01              # techo ridiculamente bajo, para que una sola respuesta lo cruce


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def con_techo(root, limit):
    return HarnessConfig(default_root=root, test_command="python -c \"pass\"", max_steps=6,
                         max_repairs=1, budget_limit=60000, compact_threshold=0.55, cost_limit=limit,
                         roles={"director": "fake:d", "worker": "fake:w", "judge": "fake:j"},
                         lang="es", temperature=0.0, secrets={})


def caro(tools=(), text=""):
    """Una respuesta de un modelo de nube con precio conocido y un millon de tokens de entrada."""
    return reply(text, tools=tools, model="deepseek-chat", prompt=CARO, completion=0)


def test_price_table_is_explicit(failures):
    check("la clave mas larga gana", price_of("gpt-4o-mini"), (0.15, 0.60), failures)
    check("y no la corta", price_of("gpt-4o"), (2.50, 10.00), failures)
    check("un motor local cuesta 0 declarado", price_of("lmstudio:kat-coder-35b"), (0.0, 0.0),
          failures)
    check("un modelo que no esta en la tabla NO es 0", price_of("modelo-inventado-9000"), None,
          failures)
    check("y una cadena vacia tampoco", price_of(""), None, failures)


def test_cost_is_pure_and_split(failures):
    entrada = Usage(prompt=CARO, completion=0)
    salida = Usage(prompt=0, completion=CARO)
    check("entrada x 1M cuesta su precio de entrada", round(cost_of("deepseek-chat", entrada)[0], 6),
          0.27, failures)
    check("salida x 1M cuesta el de salida, que es otro", round(cost_of("deepseek-chat", salida)[0], 6),
          1.10, failures)
    check("la misma medida da el mismo numero", cost_of("deepseek-chat", entrada),
          cost_of("deepseek-chat", entrada), failures)
    check("y va marcada como medida", cost_of("deepseek-chat", entrada)[1], True, failures)
    check("sin uso medido no hay precio", cost_of("deepseek-chat", None), (0.0, False), failures)
    check("ni con un uso vacio", cost_of("deepseek-chat", Usage()), (0.0, False), failures)


def test_unpriced_is_not_free(failures):
    budget = CostBudget(limit_usd=1.0)
    state = budget.observe(Usage(prompt=CARO, completion=CARO), "modelo-inventado-9000")
    check("el gasto no sube", state["spent"], 0.0, failures)
    check("pero la llamada se cuenta", state["calls"], 1, failures)
    check("y se declara sin precio", state["unpriced_calls"], 1, failures)
    check("nada se conto como medido", state["priced_calls"], 0, failures)
    check("asi que no se lee como gratis", state["unpriced_calls"] > 0, True, failures)


def test_zero_limit_is_unbounded(failures):
    budget = CostBudget(limit_usd=0.0)
    budget.observe(Usage(prompt=CARO, completion=CARO), "deepseek-chat")
    check("no hay techo", budget.bounded, False, failures)
    check("no es un 0 %", budget.ratio, None, failures)
    check("no se declara cruzado", budget.exceeded, False, failures)
    check("y no para", budget.stop(), False, failures)
    check("el estado lo dice con una palabra", budget.state()["state"], "unbounded", failures)


def test_hard_stop_crosses_once(failures):
    budget = CostBudget(limit_usd=TECHO)
    check("antes de gastar no para", budget.stop(), False, failures)
    budget.observe(Usage(prompt=CARO, completion=0), "deepseek-chat")
    check("el gasto esta medido", round(budget.spent, 6), 0.27, failures)
    check("cruzado el techo", budget.exceeded, True, failures)
    check("y ahora si para", budget.stop("prueba"), True, failures)
    check("con el motivo escrito", "USD" in budget.reason and "prueba" in budget.reason, True,
          failures)
    before = budget.reason
    check("parar otra vez sigue parando", budget.stop("otra"), True, failures)
    check("la razon no se reescribe", budget.reason, before, failures)
    check("y el estado viaja", budget.state()["exceeded"], True, failures)


def chat_run(root, limit):
    """Un turno real de conversacion con un guion que pide una segunda llamada."""
    config = con_techo(root, limit)
    worker = ScriptedProvider([caro(tools=[("c1", "read_file", {"path": "calc.py"})]),
                               caro(text="no deberia llegar")])
    router = FakeRouter(workers=worker)
    bus = Bus(clock=lambda: 0.0)
    chat = Chat(router, config, default_registry(root, config), FakeGate(ok=True), ScriptedSkills(),
                bus=bus, transcripts=Transcripts(root))
    chat.new("coste")
    turn = chat.send("lee calc.py")
    return worker, bus, turn


def test_chat_hard_stops_on_budget(failures):
    with TempProject({"calc.py": "def add(a, b):\n    return a + b\n"}) as root:
        worker, bus, turn = chat_run(root, TECHO)
        kinds = [event["kind"] for event in bus.all()]
        check("el turno hace UNA sola llamada al modelo", len(worker.calls), 1, failures)
        check("el cockpit lo vio", "budget.stop" in kinds, True, failures)
        check("y el turno lo lleva en su estado", turn["budget"]["exceeded"], True, failures)
        check("con el gasto medido", round(turn["budget"]["spent"], 6), 0.27, failures)
        check("el turno cierra con el gate", turn["exit"], 0, failures)


def test_without_a_ceiling_the_same_script_calls_twice(failures):
    """La falsificacion: sin techo, el mismo guion gasta la segunda llamada. La parada es lo que la corta."""
    with TempProject({"calc.py": "def add(a, b):\n    return a + b\n"}) as root:
        worker, bus, turn = chat_run(root, 0.0)
        check("sin techo si hay segunda llamada", len(worker.calls), 2, failures)
        check("nadie declaro parada", "budget.stop" in [e["kind"] for e in bus.all()], False, failures)
        check("y el estado dice sin tope", turn["budget"]["state"], "unbounded", failures)


def test_triad_hard_stops_on_budget(failures):
    with TempProject({"calc.py": "def add(a, b):\n    return a + b\n"}) as root:
        config = con_techo(root, TECHO)
        worker = ScriptedProvider([caro(tools=[("c1", "read_file", {"path": "calc.py"})]),
                                   caro(text="no deberia llegar")])
        router = FakeRouter(workers=worker)
        bus = Bus(clock=lambda: 0.0)
        triad = Triad(router, config, registry=default_registry(root, config),
                      gate=FakeGate(ok=True), judge=Judge(router, "es"), skills=ScriptedSkills(),
                      bus=bus)
        result = triad.run("lee calc.py y confirma")
        check("el obrero hace UNA sola llamada", len(worker.calls), 1, failures)
        check("el cockpit lo vio", "budget.stop" in [e["kind"] for e in bus.all()], True, failures)
        check("el resultado lleva el coste", result.cost["exceeded"], True, failures)
        check("con el techo declarado", round(result.cost["limit"], 6), TECHO, failures)
        check("y el run no se inventa un verde: el gate decidio", result.ok, True, failures)


def test_triad_without_a_ceiling_calls_twice(failures):
    with TempProject({"calc.py": "def add(a, b):\n    return a + b\n"}) as root:
        config = con_techo(root, 0.0)
        worker = ScriptedProvider([caro(tools=[("c1", "read_file", {"path": "calc.py"})]),
                                   caro(text="no deberia llegar")])
        router = FakeRouter(workers=worker)
        triad = Triad(router, config, registry=default_registry(root, config),
                      gate=FakeGate(ok=True), judge=Judge(router, "es"), skills=ScriptedSkills())
        result = triad.run("lee calc.py y confirma")
        check("sin techo el obrero llama dos veces", len(worker.calls), 2, failures)
        check("y el coste va sin tope", result.cost["state"], "unbounded", failures)


def run():
    failures = []
    for test in (test_price_table_is_explicit, test_cost_is_pure_and_split,
                 test_unpriced_is_not_free, test_zero_limit_is_unbounded,
                 test_hard_stop_crosses_once, test_chat_hard_stops_on_budget,
                 test_without_a_ceiling_the_same_script_calls_twice,
                 test_triad_hard_stops_on_budget, test_triad_without_a_ceiling_calls_twice):
        test(failures)
    return failures
