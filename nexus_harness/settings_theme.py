"""Panel de apariencia: cinco ejes, cinco selectores, un solo sitio.

    modo (papel) · diseño (composición) · pantón (color) · tipografía (voz) · densidad (aire)

Cada eje se elige por separado, con su formulario y su 303, y se guarda en su clave (`ui_mode`,
`ui_skin`, `ui_theme`, `ui_font`, `ui_density`) que valida `onboarding`. El diseño se presenta agrupado:
uno principal, dos especiales que cambian el esqueleto, y los alternativos.
"""
from html import escape

from . import settings_kit as kit
from . import ui_theme

TITLE = "Apariencia"
SUBTITLE = ("Cinco ejes independientes: el papel (oscuro o claro), la composición, el color, la voz y "
            "el aire. Cambiar uno no toca los otros.")
GROUP_LABELS = (("main", "Principal"), ("special", "Especiales"), ("alt", "Alternativos"))


def _radio(name, key, current):
    return ' checked' if key == current else ''


def _option(name, key, label, note, extra, current, css="themeopt"):
    return ('<label class="%s%s"><input type="radio" name="%s" value="%s"%s>'
            '<span class="tname">%s</span><span class="tnote">%s</span>'
            '<span class="tratio">%s</span></label>'
            % (css, " on" if key == current else "", name, escape(key), _radio(name, key, current),
               escape(label), escape(note), extra))


def _form(rows, submit):
    return ('<form class="sform themegrid" method="post" action="/api/settings">%s%s'
            '<div class="sactions"><button class="primary">%s</button></div></form>'
            % (kit.hidden("section", "apariencia"), "".join(rows), escape(submit)))


def _skins(current):
    blocks = []
    for key, label in GROUP_LABELS:
        rows = [_option("ui_skin", skin, name, note, "par: %s" % ui_theme.skin_palette(skin), current)
                for skin, name, note, _palette, group in ui_theme.SKINS if group == key]
        if rows:
            blocks.append('<p class="subgroup">%s</p>%s' % (escape(label), "".join(rows)))
    return _form(blocks, "Aplicar diseño")


def _modes(current):
    rows = [_option("ui_mode", mode, label, "papel %s" % mode, "", current)
            for mode, label in ui_theme.MODES]
    return _form(rows, "Aplicar modo")


def _accents(current, mode):
    rows = []
    for key, name, note, swatches in ui_theme.ACCENTS:
        chips = "".join('<i class="sw" style="background:%s"></i>' % escape(color) for color in swatches)
        rows.append(_option("ui_theme", key, name, note,
                            '<span class="tswatch">%s</span> tinta/papel %s:1'
                            % (chips, ui_theme.contrast(mode, key)), current))
    return _form(rows, "Aplicar pantón")


def _fonts(current):
    rows = [_option("ui_font", key, label, note, "", current)
            for key, label, note in ui_theme.FONTS]
    return _form(rows, "Aplicar tipografía")


def _densities(current):
    rows = [_option("ui_density", key, label, note, "", current)
            for key, label, note in ui_theme.DENSITIES]
    return _form(rows, "Aplicar densidad")


def panel(cockpit):
    config = cockpit.config
    skin = ui_theme.resolve_skin(config.ui_skin)
    mode = ui_theme.resolve_mode(config.ui_mode)
    accent = ui_theme.resolve(config.ui_theme)
    font = ui_theme.resolve_font(config.ui_font)
    density = ui_theme.resolve_density(config.ui_density)
    body = ('<h3 class="ssub">01 · Diseño</h3>%s'
            '<h3 class="ssub">02 · Modo</h3>%s'
            '<h3 class="ssub">03 · Pantón</h3>%s'
            '<h3 class="ssub">04 · Tipografía</h3>%s'
            '<h3 class="ssub">05 · Densidad</h3>%s'
            '<p class="shint">Se guardan por separado: cambiar el pantón no toca el diseño ni la voz. '
            'El modo no depende del sistema: lo eliges tú. La densidad mueve el aire (padding y gap), '
            'nunca el tipo.</p>'
            % (_skins(skin), _modes(mode), _accents(accent, mode), _fonts(font),
               _densities(density)))
    return (TITLE, SUBTITLE, body)
