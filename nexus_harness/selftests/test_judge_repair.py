"""Juez con contexto, pista de reparacion al segundo fallo y razonamiento plegable.

Cuatro cosas que un harness serio tiene que demostrar y que hasta ahora no estaban:

* un turno de solo lectura se juzga como CONVERSACION (utilidad), no como codigo (diff): exigir edicion
  en una consulta convierte cada pregunta correcta en un rechazo;
* un turno con ficheros se juzga como CODIGO, con la evidencia del gate delante;
* el mismo parche fallando DOS veces recibe las lineas REALES del fichero, numeradas;
* la pildora de actividad cuenta el relevo, la poda y la skill forjada (lo que el operador ve).
"""
from .. import activity, repair_hint
from ..judge import CONVERSATION, SYSTEM, Judge, mode_for, parse_verdict
from ..message import Message, as_text
from ..tools import default_registry
from .fakes import FakeRouter, ScriptedProvider, TempProject, reply


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def _router(script):
    return FakeRouter(judge=ScriptedProvider(list(script), default=reply(
        '{"verdict": "approve", "reason": "ok"}')))


def test_modes(failures):
    check("sin ficheros ni gate es conversacion", mode_for([], "", False), "conversation", failures)
    check("con un fichero es codigo", mode_for(["a.py"], "", False), "code", failures)
    check("con gate ejecutado es codigo", mode_for([], "lint: ok", True), "code", failures)
    check("una evidencia real de gate cuenta", mode_for([], "line_law: ok", False), "code", failures)
    check("'no gate' explicito no es codigo", mode_for([], "(no gate run)", False), "conversation",
          failures)
    check("modo conversacion por defecto", mode_for([], "", False), "conversation", failures)


def test_a_reasoning_model_with_dirty_json_is_still_read(failures):
    """Un juez que razona antes de contestar ensucia el JSON; el veredicto no se puede perder por eso."""
    from ..judge import parse_verdict
    check("dos objetos: gana el que parsea",
          parse_verdict("pienso {esto no es json} y luego {\"verdict\": \"approve\", \"reason\": "
                        "\"util\"}")[0], "approve", failures)
    check("coma final tolerada",
          parse_verdict('{"verdict": "approve", "reason": "ok",}')[0], "approve", failures)
    check("comillas curvas toleradas",
          parse_verdict('{\u201cverdict\u201d: \u201capprove\u201d}')[0], "approve", failures)
    check("truncado pero explicito se lee",
          parse_verdict('{"verdict": "approve"')[0], "approve", failures)
    check("sin JSON y sin veredicto NO se aprueba",
          parse_verdict("me parece bien el trabajo")[0], "reject", failures)
    check("un reject explicito sigue siendo reject",
          parse_verdict('{"verdict": "reject", "reason": "falta"}')[0], "reject", failures)


def test_judge_uses_the_right_system_prompt(failures):
    router = _router([reply('{"verdict": "approve", "reason": "util"}')])
    judge = Judge(router, "es")
    verdict = judge.review("¿qué hace este repo?", "lo hace bien", [], "(no gate run)")
    check("la conversacion se aprueba", verdict.verdict, "approve", failures)
    check("y se marca como conversacion", verdict.mode, "conversation", failures)
    sent = router.role("judge").calls[-1]["messages"][0]["content"]
    check("el system es el de conversacion", sent, CONVERSATION["es"], failures)
    check("el JSON del juez no se rompe por el modo", "verdict" in verdict.as_dict(), True, failures)

    router = _router([reply('{"verdict": "approve", "reason": "verde"}')])
    verdict = Judge(router, "es").review("arregla calc", "hecho", ["calc.py"], "tests: ok")
    check("con ficheros es modo codigo", verdict.mode, "code", failures)
    check("y usa el system de codigo", router.role("judge").calls[-1]["messages"][0]["content"],
          SYSTEM["es"], failures)


def test_second_failure_gets_the_real_lines(failures):
    with TempProject({"calc.py": "def add(a, b):\n    return a - b\n"}) as root:
        registry = default_registry(root)
        bad = {"path": "calc.py", "old_string": "def multiply(a, b):\n    return a * b",
               "new_string": "def multiply(a, b):\n    return a * b"}
        first = registry.call("patch_replace", bad)
        check("el primer fallo no trae pista", "[reparacion]" in first.text, False, failures)
        second = registry.call("patch_replace", bad)
        delivered = as_text(second)
        check("el segundo trae pista", "[reparacion]" in delivered, True, failures)
        check("la pista es numerada", "   2 |     return a - b" in delivered, True, failures)
        check("y nombra el fichero", "calc.py" in delivered, True, failures)
        check("as_text la entrega al modelo", delivered.startswith("ERROR:"), True, failures)
        good = registry.call("write_file", {"path": "calc.py", "content": "VALUE = 1\n"})
        check("un write correcto limpia el contador", good.ok, True, failures)
        check("y el contador se vacia", registry.hints.counts, {}, failures)
    check("el modulo se prueba a si mismo", repair_hint.selftest(), [], failures)


def test_the_pill_reports_the_new_events(failures):
    phase, glyph, text = activity._phase_line({"kind": "session.relay",
                                               "detail": "session_01 -> session_02"}, None)
    check("el relevo se ve", (phase, glyph), ("relay", "🔄"), failures)
    check("y dice a donde va", "session_02" in text, True, failures)
    phase, glyph, _text = activity._phase_line({"kind": "context.pruned", "detail": "3 salidas"}, None)
    check("la poda se ve", (phase, glyph), ("compacting", "🧹"), failures)
    _phase, glyph, text = activity._phase_line(
        {"kind": "tool.call", "detail": "forge_or_update_skill"}, None)
    check("la skill forjada se ve", glyph, "🧠", failures)
    check("y lo dice", "auto-forjada" in text, True, failures)


def test_the_judge_sees_the_change_not_just_the_names(failures):
    """Un renombrado correcto fue rechazado porque el juez solo veia nombres: ahora ve el contenido."""
    import tempfile
    from pathlib import Path
    from ..judge import Judge
    from .fakes import FakeRouter

    with tempfile.TemporaryDirectory(prefix="judge-evidence-") as workspace:
        root = Path(workspace)
        (root / "calc.py").write_text("def suma(a, b):" + chr(10) + "    return a + b" + chr(10),
                                      encoding="utf-8")
        (root / "big.py").write_text(("x = 1" + chr(10)) * 5000, encoding="utf-8")
        judge = Judge(FakeRouter(), "es")
        prompt = judge._prompt("renombra add a suma", "hecho", ["calc.py"], "tests: exit 0",
                               judge._evidence(root, ["calc.py"]))
        check("el contenido viaja", "def suma" in prompt, True, failures)
        check("y se declara que es el estado actual", "Contenido actual" in prompt, True, failures)
        huge = judge._evidence(root, ["big.py"], chars=200)
        check("el contenido se recorta", len(huge) < 400, True, failures)
        check("sin raiz no hay evidencia", judge._evidence(None, ["calc.py"]), "", failures)


def test_a_bare_word_is_a_verdict_and_format_gets_one_retry(failures):
    """`Approved.` es un veredicto; y un formato roto tiene UN reintento antes de condenar."""
    from .fakes import FakeRouter, ScriptedProvider, reply

    check("aprobado a secas", parse_verdict("Approved.")[0], "approve", failures)
    check("rechazo a secas", parse_verdict("Reject")[0], "reject", failures)
    check("una frase suelta no es veredicto", parse_verdict("looks fine to me")[0], "reject",
          failures)

    import tempfile
    with tempfile.TemporaryDirectory(prefix="judge-retry-") as workspace:
        from pathlib import Path
        root = Path(workspace)
        (root / "calc.py").write_text("x = 1", encoding="utf-8")
        router = FakeRouter(judge=ScriptedProvider([
            reply("Looks good to me, job done."),
            reply('{"verdict": "approve", "reason": "el contenido lo demuestra"}')]))
        judgement = Judge(router, "es").review("arregla", "hecho", ["calc.py"], "tests: exit 0",
                                               root=root)
        check("el reintento aprueba", judgement.verdict, "approve", failures)
        check("y dice por que", "contenido" in judgement.reason, True, failures)

        broken = FakeRouter(judge=ScriptedProvider([reply("prosa"), reply("mas prosa")],
                                                   default=reply("prosa")))
        second = Judge(broken, "es").review("arregla", "hecho", ["calc.py"], "tests: exit 0",
                                            root=root)
        check("dos fallos de formato si rechazan", second.verdict, "reject", failures)
        check("y se declara", "segundo intento" in second.reason, True, failures)


def run():
    failures = []
    test_modes(failures)
    test_a_reasoning_model_with_dirty_json_is_still_read(failures)
    test_judge_uses_the_right_system_prompt(failures)
    test_second_failure_gets_the_real_lines(failures)
    test_the_pill_reports_the_new_events(failures)
    test_the_judge_sees_the_change_not_just_the_names(failures)
    test_a_bare_word_is_a_verdict_and_format_gets_one_retry(failures)
    return failures
