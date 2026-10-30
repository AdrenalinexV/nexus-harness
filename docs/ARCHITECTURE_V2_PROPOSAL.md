# Arquitectura v2 · Propuesta desde cero

> Revisión de arquitecto sobre Nexus-Harness v1.1.0 (`f8a2491`), 2026-10-29.
> Estado medido: `verify: GREEN` — 63 suites, 0 hallazgos, 0 ficheros > 400 líneas, 0 dependencias.
> Este documento es una **crítica**, no un plan aprobado. Cada decisión lleva problema → decisión →
> invariante → migración → coste. Ordenado por **coste de hacerlo tarde**, no por vistosidad.

---

## 0. El orden manda: dos cosas empeoran si esperan, una desbloquea todo

1. **Publicar primero.** Remoto + CI + CHANGELOG + LICENSE. Sin CI, el «verde» no es una propiedad del
   repo, es una propiedad de un PC. Es lo más barato y lo que abre todo lo demás.
2. **Streaming antes de más superficie.** Hoy el transporte es `stream: False`. Añadir streaming *después*
   de LSP, plugins y flota obliga a reabrir el bucle tres veces. Se hace una vez, ahora.
3. **Sandbox de proceso antes de abrir la autonomía.** Un demonio que obedece la bandeja ejecuta comandos
   en el host. Cuanto más autónomo sin sandbox, más superficie peligrosa acumulada.

---

## 1. El defecto estructural nº1: el espacio de nombres es plano

`nexus_harness/` tiene 52 módulos planos y 12 carpetas (`context/`, `core/`, `llm/`, `platform/`,
`selftests/`, `skills/`, `tools/`, `verify/`, `web/`; `llm/transports/` ya cuelga de su capa), así que el
espacio de nombres sigue siendo mayoritariamente plano. Eso es lo que hace que el techo de 400 líneas
**duela**: `triad_loop.py` a 399 no es «un módulo grande», es **una capa entera sin casa**.

**Decisión:** organizar por **capa**, con invariante de dependencia (nada importa hacia arriba):

```
nexus_harness/
  core/        loop, message, events, turn_engine, turn_context          (el bucle)
  llm/         transports/, providers, portfolio, tokenizer
  tools/       toolbox/, tools, mcp_client
  context/     compiler, pruner, compaction, relay_state, repo_map
  verify/      gate, judge, oracle, smoke
  autonomy/    autonomy, daemon, plan_graph, spec_synth
  spec/        spec_synth (los criterios viven dentro; `criteria.py` nunca existió)
  learning/    outcomes, reflection, skill_forge, skill_router
  platform/    settings_*, web/, cockpit, vault, vps_deployer
```

**Invariante:** un ciclo de imports entre capas = test rojo. `core` no importa `verify`; `tools` no
importa `autonomy`.
**Migración:** un paquete por commit, gate verde entre cada uno. No hay big-bang.
**Coste:** ~1 semana. **Efecto:** el techo de 400 vuelve a tener aire y la próxima feature entra sin tocar
el diseño.

---

## 2. El agujero de seguridad: el sandbox debe ser un **puerto**, no una lista negra

`policy.py` deniega *dentro* del proceso. Eso no es aislamiento: es una valla cuyo guardia está dentro del
jardín.

**Decisión:** contrato `Sandbox` con tres adaptadores y **fail-closed**:

| plataforma | mecanismo | modo por defecto |
|---|---|---|
| Windows | Job Object + token restringido (AppContainer) | `workspace-write`, red off |
| Linux | bubblewrap + Landlock/seccomp | `workspace-write`, red off |
| macOS | Seatbelt (`sandbox-exec`) | `workspace-write`, red off |

**Invariante duro:** si no hay sandbox disponible, `unrestricted` **se rechaza con razón explícita**, nunca
degrada en silencio. Es el modelo de Codex — el único del panel con aislamiento a nivel de kernel.
**Coste:** 3–4 semanas. **Efecto:** cierra el riesgo nº1 y es la mayor subida de credibilidad disponible.

---

## 3. Streaming: cambia el **tipo de retorno**, no añadas un flag

`chat(messages, tools) -> Reply`. Añadir `stream=True` encima crea dos caminos para lo mismo → código
muerto garantizado (ya pasó: el `SkillRouter` que la auditoría encontró sin instanciar en producción).

**Decisión:** el transporte devuelve un **iterador de eventos** (`delta`, `reasoning`, `tool_call`, `done`)
y `Reply` se construye *plegando* eventos; el modo no-streaming es un plegado trivial.
**Invariante:** el bucle consume eventos, nunca bytes; el botón Detener corta el iterador, no solo entre
pasos. Un camino, dos modos.
**Coste:** 1 semana. **Efecto:** cancelación real y time-to-first-token visible.

---

## 4. La deuda de honestidad: los números deben **generarse**, no escribirse

El propio informe admite que el README decía «28 suites» cuando había 48. En un proyecto cuya bandera es
*«lo que no se mide no se afirma»*, eso no es indisciplina: es **un defecto arquitectónico**. Mientras las
cifras se escriban a mano, mentirán.

**Decisión:** comando `nexus_harness release` que (a) corre el gate, (b) **inyecta las cifras medidas** en
los docs (suites, ficheros, ahorro, LOC) desde el ledger/verify, y (c) **falla si un doc contradice la
medición**. Docs como artefacto de build.
**Invariante:** ningún número en `docs/` que no salga de un comando.
**Coste:** 3 días. **Efecto:** la honestidad deja de ser disciplina y pasa a ser imposible de olvidar.

---

## 5. Gobernanza → 10: cerrar los dos falsos-verdes que quedan

El gate ya devuelve `20` cuando no puede probar. Falta lo que lo hace inalcanzable:
- **Autodetección obligatoria de runner** (pytest / npm / cargo / go / dotnet) — *descubierto*, no declarado.
- **Test de humo generado** sobre los ficheros tocados cuando el proyecto no tiene tests.
- **Mutation smoke:** mutar 3 líneas del diff y exigir que **algún** test se ponga rojo. Si no se pone rojo,
  ese verde no vale nada.

**Invariante:** *un criterio cuyo check pasa por razones ajenas marca el trabajo hecho para siempre y
esconde el hueco* (lección ya escrita en la skill del proyecto).
**Coste:** 2 semanas. **Efecto:** convierte el 9 en 10 en el eje donde nadie más compite.

---

## 6. Extensibilidad: reutiliza el **contrato del hook que ya existe**

Hay un contrato excelente para hablar con harness ajenos: un JSON entra, un mensaje sale, `exit 0/10/20/30`.
No inventes otro para plugins.

**Decisión:** generaliza ese contrato a `before_turn / after_tool / before_commit / pre_verify`, declarado
en `nexus_harness.toml`. Un solo contrato, dos consumidores (harnesses externos y plugins locales).
**Coste:** 2 semanas. **Efecto:** deja de ser fork de nadie y pasa a ser plataforma.

---

## 7. Flota: un orquestador **por encima** del triad, nunca dentro

El triad a 399 líneas no debe crecer. La flota (`best-of-N`, verificación cruzada, presupuesto compartido)
es un planificador que instancia N worktrees, cada uno con su gate, y **promociona solo el que queda verde
con menos diff**.

**Invariante:** ningún resultado de un hijo entra al árbol principal sin gate verde en su worktree, y hay
**un solo** `CostBudget` compartido (o el techo se multiplica por N).
**Coste:** 3 semanas.

---

## 8. Lo que NO tocaría (anti-arquitecturas)

- **No metas LangChain/LangGraph/AutoGen.** El estudio de 11 harnesses confirma que **ninguno** de ~4 M de
  líneas los usa.
- **No introduzcas embeddings/vector DB** para retrieval. Nadie del panel lo hace; grep + mapa AST + LSP
  gana en determinismo y coste.
- **No relajes el techo de 400 líneas.** `triad_loop.py` a 399 es el síntoma sano de que toca dividir.
- **No uses resumen por LLM como compresión principal.** Inventa hechos y borra decisiones; la poda
  determinista con recibo es superior.

---

## Priorización (por coste de hacerlo tarde)

| # | trabajo | por qué ahora | coste |
|---|---|---|---|
| 1 | Publicar (remoto + CI + CHANGELOG + LICENSE) | desbloquea verificación externa | 1 sem |
| 2 | Capas + invariante de dependencia | devuelve aire al techo de 400 | 1 sem |
| 3 | Streaming (refactor de tipo del transporte) | hacerlo tarde = 3 pasadas | 1 sem |
| 4 | Sandbox de proceso (puerto fail-closed) | riesgo real, no estético | 3–4 sem |
| 5 | `release` que genera los números en los docs | mata la deuda de honestidad | 3 días |
| 6 | Mutation smoke + autodetección de runner | gobernanza 9 → 10 | 2 sem |
| 7 | Hooks/plugins sobre el contrato existente | de herramienta a plataforma | 2 sem |
| 8 | Flota (worktree por rama, gate por rama) | paralelismo con contrato | 3 sem |

**Si hay que elegir una sola:** **el sandbox de proceso.** Es el único eje donde hoy estamos en 4 y el
riesgo es real, no cosmético.

---

*Propuesta generada el 2026-10-29. Método: lectura del árbol real + auditorías propias del proyecto
(`docs/FUTURE_AUDIT.md`, `docs/CONTEXT_SAVINGS_AUDIT.md`) + estudio de referencia arXiv 2609.00006.*
