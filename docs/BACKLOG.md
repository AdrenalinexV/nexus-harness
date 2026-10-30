# Backlog — la única fuente de lo que queda abierto

> **El orden en que se arregla** vive en `docs/ROADMAP.md`; este fichero dice **qué** está abierto y ese
> dice **cuándo** toca. Si se contradicen, manda el roadmap y este fichero se corrige en el mismo commit.
>
> **Por qué este fichero existe.** La verdad estaba repartida entre `AUDIT_2026-10-29.md` (que se
> describe como medición de un día y no como cola), `UI_BACKLOG.md` (cerrado) y
> `ARCHITECTURE_V2_PROPOSAL.md` (una crítica, no un plan aprobado). Así es como un número viejo sobrevive
> a la sesión que lo iba a desmentir: nadie era el dueño de la lista.
>
> **Reglas de esta lista.** (1) Una fila por cosa abierta, con el comando que la cierra. (2) Una fila
> cerrada se queda con su commit y su comando — se tacha, no se borra: es el registro de que se midió.
> (3) Ninguna cifra se teclea: `python tools/doc_truth.py` la compara con el motor y pone el build rojo.
> (4) Lo que no se pudo medir se escribe **no medido** con el comando que lo cerraría.

Medido hoy: 64 suites · 232 ficheros · 0 hallazgos de lint · 0 ficheros > 400 líneas.

---

## 1. Abierto — lo que rompe o falta

| # | qué | dónde | por qué duele | cómo se cierra |
|---|---|---|---|---|
| **B6** | ~~`rows()` no deduplica~~ **CERRADO** en la fase 4: la fila lleva la identidad de la corrida (`id`/`started`/checkpoint) y `rows()` deduplica | `f30ea31` | — | `selftest projects` → dos escritores, **1 fila**, 120 tokens; `selftest autonomy` → dos ciclos, 2 filas |
| **B11** | ~~`dist/` obsoleto~~ **CERRADO** en la fase 4: motor 1.2.0 construido del árbol y `--frozen` comparando suites contra el fuente | `dist/` | — | `find nexus_harness -name '*.py' -newer dist/nexus-harness-engine.exe \| wc -l` → **0**; `verify.py --frozen` → `frozen exit 0 suites=63 failures=0` |
| **B13** | `docs/VERIFICATION.md` se commitea con la corrida **sin** gobernador | `docs/VERIFICATION.md` | el CI publicaría otro número que el documento | regenerar con `--write-doc` en modo gobernador y dejar escrito que el CI publica el otro |
| **B15** | ~~`llm/` a medias~~ **CERRADO** en la fase 2: `transports/` vive en `llm/transports/`, 0 imports hacia arriba | `llm/providers.py` | — | `grep "from \.\.transports" nexus_harness/llm/` → 0 |
| **Capas** | **9 de 9 paquetes** migrados (fase 2 cerrada). `skill_forge` y `skill_router` se quedan en tools/ y context/ — medido: moverlos invertiría la dependencia | `nexus_harness/*.py` | quedan 50 módulos planos: el techo de 400 sigue doliendo ahí | `selftests/test_layers.py` verde con el invariante intacto |
| **D · Sandbox** | ~~AUSENTE~~ **CERRADA** en la fase 3: `policy` exige jaula de ficheros para `unrestricted`; Job Object (Win), bwrap (Linux) y seatbelt (macOS) se aplican al ejecutar | `a5f79eb` | — | `selftest sandbox` → OK (6 casos, incluido un hijo que muere con tope de 64 MB y el Job que mata el árbol) |
| **C · Streaming** | ~~AUSENTE~~ **CERRADA** en la fase 3: los cuatro transportes devuelven eventos, `chat()` = `fold(stream())` y Detener corta el socket en vuelo | `2627150` · `41de9b8` · `d88be86` | — | `selftest stream` → OK (12 casos); `verify` GREEN en los dos modos |
| **B · LSP** | ~~AUSENTE~~ **CERRADA** en la fase 3: cliente JSON-RPC por stdio, `definition` y diagnósticos tras cada escritura; `references` queda como siguiente (no estaba en el criterio del paso 12) | `3ba9c5d` | — | `selftest lsp` → OK (5 casos, con un servidor falso que habla el protocolo) |
| **G · Hooks** | ~~AUSENTE~~ **CERRADA** en la fase 3: 4 puntos, contrato 0/10/20/30, fail-closed | `88c8018` | — | `selftest hooks` → OK (9 casos) |
| **H · Evals** | ~~PARCIAL~~ **CERRADA** en la fase 3: 20 tareas en 3 lenguajes (Python, JavaScript, Bash) y mutation smoke sobre 18 de ellas | `e19fd2c` | — | `selftest eval` → OK (20 tareas + 54 mutaciones); la negativa `over-400` sigue en 10/10 |

| **K1** | LSP `references` no existe: solo `definition` y diagnósticos | `platform/lsp.py` | un renombrado enseña los usos en `definition` pero no todos | tool `references` sobre el cliente que ya habla el protocolo; servidor falso en la suite |
| **K2** | jaula de ficheros real en Windows: el Job Object contiene procesos, no escrituras | `platform/sandbox.py` | `unrestricted` sigue negado en Windows (fail-closed, por diseño) | AppContainer + ACL del proyecto, o bwrap por WSL, con la matriz ampliada |
| **K3** | la cadena ⚡ es secuencial: dos ramas independientes no corren a la vez | `autonomy/kanvas_runner.py` | un grafo ancho tarda lo que suma, no lo que el máximo | dos worktrees (`verify/worktree_sandbox.py`) y el mismo gate por rama |

## 2. Cerrado en esta sesión (con su comando)

| # | qué | commit | verificación |
|---|---|---|---|
| — | **Tipografía determinista**: `nexus-sans.woff2` + `nexus-mono.woff2` (84 KB las dos, OFL en `web/OFL.txt`), pilas con respaldo de sistema | `ef36f95` | DOM de `/` y `/settings`: `[href],[src]` con `^https?` → **0**; wheel en venv limpio sirve los `.woff2` |
| **B7** | las 5 herramientas de `tools/` vuelven a importar, y la suite `repo_scripts` lo vigila | `40adce5` | `prove_repair_cycle.py --fake` → exit 0, `cycle: true` |
| **B10** | cifras publicadas generadas, no tecleadas: `tools/doc_truth.py` + suite + job de CI | e19fd2c | `python tools/doc_truth.py` → exit 0; con el README a 49 → exit 1 |
| **B9** | `verify.py` deja de reescribir `docs/VERIFICATION.md` salvo con `--write-doc` | e19fd2c | `python tools/verify.py` → `git status --porcelain` vacío |
| **B8** | el docstring del gate describe la conducta real (comando declarado → runner detectado → humo de importación → 20) | e19fd2c | `gate --project t --touched calc.py` → `behavior OK humo de importacion: smoke: 1/1` exit 0 |
| **B14** | **no reproducible**: `nexus/` no está muerto, es el puntero al gobernador; ahora lo exige la suite `protocol_pointer` | e19fd2c | OK con gobernador · **FAIL** con el puntero roto · SKIP sin gobernador |
| **B12** | `docs/EVAL.md` contaba las omitidas como resueltas: 7/7 → **5/7 + 2 omitidas** | e19fd2c | `doc_truth` compara el titular con su propia tabla |
| **C** | **Streaming**: eventos `delta/reasoning/tool_call/done`, `Reply` por `fold`, failover solo antes del primer evento, Detener cierra el socket, cabina por SSE | `2627150` · `41de9b8` · `5873cfd` | `selftest stream` → OK (12 casos): JSON partido, servidor que se cuelga (0,52 s) y turno entero por el cable |
| **D** | **Sandbox**: `unrestricted` sin jaula de ficheros se niega con motivo; matriz 3 modos × 3 jaulas; Job Object con kill-on-close y tope de memoria medidos | `a5f79eb` | `selftest sandbox` → OK (6 casos); `verify` GREEN en los dos modos |
| **B** | **LSP**: cliente JSON-RPC 2.0 por stdio, `definition` (LSP → AST con la razón impresa) y diagnósticos en el resultado de cada `patch`/`write_file` | `3ba9c5d` | `selftest lsp` → OK (5 casos); `definition(symbol=build_prefix)` → `context_compiler.py:81` |
| **H** | **Evals**: 20 tareas (10 Python, 5 JavaScript, 5 Bash) y mutation smoke — 3 mutaciones por tarea y ninguna sobrevive | `e19fd2c` | `selftest eval` → OK (9,3 s); `over-400-is-rejected` → exit 10 |
| **I** | **Release**: versión 1.2.0 en paquete y app, motor y instalador reconstruidos, instalación real actualizada por sha256, `--frozen` contra el fuente | `f181119` | `verify.py --frozen` → `frozen exit 0 suites=63 failures=0 skipped=7`; `installer_verify --verify` → 0 |
| **B6** | **Ledger**: identidad de corrida (`RunResult.id` uuid) y `rows()` deduplicado; dos escritores suman una vez y dos ciclos siguen sumando dos | `f30ea31` | `selftest projects` → 1 fila / 120 tokens; `selftest autonomy` → 2 filas |

## 3. Decisiones cerradas por el operador (no se reabren)

1. **Tipografía empaquetada: SÍ, acotada.** Hecho en `ef36f95`: dos familias OFL, ≤150 KB, `font-display: swap` y sistema de respaldo.
2. **Traducción EN/ES de la interfaz: NO ahora.** `lang` ya se consume donde importa (los prompts del juez en `llm/judge.py`). Cuando haya un segundo usuario será `ui_strings.py` con un test que exija las mismas claves en los dos idiomas — nunca inline.
3. **Rediseño de `/gov`: NO aquí.** Es HTML del gobernador servido por proxy (`gov.py`): se rompería en su siguiente cambio. Se queda como pantalla ajena con su entrada en la barra lateral; si algún día se quiere bonito, se hace en su repo.

## 4. No medido (y el comando que lo cerraría)

| no medido | por qué | comando |
|---|---|---|
| Ahorro real −57,9 % contra un modelo en la nube | `benchmark_ab_savings.py --doc-only` es determinista y no llama a ningún proveedor | `python tools/benchmark_ab_savings.py --steps 8 --vendor <proveedor>` con clave |
| Juez real sobre un turno de código | no hay proveedor configurado en esta máquina | `python -m nexus_harness run "<goal>" --project <tmp>` y leer el veredicto |
| LSP real (servidor de lenguaje instalado) | la suite mide el protocolo con un servidor falso y el fallback al mapa AST | `python -m nexus_harness selftest lsp` con `pyright`/`clangd` en el PATH |
