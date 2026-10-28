# Nexus-Harness — architecture

A harness is three things: a way to talk to a model, a way to touch a repository, and a rule for when
the work is done. This one adds a fourth: a rule for when the **session** is done, and what the next
one inherits.

```
                     ┌───────────────────────────── cockpit (ui.py) ─────────────────────────────┐
  browser ──────────▶│  /api/run   /api/events   /api/models   /api/projects   /api/relay         │
                     └───────────────┬─────────────────────────────────────────────────────────────┘
                                     │  (same core, two clients: ui.py and cli.py)
  mobile /task ──▶ bridge.py ────────┤
  (.nexus/hive/queue.json)           ▼
                            ┌───────────────┐
                            │  triad_loop   │  Director → Worker → Gate → Judge → repair
                            └───┬───┬───┬───┘
              context_router.py │   │   │ gate.py + judge.py
        (nexus.skills.routing)  │   │   └── rules_lint.lint_repo + project tests + LLM judge
                                │   └── tools.py → toolbox/{shell,files,edit,web}.py
                                └── providers.py → transports/{openai_compat,ollama,anthropic}.py
                                               │
                                        session_relay.py ── nexus.hive.relay (plan/checkpoint/prompt)
```

## Module map and line budget

Measured on 2026-10-28 (v1.0.0): 161 Python files under the line law, the longest module 400 lines
(`triad_loop.py`). `python tools/lint_harness.py` reports 0 findings.

Every module answers one question. The budget column is the ceiling enforced by
`tools/lint_harness.py` (R2, 400 lines) reduced on purpose: a file that reaches 250 here is already
doing two jobs.

| Module | Question it answers | Budget |
|---|---|---|
| `config.py` | Where are the keys, which model plays which role, how big is a session? | 160 |
| `providers.py` | Given a role, which endpoint and model, and how do I call it uniformly? | 160 |
| `transports/http.py` | How do I POST JSON with `urllib` and turn a failure into a typed error? | 90 |
| `transports/openai_compat.py` | OpenAI / DeepSeek / OpenRouter / LM Studio / Ollama-`/v1` in one shape | 170 |
| `transports/ollama.py` | The native `/api/chat`: `thinking`, native tools | 140 |
| `transports/anthropic.py` | Messages API: `tool_use` / `tool_result` blocks | 140 |
| `message.py` | What is a message, a tool call, a reply, a usage count? | 110 |
| `context_window.py` | Cuantos tokens caben DE VERDAD en ese motor, y como se recorta sin romper el turno. | 300 |
| `turn_engine.py` | Quien llama al worker, con que presupuesto, y que pasa si el motor dice que no cabe. | 200 |
| `tools.py` | What tools exist, what are their JSON schemas, how are they dispatched? | 150 |
| `toolbox/file_ops.py` | Bytes in, bytes out: atomic write, SHA-256 check, syntax gate, BOM/CRLF. | 230 |
| `toolbox/fuzzy_match.py` | Locate the block the model meant: eight rungs, each still deterministic. | 300 |
| `toolbox/patch_v4a.py` | Multi-file `*** Begin Patch` envelopes, validated on an overlay, applied with rollback. | 350 |
| `toolbox/repo_search.py` | Read with line numbers, search with `rg` or a Python fallback, list. | 180 |
| `toolbox/edit.py` | One block or many; idempotent when already applied; line law enforced. | 130 |
| `toolbox/output_clip.py` | Head+tail clipping that keeps the full log on disk. | 60 |
| `toolbox/shell_session.py` | Run a command; remember the cwd and the exports; never open a console. | 190 |
| `toolbox/process_manager.py` | Background processes: spawn, poll, write, kill, tree-kill on Windows. | 280 |
| `subagents.py` | `delegate_task`: parallel children, closed history, bounded turns, worktrees. | 240 |
| `attachments.py` | Paste, drag, sniff, resize, extract and stage: three shapes of one file. | 300 |
| `onboarding.py` | What this machine has (servers, models, project) and one screen to accept it. | 240 |
| `vault.py` | Cloud keys at rest: DPAPI on Windows, 0600 elsewhere, never read back out. | 140 |
| `mcp_client.py` | MCP over stdio: hidden children, handshake, tools, deadlines, namespaced calls. | 320 |
| `sidecar.py` | A shell-launched engine leaves when the shell does: no orphan holds its own `.exe`. | 140 |
| `panels.py` | The four product surfaces as thin, testable seams over those modules. | 160 |
| `web/panels.js` | Attachments, the onboarding modal, the skills editor and the connectors list. | 290 |
| `toolbox/web.py` | Fetch a page as text without a browser or an API key. | 130 |
| `context_compiler.py` | ¿Qué es estable en el turno (prefijo) y qué cambia (delta append-only)? | 199 |
| `turn_context.py` | Una sola definición de prefijo/delta/presupuesto para el Chat y la Triada. | 130 |
| `tokenizer.py` | ¿Cuánto cuesta este texto, y cuánto se desvía este modelo de la estimación? | 188 |
| `oracle.py` | ¿Con qué se prueba este proyecto, y hay algo ejecutado antes de decir verde? | 180 |
| `skill_router.py` | ¿Qué skills viajan (≤10), con qué brief y qué tasa de éxito medida? | 400 |
| `outcomes.py` | ¿Qué skill ganó turnos y cuál los perdió? Un libro append-only. | 130 |
| `reflection.py` | ¿Qué regla deja este turno, con qué exit detrás? | 210 |
| `gate.py` | Is the tree actually green: lint, behavior, line law. | 200 |
| `judge.py` | Does the change answer the goal? Fail-closed when unparsable. | 130 |
| `triad_loop.py` | One turn: plan, act, verify, repair, close. | 300 |
| `events.py` | How does the cockpit watch a turn without a websocket? | 90 |
| `session_store.py` | What is on disk for a session, and how is it archived? | 130 |
| `session_relay.py` | When does this session hand over, and what does the next one inherit? | 250 |
| `bridge.py` | How does a `/task` from a phone become a run? | 150 |
| `ui.py` | The local server: static front-end, JSON API, cross-site and token guards. | 260 |
| `cli.py` | The clients' front door: `chat`, `run`, `serve`, `selftest`, `lint`, `models`. | 260 |
| `chat.py` | A conversation with tools: gate only when a turn touched files, repair in-turn, stop. | 280 |
| `cockpit.py` | The brain both clients share: one job at a time, chat + run, state for the UI. | 300 |
| `memory.py` | Durable facts, capped twice, travelling in every prompt. | 120 |
| `transcripts.py` | Conversations on disk, so closing the window is not losing the chat. | 120 |
| `web/` | The single front-end (index, css, js) served by the engine and loaded by the desktop shell. | — |
| `apps/desktop/` | Tauri 2 shell: free port, launch token, sidecar engine, NSIS installer. | — |

## What 0.5.0 adds, and who owns it

The cockpit grew three things that did not exist as modules before: a live status line, a priority
queue of governed projects, and a loop that keeps working on the #1 project until it is finished. Each
one answers a question and owns its state:

| Module | Question it answers | State it owns |
|---|---|---|
| `api.py` | What does `/api/*` answer? (the transport stayed in `ui.py`) | none: a pure `(status, payload)` per route |
| `activity.py` | What is the engine doing *right now*, and how did the last turn end? | none: it is a pure function over the bus and the last turn |
| `projects.py` | Which projects are governed, in what order, and what is frozen in each? | `project_order` in `~/.nexus/harness.json`, `.nexus/harness/autonomy.json` per project |
| `autonomy.py` | Snapshot, plan, run the triad, commit, advance — until done, red, or out of iterations | the loop's state, in memory, published through the bus |
| `backup.py` | How do I guarantee a way back before a loop edits anything? | `git stash create` + tag, or a zip in `.nexus/backups/` |
| `ledger.py` | What did each turn actually cost and prove? | `.nexus/harness/ledger.jsonl`, one line per turn, append-only |
| `charts.py` | How do I draw three charts with no library and no network? | none: SVG strings, pure functions |
| `runner.py` | Who builds a triad run, so three callers behave the same? | none |

The order inside an autonomy cycle is the safety property, not a detail: **backup → plan → run → gate
→ commit → progress**. If the snapshot cannot be taken, nothing is edited. If the gate is red after the
worker's repairs, that project stops and the queue moves on. Progress is written only after `exit 0`.

## The five contracts

### 1. Provider (`providers.py`)

```
Provider.chat(messages, tools=None, temperature, max_tokens) -> Reply
Reply = text | tool_calls | reasoning | usage(prompt, completion) | model
```

A role (`director`, `worker`, `judge`) resolves once, at `Router` construction, from
`~/.nexus/harness.json`, the environment, or a default — in that order. Reasoning models are not a
special case: a transport puts `reasoning_content` / `thinking` in `Reply.reasoning` and the loop
prints it as an event instead of feeding it back as content.

The model never sees a transport. That is what makes `ScriptedProvider` a legitimate stand-in in
tests: the loop cannot tell the difference, so the test measures the loop.

### 2. Context window (`context_window.py`, `turn_engine.py`)

El presupuesto de un turno no es un numero de la configuracion: es `min(budget_limit, ventana del
motor - max_tokens - 5 %)`, y la ventana se le pregunta al servidor en cada turno
(`/api/v0/models` en LM Studio, `/api/ps` en Ollama). Un motor que no la publica deja el presupuesto
como estaba y se declara "sin dato"; nunca se inventa un recorte.

`TurnEngine.ask()` es la ultima red: si el motor contesta `400 ... exceeds the available context size
(N tokens)`, el numero N **es** la ventana, asi que se aprende, se poda el historial de verdad
(`Compactor.hard`, umbral 0) y se repite una vez. Si el segundo intento tampoco cabe, el error dice
que subir la ventana del modelo en el servidor. Un 400 que no sea de tamano sube intacto: el arnes no
disfraza un fallo de respuesta.

Dos consecuencias que se midieron en produccion:

* el contador del compactor es el **calibrado** (`tokenizer.count_messages`) y no `chars/4`: con
  `chars/4` el mismo texto que el motor cuenta como 66.889 tokens se leia como 42.000, y la poda
  llegaba un 60 % tarde;
* la cartera de relevo no borra el tipo del fallo: si todos los peldanos fallan con un
  `TransportError`, se relanza ese error (con su `status` y su cuerpo) en vez de un `RuntimeError`
  resumen, porque el tipo es justo lo que decide si el turno se puede salvar.

### 3. Tools (`tools.py`)

A tool is `(name, description, JSON schema, callable(args, root) -> Observation)`. The registry
returns the OpenAI-shaped schema list, so the same tool dict serves all three transports.

`Observation` carries `ok`, `text`, `meta`. Failures are observations with `ok=False`, never
exceptions escaping the loop: a model that cannot see the error cannot fix it.

### 4. Gate (`gate.py`)

Exit `0` green, `10` red — the protocol's number, so a red gate is not a new vocabulary.

Checks, in order and all of them cheap: `rules_lint.lint_repo(root)` (R0–R3, 0 findings), the project's
declared test command (`test_command` in config, else `None` → reported as *not configured*, never as
green), and the line law on files the turn touched.

`Judge` is only consulted when the gate is green. A judge that approves broken code is worse than no
judge, which is why it never runs first and why an unparsable verdict is a `reject`.

### 5. Session relay (`session_relay.py`)

`BudgetMeter` counts prompt+completion tokens from every `Reply.usage`. When `used/limit >= 0.70`
(or a phase checkpoint lands), `SessionRelay.hand_over()`:

1. writes the plan and the closed phase into `.nexus/RELAY_STATE.json` through `nexus.hive.relay`;
2. generates `.nexus/NEXT_SESSION_PROMPT.md` — git facts, closed phases with their exit codes, what is
   pending, the next commands;
3. archives `session_01.json` to `sessions/archive/` and opens `session_02` with the prompt as its
   first user message;
4. returns control to the loop, which keeps executing the queue.

A budget nobody measured is `unmeasured`, not `0 %`. That is `nexus.hive.relay.budget()`'s rule and
we do not soften it.

## Determinism

`python -m nexus_harness selftest` must pass with the network unplugged. Every suite injects
`ScriptedProvider` (a list of replies, consumed in order), a temporary project root, and a fake clock.
The one suite that touches the real world is the adversarial audit, and it says so in its own output
(`skipped: no local model` is a result, not a pass).
