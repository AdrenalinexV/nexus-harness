# Notas de UI — lo que se copia, lo que se descarta y por qué

> Medido el 2026-10-30, después de que el operador señalara cuatro cosas que no funcionaban: la puerta a
> Gobernanza, la elección de modelos, la pantalla de apariencia y el ruido de la cabecera del chat.

## Lo que se consultó

| fuente | qué aporta | qué se hizo |
|---|---|---|
| Hermes Agent (desktop) | un **switcher `Sessions / Projects / Profiles`** sobre el buscador de la columna: una columna, tres lecturas del mismo espacio | `Hilos / Proyectos` en la barra lateral. `Profiles` no se copia todavía: aquí un proyecto **es** el perfil (su `.nexus/harness`), y partirlo en dos conceptos sin datos que los separen sería inventar |
| Patrón *Model Selector* (UX Patterns, AI UX Playground) | mostrar **capacidad y coste**, no jerga de proveedor; el estado actual siempre visible; no esconder la incertidumbre | la guía por rol ordena lo que hay, dice «cabe junto al Director» o «no cabe», y marca lo que falta (clave, VRAM) |
| *Radio button cards* (Soul DS, USWDS) | una opción = una tarjeta con su muestra; clic = elegir; sin botón «Aplicar» separado | apariencia: 19 tarjetas con vista previa y un formulario por tarjeta (funciona sin JS) |

## Decisiones que se tomaron

1. **Una sola puerta.** El chat no repite el índice: `Configuración` en la cabecera. Lo que el operador
   marcó con flechas (el `motor host:puerto`, la píldora de estado con su popover, la ruta del motor al
   pie y la línea del compositor con el modelo del Director) se fue; el control del autopilot vive en
   Configuración → Espacio de trabajo, que ya lo tenía.
2. **Gobernanza no es nuestra UI.** `/gov` sirve la GUI del protocolo (otra aplicación, otro diseño). Un
   enlace cruzado en el índice hacía preguntar «¿esto qué es?». La ruta sigue existiendo; el enlace no.
3. **Los modelos no se eligen por tamaño, se eligen por lo que CABE.** La guía calcula VRAM total, peso
   del Director y presupuesto compartido: un `coder` de 14B que cabe solo pero obliga a recargar entre
   fases baja en la lista, y sube «usa el peso del Director» o el Juez `gate` ($0, 0 ms).
4. **El Juez nunca se recomienda de la familia del Director.** Si comparten familia, se dice que la
   auditoría es floja, en la propia fila.
5. **Sin emojis como iconos** (ley de `DESIGN.md`): el `⚡` del tablero pasó a la palabra `yolo`.

## Lo que queda pendiente, medido

- **Perfiles de verdad por proyecto**: hoy un proyecto es una carpeta con su `.nexus/harness` (sesiones,
  memoria, tablero) y comparte la config global. Separar modelos/skills por proyecto pide un
  `.nexus/harness/profile.json` que `config` lea encima del global — no está hecho.
- **La guía de modelos no mide latencia real**: recomienda por VRAM declarada y catálogo, no por tokens/s
  medidos en este equipo. El comando que lo cerraría: `python tools/eval.py --model <spec>` con el mismo
  rostro de tareas.
