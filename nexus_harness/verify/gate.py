"""The gate: the only thing in this harness allowed to say the work is done.

Exit `10` is red and `0` is green -- the protocol's number, so a red gate is not a new vocabulary. Three
checks, in increasing cost, and all of them deterministic:

1. **The lint**. The governor's linter (`nexus/checks/rules_lint.py`, R0-R3) when this machine has it,
   because there is then one definition of the law; otherwise the mechanical law this package ships
   (`linelaw.py`, R0-R2), so `gate` is not a 20 for every user who never installed the governor. The
   report names which one answered: a weaker law may never pass itself off as the full one.
2. **The line law** on the files the turn touched, because "no file over 400 lines" is the one rule
   the model can break the moment it writes.
3. **The project's own tests**, when the project declares a command. A project that declares none is
   reported as *not configured* -- never as green, because an absent check is not a passed check.

A gate that cannot run at all returns exit `20` and says so. Fail-closed means it refuses to be green,
not that it invents a verdict.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import linelaw, oracle

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
        source = "protocol" if module is not None else "builtin"
        try:
            report = (module.lint_repo(str(self.root)) if module is not None
                      else linelaw.lint_repo(self.root))
        except Exception as exc:
            return Check("lint", False, "lint crashed: %s: %s" % (type(exc).__name__, exc),
                         exit=EXIT_UNAVAILABLE)
        findings = report.get("findings") or []
        lines = ["[%s] %s:%s %s" % (item["rule"], item["file"], item["line"], item["detail"])
                 for item in findings[:60]]
        detail = "%d findings over %d files (%s lint, %s)" % (
            len(findings), report.get("files_scanned", 0), source,
            ",".join(report.get("rules") or ()))
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

    def tests(self, touched=None):
        """Comportamiento: el comando declarado, el runner que el repo ya tiene, o importar lo tocado.

        Un proyecto que no declara comando ya no sale "verde" por omision: si hay runner, se usa; si
        no, se importa lo que el turno toco (humo real en subproceso); y si ni eso es posible, el gate
        devuelve 20 (*no verificable*). Un verde sin prueba es el fallo mas caro de un arnes.
        """
        command = getattr(self.config, "test_command", None)
        if command:
            return self._run("tests", command, "declarado")
        found = oracle.detect(self.root)
        if found:
            return self._run("tests", found["command"], found["source"])
        if not touched:
            return Check("tests", True, "sin ficheros tocados: nada que probar", None,
                         blocking=False)
        # Un cambio de documentacion no se prueba con tests: seria ruido, no rigor. Un `.py` que el
        # turno dice haber tocado y ya no existe si es un problema: no hay nada que medir.
        python_touched = oracle.python_files(self.root, touched)
        expects_code = any(str(name).endswith(".py") for name in touched or ())
        if not python_touched:
            if expects_code:
                return Check("behavior", False, "no verificable: los .py tocados no existen",
                             exit=EXIT_UNAVAILABLE)
            return Check("tests", True, "sin ficheros ejecutables: nada que probar", None,
                         blocking=False)
        ok, detail = oracle.smoke(self.root, touched)
        if ok is None:
            return Check("behavior", False, "no verificable: %s" % detail, exit=EXIT_UNAVAILABLE)
        return Check("behavior", ok, "humo de importacion: %s" % detail,
                     exit=EXIT_GREEN if ok else EXIT_RED)

    def _run(self, name, command, source):
        """Ejecuta un comando de verificacion con cache de bytecode fresca y lo reporta."""
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
            return Check(name, False, "%r timed out after %ss (%s)" % (command, self.timeout, source),
                         exit=EXIT_RED)
        except OSError as exc:
            return Check(name, False, "could not run %r: %s" % (command, exc), exit=EXIT_RED)
        finally:
            shutil.rmtree(cache, ignore_errors=True)
        output = ((completed.stdout or "") + (completed.stderr or "")).strip()
        tail = output[-MAX_FAILURE_TEXT:]
        return Check(name, completed.returncode == 0,
                     "exit %d (%s): %s" % (completed.returncode, source, tail or "(no output)"),
                     exit=EXIT_GREEN if completed.returncode == 0 else EXIT_RED)

    def run(self, touched=None):
        checks = [self.lint(), self.line_law(touched), self.tests(touched)]
        blocking = [check for check in checks if check.blocking and not check.ok]
        unavailable = any(check.exit == EXIT_UNAVAILABLE for check in blocking)
        failures = "\n".join("%s: %s" % (check.name, check.detail)
                             for check in blocking if check.detail)
        verdict = Verdict(ok=not blocking,
                          exit=EXIT_UNAVAILABLE if unavailable else (EXIT_GREEN if not blocking
                                                                    else EXIT_RED),
                          checks=checks, failures=failures[:MAX_FAILURE_TEXT],
                          at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        oracle.write_report(self.root, {"touched": list(touched or ()), "verdict": verdict.as_dict()})
        return verdict
