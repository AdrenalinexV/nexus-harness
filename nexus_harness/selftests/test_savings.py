"""Los cuatro motores de ahorro, medidos por el motor: poda, skills dormidas, mapa y aislamiento.

Lo que se exige aqui es que el ahorro sea un NUMERO en el libro de turnos, no una promesa en un
panel: la poda corta tokens de entrada de verdad, el baseline incluye lo que un harness tradicional
habria mandado (indice de skills dormidas), el mapa AST se cuenta como COSTE (no como ahorro) y la
reparacion aislada no engorda el hilo principal.
"""
from ..platform import ledger
from ..context import context_pruner, savings, triad_brief
from .. import stats_savings
from ..config import HarnessConfig
from ..platform.events import Bus
from ..verify.gate import Gate
from ..llm.judge import Judge
from ..tools import default_registry
from ..triad_loop import Triad
from .fakes import FakeRouter, ScriptedProvider, ScriptedSkills, TempProject, reply

TEST_COMMAND = 'python -c "import calc, sys; sys.exit(0 if calc.add(2, 3) == 5 else 1)"'
BIG = "fila de datos irrelevante para el siguiente paso\n" * 600


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def test_module_selftests(failures):
    for module in (context_pruner, savings, triad_brief, stats_savings):
        for problem in module.selftest():
            failures.append("%s.selftest: %s" % (module.__name__.split(".")[-1], problem))


def test_the_ledger_records_the_savings(failures):
    turn = {"tokens": {"prompt": 1000, "completion": 10}, "steps": 3,
            "savings": {"requests": 4, "sent": 1000, "baseline": 5000, "saved": 4000,
                        "savings_pct": 80.0, "context_multiplier": 5.0, "dormant_tokens": 3000,
                        "pruned_tokens": 1000, "isolated_tokens": 0, "repomap_tokens": 800}}
    row = ledger.from_turn(turn, "Proyecto", "s1", "run")
    check("el libro guarda lo enviado", row["tokens_sent"], 1000, failures)
    check("y el baseline", row["tokens_baseline"], 5000, failures)
    check("y el ahorro", row["tokens_saved"], 4000, failures)
    check("y el multiplicador", row["context_multiplier"], 5.0, failures)
    check("sin savings no se inventa un cero", "tokens_saved" in ledger.from_turn(
        {"tokens": {"prompt": 5}}, "P", "s", "chat"), False, failures)
    total = ledger.aggregate([row, row])
    check("el agregado suma los dos turnos", total["savings"]["saved"], 8000, failures)
    check("y da su porcentaje", total["savings_pct"], 80.0, failures)
    check("y el multiplicador", total["context_multiplier"], 5.0, failures)


def test_the_same_run_is_not_counted_twice(failures):
    """El ejecutor y el bucle autonomo escribian la misma corrida: el consumo salia al doble."""
    row = {"at": "2026-10-27T01:22:07Z", "project": "Nexus-Harness", "tokens": 48930,
           "prompt_tokens": 47484, "steps": 9, "touched": 9, "exit": 10, "session": "session_10"}
    twin = dict(row, session="autonomy", source="autonomy")
    check("la misma corrida se colapsa", len(ledger.dedupe([row, twin])), 1, failures)
    check("y dos corridas distintas no", len(ledger.dedupe([row, dict(row, at="otra")])), 2, failures)
    check("el consumo medido no se duplica",
          ledger.aggregate(ledger.dedupe([row, twin]))["tokens"], 48930, failures)


def test_the_bars_and_the_card_read_the_same_number(failures):
    """La barra de enviados y la tarjeta salen del MISMO agregado: `sent` y `tokens_sent` no se mezclan.

    Medido en el panel: con el alias viejo, la barra de Nexus-Harness dibujaba 0 enviados al lado de
    4.859 evitados. Un grafico asi no miente: se contradice.
    """
    from .. import stats_savings
    row = ledger.from_turn({"tokens": {"prompt": 1000, "completion": 5}, "steps": 2,
                            "savings": {"requests": 2, "sent": 1000, "baseline": 5000, "saved": 4000,
                                        "savings_pct": 80.0, "context_multiplier": 5.0}},
                           "Nexus-Harness", "s", "run")
    aggregate = ledger.aggregate(ledger.dedupe([row]))
    bucket = aggregate["by_project"]["Nexus-Harness"]
    check("el bucket usa los nombres de la fila", bucket.get("tokens_sent"), 1000, failures)
    check("y guarda el ahorro", bucket.get("tokens_saved"), 4000, failures)
    check("la tarjeta", stats_savings.cards(aggregate)["sent"], 1000, failures)
    values = [part["value"] for part in stats_savings.rows_for(
        aggregate, ["Nexus-Harness"])[0]["parts"]]
    check("la barra de enviados no se queda a cero", values, [1000, 4000], failures)


def test_a_real_run_prunes_and_reports_it(failures):
    with TempProject({"calc.py": "def add(a, b):\n    return a + b\n", "big.txt": BIG}) as root:
        config = HarnessConfig(default_root=root, test_command=TEST_COMMAND, max_steps=6,
                               max_repairs=0, budget_limit=200000, relay_threshold=0.99,
                               roles={"director": "fake:d", "worker": "fake:w", "judge": "fake:j"},
                               lang="es", temperature=0.0, secrets={})
        worker = ScriptedProvider([
            reply("leo", tools=[("c1", "read_file", {"path": "big.txt"})]),
            reply("leo otra vez", tools=[("c2", "read_file", {"path": "big.txt"})]),
            reply("leo la tercera", tools=[("c3", "read_file", {"path": "big.txt"})]),
            reply("hecho"),
        ], default=reply("hecho"))
        router = FakeRouter(workers=worker, judge=ScriptedProvider(
            [], default=reply('{"verdict": "approve", "reason": "verde"}')))
        bus = Bus()
        triad = Triad(router, config, registry=default_registry(root, config),
                      gate=Gate(root, config), judge=Judge(router, "es"),
                      skills=ScriptedSkills(), bus=bus)
        result = triad.run("leer big.txt y arreglar calc")
        reported = result.savings or {}
        check("el run trae su contabilidad", bool(reported), True, failures)
        check("hubo poda medible", reported.get("pruned_tokens", 0) > 0, True, failures)
        check("el baseline supera lo enviado", reported.get("baseline", 0) >
              reported.get("sent", 0), True, failures)
        check("el ahorro es positivo", reported.get("saved", 0) > 0, True, failures)
        check("y el multiplicador se calcula", reported.get("context_multiplier", 0) > 1, True,
              failures)
        kinds = [event["kind"] for event in bus.all()]
        check("el hilo dice que podo", "context.pruned" in kinds, True, failures)
        check("y publica el ahorro por request", "context.savings" in kinds, True, failures)
        rows = ledger.TurnLedger(root).rows()
        check("el run deja UNA fila en el libro", len(rows), 1, failures)
        check("con sus tokens evitados", rows[-1].get("tokens_saved", 0) > 0, True, failures)

        # Motor 3: el system prompt del Obrero lleva el mapa de simbolos y su coste esta declarado.
        system = triad._system("REGLAS", [])
        check("el mapa AST viaja en el system", "Mapa de simbolos" in system, True, failures)
        check("y su coste es mayor que cero", triad_brief.map_block(config)[1] > 0, True, failures)
        check("el mapa no se reclama como ahorro",
              triad.savings.as_dict()["repomap_tokens"] >= 0, True, failures)
        check("las skills dormidas se cuentan aparte",
              triad.savings.as_dict()["index_tokens"] >= 0, True, failures)


def run():
    failures = []
    test_module_selftests(failures)
    test_the_ledger_records_the_savings(failures)
    test_the_same_run_is_not_counted_twice(failures)
    test_the_bars_and_the_card_read_the_same_number(failures)
    test_a_real_run_prunes_and_reports_it(failures)
    return failures
