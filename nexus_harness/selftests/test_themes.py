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
        check("la tipografía %s tiene su regla" % key, '[data-font="%s"]' % key in css, True, failures)


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


def run():
    failures = []
    test_every_game_reads(failures)
    test_css_is_generated(failures)
    test_skins_are_structural(failures)
    test_fonts_change_the_voice(failures)
    test_choice_is_validated(failures)
    return failures
