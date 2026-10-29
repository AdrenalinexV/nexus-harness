"""Navegador nativo: extrae texto de una pagina real, recorta con recibo y declara los muros.

Lo que se mide, sin red: una pagina local servida por `file://` es suficiente para probar la fontaneria
(extraccion, enlaces, recorte, deteccion de bloqueo y cierre). Si no hay motor de navegador en la
maquina, la suite lo dice: un navegador que no existe no puede pasar como verde.
"""
import sys
import tempfile
from pathlib import Path

from . import Skip
from .fakes import TempProject
from ..config import HarnessConfig
from ..tools.toolbox import browser


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def _page(root, name, body):
    path = Path(root) / (name if name.endswith(".html") else name + ".html")
    path.write_text("<!doctype html><html><head><title>%s</title></head><body>%s</body></html>"
                    % (name, body), encoding="utf-8")
    return path.as_uri()


def test_the_module_selftest(failures):
    for problem in browser.selftest():
        failures.append("browser.selftest: %s" % problem)


def test_a_real_page_becomes_text(failures):
    with TempProject() as root:
        url = _page(root, "hola", "<h1>Hola Nexus</h1><p>Un parrafo con <b>negrita</b>.</p>"
                                 "<a href='https://example.com/x'>un enlace</a>")
        text, meta = browser.run(root, {"action": "goto", "url": url},
                                 HarnessConfig(default_root=root))
        check("el titulo viaja", "hola" in meta["title"], True, failures)
        check("el texto esta", "Hola Nexus" in text, True, failures)
        check("sin etiquetas", "<h1>" in text, False, failures)
        check("y los enlaces se listan", "example.com/x" in text, True, failures)
        check("el estado es 200", meta["status"], 200, failures)
        check("no esta bloqueada", meta["blocked"], "", failures)


def test_the_text_is_truncated_with_a_receipt(failures):
    with TempProject() as root:
        url = _page(root, "largo", "<p>" + ("palabra " * 4000) + "</p>")
        text, meta = browser.run(root, {"action": "goto", "url": url, "max_chars": 600},
                                 HarnessConfig(default_root=root))
        check("se recorta", meta["truncated"], True, failures)
        check("y lo dice", "recortado" in text, True, failures)
        check("sin pasarse del techo", len(text) < 1200, True, failures)


def test_a_wall_is_an_error_not_a_fake_answer(failures):
    with TempProject() as root:
        url = _page(root, "muro", "<h1>Just a moment...</h1><p>Checking your browser</p>")
        try:
            browser.run(root, {"action": "goto", "url": url}, HarnessConfig(default_root=root))
            failures.append("un muro anti-bot no puede devolver texto como si fuera la pagina")
        except ValueError as exc:
            check("dice que hay muro", "anti-bot" in str(exc), True, failures)
            check("y sugiere salida", "fetch_url" in str(exc), True, failures)


def test_extract_keeps_only_matching_lines(failures):
    with TempProject() as root:
        url = _page(root, "precios", "<p>portatil 900 euros</p><p>raton 20 euros</p>"
                                     "<p>monitor 300 euros</p>")
        browser.run(root, {"action": "goto", "url": url}, HarnessConfig(default_root=root))
        text, meta = browser.run(root, {"action": "extract", "text": "raton"},
                                 HarnessConfig(default_root=root))
        check("solo la linea pedida", "raton" in text and "portatil" not in text, True, failures)
        check("y cuenta las coincidencias", meta["matches"], 1, failures)


def test_close_and_unknown_action(failures):
    with TempProject() as root:
        url = _page(root, "simple", "<p>hola</p>")
        browser.run(root, {"action": "goto", "url": url}, HarnessConfig(default_root=root))
        text, _meta = browser.run(root, {"action": "close"}, HarnessConfig(default_root=root))
        check("se cierra", "cerrado" in text, True, failures)
        again, _meta = browser.run(root, {"action": "close"}, HarnessConfig(default_root=root))
        check("cerrar dos veces no rompe", "no habia" in again, True, failures)
        try:
            browser.run(root, {"action": "volar"}, HarnessConfig(default_root=root))
            failures.append("una accion desconocida tiene que fallar")
        except ValueError as exc:
            check("y se explica", "accion desconocida" in str(exc), True, failures)


def test_the_tool_is_in_the_arsenal(failures):
    from ..tools import default_registry
    with TempProject() as root:
        registry = default_registry(root, HarnessConfig(default_root=root))
        check("el modelo ve browser", "browser" in registry.names(), True, failures)
        observation = registry.call("browser", {"action": "close"})
        check("y una accion inocua no falla", observation.ok, True, failures)


def _frozen_without_engine():
    """El .exe no empaqueta Playwright (pesa cientos de MB): se exige que lo DIGA, no que navegue."""
    if not getattr(sys, "frozen", False) or browser.available():
        return []
    try:
        browser.run(".", {"action": "goto", "url": "about:blank"})
    except browser.BrowserError as exc:
        if "playwright" in str(exc) or "motor" in str(exc):
            return []
        return ["sin motor, el mensaje no dice como arreglarlo: %s" % exc]
    return ["sin motor de navegador, la herramienta no declaro la ausencia"]


def run():
    declared = _frozen_without_engine()
    if declared:
        return list(declared)
    if getattr(sys, "frozen", False) and not browser.available():
        # El .exe no lleva motor y `_frozen_without_engine` ya exigio que lo dijera: aqui se lee la
        # ausencia declarada, no se finge una medicion.
        return []
    if not browser.available():
        raise Skip("no hay motor de navegador en esta maquina (Edge/Chrome del sistema o "
                   "`playwright install chromium`): la fontaneria no se puede medir aqui")
    failures = []
    test_the_module_selftest(failures)
    test_a_real_page_becomes_text(failures)
    test_the_text_is_truncated_with_a_receipt(failures)
    test_a_wall_is_an_error_not_a_fake_answer(failures)
    test_extract_keeps_only_matching_lines(failures)
    test_close_and_unknown_action(failures)
    test_the_tool_is_in_the_arsenal(failures)
    return failures
