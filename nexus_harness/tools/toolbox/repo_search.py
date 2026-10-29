"""Looking through a repository: bounded results, real paths, and honest refusals.

Two rules keep this useful instead of dangerous:

* **Every path resolves inside the project root.** An agent that can read `C:\\Windows\\System32` because
  it guessed a relative path is not an agent, it is a liability.
* **Every result is bounded.** `read_file` returns numbered lines behind a limit, a search caps its
  matches and says it truncated. A tool that can return 40 000 lines is a tool that ends the session it
  was called to help.

Search is `rg` when the machine has it (native Windows paths, parallel, gitignore-aware, .nexus skipped
explicitly) and a Python walk otherwise -- same output shape either way, so the model never learns two
formats. A wrong path does not get "not found": it gets the names it probably meant, because a model
that can see the right name fixes itself in one call.
"""
import os
import re
import shutil
import subprocess

from . import file_ops

MAX_READ = 1200
MAX_MATCHES = 60
MAX_BYTES = 2_000_000
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache", ".pytest_cache",
             ".nexus/skills-dormant", ".nexus", "dist", "build", "target", ".build"}
WINDOWS_FLAGS = 0x08000000 if os.name == "nt" else 0


def _rg_binary():
    return shutil.which("rg") or shutil.which("rg.exe")


def _missing(root, target, path):
    hint = file_ops.suggest_similar(target)
    return ValueError("%s does not exist%s" % (path or ".", hint) if hint
                      else "%s does not exist under %s" % (path or ".", root))


# -- reading ---------------------------------------------------------------------------------
def read(root, path, offset=1, limit=MAX_READ):
    """Numbered lines, `offset`/`limit` paged, with a footer that says how much is left."""
    target = file_ops.resolve(root, path)
    if not target.exists():
        raise _missing(root, target, path)
    if target.is_dir():
        raise ValueError("%s is a directory; use list_dir" % file_ops.relative(root, target))
    if file_ops.is_binary(target):
        raise ValueError(file_ops.describe_binary(target))
    text = file_ops.read_raw(target)[0]
    lines = text.splitlines()
    start = max(1, int(offset or 1))
    window = lines[start - 1:start - 1 + max(1, min(int(limit or MAX_READ), MAX_READ))]
    body = "\n".join("%5d| %s" % (start + index, line) for index, line in enumerate(window))
    consumed = start - 1 + len(window)
    footer = "\n... %d more lines (offset=%d)" % (len(lines) - consumed, consumed + 1) \
        if len(lines) > consumed else ""
    return body + footer, {"files": [file_ops.relative(root, target)], "lines": len(lines)}


# -- searching -------------------------------------------------------------------------------
def _rg(root, pattern, path, file_glob, limit, context):
    """`[(file, line, text)]` from ripgrep, or `None` when rg is absent or failed for a real reason."""
    binary = _rg_binary()
    if not binary:
        return None
    command = [binary, "--line-number", "--no-heading", "--color", "never", "--max-columns", "400",
               "--max-count", str(limit)]
    if context:
        command += ["--context", str(int(context))]
    if file_glob:
        command += ["--glob", file_glob]
    for name in sorted(SKIP_DIRS):
        command += ["--glob", "!**/%s/**" % name.lstrip("./")]
    command += ["--", pattern, "."]
    try:
        completed = subprocess.run(command, cwd=str(root), capture_output=True, text=True,
                                   errors="replace", timeout=60, creationflags=WINDOWS_FLAGS)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode not in (0, 1):  # 1 = no matches; anything else is a real failure
        return None
    rows = []
    for line in (completed.stdout or "").splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0].count(".") >= 0:
            rows.append((parts[0].lstrip("./"), parts[1], parts[2]))
    return rows[:limit]


def _python_search(root, pattern, path, file_glob, limit):
    target = file_ops.resolve(root, path)
    try:
        expression = re.compile(pattern)
    except re.error as exc:
        raise ValueError("bad regex %r: %s" % (pattern, exc)) from exc
    base = root.resolve()
    roots = [target] if target.is_file() else [item for item in target.rglob("*") if item.is_file()]
    rows, seen = [], set()
    for item in sorted(roots):
        parts = set(item.relative_to(base).parts) if base in item.parents or item == base else set()
        if parts & SKIP_DIRS or not item.is_file() or item.stat().st_size > MAX_BYTES:
            continue
        if file_glob and not item.match(file_glob):
            continue
        if item.suffix.lower() in {".png", ".jpg", ".zip", ".exe", ".dll", ".pyc", ".pdf"}:
            continue
        try:
            text = item.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if expression.search(line):
                rows.append((file_ops.relative(base, item), str(number), line.strip()[:400]))
                seen.add(file_ops.relative(base, item))
                if len(rows) >= limit:
                    return rows
    return rows


def search_files(root, pattern, path=".", file_glob=None, limit=MAX_MATCHES, context=0):
    """`file:line: text` rows, capped; the schema calls this `search_files`."""
    if not str(pattern or "").strip():
        raise ValueError("pattern is empty: give a regex or a literal to look for")
    limit = max(1, min(int(limit or MAX_MATCHES), 200))
    rows = _rg(root, pattern, path, file_glob, limit, context)
    if rows is None:
        rows = _python_search(root, pattern, path, file_glob, limit)
    if not rows:
        return "(no matches)", {"files": []}
    body = "\n".join("%s:%s: %s" % row for row in rows)
    touched = sorted({row[0] for row in rows})
    if len(rows) >= limit:
        body += "\n(truncated at %d matches; narrow the pattern or raise limit)" % limit
    return body, {"files": touched}


# -- listing ---------------------------------------------------------------------------------
def list_dir(root, path=".", depth=1):
    target = file_ops.resolve(root, path)
    if not target.is_dir():
        raise ValueError("%s is not a directory" % file_ops.relative(root, target))
    rows, base_depth = [], len(target.parts)
    for current, dirs, files in os.walk(target):
        level = len(current.split(os.sep)) - base_depth
        dirs[:] = sorted(name for name in dirs if name not in SKIP_DIRS)
        if level >= int(depth or 1):
            dirs[:] = []
            continue
        rows.append((file_ops.relative(root, current) or ".") + "/")
        rows.extend("  %s" % name for name in sorted(files)[:50])
    return "\n".join(rows[:200]) or "(empty)", {"files": []}


HANDLERS = {
    "read_file": lambda root, args, config: read(
        root, args.get("path", "."), args.get("offset", 1), args.get("limit", MAX_READ)),
    "search_files": lambda root, args, config: search_files(
        root, args.get("pattern", ""), args.get("path", "."), args.get("file_glob"),
        args.get("limit", MAX_MATCHES), args.get("context", 0)),
    "list_dir": lambda root, args, config: list_dir(
        root, args.get("path", "."), args.get("depth", 1)),
}
