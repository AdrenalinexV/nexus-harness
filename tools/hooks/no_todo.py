"""Hook de ejemplo: falla si lo que el turno tocó deja un TODO nuevo. Cópialo y adáptalo.

    [[hook]]
    at = "pre_verify"
    command = 'python tools/hooks/no_todo.py'

Contrato (lo mismo que cualquier hook, ver `docs/HOOKS.md`): JSON por stdin, una línea por stdout y un
código de salida que significa 0 pasó / 10 rojo / 20 no se pudo medir / 30 no aplica.
"""
import json
import os
import sys

# Palabras que un turno no debería dejar atrás. En minúsculas porque el fichero se lee tal cual.
DEBT = ("todo:", "fixme:", "xxx:", "hack:")


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    touched = (payload.get("payload") or {}).get("touched") or []
    project = payload.get("project") or "."
    here = os.path.abspath(__file__)
    hits = []
    for name in touched:
        path = os.path.abspath(os.path.join(project, name))
        if path == here:
            continue  # este fichero CONTIENE las palabras que busca: se excluye, o se denuncia a sí mismo
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                for number, line in enumerate(handle, 1):
                    if any(word in line.lower() for word in DEBT):
                        hits.append("%s:%d %s" % (name, number, line.strip()[:80]))
        except OSError:
            continue  # un fichero que ya no está no es deuda: es un borrado
    if hits:
        print("deuda declarada en %d linea(s): %s" % (len(hits), "; ".join(hits[:3])))
        return 10
    print("sin deuda nueva en %d fichero(s)" % len(touched))
    return 0


if __name__ == "__main__":
    sys.exit(main())
