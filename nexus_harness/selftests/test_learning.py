"""Aprendizaje: el fallo repetido forja, el exito tras reparar ensena, y sin exit no se apunta nada.

Lo que se mide aqui es el reflejo, no la herramienta: `ForgeTrigger` y `skill_forge` ya existian y
nadie los llamaba desde el bucle. Un turno cerrado tiene que dejar algo medido en disco, y un turno sin
gate no puede dejar nada.
"""
import json
from pathlib import Path

from .fakes import TempProject
from .. import outcomes, reflection
from ..config import HarnessConfig


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


FAIL = {"name": "tests", "ok": False, "detail": "exit 1: AssertionError: add(2,3) != 5", "exit": 10}
OK = {"name": "tests", "ok": True, "detail": "exit 0", "exit": 0}


def test_three_failures_forge_one_skill(failures):
    with TempProject({"calc.py": "def add(a, b):\n    return a - b\n"}) as root:
        book = reflection.Reflection(root, threshold=3)
        files = ["calc.py"]
        first = book.after_turn(10, [FAIL], files, repairs=0, command="python -m pytest -q")
        second = book.after_turn(10, [FAIL], files, repairs=0, command="python -m pytest -q")
        check("un fallo no forja", first["forged"], [], failures)
        check("dos tampoco", second["forged"], [], failures)
        third = book.after_turn(10, [FAIL], files, repairs=0, command="python -m pytest -q")
        check("el tercero del mismo patron forja", len(third["forged"]), 1, failures)
        forged = third["forged"][0]
        check("la skill existe en disco", Path(forged["path"]).is_file(), True, failures)
        text = Path(forged["path"]).read_text(encoding="utf-8")
        check("lleva lo observado", "AssertionError" in text, True, failures)
        check("y el comando que prueba", "pytest" in text, True, failures)
        check("el contador sobrevive al proceso", reflection.Reflection(root).trigger.counts,
              book.trigger.counts, failures)
        fourth = book.after_turn(10, [FAIL], files, repairs=0)
        check("no se forja dos veces el mismo patron", fourth["forged"], [], failures)


def test_otros_fallos_no_suman(failures):
    with TempProject() as root:
        book = reflection.Reflection(root, threshold=3)
        book.after_turn(10, [dict(FAIL, detail="ModuleNotFoundError: rust crate")], ["a.rs"])
        book.after_turn(10, [dict(FAIL, detail="TypeError: tsx props")], ["b.tsx"])
        third = book.after_turn(10, [dict(FAIL, detail="ModuleNotFoundError: rust crate")], ["c.rs"])
        check("dos patrones distintos no son tres", third["forged"], [], failures)


def test_a_repair_leaves_a_lesson_the_planner_reads(failures):
    with TempProject() as root:
        book = reflection.Reflection(root)
        green = book.after_turn(0, [OK], ["calc.py"], repairs=1, judgement="approve",
                                command="python -m pytest -q", tag="run")
        check("el turno verde tras reparar deja leccion", bool(green.get("lesson")), True, failures)
        rows = reflection.lessons(root)
        check("la leccion se puede releer", len(rows), 1, failures)
        check("nombra el comando que probo", "pytest" in rows[0]["rule"], True, failures)
        block = reflection.lessons_block(root)
        check("el planificador la recibe", "Lecciones medidas" in block, True, failures)
        clean = book.after_turn(0, [OK], ["calc.py"], repairs=0)
        check("verde a la primera no inventa regla", "lesson" in clean, False, failures)


def test_without_an_exit_nothing_is_recorded(failures):
    with TempProject() as root:
        book = reflection.Reflection(root)
        result = book.after_turn(None, [FAIL], ["calc.py"], repairs=2)
        check("sin exit no se apunta", result["ok"], False, failures)
        check("ni leccion", reflection.lessons(root), [], failures)
        check("ni contadores", book.trigger.counts, {}, failures)


def test_the_turn_wiring_uses_the_real_payload(failures):
    """`learn()` lee el diccionario que devuelve el Chat, no una forma inventada."""
    with TempProject() as root:
        config = HarnessConfig(default_root=root, test_command="python -m pytest -q")
        payload = {"exit": 0, "touched": ["calc.py"], "repairs": 2,
                   "verdict": {"checks": [OK]}, "judgement": {"verdict": "approve"}}
        learned = reflection.learn(config, payload, "chat")
        check("saca la leccion del turno", bool(learned.get("lesson")), True, failures)
        check("y guarda el comando declarado", reflection.lessons(root)[0]["command"],
              "python -m pytest -q", failures)
        command = reflection.command_for(HarnessConfig(default_root=root))
        check("sin comando declarado se descubre el del repo", command, "", failures)


def test_outcomes_and_reflection_are_separate_books(failures):
    """Dos libros distintos: el de skills (que gana turnos) y el de lecciones (que se aprendio)."""
    with TempProject() as root:
        outcomes.Outcomes(root).record(["alpha"], 0, tag="test")
        reflection.Reflection(root).after_turn(0, [OK], ["a.py"], repairs=1, command="test")
        outcome_rows = json.loads((Path(root) / outcomes.REL).read_text(encoding="utf-8")
                                  .splitlines()[0])
        lesson_rows = reflection.lessons(root)
        check("el libro de skills tiene su fila", outcome_rows["skills"], ["alpha"], failures)
        check("el de lecciones tiene la suya", len(lesson_rows), 1, failures)


def run():
    failures = []
    test_three_failures_forge_one_skill(failures)
    test_otros_fallos_no_suman(failures)
    test_a_repair_leaves_a_lesson_the_planner_reads(failures)
    test_without_an_exit_nothing_is_recorded(failures)
    test_the_turn_wiring_uses_the_real_payload(failures)
    test_outcomes_and_reflection_are_separate_books(failures)
    return failures
