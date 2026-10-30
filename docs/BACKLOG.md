# Backlog — la única fuente de lo que queda abierto

> **Por qué este fichero existe.** La verdad estaba repartida entre `AUDIT_2026-10-29.md` (que se
> describe como medición de un día y no como cola), `UI_BACKLOG.md` (cerrado) y
> `ARCHITECTURE_V2_PROPOSAL.md` (una crítica, no un plan aprobado). Así es como un número viejo sobrevive
> a la sesión que lo iba a desmentir: nadie era el dueño de la lista.
>
> **Reglas de esta lista.** (1) Una fila por cosa abierta, con el comando que la cierra. (2) Una fila
> cerrada se queda con su commit y su comando — se tacha, no se borra: es el registro de que se midió.
> (3) Ninguna cifra se teclea: `python tools/doc_truth.py` la compara con el motor y pone el build rojo.
> (4) Lo que no se pudo medir se escribe **no medido** con el comando que lo cerraría.

Medido hoy: 59 suites · 203 ficheros · 0 hallazgos de lint · 0 ficheros > 400 líneas.

---

## 1. Abierto — lo que rompe o falta

| # | qué | dónde | por qué duele | cómo se cierra |
|---|---|---|---|---|
| **B6** | `TurnLedger.rows()` no deduplica (`history()` sí) y `improve.py:96` lo lee directo | `platform/ledger.py:44`; `improve.py:96` | el planificador de mejoras ve turnos rojos duplicados e infla tokens ×1,87 | fixture con dos escritores → **1 fila** por corrida |
| **B11** | `dist/` obsoleto: el `.exe` y el instalador son más viejos que el fuente | `dist/` | un binario viejo pasa cualquier proof que solo mire `failures=0` | `find nexus_harness -name '*.py' -newer dist/nexus-harness-engine.exe \| wc -l` → **0** |
| **B13** | `docs/VERIFICATION.md` se commitea con la corrida **sin** gobernador | `docs/VERIFICATION.md` | el CI publicaría otro número que el documento | regenerar con `--write-doc` en modo gobernador y dejar escrito que el CI publica el otro |
| **B15** | `llm/` está a medias: `nexus_harness/transports/` sigue fuera y `llm/providers.py` lo importa hacia arriba (×5) | `llm/providers.py:14-16` | «6/9 capas» es optimista: son 6 paquetes, no 6 capas cerradas | mover a `llm/transports/`, matriz de imports sin ciclos |
| **Capas** | 6 de 9 paquetes migrados; faltan `autonomy/` (autonomy, autonomy_ask, daemon, plan_graph), `spec/` (spec_synth, criteria) y `learning/` (reflection, improve, skill_forge, skill_router) | `nexus_harness/*.py` | el techo de 400 duele porque hay 57 módulos planos y 10 carpetas | un paquete por commit; `selftests/test_layers.py` verde con el invariante intacto |
| **D · Sandbox** | **AUSENTE**: `policy.classify('rm -rf build','unrestricted')` → `allowed=True` | `shell_policy.py`; `policy.py` | la autonomía es un riesgo declarado, no un módulo | puerto fail-closed (Job Object/AppContainer, bwrap+Landlock, Seatbelt); sin jaula, `unrestricted` se **niega** con razón |
| **C · Streaming** | **AUSENTE**: `stream: False`; `Reply` es una dataclass plana; Detener corta entre pasos, no la request | `transports/*`; `llm/portfolio.py` | no hay un camino, dos modos; no hay cancelación real | transporte que devuelve **iterador** de eventos (`delta/reasoning/tool_call/done`) y `Reply` plegándolos |
| **B · LSP** | **AUSENTE**: 0 coincidencias; `mcp_client.py` es JSON-RPC **MCP**, no LSP | — | paridad de herramientas con Codex/Claude Code | 3 tools (definition/references/diagnostics) sobre el stdio que ya existe, degradando al mapa AST **con razón impresa** |
| **G · Hooks** | **AUSENTE**: no hay `nexus_harness.toml`, ni `pre_verify`, ni exit **30** | — | es el eje que convierte el producto en ecosistema | contrato JSON-in/mensaje-out en `before_turn/after_tool/before_commit/pre_verify`; hook que devuelve 10 → gate rojo, 0 → verde, 30 → no verificable |
| **H · Evals** | 7 tareas y **1 solo lenguaje**; sin mutation smoke | `eval_tasks.py`; `tools/eval.py` | mide capacidad, no autoestima | ~20 tareas en 3 lenguajes + mutar 3 líneas pone ≥1 test rojo; la negativa sigue en 10/10 |

## 2. Cerrado en esta sesión (con su comando)

| # | qué | commit | verificación |
|---|---|---|---|
| — | **Tipografía determinista**: `nexus-sans.woff2` + `nexus-mono.woff2` (84 KB las dos, OFL en `web/OFL.txt`), pilas con respaldo de sistema | `ef36f95` | DOM de `/` y `/settings`: `[href],[src]` con `^https?` → **0**; wheel en venv limpio sirve los `.woff2` |
| **B7** | las 5 herramientas de `tools/` vuelven a importar, y la suite `repo_scripts` lo vigila | `40adce5` | `prove_repair_cycle.py --fake` → exit 0, `cycle: true` |
| **B10** | cifras publicadas generadas, no tecleadas: `tools/doc_truth.py` + suite + job de CI | (esta fase) | `python tools/doc_truth.py` → exit 0; con el README a 49 → exit 1 |
| **B9** | `verify.py` deja de reescribir `docs/VERIFICATION.md` salvo con `--write-doc` | (esta fase) | `python tools/verify.py` → `git status --porcelain` vacío |
| **B8** | el docstring del gate describe la conducta real (comando declarado → runner detectado → humo de importación → 20) | (esta fase) | `gate --project t --touched calc.py` → `behavior OK humo de importacion: smoke: 1/1` exit 0 |
| **B14** | **no reproducible**: `nexus/` no está muerto, es el puntero al gobernador; ahora lo exige la suite `protocol_pointer` | (esta fase) | OK con gobernador · **FAIL** con el puntero roto · SKIP sin gobernador |
| **B12** | `docs/EVAL.md` contaba las omitidas como resueltas: 7/7 → **5/7 + 2 omitidas** | (esta fase) | `doc_truth` compara el titular con su propia tabla |

## 3. Decisiones cerradas por el operador (no se reabren)

1. **Tipografía empaquetada: SÍ, acotada.** Hecho en `ef36f95`: dos familias OFL, ≤150 KB, `font-display: swap` y sistema de respaldo.
2. **Traducción EN/ES de la interfaz: NO ahora.** `lang` ya se consume donde importa (los prompts del juez en `llm/judge.py`). Cuando haya un segundo usuario será `ui_strings.py` con un test que exija las mismas claves en los dos idiomas — nunca inline.
3. **Rediseño de `/gov`: NO aquí.** Es HTML del gobernador servido por proxy (`gov.py`): se rompería en su siguiente cambio. Se queda como pantalla ajena con su entrada en la barra lateral; si algún día se quiere bonito, se hace en su repo.

## 4. No medido (y el comando que lo cerraría)

| no medido | por qué | comando |
|---|---|---|
| Ahorro real −57,9 % contra un modelo en la nube | `benchmark_ab_savings.py --doc-only` es determinista y no llama a ningún proveedor | `python tools/benchmark_ab_savings.py --steps 8 --vendor <proveedor>` con clave |
| Juez real sobre un turno de código | no hay proveedor configurado en esta máquina | `python -m nexus_harness run "<goal>" --project <tmp>` y leer el veredicto |
| Sandbox / streaming / LSP / hooks | no existen (0 coincidencias en producción) | sus suites de aceptación, que hay que escribir (arriba, columna derecha) |
