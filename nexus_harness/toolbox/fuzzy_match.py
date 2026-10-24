"""Locating the block a model meant, without ever guessing silently.

A model re-types text it has just read, and it re-types it with drift: one line indented two spaces
deeper, a stray trailing space, a smart quote where the file has `"`. Refusing every such edit makes the
harness unusable; accepting any approximate one corrupts files. So there is a ladder, and each rung is
still deterministic -- it either finds exactly one region or it refuses with a diagnosis:

    exact -> line_trimmed -> whitespace_normalized -> indentation_flexible
          -> trimmed_boundary -> unicode_normalized -> block_anchor -> context_aware

The first six normalise *line content* and therefore produce spans that start and end on real line
boundaries: the splice cannot shift, and `replace_all` is safe on them. The last two accept a window
whose lines merely *resemble* the search text (SequenceMatcher), so they are marked as similarity
matches: they never run under `replace_all`, and the caller is told to review the diff.

`is_already_applied` exists because a model re-sends an edit it has already landed. Rewriting the file
a second time would be a no-op at best; the honest answer is an idempotent success.
"""
import re
from difflib import SequenceMatcher

UNICODE_MAP = {
    "\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'",
    "\u2014": "--", "\u2013": "-", "\u2026": "...", "\u00a0": " ", "\u2212": "-",
    "\u2000": " ", "\u2001": " ", "\u2002": " ", "\u2003": " ", "\u2009": " ",
    "\u202f": " ", "\u3000": " ",
}
SIMILARITY = frozenset({"block_anchor", "context_aware"})
SIMILARITY_FLOOR = 0.90
MAX_HINT_WINDOWS = 4000


# -- position helpers ------------------------------------------------------------------------
def _lines_and_offsets(content):
    """`(lines, offsets)`: `offsets[i]` is the first character of line `i`."""
    lines = content.split("\n")
    offsets, cursor = [], 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line) + 1
    return lines, offsets


def _span(content, lines, offsets, start, count):
    """Character span covering `lines[start:start+count]`, newlines excluded at both ends."""
    begin = offsets[start]
    end_line = start + count
    end = (offsets[end_line] - 1) if end_line < len(lines) else len(content)
    return begin, max(begin, end)


def _unicode(text):
    for char, replacement in UNICODE_MAP.items():
        text = text.replace(char, replacement)
    return text


def _collapse(text):
    return re.sub(r"[ \t]+", " ", text)


LINE_TRANSFORMS = (
    ("line_trimmed", lambda line: line.strip()),
    ("whitespace_normalized", lambda line: _collapse(line.strip())),
    ("indentation_flexible", lambda line: line.lstrip()),
    ("trimmed_boundary", None),  # first/last stripped, middle untouched: handled separately
    ("unicode_normalized", lambda line: _unicode(line.strip())),
)


def _window_spans(content, pattern, transform, legacy=False):
    """Spans of every line window whose transformed lines equal the transformed pattern."""
    lines, offsets = _lines_and_offsets(content)
    wanted = str(pattern).split("\n")
    count = len(wanted)
    if not count or count > len(lines) + 1:
        return []
    if legacy:
        target = [wanted[0].strip()] + wanted[1:-1] + ([wanted[-1].strip()] if count > 1 else [])
        if count == 1:
            target = [wanted[0].strip()]
    else:
        target = [transform(line) for line in wanted]
    spans = []
    for start in range(0, len(lines) - count + 1):
        window = lines[start:start + count]
        got = [transform(line) if not legacy else _legacy_line(line, index, count)
               for index, line in enumerate(window)]
        if got == target:
            spans.append(_span(content, lines, offsets, start, count))
    return spans


def _legacy_line(line, index, count):
    return line.strip() if index in (0, count - 1) else line


def _exact_spans(content, pattern):
    """Every non-overlapping occurrence (str.replace semantics, not regex semantics)."""
    if not pattern:
        return []
    spans, start = [], content.find(pattern)
    while start != -1:
        spans.append((start, start + len(pattern)))
        start = content.find(pattern, start + max(1, len(pattern)))
    return spans


# -- similarity rungs ------------------------------------------------------------------------
def _block_anchor(content, pattern):
    """Anchor on the first and last line, score the middle. 0.50 unique, 0.70 otherwise."""
    wanted = pattern.split("\n")
    count = len(wanted)
    if count < 2:
        return []
    lines, offsets = _lines_and_offsets(content)
    first, last = wanted[0].strip(), wanted[-1].strip()
    candidates = [index for index in range(0, len(lines) - count + 1)
                  if lines[index].strip() == first and lines[index + count - 1].strip() == last]
    if not candidates:
        return []
    threshold = 0.50 if len(candidates) == 1 else 0.70
    middle_wanted = "\n".join(wanted[1:-1])
    spans = []
    for index in candidates:
        if count <= 2 or SequenceMatcher(None, "\n".join(lines[index + 1:index + count - 1]),
                                         middle_wanted).ratio() >= threshold:
            spans.append(_span(content, lines, offsets, index, count))
    return spans


def _context_aware(content, pattern):
    """Last resort: first/last line and every non-blank line must score >= 0.90."""
    wanted = pattern.split("\n")
    count = len(wanted)
    lines, offsets = _lines_and_offsets(content)
    if count > len(lines):
        return []

    def similar(left, right):
        return 1.0 if left == right else SequenceMatcher(None, left, right).ratio()

    spans = []
    for index in range(0, len(lines) - count + 1):
        window = lines[index:index + count]
        if similar(wanted[0].strip(), window[0].strip()) < SIMILARITY_FLOOR:
            continue
        if similar(wanted[-1].strip(), window[-1].strip()) < SIMILARITY_FLOOR:
            continue
        if all(not want.strip() or similar(want.strip(), got.strip()) >= SIMILARITY_FLOOR
               for want, got in zip(wanted, window)):
            spans.append(_span(content, lines, offsets, index, count))
    return spans


STRATEGIES = (
    ("exact", _exact_spans),
    ("line_trimmed", lambda content, pattern: _window_spans(
        content, pattern, LINE_TRANSFORMS[0][1])),
    ("whitespace_normalized", lambda content, pattern: _window_spans(
        content, pattern, LINE_TRANSFORMS[1][1])),
    ("indentation_flexible", lambda content, pattern: _window_spans(
        content, pattern, LINE_TRANSFORMS[2][1])),
    ("trimmed_boundary", lambda content, pattern: _window_spans(
        content, pattern, None, legacy=True)),
    ("unicode_normalized", lambda content, pattern: _window_spans(
        content, pattern, LINE_TRANSFORMS[4][1])),
    ("block_anchor", _block_anchor),
    ("context_aware", _context_aware),
)


# -- diagnostics -----------------------------------------------------------------------------
def is_already_applied(content, old_string, new_string):
    """True when the edit is already in the file: a re-sent edit is a success, not a rewrite."""
    fresh = (new_string or "").strip()
    if len(fresh) < 8 or new_string not in content:
        return False
    return old_string == new_string or old_string not in content


def _line_of(content, offset):
    return content.count("\n", 0, offset) + 1


def _snippet(content, start):
    line_start = content.rfind("\n", 0, start) + 1
    line_end = content.find("\n", line_start)
    text = content[line_start:(len(content) if line_end == -1 else line_end)].strip()
    return text[:77] + "..." if len(text) > 80 else text


def describe_matches(content, spans, cap=5):
    """`L12: def handler(...)` rows for an ambiguity error, capped and counted."""
    rows = ["  L%d: %s" % (_line_of(content, start), _snippet(content, start))
            for start, _end in spans[:cap]]
    if len(spans) > cap:
        rows.append("  ... and %d more" % (len(spans) - cap))
    return "\n".join(rows)


def closest_block(content, pattern, count=3):
    """The N windows that most resemble the search text, best first: the 'did you mean' hint."""
    wanted = pattern.split("\n")
    size = max(1, len(wanted))
    lines, _offsets = _lines_and_offsets(content)
    if size > len(lines):
        return ""
    scored = []
    for index in range(0, min(len(lines) - size + 1, MAX_HINT_WINDOWS)):
        candidate = "\n".join(lines[index:index + size])
        ratio = SequenceMatcher(None, candidate.strip(), pattern.strip()).ratio()
        if ratio >= 0.45:
            scored.append((ratio, index))
    if not scored:
        return ""
    scored.sort(reverse=True)
    rows = ["  L%d (%.0f%% similar): %s" % (index + 1, ratio * 100, lines[index].strip()[:90])
            for ratio, index in scored[:count]]
    return "\nclosest existing block(s):\n" + "\n".join(rows)


# -- reindentation ---------------------------------------------------------------------------
def _indent_of(line):
    return line[:len(line) - len(line.lstrip())]


def reindent(matched_region, replacement_lines):
    """Give a similarity-matched replacement the indentation of the block it replaces.

    A rung that accepts a window which merely *resembles* the search text also accepts a replacement
    that was typed without the file's indentation. Splicing it verbatim would de-indent the region and,
    in Python, break the module. The block being replaced is the authority on indentation, so its
    prefix is applied to every replacement line that does not already carry it.
    """
    indent = _indent_of(matched_region.split("\n")[0])
    if not indent:
        return replacement_lines
    return [indent + line if line.strip() and not line.startswith(indent) else line
            for line in replacement_lines]


# -- the ladder ------------------------------------------------------------------------------
def find_and_replace(content, old_string, new_string, replace_all=False, newline="\n"):
    """`(new_content, count, strategy, error)`; on failure the content is returned untouched."""
    if not old_string:
        return content, 0, None, ("old_string is empty: nothing to match. To create a file or "
                                  "rewrite one, use write_file. Do not re-send this call unchanged.")
    if not old_string.strip():
        return content, 0, None, ("old_string is only whitespace: give non-blank text to match.")
    if old_string == new_string:
        return content, 0, None, ("old_string and new_string are identical: there is no edit to "
                                  "apply. Put the text to replace in old_string.")
    for name, strategy in STRATEGIES:
        spans = strategy(content, old_string)
        if not spans and name == "exact" and newline != "\n":
            # The file is CRLF and the model typed LF: the step between lines is the only difference.
            spans = _exact_spans(content, old_string.replace("\n", newline))
        if not spans:
            continue
        if len(spans) > 1 and not replace_all:
            return content, 0, None, (
                "%s: found %d matches. Give more context so it is unique, or set replace_all.\n%s"
                % (name, len(spans), describe_matches(content, spans)))
        if len(spans) > 1 and name in SIMILARITY:
            return content, 0, None, (
                "%d approximate matches via '%s'; replace_all only applies to exact matches. "
                "Copy the precise text (whitespace included)." % (len(spans), name))
        lines_out = new_string.replace("\r\n", "\n").split("\n")
        if name in SIMILARITY:
            region = content[spans[0][0]:spans[0][1]]
            lines_out = reindent(region, lines_out)
        replacement = newline.join(lines_out)
        updated, cursor = [], 0
        for start, end in spans:
            updated.append(content[cursor:start])
            updated.append(replacement)
            cursor = end
        updated.append(content[cursor:])
        return "".join(updated), len(spans), name, None
    return content, 0, None, ("could not find a match for old_string in the file." +
                              closest_block(content, old_string))
