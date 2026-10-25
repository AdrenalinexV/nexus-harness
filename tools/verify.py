"""One command that proves the repository: the line law, then every deterministic suite.

    python tools/verify.py [--audit] [--frozen]

Exit 0 only when both are green. `--audit` adds the model review, which needs a local server and is
therefore reported as its own result instead of quietly passing. `--frozen` adds the frozen engine,
measured against the source instead of against a number written down here.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "dist" / "nexus-harness-engine.exe"


def run(command):
    completed = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True,
                              errors="replace")
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def summary(output):
    lines = output.strip().splitlines()
    return lines[-1] if lines else ""


def frozen_row(source_summary):
    """The frozen engine against the SOURCE, not against a number kept in the rubric.

    A criterion that pins `suites=17` is stale the moment a suite is added, and one that only looks
    for `failures=0` goes green on a stale binary that runs one suite less -- which is exactly what
    happened: `dist/` ran 16 suites and the source 17, and nobody noticed because nothing was
    failing. Comparing the two summary lines closes both holes with no number to maintain.
    """
    if not FROZEN.is_file():
        return "frozen", 30, "no frozen engine at %s -- build it from tools/engine.spec" % FROZEN
    code, output = run([str(FROZEN), "selftest"])
    frozen = summary(output)
    if not frozen.startswith("suites="):
        return "frozen", 10, "the frozen engine reported no summary: %s" % (frozen[-160:] or "nothing")
    if frozen != source_summary:
        return "frozen", 10, "the frozen engine runs ANOTHER suite: source=%r frozen=%r" % (
            source_summary, frozen)
    return "frozen", 0, "%s (same as the source)" % frozen



def main(argv=None):
    parser = argparse.ArgumentParser(prog="verify")
    parser.add_argument("--audit", action="store_true", help="also run the adversarial audit")
    parser.add_argument("--frozen", action="store_true",
                        help="also measure the frozen engine against the source suite")
    args = parser.parse_args(argv)
    rows = []
    code, output = run([sys.executable, str(ROOT / "tools" / "lint_harness.py")])
    rows.append(("lint", code, summary(output)))
    code, output = run([sys.executable, "-m", "nexus_harness", "selftest"])
    source = summary(output)
    rows.append(("selftest", code, source))
    if args.frozen:
        rows.append(frozen_row(source))
    if args.audit:
        code, output = run([sys.executable, str(ROOT / "tools" / "adversary_audit.py")])
        rows.append(("audit", code, summary(output)[:160]))
    for name, code, detail in rows:
        print("%-9s exit %-3s %s" % (name, code, detail))
    failed = [name for name, code, _detail in rows if code != 0]
    print("verify: %s" % ("GREEN" if not failed else "RED (%s)" % ", ".join(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
