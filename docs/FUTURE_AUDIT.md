# Auditoría profunda y arquitectura objetivo (v2)

> **Estado (2026-10-27)**: `P0` completo, y de `P1` ya están **P1.1** (spec sintetizada), **P1.2**
> (plan en grafo + parada por criterios), **P1.3** (cartera de modelos, failover y caché medida) y
> **P1.5** (eval de 7 tareas golden). Queda **P1.4** (LSP) y todo P2. Suites 34 → 41, `verify.py`
> GREEN, 0 hallazgos de lint, 146 ficheros, ninguno por encima de 400 líneas.
> Pruebas nuevas: `python tools/proofs.py context|learning|oracle|tokenizer` (`failures=0`).
> Medido en un turno real de 9 pasos: **2.372 de 4.247 tokens de prompt (55,8 %) son prefijo idéntico
> al paso anterior**, es decir, cobrables a precio de caché; antes el `system` se reescribía en cada
> paso y ese prefijo se rompía en el byte 0. Lo que sigue es el análisis que originó el plan.

Fecha: 2026-10-27 · Base medida: `6a4c5d7` · Nada de este documento viene de memoria: cada cifra tiene
su comando detrás y está reproducida abajo.

Objetivo de este documento: decidir **qué falta para que este harness sea el definitivo**, no para que
sea más grande. El criterio es uno: que un proyecto pueda avanzar solo, con la verdad medida, gastando
menos contexto que cualquier harness del estado del arte.

---

## 0. Cómo se midió

```
$ python tools/verify.py
lint      exit 0   files=128 findings=0 max_lines=400 ignored_runtime=0
selftest  exit 0   suites=34 failures=0
verify: GREEN

$ python -c "from nexus_harness.savings import skill_index; print(skill_index(force=True))"
{'skills': 173, 'index_tokens': 3369, 'body_tokens': 446714, 'cached': False}

$ wc -l (solo fuente, sin .build/venv)
18973 líneas en nexus_harness/ + tools/ + apps/
mayor módulo: nexus_harness/triad_loop.py = 399 líneas (techo 400)
ficheros > 400 líneas: 0

$ ledger real (.nexus/harness/ledger.jsonl)
7 filas · exit 0: 1 · exit 10: 6 · 1 fila duplicada histórica (session_10, mismos 48.930 tokens)
último turno verde: 12.370 enviados / 17.229 baseline / 4.859 ahorrados (28,2 %) / ×1,39 contexto
```

---

## 1. Inventario real (lo que existe hoy)

| capa | módulos | estado medido |
|---|---|---|
| Transportes | `openai_compat`, `ollama`, `anthropic` | 6 vendors, 3 wires, sin streaming (`stream: False`) |
| Roles | `providers.Router` | director / worker / judge → un spec `vendor:modelo` fijo |
| Herramientas | `tools.Registry` | 12 nativas + `delegate_task` dinámico + MCP dinámico |
| Edición | `fuzzy_match` (8 peldaños), `patch_v4a` (multi-fichero atómico) | sólido, con rollback y overlay |
| Contexto | `context_pruner` (poda con recibo), `compaction`, `relay_state` (55/70 %), `repo_map` (AST) | el ahorro es real y se mide por request |
| Cierre | `gate` (lint + 400 líneas + tests), `judge` (modelo distinto) | exit 0/10/20, fail-closed |
| Autonomía | `autonomy.Autopilot` (cola + backup + commit), `bridge` (cola móvil), `nightshift` (rúbrica) | un job a la vez, planificador de **un** paso |
| Aprendizaje | `memory` (manual, 6.000 chars), `skill_forge` (+`ForgeTrigger`), `skill_router` | ver F1/F4: la forja existe, el reflejo no |
| Evidencia | `ledger`, `savings`, `stats_savings`, `proofs`, `verify` | 25 criterios de rúbrica, todos con comando |
| Superficies | `ui`/`api`/`panels`, Tauri desktop, CLI, `vps_deployer` | producto real, instalable |

**Veredicto corto:** el arnés tiene algo que los tres referentes no tienen juntos — **cierre
determinista (gate + juez) y contabilidad de ahorro por request con recibos auditables**. Lo que le
falta no es motor, es **criterio**: hoy sabe ejecutar un plan y probar que el árbol está verde; no sabe
decidir qué construir, ni aprender de lo que le sale mal.

---

## 2. Hallazgos (con evidencia, ordenados por impacto)

### F1 · Hay dos sistemas de skills y el que se documenta no es el que corre
`skill_router.SkillRouter` (techo 10 + catálogo dormido) **no se instancia en producción**: solo en
`selftests/test_skills.py`. El camino real es `context_router.ContextRouter`, que delega en el
protocolo con `MAX_SHORTLIST = 2`.

```
$ grep -rn "SkillRouter" --include=*.py . --exclude-dir=.build | grep -v skill_router.py
./nexus_harness/selftests/test_skills.py:34:  router = skill_router.SkillRouter(...)
```

`docs/AUTONOMY.md` afirma «techo de 10 en RAM y el resto dormidas». Lo que viaja son 2 especialistas +
las de nivel 1. El catálogo dormido se escribe en disco pero nadie lo consulta al seleccionar.
**Impacto:** documentación que miente por omisión, dos políticas que pueden divergir, y código muerto en
el camino caliente (viola la ley de «cero código muerto»).

### F2 · El prefijo del prompt se reconstruye en cada paso: caché de prefijo roto
`chat.py:212` y `triad_loop.py:195` rebuildan el mensaje `system` con `self.touched` **creciente**:

```
messages = [Message(role="system", content=self._system(self.touched))] + self.history
...
messages[0] = Message(role="system", content=self._system(WORKER_PROMPT, self.touched))
```

Cada fichero tocado cambia las skills inyectadas, el mapa AST y por tanto el byte 0 del prompt. En
DeepSeek/Anthropic/OpenAI el descuento de caché de prefijo exige **prefijo idéntico**; aquí se invalida
en cada paso del turno. Se paga entrada completa N veces y además se pierde la latencia de prefill.
**Es el mayor ahorro que queda sobre la mesa y no cuesta ni un token de diseño.**

### F3 · El presupuesto se mide en `chars / 4`
`context_pruner.CHARS_PER_TOKEN = 4`, usado por `compaction`, `savings` y los umbrales 55/70 %. En
código con identificadores largos, JSON de herramientas y acentos, el error frente a un tokenizer real
es del orden de ±20-30 %. Consecuencia: el relevo se dispara tarde o temprano según el idioma del
proyecto, y el baseline del benchmark A/B arrastra el mismo sesgo. No hay tokenizer por modelo
(tampoco `tiktoken` instalado).

### F4 · El aprendizaje es una herramienta, no un reflejo
`ForgeTrigger` (3 fallos del mismo patrón → forja) está implementado y probado, pero **nadie lo llama**:
`grep ForgeTrigger` solo aparece en su módulo y su suite. `memory.add` solo se invoca desde el panel
(`cockpit.py:257`). El enrutado de skills puntúa por léxico y extensión, **sin señal de resultado**: una
skill que participó en 12 turnos rojos puntúa igual que una que resolvió 12.
**Impacto:** el harness no mejora con el uso. Es la diferencia exacta entre «tiene skills» y «aprende».

### F5 · La autonomía empieza donde debería empezar el trabajo: la spec
`.ai/CURRENT_SPEC.json` está **escrita a mano y congelada** (3 CAs). `Autopilot` lee esa spec, pide
**un** paso al Director y lo ejecuta. No hay:
- síntesis de spec desde un objetivo en lenguaje natural;
- descomposición en criterios **ejecutables** (comando + exit esperado);
- ampliación de la spec cuando el trabajo descubre requisitos;
- criterio de parada distinto de «el Director dice que no quedan pasos».

El «proyecto que se crea a sí mismo» no existe todavía: existe su ejecutor. Y un planificador de un paso
no puede razonar sobre dependencias, ni paralelizar, ni detectar que dos pasos se contradicen.

### F6 · Un gate puede estar verde sin haber probado nada
`gate.tests()` devuelve `Check(ok=True, blocking=False, exit=None)` cuando no hay `test_command`
(`gate.py:108-112`). Si el proyecto no declara comando, el gate verde significa solo «lint y 400 líneas».
No hay autodetección (`pytest.ini`, `package.json`, `Cargo.toml`, `go.mod`, `phpunit.xml`), ni test de
humo generado sobre los ficheros tocados, ni comprobación de que el test **ejercita** lo cambiado.
**Impacto:** falso verde, que es el fallo más caro de un harness (peor que un rojo).

### F7 · Sin streaming ni cancelación parcial
`stream: False` en los dos transportes OpenAI/Ollama. Un turno de 14 pasos con un modelo local es una
espera opaca; el operador no puede cortar una generación a medias, solo entre pasos. En API, además,
el time-to-first-token es la diferencia entre «parece vivo» y «parece colgado».

### F8 · Navegación de código sin inteligencia de código
Hay `search_files` (rg), mapa AST (`repo_map`) y lectura por rangos. No hay **LSP** (definición,
referencias, diagnósticos, tipos) ni índice semántico. OpenCode ya integra LSP; Aider usa el grafo del
repo con ranking. Aquí el modelo sigue descubriendo el código a base de `grep`, que es justo lo que el
mapa AST intentaba evitar.

### F9 · No se mide la calidad del agente, solo el ahorro
Las 34 suites prueban el arnés contra sí mismo. El benchmark A/B mide tokens. **No hay golden set de
tareas** («arregla este bug», «añade este endpoint») con tasa de éxito por modelo y por rol, ni
regresión de capacidad cuando se cambia de modelo. El ledger dice 1 verde de 7: es el único indicador de
éxito real que existe, y es anecdótico.

### F10 · El verde depende de una máquina concreta
Ruta absoluta al gobernador repetida en al menos 8 módulos (`C:\Proyectos\NexusProtocol`), `NEXUS_HOME`,
`Path.home()/AppData/Local/hermes/...` en el índice de skills. Sin `.github/` (no hay CI). Un usuario
nuevo que clone el repo obtiene un harness que no arranca en verde. **No es open-source todavía: es
open-code.**

### F11 · Aislamiento del árbol, no del proceso
`worktree_sandbox` aísla la reparación en un `git worktree` (bien). Pero `shell` ejecuta en el host y
`policy.py` es una lista de denegaciones. No hay sandbox de proceso (AppContainer/Job Object en Windows,
bubblewrap/contenedor en Linux), ni límites de CPU/RAM/red por comando.

### F12 · Los módulos están en el techo
`triad_loop.py` = 399/400 líneas. La ley se cumple, pero el diseño ya no admite ni una feature sin
partirlo. Cualquier pilares de este documento exige **dividir antes de añadir** (eso es sano: el techo
está haciendo su trabajo).

### F13 · Una sola corrida a la vez, por diseño
`Autopilot` rechaza un segundo bucle; `bridge.MAX_WORKERS = 1`; `delegate_task` con `depth=1`,
`max_children=3`, `subagent_steps=8`. Es prudente hoy y es el cuello de botella mañana: la flota es lo
que convierte «un agente que prueba» en «un sistema que converge».

---

## 3. Lo que hay que asimilar del estado del arte

| capacidad | de dónde viene | ¿la tenemos? | veredicto |
|---|---|---|---|
| Cierre determinista con gate + juez separado | propio (Nexus) | **sí** | ventaja; no tocar |
| Contabilidad de ahorro por request con recibos | propio | **sí** | ventaja; falta tokenizer real |
| Relevo de sesión con evidencia y exit codes | propio | **sí** | ventaja; falta resumen semántico |
| Repo map con ranking de símbolos | Aider | parcial (AST plano, sin ranking) | mejorar: PageRank sobre grafo de imports |
| Modo arquitecto (modelo que planea ≠ modelo que edita) | Aider | **sí** (roles) | ventaja; falta escalado por coste |
| LSP: definición, referencias, diagnósticos | OpenCode | **no** | P1 alto valor |
| Plugins/hooks sin tocar el core | OpenCode / Hermes | **no** | P2 |
| Skills con divulgación progresiva y memoria curada | Hermes | parcial (2 skills, memoria manual) | **P0** |
| Delegación con contexto aislado | Hermes | parcial (depth 1, 3 hijos) | P1 |
| Búsqueda de sesiones pasadas | Hermes | **no** (transcripts sin índice) | P1 |
| Cron / daemon residente | Hermes | parcial (`nightshift`, hive parado) | P1 |
| MCP | Hermes / OpenCode | **sí** (cliente stdio) | ventaja |
| Streaming + cancelación | todos | **no** | P1 |
| Eval de capacidad con golden tasks | nadie completo | **no** | P1 (diferenciador) |

---

## 4. Arquitectura objetivo: siete pilares

Cada pilar tiene un módulo dueño, un invariante que se puede testear y un comando de verificación. Sin
esas tres cosas, un pilar es una intención.

### Pilar 1 · Contexto: de «recortar» a «compilar»
Un **compilador de contexto** con presupuesto declarado y secciones con prioridad, no una pila de
parches. Reglas:
- **Prefijo estable** (`L0`): reglas + memoria + skills del turno, congeladas al inicio del turno. Nunca
  se reescribe dentro del turno → caché de prefijo viva.
- **Delta** (`L1..Ln`): mapa AST, ficheros, resultados, en mensajes posteriores. Solo crece por el final.
- **Presupuesto por sección** con tokenizer real por familia de modelo (`tokenizer.py`, contador
  inyectable; `chars/4` queda como *fallback declarado*, no como verdad).
- **Recibos** intactos: lo podado sigue siendo reconstruible.

Módulos: `context/compiler.py` (≤250), `context/budget.py` (≤180), `tokenizer.py` (≤150).
Invariante: `hash(prefijo)` idéntico en los N pasos de un turno; error de presupuesto < 5 % frente al
`usage` real del proveedor.
Verificación: `python tools/proofs.py context` (nuevo) + una suite que compara prefijo paso 1 vs paso 9.

### Pilar 2 · Aprendizaje: de herramienta a reflejo
Tres reflejos, todos con evidencia obligatoria:
1. **Reflejo de fallo** (`ForgeTrigger` cableado en `Registry.call`): mismo patrón 3 veces → propuesta
   de skill; el Obrero la escribe **solo** con observaciones del turno (nunca de memoria del modelo).
2. **Reflejo de éxito** (nuevo): al cerrar verde, un paso de reflexión destila **una** regla accionable
   («este repo exige `python -m pytest -q` antes de tocar `X`») y la escribe en memoria o skill con el
   exit que la respalda.
3. **Reflejo de selección**: cada skill que viaja deja fila `(skill, turno, exit, juez)`. El ranking
   pasa de léxico puro a léxico + **tasa de éxito bayesiana suavizada**. Una skill que no gana turnos en
   50 oportunidades se propone para archivo.

Módulos: `learning/reflection.py` (≤220), `learning/outcomes.py` (≤180), `skill_router` adelgazado.
Invariante: **cero** escrituras de memoria/skill sin un exit code observado en el turno; toda skill
forjada con `sha256` + procedencia + contador de resultados.
Verificación: `tools/proofs.py learning` (nuevo) — un turno rojo que acaba forjando y otro que no.

### Pilar 3 · Autonomía: de «siguiente paso» a «spec viva»
El salto que convierte el ejecutor en constructor:
1. **Objetivo → spec**: el Director escribe `cas` **ejecutables** (`command`, `expect_exit`), no prosa.
2. **Validación de la spec**: cada CA se corre en el estado actual; una spec cuyos CAs ya pasan es
   inútil y se rechaza. Un CA que no se puede ejecutar no entra.
3. **Grafo, no lista**: los pasos son nodos con dependencias; el planificador devuelve un DAG corto (3-7
   nodos) y el loop ejecuta en orden topológico, paralelizando lo independiente.
4. **Spec viva**: un hallazgo del turno puede **añadir** un CA (nunca borrar uno congelado), con firma y
   fecha. La spec crece con el proyecto.
5. **Parada honesta**: no «el Director dice que no quedan pasos», sino «los N CAs ejecutables pasan y el
   juez no objetó en los últimos K turnos».

Módulos: `spec/synth.py` (≤300), `spec/criteria.py` (≤200), `spec/graph.py` (≤200), `autonomy` partido en
`autonomy/loop.py` + `autonomy/cycle.py`.
Invariante: ningún CA sin comando; ninguna fase se marca hecha sin su exit; la spec congelada no se
debilita.
Verificación: `tools/proofs.py selfspec` — un objetivo en una carpeta vacía produce spec con ≥3 CAs
ejecutables y el bucle llega a verde sin intervención.

### Pilar 4 · Verificación: de gate a oráculo
- **Autodetección de runner** (pytest/unittest/npm/cargo/go/phpunit/dotnet) con el comando real en la
  spec → `tests` deja de ser opcional: si no hay forma de probar, el gate devuelve **20**, no verde.
- **Test de humo generado** sobre los ficheros tocados (importa el módulo, ejecuta la función cambiada
  con casos triviales) cuando el proyecto no tiene tests: barato, determinista, y convierte «no
  configurado» en «probado mínimamente».
- **Detección de regresión**: correr los tests que fallaban antes y pasan ahora, y viceversa (matriz de
  transición), no solo el exit global.
- **Mutation smoke** (P2): mutar 3 líneas del diff y comprobar que algún test se pone rojo. Si no, el
  verde no vale nada.

Módulos: `verify/discovery.py` (≤180), `verify/smoke.py` (≤220), `gate` adelgazado.
Invariante: **el gate nunca devuelve 0 sin al menos una comprobación de comportamiento ejecutada**.

### Pilar 5 · Modelo y proveedor: de rol fijo a cartera
- **Cartera por rol** con presupuesto: local primero; al segundo rojo, **escalado** a un modelo mayor o
  a la nube (con `cost_limit` chequeado antes de la llamada).
- **Failover** por transporte (429/5xx/timeout) con presupuesto de reintentos y proveedor alternativo
  declarado.
- **Hints de caché** por proveedor y `cached_tokens` contados como ahorro **medido** (no estimado).
- **Enrutado por dificultad**: el Director estima dificultad y elige modelo de la cartera; el juez
  siempre distinto del obrero.

Módulos: `providers.py` → `providers/{router,portfolio,health}.py`.
Invariante: ninguna llamada sin registrar coste; ningún escalado sin presupuesto restante.

### Pilar 6 · Paralelismo: de obrero a flota
- **Worktrees paralelos** (`max_children` real, no 3) con el mismo gate por rama.
- **Best-of-N** en tareas de alto riesgo: N intentos independientes, gana el que pasa gate + juez con
  menos diff.
- **Verificación cruzada**: un hijo revisa el diff de otro con el mismo gate (no con otro LLM).
- **Presupuesto compartido**: la flota consume de un solo `CostBudget`.

Módulos: `fleet.py` (≤300), `subagents.py` adelgazado, `worktree_sandbox` con pooling.
Invariante: ningún resultado de hijo entra al árbol principal sin gate verde en su worktree.

### Pilar 7 · Operación: de cabina a plataforma
- **CI real** (GitHub Actions, Windows + Linux, rutas relativas, `NEXUS_PROTOCOL` opcional con
  *fallback* vendorizado mínimo) → el verde deja de depender del PC del operador.
- **OTel**: el protocolo ya exporta spans OTLP; el arnés debe emitir `turn`, `request`, `tool`, `gate`.
- **Plugins/hooks** (`nexus_harness.toml` + puntos `before_turn`, `after_tool`, `before_commit`) para
  que un tercero extienda sin editar el core.
- **Daemon residente** con cola multi-proyecto y cuotas por proyecto (hoy `MAX_WORKERS = 1`).
- **Eval harness**: 20 tareas golden en 3 lenguajes, tabla de éxito por modelo/rol, ejecutable en CI.
- **Sandbox de proceso** para `shell` (Job Object/AppContainer en Windows, bwrap en Linux) con límites.

---

## 5. Roadmap priorizado

Criterio de orden: primero lo que **multiplica el ahorro sin tocar la arquitectura**, después lo que
**crea capacidad nueva**, al final lo que **abre la plataforma**.

### P0 — dos semanas, sin cambiar el contrato de nadie
| # | trabajo | por qué primero | verificación |
|---|---|---|---|
| P0.1 | Prefijo estable + `tokenizer.py` + presupuesto por sección | ahorro inmediato en API y local; arregla F2/F3 | `proofs.py context`: hash estable, error < 5 % |
| P0.2 | Un solo router de skills + telemetría de resultados | elimina F1 y prepara el aprendizaje; quita código muerto | `proofs.py skills`: una fuente, filas de resultado |
| P0.3 | Cablear `ForgeTrigger` + reflexión de éxito | primer reflejo real de aprendizaje (F4) | `proofs.py learning`: rojo→forja, verde→regla |
| P0.4 | Autodetección de tests + gate nunca verde sin comportamiento | elimina el falso verde (F6), el fallo más caro | `proofs.py oracle`: proyecto sin `test_command` |

### P1 — el salto que el usuario pidió: que el proyecto se construya
| # | trabajo | verificación |
|---|---|---|
| P1.1 | `spec/synth.py`: objetivo → CAs ejecutables, validados contra el estado actual | `proofs.py selfspec` en carpeta vacía |
| P1.2 | Planificador DAG + spec viva + parada por criterios | `proofs.py graph`: 3 nodos, 2 en paralelo |
| P1.3 | Cartera de modelos + escalado local→nube con presupuesto | `proofs.py portfolio`: 2º rojo escala |
| P1.4 | LSP (`definition`, `references`, `diagnostics`) como 3 herramientas | `proofs.py lsp` con un proyecto Python |
| P1.5 | Eval harness con golden tasks + tabla por rol | `tools/eval.py --suite core` |

### P2 — plataforma
Streaming y cancelación · CI multiplataforma · OTel · plugins/hooks · sandbox de proceso · flota
paralela con best-of-N · daemon multi-proyecto · índice semántico incremental · búsqueda de sesiones.

---

## 6. Qué NO haría (anti-features)

- **Vector DB para todo el repo.** Un RAG mal rankeado mete ruido con factura. El mapa AST + grep + LSP
  es más barato y más determinista. Índice semántico solo para «¿dónde se habla de esto?».
- **Compactación por resumen de LLM como mecanismo principal.** Un resumen inventa y pierde decisiones.
  La poda determinista con recibo es superior; el resumen, como capa opcional y auditada.
- **Auto-commit sin gate verde.** Ya está bien resuelto; no relajar.
- **Enjambre de agentes sin contratos.** Paralelismo sin gate por rama es entropía con factura.
- **Más herramientas antes de mejores herramientas.** 12 herramientas bastan; lo que falta es
  diagnóstico, no cantidad.
- **Subir el techo de 400 líneas.** El techo está funcionando: `triad_loop.py` a 399 es la señal de que
  hay que partir, no de que hay que ampliar.

---

## 7. Criterios de aceptación de v2 (nuevos CAs, ejecutables)

1. `python tools/proofs.py context` → el prefijo del prompt es idéntico en los N pasos de un turno.
2. `python tools/proofs.py context` → error de presupuesto < 5 % frente al `usage` del proveedor.
3. `python tools/proofs.py skills` → una sola fuente de skills; cada skill inyectada deja fila de
   resultado con exit.
4. `python tools/proofs.py learning` → turno rojo repetido forja skill con procedencia; turno verde
   escribe regla con su exit.
5. `python tools/proofs.py oracle` → proyecto sin `test_command` detectado y probado; gate 20 si no hay
   forma de probar.
6. `python tools/proofs.py selfspec` → objetivo en carpeta vacía → ≥3 CAs ejecutables → bucle verde sin
   intervención humana.
7. `python tools/proofs.py portfolio` → segundo rojo escala de modelo respetando `cost_limit`.
8. `tools/verify.py` sigue GREEN con todo lo anterior y **cero** ficheros > 400 líneas.
9. `.github/workflows/verify.yml` verde en Windows y Linux con el repo recién clonado.

---

## 8. Resumen en una frase

El motor está terminado y es mejor que el de los tres referentes en lo que importa (cierre y evidencia);
lo que falta es **compilar el contexto en vez de recortarlo**, **aprender de los resultados en vez de
guardar skills**, y **escribir la spec en vez de obedecerla**. En ese orden.
