"""Aislamiento del Obrero y mapa AST: el arbol principal solo cambia cuando el gate ya salio verde.

La prueba de la reparacion no es "se creo un worktree", es el ciclo entero con el motor real:

1. el primer intento escribe en el arbol principal y deja el gate ROJO;
2. el Obrero repara DENTRO del worktree (`worktree_repairs=True`) y ahi el gate sale verde;
3. solo entonces los ficheros se copian y el run termina en verde;
4. si el worktree no sale verde, el arbol principal queda exactamente igual.

El mapa AST se mide con su cache: no se reconstruye si nada cambio, y se invalida al tocar un fichero.
"""
import subprocess

from .. import repair_guard, repo_map, worktree_sandbox
from ..config import HarnessConfig
from ..platform.events import Bus
from ..gate import Gate
from ..judge import Judge
from ..tools import default_registry
from ..triad_loop import Triad
from .fakes import FakeRouter, ScriptedProvider, ScriptedSkills, TempProject, reply

TEST_COMMAND = ('python -c "import calc, sys; sys.exit(0 if calc.add(2, 3) == 5 else 1)"')
BAD = "def add(a, b):\n    return a - b\n"
GOOD = "def add(a, b):\n    return a + b\n"


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t"]
                          + list(args), capture_output=True, text=True, errors="replace")


def test_module_selftests(failures):
    for problem in worktree_sandbox.selftest():
        failures.append("worktree_sandbox.selftest: %s" % problem)
    for problem in repo_map.selftest():
        failures.append("repo_map.selftest: %s" % problem)
    for problem in repair_guard.selftest():
        failures.append("repair_guard.selftest: %s" % problem)


def _config(root, **extra):
    base = dict(default_root=root, test_command=TEST_COMMAND, max_steps=3, max_repairs=1,
                budget_limit=200000, relay_threshold=0.99,
                roles={"director": "fake:d", "worker": "fake:w", "judge": "fake:j"},
                lang="es", temperature=0.0, secrets={})
    base.update(extra)
    return HarnessConfig(**base)


def test_repair_in_worktree(failures):
    with TempProject({"calc.py": BAD}) as root:
        git(root, "init", "-q", "-b", "main")
        (root / ".gitignore").write_text(".nexus/\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "base")
        config = _config(root, worktree_repairs=True)
        worker = ScriptedProvider([
            reply("escribo el arreglo", tools=[("c1", "write_file",
                                                {"path": "calc.py", "content": BAD})]),
            reply("ya esta"),
            reply("reparo en el sandbox", tools=[("c2", "write_file",
                                                 {"path": "calc.py", "content": GOOD})]),
            reply("reparado"),
        ], default=reply("hecho"))
        router = FakeRouter(workers=worker, judge=ScriptedProvider(
            [], default=reply('{"verdict": "approve", "reason": "verde"}')))
        bus = Bus()
        triad = Triad(router, config, registry=default_registry(root, config),
                      gate=Gate(root, config), judge=Judge(router, "es"),
                      skills=ScriptedSkills(), bus=bus)
        result = triad.run("arreglar calc.add")
        kinds = [event["kind"] for event in bus.all()]
        check("el run termina verde", result.ok, True, failures)
        check("hubo una reparacion", result.repairs, 1, failures)
        check("el sandbox se uso", "repair.sandbox" in kinds, True, failures)
        check("y lo promovido se dijo", "repair.sandbox.promoted" in kinds or
              "repair.sandbox.red" in kinds, True, failures)
        check("el arbol principal tiene el arreglo",
              (root / "calc.py").read_text(encoding="utf-8"), GOOD, failures)
        left = list((root / worktree_sandbox.BASE_REL).glob("*")) if (
            root / worktree_sandbox.BASE_REL).is_dir() else []
        check("no queda basura de worktrees", left, [], failures)
        check("no quedan ramas de sandbox",
              git(root, "branch", "--list", "nexus/sandbox/*").stdout.strip(), "", failures)


def test_a_red_sandbox_never_touches_the_tree(failures):
    with TempProject({"calc.py": BAD}) as root:
        git(root, "init", "-q", "-b", "main")
        (root / ".gitignore").write_text(".nexus/\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-qm", "base")
        sandbox = worktree_sandbox.Sandbox(root, name="rojo",
                                           gate='python -c "raise SystemExit(1)"')
        result = sandbox.attempt(lambda path: (path / "calc.py").write_text(GOOD,
                                                                           encoding="utf-8"))
        check("el gate rojo no promueve", result["ok"], False, failures)
        check("el arbol principal no cambia", (root / "calc.py").read_text(encoding="utf-8"), BAD,
              failures)


def run():
    failures = []
    test_module_selftests(failures)
    test_repair_in_worktree(failures)
    test_a_red_sandbox_never_touches_the_tree(failures)
    return failures
