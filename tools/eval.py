"""`python tools/eval.py` — cuantas tareas golden resuelve el harness, y con que modelo.

    python tools/eval.py --fake                 # determinista, CI, sin modelo ni red
    python tools/eval.py --model lmstudio:kat-coder
    python tools/eval.py --tasks fix-subtraction over-400-is-rejected
    python tools/eval.py --json | --write docs/EVAL.md

Salida: exit 0 si todas pasan, 10 si alguna falla, 1 si los argumentos no valen. En modo real hay una
tarea por llamada al modelo: no es un benchmark de tokens, es una tabla de aciertos.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus_harness import evalgym  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(prog="eval")
    parser.add_argument("--fake", action="store_true", help="modelo guionizado (por defecto)")
    parser.add_argument("--model", default=None, help="spec real, p. ej. lmstudio:kat-coder")
    parser.add_argument("--tasks", nargs="*", default=None, help="ids concretos")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write", default=None, help="escribe la tabla markdown en esa ruta")
    args = parser.parse_args(argv)

    payload = evalgym.run(names=args.tasks, model=args.model)
    if payload["missing"]:
        print("tareas desconocidas: %s" % ", ".join(payload["missing"]), file=sys.stderr)
    table = evalgym.render_markdown(payload)
    if args.write:
        Path(args.write).write_text("# Eval del harness\n\n" + table + "\n", encoding="utf-8")
        print("escrito %s" % args.write)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        for row in payload["rows"]:
            print("%-4s %-26s exit %s/%s  pasos=%s reparaciones=%s"
                  % ("OK" if row["ok"] else "FAIL", row["id"], row["exit"], row["expect_exit"],
                     row["steps"], row["repairs"]))
            for reason in row["reasons"]:
                print("     - %s" % reason)
        print("\n%s" % table.splitlines()[-1])
    return 0 if payload["ok"] else 10


if __name__ == "__main__":
    sys.exit(main())
