"""Spec sintetizada: el objetivo se convierte en comandos, y se valida ANTES de congelarse.

Lo que se mide aqui:
* un criterio sin comando no entra, y uno que revienta al lanzarse se descarta con su motivo;
* la spec dice que exit dio cada criterio hoy (evidencia, no promesa);
* una spec cuyos criterios ya pasan no se congela: no hay nada que construir;
* al fusionar, lo congelado no se pierde y el sha256 cambia solo si cambian los criterios.
"""
import json

from .fakes import FakeRouter, ScriptedProvider, TempProject, reply
from ..spec import spec_synth
from ..config import HarnessConfig
from ..projects import spec_of

RED = 'python -c "import sys; sys.exit(1)"'
GREEN = 'python -c "print(1)"'


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def candidates():
    return [spec_synth.Candidate("la funcion nueva existe", RED),
            spec_synth.Candidate("el proyecto importa", GREEN)]


def test_a_red_criterion_makes_the_spec_actionable(failures):
    with TempProject({"calc.py": "def add(a, b):\n    return a + b\n"}) as root:
        result = spec_synth.synthesize(root, "anade una funcion nueva", candidates=candidates(),
                                       write=True)
        check("hay criterios congelados", len(result["spec"]["cas"]), 2, failures)
        check("la spec es accionable", result["actionable"], True, failures)
        check("se escribio", result["written"], True, failures)
        check("el fichero existe", (root / ".ai" / "CURRENT_SPEC.json").is_file(), True, failures)
        check("cada criterio lleva su exit de hoy",
              [row["evidence"]["exit"] for row in result["spec"]["cas"]], [1, 0], failures)
        check("el sha cubre los criterios",
              result["spec"]["cas_sha256"], spec_synth._sha(result["spec"]["cas"]), failures)
        info = spec_of(root)
        check("el gobernador ve la spec", info["present"], True, failures)
        check("y cuenta sus criterios", info["criteria"], 2, failures)
        check("los ids son estables", [row["id"] for row in result["spec"]["cas"]],
              ["CA1", "CA2"], failures)


def test_a_green_spec_is_not_frozen(failures):
    with TempProject() as root:
        result = spec_synth.synthesize(root, "nada pendiente",
                                       candidates=[spec_synth.Candidate("ya pasa", GREEN)],
                                       write=True)
        check("no es accionable", result["actionable"], False, failures)
        check("no se escribe", result["written"], False, failures)
        check("y se explica", "ya pasan" in result["reason"], True, failures)
        check("no hay spec en disco", (root / ".ai" / "CURRENT_SPEC.json").is_file(), False,
              failures)
        forced = spec_synth.synthesize(root, "nada pendiente",
                                       candidates=[spec_synth.Candidate("ya pasa", GREEN)],
                                       write=True, force=True)
        check("con force si se congela", forced["written"], True, failures)


def test_a_command_that_cannot_run_is_dropped(failures):
    with TempProject() as root:
        broken = spec_synth.Candidate("roto", "comando-que-no-existe-xyz --flag")
        result = spec_synth.synthesize(root, "objetivo", candidates=[broken,
                                                                    spec_synth.Candidate("ok", GREEN)],
                                       write=True)
        check("el roto se descarta", len(result["dropped"]), 1, failures)
        check("y dice por que", bool(result["dropped"][0]["detail"]), True, failures)
        check("solo queda el bueno", len(result["spec"]["cas"]), 1, failures)


def test_a_destructive_command_is_refused(failures):
    with TempProject() as root:
        result = spec_synth.synthesize(root, "x", candidates=[
            spec_synth.Candidate("mata el disco", "rm -rf / --no-preserve-root"), ],
            config=HarnessConfig(default_root=root), write=True)
        check("la politica lo para", result["ok"], False, failures)
        check("y lo dice", "politica" in (result["dropped"][0]["detail"] if result["dropped"] else ""),
              True, failures)


def test_merging_never_weakens_the_frozen_spec(failures):
    with TempProject() as root:
        first = spec_synth.synthesize(root, "primera", candidates=[
            spec_synth.Candidate("viejo", GREEN)], write=True, force=True)
        old = json.loads((root / ".ai" / "CURRENT_SPEC.json").read_text(encoding="utf-8"))
        second = spec_synth.synthesize(root, "segunda", candidates=[
            spec_synth.Candidate("nuevo", RED)], write=True)
        cas = second["spec"]["cas"]
        check("el criterio viejo sigue", cas[0]["title"], "viejo", failures)
        check("y el nuevo entra", cas[1]["title"], "nuevo", failures)
        check("los ids no se repiten", len({row["id"] for row in cas}), 2, failures)
        check("el objetivo se actualiza", second["spec"]["goal"], "segunda", failures)
        check("el sha cambia con los criterios",
              second["spec"]["cas_sha256"] != old["cas_sha256"], True, failures)
        check("el id del proyecto se conserva", second["spec"]["id"], first["spec"]["id"], failures)


def test_the_director_proposes_and_the_harness_validates(failures):
    """Un criterio propuesto por el modelo se ejecuta igual: su opinion no congela nada."""
    with TempProject() as root:
        text = ('Claro, aqui tienes:\n```json\n{"cas": [{"title": "api responde", '
                '"command": "python -c \\"print(2)\\"", "expect_exit": 0}]}\n```')
        router = FakeRouter(director=ScriptedProvider([reply(text)]))
        result = spec_synth.synthesize(root, "monta la api", router=router, write=True)
        check("el criterio del director entra", len(result["spec"]["cas"]), 1, failures)
        check("con su exit medido", result["spec"]["cas"][0]["evidence"]["exit"], 0, failures)
        check("y su origen declarado", result["spec"]["cas"][0]["source"], "director", failures)


def test_a_negative_criterion_is_respected(failures):
    """`expect_exit: 1` es un criterio legitimo: un comando que DEBE fallar hoy."""
    with TempProject() as root:
        result = spec_synth.synthesize(root, "x", candidates=[
            spec_synth.Candidate("debe fallar", RED, expect_exit=1)], write=True, force=True)
        check("el criterio se cumple al fallar", result["actionable"], False, failures)
        check("y su exit es el esperado", result["spec"]["cas"][0]["expect_exit"], 1, failures)


def test_project_candidates_come_from_the_repo(failures):
    with TempProject({"pytest.ini": "[pytest]\n", "calc.py": "def add(a, b):\n    return a + b\n"}) as root:
        rows = spec_synth.project_candidates(root, HarnessConfig(default_root=root))
        check("descubre el test del repo", any("pytest" in row.command for row in rows), True,
              failures)
        check("y lo marca como detectado", rows[0].source, "pytest.ini", failures)


def run():
    failures = []
    test_a_red_criterion_makes_the_spec_actionable(failures)
    test_a_green_spec_is_not_frozen(failures)
    test_a_command_that_cannot_run_is_dropped(failures)
    test_a_destructive_command_is_refused(failures)
    test_merging_never_weakens_the_frozen_spec(failures)
    test_the_director_proposes_and_the_harness_validates(failures)
    test_a_negative_criterion_is_respected(failures)
    test_project_candidates_come_from_the_repo(failures)
    return failures
