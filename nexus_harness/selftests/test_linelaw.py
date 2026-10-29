"""The law the harness ships: R0 (syntax), R1 (swallowed error), R2 (over 400 lines).

Each rule is watched going red on a tree built for it, and the two rules that only exist in the
governor (R3, the approved-dependency policy) are not pretended: when NexusProtocol IS importable this
suite also asserts that both linters see the same findings on the same tree, so the shipped fallback
cannot quietly mean something else. On a machine without the governor that comparison cannot run and
says nothing -- the R0/R1/R2 assertions above it still do.
"""
import importlib
import os
import sys
from pathlib import Path

from .fakes import TempProject
from ..verify import linelaw


def check(name, got, expect, failures):
    if got != expect:
        failures.append("%s: %r, esperaba %r" % (name, got, expect))


def rules_of(report):
    return sorted(finding["rule"] for finding in report["findings"])


def test_line_law(failures):
    over = "".join("value_%d = %d\n" % (index, index) for index in range(linelaw.MAX_LINES + 1))
    with TempProject({"big.py": over, "small.py": "value = 1\n"}) as root:
        report = linelaw.lint_repo(root)
        check("a file over 400 lines is R2", rules_of(report), ["R2"], failures)
        check("and the finding counts the real lines",
              "lines > 400" in report["findings"][0]["detail"], True, failures)
        check("the small file was scanned too", report["files_scanned"], 2, failures)


def test_syntax_and_swallowed_errors(failures):
    with TempProject({
        "broken.py": "def broken(:\n    pass\n",
        "bare.py": "try:\n    value = 1\nexcept:\n    value = 0\n",
        "silent.py": "try:\n    value = 1\nexcept ValueError:\n    pass\n",
        "clean.py": "try:\n    value = 1\nexcept ValueError as exc:\n    print(exc)\n",
    }) as root:
        report = linelaw.lint_repo(root)
        check("a syntax error is R0", "R0" in rules_of(report), True, failures)
        check("a bare except is R1", rules_of(report).count("R1"), 2, failures)
        details = [finding["detail"] for finding in report["findings"] if finding["rule"] == "R1"]
        check("and the swallowed one says so", any("pass" in detail for detail in details), True,
              failures)
        check("a handled error is not a finding", "clean.py" not in
              [finding["file"] for finding in report["findings"]], True, failures)


def test_runtime_and_build_output_are_not_source(failures):
    over = "".join("value_%d = %d\n" % (index, index) for index in range(linelaw.MAX_LINES + 1))
    with TempProject({"app.py": "value = 1\n", ".nexus/worktrees/op/app.py": over,
                      "dist/bundled.py": over}) as root:
        report = linelaw.lint_repo(root)
        check("a copy of the repo under .nexus is not graded", rules_of(report), [], failures)
        check("nor build output", report["files_scanned"], 1, failures)


def _governor():
    """`nexus.checks.rules_lint` when this machine has it, else None. Same seam as the gate."""
    source = os.environ.get("NEXUS_PROTOCOL") or r"C:\Proyectos\NexusProtocol"
    if Path(source).is_dir() and str(source) not in sys.path:
        sys.path.insert(0, str(source))
    try:
        return importlib.import_module("nexus.checks.rules_lint")
    except ImportError:
        return None


def test_agreement_with_the_governor(failures):
    """The fallback and the canonical linter must agree on the rules they share."""
    module = _governor()
    if module is None:
        return
    with TempProject({
        "big.py": "".join("v%d = %d\n" % (index, index) for index in range(linelaw.MAX_LINES + 1)),
        "bare.py": "try:\n    value = 1\nexcept:\n    value = 0\n",
        "clean.py": "value = 1\n",
    }) as root:
        ours = sorted((f["rule"], f["file"], f["line"]) for f in linelaw.lint_repo(root)["findings"])
        theirs = sorted((f["rule"], f["file"], f["line"]) for f in module.lint_repo(root)["findings"])
        check("the shipped law and the governor find the same things in the same places", ours,
              theirs, failures)


def run():
    failures = []
    test_line_law(failures)
    test_syntax_and_swallowed_errors(failures)
    test_runtime_and_build_output_are_not_source(failures)
    test_agreement_with_the_governor(failures)
    return failures
