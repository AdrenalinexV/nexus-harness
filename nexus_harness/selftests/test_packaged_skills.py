"""Las skills que el arnes TRAE: viajan en el paquete y se enrutan como las demas.

Una skill que solo existe en el perfil de Hermes no es del producto: en otra maquina, o sin Hermes, el
arnes se queda sin ella. Esta suite comprueba que la carpeta del paquete es una raiz de enrutado y que
su contenido tiene lo minimo para competir en un turno (nombre, descripcion, palabras y referencias).
"""
import sys
from pathlib import Path

from ..context import skill_router

# Igual que `web/`: en el .exe las skills viajan en `_MEIPASS/skills`.
PACKAGED = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "skills"
SHIPPED = ("nexus-visual-identity", "nexus-layout-skins")


def check(name, got, expect, failures):
    if got != expect:
        failures.append("%s: %r, esperaba %r" % (name, got, expect))


def run():
    failures = []
    check("el paquete trae su carpeta de skills", PACKAGED.is_dir(), True, failures)
    check("y es una raiz de enrutado", PACKAGED in skill_router.protocol_roots(), True, failures)
    entries = {entry["name"]: entry for entry in skill_router.scan(PACKAGED)}
    references = {"nexus-visual-identity": ("palettes.md", "theme-system.md"),
                  "nexus-layout-skins": ("skins.md",)}
    for name in SHIPPED:
        check("%s viaja en el paquete" % name, name in entries, True, failures)
        if name not in entries:
            continue
        entry = entries[name]
        check("%s con descripcion" % name, bool(entry["description"]), True, failures)
        check("%s con palabras para el enrutado" % name, len(entry["words"]) >= 3, True, failures)
        check("%s sin pasar de 400 lineas" % name, entry["lines"] <= 400, True, failures)
        for reference in references[name]:
            path = PACKAGED / name / "references" / reference
            check("%s referencia %s" % (name, reference), path.is_file(), True, failures)
    return failures
