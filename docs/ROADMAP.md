# Roadmap — de 4,55 a ~8,5 sin mentir en el camino

> **Qué es este fichero.** El plan a 9/10 vivía repartido entre el encargo de una sesión, el §5 de
> `AUDIT_2026-10-29.md` y la propuesta V2. Aquí está la única secuencia que se ejecuta, con su estado y
> su criterio de cierre. `docs/BACKLOG.md` dice **qué está roto**; este documento dice **en qué orden se
> arregla y por qué en ese orden**.
>
> **Reglas.** (1) Una fase no se cierra sin su comando y su exit, en los dos modos (`NEXUS_PROTOCOL`
> presente y ausente). (2) Ningún número se teclea: `python tools/doc_truth.py` los contrasta con el
> motor y pone el build rojo. (3) El orden no se reordena por vistosidad: se reordena solo si un dato
> medido lo obliga, y entonces se dice en el commit.

Medido hoy: 61 suites · 215 ficheros · 57 módulos planos · 12 carpetas · 0 ficheros > 400 líneas.

---

## 1. Dónde estamos

| fase | qué cierra | estado | evidencia |
|---|---|---|---|
| **0** | Tipografía determinista: 2 familias OFL en el paquete, 0 recursos externos | **HECHA** | `ef36f95` · suite `fonts` · DOM `[href],[src]` con `^https?` → 0 |
| **1** | Que el repo deje de mentir (B7, B8, B9, B10, B12, B13, B14) | **HECHA** | `40adce5`, `7cfba97`, `5ef6acb`, `d018c64` · `doc_truth` GREEN · CI 8/8 |
| **2** | Cerrar la arquitectura por capas: de 6/9 a 9/9 | **HECHA** | `cb7a6a4`, `cd3e8de`, `144c526`, `6d8bde2` · 9 paquetes, 50 módulos planos, `test_layers` con el invariante intacto |
| **3** | Paridad competitiva: G, C, D, B, H | **EN CURSO** — G hecha | `88c8018` · suite `hooks` · gate obedece 0/10/20/30 |
| **4** | Release: `dist/` fresco, versión, B6 | pendiente | — |

**Puntuación de referencia (no re-puntuada):** `AUDIT_2026-10-29.md` §4 midió **media 4,55/10** con estos
diez ejes: gobernanza **8,5** · autonomía **8,0** · contexto **7,0** · ecosistema **6,0** · UI **5,5** ·
evals **4,5** · sandbox **2,0** · hooks **1,5** · streaming **1,5** · LSP **1,0**.

Las fases 0 y 1 **no mueven ningún eje de capacidad**: no añaden sandbox ni streaming. Lo que hacen es
que los números publicados sean ciertos y que la deuda no vuelva. Por eso la media sigue en 4,55 y
subirá en la fase 3, que es donde están los cuatro subsistemas ausentes.

---

## 2. Fase 2, cerrada — y lo que enseñó el código

**Por qué fue antes que hooks.** Hooks (G) toca `before_turn`, `after_tool`, `before_commit` y
`pre_verify` — cuatro puntos del bucle. Añadirlos con el espacio de nombres plano obliga a reabrir el
bucle otra vez cuando se muevan `autonomy`, `spec` y `learning`. Se ordena una vez, antes de más
superficie.

| # | paso | resultado medido |
|---|---|---|
| **7** | **B15**: `transports/` a `llm/transports/` | `cb7a6a4` · 15 imports reescritos, 0 `llm → ..transports` |
| **8a** | `autonomy/`: autonomy, autonomy_ask, daemon, plan_graph | `cd3e8de` · 110 módulos importan, 0 rotos |
| **8b** | `spec/`: spec_synth — **`criteria` no existe** (`Candidate`/`GREEN` viven dentro) | `144c526` |
| **8c** | `learning/`: reflection, improve | `6d8bde2` · 9/9 paquetes |

**Lo que la fase corrigió del plan, con la medición delante:**

1. `criteria.py` **nunca existió**: la propuesta v2 lo dibujó y la auditoría lo copió. Se mueve lo que
   hay; inventar un fichero para que el dibujo cuadre es justo lo que este repo persigue.
2. `skill_forge` y `skill_router` **no pueden venir** a `learning/`: los consume `tools/toolbox/
   skill_tools.py` y `context/savings.py`, así que traerlos invertiría la dependencia (el defecto que
   esta fase cierra, del revés). Se quedan donde su consumidor los necesita.
3. `ORDER` cambia porque el código manda: `autonomy` importa `spec_synth` e `improve`, e `improve`
   importa `spec`. El orden real es `… verify, spec, learning, autonomy`.
4. El rewriter aprendió tres trampas nuevas (sangría, `from pkg import a, b` con solo `a` movido, y
   nombres que son clases y no módulos) más la idempotencia y `import_module("…")` como cadena.

**Anti-regresión añadida al gate:** `test_layers` ahora exige que **cada módulo del paquete importe**
(`walk_packages`, 110 módulos, ~1 s). Al mover `autonomy` rompieron cuatro imports y ninguna suite los
tocaba.

Un paquete por commit, imports reescritos con AST (no `sed`), y `test_layers.DECLARED` actualizado en el
mismo commit que mueve los ficheros. Cierre de fase: **9 paquetes**, `flat` de 57 a **50**, y
`python tools/doc_truth.py --write` deja los docs cuadrando.

**Riesgo declarado:** cada movimiento puede engordar un fichero al rewiring mecánico. Un 399 acaba en
401: se parte antes, nunca se aprietan comentarios.

---

## 3. Después (fase 3), por impacto × coste

| # | salto | eje que sube | por qué en este orden | criterio rojo → verde |
|---|---|---|---|---|
| **9** | **G · Hooks/plugins** — **HECHA** (`88c8018`) | extensibilidad 1,5 → 8 | convierte el producto en ecosistema; reutiliza el contrato 0/10/20/**30** que ya existe | **cumplido**: `nexus_harness.toml` con `pre_verify` 10 → gate rojo · 0 → verde · 30 → no cambia el veredicto · sin fichero, motor inerte. Suite `hooks`, 9 casos, incluido un `before_commit` que impide un commit real |
| **10** | **C · Streaming** | agéntico 5 → 7 | cambia el tipo de retorno y ordena los transportes en uno: se hace una vez | un proveedor guionizado devuelve un **iterador** de `delta/reasoning/tool_call/done`; Detener cierra la request en vuelo |
| **11** | **D · Sandbox de proceso** | seguridad 4 → 7 | sin jaula, la autonomía es riesgo declarado | `policy.classify('rm -rf build','unrestricted')` → **negado** con razón; matriz 3 modos × 3 SO con SKIP explícito |
| **12** | **B · LSP** | código 6 → 8 | el stdio JSON-RPC ya existe; degrada al mapa AST | tool `definition` sobre un fixture devuelve `fichero:línea`; sin servidor → fallback **con razón impresa** |
| **13** | **H · Evals** | tareas 6 → 8 | mide capacidad; hoy son 7 tareas en 1 lenguaje | ~20 tareas en 3 lenguajes + mutar 3 líneas pone ≥1 test rojo; la negativa sigue en 10/10 |

Los ejes «gobernanza» y «contexto» ya están en 8,5 / 7,0: no se tocan hasta que el resto suba. Un 10 en
lo que ya ganamos no mueve la media.

---

## 4. Cierre (fase 4)

| # | paso | criterio |
|---|---|---|
| **14** | **I**: subir versión (1.2.0), reconstruir `dist/` (motor + instalador) y automatizar la prueba de **frescura** | `verify.py --frozen` verde **y** `find nexus_harness -name '*.py' -newer dist/nexus-harness-engine.exe \| wc -l` → **0**; el instalador publicado coincide con la versión del paquete |
| **15** | **B6**: `TurnLedger.rows()` deduplica igual que `history()` | fixture con dos escritores → **1 fila** por corrida |

Un binario viejo pasa cualquier proof que solo mire `failures=0`: por eso la frescura es un criterio de
release, no una nota.

---

## 5. Lo que NO está en el camino (decisiones cerradas)

1. **Traducción EN/ES**: no ahora. `lang` ya se consume donde importa (`llm/judge.py`); cuando haya un
   segundo usuario será `ui_strings.py` con test de claves simétricas, nunca inline.
2. **Rediseño de `/gov`**: no aquí. Es HTML del gobernador servido por proxy; se rompería en su
   siguiente cambio.
3. **Perseguir un 10/10 global**: no es el objetivo. El techo honesto del mercado es ~8; la promesa es
   «10/10 en lo que nos diferencia, 8/10 global, y por escrito dónde no lo somos».

---

## 6. Cómo se mantiene vivo

- `python tools/doc_truth.py` (suite `doc_truth` + job `docs` de CI) vigila que la cabecera de este
  fichero no contradiga al motor.
- Cada paso cerrado se tacha aquí y se anota en `docs/BACKLOG.md` con su commit y su comando.
- Si un dato medido contradice el orden de esta tabla, se cambia el orden **y se dice por qué** en el
  mensaje del commit; nunca en silencio.
