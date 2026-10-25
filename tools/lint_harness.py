"""The line law, applied to this repository by the protocol's own linter.

`nexus/checks/rules_lint.py` fixes its `ROOT` to the Nexus Protocol repository, so running it as a
script would lint the engine and not the harness. Its `lint_repo(root)` takes a root, which is the
only seam needed: one definition of R0-R3 on this machine, pointed at a second tree.

    python tools/lint_harness.py [--json]     exit 0 = clean, 1 = findings
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEXUS_SOURCE = Path(os.environ.get("NEXUS_PROTOCOL", r"C:\Proyectos\NexusProtocol"))
if str(NEXUS_SOURCE) not in sys.path:
    sys.path.insert(0, str(NEXUS_SOURCE))

from nexus.checks import rules_lint  # noqa: E402  (path is prepared above, by design)

# No skip list here: build output (`dist/`, `.build/`, `target/`) is the governor's business now, so
# this wrapper cannot drift from the rules it is applying. Measured before the move: `.build/venv`
# alone made this repository look like 1737 files with 1949 findings.


def main(argv=None):
    parser = argparse.ArgumentParser(prog="lint_harness")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)
    report = rules_lint.lint_repo(args.root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for finding in report["findings"]:
            print("%s %s:%s %s" % (finding["rule"], finding["file"], finding["line"],
                                   finding["detail"]))
        print("files=%d findings=%d max_lines=%d"
              % (report["files_scanned"], len(report["findings"]), report["max_lines"]))
    return 0 if not report["findings"] else 1


if __name__ == "__main__":
    sys.exit(main())
