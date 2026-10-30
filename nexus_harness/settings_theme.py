"""Panel de apariencia: cinco ejes, tarjetas con vista previa y un clic.

    modo (papel) · diseño (composición) · pantón (color) · tipografía (voz) · densidad (aire)

Antes cada eje era una lista de radios con su propio botón «Aplicar» al pie: había que seleccionar,
bajar y pulsar, y la opción no se parecía a lo que ibas a obtener. Ahora cada opción es una tarjeta que
enseña una muestra (papel y tinta, chips del pantón, un `Aa` con la voz, aire) y **se aplica al pulsarla**.
Un formulario por tarjeta: funciona sin script, como el resto de la pantalla.
"""
from html import escape

from . import settings_kit as kit
from . import ui_theme

TITLE = "Apariencia"
SUBTITLE = ("Cinco ejes independientes: el papel (oscuro o claro), la composición, el color, la voz y "
            "el aire. Cada tarjeta se aplica con un clic y no toca los otros ejes.")
GROUP_LABELS = (("main", "Principal"), ("special", "Especiales"), ("alt", "Alternativos"))


def _card(name, key, label, note, preview, current, extra=""):
    """Una opción como tarjeta-formulario: se ve lo que hace y se aplica al pulsarla."""
    on = key == current
    return ('<form class="themecard%s" method="post" action="/api/settings">'
            '%s%s<div class="tprev">%s</div>'
            '<span class="tname">%s</span><span class="tnote">%s</span>'
            '<span class="tmark" aria-hidden="true">%s</span>%s</form>'
            % (" on" if on else "", kit.hidden("section", "apariencia"),
               kit.hidden(name, key), preview, escape(label), escape(note),
               "OK" if on else "", extra))


def _skins(current):
    """Un solo grid para los cinco disenos: los rotulos de grupo van dentro y ocupan la fila entera.

    Antes cada grupo traia su propio grid y el de «Principal» (una sola tarjeta) se estiraba a lo ancho.
    """
    blocks = []
    for group, label in GROUP_LABELS:
        cards = [_card("ui_skin", skin,
                       name, "%s · par: %s" % (note, ui_theme.skin_palette(skin)),
                       '<span class="tsheet tsheet-%s"><i></i><i></i><i></i></span>' % escape(skin),
                       current)
                 for skin, name, note, _palette, grp in ui_theme.SKINS if grp == group]
        if cards:
            blocks.append('<p class="subgroup">%s</p>%s' % (escape(label), "".join(cards)))
    return '<div class="themegrid">%s</div>' % "".join(blocks)


def _modes(current):
    cards = []
    for mode, label in ui_theme.MODES:
        cards.append(_card("ui_mode", mode, label, "papel %s" % mode,
                           '<span class="tsheet tsheet-mode" data-preview="%s">Aa</span>'
                           % escape(mode), current))
    return '<div class="themegrid">%s</div>' % "".join(cards)


def _accents(current, mode):
    cards = []
    for key, name, note, swatches in ui_theme.ACCENTS:
        chips = "".join('<i class="sw" style="background:%s"></i>' % escape(color) for color in swatches)
        cards.append(_card("ui_theme", key, name, note,
                           '<span class="tswatch">%s</span><span class="tratio">tinta/papel %s:1</span>'
                           % (chips, ui_theme.contrast(mode, key)), current))
    return '<div class="themegrid">%s</div>' % "".join(cards)


def _fonts(current):
    cards = [_card("ui_font", key, label, note,
                   '<span class="tfont tfont-%s">Aa 123</span>' % escape(key), current)
             for key, label, note in ui_theme.FONTS]
    return '<div class="themegrid">%s</div>' % "".join(cards)


def _densities(current):
    cards = [_card("ui_density", key, label, note,
                   '<span class="tdense tdense-%s"><i></i><i></i><i></i></span>' % escape(key), current)
             for key, label, note in ui_theme.DENSITIES]
    return '<div class="themegrid">%s</div>' % "".join(cards)


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
            '<p class="shint">Se guardan por separado y se aplican al instante: cambiar el pantón no '
            'toca el diseño ni la voz. El modo no depende del sistema, lo eliges tú; la densidad mueve '
            'el aire, nunca el tipo.</p>'
            % (_skins(skin), _modes(mode), _accents(accent, mode), _fonts(font),
               _densities(density)))
    return (TITLE, SUBTITLE, body)
