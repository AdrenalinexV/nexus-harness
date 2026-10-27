"""Deterministic suites: no network, no key, no clock, no LM Studio required.

Each module exposes `run() -> list[str]`; an empty list is a pass. `runner.run()` is what
`python -m nexus_harness selftest` calls, and it prints one line per suite plus the failures.
"""
import importlib
import time

SUITES = ("providers", "retry", "repair", "tools", "edit_v4a", "shell_session", "shell_policy", "checkpoint", "subagents", "attachments",
          "onboarding", "mcp_client", "sidecar", "nightshift", "context", "triad_loop", "session_relay", "relay_state", "savings", "skills", "worktree", "deploy", "judge_repair", "compaction", "chat",
          "memory", "ui", "bridge", "budget", "charts", "activity", "projects", "autonomy", "ux",
          "learning", "oracle", "tokenizer", "spec", "plan_graph")


def run(names=None, stream=None):
    """Run the suites; returns the number of failures. Raises nothing a caller must catch."""
    out = stream or (lambda text: print(text))
    failures_total, failed_suites = 0, []
    for name in names or SUITES:
        started = time.time()
        try:
            module = importlib.import_module("nexus_harness.selftests.test_%s" % name)
            problems = list(module.run())
        except Exception as exc:  # a suite that cannot even import is a failure, not a skip
            problems = ["crashed before asserting: %s: %s" % (type(exc).__name__, exc)]
        elapsed = time.time() - started
        out("%-16s %-4s %5.2fs" % (name, "OK" if not problems else "FAIL", elapsed))
        for problem in problems:
            out("    - %s" % problem)
        failures_total += len(problems)
        if problems:
            failed_suites.append(name)
    out("suites=%d failures=%d%s" % (len(names or SUITES), failures_total,
                                     "" if not failed_suites else " failing=%s"
                                     % ",".join(failed_suites)))
    return failures_total
