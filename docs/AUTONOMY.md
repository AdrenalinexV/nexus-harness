# Autonomía de v1.0 — las cinco piezas que faltaban

Documento corto y verificable: cada pieza tiene su módulo, su suite y el comando que la mide. Si algo
de aquí no pasa su comando, no existe.

| pieza | módulo | comando |
|---|---|---|
| relevo de contexto (55 % poda · 70 % handover) | `relay_state.py`, `session_relay.py`, `compaction.py` | `python -m nexus_harness selftest` |
| skills: techo de 10 + dormidas + forja | `skill_router.py`, `skill_forge.py`, `toolbox/skill_tools.py` | `python tools/proofs.py skills` |
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

## 2. Skills

`skill_router` puntúa el catálogo contra la tarea y las extensiones de los ficheros tocados, y aplica
un techo duro de 10. Lo que no viaja se indexa en `.nexus/skills-dormant/` (nombre, descripción, ruta,
sha256): bytes en disco, cero tokens en la ventana. `skill_forge` escribe
`.nexus/skills/<slug>/SKILL.md`, valida su frontmatter y lo registra con `origin=forged` + sha256 en el
libro de procedencia del protocolo (o en `.nexus/skills-provenance.jsonl` si no está). El Director
tiene la herramienta `forge_or_update_skill`, y no pisa una skill existente sin `overwrite`.

## 3. Worktree del Obrero

`config.worktree_repairs` (por defecto `True`) hace que la reparación corra en
`.nexus/harness/worktrees/<id>` sobre una rama `nexus/sandbox/*`. Allí se ejecuta el MISMO gate del
proyecto. Verde: los ficheros cambiados se copian al árbol principal y se vuelven a medir. Rojo (o el
Obrero lanza): el worktree se descarta y el árbol principal no se tocó. En una raíz que no es git se
degrada al comportamiento anterior, y lo dice.

## 4. Deploy 24/7

`vps_deployer` lee `VPS_HOST`, `VPS_USER`, `VPS_PORT`, `VPS_SSH_KEY` de la bóveda, empaqueta el kit de
`NexusProtocol/deploy` + secretos, lo sube por `scp`/`ssh` (BatchMode) y levanta
`docker compose up -d --build`. En el VPS, `secrets.env` queda `0600`. Todo se puede planificar
(`plan()`, `dry_run=True`) y en `/settings` nada se ejecuta de verdad sin marcar `confirm`; el
resultado se pinta redactado (`***`).

## 5. Juez y reparación de llamadas

`mode_for()` decide por hechos: sin ficheros ni gate es **conversación** (se juzga utilidad, no diff);
con ficheros o gate es **código** (se exige la evidencia). `RepairHints` cuenta fallos por
`(herramienta, fichero)` y al SEGUNDO devuelve las líneas reales del fichero, numeradas, alrededor de
la línea que el error menciona. Un acierto de escritura limpia el contador de ese fichero.

## Dogfooding

`python tools/dogfood.py --iterations 3` usa el propio `Autopilot` sobre este repositorio: backup,
Director con la spec y el mapa AST (`repo_map.py`, cacheado por `mtime`), Obrero con worktree, gate,
Juez y commit atómico. Lo que produce se mide con `python tools/verify.py`, no con este documento.
