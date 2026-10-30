"""Reescribe imports con AST cuando un módulo cambia de casa, y dice qué tocó.

    python tools/rewrite_imports.py --map nexus_harness.transports=nexus_harness.llm.transports
    python tools/rewrite_imports.py --map ... --apply

**Por qué no `sed`.** Un `grep -r | sed` cambia también las cadenas dentro de un docstring, los nombres
de un `__all__` y las menciones de un mensaje de error; y con imports relativos (`from ..transports
import http`) no acierta sin saber en qué paquete vive cada fichero. Aquí se parsea, se resuelve cada
`from … import …` a su módulo ABSOLUTO, se aplica el prefijo más largo que case y se reconstruye el
import **en el mismo estilo** del original: relativo si lo era, con sus alias y su orden.

Lo que este script no hace, a propósito: mover ficheros (eso es `git mv`, en el commit del paso) y
adivinar. Si un import no resuelve, lo cuenta como `sin resolver` y no lo toca.
"""
import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = ("build", ".build", "__pycache__", ".git", "dist", "node_modules", ".nexus")


def sources():
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP for part in path.parts):
            continue
        yield path


def package_of(path):
    """El paquete que CONTIENE al fichero, en forma dotted (`nexus_harness.llm`), o "" en la raíz."""
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts[:-1])
    return ".".join(parts)


def absolute(node, package):
    if node.level == 0:
        return node.module or ""
    parts = package.split(".") if package else []
    keep = len(parts) - (node.level - 1)
    if keep < 0:
        return None  # un relativo que se sale del árbol: no es cosa de este script
    base = ".".join(parts[:keep])
    return ".".join(filter(None, [base, node.module or ""]))


def retarget(module, mapping):
    """El prefijo más largo del mapa que case, para no partir nombres por la mitad."""
    for old in sorted(mapping, key=len, reverse=True):
        if module == old or module.startswith(old + "."):
            return mapping[old] + module[len(old):]
    return module


def relative_from(package, target):
    """(puntos, resto) para escribir `from <puntos><resto> import …` desde `package`."""
    here = package.split(".") if package else []
    there = target.split(".") if target else []
    common = 0
    while common < len(here) and common < len(there) and here[common] == there[common]:
        common += 1
    rest = there[common:]
    # De `package` a `target`: un punto por cada nivel que se sube, mas el punto que abre el paquete.
    #   nexus_harness.llm          -> nexus_harness.llm.transports   = "."
    #   nexus_harness.llm.transports -> nexus_harness.core.message   = "..."
    dots = "." * (len(here) - common + 1)
    return dots, ".".join(rest)


def statement(dots, module, names):
    """Reconstruye el import en una línea, o en bloque si no cabe. Alias y orden se conservan."""
    head = "from %s%s" % (dots, module)
    line = "%s import %s" % (head, ", ".join(names))
    if len(line) <= 100:
        return line
    return "%s import (\n%s\n)" % (head, "\n".join("    %s," % name for name in names))


def rewrite(path, mapping, apply_changes):
    text = path.read_text(encoding="utf-8")
    package = package_of(path)
    tree = ast.parse(text)
    lines = text.splitlines()
    edits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        absolute_module = absolute(node, package)
        if absolute_module is None:
            continue
        target = retarget(absolute_module, mapping)
        if target == absolute_module:
            continue
        names = [alias.name + (" as %s" % alias.asname if alias.asname else "") for alias in node.names]
        if node.level:
            dots, rest = relative_from(package, target)
            new = statement(dots, rest, names)
        else:
            new = statement("", target, names)
        # Un import dentro de una funcion o un metodo lleva sangria, y `new` se construye sin ella:
        # soltarla al principio de linea rompe el bloque (IndentationError en el parseo de control).
        indent = re.match(r"[ \t]*", lines[node.lineno - 1]).group(0)
        if indent:
            new = "\n".join(indent + row for row in new.splitlines())
        old = "\n".join(lines[node.lineno - 1:node.end_lineno])
        if new != old:
            edits.append((node.lineno, node.end_lineno, new))
    if not edits:
        return 0
    for start, end, new in sorted(edits, reverse=True):
        lines[start - 1:end] = new.splitlines()
    result = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    ast.parse(result)  # si el rewrite rompe la sintaxis, revienta aqui y no en el gate
    if apply_changes:
        path.write_text(result, encoding="utf-8")
    print("%s %s (%d)" % ("reescrito" if apply_changes else "cambiaria", path.relative_to(ROOT), len(edits)))
    return len(edits)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="rewrite_imports")
    parser.add_argument("--map", action="append", required=True, metavar="VIEJO=NUEVO",
                        help="prefijo de modulo que cambia (repetible)")
    parser.add_argument("--apply", action="store_true", help="escribe; sin esto solo informa")
    args = parser.parse_args(argv)
    mapping = {}
    for row in args.map:
        old, _, new = row.partition("=")
        if not old or not new:
            parser.error("--map necesita VIEJO=NUEVO, no %r" % row)
        mapping[old] = new
    total = 0
    for path in sources():
        total += rewrite(path, mapping, args.apply)
    print("%s %d imports" % ("aplicados" if args.apply else "por aplicar", total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
