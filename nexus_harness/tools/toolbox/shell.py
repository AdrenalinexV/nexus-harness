"""Running a command: a timeout, a clean capture, and a refusal list.

The capture is truncated head+tail rather than head-only, because the end of a failing test run is
the part that says why. The refusal list is short and mechanical (it names shapes that end a machine,
not commands that are merely risky): this is an autonomous harness, and a harness that asks a human
before every build is not autonomous.
"""
import re
from pathlib import Path

from ...platform import policy, sandbox

MAX_OUTPUT = 12000
TAIL = 4000
FORBIDDEN = (
    (r"format\s+[a-z]:", "formatting a drive"),
    (r"\brm\s+-rf\s+/(\s|$)", "deleting the filesystem root"),
    (r"remove-item\s+.*-recurse\s+.*c:\\\\?\s*$", "deleting C:\\ recursively"),
    (r"\bshutdown\b", "shutting the machine down"),
    (r":\(\)\s*\{\s*:\|:&\s*\}", "fork bomb"),
)


def clipped(text):
    """Keep the head and the tail: the middle of a 30 000-line log is never the answer."""
    if len(text) <= MAX_OUTPUT:
        return text
    return "%s\n... (%d chars clipped)\n%s" % (text[:MAX_OUTPUT - TAIL],
                                               len(text) - MAX_OUTPUT, text[-TAIL:])


def refused(command):
    lowered = command.lower()
    for pattern, reason in FORBIDDEN:
        if re.search(pattern, lowered):
            return reason
    return ""


def run(root, command, timeout=None, config=None):
    """`(output, meta)` for one command. The exit code is in `meta`, never folded into the text."""
    command = str(command or "").strip()
    if not command:
        raise ValueError("empty command")
    reason = refused(command)
    if reason:
        raise ValueError("refused: %s" % reason)
    # La segunda red: la politica de siempre (modos, jaula y firma del operador). `refused()` de arriba
    # solo nombra lo catastrofico; esto decide lo demas y lo hace ANTES de crear el subproceso.
    verdict = policy.classify(command, policy.mode_of(config), cage=sandbox.current(),
                              allow_unsandboxed=sandbox.operator_override())
    if not verdict.allowed:
        raise ValueError(policy.refusal(verdict))
    limit = int(timeout or getattr(config, "shell_timeout", 180))
    # `shell=True` is the feature, not an oversight: this tool exists so a model can run `pytest -k x |
    # tail -20` in somebody's own repository. The injection surface is bounded by the refusal list
    # above and by the fact that the command comes from the operator's session, not from a web page.
    completed = sandbox.run(command, shell=True, cwd=str(Path(root)), timeout=limit)
    output = (completed.stdout or "") + (("\n[stderr]\n" + completed.stderr)
                                         if (completed.stderr or "").strip() else "")
    return clipped(output).strip() or "(no output)", {"exit": completed.returncode,
                                                      "command": command, "files": []}


HANDLERS = {"shell": lambda root, args, config: run(
    root, args.get("command", ""), args.get("timeout"), config)}
