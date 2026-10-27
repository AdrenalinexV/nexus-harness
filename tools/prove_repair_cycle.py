"""Prueba del ciclo «rojo → reparado en el worktree → verde», con el modelo real.

    python tools/prove_repair_cycle.py [--steps 10] [--task "..."]
    python tools/prove_repair_cycle.py --fake      # mismo ciclo con modelos guionizados (determinista)

El escenario se construye para que el primer intento TENGA que fallar: el test comprueba dos funciones
(`add` y `mul`), el enunciado solo menciona una, y `mul` esta rota. El Obrero arregla lo que se le pide,
el gate sale ROJO por lo otro, y la reparacion tiene que ocurrir **dentro del worktree** (motor 4) para
que el turno termine en verde.

Lo que se mide y se imprime: si hubo `repair.sandbox.promoted`, si el gate final fue 0, cuantos tokens
quedaron fuera de la ventana principal (`repair.isolated`) y el resumen del run. Si algo de eso no
ocurre, se dice — no se redondea a verde.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus_harness import runner  # noqa: E402
from nexus_harness.config import HarnessConfig  # noqa: E402
from nexus_harness.events import Bus  # noqa: E402
from nexus_harness.providers import Router  # noqa: E402

PROJECT = "RepairCycle"
TASK = ("Arregla add en calc.py: tiene que devolver la suma. El test del proyecto es la prueba.")
FILES = {
    "calc.py": "def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b + 1\n",
    "app.py": "from calc import add\n\n\ndef total(rows):\n    return add(rows[0], rows[1])\n",
}
# El test mira LAS DOS funciones: el enunciado solo pide `add`, asi que el primer intento deja `mul`
# rota y el gate tiene que salir rojo antes de que el Obrero repare.
TEST_COMMAND = ('python -c "import calc, sys; sys.exit(0 if calc.add(2, 3) == 5 and '
                'calc.mul(2, 3) == 6 else 1)"')


def build(folder):
    root = Path(folder) / PROJECT
    root.mkdir(parents=True, exist_ok=True)
    for name, text in FILES.items():
        (root / name).write_text(text, encoding="utf-8")
    (root / ".gitignore").write_text(".nexus/\n", encoding="utf-8")
    for argv in (["init", "-q", "-b", "main"], ["add", "-A"],
                 ["-c", "user.name=repair", "-c", "user.email=repair@local", "commit", "-qm", "base"]):
        subprocess.run(["git", "-C", str(root)] + argv, capture_output=True, text=True)
    return root


def fake_router(config):
    """Router guionizado: primer intento arregla `add` y deja `mul`; la reparacion las deja las dos."""
    sys.path.insert(0, str(ROOT))
    from nexus_harness.selftests.fakes import FakeRouter, ScriptedProvider, reply
    bad = "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b + 1\n"
    good = "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n"
    worker = ScriptedProvider([
        reply("arreglo add", tools=[("c1", "write_file", {"path": "calc.py", "content": bad})]),
        reply("add arreglada"),
        reply("reparo mul tambien", tools=[("c2", "write_file", {"path": "calc.py",
                                                                "content": good})]),
        reply("listo"),
    ], default=reply("hecho"))
    judge = ScriptedProvider([], default=reply('{"verdict": "approve", "reason": "verde"}'))
    director = ScriptedProvider([], default=reply("1. arreglar calc.py"))
    return FakeRouter(workers=worker, judge=judge, director=director)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="prove_repair_cycle")
    parser.add_argument("--steps", type=int, default=10)
    parser.add_argument("--task", default=TASK)
    parser.add_argument("--fake", action="store_true", help="modelos guionizados, determinista")
    args = parser.parse_args(argv)

    config = HarnessConfig.load()
    config = HarnessConfig(**{**config.__dict__, "worktree_repairs": True, "nexus_engines": True,
                              "max_steps": args.steps, "max_repairs": 2,
                              "project_tests": {PROJECT: TEST_COMMAND}})
    router = fake_router(config) if args.fake else Router(config)
    if not args.fake:
        info = router.info("worker")
        if not info.ready:
            print(json.dumps({"ok": False, "reason": "worker no listo: %s" % info.why_not_ready}))
            return 20
    workspace = Path(tempfile.mkdtemp(prefix="nexus-repair-"))
    try:
        root = build(workspace)
        bus = Bus()
        local = HarnessConfig(**{**config.__dict__, "default_root": root, "test_command": TEST_COMMAND})
        result, _triad = runner.run_triad(local, root, args.task, router, bus=bus)
        kinds = [event["kind"] for event in bus.all()]
        promoted = [event for event in bus.all() if event["kind"] == "repair.sandbox.promoted"]
        verdicts = [str(event["detail"]) for event in bus.all() if event["kind"] == "gate.verdict"]
        summary = {"model": "guionizado" if args.fake else router.info("worker").model,
                   "exit": int(result.exit), "ok": bool(result.ok), "steps": int(result.steps),
                   "repairs": int(result.repairs),
                   "gate_verdicts": verdicts,
                   "sandbox_used": "repair.sandbox" in kinds,
                   "promoted": len(promoted),
                   "isolated_tokens": int((result.savings or {}).get("isolated_tokens") or 0),
                   "savings": dict(result.savings or {}),
                   "calc_final": (root / "calc.py").read_text(encoding="utf-8"),
                   "cycle": bool(promoted) and int(result.exit) == 0,
                   "note": ("modelos guionizados: el usage es inventado, asi que estas cifras de ahorro "
                            "NO se usan para afirmar nada; el ciclo si" if args.fake else "")}
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if summary["cycle"] else 10
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
