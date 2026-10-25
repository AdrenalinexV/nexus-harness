"""Deterministic context compaction: the transcript condenses before it runs out of room.

The session relay (`session_relay.py`) replaces a session the moment it crosses 70 % of its budget,
and that is a cliff: the whole conversation is thrown away and the next session re-plans from a
prompt. Compaction is the ramp *before* the cliff. At a lower threshold the transcript is rewritten
in place -- what a turn still needs stays verbatim, the rest is digested -- so the run keeps its
footing instead of arriving jadeando at the relay.

The digest is computed, not asked for: no model call, no clock, no randomness. The same transcript
always compacts to the same bytes, which is what makes it testable and what stops it from inventing
a fact the run never had. A model-written summary can lie about what happened; `_digest` cannot.

What survives, in order:

1. the head (the system message: rules and injected skills -- the law of the turn);
2. the goal, when it is the first user message;
3. a digest of everything dropped: the tools called, the files touched, the errors seen, the words;
4. the tail verbatim, cut on a valid OpenAI boundary -- a `tool` message is never left orphaned,
   because every OpenAI-shaped server rejects one with a 400.

Below the threshold nothing happens, and that is recorded (`applied=False`), never silent.
"""
from dataclasses import dataclass, field

from .message import Message

CHARS_PER_TOKEN = 4
ENVELOPE_CHARS = 16          # role, ids and separators the wire adds around a message's text
DIGEST_HEADER = "[contexto compactado]"
MAX_LINE = 160
MAX_ERRORS = 10
MAX_FACTS = 24
MAX_FILES = 40


def estimate(messages):
    """`(chars, tokens)` of a transcript as the model will read it. Pure, so two calls agree."""
    chars = 0
    for message in messages:
        chars += len(message.text_content()) + ENVELOPE_CHARS
        for call in getattr(message, "tool_calls", None) or ():
            chars += len(call.name) + len(call.raw_arguments or "")
    return chars, chars // CHARS_PER_TOKEN


def _line(text, limit=MAX_LINE):
    """One flattened line: a digest that keeps newlines is not a digest, it is a copy."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "\u2026"


def _tool_path(call):
    arguments = getattr(call, "arguments", None)
    if isinstance(arguments, dict):
        value = arguments.get("path") or arguments.get("file")
        if value:
            return str(value)
    return ""


def _digest(messages):
    """A deterministic summary of the dropped messages. No model, no clock, no opinion."""
    calls, files, errors, facts = [], [], [], []
    for message in messages:
        if message.role == "assistant":
            for call in message.tool_calls or ():
                calls.append(call.name)
                path = _tool_path(call)
                if path:
                    files.append(path)
            text = _line(message.text_content())
            if text:
                facts.append("assistant: %s" % text)
        elif message.role == "tool":
            body = message.text_content()
            if body.startswith("ERROR"):
                errors.append(_line(body))
        elif message.role == "user":
            facts.append("user: %s" % _line(message.text_content()))
    lines = [DIGEST_HEADER]
    if calls:
        counts = {}
        for name in calls:
            counts[name] = counts.get(name, 0) + 1
        rendered = ", ".join("%s x%d" % (name, counts[name]) for name in sorted(counts))
        lines.append("Herramientas (%d): %s" % (len(calls), rendered))
    if files:
        lines.append("Ficheros: %s" % ", ".join(sorted(set(files))[:MAX_FILES]))
    if errors:
        lines.append("Errores (%d):" % len(errors))
        lines.extend("  - %s" % item for item in errors[:MAX_ERRORS])
    if facts:
        lines.append("Hechos:")
        lines.extend("  - %s" % item for item in facts[:MAX_FACTS])
    return "\n".join(lines)


def _tail_start(messages, head, wanted):
    """First index of the verbatim tail, walked back so it never starts on an orphan `tool`."""
    start = max(head, len(messages) - wanted)
    while start > head and messages[start].role == "tool":
        start -= 1
    return start


@dataclass
class Compaction:
    """What one attempt did: the new transcript, the price before and after, and why."""

    applied: bool = False
    messages: list = field(default_factory=list)
    before: int = 0
    after: int = 0
    dropped: int = 0
    digest: str = ""
    ratio: object = None
    reason: str = ""

    def as_dict(self):
        return {"applied": self.applied, "before": self.before, "after": self.after,
                "dropped": self.dropped, "ratio": self.ratio, "reason": self.reason,
                "digest_chars": len(self.digest)}


def compact(messages, limit=60000, threshold=0.55, keep_head=2, keep_tail=8):
    """Condense `messages` in place-safe fashion when they approach `limit`. Never raises."""
    before_chars, before = estimate(messages)
    messages = list(messages)
    if limit <= 0:
        return Compaction(messages=messages, before=before, after=before, ratio=None,
                          reason="no budget: unmeasured")
    ratio = before / float(limit)
    if ratio < threshold:
        return Compaction(messages=messages, before=before, after=before, ratio=ratio,
                          reason="under threshold")
    head = min(int(keep_head), len(messages))
    start = _tail_start(messages, head, int(keep_tail))
    if start <= head:
        return Compaction(messages=messages, before=before, after=before, ratio=ratio,
                          reason="nothing safely droppable")
    dropped = messages[head:start]
    digest = _digest(dropped)
    kept = list(messages[:head]) + [Message(role="user", content=digest)] + list(messages[start:])
    after = estimate(kept)[1]
    if after >= before:
        return Compaction(messages=messages, before=before, after=after, ratio=ratio,
                          reason="the digest would not shrink the transcript")
    return Compaction(applied=True, messages=kept, before=before, after=after,
                      dropped=len(dropped), digest=digest, ratio=ratio,
                      reason="compacted %d messages" % len(dropped))


class Compactor:
    """Owns the threshold and applies `compact` to the live transcript, keeping a record for the bus."""

    def __init__(self, limit=60000, threshold=0.55, keep_head=2, keep_tail=8, enabled=True):
        self.limit = int(limit or 0)
        self.threshold = float(threshold or 0.0)
        self.keep_head = int(keep_head)
        self.keep_tail = int(keep_tail)
        self.enabled = bool(enabled)
        self.count = 0
        self.history = []
        self.last = None

    def maybe(self, messages):
        """Compact the list in place when it is time; return the `Compaction` that says whether it was."""
        if not self.enabled:
            before = estimate(messages)[1]
            self.last = Compaction(messages=list(messages), before=before, after=before,
                                   reason="compaction disabled")
            return self.last
        result = compact(messages, limit=self.limit, threshold=self.threshold,
                         keep_head=self.keep_head, keep_tail=self.keep_tail)
        if result.applied:
            messages[:] = result.messages
            self.count += 1
            self.history.append(result.as_dict())
        self.last = result
        return result
