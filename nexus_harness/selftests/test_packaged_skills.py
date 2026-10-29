"""Las skills que el arnes TRAE: viajan en el paquete y se enrutan como las demas.

Una skill que solo existe en el perfil de Hermes no es del producto: en otra maquina, o sin Hermes, el
arnes se queda sin ella. Esta suite comprueba que la carpeta del paquete es una raiz de enrutado y que
su contenido tiene lo minimo para competir en un turno (nombre, descripcion, palabras y referencias).
"""
from pathlib import Path

from ..context import skill_router

PACKAGED = Path(__file__).resolve().parents[1] / "skills"
SHIPPED = "nexus-visual-identity"


def check(name, got, expect, failures):
    if got != expect:
        failures.append("%s: %r, esperaba %r" % (name, got, expect))


def run():
    failures = []
    check("el paquete trae su carpeta de skills", PACKAGED.is_dir(), True, failures)
    check("y es una raiz de enrutado", PACKAGED in skill_router.protocol_roots(), True, failures)
    entries = {entry["name"]: entry for entry in skill_router.scan(PACKAGED)}
    check("%s viaja en el paquete" % SHIPPED, SHIPPED in entries, True, failures)
    if SHIPPED in entries:
        entry = entries[SHIPPED]
        check("con descripcion", bool(entry["description"]), True, failures)
        check("con palabras para el enrutado", len(entry["words"]) >= 3, True, failures)
        check("sin pasar de 400 lineas", entry["lines"] <= 400, True, failures)
        for reference in ("palettes.md", "theme-system.md"):
            path = PACKAGED / SHIPPED / "references" / reference
            check("%s referencia %s" % (SHIPPED, reference), path.is_file(), True, failures)
    return failures
