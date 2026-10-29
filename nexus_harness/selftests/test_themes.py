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


def test_choice_is_validated(failures):
    check("un tema desconocido resuelve al de por defecto", ui_theme.resolve("nope"),
          ui_theme.DEFAULT, failures)
    check("y el de por defecto existe", ui_theme.DEFAULT in ui_theme.KEYS, True, failures)
    original = onboarding.CONFIG_FILE
    with tempfile.TemporaryDirectory() as root:
        onboarding.CONFIG_FILE = Path(root) / "harness.json"
        try:
            _saved, notes = onboarding.save_settings({"ui_theme": "cyberpunk"})
            check("un tema con errata no se guarda", len(notes), 1, failures)
            check("y no se escribe el fichero", onboarding.CONFIG_FILE.is_file(), False, failures)
            saved, _notes = onboarding.save_settings({"ui_theme": "crt"})
            check("uno que existe sí", saved.get("ui_theme"), "crt", failures)
            written = json.loads(onboarding.CONFIG_FILE.read_text(encoding="utf-8"))
            check("y queda en el fichero", written.get("ui_theme"), "crt", failures)
        finally:
            onboarding.CONFIG_FILE = original


def run():
    failures = []
    test_every_theme_reads(failures)
    test_css_covers_every_theme(failures)
    test_choice_is_validated(failures)
    return failures
