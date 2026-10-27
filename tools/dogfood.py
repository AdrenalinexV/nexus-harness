"""Dogfooding real: el bucle autonomo del arnes trabaja sobre el propio arnes.

    python tools/dogfood.py --iterations 3 --goal "auditar y mejorar..."

Lo que hace, en el orden que exige `autonomy.py`: backup -> plan (Director con la spec y el mapa AST)
-> triada (Obrero repara en worktree si el gate sale rojo) -> gate -> commit limpio -> progreso.

No es una simulacion: usa los modelos configurados (`lmstudio:...`), el mismo gate y el mismo juez que
un turno de produccion. Si un paso sale rojo, el bucle lo dice y se para en ese proyecto; lo que NO
hace es seguir afirmando que va bien.

La salida es JSON al final (una linea) y los eventos se imprimen en vivo con su tipo.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus_harness import autonomy, backup, projects, runner  # noqa: E402
from nexus_harness.config import HarnessConfig  # noqa: E402
from nexus_harness.events import Bus  # noqa: E402
from nexus_harness.providers import Router  # noqa: E402

PROJECT = "Nexus-Harness"
DEFAULT_GOAL = ("Audita y mejora la robustez de Nexus-Harness: un cambio pequeño, verificado por el "
                "gate (suite determinista + ley de 400), sin romper ninguna suite existente.")


def config_for_dogfood(iterations):
    config = HarnessConfig.load()
    tests = dict(config.project_tests or {})
    tests[PROJECT] = "python -m nexus_harness selftest"
    order = list(config.project_order or [])
    if PROJECT not in order:
        order.insert(0, PROJECT)
    config = HarnessConfig(**{**config.__dict__, "project_tests": tests, "project_order": order,
                              "max_steps": 18, "max_repairs": 1, "default_root": ROOT,
                              "budget_limit": max(int(config.budget_limit or 0), 120000),
                              "workspace": ROOT.parent})
    return config


def main(argv=None):
    parser = argparse.ArgumentParser(prog="dogfood")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--goal", default=DEFAULT_GOAL)
    parser.add_argument("--project", default=PROJECT)
    args = parser.parse_args(argv)

    config = config_for_dogfood(args.iterations)
    router = Router(config)
    for role in ("director", "worker", "judge"):
        info = router.info(role)
        if not info.ready:
            print(json.dumps({"ok": False, "reason": "%s no listo: %s" % (role, info.why_not_ready)}))
            return 20

    class PrintingBus(Bus):
        """El bus de verdad, con un `print` en cada evento: el log queda y la noche se puede leer."""

        def emit(self, kind, detail="", **payload):
            event = super().emit(kind, detail, **payload)
            print("  [%-18s] %s" % (kind, str(detail)[:140]), flush=True)
            return event

    bus = PrintingBus()
    seen = bus.all
    snap = backup.snapshot(ROOT, "dogfood")
    print("backup: %s (%s)" % (snap.get("kind"), snap.get("ref") or snap.get("reason")), flush=True)

    def run(goal, root):
        result, _triad = runner.run_triad(config, root, goal, router, bus=bus)
        return result.as_dict()

    ap = autonomy.Autopilot(config, runner=run,
                            planner=autonomy.model_planner(router, config),
                            bus=bus, snapshot=backup.snapshot)
    ok = ap._project(args.project, args.goal, max(1, int(args.iterations)))
    state = ap.state()
    progress = projects.progress(Path(config.workspace) / args.project)
    summary = {"ok": bool(ok) and not state.get("note"), "project": args.project,
               "iterations": state.get("iteration"), "steps_done": state.get("steps_done"),
               "last": state.get("last"), "note": state.get("note"),
               "backup": snap.get("kind"), "events": len(seen()),
               "steps": [{"ok": step.get("ok"), "step": str(step.get("step"))[:160],
                          "commit": step.get("commit")} for step in (progress.get("steps") or [])][-6:]}
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["ok"] else 10


if __name__ == "__main__":
    sys.exit(main())
