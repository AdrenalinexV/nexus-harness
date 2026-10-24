# Adversarial audit — findings and what was done with each

Reviewer: `kat-coder-v2.5-dev-35b-a3b` (LM Studio, `127.0.0.1:1234`), through
`python tools/adversary_audit.py <modules>`. The reviewer is told to return only defects it can point
at, in JSON, and to return `[]` when a module is clean. Its answers arrive in prose more often than in
JSON, so the tool salvages the objects it can and saves the raw text; the dispositions below were
decided by reading the code, not by trusting the reviewer.

The audit is a **review**, not a gate: it needs a model, so it can say "could not verify" and it never
blocks a commit by itself. Two of its findings were real defects with production consequences, and both
now have a deterministic regression test.

## Accepted — fixed

| Finding | Where | What was actually wrong | Test that now holds it |
|---|---|---|---|
| Auto-relay on a reply that asks for a tool | `triad_loop._work` | The handover replaced the conversation, and then the code appended the *old* reply's `tool` results to the new session. An orphan `tool` message (no `tool_calls` in front) is rejected by every OpenAI-shaped server, so the next session would have started with a 400. | `session_relay::test_relay_on_a_tool_call_leaves_no_orphan` asserts the post-relay call has exactly `["system","user"]`. |
| Unbounded relay prompt | `session_relay.hand_over` | `build_prompt` can grow with the plan and the touched files; a prompt larger than the next session's window would be silently truncated *by the provider*, mid-instruction. | Cap at `MAX_PROMPT_CHARS` with a declared cut pointing at `RELAY_STATE.json`. |
| Lost relay warning | `session_relay._protocol_prompt` | A protocol failure fell back to the generic prompt and only emitted on the bus; with no bus the operator never learned the protocol relay was broken. | `last_warning` is recorded on the relay and exposed in `status()`. |
| Archived session could be overwritten | `SessionStore.archive` | `next_id()` scanned only live sessions, so after an archive the next handover could reuse the same number and overwrite the transcript. | `next_id()` scans live **and** archived; `archive()` refuses to overwrite (timestamp suffix). |
| Fragile None-handling in `state()` | `ui.run_payload`, `ui._relay_status` | `_latest(...)["payload"]` was called conditionally and twice; correct only because the bus never deletes. | Locals with `.get()` defaults. |
| Double `\r` when patching CRLF with the normalised rung | `toolbox/edit` | Converting the inserted text to CRLF *and* converting the rebuilt file produced `\r\r\n` on every patched line. | `tools::test_crlf` asserts no `\r\r\n` and the CRLF style survives both rungs. |

## Accepted — fixed, found by self-review before the audit returned

| Finding | What was actually wrong |
|---|---|
| Stale bytecode made a fixed file look broken | `a - b` → `a + b` keeps the file's size, and Python's cache check is `(mtime_seconds, size)`. A patch landing in the same second as the previous test run let the tests import the **old** module, so the gate stayed red on correct code and the loop burned its repairs on a phantom. The gate now runs tests with a fresh `PYTHONPYCACHEPREFIX` per run. `triad_loop::test_gate_sees_a_same_size_fix` forces the exact trap with `os.utime`. |
| `Path.read_text` rewrote CRLF in memory | The patcher never saw the real bytes, so "keep the file's newline style" was a promise it could not keep. `toolbox/files.read_text` now opens with `newline=""`. |
| Sessions never closed | A finished run left its session file saying `active`, so the cockpit showed a live session for a run that was over. `SessionRelay.finish(exit)` closes it with the exit code. |

## Rejected — with the reason

| Finding | Why it is not a defect |
|---|---|
| "Race in `Cockpit.start`: `_running` is set False before `thread.start()`" | The described code is not this code. `_running` is set `True` inside the lock and only reset on the project-not-found path (which returns) or in the thread's `finally`. The reviewer reconstructed a different function. *(The adjacent real risk — `thread.start()` raising and leaving the cap held — was fixed anyway.)* |
| "`BudgetMeter` and `SessionRelay` keep two `turns` counters" | `SessionRelay.observe` copies `meter.turns` into the session file; it does not increment anything. One counter, one source. |
| "`getattr(config, 'budget_limit')` silently ignores a dict config" | The contract is a `HarnessConfig` (typed, constructed by `config.load`). Accepting a dict silently would be the defect; there is no code path that passes one. |
| "`next_id` has a race under threads" | The harness is single-writer by design: the cockpit holds one run at a time, the bridge claims one item per tick, and the CLI is one process. A lock would protect against a concurrency model the project does not have. |
| "`SessionStore.archive` races under threads" | Same reason. The overwrite risk that *was* real (id reuse) is fixed. |

## What the audit cannot tell you

It reads one module at a time with no repository context, so it cannot see cross-module contracts (the
reason its `start()` finding was wrong) and it does not run anything. That is why the suites, not the
review, are the gate.
