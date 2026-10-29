"""El aspecto de la cabina en DOS ejes independientes: diseño (skin) y pantón (palette).

Lo aprendimos de como lo resuelven otros: Hermes separa *skin* (bordes, banner, caracter) de
*personalidad*; OpenCode guarda temas como ficheros de tokens con jerarquia; Crush separa las opciones
de LAYOUT (compacto, diffs, transparencia) del color. La conclusion es la misma: el color y la
composicion son ejes distintos, y mezclarlos produce "el mismo diseno con otro pantone".

* **skin** — la composicion: tipografia, geometria, densidad, donde va el estado, como se dibuja un
  mensaje. `web/skins.css` (`[data-skin="..."]`). Cuatro: document, terminal, minimal, neon.
* **palette** — el color: `web/themes.css` (`[data-theme="..."]`). Seis pantones.

Cualquier skin funciona con cualquier panton (4 x 6 = 24 combinaciones) y hay pares recomendados.


Un tema es un juego de tokens (`web/themes.css`); la composición no cambia. Aquí viven los metadatos
—nombre, intención y tres muestras para el selector— y la validación: un `ui_theme` que no esté en
esta lista no se guarda, se dice. Un ajuste de color que rompe el arranque no es un gusto, es un fallo.

El contraste de cada pantón lo mide `selftests/test_themes.py` (WCAG sobre tinta/papel). Paleta bonita
que no se lee = defecto.
"""

# (clave, nombre, intención, pantón recomendado) — el orden es el del selector de diseños.
SKINS = (
    ("document", "Documento", "cuaderno de obra: serif, folios, reglas de 1px", "paper"),
    ("terminal", "Terminal", "TUI densa: todo monoespaciado y línea de estado", "crt"),
    ("minimal", "Minimal", "swiss: aire, una regla, cero adornos", "riso"),
    ("neon", "HUD neón", "cyberpunk: mayúsculas, esquinas cortadas, brillo", "neon"),
)
SKIN_KEYS = tuple(row[0] for row in SKINS)
DEFAULT_SKIN = "document"

# (clave, nombre, intención, (papel, sello, señal)) — el orden es el del selector.
THEMES = (
    ("neon", "Neón nocturno", "cyberpunk retro: violeta-negro, magenta y cian", ("#07060e", "#ff2e88", "#22d3ee")),
    ("crt", "Fósforo", "terminal CRT verde, con líneas de barrido", ("#050a06", "#b8ffcb", "#ffb000")),
    ("synth", "Synthwave", "SynthWave '84: ciruela, magenta y cian", ("#1a0b2e", "#ff3ea5", "#21d4fd")),
    ("amber", "Ámbar", "monocromo de fósforo ámbar", ("#0b0805", "#ffd7a3", "#ff9a1f")),
    ("riso", "Risográfica", "papel crema y duotono de imprenta", ("#f3efe4", "#1b1913", "#d93a10")),
    ("paper", "Cuaderno", "papel cálido y bermellón", ("#f4f1ea", "#191713", "#b8431f")),
)
KEYS = tuple(row[0] for row in THEMES)
DEFAULT = "neon"
# Los tokens de cada tema, para el contraste y para el selector. Se declaran aquí (y no se leen del
# CSS) porque un test que depende de un fichero de estilos no puede fallar por un color mal puesto.
TOKENS = {
    "neon": {"paper": "#07060e", "ink": "#eaf6ff", "ink2": "#9fb0cf", "seal": "#ff2e88",
             "ok": "#29f0a5", "warn": "#ffc94d", "bad": "#ff5c6c"},
    "crt": {"paper": "#050a06", "ink": "#b8ffcb", "ink2": "#6fbf85", "seal": "#ffb000",
            "ok": "#35ff86", "warn": "#ffd166", "bad": "#ff6b6b"},
    "synth": {"paper": "#1a0b2e", "ink": "#f7edff", "ink2": "#c3a6e0", "seal": "#ff3ea5",
              "ok": "#72f1b8", "warn": "#f3e70f", "bad": "#fe4450"},
    "amber": {"paper": "#0b0805", "ink": "#ffd7a3", "ink2": "#c79a5f", "seal": "#ff9a1f",
              "ok": "#ffcf66", "warn": "#ffb84d", "bad": "#ff7a45"},
    "riso": {"paper": "#f3efe4", "ink": "#1b1913", "ink2": "#5a5344", "seal": "#d93a10",
             "ok": "#1f7a4d", "warn": "#a86a00", "bad": "#c3271f"},
    "paper": {"paper": "#f4f1ea", "ink": "#191713", "ink2": "#615c53", "seal": "#b8431f",
              "ok": "#3f7a33", "warn": "#8a6512", "bad": "#a83a24"},
}


def resolve_skin(value):
    """La clave de diseño válida más cercana: lo que llegue por URL o fichero nunca rompe la cabina."""
    key = str(value or "").strip().lower()
    return key if key in SKIN_KEYS else DEFAULT_SKIN


def skin_meta(key):
    wanted = resolve_skin(key)
    return next(row for row in SKINS if row[0] == wanted)


def skin_label(key):
    return skin_meta(key)[1]


def skin_note(key):
    return skin_meta(key)[2]


def skin_palette(key):
    """El pantón con el que el diseño se pensó (recomendación, no candado)."""
    return skin_meta(key)[3]


def _luminance(hex_color):
    """Luminancia relativa WCAG de un `#rrggbb`. Puro: mismo color, mismo número."""
    value = str(hex_color).lstrip("#")
    channels = []
    for index in (0, 2, 4):
        channel = int(value[index:index + 2], 16) / 255.0
        channels.append(channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def ratio(foreground, background):
    """Contraste WCAG entre dos colores (1:1 a 21:1). Lo que se pinta, se mide."""
    high, low = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def contrast(key, field="ink"):
    """El contraste de `field` sobre el papel del tema, redondeado a un decimal."""
    tokens = TOKENS[resolve(key)]
    return round(ratio(tokens[field], tokens["paper"]), 1)


def resolve(value):
    """La clave válida más cercana: lo que llega por URL o por fichero nunca rompe la cabina."""
    key = str(value or "").strip().lower()
    return key if key in KEYS else DEFAULT


def meta(key):
    """`(clave, nombre, intención, muestras)` del tema pedido."""
    wanted = resolve(key)
    return next(row for row in THEMES if row[0] == wanted)


def label(key):
    return meta(key)[1]


def swatches(key):
    return meta(key)[3]
