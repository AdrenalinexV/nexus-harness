# Dónde está la competencia (y qué copiamos)

Revisión hecha el 2026-10-28. No es un informe de marketing: cada fila dice **qué se adopta** y qué se
descarta, con la fuente delante. El criterio es el de siempre: si no se puede verificar con un comando,
no entra.

## Lo que el mercado ya convergió (y nosotros tenemos a medias)

| patrón | quién lo demuestra | estado en Nexus | decisión |
|---|---|---|---|
| Agente de fondo con **trigger** (issue, cron, Slack, CI) y artefacto revisable | [OpenHands background agents](https://openhands.dev/blog/background-agents-for-coding-tasks) | `daemon.py` + `task add` + bandeja JSONL | **adoptado** (P1.6) |
| **Estado durable** que reanuda a mitad de trabajo, no reinicia | [Harness patterns](https://lucagattoni.github.io/Claude-Loops/24-harness-patterns) (initializer + coding agent) | `progress.json` con nodos + `daemon.json` | **adoptado**; falta reanudar DAG multi-fase |
| **Verificación en dos capas**: determinista + juez inferencial | Fowler, citado por OpenHands | `gate.py` + `judge.py` (juez ve el contenido desde hoy) | **ventaja**: el gate corre *antes* del juez |
| **Fail-closed**: sin backup no se edita; rojo no se promociona | OpenHands/Codex | `autonomy.py` (backup → plan → gate → commit) | **ventaja**, con evidencia por turno |
| **Ciclo de reparación acotado** (máx. 5) con veredicto mecánico | Harness patterns | `max_repairs` + gate real | adoptado; el juez ya no rechaza sin evidencia |
| **DAG por tarea** (no pipeline fijo de N agentes) | Harness patterns | `plan_graph.py` (≤7 nodos, olas, ciclos rechazados) | **adoptado**; ejecución en ola aún secuencial |
| Memoria por **capas** (core / recall / archival) | [MemGPT/Letta](https://www.letta.com/blog/agent-memory/), [Atlan](https://atlan.com/know/agent-memory-architectures/) | `memory.md` plano + skills | **pendiente** (P2, SQLite+FTS5) |
| Navegador **DOM-first**: extrae texto/markdown, screenshot solo si hace falta | [browser-use](https://browser-use.com/posts/speed-matters) | `toolbox/browser.py` (Edge/Chrome en worker) | **adoptado**; falta proxy/CAPTCHA de pago |
| **Sandbox de proceso** por ejecución (contenedor/microVM) | Codex, Devin, OpenHands | worktree (árbol) + política de comandos | **pendiente**: aislamiento del árbol ≠ del proceso |
| **LSP** para definición/referencias/diagnósticos | Claude Code, OpenCode | mapa AST + rg | pendiente (P1.4) |
| Multi-modelo por **workflow** con router | [OPENDEV](https://arxiv.org/pdf/2603.05344v2) | `role_ladders` + cartera + failover | adoptado; falta medir y elegir cartera |
| **Coste por turno** con techo duro | Claude Code `--max-budget-usd` | `budget.py` + libro con caché | **ventaja**: precio y caché medidos, no estimados |

## Lo que NO copiamos

- **Resumen de contexto escrito por el modelo** (Anthropic server-side compaction): puede afirmar un
  hecho que el turno no tuvo. Nuestro digest es determinista y auditable.
- **Pipeline fijo de N agentes** (planner/generator/QA siempre): se paga complejidad en tareas que no
  la necesitan. DAG dimensionado por tarea.
- **Screenshots como canal principal** del navegador: ~0,8 s por imagen y solo ves lo que cabe en
  pantalla. DOM→texto primero.
- **Lock-in de proveedor**: aquí el spec es `vendor:modelo` y una escalera; cambiar de API es config.

## Lo que nos pone por delante (y hay que mantener)

1. **Cierre determinista con recibo**: `gate` + `judge` + `ledger` por turno. Nadie del mercado
   publica el exit code de cada criterio como artefacto del trabajo.
2. **Contabilidad de ahorro por request** con baseline, poda, skills dormidas y caché medida.
3. **Spec sintetizada y viva**: objetivo → criterios ejecutables → validados → congelados. La
   competencia pide el plan; nosotros lo validamos antes de obedecerlo.
4. **Adaptadores de harness** (Aider, Claude Code) con un contrato genérico (`gate --hook`).

## Riesgos que la revisión deja abiertos

- **Sandbox**: sin aislamiento de proceso, un comando hostil dentro de una política `unrestricted` es el
  agujero más grande que queda.
- **Reanudación fina**: hoy se reanuda por nodos, no por fase con evidencia parcial de una ola.
- **Volumen de eval**: 5 tareas medibles es un instrumento, no un benchmark. Para comparar modelos hacen
  falta ~20 con dificultad graduada.
