"""Panel de apariencia: los pantones de la cabina, con sus muestras y su contraste medido.

Un tema es un juego de tokens (`web/themes.css`); elegir uno guarda `ui_theme` y vuelve (303). La
estructura no cambia —masthead, índice, folios, reglas—: lo que cambia es el vestido. Y cada pantón
declara su contraste tinta/papel, que es el número que separa un color bonito de un color legible.
"""
from html import escape

from . import settings_kit as kit
from . import ui_theme

TITLE = "Apariencia"
SUBTITLE = ("Seis pantones para el mismo documento. El color y la textura cambian; la composición no. "
            "El contraste está medido, no estimado: tinta sobre papel, WCAG.")


def _card(key, name, note, swatches, current):
    """Una opción del selector: radio nativo (funciona sin script) + muestras + contraste medido."""
    checked = " checked" if key == current else ""
    chips = "".join('<i class="sw" style="background:%s"></i>' % escape(color) for color in swatches)
    return ('<label class="themeopt%s"><input type="radio" name="ui_theme" value="%s"%s>'
            '<span class="tname">%s</span><span class="tswatch">%s</span>'
            '<span class="tnote">%s</span>'
            '<span class="tratio">tinta/papel %s:1</span></label>'
            % (" on" if key == current else "", escape(key), checked, escape(name), chips,
               escape(note), ui_theme.contrast(key)))


def panel(cockpit):
    current = ui_theme.resolve(getattr(cockpit.config, "ui_theme", ""))
    cards = "".join(_card(*row, current) for row in ui_theme.THEMES)
    body = ('<form class="sform themegrid" method="post" action="/api/settings">%s%s'
            '<div class="sactions"><button class="primary">Aplicar pantón</button></div></form>'
            % (kit.hidden("section", "apariencia"), cards))
    return (TITLE, SUBTITLE, body)
