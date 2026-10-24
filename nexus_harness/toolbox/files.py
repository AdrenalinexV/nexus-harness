"""Reading and searching a repository without flooding a context window.

Two rules keep this honest:

* **Every path is resolved inside the project root.** An agent that can write `C:\\Windows\\System32`
  because it guessed a relative path is not an agent, it is a liability.
* **Every result is bounded.** `read_file` returns numbered lines with a limit, `search` caps matches.
  A tool that can return 40 000 lines is a tool that ends the session it was called to help.
"""
import os
import re
from pathlib import Path

MAX_LINES = 400
MAX_READ = 1200
MAX_MATCHES = 60
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".mypy_cache", ".pytest_cache",
             ".nexus", "dist", "build"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".7z",
                   ".exe", ".dll", ".pyc", ".so", ".mp4", ".mp3", ".woff", ".woff2"}


def resolve(root, path):
    """`path` as an absolute path that is inside `root`, or a `ValueError` that says why not."""
    base = Path(root).resolve()
    candidate = Path(path or ".")
    target = (candidate if candidate.is_absolute() else base / candidate).resolve()
    if target != base and base not in target.parents:
        raise ValueError("%s is outside the project root %s" % (target, base))
    return target


def relative(root, target):
    try:
        return Path(target).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(target)


def line_count(text):
    return text.count("\n") + (0 if text.endswith("\n") or not text else 1)


def read_text(path):
    """The file exactly as it is on disk: `Path.read_text` would rewrite CRLF to LF in memory, and a
    patcher that cannot see the real bytes cannot keep them."""
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as handle:
        return handle.read()


def read(root, path, offset=1, limit=MAX_READ):
    target = resolve(root, path)
    if not target.is_file():
        raise ValueError("%s is not a file" % relative(root, target))
    text = read_text(target)
    lines = text.splitlines()
    start = max(1, int(offset))
    window = lines[start - 1:start - 1 + max(1, min(int(limit), MAX_READ))]
    body = "\n".join("%5d| %s" % (start + index, line) for index, line in enumerate(window))
    footer = "\n... %d more lines" % (len(lines) - (start - 1 + len(window))) \
        if len(lines) > start - 1 + len(window) else ""
    return body + footer, {"files": [relative(root, target)], "lines": len(lines)}


def write(root, path, content):
    target = resolve(root, path)
    total = line_count(content)
    if total > MAX_LINES:
        raise ValueError("%s would be %d lines > %d" % (relative(root, target), total, MAX_LINES))
    target.parent.mkdir(parents=True, exist_ok=True)
    # `newline=""`: what the model wrote is what lands. `write_text` would turn every LF into CRLF on
    # Windows, so a 40-line file would read as 40 lines and diff as 40 changes.
    with open(target, "w", encoding="utf-8", newline="") as handle:
        handle.write(content)
    return "wrote %s (%d lines)" % (relative(root, target), total), \
        {"files": [relative(root, target)], "lines": total}


def listing(root, path=".", depth=1):
    target = resolve(root, path)
    if not target.is_dir():
        raise ValueError("%s is not a directory" % relative(root, target))
    rows, base_depth = [], len(target.parts)
    for current, dirs, files in os.walk(target):
        depth_now = len(Path(current).parts) - base_depth
        dirs[:] = sorted(item for item in dirs if item not in SKIP_DIRS)
        if depth_now >= int(depth):
            dirs[:] = []
            continue
        label = (relative(root, Path(current)) or ".") + "/"
        rows.append(label)
        for name in sorted(files)[:50]:
            rows.append("  %s" % name)
    return "\n".join(rows[:200]) or "(empty)", {"files": []}


def search(root, pattern, path=".", file_glob=None, limit=MAX_MATCHES):
    target = resolve(root, path)
    try:
        expression = re.compile(pattern)
    except re.error as exc:
        raise ValueError("bad regex %r: %s" % (pattern, exc)) from exc
    files = [target] if target.is_file() else [
        item for item in sorted(target.rglob("*"))
        if item.is_file() and not (SKIP_DIRS & set(item.relative_to(Path(root).resolve()).parts))
        and item.suffix.lower() not in BINARY_SUFFIXES]
    hits, touched = [], []
    for item in files:
        if file_glob and not item.match(file_glob):
            continue
        try:
            text = item.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if expression.search(line):
                hits.append("%s:%d: %s" % (relative(root, item), number, line.strip()[:200]))
                touched.append(relative(root, item))
                if len(hits) >= int(limit):
                    return "\n".join(hits) + "\n(truncated)", {"files": sorted(set(touched))}
    return ("\n".join(hits) or "(no matches)"), {"files": sorted(set(touched))}


HANDLERS = {"read_file": lambda root, args, config: read(
                root, args.get("path", "."), args.get("offset", 1), args.get("limit", MAX_READ)),
            "write_file": lambda root, args, config: write(
                root, args.get("path", ""), str(args.get("content", ""))),
            "list_dir": lambda root, args, config: listing(
                root, args.get("path", "."), args.get("depth", 1)),
            "search": lambda root, args, config: search(
                root, args.get("pattern", ""), args.get("path", "."),
                args.get("file_glob"), args.get("limit", MAX_MATCHES))}
