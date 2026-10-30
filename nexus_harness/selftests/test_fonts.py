"""Las dos familias viajan con el paquete: locales, subseted, con su licencia y sin red.

La ley de la cabina no es "sin webfonts" sino **0 recursos externos**: una tipografía que vive en
`web/` y se sirve por el mismo HTTP que el HTML es local, y por eso se ve igual en un avión, en un
runner de CI sin salida a internet y detrás de un proxy que bloquea terceros. Lo que se prohíbe es que
la página tenga que pedir permiso a un CDN para estar bien maquetada.

Esta suite mide las cuatro cosas que pueden romperse en silencio: que los ficheros estén (y estén en
`web/`, no en una subcarpeta que `web/*` no empaqueta), que sean woff2 de verdad, que la licencia OFL
viaje a su lado, y que ninguna hoja de estilos pida nada por red.
"""
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"

# La horquilla que fijó el operador: las dos familias juntas, subseted a latino+español, ≤150 KB.
BUDGET_BYTES = 150 * 1024
FAMILIES = ("nexus-sans.woff2", "nexus-mono.woff2")

# Atributos que el navegador convierte en una petición. `xmlns="http://www.w3.org/2000/svg"` también
# empieza por http pero no pide nada: solo cuenta href/src/url, que es lo que la ley mide en el DOM.
EXTERNAL = ('href="http', "href='http", 'src="http', "src='http", "url(http", "url('http", 'url("http')


def _fonts_exist():
    problems = []
    total = 0
    for name in FAMILIES:
        path = WEB / name
        if not path.is_file():
            problems.append("falta %s: el paquete se quedaría sin su tipografía" % name)
            continue
        if path.parent != WEB:
            problems.append("%s no está en web/ directamente: `package-data web/*` no empaqueta subcarpetas" % name)
        head = path.read_bytes()[:4]
        if head != b"wOF2":
            problems.append("%s no es woff2 (magic %r): el navegador pediría un formato que no existe" % (name, head))
        total += path.stat().st_size
    if not problems and total > BUDGET_BYTES:
        problems.append("las dos familias pesan %d B > %d B: el presupuesto era ≤150 KB" % (total, BUDGET_BYTES))
    return problems


def _license():
    path = WEB / "OFL.txt"
    if not path.is_file():
        return ["falta web/OFL.txt: empaquetar una OFL sin su licencia no es empaquetar la OFL"]
    text = path.read_text(encoding="utf-8", errors="replace")
    problems = []
    if "SIL OPEN FONT LICENSE" not in text.upper():
        problems.append("OFL.txt no contiene el texto de la SIL Open Font License")
    for family, marker in (("sans", "Inter"), ("mono", "JetBrains Mono")):
        if marker not in text:
            problems.append("OFL.txt no nombra el original de la familia %s (%s)" % (family, marker))
    return problems


def _css():
    path = WEB / "tokens.css"
    if not path.is_file():
        return ["falta web/tokens.css: no hay dónde declarar las caras"]
    css = path.read_text(encoding="utf-8")
    problems = []
    faces = css.count("@font-face")
    if faces != 2:
        problems.append("tokens.css declara %d @font-face, se esperaban 2" % faces)
    if css.count("font-display: swap") < 2:
        problems.append("falta `font-display: swap` en alguna cara: sin él el texto se queda invisible al cargar")
    for name in FAMILIES:
        if name not in css:
            problems.append("tokens.css no referencia %s" % name)
    for var, family in (("--font-ui:", "Nexus Sans"), ("--font-display:", "Nexus Sans"), ("--font-mono:", "Nexus Mono")):
        line = next((row for row in css.splitlines() if row.strip().startswith(var)), "")
        if family not in line:
            problems.append("%s no lidera su pila con %s (el sistema tiene que ser el respaldo)" % (var, family))
        if "sans-serif" not in line and "monospace" not in line:
            problems.append("%s no termina en familia genérica: sin red y sin fichero no habría respaldo" % var)
    return problems


def _served():
    from .. import ui
    problems = []
    if ui.TYPES.get(".woff2") != "font/woff2":
        problems.append("ui.TYPES[.woff2] = %r: el estático se serviría como text/plain" % ui.TYPES.get(".woff2"))
    if Path(ui.WEB).resolve() != WEB.resolve():
        problems.append("ui.WEB apunta a %s y las fuentes viven en %s" % (ui.WEB, WEB))
    return problems


def _no_external():
    """Ninguna hoja ni página pide nada por red: la comprobación estática del criterio del DOM."""
    problems = []
    for path in sorted(WEB.iterdir()):
        if path.suffix.lower() not in (".html", ".css", ".js") or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in EXTERNAL:
            if marker in text:
                problems.append("%s contiene %r: un recurso externo en la cabina" % (path.name, marker))
    return problems


def run():
    return _fonts_exist() + _license() + _css() + _served() + _no_external()
