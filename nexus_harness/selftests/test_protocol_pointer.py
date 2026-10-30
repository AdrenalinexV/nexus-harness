"""`nexus/` en la raíz no es un paquete muerto: es el puntero al gobernador, y esto lo exige.

La auditoría lo dio por muerto («solo `__init__.py`») y estuvo a punto de borrarlo. No lo está: son 17
líneas que extienden `__path__` al gobernador real (`NEXUS_PROTOCOL`, o `C:\\Proyectos\\NexusProtocol`)
para que `from nexus.checks import rules_lint` resuelva con este repositorio como directorio de trabajo
**sin** copiar ni una regla — una definición, un sitio donde arreglarla. Diez llamantes lo usan
(`cli`, `bridge`, `gov`, `onboarding`, `session_relay`, `settings_skills`, `verify/gate`).

Un puntero sin test es un puntero que alguien borra en la siguiente limpieza: por eso esta suite.
"""
import importlib
import os
from pathlib import Path

from . import Skip

ROOT = Path(__file__).resolve().parent.parent.parent
SHIM = ROOT / "nexus" / "__init__.py"
SOURCE = Path(os.environ.get("NEXUS_PROTOCOL") or r"C:\Proyectos\NexusProtocol") / "nexus"


def run():
    if not SHIM.is_file():
        return ["falta nexus/__init__.py: los diez `from nexus.… import` del repo dejan de resolver"]
    # Sin gobernador esta suite no puede medir: eso es un SKIP. Con el gobernador presente, un puntero
    # que no resuelve es un ROJO — si no se distinguen, el test no sirve para nada.
    if not (SOURCE / "checks").is_dir():
        raise Skip("el gobernador no está en esta máquina (%s/checks no existe): apunta NEXUS_PROTOCOL "
                   "a NexusProtocol para que esta suite mida algo" % SOURCE)
    problems = []
    try:
        import nexus
    except Exception as exc:  # noqa: BLE001 -- el shim debe importar siempre, aun sin gobernador
        return ["`import nexus` revienta: %s: %s" % (type(exc).__name__, exc)]

    if Path(nexus.__file__).resolve() != SHIM.resolve():
        problems.append("`import nexus` resuelve a %s y no al puntero de este repo: alguien copió el "
                        "protocolo o el shim perdió prioridad en sys.path" % nexus.__file__)
    paths = [Path(entry).resolve() for entry in list(getattr(nexus, "__path__", []))]
    if SOURCE.resolve() not in paths:
        problems.append("el puntero no extendió __path__ hacia %s: __path__=%r" % (SOURCE, paths))
    try:
        rules_lint = importlib.import_module("nexus.checks.rules_lint")
    except Exception as exc:  # noqa: BLE001 -- con el gobernador presente esto es rojo, no skip
        return problems + ["`import nexus.checks.rules_lint` falla con el gobernador presente: %s: %s"
                           % (type(exc).__name__, exc)]
    # El contrato concreto que el gate consume: `lint_repo` y el techo de líneas que declara el gobernador.
    if not callable(getattr(rules_lint, "lint_repo", None)):
        problems.append("nexus.checks.rules_lint importa pero no expone `lint_repo`: el gate llama a otra API")
    if getattr(rules_lint, "MAX_LINES", None) != 400:
        problems.append("el gobernador declara MAX_LINES=%r y la ley de este repo es 400"
                        % getattr(rules_lint, "MAX_LINES", None))
    return problems
