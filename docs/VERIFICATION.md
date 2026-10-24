# Verification log — what was actually run

A claim without a command is a promise. This file records the commands and the exit codes observed on
this machine, as they were observed. It is updated by running `python tools/verify.py`, not by editing
the numbers.

## The one command

```
$ python tools/verify.py
lint      exit 0   files=40 findings=0 max_lines=400
selftest  exit 0   suites=7 failures=0
verify: GREEN
```

## The suites, individually

```
$ python -m nexus_harness selftest
providers        OK
tools            OK
context_router   OK
triad_loop       OK
session_relay    OK
ui               OK
bridge           OK
suites=7 failures=0
```

What each one actually proves:

| Suite | The property, not the code path |
|---|---|
| `providers` | Spec parsing refuses unknown vendors; the three parsers keep `reasoning_content`, native `thinking`, and Anthropic tool blocks; a cloud role with no key is `not ready` with a reason. |
| `tools` | Paths outside the root are refused; 401 lines is refused at the tool; two candidate matches is an error with the line numbers; a patch that would break 400 lines does not land; CRLF survives both patch rungs without a doubled `\r`. |
| `context_router` | Level 1 always travels; a test file calls `nexus-tdd` first; two identical calls agree; an unrelated file wakes nobody. |
| `triad_loop` | A plausible sentence goes red, the loop repairs without a human, the second attempt is green and the judge approves; a worker that never repairs ends at 10; a judge rejection spends one repair; a same-size fix in the same second is still seen (the stale-bytecode trap). |
| `session_relay` | Phase 1 crosses 70 %, `session_01` is archived, `NEXT_SESSION_PROMPT.md` is generated, `session_02` continues and all three phases close with exit 0. |
| `ui` | A real HTTP server on an ephemeral port serves the page, `/api/state` carries no secrets, a run is accepted, finishes and is published, a bad role is 400, an unknown route is 404. |
| `bridge` | A queued `/task` is claimed once, run, and closed with the exit the runner produced; the cap holds; an unknown project stays queued; a crashing runner closes red. |

## From the cockpit, through a real browser

The page was opened in a browser, the project `NexusSandbox` selected, a goal and a test command typed,
and **Ejecutar** clicked. The DOM afterwards, read back from the live page:

```
status : verde
meta   : exit 0 · 3 pasos · 0 reparaciones · NexusSandbox
gate   : exit 0  lint 0  line_law 0  tests 0
judge  : approve — "El cambio de a - b a a + b en calc.py y el test con exit code 0 demuestran ..."
skills : nexus-verification, nexus-clean-code, nexus-appsec, nexus-architecture
rows   : 25 events in the feed
```

And the project afterwards: `calc.py` contains `return a + b`, `python -c "import calc; assert
calc.add(2,3)==5"` exits 0, and `session_03.json` is stored as `"status": "closed", "exit": 0`.

Note the shape of the transcript: it lives in the server process (the page survives a tab close, a
server restart starts a new one). That is a deliberate size/complexity decision, not persistence.

## Against the real models

Director `qwen3.8-27b`, worker `kat-coder-v2.5-dev-35b-a3b`, judge `qwen3.8-27b`, all through LM Studio
on `127.0.0.1:1234`:

```
$ python -m nexus_harness run "arregla la funcion add de calc.py para que SUME ..." \
    --project C:/Proyectos/_harness_sandbox \
    --test-command 'python -c "import calc; assert calc.add(2,3)==5"'
gate      : exit 0 · lint=True, line_law=True, tests=True
judge     : approve El cambio de `a - b` por `a + b` en `calc.py` y el test con exit 0 demuestran ...
steps     : 3 · repairs: 0 · sessions: session_01
touched   : calc.py, test_calc.py
verdict   : GREEN
```

The file was read back afterwards: `return a + b`, and the test command exits 0 when run by hand.

Reachability of the local fleet, as the harness sees it:

```
$ python -m nexus_harness models
director  lmstudio:qwen3.8-27b-...        ready
worker    lmstudio:kat-coder-v2.5-...     ready
judge     lmstudio:qwen3.8-27b-...        ready
lmstudio: 22 models      ollama: 24 models
```

## The cockpit, over real sockets

```
$ python -m nexus_harness serve --port 8765 &
$ curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8765/          -> 200
$ curl -s http://127.0.0.1:8765/api/health                               -> {"ok": true, "seq": 0}
$ curl -s http://127.0.0.1:8765/api/state | head -c 120                  -> {"running": false, "config": {...}}
```

## What is **not** verified here

- **Cloud providers** (`openai`, `deepseek`, `openrouter`, `anthropic`): no key for them is in
  `~/.nexus/secrets.json` on this machine, so only their construction, `ready` reporting and parsers
  are tested. A live cloud call is **could not verify**.
- **The protocol's remote listener** (Telegram/Discord polling): its queue contract is tested
  (`bridge`), its network side is the protocol's own suite, not this one.
- **A full adversarial audit** is reported by `python tools/adversary_audit.py`, whose result belongs
  to the run that produced it and is not a permanent property of the tree.
