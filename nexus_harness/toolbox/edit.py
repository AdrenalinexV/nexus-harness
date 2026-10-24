"""The edit tools: one block, many blocks, or a whole V4A patch -- each verified before it lands.

Every path here ends in `file_ops.atomic_write`, which means every edit passes the same three doors:
the line law, the syntax gate, and a SHA-256 re-read. None of them is optional and none can be skipped
by a tool argument, because the one thing an autonomous editor must not have is a way to disable its
own verification.

The order inside one edit is deliberate:

1. **already applied?** A re-sent edit returns an idempotent success without touching the file.
2. **find exactly one region** via `fuzzy_match`'s ladder, or refuse with the closest blocks.
3. **rewrite in the file's own newline style**, keeping a BOM if it had one.
4. **prove the result**: line law, parser, bytes on disk.
"""
import re

from . import file_ops, fuzzy_match

MAX_LINES = file_ops.MAX_LINES
BLOCK = re.compile(r"<{5,}\s*SEARCH[^\n]*\n(.*?)\n={5,}[^\n]*\n(.*?)\n>{5,}\s*REPLACE[^\n]*", re.S)
FENCE = re.compile(r"^```[a-zA-Z0-9_+-]*$", re.M)
CREATE_HINT = ("%s does not exist. Use write_file, or pass an empty old_string with the full "
               "content of the new file.")


def _guard(root, target, text):
    """The three doors, in order: line law, syntax, then the write itself."""
    total = file_ops.line_count(text)
    if total > MAX_LINES:
        raise ValueError("%s would be %d lines > %d; split the module instead"
                         % (file_ops.relative(root, target), total, MAX_LINES))
    broken = file_ops.syntax_check(target, text)
    if broken:
        raise ValueError("%s would not parse, so nothing was written: %s"
                         % (file_ops.relative(root, target), broken))
    bom = target.is_file() and file_ops.read_raw(target)[1]
    return file_ops.atomic_write(target, text, bom=bom), total


def patch_replace(root, path, old_string, new_string, replace_all=False):
    """Replace one block (or every exact one). `(text, meta)`; raises `ValueError` to refuse."""
    target = file_ops.resolve(root, path)
    original = file_ops.read_raw(target)[0] if target.is_file() else None
    old_string, new_string = str(old_string or ""), str(new_string or "")
    if original is None:
        if old_string.strip():
            raise ValueError(CREATE_HINT % file_ops.relative(root, target))
        digest, total = _guard(root, target, new_string)
        return ("created %s (%d lines, sha256 %s)"
                % (file_ops.relative(root, target), total, digest[:12]),
                {"files": [file_ops.relative(root, target)], "lines": total, "match": "created",
                 "sha256": digest})
    if fuzzy_match.is_already_applied(original, old_string, new_string):
        return ("no change needed: %s already contains that text (idempotent)"
                % file_ops.relative(root, target),
                {"files": [file_ops.relative(root, target)], "match": "already_applied",
                 "lines": file_ops.line_count(original)})
    updated, count, strategy, error = fuzzy_match.find_and_replace(
        original, old_string, new_string, replace_all=bool(replace_all),
        newline=file_ops.newline_of(original))
    if error:
        raise ValueError(error)
    digest, total = _guard(root, target, updated)
    text = ("patched %s (%d lines, %s match x%d, sha256 %s)"
            % (file_ops.relative(root, target), total, strategy, count, digest[:12]))
    if strategy in fuzzy_match.SIMILARITY:
        text += ("\nnote: the span was located approximately by '%s' -- review the diff, a "
                 "shifted boundary can duplicate or drop a line next to the edit." % strategy)
    return text, {"files": [file_ops.relative(root, target)], "lines": total, "match": strategy,
                  "replacements": count, "sha256": digest}


def parse_blocks(raw):
    """Every SEARCH/REPLACE pair in a model answer, fences stripped."""
    return [(match.group(1), match.group(2))
            for match in BLOCK.finditer(FENCE.sub("", str(raw or "")))]


def apply_blocks(root, path, raw, max_lines=MAX_LINES):
    """Aider's multi-block edit against one file, all-or-nothing on the original bytes."""
    blocks = parse_blocks(raw)
    if not blocks:
        raise ValueError("no SEARCH/REPLACE blocks found: expected <<<<<<< SEARCH ... "
                         "======= ... >>>>>>> REPLACE")
    target = file_ops.resolve(root, path)
    snapshot = file_ops.read_raw(target) if target.is_file() else None
    try:
        for old, new in blocks:
            patch_replace(root, path, old, new)
    except ValueError:
        if snapshot is None:
            target.unlink(missing_ok=True)
        else:
            file_ops.atomic_write(target, snapshot[0], bom=snapshot[1])
        raise
    total = file_ops.line_count(file_ops.read_raw(target)[0])
    return ("applied %d block(s) to %s (%d lines)"
            % (len(blocks), file_ops.relative(root, target), total),
            {"files": [file_ops.relative(root, target)], "lines": total, "blocks": len(blocks)})


HANDLERS = {
    "patch_replace": lambda root, args, config: patch_replace(
        root, args.get("path", ""), args.get("old_string", args.get("search", "")),
        str(args.get("new_string", args.get("replace", ""))), args.get("replace_all", False)),
    "apply_blocks": lambda root, args, config: apply_blocks(
        root, args.get("path", ""), str(args.get("blocks", ""))),
}
