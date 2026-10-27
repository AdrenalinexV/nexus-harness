"""El oraculo: descubrir el runner del repo y no dar verde sin comportamiento ejecutado.

El falso verde que se cierra: sin `test_command`, el gate devolvia `ok=True, blocking=False` y un
proyecto sin pruebas salia "verde" habiendo comprobado solo lint y ley de 400. Aqui se exige que haya
algo ejecutado, y que cuando no se pueda probar se diga con el codigo del protocolo (20).
"""
from .fakes import TempProject
from .. import oracle
from ..config import HarnessConfig
from ..gate import EXIT_GREEN, EXIT_RED, EXIT_UNAVAILABLE, Gate


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def test_detects_the_runner_the_repo_already_has(failures):
    with TempProject({"pytest.ini": "[pytest]\n", "calc.py": "def add(a, b):\n    return a + b\n"}) as root:
        found = oracle.detect(root)
        check("ve pytest", found.get("command"), "python -m pytest -q", failures)
        check("y dice de donde lo saco", found.get("source"), "pytest.ini", failures)
    with TempProject({"package.json": '{"scripts": {"test": "jest"}}\n'}) as root:
        check("ve npm", oracle.detect(root).get("command"), "npm test --silent", failures)
    with TempProject({"package.json": '{"name": "x"}\n'}) as root:
        check("un package.json sin script no es un runner", oracle.detect(root), {}, failures)
    with TempProject({"Cargo.toml": "[package]\nname='x'\n"}) as root:
        check("ve cargo", oracle.detect(root).get("command"), "cargo test -q", failures)


def test_without_command_the_gate_runs_a_real_smoke(failures):
    with TempProject({"calc.py": "def add(a, b):\n    return a + b\n"}) as root:
        gate = Gate(root, HarnessConfig(default_root=root))
        verdict = gate.run(["calc.py"])
        names = [check_row.name for check_row in verdict.checks]
        check("el gate ejecuta comportamiento", "behavior" in names, True, failures)
        check("y sale verde porque el modulo importa", verdict.ok, True, failures)
        behavior = next(row for row in verdict.checks if row.name == "behavior")
        check("el detalle dice que se ejecuto", "importacion" in behavior.detail, True, failures)
        check("el gate deja su informe en disco",
              (root / ".nexus" / "harness" / "oracle.json").is_file(), True, failures)


def test_a_module_that_cannot_import_is_red(failures):
    with TempProject({"roto.py": "raise RuntimeError('boom al importar')\n"}) as root:
        verdict = Gate(root, HarnessConfig(default_root=root)).run(["roto.py"])
        check("un modulo que no importa es rojo", verdict.ok, False, failures)
        check("con el codigo del protocolo", verdict.exit, EXIT_RED, failures)
        check("y el motivo del fallo", "boom al importar" in verdict.failures, True, failures)


def test_only_docs_is_not_a_false_green_but_not_red_either(failures):
    with TempProject({"README.md": "# hola\n"}) as root:
        verdict = Gate(root, HarnessConfig(default_root=root)).run(["README.md"])
        tests = next(row for row in verdict.checks if row.name == "tests")
        check("sin ficheros de codigo no se inventa prueba", tests.blocking, False, failures)
        check("y el gate no finge haber probado", tests.exit, None, failures)


def test_cannot_verify_is_twenty_not_green(failures):
    with TempProject({"notas.txt": "nada\n"}) as root:
        # El turno dice haber tocado un .py que ya no existe: no hay nada que importar.
        verdict = Gate(root, HarnessConfig(default_root=root)).run(["no_existe.py"])
        check("no verificable no es verde", verdict.ok, False, failures)
        check("es 20, no 10", verdict.exit, EXIT_UNAVAILABLE, failures)
        check("y lo explica", "no verificable" in verdict.failures, True, failures)


def test_declared_command_still_wins(failures):
    with TempProject({"calc.py": "def add(a, b):\n    return a + b\n"}) as root:
        config = HarnessConfig(default_root=root,
                               test_command='python -c "import calc; assert calc.add(2,3)==5"')
        verdict = Gate(root, config).run(["calc.py"])
        tests = next(row for row in verdict.checks if row.name == "tests")
        check("el comando declarado manda", "declarado" in tests.detail, True, failures)
        check("y su exit es el verde", verdict.exit, EXIT_GREEN, failures)
        check("sin lanzar el humo", "behavior" in [row.name for row in verdict.checks], False,
              failures)


def run():
    failures = []
    test_detects_the_runner_the_repo_already_has(failures)
    test_without_command_the_gate_runs_a_real_smoke(failures)
    test_a_module_that_cannot_import_is_red(failures)
    test_only_docs_is_not_a_false_green_but_not_red_either(failures)
    test_cannot_verify_is_twenty_not_green(failures)
    test_declared_command_still_wins(failures)
    return failures
