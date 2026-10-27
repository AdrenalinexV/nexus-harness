"""Renderiza el panel de Estadisticas y Auditoria por consola, para poder leerlo sin navegador.

    python tools/render_stats.py [--html]

Sirve para lo que sirve: comprobar con los ojos que la tarjeta y las barras dicen lo MISMO, que la
tabla de extrapolacion esta, y que lo del gobernador aparece etiquetado como suyo. Un panel que solo se
puede ver a mano en la ventana es un panel que nadie revisa en un cambio.
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus_harness import settings_tools  # noqa: E402
from nexus_harness.cockpit import Cockpit  # noqa: E402
from nexus_harness.config import HarnessConfig  # noqa: E402

TAG = re.compile(r"<[^>]+>")


def visible(html):
    """El texto que un operador lee: sin etiquetas, sin huecos de tres lineas."""
    text = TAG.sub(" ", html)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="render_stats")
    parser.add_argument("--html", action="store_true")
    args = parser.parse_args(argv)
    config = HarnessConfig.load()
    config.default_root = ROOT
    cockpit = Cockpit(config)
    title, subtitle, body = settings_tools.stats(cockpit)
    print("%s — %s" % (title, subtitle))
    print(visible(body) if not args.html else body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
