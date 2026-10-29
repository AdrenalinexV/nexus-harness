"""Keeping a 40 000-line build log out of a 60 000-token budget without losing it.

The rule is head+tail, never head-only: the first lines of a test run say what started, the last lines
say why it failed, and the middle of a 40 000-line log has never once been the answer. What gets clipped
is not thrown away -- it lands in `.nexus/harness/logs/` and the model is handed the path, so it can
page through the part it actually needs without the transcript paying for it.
"""
import time
from pathlib import Path

MAX_OUTPUT = 12000
TAIL = 4000
LOG_DIR = Path(".nexus") / "harness" / "logs"


def clip(text, limit=MAX_OUTPUT, tail=TAIL):
    """Head + tail with a marker that says exactly how much is missing."""
    text = str(text or "")
    if len(text) <= limit:
        return text
    head = limit - tail
    return "%s\n... (%d chars clipped, full log on disk)\n%s" % (text[:head], len(text) - limit,
                                                                text[-tail:])


def log_path(root, label="output"):
    """A fresh log file for one command, inside the project's own `.nexus` directory."""
    directory = Path(root) / LOG_DIR
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in str(label))[:40]
    return directory / ("%s-%s.log" % (stamp, safe or "output"))


def clip_with_log(root, text, label="output"):
    """`(clipped_text, log_path_or_None)`: a path only when something was actually clipped."""
    text = str(text or "")
    if len(text) <= MAX_OUTPUT:
        return text, None
    target = log_path(root, label)
    with open(target, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return clip(text), str(target)
