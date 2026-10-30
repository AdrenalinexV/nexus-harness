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
DOC = ROOT / "docs" / "VERIFICATION.md"


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
    # El congelado puede saltarse MAS suites que el checkout (las que miden el arbol del repo no tienen
    # nada que medir dentro de un .exe), pero no puede correr MENOS suites ni fallar ninguna.
    def counts(line):
        return {key: int(value) for key, value in
                (chunk.split("=") for chunk in line.split() if "=" in chunk)}

    source, binary = counts(source_summary), counts(frozen)
    if binary.get("suites") != source.get("suites"):
        return "frozen", 10, "the frozen engine runs ANOTHER suite: source=%r frozen=%r" % (
            source_summary, frozen)
    if binary.get("failures"):
        return "frozen", 10, "the frozen engine FAILS: %r" % frozen
    if binary.get("skipped", 0) < source.get("skipped", 0):
        return "frozen", 10, "el congelado salta menos suites que el checkout: %r" % frozen
    return "frozen", 0, "%s (skips de checkout permitidos)" % frozen



def report_lines(rows):
    """Las lineas que se imprimen Y las que se escriben en el registro: una sola fuente.

    Si la impresion y lo que se guarda salieran de dos sitios distintos, el documento acabaria contando
    una noche que no fue la que corrio.
    """
    lines = ["%-9s exit %-3s %s" % (name, code, detail) for name, code, detail in rows]
    failed = [name for name, code, _detail in rows if code != 0]
    lines.append("verify: %s" % ("GREEN" if not failed else "RED (%s)" % ", ".join(failed)))
    return lines, failed


def _fenced(lines):
    return "```\n%s\n```" % "\n".join(lines)


def _replace_block(text, marker, body):
    """Sustituye el bloque cercado que sigue a `marker`, o None si el documento no tiene esa forma."""
    start = text.find(marker)
    opening = text.find("```", start) if start >= 0 else -1
    closing = text.find("```", opening + 3) if opening >= 0 else -1
    if closing < 0:
        return None
    return text[:opening] + body + text[closing + 3:]


def sync_doc(lines, command, suites):
    """El registro (`docs/VERIFICATION.md`) se actualiza con lo que se acaba de medir.

    El fichero decia que "se actualiza ejecutando `python tools/verify.py`" y no lo hacia: seguia
    anunciando `files=55 suites=12` con el arbol en 80 y 23. Se reescriben SOLO los dos bloques medidos
    (el resumen y la lista de suites, con el comando tal como se lanzo); el resto del registro es
    historia de su momento y no se toca.
    """
    if not DOC.is_file():
        return "no hay registro en %s" % DOC.relative_to(ROOT)
    text = DOC.read_text(encoding="utf-8")
    updated = _replace_block(text, "## The one command", _fenced(["$ " + command] + lines))
    if updated is not None:
        updated = _replace_block(updated, "## The suites, individually",
                                 _fenced([line for line in suites.splitlines() if line.strip()]))
    if updated is None:
        return "el registro no tiene los bloques esperados; no se toca"
    DOC.write_text(updated, encoding="utf-8")
    return "actualizado %s" % DOC.relative_to(ROOT)


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
    suites = output
    rows.append(("selftest", code, source))
    if args.frozen:
        rows.append(frozen_row(source))
    if args.audit:
        code, output = run([sys.executable, str(ROOT / "tools" / "adversary_audit.py")])
        rows.append(("audit", code, summary(output)[:160]))
    lines, failed = report_lines(rows)
    for line in lines:
        print(line)
    command = "python tools/verify.py" + (" --frozen" if args.frozen else "") + \
              (" --audit" if args.audit else "")
    print(sync_doc(lines, command, suites))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
