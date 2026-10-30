"""Hooks: el contrato 0/10/20/30 en los cuatro puntos, y el gate obedeciéndolo.

Lo que se mide aquí no es "existe un fichero de configuración": es que un programa del usuario pueda
**parar el motor** (10), **dejarlo pasar** (0), **declararse no medible** (20) o **declararse no
aplicable** (30), y que el gate, el turno y el commit lo respeten. Un hook que solo se ejecuta y nadie
mira no es un punto de extensión: es un log.

Y se mide el fail-closed, que es la mitad que siempre falta: un `nexus_harness.toml` que existe y no se
puede leer **no** puede dejar al motor sin hooks en silencio — cada punto devuelve 20 con el motivo.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from ..platform import hooks as hooks_mod

# En una cadena literal de TOML las barras invertidas son LITERALES: un `%r` de una ruta de Windows las
# duplica y el comando deja de existir (exit 1, "no se pudo ejecutar"). Con barras normales, `%r` es
# seguro y además se lee.
PYTHON = sys.executable.replace("\\", "/")

HOOK = '''import json, sys
payload = json.loads(sys.stdin.read() or "{}")
data = payload.get("payload", {})
print("punto=%s proyecto=%s tool=%s" % (payload.get("point"), bool(payload.get("project")),
                                        data.get("tool", "-")))
sys.exit(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
'''


def _project(code, point="pre_verify", extra_toml=""):
    root = Path(tempfile.mkdtemp(prefix="nexus-hook-"))
    (root / "hook.py").write_text(HOOK, encoding="utf-8")
    (root / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    command = '"%s" hook.py %d' % (PYTHON, code)
    (root / hooks_mod.CONFIG_NAME).write_text(
        '[[hook]]\nat = "%s"\ncommand = %r\n%s' % (point, command, extra_toml), encoding="utf-8")
    return root


def _run(root, point="pre_verify", payload=None):
    return hooks_mod.Hooks.load(root, timeout=10).at(point, payload or {}, cwd=root)


def test_inert(failures):
    root = Path(tempfile.mkdtemp(prefix="nexus-hook-"))
    declared = hooks_mod.Hooks.load(root)
    if not declared.empty():
        failures.append("sin nexus_harness.toml el motor deberia estar inerte")
    if declared.at("pre_verify", {}, cwd=root) != []:
        failures.append("sin fichero, un punto no puede devolver nada")


def test_codes(failures):
    for code, expect_ok, verdict in ((0, True, "ok"), (10, False, "rojo"),
                                     (30, True, "no aplica")):
        root = _project(code)
        result = _run(root)[0]
        if result.code != code:
            failures.append("exit %d no llego: %r" % (code, result))
        if result.ok != expect_ok:
            failures.append("exit %d: ok=%r, esperaba %r" % (code, result.ok, expect_ok))
        if result.verdict != verdict:
            failures.append("exit %d: verdict=%r, esperaba %r" % (code, result.verdict, verdict))
        if "punto=pre_verify" not in result.message:
            failures.append("el hook no recibio el payload por stdin: %r" % result.message)


def test_unmeasured(failures):
    result = _run(_project(20))[0]
    if result.code != 20 or result.ok:
        failures.append("exit 20 debe ser 'no verificable' y parar: %r" % result)
    weird = _run(_project(7))[0]
    if weird.code != 20:
        failures.append("un codigo fuera del contrato (7) debe leerse como 20, no como %d" % weird.code)


def test_timeout(failures):
    root = Path(tempfile.mkdtemp(prefix="nexus-hook-"))
    (root / hooks_mod.CONFIG_NAME).write_text(
        '[[hook]]\nat = "pre_verify"\ncommand = %r\n' % ('"%s" -c "import time; time.sleep(5)"' % PYTHON),
        encoding="utf-8")
    result = hooks_mod.Hooks.load(root, timeout=1).at("pre_verify", {}, cwd=root)[0]
    if result.code != 20 or "timeout" not in result.message:
        failures.append("un hook que no termina debe ser 20 con 'timeout': %r" % result)


def test_broken_config(failures):
    root = Path(tempfile.mkdtemp(prefix="nexus-hook-"))
    (root / hooks_mod.CONFIG_NAME).write_text("[[hook]\nat = ", encoding="utf-8")
    declared = hooks_mod.Hooks.load(root)
    if not declared.error:
        failures.append("un toml roto no se reporta")
    for point in hooks_mod.POINTS:
        results = declared.at(point, {}, cwd=root)
        if len(results) != 1 or results[0].code != 20:
            failures.append("config rota: %s deberia dar 20 (fail-closed), dio %r" % (point, results))


def test_unknown_point(failures):
    root = Path(tempfile.mkdtemp(prefix="nexus-hook-"))
    (root / hooks_mod.CONFIG_NAME).write_text(
        '[[hook]]\nat = "antes_de_nada"\ncommand = "echo hola"\n', encoding="utf-8")
    declared = hooks_mod.Hooks.load(root)
    if "no es un punto" not in declared.error:
        failures.append("un `at` inventado no se rechaza: %r" % declared.error)
    if declared.at("pre_verify", {}, cwd=root)[0].code != 20:
        failures.append("con config invalida el gate debe ser 20, no seguir como si nada")


def test_gate_obeys(failures):
    """El criterio del roadmap: 10 → gate rojo, 0 → verde, 30 → no verificable, sin fichero → igual que hoy."""
    from ..verify.gate import Gate
    for code, expect in ((0, 0), (10, 10), (20, 20)):
        verdict = Gate(_project(code), timeout=30).run(touched=["calc.py"])
        if verdict.exit != expect:
            failures.append("hook %d -> gate exit %d, esperaba %d" % (code, verdict.exit, expect))
    neutral = Gate(_project(30), timeout=30).run(touched=["calc.py"])
    if neutral.exit != 0:
        failures.append("30 'no aplica' no puede cambiar el veredicto del gate: exit %d" % neutral.exit)
    inert = Path(tempfile.mkdtemp(prefix="nexus-hook-"))
    (inert / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    if Gate(inert, timeout=30).run(touched=["calc.py"]).exit != 0:
        failures.append("sin nexus_harness.toml el gate cambia de conducta")


def test_every_point_runs(failures):
    for point in hooks_mod.POINTS:
        root = _project(0, point=point)
        result = _run(root, point=point)[0]
        if result.code != 0 or ("punto=%s" % point) not in result.message:
            failures.append("%s no ejecuto su hook: %r" % (point, result))
        other = _run(root, point="pre_verify" if point != "pre_verify" else "before_turn")
        if other:
            failures.append("%s ejecuto tambien los hooks de otro punto" % point)


def test_commit_hook_stops(failures):
    """`before_commit` con 10 no deja commitear; con 0 sí. Se mide sobre un repo de verdad."""
    from ..autonomy.autonomy import _commit
    root = Path(tempfile.mkdtemp(prefix="nexus-hook-"))
    (root / "a.txt").write_text("hola\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
    ok, why = _commit(root, "base")
    if not ok:
        failures.append("el commit base del fixture fallo: %s" % why)
        return
    (root / "a.txt").write_text("adios\n", encoding="utf-8")
    (root / "hook.py").write_text(HOOK, encoding="utf-8")
    (root / hooks_mod.CONFIG_NAME).write_text(
        '[[hook]]\nat = "before_commit"\ncommand = %r\n'
        % ('"%s" hook.py 10' % PYTHON), encoding="utf-8")
    ok, why = _commit(root, "no deberia existir")
    if ok:
        failures.append("un hook before_commit que devuelve 10 no paro el commit")
    elif "hook" not in why:
        failures.append("el commit se paro pero no dijo por que: %s" % why)
    (root / hooks_mod.CONFIG_NAME).write_text(
        '[[hook]]\nat = "before_commit"\ncommand = %r\n'
        % ('"%s" hook.py 0' % PYTHON), encoding="utf-8")
    ok, why = _commit(root, "este si")
    if not ok:
        failures.append("un hook before_commit que devuelve 0 impidio el commit: %s" % why)


def run():
    failures = []
    test_inert(failures)
    test_codes(failures)
    test_unmeasured(failures)
    test_timeout(failures)
    test_broken_config(failures)
    test_unknown_point(failures)
    test_every_point_runs(failures)
    test_gate_obeys(failures)
    test_commit_hook_stops(failures)
    return failures
