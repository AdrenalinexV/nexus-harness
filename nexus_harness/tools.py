"""The arsenal: one registry, nine actions, and a failure the model can read.

A tool is a name, a JSON schema and a callable. The schemas are the OpenAI shape because all three
wires accept it, so there is no per-vendor tool table to drift.

Failures are observations (`ok=False`, text starting with the reason), never exceptions that escape
the loop: a model that cannot see the error cannot repair it, and a traceback in the transcript
teaches nothing.
"""
from dataclasses import dataclass, field

from .toolbox import edit, files, shell, web

ROOT_HANDLERS = (files.HANDLERS, edit.HANDLERS, shell.HANDLERS, web.HANDLERS)

SCHEMAS = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a file with line numbers. Use offset/limit on large files.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Path relative to the project root"},
            "offset": {"type": "integer", "description": "First line (1-based)"},
            "limit": {"type": "integer", "description": "How many lines (default 1200)"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or overwrite a file. Refused above 400 lines: split the module.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "list_dir",
        "description": "List a directory (skips .git, node_modules, caches).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "depth": {"type": "integer"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "search",
        "description": "Regex search across the project. Returns file:line: text, capped.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"}, "path": {"type": "string"},
            "file_glob": {"type": "string", "description": "e.g. *.py"},
            "limit": {"type": "integer"}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "patch",
        "description": ("Replace ONE exact block of text. The search text must appear exactly once "
                        "and byte-for-byte; wrong indentation or two matches is an error, not a "
                        "guess."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "search": {"type": "string"},
            "replace": {"type": "string"}},
            "required": ["path", "search", "replace"]}}},
    {"type": "function", "function": {
        "name": "apply_blocks",
        "description": ("Apply several <<<<<<< SEARCH / ======= / >>>>>>> REPLACE blocks to one file, "
                        "all-or-nothing."),
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "blocks": {"type": "string"}},
            "required": ["path", "blocks"]}}},
    {"type": "function", "function": {
        "name": "shell",
        "description": ("Run a shell command in the project root. Returns output and the exit code; "
                        "destructive shapes are refused."),
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"}, "timeout": {"type": "integer"}},
            "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "fetch_url",
        "description": "Fetch a URL and return its readable text (no browser, no API key).",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}},
                       "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the web and return titles with links.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["query"]}}},
]


@dataclass
class Observation:
    """What a tool saw. `meta` carries the exit code and the files the call touched."""

    ok: bool = True
    text: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def files(self):
        return list(self.meta.get("files") or [])


class Registry:
    """Name -> (schema, handler). The root is fixed for the life of a run, so paths cannot wander."""

    def __init__(self, root, config=None, schemas=None, handlers=None):
        self.root = root
        self.config = config
        self.schemas_list = list(schemas if schemas is not None else SCHEMAS)
        table = {}
        for module_handlers in (handlers if handlers is not None else ROOT_HANDLERS):
            table.update(module_handlers)
        self.handlers = table

    def names(self):
        return sorted(name for name in self.handlers
                      if name in {schema["function"]["name"] for schema in self.schemas_list})

    def schemas(self, allowed=None):
        if allowed is None:
            return [schema for schema in self.schemas_list
                    if schema["function"]["name"] in self.handlers]
        keep = set(allowed)
        return [schema for schema in self.schemas_list if schema["function"]["name"] in keep]

    def call(self, name, arguments):
        handler = self.handlers.get(name)
        if handler is None:
            return Observation(ok=False, text="unknown tool %r (have: %s)"
                               % (name, ", ".join(self.names())))
        try:
            text, meta = handler(self.root, dict(arguments or {}), self.config)
            return Observation(ok=True, text=str(text), meta=dict(meta or {}))
        except ValueError as exc:
            return Observation(ok=False, text=str(exc))
        except OSError as exc:
            return Observation(ok=False, text="%s: %s" % (type(exc).__name__, exc))
        except Exception as exc:  # a tool must never take the loop down with it
            return Observation(ok=False, text="%s failed: %s" % (name, exc))


def default_registry(root, config=None):
    return Registry(root, config)
