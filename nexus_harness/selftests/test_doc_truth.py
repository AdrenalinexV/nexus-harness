"""Un doc no puede contradecir al motor: la suite que mete `tools/doc_truth.py` dentro del gate.

El README decía «50 suites», el CI y tres documentos decían «49», la real era 55, y el titular del eval
contaba las dos omitidas como resueltas. Ninguna de esas cifras la había medido nadie, y ninguna suite
las miraba: el verde del gate era cierto sobre el código y falso sobre lo publicado.

Esta suite importa el medidor y le pide su veredicto. No escribe nada (para eso está
`python tools/doc_truth.py --write`): un gate que reescribe documentos mientras los juzga no es un gate.
"""
import importlib
import sys
from pathlib import Path

from . import Skip

ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS = str(ROOT / "tools")


def run():
    if not (ROOT / "tools" / "doc_truth.py").is_file():
        # Wheel instalado: el medidor vive en el checkout, no en el paquete. SKIP con razón, no rojo.
        raise Skip("no hay tools/doc_truth.py en %s: esta suite solo mide el checkout" % ROOT)
    if TOOLS not in sys.path:
        sys.path.insert(0, TOOLS)
    try:
        module = importlib.import_module("doc_truth")
    except Exception as exc:  # noqa: BLE001 -- si el medidor no importa, no hay veredicto posible
        return ["tools/doc_truth.py no importa: %s: %s" % (type(exc).__name__, exc)]
    problems, values, covered = module.check()
    if values["suites"] < 1 or not covered:
        return ["doc_truth no midió nada: suites=%r docs=%r" % (values["suites"], covered)]
    return list(problems)
