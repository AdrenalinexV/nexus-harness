"""The line law, applied to this repository. Canonical linter when the governor is here, ours when not.

`nexus/checks/rules_lint.py` fixes its `ROOT` to the Nexus Protocol repository, so running it as a
script would lint the engine and not the harness. Its `lint_repo(root)` takes a root, which is the
only seam needed: one definition of R0-R3 on this machine, pointed at a second tree.

That import used to be unconditional, and it made this repository impossible to verify on any machine
without the governor -- a fresh clone on CI died in `lint` with `No module named 'nexus'`. Now the
governor wins when it is importable (R0-R3) and the harness's own mechanical law answers when it is
not (R0-R2), and the summary line always says which one ran.

    python tools/lint_harness.py [--json]     exit 0 = clean, 1 = findings
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus_harness.verify import linelaw  # noqa: E402  (the law lives in the verify layer)


def canonical():
    """The governor's linter, or None. Never a module-level import: it is optional by definition."""
    source = os.environ.get("NEXUS_PROTOCOL") or r"C:\Proyectos\NexusProtocol"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    try:
        from nexus.checks import rules_lint
        return rules_lint
    except ImportError:
        return None

# No skip list here: build output (`dist/`, `.build/`, `target/`) is the governor's business now, so
# this wrapper cannot drift from the rules it is applying. Medido antes del cambio: `.build/venv`
# alone made this repository look like 1737 files with 1949 findings.
#
# La UNICA excepcion es `.nexus/`: es estado de ejecucion (worktrees del Obrero, sesiones, caches), no
# codigo del repositorio, y una copia de seguridad de git no lo versiona (esta en `.gitignore`). Un
# worktree huerfano de un proceso matado a la fuerza hacia que la ley de 400 midiera 237 ficheros en
# vez de 115, y un gate que cuenta copias de si mismo no mide el repositorio. Se FILTRA y se dice
# cuantos se ignoraron: no es un skip silencioso.
RUNTIME_PARTS = {".nexus"}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="lint_harness")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args(argv)
    module = canonical()
    if module is not None:
        report = module.lint_repo(args.root)
        report["linter"], report["rules"] = "protocol", ["R0", "R1", "R2", "R3"]
    else:
        report = linelaw.lint_repo(args.root)
    findings = report["findings"]
    ignored = [item for item in findings
               if RUNTIME_PARTS & set(Path(str(item.get("file") or "")).parts)]
    report["findings"] = [item for item in findings if item not in ignored]
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for finding in report["findings"]:
            print("%s %s:%s %s" % (finding["rule"], finding["file"], finding["line"],
                                   finding["detail"]))
        print("files=%d findings=%d max_lines=%d ignored_runtime=%d linter=%s(%s)"
              % (report["files_scanned"], len(report["findings"]), report["max_lines"],
                 len(ignored), report.get("linter", "builtin"),
                 ",".join(report.get("rules") or ())))
    return 0 if not report["findings"] else 1


if __name__ == "__main__":
    sys.exit(main())
