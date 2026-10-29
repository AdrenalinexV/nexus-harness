# Cabina — rework de UI y correcciones U1–U5 (2026-10-29)

> Repo `C:\Proyectos\Nexus-Harness` · partida `d9be74a` · **código de la cabina hasta `174a65f`** ·
> versión `1.1.0`, más la **segunda pasada de dirección de arte** (§6). Lo que va después son
> correcciones de este documento y sus capturas.
> Commits: `534f9df` (U1/U2/U3/U5 + prueba), `6886bd9` (sistema visual + chat + configuración),
> `14c4019` (gobernanza), `174a65f` (iconos dibujados, estado honesto en reposo) y los de este
> documento con sus capturas. Nada de esto toca el motor, el gate ni la lógica de turno.
>
> Todo lo que dice este documento se midió. Donde no se pudo medir, se dice **no medido** y con qué
> comando se cerraría.

## 0. Cómo se midió (reproducible)

Motor aislado, nunca la configuración del operador:

```bash
export NEXUS_HOME=<scratch>/ui_home NEXUS_HARNESS_TOKEN=ui-audit-token-2026 \
       NEXUS_WORKSPACE=<scratch>/ui_ws
python -m nexus_harness serve --port 8799
```

El «antes» no es un recuerdo: es el mismo binario de medición sobre un worktree del commit de partida,
en otro puerto y con su propia copia de `NEXUS_HOME`:

```bash
git worktree add <scratch>/nx-old d9be74a
cd <scratch>/nx-old && NEXUS_HOME=<scratch>/ui_home_old python -m nexus_harness serve --port 8800
```

Sonda única, ejecutada en un navegador real en las dos versiones (`:8800` = antes, `:8799` = después):

```js
const EMO = /[\u{1F300}-\u{1FAFF}]/gu;
emojis   = (document.body.innerText.match(EMO) || []).length;
pillish  = [...document.querySelectorAll('body *')].filter(e => {
             const r = parseFloat(getComputedStyle(e).borderTopLeftRadius) || 0;
             const b = e.getBoundingClientRect();
             return r >= 100 && b.width > 0 && b.height > 0; }).length;
externos = [...document.querySelectorAll('script,link,img')]
             .map(e => e.getAttribute('src') || e.getAttribute('href') || '')
             .filter(u => /^(https?:)?\/\//i.test(u)).length;
```

Y el `303` con un cliente que **no** sigue la redirección (un `fetch(..., {redirect:'manual'})`
devuelve `opaqueredirect` sin `Location`: no afirma nada):

```bash
curl -s -D - -o /dev/null -X POST -H 'Content-Type: application/x-www-form-urlencoded' \
     -H 'Cookie: nexus_token=ui-audit-token-2026' --data 'section=memoria&relay_threshold=70' \
     http://127.0.0.1:8799/api/settings | grep -i location
```

## 1. Los cinco defectos, reproducidos y cerrados

| # | Reproducido en `d9be74a` | Arreglo | Cómo se comprueba |
|---|---|---|---|
| **U1** | `Location: /settings?section=memoria&note=contexto%20guardado` — **sin `token=`**. Y `/` servía el enlace a Configuración sin token. | `ui._with_token()` en los dos `303`; `<meta name="nexus-token">` en las dos páginas; `token.js` resuelve (URL → meta → `sessionStorage`) y estampa todo enlace interno; el árbol de `/settings` lo lleva en el HTML servido (funciona sin script). | `curl -D -` (arriba) → `Location: …&token=…`; navegador: `settingsLinks` sin token = 0 |
| **U2** | Un `401` se pintaba «El motor no contesta a /api/health … relanza Nexus-Harness.bat». | Rama propia para `401` («falta la credencial») y para `403` (cross-site); el consejo de relanzar queda para el fallo real, ahora con el código de estado en el texto. | `test_ui_contract.test_401_is_not_a_dead_engine`; `/api/state` sin credencial → `401` |
| **U3** | Guardar «Memoria» dejaba `harness.json` en `relay_threshold: 70.0`, `compact_threshold: 55.0` (sobre `0.70`/`0.55`) y **la nota salía verde**: relevo y compactación desactivados en silencio. En `/gov` se leía «relevo automático al **7000 %**». | `settings_kit.percent_to_fraction()` normaliza en UN sitio (% → fracción), rechaza `>100 %` con nota roja y no escribe nada; `show_percent()` pinta desde la fracción y declara `?` si el valor guardado no es una fracción (nunca vuelve a multiplicar). | round-trip real: 70/55 → `{0.7, 0.55}` y 63/41 → `{0.63, 0.41}` en disco; `150` → `303 … &bad=1`, fichero intacto; `/gov` → «al 70 %» |
| **U4** | `/gov` sin enlace desde el chat (`govLinks = 0`) y con **5** enlaces propios (volver + 4 pestañas 01–04), repitiendo el `role="tablist"` que la vista del protocolo ya trae. | Entrada «Gobernanza» en la columna izquierda con icono y token; la barra inyectada queda en **una** entrada («← Volver al chat») y el nombre de la sección. | navegador en `/gov`: `hnavLinks = 1`, `tabs` del protocolo intactas = 1 tablist |
| **U5** | `exit 20/30` se pintaba como `Gate ROJO`; el tercer final no existía en la cabina. | `activity.verdict_class()` / `verdict_word()`: verde (decisión tomada) · **ámbar «NO VERIFICABLE (exit 20)»** · rojo (roto) · gris (sin registro). El desplegable usa `gate.class` y el color va acompañado de la leyenda escrita en la propia cabina. | `test_ui_contract.test_verdict_classes`; leyenda visible en el desplegable de estado |

## 2. Antes → después, criterio por criterio

Medido en navegador real (1264×569), salvo donde se dice.

| criterio | antes (`d9be74a`) | después | comando / sonda |
|---|---|---|---|
| Emojis en el DOM del chat | **1** (`🟢`) | **0** | sonda `emojis` en `/` |
| Emojis en `/settings` | **14** (`📁 🛡 🧠 🔌 📱 🤖 🖥 📊 🏠 🔄`) | **0** | sonda `emojis` en `/settings` |
| Emojis por panel (13 paneles) | 8–14 por panel | **0 en los 13** | `test_ui_contract.test_iconography_is_svg` |
| Emojis en `/gov` | 2 (`💬` nuestro + `🌐` del protocolo) | **1** — queda el `🌐` del **protocolo**, que no es nuestro HTML | sonda `emojis` en `/gov` |
| Iconos | emojis del sistema | **16 símbolos SVG** inline (`ui_icons.py`), trazo 1.5, `currentColor`; 14 usos en el chat, 17 en Configuración | `grep -c '<symbol' nexus_harness/ui_icons.py` → 16 |
| Píldoras (radio ≥ 100 px) en el chat | **2** | **0** | sonda `pillish` |
| Pestañas / rails / badges en el chat | 0 / 0 / 0 | **0 / 0 / 0** | sonda `tabs`, `rails` |
| Assets externos (3 pantallas) | 0 | **0** | sonda `externos` (por atributo, no por propiedad) |
| Ancho del chat | `1000 + 264 = 1264` | `1000 + 264 = 1264` (se conserva) | sonda widths |
| Enlaces internos sin token (chat) | `/settings` **sin** token | **0** sin token | `settingsLinks` + `grep 'href="/settings?token'` |
| `Location` del `303` | sin `token=` | **con** `token=` | `curl -D -` (arriba) |
| `relay_threshold` tras guardar 70 % | `70.0` | **`0.7`** (y `compact_threshold: 0.55`) | leer `harness.json` |
| `/gov` «relevo automático» | **7000 %** | **63 %** | `curl /gov \| grep relevo` |
| `150 %` | se escribía | **rechazado** (`&bad=1`, fichero intacto) | `curl -D -` con `relay_threshold=150` |
| `/gov` «relevo» tras guardar 70 % | `7000 %` | **70 %** | `curl /gov \| grep relevo` |
| Medidor de progreso en reposo | carril de 64 px al 0 % (se lee como «en marcha») | **oculto**: solo con progreso real | navegador: `display` del `#activity-bar` = `none` |
| Botón «Detener bucle» en reposo | visible (el `hidden` del HTML perdía contra `button{display}`) | **oculto** | regla `[hidden]{display:none!important}` en `tokens.css` |
| `401` | «motor caído, relanza» | rama propia («pide token») | `test_ui_contract` |
| Veredicto `exit 20` | «Gate ROJO» | **ámbar «NO VERIFICABLE»** + leyenda | `test_ui_contract` |
| Entradas de Configuración | 13 planas, 13×200 con `h1` propio | **13 en 4 grupos**, 13×200 con `h1` propio | sonda por `href` |
| Ctrl+K | enfocaba y filtraba el árbol | **paleta de destinos**: «relevo» → Memoria y contexto, «skill» → Skills, flechas + Enter navegan | navegador (teclas reales) |
| Esc / ✕ | volvía a `/` sin token | vuelve a `/?token=…` | navegador: `location` tras Esc |
| `/gov` alcanzable desde el chat | **0** enlaces | **1** entrada en la columna izquierda | sonda `govLinks` |
| Barra propia en `/gov` | 5 enlaces (volver + 4 pestañas) | **1** (volver) | sonda `hnavLinks` |
| `verify.py` (gobernador) | exit 0, `suites=51` | exit 0, **`suites=52`** (nueva suite `ui_contract`) | `NEXUS_PROTOCOL=… python tools/verify.py` |
| `verify.py` (lint builtin) | exit 0, `skipped=2` | exit 0, `skipped=2` | `NEXUS_PROTOCOL=/nonexistent python tools/verify.py` |

## 3. Capturas y diff visual

En `docs/ui/` (1264×569, mismo navegador, misma ventana):

| fichero | qué enseña |
|---|---|
| `before-chat.png` / `after-chat-empty.png` | el chat vacío: antes sin estado (hilo en blanco) y «⚙ Configuración», «+ Adjuntar» apilado; después con jerarquía, estado vacío y compositor en una fila |
| `before-settings-modelos.png` / `after-settings-modelos.png` | Modelos: antes 13 entradas planas con emojis; después 4 grupos, iconos y la misma información |
| `after-settings-memoria.png` | el panel de Memoria con los porcentajes en % (63/41) y su nota |
| `before-gov.png` / `after-gov.png` | gobernanza: antes la barra de 4 pestañas; después una sola puerta de vuelta |
| `after-settings-palette.png` | Ctrl+K abierto buscando «relevo»: un solo destino, «Memoria y contexto» |
| `after-activity-legend.png` | el desplegable de estado con la leyenda de los cuatro tonos y el botón del Autopilot |
| `after-chat-thread.png` | un hilo real (3 mensajes, herramientas y turno) — no tiene «antes»: el hilo vacío del chat antes no se pintaba y no hay captura equivalente |
| `diff-chat.png`, `diff-settings.png`, `diff-gov.png` | antes \| después lado a lado |

Diferencia de píxeles (umbral 24 sobre 255, misma ventana; mide **cuánto cambió**, no si mejoró):
chat **6,4 %**, configuración **15,9 %**, gobernanza **1,5 %**.

## 4. No medido (y cómo se cerraría)

- **Emoji de `/gov`.** Queda 1 (`🌐`) en la página que sirve **NexusProtocol**: arreglarlo exige tocar
  el protocolo, que está fuera del alcance de esta sesión. Cerrarlo: `NEXUS_PROTOCOL=… pytest` en el
  protocolo, o inyectar una hoja que lo sustituya en `gov.page`.
- **El `401` en un navegador de verdad.** La página siembra la cookie `nexus_token` al servirse, así que
  en condiciones normales no se llega al `401`; se afirma la rama (texto servido) y el `401` real de la
  API sin credencial. Cerrarlo del todo: abrir la cabina con el motor reiniciado y token nuevo.
- **Contraste y accesibilidad.** No hay herramienta de contraste en el repo; «no medido». Cerrarlo:
  `axe-core` sobre las tres pantallas, o un cálculo de luminancia por par token/fondo.
- **CI.** Workflow `verify` (Windows + Linux). El commit `39d2973` (pantones) salió **rojo** y con razón:
  la suite corre también sobre el **wheel instalado** y `nexus_harness/skills/` no viajaba en
  `package-data`, así que `packaged_skills` falló allí. Arreglado en `a00ebfb` (run `40972338204`, verde,
  1m24s) y comprobado sobre el wheel extraído, no solo en el checkout.
- **El vacío del chat «antes»**: el hilo no pintaba estado vacío en esa corrida y no se investigó por
  qué (queda como diferencia observada, no como defecto nombrado).

## 6. Segunda pasada — dirección de arte (por qué la primera seguía siendo genérica)

La primera entrega era correcta y **fea del modo en que lo es todo lo vibecodeado**: sidebar, tarjetas
con radio y borde, acento azul, modo oscuro permanente. Es el patrón que la comunidad tiene medido:

- [Rottoways, *The vibecoding design problem*](https://rottoways.com/blog/vibecoding-design-problem):
  los modelos convergen porque el corpus es el mismo (shadcn, Tailwind, plantillas Vercel). «Cambiar de
  herramienta no ayuda; la varianza está entre el default del LLM y un design system restringido».
- [*AI Design Slop: 16 patterns*](https://www.developersdigest.tech/blog/ai-design-slop-and-how-to-spot-it):
  Inter en todo, acento lavanda/azul, dark mode permanente, tarjetas idénticas con icono.
- [Washington Post DESIGN.md](https://www.shadcn.io/design/wapo/raw): «hairline-only dividers — no
  shadows, no card fills, no border tints», un solo color de voltaje, tinta casi negra nunca pura.
- [agent-manager DESIGN.md](https://github.com/YoanWai/agent-manager/blob/main/DESIGN.md): superficie
  densa de trabajo, profundidad estructural, estado = glifo + color + **palabra**.
- [awesome-tui-design](https://github.com/cola-runner/awesome-tui-design): el catálogo de lo que hay
  que **no** copiar del cliché «neo-terminal» (fósforo verde, scanlines, rejillas de puntos).

Dirección aplicada, escrita en `docs/DESIGN.md` y en la skill `nexus-ui-surgeon`: **«Cuaderno de
taller»** — la cabina como documento técnico impreso.

- Sin tarjetas: la estructura son reglas de 1px y espacio.
- Sin azul: el único voltaje es un **bermellón de sello** (`--seal #d4502e`), una vez por pantalla
  (acción primaria + elemento activo).
- Papel cálido (`#121110`) y tinta cálida (`#ece7dd`), nunca el par azulado del «dark mode por defecto».
- Tres familias del sistema con tres trabajos: `ui-serif` (Georgia) para títulos y `§` de sección,
  `system-ui` para prosa, `ui-monospace` para **toda** cifra, folio, ruta y etiqueta.
- El chat es un documento: **folio por mensaje** en el margen (01, 02…), título serif, medida de 68ch,
  y un compositor que es una línea de formulario con las acciones en mono.
- La configuración es un **manual de operación**: índice numerado 01–10 agrupado por dominio, `§NN` en
  el título del panel, y cada ajuste es una línea `etiqueta | control | regla`.
- Las tarjetas del arnés dentro de `/gov` se reescribieron con **colores literales**: ese HTML se
  inyecta en el documento del protocolo, que define su propio `--accent` azul; heredarlo era volver al
  producto vecino.

Medido en navegador real, tras la segunda pasada (misma sonda):

Tres versiones servidas a la vez (worktrees de `d9be74a` en `:8800` y de la primera pasada `174a65f`
en `:8801`, la actual en `:8799`) y la **misma** sonda en las dos pantallas. Pares *chat / settings*:

| criterio | `d9be74a` | 1.ª pasada | **2.ª pasada** |
|---|---|---|---|
| cajas con relleno propio (fondo ≠ papel, fuera de campos) | 4 / 25 | 3 / 26 | **0 / 2** (un aviso y un `<summary>`) |
| `border-radius > 2px` fuera de campos | 3 / 41 | 3 / 38 | **0 / 0** |
| `box-shadow` | 1 / 2 | 0 / 0 | **0 / 0** |
| elementos con el azul del corpus | 5 / 28 | 6 / 18 | **0 / 0** |
| píldoras (`radius >= 100px`) | 2 / 10 | 0 / 0 | **0 / 0** |
| emojis en body | 1 / 14 | 0 / 0 | **0 / 0** (en `/gov` queda 1: el `🌐` del protocolo) |
| `main + índice = body` | 1000+264=1264 | ídem | **1000+264=1264** |
| familia del título | `system-ui` 16px | `system-ui` 16px | **`ui-serif` 21px** |
| fichero mayor | `app.js` 395 | `settings.py` 372 | **`settings.py` 386** |

Diferencia de píxeles contra `d9be74a` (misma ventana): chat **6,8 %**, configuración **16,9 %**,
gobernanza **8,7 %**.

Capturas: `v2-chat-empty.png`, `v2-chat-thread.png`, `v2-settings-modelos.png`,
`v2-settings-memoria.png`, `v2-settings-stats.png`, `v2-settings-palette.png`, `v2-gov.png`;
lado a lado en `diff2-chat.png`, `diff2-settings.png`, `diff2-gov.png`.

## 7. Tercera pasada — pantones y skill de diseño nativa

La cabina ya se puede vestir. Un tema es un **juego de tokens** (`web/themes.css`), no otra pantalla:
masthead, índice, folios y reglas no se mueven. Seis pantones de serie, elegidos en `§10 Apariencia`,
guardados como `ui_theme` y servidos en `data-theme` desde el servidor (sin parpadeo: el color se
resuelve antes del primer pintado).

| clave | pantón | cita | papel / tinta / sello | tinta-papel |
|---|---|---|---|---|
| `neon` | Neón nocturno | cyberpunk retro (magenta + cian) | `#07060e` / `#eaf6ff` / `#ff2e88` | 18,4:1 |
| `crt` | Fósforo | CRT verde con líneas de barrido | `#050a06` / `#b8ffcb` / `#ffb000` | 17,3:1 |
| `synth` | Synthwave | SynthWave '84 | `#1a0b2e` / `#f7edff` / `#ff3ea5` | 16,4:1 |
| `amber` | Ámbar | terminal monocromo | `#0b0805` / `#ffd7a3` / `#ff9a1f` | 14,7:1 |
| `riso` | Risográfica | serigrafía de dos tintas | `#f3efe4` / `#1b1913` / `#d93a10` | 15,3:1 |
| `paper` | Cuaderno | papel cálido y bermellón | `#f4f1ea` / `#191713` / `#b8431f` | 15,9:1 |

- **Contraste medido**: `selftests/test_themes.py` recalcula WCAG para tinta, tinta-2, sello y los tres
  estados en cada pantón, y falla si el CSS no tiene el bloque o el tema no define sus tokens. El
  naranja riso original (`#ff4a1c`, 2,93:1) se oscureció a `#d93a10` (4,01:1): el mismo pigmento,
  legible. Ese hallazgo salió del test, no del ojo.
- **Duotono declarado**: los temas neón usan `--seal` (acción/activo) y `--signal` (sigilos y filetes).
  Es la excepción escrita a «un solo acento»; en el resto, un voltaje.
- **Persistencia real**: el selector postea `ui_theme` a `/api/settings`, la lista blanca de
  `onboarding.save_settings` valida la clave (una errata no se escribe), `reload_config()` la relee y el
  servidor pinta `data-theme`. Recargar no reenvía nada (303).

El índice pasa de 13 a **15 destinos** (11 categorías + las 4 sub-vistas de la tríada): el §10 es el
nuevo panel de pantones.

**Skill nativa en los dos lados.** `nexus_harness/skills/nexus-visual-identity/` viaja en el paquete y
es una raíz de enrutado (`context/skill_router.py`), así que el arnés la puede inyectar en un turno sin
Hermes; `tools/install_skill.py nexus-visual-identity` la instala en el perfil de Hermes. Contenido:
método para inventar un pantón, los seis con sus números y un mapa de implementación.

Verificación nueva:

```bash
python -c "import sys;sys.path.insert(0,'.');from nexus_harness.selftests import run;print(run(['themes','packaged_skills']))"
# themes OK · packaged_skills OK
```

Capturas: `themes-sheet.png` (los seis chats), `theme-<clave>.png`, `theme-panel.png` (§ Apariencia).

## 5. Tamaño de los ficheros (ley de 400 también aquí)

| antes | líneas | después | líneas |
|---|---|---|---|
| `web/app.js` | 395 | `web/app.js` | 149 |
| | | `web/chat_stream.js` | 175 |
| | | `web/sessions.js` | 104 |
| | | `web/composer.js` | 82 |
| `web/panels.js` | 63 | *(absorbido por `composer.js`)* | — |
| `web/activity.js` | 205 | `web/activity.js` | 232 |
| `web/app.css` | 373 | `web/tokens.css` | 121 |
| | | `web/app.css` | 168 |
| `web/settings.css` | 114 | `web/settings.css` | 331 |
| `web/settings.js` | 166 | `web/settings.js` | 238 |
| `web/index.html` | 95 | `web/index.html` | 116 |
| — | — | `web/token.js` | 35 |
| `settings.py` | 387 | `settings.py` | 372 |
| | | `settings_actions.py` | 134 |
| — | — | `ui_icons.py` | 78 |

`python tools/verify.py` → `lint exit 0 files=189 findings=0 max_lines=400`.
