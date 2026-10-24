# Nexus-Harness

An autonomous engineering harness in pure Python, where the Nexus Protocol is not a hook bolted on
from outside but the turn loop itself: skills routing runs before every model call, the deterministic
lint is the gate, and a session that fills its budget hands itself over to a clean one without asking.

```
python -m nexus_harness run "make the login endpoint reject empty passwords"
python -m nexus_harness serve            # cockpit on http://127.0.0.1:8765
python -m nexus_harness selftest         # deterministic suites, no network
python tools/lint_harness.py             # the line law (0 findings)
```

Design and module map: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
What was learned from Hermes / Aider / OpenCode: [docs/FORENSICS.md](docs/FORENSICS.md).

Requirements: Python 3.11+ and `C:\Proyectos\NexusProtocol` on disk (override with `NEXUS_PROTOCOL`).
No third-party packages.
