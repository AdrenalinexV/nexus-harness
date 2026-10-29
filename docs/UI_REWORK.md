# Cabina — rework de UI y correcciones U1–U5 (2026-10-29)

> Repo `C:\Proyectos\Nexus-Harness` · partida `d9be74a` · HEAD `174a65f` · versión `1.1.0`.
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
- **CI.** Verde en cada commit de la rama: workflow `verify` (Windows + Linux). Últimos runs:
  `40966603175` (1m35s), `40966851010` (1m20s). Se comprueba con `gh run list --limit 2`.
- **El vacío del chat «antes»**: el hilo no pintaba estado vacío en esa corrida y no se investigó por
  qué (queda como diferencia observada, no como defecto nombrado).

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
