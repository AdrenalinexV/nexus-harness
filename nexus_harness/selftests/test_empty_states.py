"""Los estados vacios de /settings dicen QUE HACER, no solo que no hay nada.

Un «ninguno.» a secas se lee como una pantalla rota: el estado vacio es la primera pantalla de un
operador nuevo y la ultima que ve cuando algo falla. Los tres peores (skills sin skills, VPS sin claves
y MCP sin servidores) dicen la accion siguiente en el MISMO parrafo; lo que se afirma aqui es esa
frase, no la existencia de un panel.
"""
import tempfile
import types
from pathlib import Path

from .. import settings_kit as kit
from .. import settings_skills, settings_tools, settings_vps
from ..tools import mcp_client


def check(name, got, expect, failures):
    if got != expect:
        failures.append("%s: %r, esperaba %r" % (name, got, expect))


class _Cockpit:
    """Lo minimo que un panel toca cuando no hay nada que enseñar."""

    def __init__(self, root):
        self.root = Path(root)
        self.config = types.SimpleNamespace(workspace=Path(root))

    def state(self):
        return {"chat": {"last": {}}}


def _body(panel):
    """Un panel devuelve `(titulo, subtitulo, cuerpo)`; el cuerpo es lo que se mide."""
    return panel[2] if isinstance(panel, tuple) else panel


def test_helper_keeps_both_halves(failures):
    """El hueco y su salida van juntos: una mitad sola no es un estado vacio, es media pantalla."""
    html = kit.empty("no hay nada", "pulsa Guardar.")
    check("el hueco lleva su frase", "no hay nada" in html, True, failures)
    check("y la accion siguiente", "pulsa Guardar." in html, True, failures)
    check("con su clase propia", 'class="sempty"' in html, True, failures)


def test_skills_empty_names_the_next_step(failures):
    root = tempfile.mkdtemp(prefix="nexus-empty-skills-")
    original_catalog, original_roots = settings_skills.catalog, settings_skills.roots
    settings_skills.catalog = lambda cockpit: []
    settings_skills.roots = lambda cockpit: []
    try:
        page = _body(settings_skills.skills(_Cockpit(root), {}))
    finally:
        settings_skills.catalog, settings_skills.roots = original_catalog, original_roots
    check("skills sin skills lo dice", "Todavía no hay ninguna skill" in page, True, failures)
    check("y nombra el boton que lo llena", "Diseñar y Forjar Skill" in page, True, failures)


def test_mcp_empty_names_the_next_step(failures):
    root = tempfile.mkdtemp(prefix="nexus-empty-mcp-")
    original_load, original_status = mcp_client.load_config, settings_tools.panels.mcp_status
    mcp_client.load_config = lambda: {"servers": {}}
    settings_tools.panels.mcp_status = lambda cockpit: {"tools": 0, "servers": []}
    try:
        page = _body(settings_tools.mcp(_Cockpit(root)))
    finally:
        mcp_client.load_config = original_load
        settings_tools.panels.mcp_status = original_status
    check("mcp sin servidores lo dice", "Todavía no hay ningún conector MCP" in page, True, failures)
    check("y nombra el boton que lo guarda", "Guardar conector y recargar" in page, True, failures)


def test_vps_empty_names_the_next_step(failures):
    """El VPS sin claves no puede ofrecer un boton que fallaria: dice que clave falta y donde se pone."""

    class _Config:
        missing = ("VPS_HOST", "VPS_SSH_KEY")
        target = ""
        port = ""
        host = ""
        user = ""

    class _Deployer:
        def plan(self):
            return []

    original = settings_vps._deployer
    settings_vps._deployer = lambda: (_Config(), _Deployer())
    try:
        page = _body(settings_vps.page(_Cockpit(tempfile.mkdtemp(prefix="nexus-empty-vps-"))))
    finally:
        settings_vps._deployer = original
    check("vps sin claves lo dice", "Faltan credenciales en la bóveda" in page, True, failures)
    check("y nombra el boton que las guarda", "pulsa Guardar" in page, True, failures)


def run():
    failures = []
    test_helper_keeps_both_halves(failures)
    test_skills_empty_names_the_next_step(failures)
    test_mcp_empty_names_the_next_step(failures)
    test_vps_empty_names_the_next_step(failures)
    return failures
