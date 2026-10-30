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

- [x] **U-02 · Banda de reintento** — si `/api/state` falla 3 veces seguidas, se levanta la banda
  `#warn` con «motor sin respuesta · Reintentar» y un botón que reintenta ya; al volver el motor, la
  banda se retira sola. Medido en navegador real (CDP, motor aislado): último sondeo bueno → tercera
  falla **7,50 s** (≤8 s); clic real en `Reintentar` → `GET /api/state` **1 ms** después; motor
  relanzado → banda oculta y `failures=0`. Hecho en `f502424` (`showOffline`/`markReachable` en
  `app.js`). *Verificado con apagar/encender el servidor.*

- [x] **U-03 · Exportar el hilo a Markdown** — botón `Exportar` en `.doc-head`; genera un `.md` con
  `## folio NN · ROL`, el texto y las herramientas, y lo descarga con `Blob`. El modelo del documento
  vive en `state.doc` (lo llena `chat_stream.js` al pintar, para que los folios del `.md` sean los
  mismos que los de pantalla) y lo vuelca `export.js`. Medido en navegador real (CDP, motor aislado con
  una conversación sembrada): clic real → descarga `exportar-el-hilo.md`, el blob empieza por
  `# Exportar el hilo` (el `h1` servido) y contiene `folio 01`; sonda 0 radius>2 / 0 sombras / 0 pills /
  0 emojis / 0 azul de corpus y el botón aporta 0 cajas con relleno. Hecho en `2f563a2`.
  *Verificado creando el Blob de verdad y leyendo sus primeros 80 caracteres.*

- [x] **U-04 · Sección «Acerca de»** (`§12`, `settings_about.py`) — versión, `api`, host:puerto, raíz,
  uptime y un botón `Comprobar` que llama a `/api/health` y deja su resultado en la nota. Las seis
  cifras salen en vivo de `cockpit.state()` y `/api/health` (que ahora publica `uptime`), sin ninguna
  escrita a mano; el botón es un `<form>` de verdad, así que funciona con el script bloqueado. Medido
  en navegador real (motor aislado `:53899` con `NEXUS_HOME` en scratch): `GET /settings?section=about`
  → **200** con `<h1><span class="folio">§12</span>Acerca de</h1>`, host y raíz reales, y **0 radius>2 /
  0 sombras / 0 pills / 0 emojis / 0 azul de corpus / 0 enlaces sin token**; clic real en `Comprobar` →
  303 a `…&note=salud%3A%20responde…&token=…` y la fila `uptime` pasa de 3 s a 9 s. El índice queda en
  12 destinos (§01–§12) / 15 entradas navegables. Hecho en `aa1d4b9`.
  *Verificado con clic real en el navegador y el 303 leído sin seguirlo.*

- [x] **U-05 · Hoja de atajos** — `?` abre un `<dialog>` con Ctrl+Enter, Esc, Ctrl+K, `?` y los ejes de
  apariencia; sin dependencias. Aceptación: pulsar `?` (tecla real) abre `dialog[open]`. Verificación:
  CDP `Input.dispatchKeyEvent`.

- [x] **U-06 · Densidad** — eje `ui_density` (`normal` | `compacta`): la compacta reduce aire (padding y
  gap) sin cambiar tipos. Aceptación: `data-density` servido y altura del hilo distinta ≥10 %.
  Verificación: navegador (medir `#thread` en ambas). Medido en motor aislado `:52812` con una
  conversación sembrada de 12 mensajes: `#thread.scrollHeight` **1621 px** (`normal`) → **1247 px**
  (`compacta`) = **−23,1 %**, con `.bubble` `font-size` idéntico (14,5 px) en las dos; `data-density`
  servido por el chat y por `/settings`, y clic real en el radio `compacta` + `Aplicar densidad` → 303
  con la nota `densidad → compacta` y `harness.json` con `"ui_density": "compacta"`. Sonda 0 radius>2 /
  0 sombras / 0 pills / 0 emojis / 0 azul de corpus / 0 enlaces sin token. `density.css` no declara
  `font-family` ni `font-size` (lo exige `test_density_moves_air_not_type`). Hecho en `c5a079d`.
  *Verificado con dos medidas reales del hilo en el navegador y capturas en `docs/ui/density-*.png`.*

- [x] **U-07 · Teclado en el índice** — las conversaciones son `role="option"` en un `listbox` con
  flechas y Enter. Aceptación: ArrowDown mueve el foco y Enter abre. Verificación: CDP. Medido con
  teclas reales en motor aislado `:52931` (tres conversaciones sembradas): `#sessions` `role=listbox`,
  filas `role=option` con `tabindex` móvil `0,-1,-1`; `Tab` entra en el índice; `ArrowDown` mueve el
  foco a `…000002` y luego `…000003` (tabindex `-1,0,-1` → `-1,-1,0`), `ArrowUp`/`Home`/`End` también;
  `Enter` → `POST /api/chat/load` en la traza de `fetch`, la fila queda `.active` con
  `aria-selected=true` y el título servido cambia al de la conversación; foco visible `1px solid
  rgb(184,67,31)`; sonda 0 radius>2 / 0 sombras / 0 pills / 0 emojis / 0 azul de corpus / 0 enlaces sin
  token. La hoja de atajos (`?`) anuncia «↑ ↓ · recorrer el índice · Enter abre». Hecho en `0cd3d6d`.
  *Verificado con `Input.dispatchKeyEvent` (CDP) sobre el motor aislado.*

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
