"""Deterministic patching: exact text, one match, and the line law enforced after the write.

Aider's format is the good idea here (`<<<<<<< SEARCH / ======= / >>>>>>> REPLACE` blocks), and so is
its whitespace tolerance. Its 0.8-similarity fallback is not: when two chunks score alike, applying
one of them silently corrupts the file. So the ladder here stops at the first rung that is still
deterministic:

1. exact match, byte for byte -- so a CRLF file stays a CRLF file;
2. exact match after normalising line endings and trailing whitespace, written back in the file's own
   newline style so the diff stays about the change;
3. refuse, and say what was looked for and how many candidates there were.

Every write is verified before it is kept: if the result would exceed the line limit, the call fails
and nothing is written. The law wins over the edit.
"""
import re

from . import files

MAX_LINES = 400
BLOCK = re.compile(r"<{5,}\s*SEARCH[^\n]*\n(.*?)\n={5,}[^\n]*\n(.*?)\n>{5,}\s*REPLACE[^\n]*", re.S)
FENCE = re.compile(r"^```[a-zA-Z0-9_+-]*$", re.M)


def normalize(text):
    """Line endings unified and trailing blanks removed: the two differences that are never semantic."""
    return "\n".join(line.rstrip() for line in str(text).replace("\r\n", "\n").split("\n"))


def newline_of(text):
    """The style the file already speaks, so patching it does not rewrite every other line."""
    return "\r\n" if text.count("\r\n") * 2 >= text.count("\n") else "\n"


def occurrences(haystack, needle):
    """Every start offset of `needle` in `haystack`, without overlapping."""
    found, start = [], haystack.find(needle)
    while start != -1:
        found.append(start)
        start = haystack.find(needle, start + max(1, len(needle)))
    return found


def line_of(text, offset):
    return text.count("\n", 0, offset) + 1


def _ambiguous(haystack, hits):
    lines = ", ".join(str(line_of(haystack, hit)) for hit in hits[:6])
    return ValueError("search text appears %d times (lines %s): include more context"
                      % (len(hits), lines))


def _locate(original, search):
    """`(offset, rung, haystack)` for exactly one match, or a `ValueError` a model can act on."""
    hits = occurrences(original, search)
    if len(hits) == 1:
        return hits[0], "exact", original
    if len(hits) > 1:
        raise _ambiguous(original, hits)
    haystack, needle = normalize(original), normalize(search)
    hits = occurrences(haystack, needle)
    if len(hits) == 1:
        return hits[0], "normalised", haystack
    if len(hits) > 1:
        raise _ambiguous(haystack, hits)
    first = search.strip().splitlines()[0][:80] if search.strip() else "(empty)"
    raise ValueError("search text not found; it starts with %r. Read the file and copy the exact "
                     "block, or use write_file for a new file." % first)


def _write(target, text):
    with open(target, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def apply_text(root, path, search, replace, max_lines=MAX_LINES):
    """`(new_text, meta)` after one replacement, or a refusal. Never partially applied."""
    target = files.resolve(root, path)
    original = target.read_text(encoding="utf-8") if target.is_file() else None
    search, replace = str(search), str(replace)
    if original is None:
        if normalize(search).strip():
            raise ValueError("%s does not exist; create it with an empty search block or write_file"
                             % files.relative(root, target))
        updated = replace
        meta = {"match": "created", "created": True}
    else:
        style = newline_of(original)
        offset, rung, haystack = _locate(original, search)
        needle = search if rung == "exact" else normalize(search)
        inserted = replace.replace("\r\n", "\n")
        if style == "\r\n":
            inserted = inserted.replace("\n", "\r\n")
        updated = haystack[:offset] + inserted + haystack[offset + len(needle):]
        if rung == "normalised" and style == "\r\n":
            updated = updated.replace("\n", "\r\n")
        meta = {"match": rung, "created": False}
    total = files.line_count(updated)
    if total > max_lines:
        raise ValueError("patch would leave %s at %d lines > %d; split the module instead"
                         % (files.relative(root, target), total, max_lines))
    target.parent.mkdir(parents=True, exist_ok=True)
    _write(target, updated)
    meta.update({"files": [files.relative(root, target)], "lines": total})
    return updated, meta


def patch(root, path, search, replace):
    _updated, meta = apply_text(root, path, search, replace)
    verb = "created" if meta["created"] else "patched"
    return ("%s %s (%d lines, %s match)"
            % (verb, meta["files"][0], meta["lines"], meta["match"]), meta)


def parse_blocks(raw):
    """Every SEARCH/REPLACE pair in a model answer, fences included or not."""
    text = FENCE.sub("", str(raw or ""))
    return [(match.group(1), match.group(2)) for match in BLOCK.finditer(text)]


def apply_blocks(root, path, raw, max_lines=MAX_LINES):
    """All blocks against one file, all-or-nothing: a failed block restores the original bytes."""
    blocks = parse_blocks(raw)
    if not blocks:
        raise ValueError("no SEARCH/REPLACE blocks found in the edit")
    target = files.resolve(root, path)
    original = target.read_text(encoding="utf-8") if target.is_file() else None
    try:
        for search, replace in blocks:
            apply_text(root, path, search, replace, max_lines)
    except ValueError:
        if original is None:
            target.unlink(missing_ok=True)
        else:
            _write(target, original)
        raise
    total = files.line_count(target.read_text(encoding="utf-8"))
    return ("applied %d block(s) to %s (%d lines)"
            % (len(blocks), files.relative(root, target), total),
            {"files": [files.relative(root, target)], "lines": total, "blocks": len(blocks)})


HANDLERS = {
    "patch": lambda root, args, config: patch(root, args.get("path", ""),
                                              str(args.get("search", "")),
                                              str(args.get("replace", ""))),
    "apply_blocks": lambda root, args, config: apply_blocks(root, args.get("path", ""),
                                                            str(args.get("blocks", ""))),
}
