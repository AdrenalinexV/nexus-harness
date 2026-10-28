# Autonomía de v1.0 — las cinco piezas que faltaban

Documento corto y verificable: cada pieza tiene su módulo, su suite y el comando que la mide. Si algo
de aquí no pasa su comando, no existe.

| pieza | módulo | comando |
|---|---|---|
| relevo de contexto (55 % poda · 70 % handover) | `relay_state.py`, `session_relay.py`, `compaction.py` | `python -m nexus_harness selftest` |
| contexto compilado: prefijo estable + tokenizer calibrado | `context_compiler.py`, `turn_context.py`, `tokenizer.py` | `python tools/proofs.py context` |
| skills: catálogo único, techo de 10 y resultados | `skill_router.py`, `outcomes.py` | `python tools/proofs.py skills` |
| aprendizaje: fallo repetido forja, verde tras reparar enseña | `reflection.py` | `python tools/proofs.py learning` |
| oráculo: runner descubierto y humo de importación | `oracle.py`, `gate.py` | `python tools/proofs.py oracle` |
| spec sintetizada: objetivo → criterios ejecutables validados | `spec_synth.py`, `nexus_harness spec` | `python tools/proofs.py spec` |
| plan en grafo, olas y parada por criterios | `plan_graph.py`, `autonomy.py` | `python tools/proofs.py plan` |
| cartera de modelos: escalado, failover y caché contada | `portfolio.py`, `providers.py` | `python tools/proofs.py portfolio` |
| eval de capacidad: 7 tareas golden con verdad ejecutable | `eval_tasks.py`, `evalgym.py`, `tools/eval.py` | `python tools/eval.py --fake` |
| daemon autonomo: bandeja, triggers, reanudacion y avisos | `daemon.py`, `tasks.py`, `notify.py`, `improve.py` | `python tools/proofs.py daemon` |
| navegador nativo: DOM→texto, perfil con cookies, muros declarados | `toolbox/browser.py` | `python tools/proofs.py browser` |
| reparación en `git worktree` | `worktree_sandbox.py`, `repair_guard.py` | `python tools/proofs.py worktree` |
| deploy al VPS (SSH + Compose) | `vps_deployer.py`, `settings_vps.py` | `python tools/proofs.py deploy` |
| juez con contexto + pista de líneas reales | `judge.py`, `repair_hint.py` | `python tools/proofs.py judge` |

## 1. Relevo de contexto

`BudgetMeter` mide tokens reales por respuesta. `unmeasured` no es 0 %: sin uso informado no se
dispara nada. En el 55 % (`compact_threshold`) el transcript se poda: las salidas de herramientas
viejas se sustituyen por `[salida podada] <path> (N líneas, sha256=...)`, y la compactación
determinista condensa lo que ya nadie lee. En el 70 % (`relay_threshold`) se escribe
`.nexus/RELAY_STATE.json` (clave `harness`, sin pisar `phases`/`queue` del protocolo), se genera
`.nexus/NEXT_SESSION_PROMPT.md` desde ese estado y la sesión sigue en una nueva, numerada y enlazada.
La píldora superior lo dice: `🔄 Relevo automático de contexto`.

## 2. Skills — un solo catálogo, y un libro de resultados

El enrutado **se hace en un solo sitio**: `skill_router.library(root)` escanea el protocolo, las skills
forjadas y el catálogo de Hermes (173 skills medidas en esta máquina) y aplica un techo duro de 10. Lo
que no viaja se indexa en `.nexus/skills-dormant/` con su sha256: bytes en disco, cero tokens en la
ventana.

El cuerpo entero **nunca** viaja: el brief son una línea por skill (nombre + descripción recortada), y
el `SKILL.md` se lee con `read_file` cuando hace falta. Medido: 173 cuerpos ≈ 446.714 tokens; el brief
de un turno real, 137.

Cada turno cerrado apunta `(skill, proyecto, exit, juez)` en `.nexus/harness/skill_outcomes.jsonl`. De
ahí sale un multiplicador suavizado y acotado (`0,7 .. 1,3`) que ajusta el score léxico: una skill que
resuelve turnos sube, una que los pierde baja, y ninguna sustituye a la evidencia. Sin muestras el
factor es 1,0 — no se inventa corrección.

## 3. Spec sintetizada — el bucle ya no obedece una spec escrita a mano

`python -m nexus_harness spec "<objetivo>" [--write] [--model]` convierte un objetivo en criterios
**ejecutables** (`command` + `expect_exit`), los **valida en el acto** y solo entonces los congela en
`.ai/CURRENT_SPEC.json`:

- un criterio sin comando no entra; uno que no se puede lanzar (comando inexistente, política de shell)
  se descarta y se dice por qué;
- cada criterio guarda su `evidence.exit` de hoy: la spec nace con hechos, no con promesas;
- si **todos** los criterios ya pasan, la spec no se congela (`actionable=false`): no hay nada que
  construir y un plan sin hueco es una firma;
- al fusionar, lo ya congelado **no se pierde** y solo se añaden criterios nuevos; `cas_sha256` cubre el
  conjunto.

Medido de punta a punta en un proyecto de prueba (`pytest.ini` + test rojo): el comando descubrió
`python -m pytest -q`, lo ejecutó (`exit 1`), y congeló `CA1` con esa evidencia.

## 4. Plan como grafo y parada por criterios

El Director ya no devuelve un paso suelto: devuelve `{"nodes": [...], "new_criterion": ...}` con hasta
**7 nodos** y sus dependencias (`plan_graph.py`).

- **Un ciclo se rechaza al validar**, no se ejecuta a medias: `n1 -> n2 -> n1` es un plan imposible.
- **Olas topológicas**: `waves()` dice qué se puede hacer a la vez. La ejecución dentro de una ola es
  secuencial a propósito — dos escrituras en el mismo árbol compiten, y ese es el fallo que el gate
  existe para cazar. El grafo describe el paralelismo; el worktree por rama lo hará seguro.
- **Los nodos hechos se persisten** en el progreso (`nodes`), así que un plan repetido no re-ejecuta lo
  que ya está verde.

**La parada ya no es «el Director dice que no quedan pasos»**: en cada ciclo se ejecutan los criterios
congelados (`spec_synth.evaluate`) y, si **todos** pasan, el proyecto se cierra con **cero llamadas al
modelo** y el paso `criterios cumplidos` en el progreso. Vacio no es éxito: una spec sin comandos no
opina y el bucle sigue planificando.

**La spec crece con el trabajo**: si el Director descubre algo que la spec no mide, devuelve
`new_criterion`; `spec_synth.add_criterion` lo **ejecuta**, y solo si no se cumple ya y su comando
funciona lo añade (`origin: director`, `grown_by`, sha recalculado). Nunca quita un criterio congelado.

## 5. Cartera de modelos — una caída no termina el turno

Cada rol puede declarar una **escalera** en `~/.nexus/harness.json`:

```json
{"roles": {"worker": "lmstudio:kat-coder"},
 "role_ladders": {"worker": ["lmstudio:kat-coder", "deepseek:deepseek-chat"],
                  "judge": ["lmstudio:qwen3.8-27b", "openai:gpt-4o-mini"]}}
```

Dos comportamientos, y los dos se declaran:

- **Failover.** `Router.role()` devuelve un `FailoverTransport`: prueba los peldaños en orden y
  devuelve el primero que contesta. El bucle no sabe que existe (misma cara que un transporte), y si
  **todos** caen el error agrega el motivo de cada uno. Un peldaño sin clave se declara `not ready` y
  se pasa al siguiente; nunca se salta en silencio.
- **Escalado.** Al **segundo** gate rojo del turno, `maybe_escalate` sube un peldaño y el router cambia
  de modelo para el resto del run (evento `router.escalated`). Si no hay siguiente, o el presupuesto en
  USD ya se cruzó, **no se escala** y se dice por qué (`router.escalate_refused`). Escalar a un modelo
  más caro con el techo agotado es empeorar el problema.

**Caché de proveedor, medida y no supuesta.** `Usage.cached` se lee de cada proveedor
(`prompt_tokens_details.cached_tokens`, `prompt_cache_hit_tokens`, `cache_read_input_tokens`), viaja al
libro de turnos (`cached_tokens`) y abarata el coste con un descuento **declarado** del 10 % sobre la
entrada (`budget.CACHE_DISCOUNT`). No se cuenta como «tokens ahorrados»: es dinero, no contexto.

## 6. Worktree del Obrero

`config.worktree_repairs` (por defecto `True`) hace que la reparación corra en
`.nexus/harness/worktrees/<id>` sobre una rama `nexus/sandbox/*`. Allí se ejecuta el MISMO gate del
proyecto. Verde: los ficheros cambiados se copian al árbol principal y se vuelven a medir. Rojo (o el
Obrero lanza): el worktree se descarta y el árbol principal no se tocó. En una raíz que no es git se
degrada al comportamiento anterior, y lo dice.

## 7. Deploy 24/7

`vps_deployer` lee `VPS_HOST`, `VPS_USER`, `VPS_PORT`, `VPS_SSH_KEY` de la bóveda, empaqueta el kit de
`NexusProtocol/deploy` + secretos, lo sube por `scp`/`ssh` (BatchMode) y levanta
`docker compose up -d --build`. En el VPS, `secrets.env` queda `0600`. Todo se puede planificar
(`plan()`, `dry_run=True`) y en `/settings` nada se ejecuta de verdad sin marcar `confirm`; el
resultado se pinta redactado (`***`).

## 8. Juez y reparación de llamadas

`mode_for()` decide por hechos: sin ficheros ni gate es **conversación** (se juzga utilidad, no diff);
con ficheros o gate es **código** (se exige la evidencia). `RepairHints` cuenta fallos por
`(herramienta, fichero)` y al SEGUNDO devuelve las líneas reales del fichero, numeradas, alrededor de
la línea que el error menciona. Un acierto de escritura limpia el contador de ese fichero.

## 9. Eval de capacidad — aciertos, no adjetivos

`python tools/eval.py --fake` corre **7 tareas golden** contra el mismo `Triad` de producción y publica
una tabla de aciertos (`docs/EVAL.md`). Cada tarea es un proyecto diminuto con una verdad ejecutable:

| tarea | qué exige |
|---|---|
| `fix-subtraction` | arreglar un bug con `patch_replace` y dejar el test en 0 |
| `add-function` | añadir `mul()` sin romper `add()` |
| `rename-symbol` | renombrar en dos ficheros (multi-fichero real) |
| `delete-dead-code` | borrar una función muerta y no dejar rastro |
| `recover-syntax` | arreglar un `def` sin dos puntos y dejarlo importable |
| `respect-policy` | encontrarse la negativa de la política de shell y seguir |
| `over-400-is-rejected` | **negativa**: un fichero de 402 líneas tiene que acabar en `exit 10` |

Dos modos y dos preguntas distintas:

- `--fake` (CI, sin red ni modelo): ¿el **arnés** convierte un guion correcto en verde y un fichero que
  rompe la ley en rojo? Si esta tabla baja, el que se rompió es el motor.
- `--model <spec>`: ¿el **modelo** que tengo resuelve el trabajo? Es la tabla que se compara entre
  modelos y la que detecta una regresión al cambiar de cartera.

El veredicto nunca sale del resumen del modelo: sale del `exit`, del contenido en disco y de los
eventos del bus (para la negativa de política).

Dos cosas que el eval declara en vez de fingir:

- **`respect-policy` es `script_only`.** Con un modelo real se **omite** con su motivo: exige que el
  modelo obedezca una orden destructiva, y un modelo que se niega está haciendo lo correcto. La política
  se prueba de forma determinista en su suite (`shell_policy`), no pidiéndole al modelo que la rompa.
- **`--repeat N`** separa pass@k de fiabilidad: `passed` cuenta tareas con algún intento bueno y
  `stable` las que pasaron en **todos**. Con un 27B local las dos cifras difieren, y esa diferencia es
  el dato (un modelo que acierta a la segunda no es un modelo que acierta).

## 10. Daemon — trabajo autonomo sin ventana abierta

`python -m nexus_harness daemon` cierra el circulo: nadie tiene que abrir la cabina para que el trabajo
avance. Un tick hace, en este orden (y el orden es la propiedad de seguridad):

1. **Bandeja** — lo que pidio una persona o un bot (`task add`, o una linea en `inbox.jsonl`).
2. **Spec** — si el proyecto no tiene criterios, intenta congelar los que el repo ya sabe probar. Sin
   runner no se inventa trabajo: se encola «declara como se prueba esto».
3. **Criterios** — si ya pasan, el proyecto no se toca y se encolan mejoras medidas (`improve.py`).
4. **Trabajo** — un ciclo de `Autopilot` (backup, plan, gate, juez, commit) y el progreso a disco.

Un daemon en reposo **no gasta tokens**: sin tarea y sin criterio rojo no hay llamada al modelo. Un
segundo daemon se niega a arrancar (cerrojo con pid). El estado vive en `NEXUS_HOME/harness/daemon.json`
y la bandeja en `<workspace>/.nexus/harness/inbox.jsonl`.

Avisos a Discord/Telegram/ntfy con `notify` en `~/.nexus/harness.json` (valores `$SECRETO` se resuelven
de la boveda). Detalle operativo, contrato para bots y unidad de systemd para el VPS: `docs/DAEMON.md`.

## 11. Navegador nativo — donde `fetch_url` no llega

La herramienta `browser` conduce un navegador real (Edge/Chrome del sistema, o Chromium de Playwright)
para las páginas que un `curl` no puede leer: JavaScript, login, cookies, muros anti-bot.

- **DOM → texto**, no capturas: se devuelve el texto visible y los enlaces, recortado con recibo. Una
  captura cuesta ~0,8 s de codificación y solo muestra lo que cabe en pantalla.
- **Perfil persistente** en `.nexus/browser/profile`: una web con login se abre una vez.
- **Un muro se declara**: 403/429 o «Just a moment» devuelve error con el motivo, no un texto de 12
  caracteres que parece una respuesta.
- **Vive en su propio hilo**: Playwright síncrono se niega a arrancar dentro de un bucle de asyncio, y el
  arnés corre dentro de uno; el worker resuelve las dos cosas y la sesión persiste entre llamadas.

Acciones: `goto`, `extract` (busca líneas), `click`, `fill`, `press`, `links`, `screenshot`, `close`,
`restart`. Si no hay motor instalado, la herramienta **lo dice** y sugiere `fetch_url`.

## Dogfooding

`python tools/dogfood.py --iterations 3` usa el propio `Autopilot` sobre este repositorio: backup,
Director con la spec y el mapa AST (`repo_map.py`, cacheado por `mtime`), Obrero con worktree, gate,
Juez y commit atómico. Lo que produce se mide con `python tools/verify.py`, no con este documento.
