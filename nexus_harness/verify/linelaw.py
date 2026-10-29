"""The mechanical law, shipped with the harness so a gate works on a machine with no governor.

`nexus/checks/rules_lint.py` is the governor's linter and it is better than this one: it also applies
R3 (an import must be stdlib, local, or listed under APPROVED DEPENDENCIES in `.ai/PROJECT_RULES.md`),
which is a *policy* about one project. This module carries the three laws that hold for any tree and
need no policy:

  R0  syntax error
  R1  `except:` bare, or a handler whose whole body is `pass` (the error is swallowed)
  R2  a file longer than 400 lines

Why it ships: `gate` is the product, and it used to answer `20 -- could not verify` for every user who
did not have the Nexus Protocol repository on disk, which is every user. A gate that can only run
inside one machine is not a gate. When the governor IS importable the wrapper in `tools/` and the gate
still prefer it -- the canonical rules win where they exist -- and the report says which linter ran, so
a weaker law can never pass itself off as the full one.
"""
import ast
import sys
from pathlib import Path

MAX_LINES = 400
RULES = ("R0", "R1", "R2")

# Source only. A linter that grades build output drowns the law in findings about somebody else's
# generated code: one PyInstaller work dir plus a Cargo `target` was 1737 files and 1949 findings.
SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "node_modules", ".mypy_cache", ".pytest_cache", "Nexus_Release",
    "dist", "build", ".build", "target", "engine", "site-packages",
    # Runtime state of this harness: worktrees of the worker, sessions, attachment staging. A gate that
    # counts copies of the repository measures the machine's crud, not the source.
    ".nexus",
}


def python_files(root):
    """Every `.py` under `root` that is source, in a stable order."""
    root = Path(root)
    return sorted(path for path in root.rglob("*.py")
                  if not any(part in SKIP_DIRS for part in path.relative_to(root).parts))


def _line_count(text):
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _swallowed(node):
    """R1: a handler that hides the error -- bare, or a body of nothing but `pass`."""
    if node.type is None:
        return "bare except"
    body = [item for item in node.body if not isinstance(item, ast.Expr)]
    if body and all(isinstance(item, ast.Pass) for item in body):
        return "handler body is only `pass`: error swallowed"
    return None


def lint_file(path, root):
    """Findings for one file. Separate from the walk so a test can grade a string in one call."""
    path = Path(path)
    rel = path.relative_to(root).as_posix() if path.is_absolute() else path.as_posix()
    text = path.read_text(encoding="utf-8", errors="replace")
    findings = []
    lines = _line_count(text)
    if lines > MAX_LINES:
        findings.append({"rule": "R2", "file": rel, "line": 0,
                         "detail": "%d lines > %d" % (lines, MAX_LINES)})
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        findings.append({"rule": "R0", "file": rel, "line": exc.lineno or 0,
                         "detail": "syntax error: %s" % exc.msg})
        return findings
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            reason = _swallowed(node)
            if reason:
                findings.append({"rule": "R1", "file": rel, "line": node.lineno,
                                 "detail": reason})
    return findings


def lint_repo(root, max_lines=MAX_LINES):
    """`{findings, counts, files_scanned, max_lines, rules, linter}` over a whole tree.

    The shape is the governor's on purpose: `tools/lint_harness.py` and `Gate.lint` read the same
    keys, so which linter answered is a fact in the report, not a difference in behaviour.
    """
    root = Path(root)
    findings, files = [], python_files(root)
    for path in files:
        findings.extend(lint_file(path, root))
    counts = {}
    for finding in findings:
        counts[finding["rule"]] = counts.get(finding["rule"], 0) + 1
    return {"findings": findings, "counts": counts, "files_scanned": len(files),
            "max_lines": max_lines, "rules": list(RULES), "linter": "builtin"}


def summary(report):
    """One line for a human: what ran, over how many files, and how many findings."""
    return "files=%d findings=%d max_lines=%d linter=%s(%s)" % (
        report.get("files_scanned", 0), len(report.get("findings") or []),
        report.get("max_lines", MAX_LINES), report.get("linter", "builtin"),
        ",".join(report.get("rules") or RULES))


def main(argv=None):  # pragma: no cover - the wrapper in tools/ is the entry point
    root = Path(argv[1] if argv and len(argv) > 1 else ".").resolve()
    report = lint_repo(root)
    for finding in report["findings"]:
        print("%s %s:%s %s" % (finding["rule"], finding["file"], finding["line"],
                               finding["detail"]))
    print(summary(report))
    return 0 if not report["findings"] else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv))
