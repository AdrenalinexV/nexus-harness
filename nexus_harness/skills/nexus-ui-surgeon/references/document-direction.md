# Dirección: «Cuaderno de taller»

La cabina no es un panel de control: es el cuaderno de obra de un agente. Se lee como un documento
técnico impreso —folio, índice, reglas de 1px, cifras tabulares, sellos de veredicto—, no como un
dashboard de SaaS.

## Por qué (y de dónde sale)

- Los modelos convergen porque el corpus es el mismo (shadcn, Tailwind, plantillas Vercel):
  <https://rottoways.com/blog/vibecoding-design-problem>.
- Los patrones que delatan una UI generada (acento azul/lavanda, dark permanente, tarjetas con icono):
  <https://www.developersdigest.tech/blog/ai-design-slop-and-how-to-spot-it>.
- Reglas editoriales que sí se sostienen (reglas de 1px, sin sombras, sin relleno de tarjeta, un solo
  color de voltaje, tinta no pura): <https://www.shadcn.io/design/wapo/raw>.
- Superficie densa de trabajo, profundidad estructural, estado = glifo + color + palabra:
  <https://github.com/YoanWai/agent-manager/blob/main/DESIGN.md>.
- Lo que NO hay que copiar del cliché «neo-terminal» (fósforo verde, scanlines, dot-grid):
  <https://github.com/cola-runner/awesome-tui-design>.

## Tokens (papel oscuro / papel claro)

| token | oscuro | claro | uso |
|---|---|---|---|
| `--paper` | `#121110` | `#f4f1ea` | fondo |
| `--paper-2` | `#171614` | `#efeade` | elevada (compositor, popover, hover) |
| `--ink` | `#ece7dd` | `#191713` | texto |
| `--ink-2` | `#a8a29a` | `#615c53` | secundario |
| `--ink-3` | `#6f6a63` | `#8b857b` | marginalia, folios |
| `--rule` | `#2b2926` | `#d8d2c6` | reglas |
| `--rule-2` | `#3a3733` | `#c4bcae` | reglas de foco |
| `--seal` | `#d4502e` | `#b8431f` | acción primaria + activo + foco |
| `--ok` | `#7fae6a` | `#3f7a33` | decisión tomada |
| `--warn` | `#c99a3f` | `#8a6512` | espera humana / no verificable |
| `--bad` | `#cc5b45` | `#a83a24` | detectado / roto |
| `--idle` | `#6f6a63` | `#8b857b` | sin registro |

Tipos: `ui-serif` (Georgia) para títulos y `§`; `system-ui` para prosa; `ui-monospace` para toda cifra,
folio, ruta y etiqueta. Escala 10.5 / 11.5 / 13 / 14.5 / 17 / 21 / 30 px. `--radius: 0` (2px solo en
campos). Sin sombras, sin degradados, sin píldoras.

## Composición

```
┌ NEXUS HARNESS │ motor · versión │ ▸ estado ───────────────────────────────┐
│ ÍNDICE        │ Título de la conversación (serif 21)                     │
│ 01 …          │ ───────────────────────────────────────────────────────  │
│ 02 …          │ 01  TÚ / texto                                           │
│ PROYECTO ▾    │ 02  NEXUS / texto      ▸ tool · tool                     │
│ PUERTAS       │ ───────────────────────────────────────────────────────  │
│ § Configur.   │ Escribe…                        (campo reglado)          │
│ ◇ Gobernan.   │ ADJUNTAR   DIRECTOR ▾                        ENVIAR ⏎    │
└───────────────┴──────────────────────────────────────────────────────────┘
```

- Columna izquierda = índice (264px, mismo ancho que antes: `main + índice = body`).
- `settings` = manual: índice numerado 01–10 agrupado por dominio, `§NN` en el título, cada ajuste una
  línea `etiqueta | control | regla`.
- El estado vive en el masthead (`glifo + frase + medidor`) y se despliega en un panel de reglas.

## Etiquetas

Caja alta 10.5px, `letter-spacing:.16em`, tinta 3: `ÍNDICE`, `PROYECTO`, `PUERTAS`, `ENVIAR`. Títulos
en serif, frase normal. Verbos del operador: enviar, detener, abrir, guardar.
