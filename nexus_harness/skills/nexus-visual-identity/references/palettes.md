# Los seis pantones, con sus números

Contraste calculado con `ui_theme.ratio` (WCAG 2.1, luminancia relativa). Umbrales del test:
tinta ≥ 7:1 · tinta-2 ≥ 4.5:1 · sello y estados ≥ 3:1.

| tema | papel | tinta | tinta-2 | sello | señal | ok / warn / bad | tinta/papel | tinta-2/papel | sello/papel |
|---|---|---|---|---|---|---|---|---|---|
| `neon` | `#07060e` | `#eaf6ff` | `#9fb0cf` | `#ff2e88` | `#22d3ee` | `#29f0a5` `#ffc94d` `#ff5c6c` | 18.4 | 7.9 | 5.1 |
| `crt` | `#050a06` | `#b8ffcb` | `#6fbf85` | `#ffb000` | `#7dffb0` | `#35ff86` `#ffd166` `#ff6b6b` | 17.3 | 8.6 | 9.6 |
| `synth` | `#1a0b2e` | `#f7edff` | `#c3a6e0` | `#ff3ea5` | `#21d4fd` | `#72f1b8` `#f3e70f` `#fe4450` | 16.4 | 8.4 | 4.9 |
| `amber` | `#0b0805` | `#ffd7a3` | `#c79a5f` | `#ff9a1f` | `#ffd7a3` | `#ffcf66` `#ffb84d` `#ff7a45` | 14.7 | 7.4 | 7.7 |
| `riso` | `#f3efe4` | `#1b1913` | `#5a5344` | `#d93a10` | `#2b4bff` | `#1f7a4d` `#a86a00` `#c3271f` | 15.3 | 6.6 | 4.0 |
| `paper` | `#f4f1ea` | `#191713` | `#615c53` | `#b8431f` | `#b8431f` | `#3f7a33` `#8a6512` `#a83a24` | 15.9 | 6.5 | 5.9 |

(Los ratios de la tabla se recalculan con el test; si un número no cuadra, manda el test.)

## Qué cita cada uno, y por qué esos valores

- **`neon` — cyberpunk retro.** Cita las salas de máquinas de 1982 y el neón de *Blade Runner*: violeta
  casi negro, blanco algo azulado, magenta de rótulo y cian de pantalla. El negro es **tintado**
  (`#07060e`), no `#000`: el negro puro aplana la pantalla y hace vibrar el magenta. Duotono declarado
  (sello magenta + señal cian) porque el género es así; el cian solo toca sigilos (`§`, `◇`) y filetes.
- **`crt` — fósforo verde.** Cita el monitor de fósforo P1 y los terminales de los 80: verde muy
  claro sobre casi negro, ámbar para la acción. Lleva líneas de barrido a `pointer-events:none` y un
  `text-shadow` de 6px: el brillo es del fósforo, no del texto.
- **`synth` — SynthWave '84.** Cita la paleta del tema de VS Code del mismo nombre (ciruela `#262335`,
  rosa `#fe4450`, verde `#72f1b8`, amarillo `#f3e70f`). Aquí el papel es más violeta y el sello rosa
  para no competir con el amarillo del estado de espera.
- **`amber` — monocromo.** Cita el terminal ámbar de los 70 y las pantallas de aviónica. Un solo hue:
  todo lo que no es tinta es ámbar con distinta saturación. El verde/rojo de estado se mantiene por
  ley (se desaturan, no se sustituyen).
- **`riso` — risográfica.** Cita la serigrafía de dos tintas: papel crema sin blanquear, tinta negra
  cálida y naranja de riso. El naranja original `#ff4a1c` daba 2.93:1 sobre el papel (ilegible para
  texto): se oscureció a `#d93a10` (4.01:1) — el mismo pigmento, legible. La señal azul (`#2b4bff`)
  es la segunda tinta de la imprenta.
- **`paper` — cuaderno.** La del documento: papel cálido, tinta casi negra y bermellón de sello.

## Cómo se añade un séptimo

1. Una fila en `ui_theme.THEMES` (clave, nombre, intención, tres muestras) y otra en `TOKENS`.
2. Un bloque `[data-theme="clave"]` en `web/themes.css` con `--paper --paper-2 --paper-3 --ink
   --ink-2 --ink-3 --rule --rule-2 --seal --seal-ink --seal-soft --signal --ok --warn --bad --idle`.
3. `run(['themes'])` en verde: contraste y cobertura.
4. Captura de chat y de `§ Apariencia`; si el tema añade textura, declárala (scanlines/glow) y
   comprueba que no tapa texto.
