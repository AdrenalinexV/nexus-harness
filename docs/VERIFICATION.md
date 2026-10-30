# Verification log — what was actually run

A claim without a command is a promise. This file records the commands and the exit codes observed on
this machine, as they were observed. It is regenerated **deliberately**, with
`python tools/verify.py --write-doc` — never by editing the numbers, and not as a side effect of a plain
`verify` run: a gate that rewrites the document it grades leaves the tree dirty and lets a stale figure
ride along in an unrelated commit. **Qué corrida es esta, exactamente.** La de abajo se hizo CON el gobernador en disco: `NEXUS_PROTOCOL=C:\Proyectos\NexusProtocol python tools/verify.py --write-doc`. El CI no lo tiene y publica otra cosa, que es la correcta para el CI: `linter=builtin(R0,R1,R2)`, `skipped=3` y ninguna suite roja. Por eso `verify.py --frozen` compara el binario contra ESTA corrida y no contra una cifra suelta.

## The one command

```
$ python tools/verify.py --write-doc
lint      exit 0   files=234 findings=0 max_lines=400 ignored_runtime=0 linter=protocol(R0,R1,R2,R3)
selftest  exit 0   suites=64 failures=0 skipped=0
verify: GREEN
```

## The suites, individually

```
providers        OK    0.09s
retry            OK    0.00s
repair           OK    0.45s
tools            OK    0.44s
linelaw          OK    0.04s
layers           OK    0.20s
edit_v4a         OK    0.06s
shell_session    OK    1.59s
shell_policy     OK    0.25s
checkpoint       OK    0.27s
subagents        OK    0.01s
warning: The `fitz` API is deprecated and will be removed in future. Use `import pymupdf` instead.
attachments      OK    0.16s
onboarding       OK    0.13s
mcp_client       OK    0.44s
sidecar          OK    5.08s
estado listo: 2 criterios (2 pendientes)
a -> exit 0 (VERDE)
findings=0
b -> exit 10 (ROJO)
b marcado blocked
criterio desconocido: zzz
cerrojo ocupado: el turno de noche ya esta en marcha: pid 23416 desde 2026-10-30T22:48:05+00:00 (suite)
no se toca nada. Si esa sesion ya no corre, el cerrojo se hereda solo; para forzarlo a mano, borra C:\Users\Vexus\AppData\Local\Temp\nightshift-adife1lm\.nexus\harness\nightshift.lock
TOCA: b — falla
  prueba: python -c "raise SystemExit(10)"
  estado: blocked (intentos 1)
a -> exit 0 (VERDE)
findings=0
nightshift       OK    0.49s
context          OK    0.15s
triad_loop       OK    2.82s
session_relay    OK    1.48s
relay_state      OK    0.32s
savings          OK    0.71s
skills           OK    0.22s
worktree         OK    4.32s
deploy           OK    0.03s
judge_repair     OK    0.06s
compaction       OK    0.26s
chat             OK    0.86s
memory           OK    0.64s
ui               OK    1.04s
bridge           OK    0.06s
budget           OK    0.44s
charts           OK    0.00s
activity         OK    0.00s
projects         OK    0.94s
autonomy         OK    1.05s
ux               OK    2.21s
learning         OK    0.04s
oracle           OK    0.39s
tokenizer        OK    0.02s
spec             OK    0.46s
plan_graph       OK    0.00s
portfolio        OK    0.20s
eval             OK    9.11s
daemon           OK    0.44s
notify           OK    0.00s
browser          OK    6.24s
recall           OK    0.26s
ui_contract      OK    3.96s
themes           OK    0.01s
packaged_skills  OK    0.00s
context_window   OK    0.47s
triad_presets    OK    0.04s
triad_balance    OK    0.05s
consult          OK    0.17s
empty_states     OK    0.02s
fonts            OK    0.00s
repo_scripts     OK    0.01s
doc_truth        OK    1.18s
protocol_pointer OK    0.00s
hooks            OK    8.04s
stream           OK    1.93s
sandbox          OK    0.13s
lsp              OK    0.44s
kanvas           OK    0.54s
suites=64 failures=0 skipped=0
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
| `edit_v4a` | A block re-typed with two spaces where the file has four still lands; the same edit twice is an idempotent success with the bytes untouched; a patch that would leave a `.py` unparseable is refused and the file keeps its bytes; a V4A patch with Update + Add + Delete applies whole, and one whose second operation is impossible rolls the first one back. |
| `shell_session` | `cd sub` in one call is honoured by the next; `export K=V` reaches the following command; 40 000 chars of output come back clipped head+tail with the full log in `.nexus/harness/logs/`; a background process is spawned, polled alive, fed on stdin and killed. |
| `subagents` | Two children meet at a `threading.Barrier` (real overlap, not a stopwatch); turns stop at `subagent_steps`; a pre-set stop event means zero model calls; a child cannot delegate; a read-only child gets no editing tools and no `delegate_task`. |

## From the cockpit, through a real browser

The page was opened in a browser, the project `NexusSandbox` selected, a goal and a test command typed,
and **Ejecutar** clicked. The DOM afterwards, read back from the live page:

```
status : verde
meta   : exit 0 · 5 pasos · 0 reparaciones · NexusSandbox
gate   : exit 0  lint OK  line_law OK  tests OK
judge  : approve
skills : nexus-verification, nexus-clean-code, nexus-appsec, nexus-architecture (≈699 tokens)
budget : 11562/60000 tokens (19 %) · relevo a 70 %
feed   : OBRERO, TOOL, SKILLS, PRESUPUESTO, GATE, JUEZ — 25+ events
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

## The desktop app, installed

```
$ "Nexus Harness_0.1.0_x64-setup.exe" /S        -> exit 0, installed per-user
$ %LOCALAPPDATA%\Nexus Harness\nexus-harness-desktop.exe
   nexus-harness-desktop  (MainWindowTitle: "Nexus Harness")
   nexus-harness-engine   (child, no console window)
   TCP 127.0.0.1:55973 LISTENING               <- engine picked a free port
   GET /                       -> 200 (the app, not a splash)
   GET /api/state (no token)   -> 401          <- per-launch token enforced
```

The frozen engine was also exercised on its own:

```
$ dist/nexus-harness-engine.exe selftest
suites=9 failures=0
```

and a real chat turn through the frozen engine, from the UI, in `NexusSandbox`:

```
project : C:\Proyectos\NexusSandbox
reply   : "Un cambio está bien cuando un test (o comando) que antes fallaba ahora pasa..."
skills  : nexus-verification, nexus-clean-code
steps   : 1 · exit 0 · messages: user, assistant
```

That run found and fixed two real bugs the suites now cover: the cockpit re-targeted the conversation
to the default project on every state poll (throwing away the project the operator had chosen), and the
UI never refreshed the thread after a turn, so the answer only appeared if you clicked something else.

## v0.2.0 — the frozen engine, the installer and a live process

Everything below was run on this machine on 2026-10-24, in this order.

```
$ python tools/verify.py
lint      exit 0   files=55 findings=0 max_lines=400
selftest  exit 0   suites=12 failures=0
verify: GREEN

$ cd .build && pyinstaller --noconfirm --distpath ../dist --workpath pyi nexus-harness-engine.spec
Build complete! The results are available in: C:\Proyectos\Nexus-Harness\dist
$ dist/nexus-harness-engine.exe --version      -> nexus-harness 0.2.0
$ dist/nexus-harness-engine.exe selftest       -> suites=12 failures=0   (exit 0, frozen)

$ cd apps/desktop && npm run build
Finished 1 bundle: Nexus Harness_0.2.0_x64-setup.exe (11.43 MiB)
$ copy to dist/NexusHarness-Setup-0.2.0.exe    -> 11 981 628 bytes

$ "dist/NexusHarness-Setup-0.2.0.exe" /S /D=%LOCALAPPDATA%\NexusHarnessVerify   -> exit 0
  installed: engine\nexus-harness-engine.exe, nexus-harness-desktop.exe, uninstall.exe
  installed engine --version                   -> nexus-harness 0.2.0
  installed engine selftest                    -> suites=12 failures=0
  PE subsystem: nexus-harness-desktop.exe = GUI (2, no console); engine = console (3),
                hidden at spawn by CREATE_NO_WINDOW (apps/desktop/src-tauri/src/main.rs:90-91)
  GET /api/state (X-Nexus-Token)               -> version "0.2.0", 13 keys
  GET /api/state without the token             -> 401
  GET /?token=...                              -> page contains id="activity" (ACTIVIDAD panel)
  the isolated copy was uninstalled with uninstall.exe /S  -> exit 0
```

A later build (after the shutdown fix below) was installed the same way and proved graceful exit:

```
$ "dist/NexusHarness-Setup-0.2.0.exe" /S /D=%LOCALAPPDATA%\NexusHarnessVerify  -> exit 0
  installed engine --version    -> nexus-harness 0.2.0
  installed engine selftest     -> suites=12 failures=0
  POST /api/shutdown (token)    -> 200, the engine exits by itself in ~1.0 s, the port closes
  uninstall.exe /S              -> exit 0, directory removed with no locked file left behind
```

That last line is the fix for a real production defect found while installing: a PyInstaller one-file
build is two processes, so `Child::kill()` on the bootloader left the engine alive, holding its own
`.exe`. That is why the first install reported success and kept the old engine: three such orphans had
it open. The engine now exposes `POST /api/shutdown` (token-guarded) which closes the socket and calls
`os._exit(0)`, and the shell calls it on `WindowEvent::Destroyed` before falling back to
`taskkill /T /F`.

**One thing that did not happen, and why:** the install into the default per-user directory
(`%LOCALAPPDATA%\Nexus Harness`) could not replace its engine, because three
`nexus-harness-engine.exe` processes were running and holding the file open. The installer itself
returned 0 and updated `nexus-harness-desktop.exe`, but NSIS cannot overwrite a locked binary. The
verification above therefore used `/D=` into a throwaway directory, then removed it. Replacing the
default installation needs those processes closed first (or a reboot, which reschedules the copy).

## v0.3.0 — the product surface, the four NexusProtocol milestones, and one real turn

Measured on 2026-10-24, in this order. Everything below is an observed exit code or an observed value.

```
$ python tools/verify.py
lint      exit 0   files=65 findings=0 max_lines=400
selftest  exit 0   suites=16 failures=0
verify: GREEN

$ python -c "...rules_lint.lint_repo('C:/Proyectos/NexusProtocol')"
PROTOCOL files=215 findings=0

$ python nexus/cli.py doctor            -> exit 0, "everything a self-test can prove is green"
  (three new checks travel inside it: auto-spec, the SKILL.md editor, the bridge toggle)

$ .build/venv/Scripts/pyinstaller ... nexus-harness-engine.spec
$ dist/nexus-harness-engine.exe --version   -> nexus-harness 0.3.0
$ dist/nexus-harness-engine.exe selftest    -> suites=15 failures=0      (frozen, exit 0)

$ "dist/NexusHarness-Setup-0.3.0.exe" /S /D=%LOCALAPPDATA%\NexusHarnessVerify   -> exit 0
  installed engine --version                 -> nexus-harness 0.3.0
  installed engine selftest                  -> suites=16 failures=0
  GET /api/state                             -> version "0.3.0"
  GET /api/onboarding                        -> lmstudio ready (22 models), ollama ready (24),
                                                31 projects, keys: ["TYPESAFE_API_KEY"]
  GET /api/skills                            -> 12 SKILL.md files; ?name=nexus-appsec -> 28 lines
  GET /api/mcp                               -> nexus ready, 3 tools
  POST mcp__nexus__nexus_status              -> "governed projects: 31, last verdict: exit 0 ..."
  GET /api/bridge/daemon                     -> running False, queue 0
  POST /api/shutdown                         -> 200, the engine exits by itself in ~1 s
  uninstall.exe /S                           -> exit 0, the directory is removed with nothing locked
```

The orphan guarantee, measured with the frozen engine (a parent that declares itself, then dies):

```
parent declares NEXUS_HARNESS_PARENT=<its pid> and spawns the engine
  engine served while the parent lived      -> True
  parent killed
  engine left on its own                    -> True, in ~4.1 s
```

And the live turn, through a real engine process on `127.0.0.1`, against LM Studio (`kat-coder-35b-a3b`):

```
POST /api/chat  "Usa la herramienta write_file para crear notas.md en la raiz con una sola linea: hola"
  exit 0 · steps 2 · touched ["notas.md"]
  GATE  : exit 0 — lint OK, line_law OK, tests OK        (the protocol's own linter ran)
  JUEZ  : approve — "El archivo notas.md fue creado ... y pasa todos los gates (lint, line_law)"
  SKILLS: nexus-verification, nexus-clean-code
  BUDGET: 5300/60000 tokens (8.8 %) · measured · relevo a 70 %
  notas.md on disk: "hola"
```

Two things worth recording because they were *refusals*, not successes:

* The first attempt used an 8B model that answered with the tool call **written as prose**. Nothing was
  touched, so the turn ended with no gate and no judge — which is exactly what the design says should
  happen (a turn that changed nothing has nothing to prove).
* The bridge toggle started the listener, watched it exit, and the log said why:
  `remote: no telegram token in the vault or the environment`. The panel reported `running: False`
  instead of claiming ON.

**Still blocked at the time of writing:** the install into the default per-user directory. Two running
`nexus-harness-engine.exe` (the 0.1.0 build, PIDs 14232 and 38524) hold their own `.exe` open, so NSIS
reports success and keeps the old binary. Closing those two processes (or rebooting) lets the same
installer do its job; the isolated `/D=` install above is the proof that the installer itself is sound.
The shell no longer creates such orphans: it asks `/api/shutdown` first and tree-kills as a fallback.

## What is **not** verified here

- **Cloud providers** (`openai`, `deepseek`, `openrouter`, `anthropic`): no key for them is in
  `~/.nexus/secrets.json` on this machine, so only their construction, `ready` reporting and parsers
  are tested. A live cloud call is **could not verify**.
- **The protocol's remote listener** (Telegram/Discord polling): its queue contract is tested
  (`bridge`), its network side is the protocol's own suite, not this one.
- **A full adversarial audit** is reported by `python tools/adversary_audit.py`, whose result belongs
  to the run that produced it and is not a permanent property of the tree.
