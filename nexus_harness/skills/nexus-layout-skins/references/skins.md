# Los cuatro diseños, en detalle

Cada skin es una composición del MISMO HTML. Lo que cambia, por ejes:

| | document | terminal | minimal | neon |
|---|---|---|---|---|
| títulos | serif 21px | mono 13,5px con `#` | sans 21px, sin folio | mono 14,5px mayúsculas, `::` |
| mensaje | fila con folio + regla encima | fila `L01` + `›` / `·` | párrafo sin cromo | panel con esquinas de sello |
| separadores | 1px sólida | 1px discontinua | ninguno | 1px + brillo en masthead y compositor |
| densidad | media | alta (sin aire) | baja (mucho aire) | media, compacta en cajas |
| columna | 264px | 224px | 232px | 236px |
| compositor | campo reglado | línea mono sin caja | caja redondeada 8px | caja cortada + `[ ENVIAR ]` |
| ajustes | líneas con regla | `clave = valor` | aire, sin reglas | secciones con guiones y brillo |
| par recomendado | `paper` | `crt` | `riso` | `neon` |

## Cuándo usar cada uno

- **document** — por defecto: lectura larga, operador que cita folios («mira el folio 07»). Es el que
  mejor envejece en pantallas grandes y con hilos de muchos turnos.
- **terminal** — sesiones cortas y densas, teclado, pantallas pequeñas; quien vive en tmux se siente en casa.
- **minimal** — demos, capturas, gente que odia el cromo; es el más legible en claro y el que menos
  distrae del texto del modelo.
- **neon** — gusta o no gusta, pero tiene una ventaja funcional: el panel por mensaje separa turnos
  largos con herramientas sin depender de la regla.

## Añadir un quinto (por ejemplo `editorial`)

1. Un bloque `[data-skin="editorial"]` en `web/skins.css` que toque, como mínimo:
   `.title`, `.app`, `.msg`, `.composer`, `.sfield`, `.masthead`.
2. Una fila en `ui_theme.SKINS`: `("editorial", "Editorial", "revista: dos columnas, capitulares", "paper")`.
3. `run(['themes'])`: exige ≥10 reglas y los cuatro selectores obligatorios.
4. Tres capturas con pantones distintos; si el diseño falla en claro u oscuro, no está acabado.

## Mapa

| pieza | fichero |
|---|---|
| composiciones | `nexus_harness/web/skins.css` |
| catálogo y validación | `nexus_harness/ui_theme.py` (`SKINS`, `SKIN_KEYS`, `resolve_skin`) |
| inyección | `nexus_harness/ui.py` → `data-skin` en `<html>` |
| selector | `nexus_harness/settings_theme.py` (`§ Apariencia`, eje 01) |
| prueba | `nexus_harness/selftests/test_themes.py` (`test_skins_are_structural`) |
