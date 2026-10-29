"""El juego de iconos de la cabina: dieciseis simbolos SVG, inline y sin dependencias.

Por que un sprite y no emojis: un emoji cambia de forma en cada sistema operativo, no se alinea con
la linea de texto, no hereda el color y no se puede medir. Un `<symbol>` con `stroke-width: 1.5` y
`currentColor` se ve igual en Windows, Linux y macOS, se alinea con `vertical-align` y obedece al tono
semantico que le ponga el CSS.

Se sirve inline en las dos paginas (`ui_icons.sprite()` dentro de `<body>`), no como fichero externo:
`<use>` sobre otro documento no hereda `currentColor`, y ademas una pagina que necesita la red para
verse bien esta rota en un avion.

Reglas del dibujo: caja 24x24, trazo 1.5, sin relleno, esquinas redondeadas, un solo nivel de detalle.
Dieciseis iconos, ni uno mas: si un decimoséptimo parece necesario, se reutiliza uno.
"""
from html import escape

SYMBOLS = {
    # marca
    "nexus": '<path d="M12 3l7.5 4.3v9.4L12 21l-7.5-4.3V7.3z"/><path d="M12 8.4l3.6 2.1v4.2L12 16.8'
             'l-3.6-2.1v-4.2z"/>',
    # configuracion: tres mandos
    "sliders": '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/>'
               '<circle cx="10" cy="17" r="2"/>',
    # gobernanza / seguridad
    "shield": '<path d="M12 3l7 3v5.6c0 4.3-2.9 7.9-7 9.4-4.1-1.5-7-5.1-7-9.4V6z"/>'
              '<path d="M9 12l2.2 2.2L15.5 10"/>',
    # espacio de trabajo / proyectos
    "folder": '<path d="M3 7.5A1.5 1.5 0 014.5 6h4l2 2.5h7A1.5 1.5 0 0119 10v7.5A1.5 1.5 0 0117.5 19'
              'h-13A1.5 1.5 0 013 17.5z"/>',
    # modelos, autonomia, vps
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5"'
           ' rx="1"/><path d="M10 3v3M14 3v3M10 18v3M14 18v3M3 10h3M3 14h3M18 10h3M18 14h3"/>',
    # memoria, estadisticas
    "layers": '<path d="M12 3.5l8 4.2-8 4.3-8-4.3z"/><path d="M4 12.2l8 4.3 8-4.3"/>'
              '<path d="M4 16.4l8 4.3 8-4.3"/>',
    # skills
    "bolt": '<path d="M13.2 3L6 13.4h4.6L10 21l7.4-10.6h-4.7z"/>',
    # conectores MCP / puente movil
    "plug": '<path d="M9 3v5M15 3v5"/><path d="M6.5 8h11v3.5a5.5 5.5 0 01-11 0z"/>'
            '<path d="M12 17v4"/>',
    # buscar
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
    # cerrar / descartar
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    # enviar
    "send": '<path d="M4 12l16-7-7 16-2.4-6.4z"/><path d="M13.6 10.4L20 5"/>',
    # detener
    "stop": '<rect x="7" y="7" width="10" height="10" rx="1.6"/>',
    # adjuntar
    "paperclip": '<path d="M9 12.5l5.4-5.4a2.6 2.6 0 013.7 3.7l-7.6 7.6a4 4 0 01-5.7-5.7l7-7"/>',
    # veredicto: decision tomada
    "check": '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12.2l2.4 2.4 4.6-5"/>',
    # veredicto: espera a una persona / no verificable
    "alert": '<path d="M12 4.5l8.2 14.2H3.8z"/><path d="M12 10v4"/><path d="M12 16.6v.1"/>',
    # veredicto: detectado / roto
    "xcircle": '<circle cx="12" cy="12" r="8.5"/><path d="M9.2 9.2l5.6 5.6M14.8 9.2l-5.6 5.6"/>',
}

STYLE = "fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round"


def sprite():
    """El sprite entero, oculto: `<svg><symbol id="i-search">…` y un `icon('search')` en cada sitio."""
    body = "".join('<symbol id="i-%s" viewBox="0 0 24 24">%s</symbol>' % (name, path)
                   for name, path in SYMBOLS.items())
    return ('<svg class="sprite" aria-hidden="true" focusable="false" width="0" height="0" '
            'style="position:absolute;overflow:hidden">%s</svg>' % body)


def icon(name, cls="", label=""):
    """Un icono a tamano del texto. `label` solo cuando el icono es la unica etiqueta del control."""
    if name not in SYMBOLS:
        return ""
    name = escape(name)
    hidden = '' if label else ' aria-hidden="true"'
    title = '<title>%s</title>' % escape(label) if label else ""
    return ('<svg class="icon %s" viewBox="0 0 24 24" style="%s"%s>%s'
            '<use href="#i-%s"/></svg>' % (escape(cls), STYLE, hidden, title, name))
