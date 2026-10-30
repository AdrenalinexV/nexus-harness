"""Deterministic suites: no network, no key, no clock, no LM Studio required.

Each module exposes `run() -> list[str]`; an empty list is a pass. A suite whose capability this
machine simply does not have raises `Skip(reason)` instead: it is printed as SKIP with the reason and
counted apart from failures, because a check that could not run is not a check that passed -- and a
silent skip is a lie the same way a false green is.
"""
import importlib
import time


class Skip(Exception):
    """Raised by a suite that cannot run on this machine (missing optional engine, repo-only script)."""


def require_protocol(module):
    """Import a governor module, or declare the suite SKIP.

    Some contracts are the governor's, not this package's: the hive queue, the relay state, the auto-spec
    generator. When `NEXUS_PROTOCOL` is not on the machine those suites cannot measure anything, and the
    honest answer is a SKIP naming the module and the variable that would fix it -- never a red that
    reads like a bug in the harness.
    """
    try:
        return importlib.import_module(module)
    except Exception as exc:  # noqa: BLE001 -- any import failure means "not this machine"
        raise Skip("necesita el gobernador (%s): %s: %s -- apunta NEXUS_PROTOCOL a NexusProtocol"
                   % (module, type(exc).__name__, exc))


SUITES = ("providers", "retry", "repair", "tools", "linelaw", "layers", "edit_v4a", "shell_session", "shell_policy", "checkpoint", "subagents", "attachments",
          "onboarding", "mcp_client", "sidecar", "nightshift", "context", "triad_loop", "session_relay", "relay_state", "savings", "skills", "worktree", "deploy", "judge_repair", "compaction", "chat",
          "memory", "ui", "bridge", "budget", "charts", "activity", "projects", "autonomy", "ux",
          "learning", "oracle", "tokenizer", "spec", "plan_graph", "portfolio", "eval", "daemon", "notify", "browser", "recall", "ui_contract", "themes", "packaged_skills",
          "context_window", "triad_presets", "triad_balance", "consult", "empty_states", "fonts", "repo_scripts", "doc_truth", "protocol_pointer", "hooks",
          "stream", "sandbox", "lsp")


def run(names=None, stream=None):
    """Run the suites; returns the number of failures. Raises nothing a caller must catch."""
    out = stream or (lambda text: print(text))
    failures_total, failed_suites, skipped = 0, [], []
    for name in names or SUITES:
        started = time.time()
        try:
            module = importlib.import_module("nexus_harness.selftests.test_%s" % name)
            problems = list(module.run())
            status = "OK" if not problems else "FAIL"
        except Skip as exc:
            problems, status = [str(exc)], "SKIP"
            skipped.append(name)
        except Exception as exc:  # a suite that cannot even import is a failure, not a skip
            problems = ["crashed before asserting: %s: %s" % (type(exc).__name__, exc)]
            status = "FAIL"
        elapsed = time.time() - started
        out("%-16s %-4s %5.2fs" % (name, status, elapsed))
        for problem in problems:
            out("    - %s" % problem)
        if status == "FAIL":
            failures_total += len(problems)
            failed_suites.append(name)
    out("suites=%d failures=%d skipped=%d%s" % (len(names or SUITES), failures_total, len(skipped),
                                                "" if not failed_suites else " failing=%s"
                                                % ",".join(failed_suites)))
    return failures_total
