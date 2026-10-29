# Nexus-Harness — project rules

This repository is governed by Nexus Protocol from its first commit. The rules below are the ones a
machine checks (`tools/lint_harness.py`: the governor's `rules_lint.py` when it is importable, else the
mechanical law shipped in `nexus_harness/linelaw.py`, R0-R2 — the summary line always says which one
answered); the rest are the ones a reviewer checks.

## Laws

- No file over 400 lines. A module that reaches the limit is split by owner, not by length.
- No dead code, no "just in case" parameter, no commented-out block. Git keeps what is removed.
- A claim is only a claim until a command with its exit code backs it. `selftest` is that command.
- The dependency budget is the standard library. Anything else is a decision written here.
- `%LOCALAPPDATA%\hermes\hermes-agent` is read-only for this project: ideas are adopted, files are
  never touched.

## APPROVED DEPENDENCIES

- nexus -- the governance engine this harness is built on (`C:\Proyectos\NexusProtocol`): skills
  routing, deterministic lint, relay state. Imported, never vendored, so there is one definition of
  each rule on this machine.

## Layout contract

- `nexus_harness/` — the harness. `providers.py` and `tools.py` are the two deep interfaces: every
  model and every action enters through them.
- `nexus_harness/selftests/` — deterministic tests. No network, no key, no clock: a fake transport
  stands in for the model, so a green run means the logic is right, not that the network was up.
- `tools/` — repository tooling (lint wrapper, verification script).
- `nexus/` — one file, and it is a pointer, not code: it extends the package path to NexusProtocol so
  `python -m nexus.harness.adapters` resolves from this root. `nexus/harness/` holds the translators
  that put the gate inside other harnesses (Aider first), and vendoring them here would leave two
  definitions of every rule on this machine.

## Verification

```
python tools/lint_harness.py          # 0 findings, exit 0
python -m nexus_harness selftest      # every suite, exit 0
python -m nexus_harness run "<goal>"  # the triad: director, worker, gate
```
