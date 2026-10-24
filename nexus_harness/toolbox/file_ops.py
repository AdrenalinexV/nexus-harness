"""The floor of every write: bytes in, bytes out, and a machine that says if they parse.

Nothing above this module touches a file with `Path.write_text`. Three properties are the reason:

* **The bytes are the file's own.** `write_text` silently rewrites CRLF to CRLF-on-Windows and drops a
  BOM, so a 40-line edit shows up as 40 changed lines. Reads use `newline=""` and writes restore the
  BOM and the newline style the file already had.
* **A write either lands whole or not at all.** The text goes to a sibling temp file, is flushed to
  the disk, replaces the target with `os.replace`, and the result is re-read and hashed. A hash that
  does not match the bytes we meant to write is a failed write, not a warning.
* **Syntax is a gate, not a suggestion.** `ast.parse` / `json.loads` / `tomllib` run *before* the
  handle opens: a model that writes `def f(:` finds out from us, not from the next test run. When no
  parser exists for a language the gate abstains (`ok=True`) instead of pretending to have checked.
"""
import ast
import hashlib
import importlib
import importlib.util
import json
import os
import tomllib
from difflib import get_close_matches
from pathlib import Path

MAX_LINES = 400
BOM = "\ufeff"
SYNTAX_SUFFIXES = {".py", ".json", ".toml", ".yaml", ".yml"}
BINARY_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpeg"), (b"GIF87a", "gif"),
    (b"GIF89a", "gif"), (b"PK\x03\x04", "zip"), (b"%PDF-", "pdf"),
    (b"\x7fELF", "elf binary"), (b"MZ", "windows executable"), (b"\x1f\x8b", "gzip"),
    (b"RIFF", "riff container"), (b"OggS", "ogg"), (b"ID3", "mp3"),
)


# -- paths -----------------------------------------------------------------------------------
def resolve(root, path):
    """`path` as an absolute path inside `root`, or a `ValueError` that says why not."""
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


def newline_of(text):
    """The style the file already speaks, so an edit does not rewrite every other line."""
    return "\r\n" if text.count("\r\n") * 2 >= text.count("\n") else "\n"


# -- reading ---------------------------------------------------------------------------------
def read_raw(path):
    """`(text, had_bom)` exactly as the file is on disk, byte for byte."""
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as handle:
        text = handle.read()
    return (text[1:], True) if text.startswith(BOM) else (text, False)


def read_text(path):
    return read_raw(path)[0]


def is_binary(path, sample=4096):
    """True when the first bytes are not text: magic first, then a NUL in the sample."""
    try:
        with open(path, "rb") as handle:
            chunk = handle.read(sample)
    except OSError:
        return False
    return bool(kind_of(chunk)) or b"\x00" in chunk


def kind_of(sample):
    """`'png'`, `'windows executable'`, ... for a known magic, else `''`."""
    for magic, label in BINARY_MAGIC:
        if sample.startswith(magic):
            return label
    return ""


def describe_binary(path, size=0):
    try:
        with open(path, "rb") as handle:
            kind = kind_of(handle.read(4096)) or "binary"
            size = size or os.path.getsize(path)
    except OSError:
        kind = "binary"
    return "%s is a %s file (%d bytes); read_file only reads text" % (Path(path).name, kind, size)


def suggest_similar(target, limit=3):
    """`'(did you mean: a.py, b.py?)'` for a missing path, or `''` when nothing is close."""
    target = Path(target)
    directory = target.parent
    try:
        names = [item.name for item in directory.iterdir()]
    except OSError:
        return ""
    hits = get_close_matches(target.name, names, n=limit, cutoff=0.6)
    if not hits and directory.parent != directory:
        try:
            flat = [str(item.relative_to(directory.parent)) for item in directory.parent.rglob("*")]
        except OSError:
            flat = []
        hits = get_close_matches(target.name, [Path(name).name for name in flat],
                                 n=limit, cutoff=0.6)
    return " (did you mean: %s?)" % ", ".join(hits) if hits else ""


# -- syntax gate -----------------------------------------------------------------------------
def _json_constant(name):
    raise ValueError("invalid JSON constant %s (JSON has no NaN/Infinity)" % name)


def syntax_check(path, text):
    """`''` when the text parses (or nothing can parse this suffix), else the parser's message."""
    suffix = Path(str(path)).suffix.lower()
    if suffix not in SYNTAX_SUFFIXES:
        return ""
    try:
        if suffix == ".py":
            ast.parse(text, filename=str(path))
        elif suffix == ".json":
            json.loads(text, parse_constant=_json_constant)
        elif suffix == ".toml":
            tomllib.loads(text)
        else:
            _yaml_check(text)
    except SyntaxError as exc:
        return "SyntaxError at line %s: %s" % (exc.lineno, exc.msg)
    except ValueError as exc:
        return "%s" % exc
    except tomllib.TOMLDecodeError as exc:  # subclass of ValueError on 3.11, kept explicit
        return "TOMLDecodeError: %s" % exc
    return ""


def _yaml_check(text):
    """Structure-only. PyYAML is an optional dependency here, so when it is absent the check
    degrades to the one thing that can be proven without it: YAML forbids tab indentation."""
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("\t"):
            raise ValueError("tab indentation at line %d (YAML forbids tabs)" % number)
    if importlib.util.find_spec("yaml") is None:
        return
    yaml = importlib.import_module("yaml")
    try:
        yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError("YAML: %s" % exc)


# -- writing ---------------------------------------------------------------------------------
def atomic_write(path, text, bom=False):
    """Replace `path` with `text` atomically and return the SHA-256 of what is now on disk."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (BOM + text if bom else text).encode("utf-8")
    temporary = target.with_name(".%s.nexus-tmp" % target.name)
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    with open(target, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    if digest != hashlib.sha256(payload).hexdigest():
        raise OSError("write verification failed for %s (sha256 mismatch)" % target)
    return digest


def write(root, path, content):
    """Create or overwrite one file, under the line law and behind the syntax gate."""
    target = resolve(root, path)
    text = str(content)
    total = line_count(text)
    if total > MAX_LINES:
        raise ValueError("%s would be %d lines > %d; split the module instead"
                         % (relative(root, target), total, MAX_LINES))
    broken = syntax_check(target, text)
    if broken:
        raise ValueError("%s would not parse, so nothing was written: %s"
                         % (relative(root, target), broken))
    bom = target.is_file() and read_raw(target)[1]
    digest = atomic_write(target, text, bom=bom)
    return ("wrote %s (%d lines, sha256 %s)" % (relative(root, target), total, digest[:12]),
            {"files": [relative(root, target)], "lines": total, "sha256": digest})


def append_log(path, text):
    """Unbounded-by-line-law on purpose: logs are not modules, and they never are imported."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return target


HANDLERS = {"write_file": lambda root, args, config: write(
    root, args.get("path", ""), str(args.get("content", "")))}
