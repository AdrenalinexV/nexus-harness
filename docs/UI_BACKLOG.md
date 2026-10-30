# Cola de trabajo — cabina (UI/UX/GUI)

> Cola determinista para el bucle autónomo. **Una tarea por pasada.** Cada tarea trae su criterio de
> aceptación y el comando que lo demuestra; una tarea sin comando no entra en la cola.
>
> Reglas de la pasada (léelas antes de tocar nada):
> 1. `git -C C:/Proyectos/Nexus-Harness status --porcelain` debe estar vacío. Si no, `git checkout -- .`
>    y sigue: una pasada nunca empieza con trabajo a medias de otra.
> 2. Backup antes de editar: `git tag -f backup-<id>` (el commit anterior ya es el backup real).
> 3. Ley del repo: ningún fichero > **400 líneas**; **0 emojis**; sin CDN/webfonts; toda cifra se lee
>    de `/api/*`; las claves de color solo en `themes.css` (generado).
> 4. Verificar SIEMPRE con `python tools/gen_themes.py --check` y
>    `NEXUS_PROTOCOL='C:\Proyectos\NexusProtocol' python tools/verify.py` → exit 0.
> 5. Si verify falla: `git checkout -- .` y marca la tarea **BLOQUEADA** con la primera línea del error.
>    No dejes el árbol sucio.
> 6. Al terminar: commit pequeño con la verificación en el mensaje, `git push`, y marca la casilla con
>    el hash. Si no quedan tareas, responde «cola vacía» y no hagas nada más.

## Cola

- [x] **U-01 · Copiar mensaje** — botón `copiar` por mensaje del asistente, con `navigator.clipboard` y
  caída a `execCommand`; feedback `copiado` y vuelta a `copiar` a los 1,6 s. Hecho en `123a424`+ (ver
  `chat_stream.js`, `.copy` en `app.css`). *Verificado con clic real (CDP): label `copiado`.*

- [ ] **U-02 · Banda de reintento** — si `/api/state` falla 3 veces seguidas, mostrar la banda `#warn`
  con el texto «motor sin respuesta · Reintentar» y un botón que reintente ya. Aceptación: con el motor
  apagado aparece en ≤8 s; al volver, desaparece. Verificación: navegador (apagar/encender el servidor).

- [ ] **U-03 · Exportar el hilo a Markdown** — botón `Exportar` en `.doc-head`; genera un `.md` con
  `## folio NN · ROL`, el texto y las herramientas, y lo descarga con `Blob`. Aceptación: el blob
  empieza por `# ` + título y contiene `folio 01`. Verificación: JS (crear el blob y leer los primeros
  80 caracteres).

- [ ] **U-04 · Sección «Acerca de»** (`§11`, `settings_about.py`) — versión, `api`, host:puerto, raíz,
  uptime y un botón `Comprobar` que llama a `/api/health` y pinta el resultado. Aceptación: 200 con `h1`
  propio y `test_ui_contract` sigue verde (el índice pasa a 16 destinos). Verificación: curl + suite.

- [x] **U-05 · Hoja de atajos** — `?` abre un `<dialog>` con Ctrl+Enter, Esc, Ctrl+K, `?` y los ejes de
  apariencia; sin dependencias. Aceptación: pulsar `?` (tecla real) abre `dialog[open]`. Verificación:
  CDP `Input.dispatchKeyEvent`.

- [ ] **U-06 · Densidad** — eje `ui_density` (`normal` | `compacta`): la compacta reduce aire (padding y
  gap) sin cambiar tipos. Aceptación: `data-density` servido y altura del hilo distinta ≥10 %.
  Verificación: navegador (medir `#thread` en ambas).

- [ ] **U-07 · Teclado en el índice** — las conversaciones son `role="option"` en un `listbox` con
  flechas y Enter. Aceptación: ArrowDown mueve el foco y Enter abre. Verificación: CDP.

- [ ] **U-08 · Copiar código** — bloques `pre`/fences del mensaje con botón copiar y `tab-size: 4`.
  Aceptación: 1 botón por bloque detectado (```...```). Verificación: JS.

- [ ] **U-09 · Guía de uso** (`docs/UI_GUIDE.md`) — los cuatro ejes con capturas, atajos, accesibilidad
  (salto, reduced-motion, contraste) y cómo añadir un diseño o un pantón. Aceptación: enlaza capturas
  existentes y no inventa comandos.

- [ ] **U-10 · Revisión de estados vacíos** — cada panel de `/settings` sin datos dice qué hacer; los
  tres peores (skills sin skills, vps sin claves, mcp sin servidores) con texto accionable.
  Aceptación: los tres paneles mencionan la acción siguiente. Verificación: grep de las frases.

## Fuera de la cola (necesitan decisión humana)

- Tipografía empaquetada (woff2 con licencia OFL) — implica añadir binarios al repo.
- Traducción EN/ES de la cabina (`lang` ya existe en config).
- Rediseño de `/gov` (es HTML del protocolo; solo se puede maquillar lo inyectado).
