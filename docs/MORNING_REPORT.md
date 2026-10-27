# Informe de la noche — Nexus-Harness v1.0.0

Fecha: 2026-10-27 · Base: `f340f19` (v0.5.0) · HEAD: `99ed438` · 10 commits atómicos.

**Resultado: rúbrica 23/23 en verde con medición fresca, `verify --frozen` GREEN, protocolo 71/71 checks
y release `unlock` verde.** Lo que NO se hizo, se dice en «Límites» al final.

## 1. Rúbrica (medida esta noche, criterio a criterio)

| # | criterio | exit |
|---|---|---|
| 1 | gate-lint | 0 |
| 2 | suites-source | 0 |
| 3 | frozen-engine | 0 |
| 4 | protocol-lint | 0 |
| 5 | protocol-doctor | 0 |
| 6 | hook-contract | 0 |
| 7 | adapter-aider | 0 |
| 8 | adapter-claude | 0 |
| 9 | providers-retry | 0 |
| 10 | tool-arg-repair | 0 |
| 11 | shell-policy | 0 |
| 12 | context-compaction | 0 |
| 13 | turn-checkpoint | 0 |
| 14 | cost-budget | 0 |
| 15 | evidence-export | 0 |
| 16 | no-orphans | 0 |
| 17 | installer | 0 |
| 18 | relay-auto | 0 |
| 19 | skills-autonomous | 0 |
| 20 | worktree-isolation | 0 |
| 21 | vps-deploy | 0 |
| 22 | judge-context | 0 |
| 23 | spec-priority | 0 |

Salida cruda por criterio: `.ai/HARNESS_STATE.json`; tabla regenerada por
`python tools/nightshift.py report` → `docs/NIGHT_REPORT.md`.

## 2. Qué se construyó (y qué comando lo prueba)

### Fase 1 — Relevo de contexto
- `nexus_harness/relay_state.py`: poda al 55 % (`[salida podada] path (N líneas, sha256=…)`) + estado
  del relevo en `.nexus/RELAY_STATE.json` bajo la clave `harness`, **sin pisar** `phases`/`queue` del
  protocolo (el primer intento los borraba: medido, 3 fases → 1).
- `session_relay.py` escribe el estado antes del prompt y lo expone en `status()`; `triad_loop` poda
  salidas en cada vuelta y emite `context.pruned`; el gate verde se guarda como último veredicto.
- **Prueba de producción (no simulada):** el dogfooding disparó dos relevos reales,
  `session_09 -> session_10` y `session_12 -> session_13`, con el bucle continuando.

### Fase 2 — Skills autónomas
- `skill_router.py`: puntuación determinista por tarea/extensiones y **techo duro de 10**; lo que no
  viaja queda indexado en `.nexus/skills-dormant/` (0 tokens).
- `skill_forge.py`: escribe `SKILL.md`, valida frontmatter, registra `origin=forged` + sha256 en el
  libro del protocolo (o `skills-provenance.jsonl` local); `ForgeTrigger` pide forja al tercer fallo
  del mismo patrón, una sola vez.
- Herramienta nueva en el arsenal del Director: `forge_or_update_skill(topic, reason, observations)`.
  Suites: `tools/proofs.py skills`.

### Fase 3 — Deploy VPS
- `vps_deployer.py`: credenciales desde la bóveda (`VPS_HOST`, `VPS_USER`, `VPS_PORT`, `VPS_SSH_KEY`),
  `ssh`/`scp` en BatchMode, `secrets.env` **0600**, `docker compose up -d --build`, `plan()` y
  `dry_run` sin red, logs **redactados**.
- `settings_vps.py`: bloque en `⚙ Configuración → 📱 Puente Móvil & Deploy VPS (Hive 24/7)` con los dos
  modos y `confirm` obligatorio; sin la casilla, solo enseña el plan.
- Suites: `tools/proofs.py deploy`.

### Fase 4 — Aislamiento y mapa
- `worktree_sandbox.py`: rama + worktree en `.nexus/harness/worktrees/<id>`, gate dentro, `promote`
  solo en verde, `discard` siempre; `reap()` borra huérfanos por edad.
- `repair_guard.py`: `worktree_repairs=True` (por defecto) repara en el sandbox y re-mide al promover;
  sin git se degrada declarándolo.
- `repo_map.py`: mapa AST por fichero (clases/bases/firmas/líneas/imports), cacheado por `mtime_ns`,
  techo de tokens; el Director lo recibe en el prompt del planificador.
- Suites: `tools/proofs.py worktree`.

### Fase 5 — Juez y reparación de llamadas
- `judge.mode_for()`: sin ficheros ni gate ⇒ **conversación** (utilidad); con ficheros o gate ⇒
  **código** (evidencia). `Judgement.mode` viaja en el veredicto.
- `parse_verdict()` reescrito: escaneo de llaves (no regex codiciosa), comas finales, comillas curvas y
  veredicto explícito en JSON roto. Sin JSON ni declaración ⇒ reject (no se aprueba por cansancio).
- `repair_hint.py`: al **segundo** fallo del mismo `(herramienta, fichero)` inyecta las líneas reales
  numeradas alrededor de la línea que el error menciona; un write correcto limpia el contador.
- `web/app.js`: el razonamiento va en `<details class="reasoning">`, entero y escapado.
- Suites: `tools/proofs.py judge`.

### Fase 6 — UX
- Píldora de actividad: relevo (`🔄`), poda (`🧹`) y skill forjada (`🧠`) además de tríada/gate/juez.
- `Nexus-Harness` es el **#1** de la cola (`~/.nexus/harness.json`) y tiene
  `.ai/CURRENT_SPEC.json` con 3 CAs reales (`selftest`, `lint_harness`, `verify`).
- Versión 1.0.0 en motor, paquete, Tauri y lanzador.

## 3. Dogfooding real (`tools/dogfood.py`)

Cuatro corridas con los modelos configurados (`lmstudio`), backup por ciclo, gate real y Juez real:

| corrida | resultado | hallazgo |
|---|---|---|
| 0 (humo) | rojo | el Director devolvía solo `reasoning_content`; el planificador lo ignoraba → bucle parado. **Arreglado** |
| 1 | rojo (Juez) | el Obrero leyó y razonó 18 pasos sin editar; el Juez lo rechazó. Se ejercitó el relevo real `session_09→10` |
| 2 | rojo (gate) | el Obrero escribió un caso para `test_relay_state.py`; falló porque `keep_last` protegía la única salida. Se corrigió el supuesto y el caso queda verde |
| 3 | rojo (Juez) | el Obrero añadió `mode_for([], '', False) == 'conversation'` (verde) y el Juez rechazó por **JSON malformado** → defecto real del parser. **Arreglado** y con caso |

Ninguna corrida terminó con commit automático del bucle: el Juez rechazó o el gate quedó rojo. Los
cambios válidos que produjo se verificaron y se commitearon a mano; los defectos que reveló están
arreglados y con test. El bucle no se auto-aprobó ni una vez, que es lo que tenía que pasar.

## 4. Evidencia de cierre

```
$ python tools/verify.py --frozen
lint      exit 0   files=119 findings=0 max_lines=400 ignored_runtime=0
selftest  exit 0   suites=33 failures=0
frozen    exit 0   suites=33 failures=0 (same as the source)
verify: GREEN

$ python -m nexus doctor            -> 71 checks, 0 failed
$ python nexus/cli.py release       -> unlock gate=done exit=0 (66/66 CA, 7 rojas en base → verdes)
$ python tools/nightshift.py status -> cumplidos 23/23
$ python tools/nightshift.py install --check
  instalador : NexusHarness-Setup-1.0.0.exe -> exit 0
  ventana    : nexus-harness-desktop.exe subsystem=2
  motor      : repo sha256=9f19796c01c3 == instalado sha256=9f19796c01c3
  desinstalar: exit 0 · sala eliminada · registro devuelto como estaba
```

Artefactos: `dist/nexus-harness-engine.exe` (17,7 MB, 33 suites),
`dist/NexusHarness-Setup-1.0.0.exe` (18,8 MB, NSIS por usuario).

## 5. Límites (lo que no está probado, y por qué)

1. **El deploy al VPS no se ejecutó contra un VPS real.** La bóveda de esta máquina tiene una sola
   clave y ninguna `VPS_*`, así que se verificó lo verificable: construcción de comandos, plan de 5
   pasos, `secrets.env` 0600, redacción y panel con `confirm`. Falta el host para la prueba de fuego.
2. **El dogfooding no produjo commits autónomos** (ver §3). Es un límite del modelo local y del tiempo
   por iteración (~8-12 min), no del bucle: backup, plan, tríada, gate, worktree y Juez corrieron.
3. **Los procesos `nexus-harness-*` vivos son la app instalada del operador** (23:12, motor 0.5.0),
   no huérfanos de esta sesión; `no-orphans` mide su propio contrato y pasó.
4. El mapa AST omite la carpeta `dist/` y los árboles de `node_modules` por diseño; el lint de línea
   filtra `.nexus/` (estado de ejecución) y lo declara con `ignored_runtime=`.

## 6. Siguiente paso sugerido

1. Meter `VPS_HOST`/`VPS_USER`/`VPS_SSH_KEY` en la bóveda y correr `vps_probe` + `vps_deploy` con
   `confirm` sobre el VPS de pruebas.
2. Subir el presupuesto de pasos del dogfooding a 24 con un objetivo de una sola edición y dejar que
   el bucle cierre él mismo el commit (hoy el Juez lo frena, y frena bien).
3. Revisar `docs/NIGHT_SHIFT.md` §«Subida del listón v1.0» con la evidencia de esta noche.
