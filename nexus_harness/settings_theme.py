"""Panel de apariencia: DOS ejes, dos selectores.

Lo aprendido de Hermes (skin != personalidad), OpenCode (temas como tokens) y Crush (layout != color):
el DISEÑO y el PANTÓN son decisiones separadas. Aquí se eligen por separado, cada una con su formulario
y su 303, y se guardan en claves distintas (`ui_skin`, `ui_theme`) que valida `onboarding`.

Cada diseño declara el pantón con el que se pensó (recomendación, no candado: 4 x 6 = 24 válidas).
"""
from html import escape

from . import settings_kit as kit
from . import ui_theme

TITLE = "Apariencia"
SUBTITLE = ("El diseño cambia la composición —tipografía, densidad, dónde vive el estado—; el pantón "
            "cambia el color. Son ejes independientes: cualquier diseño funciona con cualquier pantón.")


def _card(kind, key, name, note, extra, current):
    """Una opción: radio nativo (funciona sin script) + nombre + intención + dato medido."""
    checked = " checked" if key == current else ""
    return ('<label class="themeopt%s"><input type="radio" name="%s" value="%s"%s>'
            '<span class="tname">%s</span><span class="tnote">%s</span>'
            '<span class="tratio">%s</span></label>'
            % (" on" if key == current else "", kind, escape(key), checked, escape(name),
               escape(note), extra))


def _skins(current):
    rows = []
    for key, name, note, palette in ui_theme.SKINS:
        extra = "par sugerido: %s" % ui_theme.skin_palette(key)
        rows.append(_card("ui_skin", key, name, note, extra, current))
    return ('<form class="sform themegrid" method="post" action="/api/settings">%s%s'
            '<div class="sactions"><button class="primary">Aplicar diseño</button></div></form>'
            % (kit.hidden("section", "apariencia"), "".join(rows)))


def _themes(current):
    rows = []
    for key, name, note, swatches in ui_theme.THEMES:
        chips = "".join('<i class="sw" style="background:%s"></i>' % escape(color) for color in swatches)
        rows.append(_card("ui_theme", key, name, note,
                          '<span class="tswatch">%s</span> tinta/papel %s:1'
                          % (chips, ui_theme.contrast(key)), current))
    return ('<form class="sform themegrid" method="post" action="/api/settings">%s%s'
            '<div class="sactions"><button class="primary">Aplicar pantón</button></div></form>'
            % (kit.hidden("section", "apariencia"), "".join(rows)))


def panel(cockpit):
    skin = ui_theme.resolve_skin(getattr(cockpit.config, "ui_skin", ""))
    theme = ui_theme.resolve(getattr(cockpit.config, "ui_theme", ""))
    body = ('<h3 class="ssub">01 · Diseño</h3>%s'
            '<h3 class="ssub">02 · Pantón</h3>%s'
            '<p class="shint">Se guardan por separado: cambiar de pantón no toca el diseño, y al revés.</p>'
            % (_skins(skin), _themes(theme)))
    return (TITLE, SUBTITLE, body)
