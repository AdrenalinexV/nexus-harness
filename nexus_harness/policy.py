"""Zero-trust command policy: what this harness refuses to run, and who is allowed to lift it.

The harness hands a shell to a model, so "the model will be careful" is not a control. This module is
the control: a command is classified *before* a subprocess exists, and the answer is a `Verdict` --
allowed, or refused with the rule that stopped it. One deny-list cannot serve both a reviewer reading a
repo and an operator shipping a fix, so there are three levels:

* **catastrophic** -- refused in *every* mode, `unrestricted` included: formatting a drive, wiping the
  filesystem root, shutting the machine down, a fork bomb. An agent harness that can be talked into
  these is not a harness, it is a loaded gun with a chat window.
* **reckless** -- refused in `read_only` and `standard`, allowed only in `unrestricted`: `git push
  --force`, `git reset --hard`, `git clean -fd`, `rm -rf <path>`. Destructive *and* plausible in a
  normal turn, so the default makes the operator type the opt-in once, on purpose.
* **mutating** -- refused only in `read_only`: any write to the tree (`rm`, `mv`, `mkdir`, a
  redirection, a package install, a commit). That mode is for auditing a repository without touching it.

Matching is on the command **as written**, lowercased -- the same stance Claude Code documents for its
`Bash` deny rules -- which keeps every rule readable and testable. The limit is written down instead of
hidden: a model that obfuscates a command (`$(printf 'rm -rf /')`) is not caught here; the gate and the
filesystem are the backstop, not this table. The refusal is a `ValueError`, which `tools.Registry.call`
already turns into an observation (`ok=False`, text starting with `refused`) that the model can read and
act on -- never a crash, never a silent skip, never a "yes" it did not earn.
"""
import re
from dataclasses import dataclass

MODES = ("read_only", "standard", "unrestricted")
DEFAULT_MODE = "standard"
CONFIG_FIELD = "shell_policy"

# Denied in every mode. The rules that would end an operator's day rather than their turn.
CATASTROPHIC = (
    (r"\bformat\s+[a-z]:", "formatear una unidad"),
    (r"\bmkfs(\.[a-z0-9]+)?\b", "formatear un dispositivo"),
    (r"\brm\s+(-[a-z]*[rf][a-z]*\s+)+/(\s|$|\*)", "borrar la raiz del sistema de ficheros"),
    (r"\b(remove-item|rd|rmdir)\b[^\n]*-recurse\b[^\n]*[a-z]:\\?\s*$", "borrar una unidad recursivamente"),
    (r"\b(del|erase)\b\s+/[fsq][^\n]*[a-z]:\\?\s*$", "borrar una unidad con del /s"),
    (r"\bshutdown\b", "apagar la maquina"),
    (r"\breboot\b\s*$", "reiniciar la maquina"),
    (r"\bdd\b[^\n]*\bof=/dev/(sd|nvme|hd|disk)", "escribir sobre un disco crudo"),
    (r":\s*\(\s*\)\s*\{[^\n]*:\s*\|\s*:[^\n]*\}", "bomba fork"),
)

# Denied in read_only and standard: destructive and plausible. The opt-in is one config line.
RECKLESS = (
    (r"\bgit\s+push\b[^\n]*--force", "empujar con --force"),
    (r"\bgit\s+reset\b[^\n]*--hard", "tirar el trabajo local (reset --hard)"),
    (r"\bgit\s+clean\b[^\n]*-[a-z]*[fd]", "borrar ficheros no versionados (git clean)"),
    (r"\brm\s+(-[a-z]*[rf][a-z]*\s+)+", "borrado recursivo o forzado (rm -rf)"),
    (r"\b(del|erase)\b[^\n]*/[fs]\b", "borrado forzado con del"),
    (r"\btaskkill\b[^\n]*/f", "matar procesos a la fuerza"),
    (r"\btruncate\b[^\n]*-s\s*0", "truncar un fichero a cero"),
)

# Denied in read_only only: this is what writing looks like from a shell.
MUTATING = (
    (r"\b(rm|rmdir|del|erase|mv|move|cp|copy|mkdir|touch|chmod|chown|attrib)\b", "escribir en el arbol"),
    (r"\bgit\s+(add|commit|push|pull|fetch|checkout|switch|merge|rebase|stash|cherry-pick|apply|tag|init)\b",
     "mover el repositorio"),
    (r"\b(npm|pnpm|yarn|pip|pip3|uv|poetry|cargo|go|gem|apt|brew)\s+(install|add|remove|uninstall|sync|update|get|upgrade)\b",
     "instalar o quitar dependencias"),
    (r"(^|[^<>=-])>{1,2}\s*\S", "redirigir la salida a un fichero"),
    (r"\btee\b", "escribir via tee"),
    (r"\bsed\b[^\n]*\s-i", "editar ficheros con sed -i"),
)

LEVELS = (("catastrophic", CATASTROPHIC, ()), ("reckless", RECKLESS, ("unrestricted",)),
          ("mutating", MUTATING, ("standard", "unrestricted")))


@dataclass(frozen=True)
class Verdict:
    """What the policy decided: allowed, or refused with the level, the rule and the reason."""

    allowed: bool
    mode: str = DEFAULT_MODE
    level: str = ""
    reason: str = ""

    def as_dict(self):
        return {"allowed": self.allowed, "mode": self.mode, "level": self.level, "reason": self.reason}


def normalise(mode):
    """A mode the policy knows, or the default. A typo in a config file is not a licence."""
    text = str(mode or "").strip().lower()
    return text if text in MODES else DEFAULT_MODE


def mode_of(config):
    """The mode a config asks for (`shell_policy`), read defensively: no config means the default."""
    return normalise(getattr(config, CONFIG_FIELD, None) if config is not None else None)


def classify(command, mode=DEFAULT_MODE):
    """Classify one command. Pure: the same command and mode always give the same verdict."""
    mode = normalise(mode)
    text = " ".join(str(command or "").lower().split())
    if not text:
        return Verdict(False, mode, "empty", "comando vacio")
    for level, table, allowed_in in LEVELS:
        if mode in allowed_in:
            continue
        for pattern, reason in table:
            if re.search(pattern, text):
                return Verdict(False, mode, level, reason)
    return Verdict(True, mode)


def refusal(verdict):
    """The text the model reads: what was refused, why, and how to lift it on purpose."""
    return ("refused [%s/%s]: %s -- sube la politica (%s en ~/.nexus/harness.json: %s) "
            "solo si de verdad lo quieres" % (verdict.mode, verdict.level, verdict.reason,
                                              CONFIG_FIELD, "|".join(MODES)))
