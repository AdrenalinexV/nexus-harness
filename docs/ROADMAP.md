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

Medido hoy: 64 suites · 232 ficheros · 57 módulos planos · 12 carpetas · 0 ficheros > 400 líneas.

---

## 1. Dónde estamos

| fase | qué cierra | estado | evidencia |
|---|---|---|---|
| **0** | Tipografía determinista: 2 familias OFL en el paquete, 0 recursos externos | **HECHA** | `ef36f95` · suite `fonts` · DOM `[href],[src]` con `^https?` → 0 |
| **1** | Que el repo deje de mentir (B7, B8, B9, B10, B12, B13, B14) | **HECHA** | `40adce5`, `7cfba97`, `5ef6acb`, `d018c64` · `doc_truth` GREEN · CI 8/8 |
| **2** | Cerrar la arquitectura por capas: de 6/9 a 9/9 | **HECHA** | `cb7a6a4`, `cd3e8de`, `144c526`, `6d8bde2` · 9 paquetes, 50 módulos planos, `test_layers` con el invariante intacto |
| **3** | Paridad competitiva: G, C, D, B, H | **HECHA** — los cinco pasos con su suite | `88c8018` · suite `hooks` · gate obedece 0/10/20/30 · `41de9b8` · suite `stream` · `chat()` = `fold(stream())` · `a5f79eb` · suite `sandbox` · `unrestricted` sin jaula se niega · `3ba9c5d` · suite `lsp` · `definition` con fallback declarado · `e19fd2c` · suite `eval` · 20 tareas y mutation smoke |
| **4** | Release: `dist/` fresco, versión, B6 | **HECHA** | `verify.py --frozen` → `frozen exit 0 suites=63` · 1.2.0 instalado con el sha256 del repo · `f30ea31` |
| **5** | Tablero Kanvas: plan versionado, DAG y `done` firmado por Gate+Juez | **HECHA** | `5df79b4` · suite `kanvas` (9 casos) · vista `/kanvas` |

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
| **10** | **C · Streaming** — **HECHA** (`41de9b8`, `d88be86`) | agéntico 5 → 7 | cambia el tipo de retorno y ordena los transportes en uno: se hace una vez | **cumplido**: un proveedor guionizado devuelve el **iterador** de `delta/reasoning/tool_call/done` y `fold()` da el MISMO `Reply`; los cuatro parsers sobreviven a un JSON partido a la mitad; Detener cierra el socket (0,52 s, y el servidor ve caer la conexión); la cabina pide los deltas por `/api/events/stream` (SSE, api 4). Suite `stream`, 12 casos |
| **11** | **D · Sandbox de proceso** — **HECHA** (`a5f79eb`) | seguridad 4 → 7 | sin jaula, la autonomía es riesgo declarado | **cumplido**: `classify('rm -rf build','unrestricted')` → negado con nivel `sandbox` y motivo; con jaula de ficheros → permitido; matriz 3 modos × 3 jaulas medida; Job Object con kill-on-close y tope de memoria medidos. Suite `sandbox`, 6 casos |
| **12** | **B · LSP** — **HECHA** (`3ba9c5d`) | código 6 → 8 | el stdio JSON-RPC ya existe; degrada al mapa AST | **cumplido**: `definition` devuelve `fichero:línea` por LSP (servidor falso que habla el protocolo) y, sin servidor, el mapa AST con la razón impresa; los diagnósticos del servidor entran en el resultado de cada `patch`/`write_file` con presupuesto de 1,2 s. Suite `lsp`, 5 casos |
| **13** | **H · Evals** — **HECHA** (`e19fd2c`) | tareas 6 → 8 | mide capacidad; hoy son 7 tareas en 1 lenguaje | **cumplido**: 20 tareas en 3 lenguajes (10 Python, 5 JavaScript, 5 Bash); mutation smoke con 3 mutaciones por tarea y 18/18 tareas con al menos una roja; la negativa sigue en 10/10. Suite `eval`, 9,3 s |

Los ejes «gobernanza» y «contexto» ya están en 8,5 / 7,0: no se tocan hasta que el resto suba. Un 10 en
lo que ya ganamos no mueve la media.

---

## 4. Cierre (fase 4)

| # | paso | criterio |
|---|---|---|
| **14** | **I**: versión **1.2.0**, `dist/` reconstruido (motor 19,3 MB + instalador 19,5 MB) y frescura medida | **cumplido**: `verify.py --frozen` → `frozen exit 0 suites=63 failures=0 skipped=7`; `find … -newer dist/nexus-harness-engine.exe \| wc -l` → **0**; instalado en `%LOCALAPPDATA%\Nexus Harness` con el sha256 del repositorio (`installer_verify --verify` → 0) |
| **15** | **B6**: `TurnLedger.rows()` deduplica igual que `history()` — **HECHA** (`f30ea31`) | **cumplido**: fixture con dos escritores → **1 fila** (120 tokens, no 240); y dos ciclos distintos siguen siendo 2 filas |

Un binario viejo pasa cualquier proof que solo mire `failures=0`: por eso la frescura es un criterio de
release, no una nota.

---

## 4b. Fase 5 — el tablero (Kanvas), cerrada

El plan deja de vivir en la cabeza de una sesión: `.nexus/kanvas.json` viaja en git, sobrevive a un
relevo y lo leen igual la cabina, la herramienta del modelo y el CLI. Lo que lo separa de un Kanban
normal es quién firma el `done`.

| # | paso | criterio rojo → verde |
|---|---|---|
| **16** | **Kanvas** — carriles, tareas y DAG con `proposed/blocked/todo/doing/review/done` | **cumplido**: el estado de una tarea no se escribe a mano (`blocked` se calcula); `review` exige commit/diff y gate 0; `done` exige gate 0 y, con Juez, su aprobación; la cadena ⚡ cierra pasando por `review` igual que un humano y **para** con el gate rojo. Vista `/kanvas` con resumen, filtro y flechas bezier SVG en vivo por SSE. Suite `kanvas`, 9 casos |

Reglas que no se negocian, escritas en el motor y probadas: `done` es final (reabrir es otra tarea con
nota); el agente **no** tiene `approve` (solo el operador por la cabina/CLI, o el ejecutor con Gate+Juez);
y crear una tarea ya `done` está prohibido — se nace `proposed` o `todo`.

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
