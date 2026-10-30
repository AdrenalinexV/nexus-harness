# Anti-slop: lo que se mide, y cómo se arregla

Cada fila es una comprobación con un número, no una opinión. Se ejecuta en las tres pantallas con un
motor aislado:

```js
const all = [...document.querySelectorAll('body *')];
const radius = (e) => parseFloat(getComputedStyle(e).borderTopLeftRadius) || 0;
const filled = all.filter((e) => {                      // cajas con relleno propio
  const cs = getComputedStyle(e), b = e.getBoundingClientRect();
  if (['INPUT','SELECT','TEXTAREA','BUTTON'].includes(e.tagName) || b.width < 40) return false;
  const own = cs.backgroundColor, bg = getComputedStyle(document.body).backgroundColor;
  return own && own !== 'rgba(0, 0, 0, 0)' && own !== bg;
}).length;
const rounded = all.filter((e) => radius(e) > 2 && !['INPUT','SELECT','TEXTAREA','BUTTON']
  .includes(e.tagName)).length;                                        // radio fuera de campos
const shadows = all.filter((e) => getComputedStyle(e).boxShadow !== 'none').length;
const pills = all.filter((e) => radius(e) >= 100).length;
const blue = all.filter((e) => ['rgb(59, 130, 246)','rgb(91, 141, 239)']
  .includes(getComputedStyle(e).color)).length;                        // acento del corpus
const emojis = (document.body.innerText.match(/[\u{1F300}-\u{1FAFF}]/gu) || []).length;
```

| patrón | objetivo | arreglo en este repo |
|---|---|---|
| tarjetas (fondo + borde + radio) | `filled = 0` | `border-left: 1px` + `padding-left`, nunca `background` |
| esquinas redondeadas | `rounded = 0` | `--radius: 0`; 2px solo en campos |
| sombras | `shadows = 0` | profundidad por reglas y tono, no por `box-shadow` |
| azul de acento | `blue = 0` | `--seal` bermellón, una vez por pantalla |
| píldoras | `pills = 0` | etiquetas de texto; el estado es texto + glifo |
| emojis | `emojis = 0` | sprite SVG de 16 símbolos (`ui_icons.py`) |
| webfonts / CDN | 0 assets externos | familias del sistema; sprite y CSS locales |
| movimiento decorativo | solo `.abar i` | la transición comunica progreso, nada más |

Además, tres comprobaciones que no son de estilo sino de honestidad:

1. `document.title` puede reescribirlo el navegador anfitrión: mide emojis en `document.body`.
2. `/gov` es HTML del protocolo: sus píldoras y su azul **no son tuyos**; cuenta solo `#hnav` y las
   `.hsec` que inyecta el arnés (y usa colores literales allí: `var(--accent)` allí es azul).
3. Un `[class*=card]` puede sobrevivir como nombre aunque el look ya no sea tarjeta: mide relleno y
   radio, no el nombre de la clase.
