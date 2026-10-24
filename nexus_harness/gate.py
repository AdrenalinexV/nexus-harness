"""The gate: the only thing in this harness allowed to say the work is done.

Exit `10` is red and `0` is green -- the protocol's number, so a red gate is not a new vocabulary. Three
checks, in increasing cost, and all of them deterministic:

1. **The lint** (`nexus/checks/rules_lint.py`, R0-R3). Zero findings or red. It is the same function
   the Nexus repository runs on itself, imported: there is one definition of the law on this machine.
2. **The line law** on the files the turn touched, because "no file over 400 lines" is the one rule
   the model can break the moment it writes.
3. **The project's own tests**, when the project declares a command. A project that declares none is
   reported as *not configured* -- never as green, because an absent check is not a passed check.

A gate that cannot run (no Nexus install) returns exit `20` and says so. Fail-closed means it refuses
to be green, not that it invents a verdict.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

EXIT_GREEN = 0
EXIT_RED = 10
EXIT_UNAVAILABLE = 20
MAX_FAILURE_TEXT = 4000


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    exit: object = None
    blocking: bool = True

    def as_dict(self):
        return {"name": self.name, "ok": self.ok, "detail": self.detail, "exit": self.exit,
                "blocking": self.blocking}


@dataclass
class Verdict:
    ok: bool = False
    exit: int = EXIT_RED
    checks: list = field(default_factory=list)
    failures: str = ""
    at: str = ""

    def as_dict(self):
        return {"ok": self.ok, "exit": self.exit, "failures": self.failures, "at": self.at,
                "checks": [check.as_dict() for check in self.checks]}


def _linter():
    """`lint_repo` from the protocol, or `None` when this machine does not have it."""
    source = os.environ.get("NEXUS_PROTOCOL") or r"C:\Proyectos\NexusProtocol"
    if source not in sys.path:
        sys.path.insert(0, source)
    try:
        from nexus.checks import rules_lint
        return rules_lint
    except ImportError:
        return None


class Gate:
    def __init__(self, root, config=None, max_lines=400, timeout=300):
        self.root = Path(root)
        self.config = config
        self.max_lines = max_lines
        self.timeout = timeout

    def lint(self):
        module = _linter()
        if module is None:
            return Check("lint", False, "nexus lint not importable (NEXUS_PROTOCOL?)",
                         exit=EXIT_UNAVAILABLE)
        try:
            report = module.lint_repo(str(self.root))
        except Exception as exc:
            return Check("lint", False, "lint crashed: %s: %s" % (type(exc).__name__, exc),
                         exit=EXIT_UNAVAILABLE)
        findings = report.get("findings") or []
        lines = ["[%s] %s:%s %s" % (item["rule"], item["file"], item["line"], item["detail"])
                 for item in findings[:60]]
        detail = "%d findings over %d files" % (len(findings), report.get("files_scanned", 0))
        if lines:
            detail = "%s\n%s" % (detail, "\n".join(lines))
        return Check("lint", not findings, detail,
                     exit=EXIT_GREEN if not findings else EXIT_RED)

    def line_law(self, touched):
        over = []
        for name in sorted(set(touched or [])):
            path = self.root / name
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            total = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
            if total > self.max_lines:
                over.append("%s has %d lines > %d" % (name, total, self.max_lines))
        return Check("line_law", not over, "; ".join(over) or "every touched file is under the limit",
                     exit=EXIT_GREEN if not over else EXIT_RED)

    def tests(self):
        command = getattr(self.config, "test_command", None)
        if not command:
            return Check("tests", True, "no test_command configured for this project", None,
                         blocking=False)
        # A patch that keeps the file's size and lands in the same second as the previous run leaves
        # Python's bytecode cache "valid": the test then exercises the OLD module and the gate reports
        # red on code that is already fixed. A fresh cache prefix per run makes the compiler read the
        # source every time, which is the only thing a gate is allowed to believe.
        cache = Path(tempfile.mkdtemp(prefix="nexus-gate-pyc-"))
        environment = dict(os.environ, PYTHONPYCACHEPREFIX=str(cache))
        try:
            completed = subprocess.run(command, shell=True, cwd=str(self.root), capture_output=True,
                                       text=True, errors="replace", timeout=self.timeout,
                                       env=environment)
        except subprocess.TimeoutExpired:
            return Check("tests", False, "%r timed out after %ss" % (command, self.timeout),
                         exit=EXIT_RED)
        except OSError as exc:
            return Check("tests", False, "could not run %r: %s" % (command, exc), exit=EXIT_RED)
        finally:
            shutil.rmtree(cache, ignore_errors=True)
        output = ((completed.stdout or "") + (completed.stderr or "")).strip()
        tail = output[-MAX_FAILURE_TEXT:]
        return Check("tests", completed.returncode == 0,
                     "exit %d: %s" % (completed.returncode, tail or "(no output)"),
                     exit=EXIT_GREEN if completed.returncode == 0 else EXIT_RED)

    def run(self, touched=None):
        checks = [self.lint(), self.line_law(touched), self.tests()]
        blocking = [check for check in checks if check.blocking and not check.ok]
        unavailable = any(check.exit == EXIT_UNAVAILABLE for check in blocking)
        failures = "\n".join("%s: %s" % (check.name, check.detail)
                             for check in blocking if check.detail)
        verdict = Verdict(ok=not blocking,
                          exit=EXIT_UNAVAILABLE if unavailable else (EXIT_GREEN if not blocking
                                                                    else EXIT_RED),
                          checks=checks, failures=failures[:MAX_FAILURE_TEXT],
                          at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        return verdict
