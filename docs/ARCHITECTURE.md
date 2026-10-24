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
| `tools.py` | What tools exist, what are their JSON schemas, how are they dispatched? | 150 |
| `toolbox/shell.py` | Run a command with a timeout and a clean capture. | 100 |
| `toolbox/files.py` | Read with line numbers, search with a bound, list. | 140 |
| `toolbox/edit.py` | Apply a patch deterministically; refuse ambiguity; enforce the line law. | 170 |
| `toolbox/web.py` | Fetch a page as text without a browser or an API key. | 130 |
| `context_router.py` | Which specialists does this turn touch, and what text travels with it? | 140 |
| `gate.py` | Is the tree actually green: lint, tests, line law. | 170 |
| `judge.py` | Does the change answer the goal? Fail-closed when unparsable. | 130 |
| `triad_loop.py` | One turn: plan, act, verify, repair, close. | 300 |
| `events.py` | How does the cockpit watch a turn without a websocket? | 90 |
| `session_store.py` | What is on disk for a session, and how is it archived? | 130 |
| `session_relay.py` | When does this session hand over, and what does the next one inherit? | 250 |
| `bridge.py` | How does a `/task` from a phone become a run? | 150 |
| `ui.py` | The local server: routes, JSON API, one page. | 260 |
| `ui_html.py` / `ui_css.py` / `ui_js.py` | The cockpit itself, split so no file owns two languages. | 200 each |
| `cli.py` | The second client: `run`, `serve`, `selftest`, `lint`, `models`. | 230 |

## The four contracts

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

### 2. Tools (`tools.py`)

A tool is `(name, description, JSON schema, callable(args, root) -> Observation)`. The registry
returns the OpenAI-shaped schema list, so the same tool dict serves all three transports.

`Observation` carries `ok`, `text`, `meta`. Failures are observations with `ok=False`, never
exceptions escaping the loop: a model that cannot see the error cannot fix it.

### 3. Gate (`gate.py`)

Exit `0` green, `10` red — the protocol's number, so a red gate is not a new vocabulary.

Checks, in order and all of them cheap: `rules_lint.lint_repo(root)` (R0–R3, 0 findings), the project's
declared test command (`test_command` in config, else `None` → reported as *not configured*, never as
green), and the line law on files the turn touched.

`Judge` is only consulted when the gate is green. A judge that approves broken code is worse than no
judge, which is why it never runs first and why an unparsable verdict is a `reject`.

### 4. Session relay (`session_relay.py`)

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
