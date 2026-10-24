"""One command that proves the repository: the line law, then every deterministic suite.

    python tools/verify.py [--audit]

Exit 0 only when both are green. `--audit` adds the model review, which needs a local server and is
therefore reported as its own result instead of quietly passing.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command):
    completed = subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True,
                              errors="replace")
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="verify")
    parser.add_argument("--audit", action="store_true", help="also run the adversarial audit")
    args = parser.parse_args(argv)
    rows = []
    code, output = run([sys.executable, str(ROOT / "tools" / "lint_harness.py")])
    rows.append(("lint", code, output.strip().splitlines()[-1] if output.strip() else ""))
    code, output = run([sys.executable, "-m", "nexus_harness", "selftest"])
    rows.append(("selftest", code, output.strip().splitlines()[-1] if output.strip() else ""))
    if args.audit:
        code, output = run([sys.executable, str(ROOT / "tools" / "adversary_audit.py")])
        rows.append(("audit", code, output.strip().splitlines()[-1][:160] if output.strip() else ""))
    for name, code, detail in rows:
        print("%-9s exit %-3s %s" % (name, code, detail))
    failed = [name for name, code, _detail in rows if code != 0]
    print("verify: %s" % ("GREEN" if not failed else "RED (%s)" % ", ".join(failed)))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
