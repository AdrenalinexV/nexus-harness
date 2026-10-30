"""Los paneles laterales del cockpit (onboarding, MCP, skills, daemon), fuera del bucle.

Vivian dentro de `cockpit.py`, que llego a 396 lineas justo cuando el tablero Kanvas necesitaba dos
metodos mas (`reserve`/`release`). Son diez lineas de fontaneria que delegan en `panels`: no deciden
nada, asi que se van enteras -- mismo trato que `context/accounting.py` con el chat.
"""
from . import panels


class Panels:
    """La cara que la API usa para los paneles: estado, y una accion por cada uno."""

    def onboarding_state(self):
        return panels.onboarding_status(self)

    def onboarding_apply(self, payload):
        return panels.onboarding_apply(self, payload)

    def mcp_state(self):
        return panels.mcp_status(self)

    def mcp_reload(self):
        self.mcp()
        return panels.mcp_reload(self)

    def skills_list(self):
        return panels.skills_list(self)

    def skill_read(self, name):
        return panels.skills_read(self, name)

    def skill_save(self, name, text):
        return panels.skills_save(self, name, text)

    def daemon_state(self):
        return panels.daemon_status(self)

    def daemon_toggle(self, provider=""):
        return panels.daemon_toggle(self, provider or "telegram")

    def daemon_stop(self):
        return panels.daemon_stop(self)
