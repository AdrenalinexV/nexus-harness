# Changelog

All notable changes to Nexus-Harness, newest first. Versions before 1.0.0 were internal
milestones of the same tree (there are no separate tags for them).

## 1.1.0 — 2026-10-28

Autonomy that asks instead of inventing a decision.

- **`consult`**: a question is written to an append-only journal, sent to the operator's channels,
  and waited on with a deadline; on silence the **default the question itself declares** is applied.
  Telegram is polled for real (`getUpdates` with a persisted offset), Discord is polled when there is
  a bot token, and a webhook is declared *write-only* instead of pretending it can hear.
- **Three exits with different effects**: `seguir` (another cycle, red reason in front), `revertir`
  (checkpoint restores the previous bytes) and `parar` (the queue moves on, the default).
- **Detener interrupts the wait**, and the question stays open in the cockpit.
- Settings gained *Autonomía & Preguntas* and a dedicated *VPS 24/7* page.
- LICENSE (MIT) added; README figures brought in line with the measured suite.

## 1.0.0 — 2026-10-27

First version with the gate loop closed end to end.

- **The judge reads its verdict even when the model dirties the JSON**: balanced-brace scanning,
  trailing commas and curly quotes normalised; one bounded retry with a stricter instruction.
- Frozen desktop engine measured against the **source** suite instead of a number written by hand
  (`verify.py --frozen`), so a stale binary can no longer pass on a smaller suite count.

## 0.5.0 — 2026-10-25

- Session handover measured in tokens, with the ramp before the cliff: old tool outputs collapse to a
  receipt `(tool, path, range, chars, sha256)` while the last steps stay verbatim.

## 0.4.0 — 2026-10-25

- **Native desktop app by default** (`NexusHarness-Setup-*.exe`, engine frozen inside, no Python on
  the target machine) and the seven settings screens rebuilt.

## 0.3.0 — 2026-10-24

Product surface and the four milestones.

- **Onboarding that measures the machine**: probes LM Studio and Ollama, lists what is actually
  downloaded, assigns Director / Obrero / Juez in one click; cloud keys go into a sealed store that
  can report which keys exist and never reads a value back.
- **Attachments and vision**: images sniffed by magic bytes, resized inside 1568 px, re-encoded;
  documents extracted (PDFs when PyMuPDF is present, refused with a reason when not).
- **Native MCP client** (stdio), tray icon with a clean close.

## 0.2.0 — 2026-10-24

The industrial core, rebuilt to one rule: nothing is "approximately written".

- **`file_ops.atomic_write`**: every edit passes the same three doors — the 400-line law, a parser
  (`ast` / `json` / `tomllib` / YAML) and a SHA-256 read-back.
- **`patch_replace`** walks eight matching rungs and refuses with the closest existing block instead
  of guessing; a re-sent edit is an idempotent success.
- **`apply_patch`** (V4A envelopes) validated on an in-memory overlay, applied with rollback.
- **`shell`** keeps its working directory, exports declared variables, sends long runs to the
  background, and kills the whole process tree (`taskkill /T /F` on Windows).
- **`delegate_task`** runs children in parallel with a bounded turn budget, read-only tools unless
  `allow_edit`, optional `git worktree` isolation, and the same stop event as the Detener button.

## 0.1.0 — 2026-10-24

The turn loop itself: skills routing before every model call, the deterministic gate
(`0` green / `10` red / `20` could-not-verify) running **before** a judge that is not the worker,
a per-turn ledger, and the cockpit.
