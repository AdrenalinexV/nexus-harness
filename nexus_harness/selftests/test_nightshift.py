"""La maquina de estados del turno de noche, medida sin tocar la rubrica ni el estado reales."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run():
    """Carga `tools/nightshift.py` como modulo y ejecuta su propio selftest."""
    spec = importlib.util.spec_from_file_location("nightshift", ROOT / "tools" / "nightshift.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("nightshift", module)
    spec.loader.exec_module(module)
    return list(module.selftest())
