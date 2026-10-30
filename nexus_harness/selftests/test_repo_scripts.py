"""Los scripts de `tools/` importan: el refactor a capas los dejó muertos sin que nadie lo viera.

Cinco herramientas murieron con `ModuleNotFoundError` porque el refactor movió `events`, `message` y
`compaction` a sus capas y los scripts siguieron apuntando a la raíz. Nadie se enteró porque ningún
test los importaba: el gate corría las suites del paquete y los scripts no están en el gate. Esa es la
lección que esta suite compra — **un script que nadie importa es un script que se rompe gratis**.

Se importan los cinco y se exige que cada uno exponga `main`. No se ejecutan: correr de verdad necesita
un proveedor, un reloj o un directorio de trabajo, y un test que depende de eso deja de ser determinista.
"""
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS = str(ROOT / "tools")
SCRIPTS = ("audit_context", "benchmark_ab_savings", "prove_repair_cycle", "adversary_audit", "dogfood")


def run():
    problems = []
    if TOOLS not in sys.path:
        sys.path.insert(0, TOOLS)
    for name in SCRIPTS:
        path = ROOT / "tools" / ("%s.py" % name)
        if not path.is_file():
            problems.append("tools/%s.py no existe: la lista de esta suite está desfasada" % name)
            continue
        try:
            module = importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 -- cualquier fallo de import es el defecto que se mide
            problems.append("tools/%s.py no importa: %s: %s" % (name, type(exc).__name__, exc))
            continue
        if not callable(getattr(module, "main", None)):
            problems.append("tools/%s.py importa pero no expone main(argv=None)" % name)
    return problems
