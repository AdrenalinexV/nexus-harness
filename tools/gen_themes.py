"""Escribe `web/themes.css` desde `ui_theme.tokens()`.

Los colores tienen UNA fuente (Python). El CSS es el artefacto que sirve el navegador, y el test
`themes` compara los dos: editar el CSS a mano es un error que se detecta, no un atajo.

    python tools/gen_themes.py            # escribe el fichero
    python tools/gen_themes.py --check    # exit 1 si el fichero no coincide con el generador
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus_harness import ui_theme  # noqa: E402

TARGET = ROOT / "nexus_harness" / "web" / "themes.css"


def main(argv=None):
    parser = argparse.ArgumentParser(description="genera web/themes.css desde ui_theme")
    parser.add_argument("--check", action="store_true", help="no escribe; falla si hay diferencias")
    args = parser.parse_args(argv)
    generated = ui_theme.css()
    current = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else ""
    if args.check:
        same = current == generated
        print("themes.css %s" % ("coincide" if same else "NO coincide con el generador"))
        return 0 if same else 1
    TARGET.write_text(generated, encoding="utf-8", newline="\n")
    print("escrito %s (%d lineas)" % (TARGET.relative_to(ROOT), generated.count("\n")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
