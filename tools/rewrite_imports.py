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
    """El prefijo más largo del mapa que case, para no partir nombres por la mitad.

    Es **idempotente**: si el módulo ya empieza por el destino, se deja como está. Sin eso, una segunda
    pasada del mismo mapa convierte `nexus_harness.autonomy.autonomy` en `...autonomy.autonomy.autonomy`,
    que es cómo un rewrite 'repetible' deja de serlo.
    """
    for old in sorted(mapping, key=len, reverse=True):
        new = mapping[old]
        if module == new or module.startswith(new + "."):
            return module
        if module == old or module.startswith(old + "."):
            return new + module[len(old):]
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
        if isinstance(node, ast.Call):
            # `import_module("nexus_harness.lo_que_sea")` es una referencia real a un módulo escrita como
            # cadena. No se tocan cadenas en general (un docstring no es un import), pero esta forma sí:
            # dejarla apunta a un módulo que ya no existe y solo revienta en tiempo de ejecución.
            label = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
            if label in ("import_module", "__import__") and node.args:
                argument = node.args[0]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    target = retarget(argument.value, mapping)
                    if target != argument.value:
                        # La cadena puede estar en OTRA línea que la llamada (`import_module(` + salto).
                        row = argument.lineno - 1
                        new = lines[row].replace('"%s"' % argument.value, '"%s"' % target)
                        edits.append((row + 1, row + 1, new))
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = retarget(alias.name, mapping)
                if target == alias.name:
                    continue
                new = "import %s" % target + (" as %s" % alias.asname if alias.asname else "")
                edits.append((node.lineno, node.end_lineno, _indented(new, lines[node.lineno - 1])))
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        absolute_module = absolute(node, package)
        if absolute_module is None:
            continue
        base = retarget(absolute_module, mapping)
        groups = _groups(node, absolute_module, base, mapping)
        if base == absolute_module and all(module == base for module, _names in groups):
            continue  # nada de esta línea se muda: reconstruirla solo cambiaría el formato
        pieces = []
        for module, names in groups:
            if node.level:
                dots, rest = relative_from(package, module)
                pieces.append(statement(dots, rest, names))
            else:
                pieces.append(statement("", module, names))
        # Un import dentro de una funcion o un metodo lleva sangria, y `new` se construye sin ella:
        # soltarla al principio de linea rompe el bloque (IndentationError en el parseo de control).
        new = _indented("\n".join(pieces), lines[node.lineno - 1])
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


def _indented(new, first_line):
    """Devuelve `new` con la sangría de la línea original: un import dentro de un método la lleva."""
    indent = re.match(r"[ \t]*", first_line).group(0)
    return "\n".join(indent + row for row in new.splitlines()) if indent else new


def _groups(node, absolute_module, fallback, mapping):
    """Reparte los nombres de un `from X import a, b` por su módulo de destino.

    `from nexus_harness import plan_graph, projects` importa DOS módulos disfrazados de uno: si uno se
    muda y el otro no, la línea se parte en dos. Y en `from nexus_harness.autonomy import Autopilot` el
    nombre es una CLASE: el mapa solo casa si el nombre cuelga justo del paquete del que se importa.
    """
    groups, order = {}, []
    for alias in node.names:
        name = alias.name + (" as %s" % alias.asname if alias.asname else "")
        candidate = "%s.%s" % (absolute_module, alias.name) if absolute_module else alias.name
        parent = candidate.rpartition(".")[0]
        if parent == absolute_module and candidate in mapping:
            # `from pkg import modulo` NO importa un símbolo: importa el MÓDULO. Se emite desde su
            # paquete nuevo (`from pkg.capa import modulo`), no desde el fichero (`from ...modulo import
            # modulo`), que fallaría salvo que el módulo se llamara igual que algo de dentro.
            head, _, leaf = mapping[candidate].rpartition(".")
            module = head or mapping[candidate]
            name = leaf + (" as %s" % alias.asname if alias.asname else "")
        else:
            module = fallback
        if module not in groups:
            groups[module] = []
            order.append(module)
        groups[module].append(name)
    return [(module, groups[module]) for module in order]


def absolutize(path, apply_changes):
    """Convierte los relativos de UN fichero en absolutos, para que moverlo no rompa nada.

    Un import relativo dice «desde donde estoy»; si el fichero cambia de carpeta, cambia de significado
    en silencio (`from ..core.message` pasa a apuntar a otra parte). Absolutizar ANTES de mover deja el
    fichero indiferente a su ubicación, y el rewrite posterior solo renombra el prefijo.
    """
    text = path.read_text(encoding="utf-8")
    package = package_of(path)
    lines = text.splitlines()
    edits = []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.ImportFrom) or not node.level:
            continue
        absolute_module = absolute(node, package)
        if absolute_module is None:
            continue
        names = [alias.name + (" as %s" % alias.asname if alias.asname else "") for alias in node.names]
        new = _indented(statement("", absolute_module, names), lines[node.lineno - 1])
        old = "\n".join(lines[node.lineno - 1:node.end_lineno])
        if new != old:
            edits.append((node.lineno, node.end_lineno, new))
    if not edits:
        return 0
    for start, end, new in sorted(edits, reverse=True):
        lines[start - 1:end] = new.splitlines()
    result = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    ast.parse(result)
    if apply_changes:
        path.write_text(result, encoding="utf-8")
    print("%s %s (%d absolutos)" % ("reescrito" if apply_changes else "cambiaria",
                                    path.relative_to(ROOT), len(edits)))
    return len(edits)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="rewrite_imports")
    parser.add_argument("--map", action="append", default=[], metavar="VIEJO=NUEVO",
                        help="prefijo de modulo que cambia (repetible)")
    parser.add_argument("--absolutize", action="append", default=[], metavar="RUTA",
                        help="convierte los relativos de esta ruta en absolutos (antes de moverla)")
    parser.add_argument("--apply", action="store_true", help="escribe; sin esto solo informa")
    args = parser.parse_args(argv)
    if not args.map and not args.absolutize:
        parser.error("nada que hacer: usa --map y/o --absolutize")
    total = 0
    for target in args.absolutize:
        path = (ROOT / target).resolve()
        files = [path] if path.is_file() else sorted(path.rglob("*.py"))
        for file in files:
            if not any(part in SKIP for part in file.parts):
                total += absolutize(file, args.apply)
    if args.map:
        mapping = {}
        for row in args.map:
            old, _, new = row.partition("=")
            if not old or not new:
                parser.error("--map necesita VIEJO=NUEVO, no %r" % row)
            mapping[old] = new
        for path in sources():
            total += rewrite(path, mapping, args.apply)
    print("%s %d imports" % ("aplicados" if args.apply else "por aplicar", total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
