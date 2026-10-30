"""Los ejes del aspecto: contraste de las 12 parejas, CSS generado, diseños estructurales y validación.

Un tema es un juego de tokens (modo x pantón). Lo que se afirma no es "queda bonito": es que cada una
de las 12 parejas se lee (WCAG), que `web/themes.css` es exactamente lo que genera `ui_theme.css()`
—una sola fuente de color—, que cada diseño toca ESTRUCTURA y no solo color, y que una errata en
cualquiera de las cuatro claves (`ui_mode`, `ui_skin`, `ui_theme`, `ui_font`) no se guarda.
"""
import json
import tempfile
from pathlib import Path

from .. import onboarding, ui_theme

# Umbrales: tinta AAA (7:1), secundaria AA (4.5:1), sellos y estados AA no textual (3:1).
MIN_TEXT, MIN_SECOND, MIN_STATE = 7.0, 4.5, 3.0
WEB = Path(__file__).resolve().parents[1] / "web"
CSS = WEB / "themes.css"
SKIN_FILES = (WEB / "skins.css", WEB / "skins-special.css")
# Un diseño que solo cambia colores no es un diseño: tiene que tocar tipografía, rejilla, mensaje y campo.
SKIN_MUST = (".title", ".app", ".msg", ".sfield")


def check(name, got, expect, failures):
    if got != expect:
        failures.append("%s: %r, esperaba %r" % (name, got, expect))


def test_every_game_reads(failures):
    for mode in ui_theme.MODE_KEYS:
        for accent in ui_theme.ACCENT_KEYS:
            game = ui_theme.tokens(mode, accent)
            label = "%s/%s" % (mode, accent)
            check("%s tinta/papel >= %s" % (label, MIN_TEXT),
                  ui_theme.ratio(game["ink"], game["paper"]) >= MIN_TEXT, True, failures)
            check("%s tinta-2/papel >= %s" % (label, MIN_SECOND),
                  ui_theme.ratio(game["ink-2"], game["paper"]) >= MIN_SECOND, True, failures)
            for field in ("seal", "ok", "warn", "bad"):
                check("%s %s/papel >= %s" % (label, field, MIN_STATE),
                      ui_theme.ratio(game[field], game["paper"]) >= MIN_STATE, True, failures)


def test_css_is_generated(failures):
    """`web/themes.css` no se edita a mano: es el artefacto del generador."""
    current = CSS.read_text(encoding="utf-8")
    check("themes.css coincide con el generador", current, ui_theme.css(), failures)
    for mode in ui_theme.MODE_KEYS:
        for accent in ui_theme.ACCENT_KEYS:
            block = '[data-mode="%s"][data-accent="%s"]' % (mode, accent)
            check("%s tiene bloque" % block, block in current, True, failures)


def test_skins_are_structural(failures):
    css = "".join(path.read_text(encoding="utf-8") for path in SKIN_FILES)
    for key in ui_theme.SKIN_KEYS:
        if key == ui_theme.DEFAULT_SKIN:
            check("el diseño base se declara", "01 · main" in css, True, failures)
            continue
        block = '[data-skin="%s"]' % key
        check("%s tiene su bloque" % key, block in css, True, failures)
        check("%s toca al menos 10 reglas (no es un pantón)" % key, css.count(block) >= 10, True,
              failures)
        for selector in SKIN_MUST:
            check("%s redefine %s" % (key, selector), (block + " " + selector) in css, True, failures)
    check("los seis diseños están agrupados (principal/especial/alternativo)",
          sorted({row[4] for row in ui_theme.SKINS}), ["alt", "main", "special"], failures)


def test_fonts_change_the_voice(failures):
    css = "".join(path.read_text(encoding="utf-8") for path in SKIN_FILES)
    for key in ui_theme.FONT_KEYS:
        if key == ui_theme.DEFAULT_FONT:
            continue
        check("la voz %s tiene su regla" % key, '[data-font="%s"]' % key in css, True, failures)


GENERIC = {"ui-serif", "ui-monospace", "ui-sans-serif", "system-ui", "sans-serif", "serif",
           "monospace", "cursive", "fantasy"}


def test_stacks_name_a_real_family_first(failures):
    """Una pila que empieza por `ui-serif` deja la elección al navegador: en Windows eso es Times.

    Se exige que la PRIMERA familia de `--font-ui`, `--font-display` y `--font-mono` sea un nombre
    concreto (un nombre propio entre comillas), no una palabra genérica de CSS.
    """
    tokens = (WEB / "tokens.css").read_text(encoding="utf-8")
    for name in ("--font-ui", "--font-display", "--font-mono"):
        start = tokens.find(name + ":")
        stack = tokens[start:tokens.find(";", start)].split(":", 1)[1].strip()
        first = stack.split(",")[0].strip().strip('"\'')
        check("%s empieza por familia concreta (%r)" % (name, first), first.lower() in GENERIC,
              False, failures)


def test_choice_is_validated(failures):
    check("pantón desconocido -> defecto", ui_theme.resolve("nope"), ui_theme.DEFAULT_ACCENT, failures)
    check("modo desconocido -> defecto", ui_theme.resolve_mode("sepia"), ui_theme.DEFAULT_MODE, failures)
    check("tipografía desconocida -> defecto", ui_theme.resolve_font("comic"), ui_theme.DEFAULT_FONT,
          failures)
    check("diseño desconocido -> defecto", ui_theme.resolve_skin("hud"), ui_theme.DEFAULT_SKIN, failures)
    check("cada diseño recomienda un pantón que existe",
          [row[3] for row in ui_theme.SKINS if row[3] not in ui_theme.ACCENT_KEYS], [], failures)
    original = onboarding.CONFIG_FILE
    with tempfile.TemporaryDirectory() as root:
        onboarding.CONFIG_FILE = Path(root) / "harness.json"
        try:
            for key, bogus in (("ui_theme", "cyberpunk"), ("ui_skin", "hud"),
                               ("ui_mode", "sepia"), ("ui_font", "comic")):
                _saved, notes = onboarding.save_settings({key: bogus})
                check("%s con errata no se guarda" % key, len(notes), 1, failures)
            check("y no se escribe el fichero", onboarding.CONFIG_FILE.is_file(), False, failures)
            saved, _notes = onboarding.save_settings(
                {"ui_skin": "matrix", "ui_theme": "crt", "ui_mode": "light", "ui_font": "mono"})
            check("los cuatro ejes se guardan juntos",
                  sorted(k for k in saved if k.startswith("ui_")),
                  ["ui_font", "ui_mode", "ui_skin", "ui_theme"], failures)
            written = json.loads(onboarding.CONFIG_FILE.read_text(encoding="utf-8"))
            check("y quedan en el fichero", written.get("ui_skin"), "matrix", failures)
        finally:
            onboarding.CONFIG_FILE = original


def test_density_moves_air_not_type(failures):
    """El quinto eje (`ui_density`) mueve padding y gap; si toca el tipo, no es densidad.

    Se comprueba sobre el CSS servido: cada densidad con su bloque, el bloque tocando las cuatro piezas
    del documento (hilo, mensaje, compositor y manual) con al menos diez reglas, y CERO declaraciones de
    `font-family`/`font-size` dentro de él. Y la errata no se guarda, igual que en los otros ejes.
    """
    css = (WEB / "density.css").read_text(encoding="utf-8")
    for key in ui_theme.DENSITY_KEYS:
        if key == ui_theme.DEFAULT_DENSITY:
            continue
        block = '[data-density="%s"]' % key
        check("%s tiene su bloque" % key, block in css, True, failures)
        check("%s toca al menos 10 reglas" % key, css.count(block) >= 10, True, failures)
        for selector in (".thread", ".msg", ".composer", ".settings-panel"):
            check("%s ajusta %s" % (key, selector), block + " " + selector in css, True, failures)
    # El fichero del eje no declara tipo en NINGUNA parte: si lo declarara, no sería densidad.
    for forbidden in ("font-family", "font-size"):
        check("density.css no declara %s (el eje es aire, no tipo)" % forbidden,
              forbidden in css, False, failures)
    check("la densidad por defecto no tiene bloque (es el aire de cada diseño)",
          css.count('[data-density="%s"]' % ui_theme.DEFAULT_DENSITY), 0, failures)
    check("densidad desconocida -> defecto", ui_theme.resolve_density("apretada"),
          ui_theme.DEFAULT_DENSITY, failures)
    original = onboarding.CONFIG_FILE
    with tempfile.TemporaryDirectory() as root:
        onboarding.CONFIG_FILE = Path(root) / "harness.json"
        try:
            _saved, notes = onboarding.save_settings({"ui_density": "apretada"})
            check("ui_density con errata no se guarda", len(notes), 1, failures)
            check("y no se escribe el fichero", onboarding.CONFIG_FILE.is_file(), False, failures)
            saved, _notes = onboarding.save_settings({"ui_density": "compacta"})
            check("densidad válida se guarda", saved.get("ui_density"), "compacta", failures)
        finally:
            onboarding.CONFIG_FILE = original


def run():
    failures = []
    test_every_game_reads(failures)
    test_css_is_generated(failures)
    test_skins_are_structural(failures)
    test_fonts_change_the_voice(failures)
    test_density_moves_air_not_type(failures)
    test_stacks_name_a_real_family_first(failures)
    test_choice_is_validated(failures)
    return failures
