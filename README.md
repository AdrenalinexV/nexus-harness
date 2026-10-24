# Nexus-Harness

An autonomous engineering harness in pure Python, where the Nexus Protocol is not a hook bolted on
from outside but the turn loop itself: skills routing runs before every model call, the deterministic
lint is the gate, and a session that fills its budget hands itself over to a clean one without asking.

```
python -m nexus_harness run "make the login endpoint reject empty passwords" --project C:/Proyectos/x
python -m nexus_harness serve            # cockpit on http://127.0.0.1:8765
python -m nexus_harness selftest         # 7 deterministic suites, no network
python -m nexus_harness models           # what LM Studio / Ollama actually offer
python -m nexus_harness gate --project .  # lint + line law + tests, exit 0/10/20
python -m nexus_harness bridge --tick     # run one /task queued from the phone
python tools/verify.py                    # lint + selftest, one exit code
python tools/adversary_audit.py           # kat-coder reviews the modules, read-only
```

`Nexus-Harness.bat` is the desktop launcher: no arguments starts the cockpit and opens it; arguments
go straight to the CLI (`Nexus-Harness.bat run "..."`).

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

Requirements: Python 3.11+ and `C:\Proyectos\NexusProtocol` on disk (override with `NEXUS_PROTOCOL`).
No third-party packages.
