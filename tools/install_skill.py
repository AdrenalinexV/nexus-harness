"""Instala una skill del paquete en el perfil de Hermes.

El repo es la fuente: `nexus_harness/skills/<name>/` viaja con el arnes y se enruta en cada turno
(`context/skill_router.py`). Esta copia es solo para que el agente que corre en Hermes la tenga en su
catalogo nativo, sin que nadie copie carpetas a mano.

    python tools/install_skill.py nexus-visual-identity [--dest DIR]

Sin `--dest` usa `%LOCALAPPDATA%/hermes/profiles/<perfil>/skills`, que es lo que Hermes lee.
"""
import argparse
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def hermes_skills():
    profile = os.environ.get("HERMES_PROFILE") or "nexus-harness"
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return base / "hermes" / "profiles" / profile / "skills"


def install(name, dest=None):
    source = ROOT / "nexus_harness" / "skills" / name
    if not (source / "SKILL.md").is_file():
        return False, "no existe %s" % (source / "SKILL.md")
    target = Path(dest) if dest else hermes_skills()
    target = target / name
    target.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        if item.is_dir():
            continue
        relative = item.relative_to(source)
        (target / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target / relative)
    return True, str(target)


def main(argv=None):
    parser = argparse.ArgumentParser(description="instala una skill del paquete en Hermes")
    parser.add_argument("name")
    parser.add_argument("--dest", default=None)
    args = parser.parse_args(argv)
    ok, where = install(args.name, args.dest)
    print(("instalada: %s" if ok else "no instalada: %s") % where)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
