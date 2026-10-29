"""El aspecto de la cabina: cuatro ejes independientes, no un catálogo de combinaciones.

Lo que se aprendió mirando a los demás: Hermes separa *skin* de *personalidad*; OpenCode guarda temas
como tokens; Crush separa layout de color. De ahí, cuatro ejes que se eligen por separado:

    modo      dark | light      (el papel: oscuro o claro — NO depende del sistema)
    diseño    main | matrix | glossy | terminal | minimal | neon   (la composición)
    pantón    neon | crt | synth | amber | riso | paper             (el color)
    tipografía system | serif | mono | condensed                    (la voz)

`main` es el diseño de la casa y el único que se anuncia como principal; `matrix` y `glossy` son
especiales (cambian el esqueleto de verdad); `terminal`, `minimal` y `neon` quedan como alternativos.

Este módulo es la ÚNICA fuente de los colores: `web/themes.css` se genera desde `TOKENS`
(`tools/gen_themes.py`) y un test falla si el fichero y el generador se separan.
"""

MODES = (("dark", "Oscuro"), ("light", "Claro"))
MODE_KEYS = tuple(row[0] for row in MODES)
DEFAULT_MODE = "dark"

FONTS = (
    ("system", "Sistema", "sans del escritorio; neutra y rápida"),
    ("serif", "Editorial", "serif del sistema para títulos y prosa"),
    ("mono", "Técnica", "monoespaciada en todo; cifras y códigos"),
    ("condensed", "Condensada", "estrecha y alta; más texto por línea"),
)
FONT_KEYS = tuple(row[0] for row in FONTS)
DEFAULT_FONT = "system"

# (clave, nombre, intención, par recomendado) — `group`: main | special | alt
SKINS = (
    ("main", "Principal", "cuaderno de obra: serif en títulos, folios, reglas de 1px", "paper", "main"),
    ("matrix", "Matrix", "terminal retro: verde fósforo, barrido, columna estrecha, sin tarjetas", "crt", "special"),
    ("glossy", "Glossy", "años 2000: barra con degradado, botones con brillo y relieve", "paper", "special"),
    ("terminal", "Terminal", "TUI densa: todo mono, línea de estado, prefijos › y ·", "crt", "alt"),
    ("minimal", "Minimal", "swiss: aire, una regla, cero adornos, sans", "riso", "alt"),
    ("neon", "HUD neón", "cyberpunk: mayúsculas, esquinas cortadas, brillo", "neon", "alt"),
)
SKIN_KEYS = tuple(row[0] for row in SKINS)
DEFAULT_SKIN = "main"

# (clave, nombre, intención, (papel, sello, señal)) — el orden es el del selector de pantones
ACCENTS = (
    ("neon", "Neón", "magenta de rótulo y cian de pantalla", ("#07060e", "#ff2e88", "#22d3ee")),
    ("crt", "Fósforo", "verde de terminal P1 y ámbar de aviónica", ("#050a06", "#b8ffcb", "#ffb000")),
    ("synth", "Synthwave", "ciruela, magenta y cian de 1984", ("#1a0b2e", "#ff3ea5", "#21d4fd")),
    ("amber", "Ámbar", "monocromo cálido de fósforo", ("#0b0805", "#ffd7a3", "#ff9a1f")),
    ("riso", "Risográfica", "naranja de imprenta sobre crema", ("#f3efe4", "#d93a10", "#2b4bff")),
    ("paper", "Bermellón", "papel cálido y tinta de sello", ("#f4f1ea", "#b8431f", "#b8431f")),
)
ACCENT_KEYS = tuple(row[0] for row in ACCENTS)
DEFAULT_ACCENT = "paper"

# Papel de cada pantón en modo oscuro (el tinte es parte del carácter del color) y el mismo juego en
# modo claro: un papel cálido compartido y el sello oscurecido hasta cumplir contraste.
DARK_PAPER = {
    "neon": ("#07060e", "#0d0a18", "#141026", "#241b3a", "#3d2a60"),
    "crt": ("#050a06", "#08120b", "#0c1a11", "#12351f", "#1d4c2d"),
    "synth": ("#1a0b2e", "#24103c", "#2f1550", "#3a1c5c", "#57308a"),
    "amber": ("#0b0805", "#120e08", "#1a1309", "#33240f", "#4d3717"),
    "riso": ("#12100c", "#181510", "#1f1b14", "#2e2820", "#3f382d"),
    "paper": ("#121110", "#171614", "#1e1c19", "#2b2926", "#3a3733"),
}
DARK_INK = {
    "neon": ("#eaf6ff", "#9fb0cf", "#6d7ea0"),
    "crt": ("#b8ffcb", "#6fbf85", "#4d8a5f"),
    "synth": ("#f7edff", "#c3a6e0", "#8d6fb0"),
    "amber": ("#ffd7a3", "#c79a5f", "#8a6a3e"),
    "riso": ("#efe8dc", "#b9ad99", "#8c8171"),
    "paper": ("#ece7dd", "#a8a29a", "#6f6a63"),
}
# En claro el papel es el mismo para todos (crema sin blanquear) y lo que cambia es el sello.
LIGHT_PAPER = ("#f5f2ea", "#ece7dc", "#e2dbcc", "#d6cdba", "#c4b9a2")
LIGHT_INK = ("#191713", "#5f594e", "#8a8478")
LIGHT_SEAL = {
    "neon": "#c31f66", "crt": "#1f7a3a", "synth": "#a8247c",
    "amber": "#8a5a00", "riso": "#c0330c", "paper": "#b8431f",
}
STATE_DARK = {"ok": "#7fae6a", "warn": "#c99a3f", "bad": "#cc5b45", "idle": "#6f6a63"}
STATE_LIGHT = {"ok": "#3f7a33", "warn": "#8a6512", "bad": "#a83a24", "idle": "#8a8478"}
SIGNAL_DARK = {"neon": "#22d3ee", "crt": "#7dffb0", "synth": "#21d4fd",
               "amber": "#ffd7a3", "riso": "#bda98c", "paper": "#b8431f"}
SIGNAL_LIGHT = {"neon": "#0e7490", "crt": "#166534", "synth": "#7c3aed",
                "amber": "#7a4a00", "riso": "#2b4bff", "paper": "#b8431f"}


def tokens(mode, accent):
    """El juego completo de tokens de una pareja (modo, pantón). Puro: misma entrada, mismo dict."""
    mode, accent = resolve_mode(mode), resolve(accent)
    if mode == "dark":
        paper, paper2, paper3, rule, rule2 = DARK_PAPER[accent]
        ink, ink2, ink3 = DARK_INK[accent]
        seal = next(row[3][1] for row in ACCENTS if row[0] == accent)
        signal, state = SIGNAL_DARK[accent], STATE_DARK
        seal_ink = "#120a06" if accent in ("neon", "synth", "amber") else paper
    else:
        paper, paper2, paper3, rule, rule2 = LIGHT_PAPER
        ink, ink2, ink3 = LIGHT_INK
        seal, signal, state = LIGHT_SEAL[accent], SIGNAL_LIGHT[accent], STATE_LIGHT
        seal_ink = "#ffffff"
    return {"paper": paper, "paper-2": paper2, "paper-3": paper3, "rule": rule, "rule-2": rule2,
            "ink": ink, "ink-2": ink2, "ink-3": ink3, "seal": seal, "seal-ink": seal_ink,
            "signal": signal, **state}


def css():
    """El CSS de los 12 juegos (2 modos x 6 pantones), generado desde `tokens`.

    Se genera para que no existan dos fuentes de color. `tools/gen_themes.py` escribe el fichero y
    `test_themes` compara: si alguien edita el CSS a mano, el test lo dice.
    """
    head = ["""/* Nexus-Harness — pantones: 2 modos x 6 colores. GENERADO por tools/gen_themes.py.
   No se edita a mano: la fuente es `nexus_harness/ui_theme.tokens()` y el test compara. */""",
            ':root { --signal: var(--seal); --glow: 0 0 0 transparent; }']
    for mode, _label in MODES:
        head.append('[data-mode="%s"] { %s }' % (mode, _decl(tokens(mode, DEFAULT_ACCENT))))
    for accent, name, _note, _swatch in ACCENTS:
        head.append('/* %s · %s */' % (accent, name))
        for mode, _label in MODES:
            head.append('[data-mode="%s"][data-accent="%s"] { %s }'
                        % (mode, accent, _decl(tokens(mode, accent))))
    return "\n".join(head) + "\n" + DECOR


# Adornos que son del PANTÓN (no del diseño): barrido de CRT y brillo de neón. Se emiten aquí para que
# sigan teniendo una sola fuente, y `skins.css` (que se carga después) manda en la composición.
DECOR = """
[data-mode="dark"][data-accent="crt"] body::after {
  content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 9999;
  background: repeating-linear-gradient(to bottom, rgba(0, 0, 0, .26) 0 1px, transparent 1px 3px);
  opacity: .5;
}
[data-mode="dark"][data-accent="crt"] body { text-shadow: 0 0 6px rgba(88, 255, 140, .26); }
[data-mode="dark"][data-accent="amber"] body { text-shadow: 0 0 6px rgba(255, 154, 31, .2); }
[data-accent="neon"] .brand span { text-shadow: 0 0 10px var(--seal); }
[data-mode="dark"][data-accent="neon"] .masthead { box-shadow: 0 0 22px -10px var(--seal); }
[data-mode="dark"][data-accent="neon"] button.primary,
[data-mode="dark"][data-accent="synth"] button.primary { box-shadow: 0 0 14px -4px var(--seal); }
"""


def _decl(values):
    return " ".join("--%s: %s;" % (key, value) for key, value in values.items())


def accent_meta(key):
    wanted = resolve(key)
    return next(row for row in ACCENTS if row[0] == wanted)


def swatches(key):
    return accent_meta(key)[3]


def _luminance(hex_color):
    value = str(hex_color).lstrip("#")
    channels = []
    for index in (0, 2, 4):
        channel = int(value[index:index + 2], 16) / 255.0
        channels.append(channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def ratio(foreground, background):
    high, low = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def contrast(mode, accent, field="ink"):
    game = tokens(mode, accent)
    return round(ratio(game[field], game["paper"]), 1)


def resolve(value):
    key = str(value or "").strip().lower()
    return key if key in ACCENT_KEYS else DEFAULT_ACCENT


def resolve_mode(value):
    key = str(value or "").strip().lower()
    return key if key in MODE_KEYS else DEFAULT_MODE


def resolve_font(value):
    key = str(value or "").strip().lower()
    return key if key in FONT_KEYS else DEFAULT_FONT


def resolve_skin(value):
    key = str(value or "").strip().lower()
    return key if key in SKIN_KEYS else DEFAULT_SKIN


def skin_meta(key):
    wanted = resolve_skin(key)
    return next(row for row in SKINS if row[0] == wanted)


def skin_label(key):
    return skin_meta(key)[1]


def group_of(key):
    return skin_meta(key)[4]


def skin_palette(key):
    return skin_meta(key)[3]


def font_label(key):
    wanted = resolve_font(key)
    return next(row for row in FONTS if row[0] == wanted)[1]


def mode_label(key):
    wanted = resolve_mode(key)
    return next(row for row in MODES if row[0] == wanted)[1]
