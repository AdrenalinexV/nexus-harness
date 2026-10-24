"""V4A patches: many files, one atomic commit, and nothing written if any part is wrong.

The format is the one Aider taught and Codex CLI inherited -- a `*** Begin Patch` envelope holding
`*** Update File`, `*** Add File`, `*** Delete File` and `*** Move File` operations, `@@ hint @@`
anchors inside an update, and `+`/`-`/space prefixes per line.

What makes it usable by a model is *two phases*, not one:

1. **Validate everything against an in-memory overlay.** Reads check the overlay first, then the disk;
   updates are simulated in order, so a hunk that a previous hunk changed sees the new text. Add and
   Move destinations are checked as *free*, and a read that failed for any reason other than
   "not found" is treated as occupied, not free -- writing over a file we could not inspect is the
   exact bug the check exists to prevent.
2. **Apply, with rollback.** Originals are kept in memory; a failure half-way restores every file
   already touched. A patch either lands whole or it does not land.

Markers are matched at column 0 only, so a content line that merely mentions `*** End Patch` cannot
truncate the patch.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import file_ops, fuzzy_match

BEGIN = re.compile(r"^\*\*\*\s*Begin\s+Patch\s*$")
END = re.compile(r"^\*\*\*\s*End\s+Patch\s*$")
HINT = re.compile(r"@@\s*(.+?)\s*@@")
OPERATIONS = (
    ("update", re.compile(r"^\*\*\*\s*Update\s+File:\s*(.+)")),
    ("add", re.compile(r"^\*\*\*\s*Add\s+File:\s*(.+)")),
    ("delete", re.compile(r"^\*\*\*\s*Delete\s+File:\s*(.+)")),
    ("move", re.compile(r"^\*\*\*\s*Move\s+File:\s*(.+?)\s*->\s*(.+)")),
)


@dataclass
class Hunk:
    hint: str = ""
    lines: list = field(default_factory=list)  # [(prefix, content)]


@dataclass
class Operation:
    kind: str
    path: str
    destination: str = ""
    hunks: list = field(default_factory=list)


@dataclass
class PatchResult:
    ok: bool = False
    text: str = ""
    created: list = field(default_factory=list)
    modified: list = field(default_factory=list)
    deleted: list = field(default_factory=list)

    def as_meta(self):
        files = sorted(set(self.created + self.modified + self.deleted))
        return {"files": files, "created": self.created, "modified": self.modified,
                "deleted": self.deleted}


# -- parsing ---------------------------------------------------------------------------------
def parse(patch_text):
    """`(operations, error)`: an empty patch is `([], '')`, never a crash."""
    raw = [line.removesuffix("\r") for line in str(patch_text or "").split("\n")]
    start, end = -1, len(raw)
    for index, line in enumerate(raw):
        if BEGIN.match(line):
            start = index
        elif END.match(line):
            end = index
            break
    operations, current, hunk = [], None, None

    def flush():
        if current is not None and hunk is not None and hunk.lines:
            current.hunks.append(hunk)

    for line in raw[start + 1:end]:
        matched = next(((kind, match) for kind, pattern in OPERATIONS
                        if (match := pattern.match(line))), None)
        if matched:
            flush()
            kind, match = matched
            current = Operation(kind, match.group(1).strip(),
                                match.group(2).strip() if kind == "move" else "")
            hunk = Hunk() if kind == "add" else None
            operations.append(current)
            if kind in ("delete", "move"):
                current = None
        elif line.startswith("@@"):
            if current is not None:
                flush()
                found = HINT.match(line)
                hunk = Hunk(found.group(1) if found else "")
        elif current is not None and line:
            if hunk is None:
                hunk = Hunk()
            if line[0] in "+- ":
                hunk.lines.append((line[0], line[1:]))
            elif line[0] != "\\":
                hunk.lines.append((" ", line))
    flush()
    problems = []
    for operation in operations:
        if not operation.path:
            problems.append("an operation has an empty file path")
        elif operation.kind == "update" and not operation.hunks:
            problems.append("UPDATE %r has no hunks" % operation.path)
        elif operation.kind == "move" and not operation.destination:
            problems.append("MOVE %r has no destination (expected 'src -> dst')" % operation.path)
    return ([], "patch parse error: " + "; ".join(problems)) if problems else (operations, "")


def _split(hunk):
    search = [content for prefix, content in hunk.lines if prefix != "+"]
    replace = [content for prefix, content in hunk.lines if prefix != "-"]
    return search, replace


# -- validation ------------------------------------------------------------------------------
class _Overlay:
    """What the disk will look like when the operation being validated gets its turn."""

    def __init__(self, root):
        self.root = root
        self.pending = {}
        self.removed = set()

    def read(self, path):
        if path in self.pending:
            return self.pending[path], ""
        if path in self.removed:
            return None, "file does not exist (deleted earlier in this patch)"
        target = file_ops.resolve(self.root, path)
        if not target.is_file():
            return None, "file does not exist"
        return file_ops.read_raw(target)[0], ""

    def free(self, path):
        """`''` when the path is free for writing, else why it is not. Failure is not freedom."""
        if path in self.pending:
            return "destination already exists in this patch"
        if path in self.removed:
            return ""
        target = file_ops.resolve(self.root, path)
        if target.exists():
            return "destination already exists"
        parent = target.parent
        return "" if parent.is_dir() or not parent.exists() else \
            "cannot confirm the path is free (%s is a file)" % parent

    def write(self, path, content):
        self.pending[path] = content
        self.removed.discard(path)

    def remove(self, path):
        self.removed.add(path)
        self.pending.pop(path, None)


def _apply_hunk(content, hunk, newline):
    """`(content, error)` for one hunk, or `(content, None)` when it was already applied."""
    search, replace = _split(hunk)
    if search and search == replace:
        return content, None
    if not search:
        return _insert_after_hint(content, hunk.hint, replace, newline)
    updated, count, _strategy, error = fuzzy_match.find_and_replace(
        content, "\n".join(search), "\n".join(replace), newline=newline)
    if error and fuzzy_match.is_already_applied(content, "\n".join(search), "\n".join(replace)):
        return content, None
    return (updated, None) if not error else (content, "hunk failed: " + error)


def _insert_after_hint(content, hint, lines, newline):
    """An addition-only hunk lands after its hint line, or at EOF when the hint is absent."""
    addition = newline.join(lines)
    if hint:
        hits = content.count(hint)
        if hits > 1:
            return content, ("addition-only hunk: context hint %r is ambiguous (%d occurrences)"
                             % (hint, hits))
        if hits == 1:
            anchor = content.find(hint)
            eol = content.find("\n", anchor)
            if eol == -1:
                return content + newline + addition + newline, None
            return content[:eol + 1] + addition + newline + content[eol + 1:], None
    return content.rstrip("\r\n") + newline + addition + newline, None


def _update(content, operation, newline):
    for hunk in operation.hunks:
        content, error = _apply_hunk(content, hunk, newline)
        if error:
            return None, "%s: %s" % (operation.path, error)
    return content, ""


def validate(operations, root):
    """Every operation dry-run against the overlay. `[errors]`, empty means safe to write."""
    overlay, errors = _Overlay(root), []
    for operation in operations:
        if operation.kind == "add":
            reason = overlay.free(operation.path)
            if reason:
                errors.append("ADD %r: %s -- use Update File" % (operation.path, reason))
                continue
            overlay.write(operation.path, "\n".join(
                content for hunk in operation.hunks for prefix, content in hunk.lines
                if prefix == "+"))
        elif operation.kind == "delete":
            content, error = overlay.read(operation.path)
            if error:
                errors.append("DELETE %r: %s" % (operation.path, error))
            else:
                overlay.remove(operation.path)
        elif operation.kind == "move":
            content, error = overlay.read(operation.path)
            free = overlay.free(operation.destination)
            if error:
                errors.append("MOVE %r: %s" % (operation.path, error))
            elif free:
                errors.append("MOVE %r -> %r: %s" % (operation.path, operation.destination, free))
            else:
                overlay.remove(operation.path)
                overlay.write(operation.destination, content)
        else:
            content, error = overlay.read(operation.path)
            if error:
                errors.append("UPDATE %r: %s" % (operation.path, error))
                continue
            updated, error = _update(content, operation, file_ops.newline_of(content))
            if error:
                errors.append(error)
            else:
                overlay.write(operation.path, updated)
    return errors


# -- applying --------------------------------------------------------------------------------
def apply(root, patch_text):
    """Validate, then apply with rollback. Returns a `PatchResult`; never leaves a half patch."""
    operations, error = parse(patch_text)
    if error:
        return PatchResult(False, error)
    if not operations:
        return PatchResult(False, "the patch contains no operations")
    errors = validate(operations, root)
    if errors:
        return PatchResult(False, "patch validation failed, no files were modified:\n"
                           + "\n".join("  - %s" % item for item in errors))
    outcome, originals, notes = PatchResult(ok=True), {}, []
    try:
        for operation in operations:
            _commit(root, operation, outcome, originals, notes)
    except (ValueError, OSError) as exc:
        _rollback(root, originals)
        return PatchResult(False, "patch failed and was rolled back: %s" % exc)
    pieces = ["%d created, %d modified, %d deleted" % (len(outcome.created),
                                                       len(outcome.modified),
                                                       len(outcome.deleted))]
    if notes:
        pieces.extend(notes)
    outcome.text = "; ".join(pieces)
    return outcome


def _remember(root, path, originals):
    """Snapshot the file's bytes and BOM before the first operation that touches it."""
    target = file_ops.resolve(root, path)
    if path not in originals:
        originals[path] = file_ops.read_raw(target) if target.is_file() else None


def _commit(root, operation, outcome, originals, notes):
    """One operation, on disk. Raises on anything the validation phase did not foresee."""
    resolved = file_ops.resolve(root, operation.path)
    if operation.kind == "add":
        text = "\n".join(content for hunk in operation.hunks
                         for prefix, content in hunk.lines if prefix == "+")
        _remember(root, operation.path, originals)
        file_ops.write(root, operation.path, text)
        outcome.created.append(file_ops.relative(root, resolved))
        return
    if operation.kind == "delete":
        _remember(root, operation.path, originals)
        resolved.unlink()
        outcome.deleted.append(file_ops.relative(root, resolved))
        return
    if operation.kind == "move":
        _remember(root, operation.path, originals)
        text, bom = file_ops.read_raw(resolved)
        file_ops.atomic_write(file_ops.resolve(root, operation.destination), text, bom=bom)
        resolved.unlink()
        outcome.modified.append("%s -> %s" % (file_ops.relative(root, resolved),
                                              operation.destination))
        return
    _remember(root, operation.path, originals)
    content, bom = file_ops.read_raw(resolved)
    updated, error = _update(content, operation, file_ops.newline_of(content))
    if error:
        raise ValueError(error)
    broken = file_ops.syntax_check(resolved, updated)
    if broken:
        raise ValueError("%s would not parse: %s" % (operation.path, broken))
    file_ops.atomic_write(resolved, updated, bom=bom)
    outcome.modified.append(file_ops.relative(root, resolved))
    matched = [hint for hunk in operation.hunks for hint in [hunk.hint] if hint]
    if matched:
        notes.append("anchors used: %s" % ", ".join(matched[:4]))


def _rollback(root, originals):
    """Put every file this patch touched back the way it was."""
    for path, snapshot in originals.items():
        target = file_ops.resolve(root, path)
        try:
            if snapshot is None:
                target.unlink(missing_ok=True)
            else:
                file_ops.atomic_write(target, snapshot[0], bom=snapshot[1])
        except OSError:
            continue


def apply_patch(root, patch_text):
    """Toolbox handler body: a `PatchResult` rendered as text and metadata."""
    result = apply(root, patch_text)
    return result.text, result.as_meta() if result.ok else {"files": []}


HANDLERS = {"apply_patch": lambda root, args, config: apply_patch(
    root, str(args.get("patch", args.get("content", "")) or ""))}
