# Nexus-Harness

An autonomous engineering harness in pure Python, where the Nexus Protocol is not a hook bolted on
from outside but the turn loop itself: skills routing runs before every model call, the deterministic
lint is the gate, and a session that fills its budget hands itself over to a clean one without asking.

**It ships as a desktop app**: `NexusHarness-Setup-1.0.0.exe` installs a native window with the engine
frozen inside (no Python on the target machine). See [docs/DESKTOP.md](docs/DESKTOP.md).

```
python -m nexus_harness run "make the login endpoint reject empty passwords" --project C:/Proyectos/x
python -m nexus_harness serve            # cockpit on http://127.0.0.1:8765
python -m nexus_harness selftest         # 28 deterministic suites, no network
python -m nexus_harness models           # what LM Studio / Ollama actually offer
python -m nexus_harness gate --project .  # lint + line law + tests, exit 0/10/20
python -m nexus_harness bridge --tick     # run one /task queued from the phone
python tools/verify.py                    # lint + selftest, one exit code
python tools/adversary_audit.py           # kat-coder reviews the modules, read-only
```

`Nexus-Harness.bat` is the desktop launcher: no arguments starts the cockpit and opens it; arguments
go straight to the CLI (`Nexus-Harness.bat run "..."`).

## What 0.2.0 adds (the industrial core)

Reverse-engineered from the harness this project runs on, then rebuilt to one rule: nothing is
"approximately written". Every edit ends in `file_ops.atomic_write`, which means the same three doors
for all of them -- the 400-line law, a parser (`ast` / `json` / `tomllib` / YAML), and a SHA-256 read-back.

- **`patch_replace`** walks eight matching rungs (exact -> trimmed -> whitespace -> indentation ->
  unicode -> similarity >= 0.90) and refuses with the closest existing block instead of guessing.
  A re-sent edit is an idempotent success, never a second rewrite.
- **`apply_patch`** takes V4A envelopes (`*** Begin Patch`, Update/Add/Delete/Move File, `@@ hint @@`):
  validated against an in-memory overlay first, applied with rollback, atomic across files.
- **`shell`** remembers the working directory between calls and exports `export K=V` into the next
  one; long runs go to `background` and are driven with `process_manage(list|poll|write|kill)`, with
  `CREATE_NO_WINDOW` on every Windows spawn and `taskkill /T /F` to kill the tree.
- **Output** is clipped head+tail (12 000 chars) and the full log lands in `.nexus/harness/logs/`.
- **`search_files`** uses ripgrep when present, a Python walk otherwise; `.nexus/skills-dormant` and
  build trees are always excluded; `read_file` pages with line numbers and refuses binaries by magic.
- **`delegate_task`** runs children in parallel (`ThreadPoolExecutor`), each with a closed history,
  a bounded turn budget, read-only tools unless `allow_edit`, optional `git worktree` isolation, and
  the same stop event as the Detener button.
- **Read-only tool calls in one turn run together**; edits and shells stay sequential, and every
  child's touched files flow into the same gate before the turn can claim green.

## What 0.3.0 adds (product surface + the four milestones)

- **Onboarding that measures the machine.** The gear button probes LM Studio (`:1234`) and Ollama
  (`:11434`), lists the models that are *actually downloaded*, and assigns them to Director / Obrero /
  Juez in one click; cloud keys go into a DPAPI-sealed store that can report which keys exist and
  never reads a value back; picking a project can synthesise its governance through NexusProtocol's
  Auto-Spec generator.
- **Attachments and vision.** Paste (`Ctrl+V`), drag or `+ Adjuntar`: images are sniffed by magic
  bytes, resized inside 1568 px and re-encoded (Pillow ships inside the engine), documents are
  extracted (text; PDFs when PyMuPDF is present, refused with a reason when not), and every turn
  carries chips with a small preview -- never the full base64, never in the transcript.
- **Native MCP client.** Servers from `~/.nexus/mcp.json` (with the protocol's own
  `nexus_status` / `nexus_lint` / `nexus_relay` as the default) are spawned hidden, handshaken over
  JSON-RPC, and their tools appear to the model as `mcp__<server>__<tool>`. The sidebar shows what is
  connected and how many tools it contributes.
- **System tray and a clean exit.** The X hides the window into the tray (Abrir / Estado del motor /
  Salir completamente); leaving asks the engine to exit over `/api/shutdown` and falls back to
  `taskkill /T /F`. The engine also watches the shell's own PID (`NEXUS_HARNESS_PARENT`), so even a
  crash or a Task Manager kill cannot leave one behind holding its `.exe` -- which is what silently
  blocked the next install.

## The cockpit

One page, six endpoints, no framework: `/api/state`, `/api/events?since=N`, `/api/models`,
`/api/run`, `/api/roles`, `/api/bridge`. It shows the director's plan, every tool call, the skills
injected into that turn, the budget bar with its 70 % relay mark, the gate's checks and the judge's
verdict — live, by polling a sequence number. Closing the tab does not lose the run: the transcript
lives in the server's bus.

## Roles and models

`~/.nexus/harness.json` (all optional) overrides the defaults:

```json
{"roles": {"director": "lmstudio:qwen3.8-27b-heretic-abliterated-uncensored",
           "worker":   "lmstudio:kat-coder-v2.5-dev-35b-a3b-abliterated-uncensored-philadelphia-class",
           "judge":    "lmstudio:qwen3.8-27b-heretic-abliterated-uncensored"},
 "budget_limit": 60000, "relay_threshold": 0.70, "test_command": "python -m pytest -q"}
```

A spec is `provider:model`, with `lmstudio`, `ollama`, `openai`, `deepseek`, `openrouter` and
`anthropic` known out of the box. Keys are read from `~/.nexus/secrets.json` or the environment —
never from this repository. The judge is deliberately a different model from the worker.

Design and module map: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
What was learned from Hermes / Aider / OpenCode: [docs/FORENSICS.md](docs/FORENSICS.md).
What was actually run, with exit codes: [docs/VERIFICATION.md](docs/VERIFICATION.md).
What the adversarial reviewer found and what was rejected: [docs/AUDIT.md](docs/AUDIT.md).

Requirements: Python 3.11+ and `C:\Proyectos\NexusProtocol` on disk (override with `NEXUS_PROTOCOL`).
No third-party packages.
