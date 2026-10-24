"""Which specialists this turn calls for, injected in RAM and nowhere else.

The arithmetic is Nexus Protocol's (`nexus/skills/routing.py`): globs declared by each specialist
against the files the turn actually touched, the two highest scores travel, ties break on name. This
module owns the part the protocol cannot: *when* it runs. It runs before every model call, against
the accumulated set of files, so a turn that starts on `README.md` and ends in `src/auth.py` carries
the auth rules by its third call -- not from the first token, and not by re-reading a directory of
inactive skills.

Level 1 (`verification`, `clean-code`) always travels: those two rules are cheap and a project cannot
afford to forget them. Level 2 travels only on a match, which is why eight specialists cost what two do.
"""
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

NEXUS_SOURCE = Path(os.environ.get("NEXUS_PROTOCOL") or r"C:\Proyectos\NexusProtocol")
MAX_SHORTLIST = 2
CHARS_PER_TOKEN = 4


def _modules():
    """The protocol's routing and catalogue, imported once and reported if this machine moved them."""
    if str(NEXUS_SOURCE) not in sys.path:
        sys.path.insert(0, str(NEXUS_SOURCE))
    from nexus.skills import catalog, routing
    return catalog, routing


@dataclass
class Injection:
    """What travels with the turn: the names, the text, and what it cost."""

    names: list = field(default_factory=list)
    entries: list = field(default_factory=list)
    brief: str = ""
    tokens: int = 0
    available: bool = True
    note: str = ""

    def as_dict(self):
        return {"names": list(self.names), "tokens": self.tokens, "available": self.available,
                "note": self.note, "chars": len(self.brief)}


class ContextRouter:
    """The prefilter, called as often as the turn changes its mind about which files matter."""

    def __init__(self, lang="es", limit=MAX_SHORTLIST, enabled=True):
        self.lang = lang
        self.limit = int(limit)
        self.enabled = enabled
        self._always = None
        self._pack = None
        self._error = ""

    def _load(self):
        if self._always is not None or self._error:
            return
        try:
            catalog, _routing = _modules()
            self._always = [entry for entry in getattr(catalog, "MAIN", ()) if entry.get("name")]
            self._pack = catalog.pack()
        except Exception as exc:  # the harness reports a missing engine instead of pretending
            self._error = "%s: %s" % (type(exc).__name__, exc)
            self._always, self._pack = [], []

    @property
    def available(self):
        self._load()
        return not self._error

    def select(self, files):
        """The injection for these files. Calling it twice with the same list gives the same answer."""
        if not self.enabled:
            return Injection(note="routing disabled", available=True)
        self._load()
        if self._error:
            return Injection(available=False, note="routing unavailable -- %s" % self._error)
        _catalog, routing = _modules()
        try:
            picked = routing.shortlist([str(item) for item in files if str(item).strip()],
                                       limit=self.limit, entries=self._pack)
        except Exception as exc:
            return Injection(available=False, note="routing failed -- %s: %s"
                             % (type(exc).__name__, exc))
        entries = list(self._always) + picked
        brief = routing.brief(entries, self.lang)
        return Injection(names=[entry["name"] for entry in entries], entries=entries, brief=brief,
                         tokens=len(brief) // CHARS_PER_TOKEN, available=True)
