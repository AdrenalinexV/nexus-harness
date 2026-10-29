"""Los seis pantones: contraste medido, cobertura del CSS y elección validada.

Un tema es un juego de tokens. Lo que se afirma aquí no es "queda bonito": es que cada pantón se lee
(WCAG), que el CSS tiene su bloque, que define los tokens que la cabina usa, y que un `ui_theme` con
una errata no se guarda en silencio.
"""
import json
import tempfile
from pathlib import Path

from .. import onboarding, ui_theme

# Umbrales: tinta principal AAA (7:1), secundaria AA (4.5:1), estados AA para elementos no textuales.
MIN_TEXT, MIN_SECOND, MIN_STATE = 7.0, 4.5, 3.0
# (clave en TOKENS, nombre real en el CSS)
CORE = (("paper", "--paper"), ("ink", "--ink"), ("ink2", "--ink-2"), ("seal", "--seal"))
CSS = Path(__file__).resolve().parents[1] / "web" / "themes.css"
SKINS_CSS = Path(__file__).resolve().parents[1] / "web" / "skins.css"
# Un diseño que solo cambia colores no es un diseño: tiene que tocar tipografía, rejilla y mensaje.
SKIN_MUST = (".title", ".app", ".msg", ".sfield")


def check(name, got, expect, failures):
    if got != expect:
        failures.append("%s: %r, esperaba %r" % (name, got, expect))


def test_every_theme_reads(failures):
    for key in ui_theme.KEYS:
        tokens = ui_theme.TOKENS[key]
        paper = tokens["paper"]
        ratio = ui_theme.ratio(tokens["ink"], paper)
        check("%s: tinta sobre papel >= %s:1" % (key, MIN_TEXT), ratio >= MIN_TEXT, True, failures)
        second = ui_theme.ratio(tokens["ink2"], paper)
        check("%s: tinta-2 >= %s:1" % (key, MIN_SECOND), second >= MIN_SECOND, True, failures)
        for state in ("ok", "warn", "bad", "seal"):
            value = ui_theme.ratio(tokens[state], paper)
            check("%s: %s sobre papel >= %s:1" % (key, state, MIN_STATE), value >= MIN_STATE,
                  True, failures)


def test_css_covers_every_theme(failures):
    css = CSS.read_text(encoding="utf-8")
    for key in ui_theme.KEYS:
        block = '[data-theme="%s"] {' % key
        check("%s tiene su bloque en themes.css" % key, block in css, True, failures)
        start = css.find(block)
        body = css[start:css.find("}", start)]
        for _field, token in CORE:
            check("%s define %s" % (key, token), (token + ":") in body, True, failures)


def test_skins_are_structural(failures):
    """Cada diseño cambia ESTRUCTURA, no solo color: título, rejilla, mensaje y campo."""
    css = SKINS_CSS.read_text(encoding="utf-8")
    for key in ui_theme.SKIN_KEYS:
        if key == ui_theme.DEFAULT_SKIN:
            check("el diseño base se declara", '01 · document' in css, True, failures)
            continue
        block = '[data-skin="%s"]' % key
        check("%s tiene su bloque" % key, block in css, True, failures)
        rules = css.count(block)
        check("%s toca al menos 10 reglas (no es un pantón)" % key, rules >= 10, True, failures)
        for selector in SKIN_MUST:
            check("%s redefine %s" % (key, selector), (block + " " + selector) in css, True, failures)


def test_choice_is_validated(failures):
    check("un tema desconocido resuelve al de por defecto", ui_theme.resolve("nope"),
          ui_theme.DEFAULT, failures)
    check("un diseño desconocido resuelve al de por defecto", ui_theme.resolve_skin("nope"),
          ui_theme.DEFAULT_SKIN, failures)
    check("cada diseño recomienda un pantón que existe",
          [row[3] for row in ui_theme.SKINS if row[3] not in ui_theme.KEYS], [], failures)
    check("y el de por defecto existe", ui_theme.DEFAULT in ui_theme.KEYS, True, failures)
    original = onboarding.CONFIG_FILE
    with tempfile.TemporaryDirectory() as root:
        onboarding.CONFIG_FILE = Path(root) / "harness.json"
        try:
            _saved, notes = onboarding.save_settings({"ui_theme": "cyberpunk"})
            check("un tema con errata no se guarda", len(notes), 1, failures)
            check("y no se escribe el fichero", onboarding.CONFIG_FILE.is_file(), False, failures)
            _saved, notes = onboarding.save_settings({"ui_skin": "hud"})
            check("un diseño con errata no se guarda", len(notes), 1, failures)
            saved, _notes = onboarding.save_settings({"ui_skin": "neon", "ui_theme": "crt"})
            check("diseño y pantón se guardan juntos",
                  sorted(k for k in saved if k in ("ui_skin", "ui_theme")), ["ui_skin", "ui_theme"],
                  failures)
            check("uno que existe sí", saved.get("ui_theme"), "crt", failures)
            written = json.loads(onboarding.CONFIG_FILE.read_text(encoding="utf-8"))
            check("y queda en el fichero", written.get("ui_theme"), "crt", failures)
        finally:
            onboarding.CONFIG_FILE = original


def run():
    failures = []
    test_every_theme_reads(failures)
    test_css_covers_every_theme(failures)
    test_skins_are_structural(failures)
    test_choice_is_validated(failures)
    return failures
