"""El invariante de capas: una capa no puede mirar hacia arriba.

Una capa no es una carpeta con un nombre bonito: es una regla que un test puede romper. Se declara aqui
lo que YA esta migrado, y se exige exactamente eso:

* **lo declarado es lo real.** El set de modulos de cada carpeta es exacto: un fichero suelto es una capa
  sin duenno y un modulo declarado que no existe es un documento que miente.
* **nadie importa hacia su derecha.** Un modulo puede importar capas a su izquierda (y hermanos de la
  suya); importar una capa posterior -- o un modulo que sigue plano, que es arriba por definicion -- es un
  `file:line` con el import completo, no un contador.
* **y carga.** `importlib` sobre cada modulo declarado: un invariante de texto que no arranca el paquete
  no prueba nada del paquete.

Deliberadamente NO exige que el arbol entero este mapeado: una suite que lleva semanas roja por trabajo
pendiente se desactiva mucho antes de que la migracion acabe. El mapa crece con cada capa, y los planos
que quedan se cuentan en el plan, no se afirman aqui.
"""
import ast
import importlib
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]

# El orden es la ley: cada capa puede importar las de su izquierda, nunca las de su derecha.
ORDER = ("platform", "core", "llm", "tools", "context", "verify", "autonomy", "spec", "learning")
DECLARED = {
    "platform": ("backup", "events", "hardware_probe", "ledger", "policy", "tokenizer",
                 "transcripts", "vault"),
    "core": ("budget", "message", "outcomes", "tasks"),
}


def check(name, got, expect, failures):
    if got != expect:
        failures.append("%s: %r, esperaba %r" % (name, got, expect))


def modules_in(layer):
    return tuple(sorted(p.stem for p in (PKG / layer).glob("*.py") if p.stem != "__init__"))


def flat_modules():
    return {p.stem for p in PKG.glob("*.py")}


def package_of(path):
    return list(path.relative_to(PKG).with_suffix("").parts[:-1])


def resolve(node, path):
    """El modulo absoluto que importa `node`, visto desde `path` (`core.tasks`, `tools`, ...)."""
    level = node.level or 0
    package = package_of(path)
    base = package[:len(package) - (level - 1)] if level > 1 else package
    if node.module:
        return ".".join(base + node.module.split("."))
    return ""


def targets_of(node, path):
    """Los modulos destino de una sentencia de import (vacio si no apunta dentro del paquete)."""
    if isinstance(node, ast.Import):
        return [a.name[len("nexus_harness."):] for a in node.names if a.name.startswith("nexus_harness.")]
    if not isinstance(node, ast.ImportFrom):
        return []
    base = resolve(node, path)
    if node.module:
        return [base]
    return ["%s.%s" % (base, alias.name) if base else alias.name for alias in node.names]


def layer_of(module):
    head = module.split(".")[0] if module else ""
    return head if head in ORDER else None


def violations():
    """`['capa/fichero.py:12 importa tools (a la derecha)']` sobre el mapa declarado."""
    found, flat = [], flat_modules()
    for layer, names in DECLARED.items():
        for name in names:
            path = PKG / layer / (name + ".py")
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8", errors="replace"))):
                for target in targets_of(node, path):
                    other = layer_of(target)
                    where = "%s/%s.py:%s" % (layer, name, node.lineno)
                    if other is None:
                        if target.split(".")[0] in flat:
                            found.append("%s importa %r, que sigue plano (arriba)" % (where, target))
                    elif ORDER.index(other) > ORDER.index(layer):
                        found.append("%s importa %r, capa a la derecha" % (where, target))
    return found


def test_declared_is_real(failures):
    for layer, names in DECLARED.items():
        check("%s declara exactamente sus modulos" % layer, modules_in(layer),
              tuple(sorted(names)), failures)


def test_nobody_imports_upwards(failures):
    check("ninguna capa migrada importa hacia su derecha", violations(), [], failures)


def test_every_layer_loads(failures):
    broken = []
    for layer, names in DECLARED.items():
        for name in names:
            try:
                importlib.import_module("nexus_harness.%s.%s" % (layer, name))
            except Exception as exc:  # noqa: BLE001 -- un import roto es el hallazgo
                broken.append("%s.%s: %s: %s" % (layer, name, type(exc).__name__, exc))
    check("cada modulo declarado se importa", broken, [], failures)
    check("y el orden de capas empieza por platform", ORDER[0], "platform", failures)


def run():
    failures = []
    test_declared_is_real(failures)
    test_nobody_imports_upwards(failures)
    test_every_layer_loads(failures)
    return failures
