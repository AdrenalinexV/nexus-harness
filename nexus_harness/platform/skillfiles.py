"""El formato en disco de un fichero de skill: donde vive lo forjado y como se lee su frontmatter.

Vivia en `skill_router` (capa de contexto). Lo necesitan tanto el router como `skill_forge`, que es la
herramienta que escribe esos ficheros: el formato es de la capa de abajo, no de quien lo consume.
"""
import re
from pathlib import Path

FORGED_REL = Path(".nexus") / "skills"
FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)


def parse_frontmatter(text):
    """`(campos, cuerpo)` del `SKILL.md`. Sin frontmatter, `({}, texto)`: no se inventa un contrato."""
    match = FRONTMATTER.match(str(text or ""))
    if not match:
        return {}, str(text or "")
    fields, key = {}, ""
    for line in match.group(1).splitlines():
        if re.match(r"^\s+\S", line) and key:            # continuacion de una lista YAML
            fields[key] = "%s %s" % (fields.get(key, ""), line.strip())
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip().lower()] = value.strip().strip("\"'")
    return fields, str(text or "")[match.end():]
