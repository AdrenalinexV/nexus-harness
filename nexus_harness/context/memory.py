"""Durable memory: the few facts a harness must not re-learn every session.

Memory is a markdown file, one entry per paragraph, capped twice (entries and characters). That is
deliberately boring: a memory you cannot read with `cat` is a memory you cannot audit, and an
unbounded one is a context leak that grows every turn.

The rule for what belongs here is the one in the system prompt: facts that apply to every session
regardless of task (who the operator is, machine quirks, standing conventions). Procedures belong in
skills, where they load only when relevant -- a memory entry costs tokens on every single turn.
"""
import os
import time
from pathlib import Path

DEFAULT_PATH = Path(os.environ.get("NEXUS_HOME") or (Path.home() / ".nexus")) / "harness" / "memory.md"
MAX_ENTRIES = 200
MAX_CHARS = 6000
HEADER = "# Nexus-Harness memory\n\nFacts that apply to every session. One entry per paragraph.\n"


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Memory:
    """The operator's durable notes. Add, remove, and the block that travels with every turn."""

    def __init__(self, path=None):
        self.path = Path(path) if path else DEFAULT_PATH

    def _read(self):
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError:
            return HEADER

    def entries(self):
        """The entries as a list, in file order. The header is not an entry."""
        blocks = [block.strip() for block in self._read().split("\n\n")]
        return [block for block in blocks
                if block and not block.startswith("# Nexus-Harness memory")
                and not block.startswith("Facts that apply")]

    def _write(self, entries):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = "\n\n".join(entries)
        self.path.write_text(HEADER + ("\n" + body + "\n" if body else ""), encoding="utf-8")

    def add(self, text):
        """Append one entry. Returns the state, or a refusal that says why it would not fit."""
        cleaned = " ".join(str(text or "").split())
        if not cleaned:
            return {"ok": False, "reason": "an empty entry says nothing"}
        current = self.entries()
        if cleaned in current:
            return {"ok": True, "duplicate": True, "entries": len(current)}
        if len(current) >= MAX_ENTRIES:
            return {"ok": False, "reason": "memory is full (%d entries): remove one first"
                    % MAX_ENTRIES}
        candidate = current + [cleaned]
        if len("\n\n".join(candidate)) > MAX_CHARS:
            return {"ok": False, "reason": "memory would exceed %d characters: consolidate first"
                    % MAX_CHARS}
        self._write(candidate)
        return {"ok": True, "entries": len(candidate), "chars": len("\n\n".join(candidate))}

    def remove(self, needle):
        """Remove every entry containing `needle`. Returns how many went."""
        text = str(needle or "").strip()
        if not text:
            return {"ok": False, "reason": "nothing to match"}
        current = self.entries()
        kept = [entry for entry in current if text.lower() not in entry.lower()]
        if len(kept) == len(current):
            return {"ok": False, "reason": "no entry contains that text", "removed": 0}
        self._write(kept)
        return {"ok": True, "removed": len(current) - len(kept), "entries": len(kept)}

    def block(self):
        """What the model sees. Empty when there is no memory: silence is a valid answer."""
        entries = self.entries()
        if not entries:
            return ""
        budget, picked = MAX_CHARS // 2, []
        for entry in reversed(entries):  # the newest entries matter most when space runs out
            if len(entry) > budget:
                break
            picked.append(entry)
            budget -= len(entry)
        return "## Memoria del operador\n\n" + "\n\n".join(reversed(picked))

    def as_dict(self):
        entries = self.entries()
        return {"path": str(self.path), "entries": entries, "count": len(entries),
                "chars": len("\n\n".join(entries)), "limit_chars": MAX_CHARS,
                "limit_entries": MAX_ENTRIES, "updated_at": _now()}
