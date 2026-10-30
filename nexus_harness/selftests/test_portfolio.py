"""La cartera: escalera por rol, escalado con presupuesto, failover de transporte y cache contada.

Lo que se mide:
* la escalera se lee de la config y no inventa peldanos;
* no se escala sin siguiente modelo ni con el presupuesto agotado;
* un transporte que cae no termina el turno: responde el siguiente y los errores se declaran;
* los tokens de cache viajan al libro como medida, y abaratan el coste sin contarse como gratis.
"""
from .fakes import FakeGate, FakeRouter, ScriptedProvider, TempProject, reply
from ..platform import ledger
from ..core import budget
from ..context import savings
from ..config import HarnessConfig
from ..core.message import Usage
from ..llm.portfolio import Portfolio, maybe_escalate
from ..llm.providers import Router
from ..selftests.test_triad_loop import config_for
from ..triad_loop import Triad


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


class Broken:
    """Un peldano que no contesta. `ready` es True: el fallo es del transporte, no de la config."""

    model = "fake:broken"
    ready = True
    why_not_ready = ""

    def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        raise RuntimeError("connection reset by peer")

    def models(self, timeout=8):
        return []


class Working(ScriptedProvider):
    ready = True
    why_not_ready = ""


def test_the_ladder_is_read_and_deduplicated(failures):
    single = HarnessConfig(roles={"worker": "fake:w"})
    check("sin escalera hay un peldano", Portfolio(single).ladder("worker"), ["fake:w"], failures)
    config = HarnessConfig(roles={"worker": "fake:w"},
                           role_ladders={"worker": ["fake:w", "fake:big", "fake:big", "deepseek:x"]})
    portfolio = Portfolio(config)
    check("la escalera se limpia", portfolio.ladder("worker"),
          ["fake:w", "fake:big", "deepseek:x"], failures)
    check("desde el segundo, quedan dos", portfolio.after("worker", "fake:big"),
          ["fake:big", "deepseek:x"], failures)
    check("el siguiente del primario", portfolio.next_spec("worker"), "fake:big", failures)
    check("el ultimo no tiene siguiente", portfolio.next_spec("worker", "deepseek:x"), "", failures)


def test_escalation_respects_the_end_and_the_budget(failures):
    config = HarnessConfig(roles={"worker": "fake:w"}, role_ladders={"worker": ["fake:w"]})
    at_end = Portfolio(config).escalate("worker")
    check("sin siguiente no se escala", at_end.ok, False, failures)
    check("y se dice por que", "no hay un modelo siguiente" in at_end.reason, True, failures)

    ladder = HarnessConfig(roles={"worker": "fake:w"},
                           role_ladders={"worker": ["fake:w", "fake:big"]})
    tight = budget.CostBudget(limit_usd=0.1)
    tight.observe(Usage(prompt=2_000_000), "deepseek-chat")   # 0,54 USD: techo cruzado
    refused = Portfolio(ladder).escalate("worker", budget=tight)
    check("con el presupuesto agotado no se escala", refused.ok, False, failures)
    check("y lo dice", "presupuesto" in refused.reason, True, failures)
    allowed = Portfolio(ladder).escalate("worker", budget=budget.CostBudget(limit_usd=10.0))
    check("con presupuesto si se escala", allowed.ok, True, failures)
    check("al siguiente peldano", allowed.spec, "fake:big", failures)
    check("y declara de donde venia", allowed.from_spec, "fake:w", failures)


def test_a_dead_transport_does_not_end_the_turn(failures):
    config = HarnessConfig(roles={"worker": "fake:a"},
                           role_ladders={"worker": ["fake:a", "fake:b"]})
    good = Working([reply("contesto el segundo", model="fake:b")])
    router = Router(config, transports={"fake:a": Broken(), "fake:b": good})
    transport = router.role("worker")
    check("la cartera esta lista si un peldano lo esta", transport.ready, True, failures)
    answer = transport.chat([])
    check("responde el siguiente", answer.text, "contesto el segundo", failures)
    check("y se sabe cual fue", transport.used, "fake:b", failures)
    check("el fallo queda declarado", any("connection reset" in one for one in transport.errors),
          True, failures)


def test_when_every_rung_falls_the_error_names_them(failures):
    config = HarnessConfig(roles={"worker": "fake:a"},
                           role_ladders={"worker": ["fake:a", "fake:b"]})
    router = Router(config, transports={"fake:a": Broken(), "fake:b": Broken()})
    try:
        router.role("worker").chat([])
        failures.append("sin ningun peldano vivo tiene que lanzar")
    except RuntimeError as exc:
        check("el error agrega los dos", str(exc).count("connection reset"), 2, failures)


def test_a_transport_failure_keeps_its_type(failures):
    """El 400 de tamaño tiene que llegar como `TransportError`, no como un resumen sin cuerpo.

    El arnes decide si puede arreglar el fallo mirando el tipo y el cuerpo: un 400 de ventana se
    arregla podando, un 401 no. Un `RuntimeError` agregado convierte un fallo reparable en un turno
    perdido, y eso era parte del fallo original: el chat recibia "ningun modelo respondio" y moria.
    """
    from ..llm.transports.http import TransportError

    class Gordo:
        model = "fake:gordo"
        ready = True
        why_not_ready = ""

        def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
            raise TransportError("400", status=400, body='{"error":"exceeds the available context size '
                                                        '(12544 tokens)"}')

        def models(self, timeout=8):
            return []

    config = HarnessConfig(roles={"worker": "fake:gordo"},
                           role_ladders={"worker": ["fake:gordo"]})
    router = Router(config, transports={"fake:gordo": Gordo()})
    caught = None
    try:
        router.role("worker").chat([])
    except TransportError as exc:
        caught = exc
    except RuntimeError as exc:
        failures.append("el tipo se perdio en la cartera: %s" % exc)
    check("el fallo de transporte conserva su tipo", caught is not None, True, failures)
    check("y su status", getattr(caught, "status", None), 400, failures)
    check("y el cuerpo que dice la ventana", "12544" in str(getattr(caught, "body", "")), True,
          failures)


def test_the_second_red_escalates(failures):
    config = HarnessConfig(roles={"worker": "fake:w"},
                           role_ladders={"worker": ["fake:w", "fake:big"]})

    class Recording(FakeRouter):
        def __init__(self):
            super().__init__(workers=ScriptedProvider([reply("uno")]))
            self.moved = []
            self.portfolio = Portfolio(config)

        def swap(self, role, spec):
            self.moved.append((role, spec))
            return self.info(role)

    router = Recording()
    checks = []

    class Emitter:
        def __call__(self, kind, detail="", **payload):
            checks.append(kind)

    budget_box = budget.CostBudget(limit_usd=0.0)
    check("al primer rojo no se escala", maybe_escalate(router, router.portfolio, budget_box, 1),
          None, failures)
    move = maybe_escalate(router, router.portfolio, budget_box, 2, Emitter())
    check("al segundo si", bool(move and move.ok), True, failures)
    check("y el router cambia de modelo", router.moved, [("worker", "fake:big")], failures)
    check("el evento queda", "router.escalated" in checks, True, failures)


def test_the_triad_escalates_after_two_red_gates(failures):
    with TempProject() as root:
        config = config_for(root, max_repairs=3, max_steps=1,
                            role_ladders={"worker": ["fake:w", "fake:big"]})
        router = FakeRouter(workers=ScriptedProvider([reply("hecho")]))
        router.portfolio = Portfolio(config)
        moved = []
        router.swap = lambda role, spec: moved.append((role, spec)) or router.info(role)
        red = __import__("nexus_harness.verify.gate", fromlist=["Check", "Verdict"])
        verdicts = [__import__("nexus_harness.selftests.test_chat", fromlist=["verdict"])
                    .verdict(False) for _ in range(2)] + [
                    __import__("nexus_harness.selftests.test_chat", fromlist=["verdict"])
                    .verdict(True)]
        triad = Triad(router, config, gate=FakeGate(verdicts=verdicts),
                      judge=__import__("nexus_harness.llm.judge", fromlist=["Judge"]).Judge(router, "es"))
        triad.run("arregla calc.py")
        check("escalo una vez", len(moved), 1, failures)
        check("al segundo peldano", moved[0][1] if moved else "", "fake:big", failures)


def test_cached_tokens_are_measured_and_cheaper(failures):
    openai = Usage.from_openai({"prompt_tokens": 1000, "completion_tokens": 10,
                                "prompt_tokens_details": {"cached_tokens": 600}})
    check("openai trae el cache", openai.cached, 600, failures)
    deepseek = Usage.from_openai({"prompt_tokens": 1000, "completion_tokens": 10,
                                  "prompt_cache_hit_tokens": 800})
    check("deepseek lo llama de otra forma", deepseek.cached, 800, failures)
    anthropic_usage = Usage.from_anthropic({"input_tokens": 900, "output_tokens": 10,
                                            "cache_read_input_tokens": 500})
    check("anthropic tambien", anthropic_usage.cached, 500, failures)
    check("la proporcion se calcula", deepseek.cache_ratio, 0.8, failures)
    check("sin medida no hay proporcion", Usage().cache_ratio, None, failures)

    full, _ = budget.cost_of("deepseek-chat", Usage(prompt=1_000_000))
    cached, _ = budget.cost_of("deepseek-chat", Usage(prompt=1_000_000, cached=1_000_000))
    check("el cache abarata la entrada", round(cached, 6), round(full * budget.CACHE_DISCOUNT, 6),
          failures)

    book = savings.SavingsLedger(index_tokens=0)
    book.request(1000, cached_tokens=600)
    check("el libro guarda el cache", book.as_dict()["cached_tokens"], 600, failures)
    row = ledger.from_turn({"exit": 0, "tokens": {"prompt": 1000, "completion": 0},
                            "savings": book.as_dict()})
    check("y viaja al libro de turnos", row.get("cached_tokens"), 600, failures)


def run():
    failures = []
    test_the_ladder_is_read_and_deduplicated(failures)
    test_escalation_respects_the_end_and_the_budget(failures)
    test_a_dead_transport_does_not_end_the_turn(failures)
    test_when_every_rung_falls_the_error_names_them(failures)
    test_a_transport_failure_keeps_its_type(failures)
    test_the_second_red_escalates(failures)
    test_the_triad_escalates_after_two_red_gates(failures)
    test_cached_tokens_are_measured_and_cheaper(failures)
    return failures
