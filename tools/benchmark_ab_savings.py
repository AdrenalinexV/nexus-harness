"""Benchmark A/B del ahorro, en vivo y con el mismo codigo en los dos modos.

    python tools/benchmark_ab_savings.py --steps 8 [--vendor auto|local|deepseek] [--task ...]

**Modo A (tradicional)**: el motor con `nexus_engines = False`. El system prompt lleva el indice de
TODAS las skills instaladas, no se poda nada, no hay mapa AST y la reparacion ocurre en el hilo
principal. Es lo que hace un harness normal, medido con el mismo Obrero y el mismo modelo.

**Modo B (Nexus)**: los cuatro motores encendidos.

Lo que se compara no es una estimacion: los tokens de prompt de cada request son los que el proveedor
devuelve en su `usage` (o el contador determinista cuando el servidor local no informa). Se miden:

* tokens enviados en A vs B y su ahorro real;
* el prompt MAXIMO alcanzado (cuanto se alarga la vida de la ventana);
* coste en el modelo economico, en Claude y en GPT con los precios DECLARADOS, y el equivalente local
  (KV-cache y segundos de prefill).

El proveedor: `--vendor auto` usa DeepSeek si hay clave en la boveda o el entorno, y si no lo dice y
mide con el modelo local. Nunca inventa una llamada de nube que no puede hacer.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus_harness import backup, runner, stats_savings  # noqa: E402
from nexus_harness.config import HarnessConfig  # noqa: E402
from nexus_harness.events import Bus  # noqa: E402
from nexus_harness.providers import Router  # noqa: E402

PROJECT = "BenchAB"
DEFAULT_TASK = ("Lee los modulos del proyecto, encuentra el defecto de calc.py (add devuelve mal) y "
                "arreglalo. El test del proyecto tiene que pasar.")
FILES = {
    "calc.py": "def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n",
    "util.py": "import json\n\n\ndef load(path):\n    with open(path, encoding='utf-8') as handle:\n        return json.load(handle)\n",
    "report.py": "from calc import add\n\n\ndef total(rows):\n    return add(rows[0], rows[1])\n",
    "notes.md": "# Notas\n\nEl modulo de calculo tiene un defecto conocido en `add`.\n",
}
TEST_COMMAND = ('python -c "import calc, sys; sys.exit(0 if calc.add(2, 3) == 5 else 1)"')
OUT_JSON = ROOT / ".nexus" / "harness" / "benchmark_ab.json"
OUT_DOC = ROOT / "docs" / "BENCHMARK_AB.md"


def build_project(folder):
    """El proyecto de prueba, con git: sin repositorio no hay worktree y el motor 4 no se podria medir."""
    import subprocess
    root = Path(folder) / PROJECT
    root.mkdir(parents=True, exist_ok=True)
    for name, text in FILES.items():
        (root / name).write_text(text, encoding="utf-8")
    (root / ".gitignore").write_text(".nexus/\n", encoding="utf-8")
    for argv in (["init", "-q", "-b", "main"], ["add", "-A"],
                 ["-c", "user.name=bench", "-c", "user.email=bench@local", "commit", "-qm", "base"]):
        subprocess.run(["git", "-C", str(root)] + argv, capture_output=True, text=True)
    return root


def role_specs(vendor, config):
    """Las specs de rol para el vendor pedido, o `None` con el motivo de por que no se puede."""
    if vendor == "local":
        return dict(config.roles), "modelo local (lmstudio/ollama), sin coste de API"
    keys = ("DEEPSEEK_API_KEY", "OPENROUTER_API_KEY")
    found = next((name for name in keys if os.environ.get(name)), "")
    if not found:
        return None, ("no hay clave %s en el entorno ni en la boveda: se mide con el modelo local "
                      "(ponla en la boveda para el A/B en la nube)" % "/".join(keys))
    if vendor in ("auto", "deepseek") and os.environ.get("DEEPSEEK_API_KEY"):
        model = os.environ.get("NEXUS_HARNESS_BENCH_MODEL") or "deepseek-chat"
        return {role: "deepseek:%s" % model for role in ("director", "worker", "judge")}, \
            "deepseek:%s" % model
    model = os.environ.get("NEXUS_HARNESS_BENCH_MODEL") or "deepseek/deepseek-v4.1-flash"
    return {role: "openrouter:%s" % model for role in ("director", "worker", "judge")}, \
        "openrouter:%s" % model


def run_mode(root, config, router, task, steps, engines):
    """Una corrida de la triada en un modo. Devuelve la medida del ahorro y el resultado."""
    local = HarnessConfig(**{**config.__dict__, "nexus_engines": bool(engines),
                             "worktree_repairs": bool(engines), "max_steps": int(steps),
                             "max_repairs": 1, "default_root": root, "test_command": TEST_COMMAND})
    # El directorio se limpia entre modos: A y B tienen que partir del MISMO proyecto.
    (root / "calc.py").write_text(FILES["calc.py"], encoding="utf-8")
    bus = Bus()
    started = time.time()
    result, _triad = runner.run_triad(local, root, task, router, bus=bus)
    return {"engines": bool(engines), "ok": bool(result.ok), "exit": int(result.exit),
            "steps": int(result.steps), "repairs": int(result.repairs),
            "seconds": round(time.time() - started, 1),
            "tokens": dict(result.tokens or {}),
            "savings": dict(result.savings or {}),
            "events": len(bus.all()), "touched": list(result.touched or []),
            "summary": str(result.summary or "")[:300]}


def compare(a, b):
    """Las cifras del A/B, con el ahorro medido entre los dos modos (no contra una suposicion)."""
    sent_a = int((a.get("savings") or {}).get("sent") or 0)
    sent_b = int((b.get("savings") or {}).get("sent") or 0)
    peak_a = int((a.get("savings") or {}).get("peak_sent") or 0)
    peak_b = int((b.get("savings") or {}).get("peak_sent") or 0)
    steps_a = int(a.get("steps") or 0) or 1
    steps_b = int(b.get("steps") or 0) or 1
    return {"sent_a": sent_a, "sent_b": sent_b, "saved": max(0, sent_a - sent_b),
            "per_step_a": round(sent_a / float(steps_a), 1),
            "per_step_b": round(sent_b / float(steps_b), 1),
            "savings_pct": (round(100.0 * (sent_a - sent_b) / sent_a, 1) if sent_a else None),
            "peak_a": peak_a, "peak_b": peak_b,
            "peak_reduction_pct": (round(100.0 * (peak_a - peak_b) / peak_a, 1) if peak_a else None),
            "window_life_multiplier": (round(peak_a / float(peak_b), 2) if peak_b else None),
            "steps_a": a.get("steps"), "steps_b": b.get("steps"),
            "ok_a": a.get("ok"), "ok_b": b.get("ok")}


def cost_rows(savings, label):
    """Tabla de coste de UN modo, con la misma funcion que usa la pantalla."""
    aggregate = {"turns": 1, "savings": {"sent": savings.get("sent"), "baseline": savings.get("sent"),
                                         "saved": 0}, "savings_pct": 0.0}
    rows, _data = stats_savings.cost_table(aggregate)
    return {"label": label, "rows": [{"label": row["label"], "usd": row["value"]} for row in rows]}


def write_doc(payload):
    compare_rows = payload["compare"]
    lines = ["# Benchmark A/B del ahorro de contexto", "",
             "- fecha: %s" % payload["at"],
             "- modelo: %s" % payload["model"],
             "- tarea: %s" % payload["task"],
             "- pasos: %d · proyecto: `%s` (calc.py con un defecto real)" % (payload["steps"], PROJECT),
             "", "| medida | A (tradicional) | B (Nexus) | diferencia |", "|---|---|---|---|",
             "| tokens de prompt enviados | %s | %s | **%s%%** |" % (
                 payload["compare"]["sent_a"], payload["compare"]["sent_b"],
                 payload["compare"]["savings_pct"]),
             "| prompt maximo alcanzado | %s | %s | **%s%%** |" % (
                 payload["compare"]["peak_a"], payload["compare"]["peak_b"],
                 payload["compare"]["peak_reduction_pct"]),
             "| vida de la ventana | x1 | x%s | — |" % payload["compare"]["window_life_multiplier"],
             "| pasos | %s | %s | — |" % (payload["compare"]["steps_a"], payload["compare"]["steps_b"]),
             "| tokens por paso | %s | %s | **ver abajo** |" % (
                 payload["compare"].get("per_step_a"), payload["compare"].get("per_step_b")),
             "| gate verde | %s | %s | — |" % (payload["compare"]["ok_a"], payload["compare"]["ok_b"]),
             "", "## Ahorro del modo B por motor", "",
             "```json", json.dumps(payload["b"]["savings"], indent=2, ensure_ascii=False), "```",
             "", "## Coste extrapolado", "", "| modelo | A (USD) | B (USD) |", "|---|---|---|"]
    costs_a = {row["label"]: row["usd"] for row in payload["cost_a"]["rows"]}
    for row in payload["cost_b"]["rows"]:
        lines.append("| %s | %s | %s |" % (row["label"], costs_a.get(row["label"], "—"), row["usd"]))
    lines += ["", stats_savings.NOTE, "",
              "Modo A: `nexus_engines=False` (indice completo de skills, sin poda, sin mapa, reparacion "
              "en el hilo). Modo B: los cuatro motores. El mismo modelo y la misma tarea en los dos.",
              "",
              "**Limite declarado:** A y B no dan necesariamente el mismo numero de pasos, porque el "
              "modelo decide cuando parar y su contexto cambia entre modos. Por eso la tabla lleva los "
              "tokens POR PASO ademas del total: comparar solo el total premiaria al modo que se dio "
              "por vencido antes.",
              "", payload["vendor_note"]]
    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="benchmark_ab_savings")
    parser.add_argument("--doc-only", action="store_true",
                        help="regenera el informe desde la ultima medida guardada, sin volver a correr")
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--vendor", default="auto", choices=("auto", "local", "deepseek"))
    parser.add_argument("--task", default=DEFAULT_TASK)
    args = parser.parse_args(argv)

    if args.doc_only:
        payload = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        payload["compare"] = compare(payload["a"], payload["b"])
        write_doc(payload)
        print(json.dumps(payload["compare"], ensure_ascii=False))
        return 0
    config = HarnessConfig.load()
    specs, vendor_note = role_specs(args.vendor, config)
    if specs is None:
        specs, vendor_note = dict(config.roles), vendor_note
    config = HarnessConfig(**{**config.__dict__, "roles": specs, "project_tests":
                              {PROJECT: TEST_COMMAND}})
    router = Router(config)
    ready = {role: router.info(role).ready for role in ("director", "worker", "judge")}
    if not all(ready.values()):
        print(json.dumps({"ok": False, "reason": "roles no listos: %s" % ready,
                          "vendor_note": vendor_note}, ensure_ascii=False))
        return 20

    workspace = Path(tempfile.mkdtemp(prefix="nexus-bench-"))
    try:
        root = build_project(workspace)
        snap = backup.snapshot(root, "benchmark")
        print("modelo: %s · pasos %d · backup %s" % (vendor_note, args.steps, snap.get("kind")),
              flush=True)
        print("corriendo A (tradicional)…", flush=True)
        a = run_mode(root, config, router, args.task, args.steps, engines=False)
        print("corriendo B (Nexus)…", flush=True)
        b = run_mode(root, config, router, args.task, args.steps, engines=True)
        payload = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "model": vendor_note, "vendor_note": vendor_note, "task": args.task,
                   "steps": args.steps, "a": a, "b": b, "compare": compare(a, b),
                   "cost_a": cost_rows(a["savings"], "A"), "cost_b": cost_rows(b["savings"], "B")}
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        write_doc(payload)
        print(json.dumps(payload["compare"], ensure_ascii=False))
        print("informe: %s" % OUT_DOC)
        return 0
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
