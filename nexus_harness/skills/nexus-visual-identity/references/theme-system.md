# Cómo se cablea un tema (mapa de ficheros)

Un tema es **un juego de tokens**, no otra pantalla. El servidor decide cuál se sirve; el navegador no
elige nada por su cuenta (un toggle en JS que se olvida al recargar es una mentira).

| pieza | fichero | responsabilidad |
|---|---|---|
| metadatos + tokens + contraste | `nexus_harness/ui_theme.py` | `THEMES`, `TOKENS`, `resolve()`, `ratio()`, `contrast()` |
| CSS de los temas | `nexus_harness/web/themes.css` | un bloque `[data-theme="clave"]` por pantón |
| defecto | `nexus_harness/config.py` | `ui_theme: str = "neon"` (y en `DEFAULTS`) |
| guardado validado | `nexus_harness/onboarding.py` | `save_settings({"ui_theme": …})` rechaza claves desconocidas |
| inyección | `nexus_harness/ui.py` | `data-theme` en `<html>` del chat y de la configuración |
| selector | `nexus_harness/settings_theme.py` + `§ Apariencia` | radios que postean `ui_theme` → 303 |
| prueba | `nexus_harness/selftests/test_themes.py` | contraste WCAG, cobertura del CSS, validación |

## Flujo de una elección

1. `§ Apariencia` pinta un `<form method="post" action="/api/settings">` con un radio por tema.
2. `settings.save(..., section="apariencia")` llama a `onboarding.save_settings({"ui_theme": key})`.
3. La lista blanca valida la clave; si no existe, **no escribe** y la nota sale en rojo.
4. `cockpit.reload_config()` relee `harness.json`.
5. `ui.py` sirve las páginas con `data-theme="clave"`; `themes.css` hace el resto.
6. Respuesta `303` de vuelta al panel, con el token: recargar no reenvía el formulario.

## Reglas de implementación

- La estructura no se toca: masthead, índice, folios, reglas de 1px y los cuatro tonos son iguales en
  los seis temas. Si un tema necesita mover algo, el tema está mal, no la estructura.
- Las texturas (scanlines, glow) son **overlay** con `pointer-events:none`, nunca fondo del contenedor
  de texto.
- Un color literal en un componente es un defecto: los componentes leen tokens. La única excepción
  conocida son las tarjetas del arnés dentro de `/gov` (documento ajeno) que usan valores literales a
  propósito.
- `data-theme` va en `<html>`: se aplica antes del primer pintado y no hay parpadeo al recargar.
