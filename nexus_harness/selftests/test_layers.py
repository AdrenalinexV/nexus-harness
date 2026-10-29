"""El invariante de capas: `platform/` no puede mirar hacia arriba.

Una capa no es una carpeta con un nombre bonito: es una regla que un test puede romper. Esta suite mide
la primera y la mas barata de todas -- la hoja -- y sirve de plantilla para las que faltan:

* **platform importa solo platform.** Nada de `from ..config`, ni `from . import message`, ni
  `nexus_harness.chat`. Si la capa de abajo mira hacia arriba, la migracion no ha terminado aunque los
  tests pasen: es un alias con burocracia.
* **lo declarado es lo que hay.** El set de modulos de `platform/` es exacto: un fichero suelto ahi es
  una capa sin duenno, y un modulo declarado que no existe es un documento que miente.
* **y se puede importar.** Un invariante de texto que no arranca el paquete no prueba que el paquete
  cargue; se importan los modulos declarados uno a uno.

Deliberadamente NO exige que el resto del arbol ya este por capas: eso es el paso 2, y una suite que se
pone roja durante semanas por trabajo pendiente se acaba desactivando. Cuando el arbol entero este
mapeado, la lista de capas de aqui abajo crece y la regla se aplica a todas.
"""
import ast
import importlib
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
PLATFORM = PACKAGE / "platform"

# El orden es la ley: cada capa puede importar las de su izquierda, nunca las de su derecha.
LAYERS = ("platform", "core", "llm", "tools", "context", "verify", "autonomy", "spec", "learning")
PLATFORM_MODULES = ("backup", "events", "hardware_probe", "ledger", "policy", "tokenizer",
                    "transcripts", "vault")


def check(name, got, expect, failures):
    if got != expect:
        failures.append("%s: %r, esperaba %r" % (name, got, expect))


def _imports_of(path):
    """`(linea, texto)` de cada import del fichero, sea relativo o absoluto."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8", errors="replace"))):
        if isinstance(node, ast.ImportFrom):
            where = "." * node.level + (node.module or "")
            if node.module is None:
                where = "." * node.level + "{%s}" % ", ".join(a.name for a in node.names)
            found.append((node.lineno, where))
        elif isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
    return found


def _platform_siblings():
    return {path.stem for path in PLATFORM.glob("*.py") if path.stem != "__init__"}


def test_platform_is_a_leaf(failures):
    siblings = _platform_siblings()
    escapes = []
    for path in sorted(PLATFORM.glob("*.py")):
        for line, where in _imports_of(path):
            if where.startswith(".."):
                escapes.append("%s:%s %s sale de la capa con un import relativo" % (path.name, line, where))
                continue
            if where.startswith("."):
                if where.startswith(".{"):
                    names = where[2:-1].split(", ")
                    for name in names:
                        if name != "__version__" and name not in siblings:
                            escapes.append("%s:%s importa %r de la raiz" % (path.name, line, name))
                continue
            if where.split(".")[0] == "nexus_harness":
                target = where.split(".")[1] if "." in where else ""
                if target not in ("platform",):
                    escapes.append("%s:%s importa %s" % (path.name, line, where))
    check("platform no importa nada de fuera de platform", escapes, [], failures)


def test_the_declared_modules_are_the_real_ones(failures):
    check("los modulos de platform son exactamente los declarados", tuple(sorted(_platform_siblings())),
          tuple(sorted(PLATFORM_MODULES)), failures)


def test_the_layer_loads(failures):
    broken = []
    for module in PLATFORM_MODULES:
        try:
            importlib.import_module("nexus_harness.platform.%s" % module)
        except Exception as exc:  # noqa: BLE001 -- un import roto es el hallazgo
            broken.append("%s: %s: %s" % (module, type(exc).__name__, exc))
    check("cada modulo de la capa se importa", broken, [], failures)
    check("y la capa declara su sitio en el orden", LAYERS[0], "platform", failures)


def run():
    failures = []
    test_platform_is_a_leaf(failures)
    test_the_declared_modules_are_the_real_ones(failures)
    test_the_layer_loads(failures)
    return failures
