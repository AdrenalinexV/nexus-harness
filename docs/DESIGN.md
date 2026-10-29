# DESIGN.md — Nexus-Harness cockpit

> Documento de dirección, no de intenciones: cada regla de aquí se comprueba con un comando del
> §Verificación. Si una pantalla lo incumple, es un defecto con nombre.

## North star — «Cuaderno de taller»

La cabina no es un panel de control: es el **cuaderno de obra** de un agente. Se lee como un documento
técnico impreso —folio, índice, reglas de 1px, cifras tabulares, sellos de veredicto— y no como un
dashboard de SaaS.

Consecuencias que son decisiones, no gustos:

1. **No hay tarjetas.** La estructura la hacen las reglas de 1px y el espacio. Una caja con fondo,
   borde redondeado y sombra es el patrón #1 del corpus del que salen todas las interfaces "IA".
2. **No hay azul.** El azul de acento es el default del corpus (shadcn/Tailwind). El único color de
   voltaje es un **bermellón de sello** (`--seal`), y se usa una sola vez por pantalla: la acción
   primaria y el elemento activo. Nada más.
3. **La tinta es cálida y nunca blanca.** `#121110` de papel, `#ece7dd` de tinta. Un gris azulado
   (#0b0d10 / #e9eef5) es el tell de "dark mode por defecto".
4. **La página se abre en el trabajo.** Sin hero, sin banner de bienvenida: masthead, índice y el
   hilo. La primera cosa que se lee es la conversación, no la marca.
5. **Tres familias del sistema, tres trabajos.** `ui-serif` (Georgia) para títulos y números de
   sección; `system-ui` para prosa; `ui-monospace` para TODA cifra, folio, ruta, token y etiqueta
   técnica. Sin webfonts: una página que necesita red para verse bien está rota.
6. **El estado se escribe.** Un color nunca va solo: va con su palabra y, si hay veredicto, con su
   glifo. Verde = decisión tomada · ámbar = espera humana o *no verificable* · rojo = detectado/roto ·
   gris = sin registro.

## Tokens

| token | valor (papel oscuro) | papel claro | uso |
|---|---|---|---|
| `--paper` | `#121110` | `#f4f1ea` | fondo de página |
| `--paper-2` | `#171614` | `#efeade` | superficie elevada (compositor, hover, popover) |
| `--ink` | `#ece7dd` | `#191713` | texto |
| `--ink-2` | `#a8a29a` | `#615c53` | texto secundario |
| `--ink-3` | `#6f6a63` | `#8b857b` | marginalia, folios |
| `--rule` | `#2b2926` | `#d8d2c6` | reglas de 1px |
| `--rule-2` | `#3a3733` | `#c4bcae` | reglas de foco/estructura |
| `--seal` | `#d4502e` | `#b8431f` | acción primaria, activo, foco (una vez por pantalla) |
| `--ok` | `#7fae6a` | `#3f7a33` | decisión tomada |
| `--warn` | `#c99a3f` | `#8a6512` | espera humana / no verificable |
| `--bad` | `#cc5b45` | `#a83a24` | detectado / roto |
| `--idle` | `#6f6a63` | `#8b857b` | sin registro |

Escala tipográfica: 10.5 / 11.5 / 13 / 14.5 / 17 / 21 / 30 px. Nada intermedio. `--radius: 0`; solo
los campos de formulario llevan 2px. Sin sombras, sin degradados, sin `border-radius: 999px`.

## Composición

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ NEXUS HARNESS   │ 127.0.0.1:8765 · v1.1.0          ▸ GATE OK · JUEZ VERDE · 18 %│ masthead (1 regla)
├──────────────┬────────────────────────────────────────────────────────────────┤
│ ÍNDICE       │ Título de la conversación                          (serif 21)   │
│ 01 convers…  │ ─────────────────────────────────────────────────────────────  │
│ 02 convers…  │ 01  TÚ                                                         │
│              │     pedido…                                                    │
│ PROYECTO ▾   │ 02  NEXUS                                                      │
│              │     respuesta…        ▸ read_file · read_file   (log, mono)    │
│ PUERTAS      │ ─────────────────────────────────────────────────────────────  │
│ § Configur…  │ Escribe…                                          (campo reglado)│
│ ◇ Gobernan…  │ ADJUNTAR   DIRECTOR ▾                              ENVIAR ⏎      │
└──────────────┴────────────────────────────────────────────────────────────────┘
```

- Columna izquierda = **índice** del cuaderno (264 px): folios mono, entradas numeradas, puertas al
  pie. Nunca "tarjetas de navegación".
- El hilo lleva **folio por mensaje** en el margen y una regla encima de cada uno: se puede citar
  «folio 07» en vez de "el mensaje de antes".
- El compositor es una **línea de formulario**: campo sin caja, regla inferior, acciones en una fila
  de texto con sus atajos.
- El estado vive en el masthead, como una línea de ledger (`GLIFO + frase + medidor`), y su detalle se
  despliega en un panel de reglas, no en un modal.

## Voz y etiquetas

- Etiquetas en caja alta, 10.5 px, `letter-spacing: .16em`, tinta 3: `ÍNDICE`, `PROYECTO`, `PUERTAS`,
  `ENVIAR`. Nunca una etiqueta en negrita grande.
- Títulos en serif, frase normal (no caja alta), 21–30 px.
- Toda cifra en mono con `font-variant-numeric: tabular-nums`; los porcentajes llevan espacio fino
  antes del `%`.
- Los verbos de acción son los del operador: *enviar*, *detener*, *abrir*, *guardar*.

## Prohibido (y cómo se mide)

| patrón | comprobación |
|---|---|
| tarjetas (fondo + borde + radio > 2px) | `document.querySelectorAll('[class*=card]')` → 0 y ningún elemento con `border-radius > 2px` salvo campos |
| sombras y degradados | `grep -E 'box-shadow|gradient' web/*.css` → 0 |
| píldoras | elementos con `border-radius >= 100px` → 0 |
| azul de acento | `grep -c '#3b82f6\\|#5b8def\\|#2563eb' web/*.css` → 0 |
| emojis | `/[\u{1F300}-\u{1FAFF}]/u` en `document.body.innerText` → 0 |
| webfonts / CDN | `getAttribute('href'\|'src')` con `^https?` → 0 |
| más de un acento | un solo `--seal`; los demás son tonos de estado |
| movimiento decorativo | `transition`/`animation` solo en `.abar i` (progreso) |

## Verificación

```bash
NEXUS_PROTOCOL='C:\Proyectos\NexusProtocol' python tools/verify.py     # exit 0
NEXUS_PROTOCOL=/nonexistent python tools/verify.py                     # exit 0, skipped=2
# navegador real, motor aislado (:8799), tres pantallas:
#   emojis 0 · radio>=100 0 · radio>2 (fuera de campos) 0 · cajas [class*=card] 0
#   box-shadow/gradient 0 · assets externos 0 · main+index = body
```

Capturas antes/después en `docs/ui/`; el diff lado a lado, por pantalla.
