"""La maquina de estados del turno de noche, medida sin tocar la rubrica ni el estado reales."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# En el motor congelado este modulo vive dentro del desempaquetado de PyInstaller, asi que la raiz
# del repositorio no esta donde el fuente la deja. `engine.spec` empaqueta el fichero para que la
# suite corra igual de congelada -- y si algun dia no lo encuentra, lo dice con las dos rutas que
# intento en vez de fallar por un camino que nadie puede leer.
FROZEN_ROOT = Path(getattr(sys, "_MEIPASS", ROOT))


def source_file():
    """`tools/nightshift.py` en el repositorio o empaquetado, o None."""
    for base in (ROOT, FROZEN_ROOT):
        candidate = base / "tools" / "nightshift.py"
        if candidate.is_file():
            return candidate
    return None


def run():
    """Carga `tools/nightshift.py` como modulo y ejecuta su propio selftest."""
    path = source_file()
    if path is None:
        return ["no encuentro tools/nightshift.py: ni en %s ni en %s" % (ROOT, FROZEN_ROOT)]
    spec = importlib.util.spec_from_file_location("nightshift", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("nightshift", module)
    spec.loader.exec_module(module)
    return list(module.selftest())
