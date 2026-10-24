"""The arsenal: one registry, one schema shape, and a failure the model can read.

A tool is a name, a JSON schema and a handler `(root, args, config) -> (text, meta)`. The schemas are
the OpenAI shape because all three wires accept it, so there is no per-vendor tool table to drift.

Two rules are structural, not stylistic:

* **Failures are observations** (`ok=False`, text starting with the reason), never exceptions that
  escape the loop. A model that cannot see the error cannot repair it, and a traceback in the
  transcript teaches nothing.
* **Read-only calls may run concurrently.** `READ_ONLY` names them, and `parallel_reads` is the only
  place that decides it: an edit or a shell command is never dispatched beside another, because two
  writes racing on one file is the failure mode the whole gate exists to catch.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .toolbox import edit, file_ops, patch_v4a, process_manager, repo_search, shell_session, web

ROOT_HANDLERS = (repo_search.HANDLERS, file_ops.HANDLERS, edit.HANDLERS, patch_v4a.HANDLERS,
                 shell_session.HANDLERS, process_manager.HANDLERS, web.HANDLERS)
READ_ONLY = frozenset({"read_file", "search_files", "list_dir"})
MAX_PARALLEL = 4


def _schema(name, description, properties, required=None):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": required or []}}}


SCHEMAS = [
    _schema("read_file", "Read a file with line numbers. Use offset/limit on large files.",
            {"path": {"type": "string", "description": "Path relative to the project root"},
             "offset": {"type": "integer", "description": "First line (1-based)"},
             "limit": {"type": "integer", "description": "How many lines (default 1200)"}},
            ["path"]),
    _schema("write_file", "Create or overwrite a file. Refused above 400 lines: split the module.",
            {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    _schema("list_dir", "List a directory (skips .git, node_modules, .nexus, caches).",
            {"path": {"type": "string"}, "depth": {"type": "integer"}}, []),
    _schema("search_files",
            "Regex search across the project (ripgrep when available). Returns file:line: text.",
            {"pattern": {"type": "string"}, "path": {"type": "string"},
             "file_glob": {"type": "string", "description": "e.g. *.py"},
             "context": {"type": "integer", "description": "Lines of context around a match"},
             "limit": {"type": "integer"}}, ["pattern"]),
    _schema("patch_replace",
            "Replace ONE block of text. Tolerates whitespace/indentation drift; refuses when the "
            "match is ambiguous or the result would not parse.",
            {"path": {"type": "string"}, "old_string": {"type": "string"},
             "new_string": {"type": "string"},
             "replace_all": {"type": "boolean", "description": "Exact matches only"}},
            ["path", "old_string", "new_string"]),
    _schema("apply_blocks",
            "Apply several <<<<<<< SEARCH / ======= / >>>>>>> REPLACE blocks to one file, "
            "all-or-nothing.", {"path": {"type": "string"}, "blocks": {"type": "string"}},
            ["path", "blocks"]),
    _schema("apply_patch",
            "Apply a V4A patch (*** Begin Patch ... *** End Patch) with Update/Add/Delete/Move File "
            "operations and optional @@ hint @@ anchors. Multi-file, atomic, rolled back on failure.",
            {"patch": {"type": "string"}}, ["patch"]),
    _schema("shell",
            "Run a shell command in the project root. The working directory persists between calls; "
            "the exit code comes back in the metadata. Use background for servers and long builds.",
            {"command": {"type": "string"}, "timeout": {"type": "integer"},
             "background": {"type": "boolean"}}, ["command"]),
    _schema("process_manage",
            "Inspect or control a background process started with shell(background=true).",
            {"action": {"type": "string", "enum": ["list", "poll", "write", "kill"]},
             "session_id": {"type": "string"}, "data": {"type": "string"}}, ["action"]),
    _schema("fetch_url", "Fetch a URL and return its readable text (no browser, no API key).",
            {"url": {"type": "string"}}, ["url"]),
    _schema("web_search", "Search the web and return titles with links.",
            {"query": {"type": "string"}, "limit": {"type": "integer"}}, ["query"]),
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


def parallel_reads(registry, calls, stop=None, workers=MAX_PARALLEL):
    """Dispatch independent read-only calls together; everything else stays sequential.

    Returns observations in the order the model asked for them -- the transcript must not reorder
    tool results, or the `tool` messages stop matching their `tool_calls`.
    """
    pairs = list(calls)
    if len(pairs) < 2 or any(call.name not in READ_ONLY for call, _ in pairs):
        return [registry.call(call.name, call.arguments) for call, _ in pairs]

    def one(pair):
        call, _index = pair
        if stop is not None and stop.is_set():
            return Observation(ok=False, text="stopped before this read ran")
        return registry.call(call.name, call.arguments)

    with ThreadPoolExecutor(max_workers=min(workers, len(pairs))) as pool:
        return list(pool.map(one, pairs))


class Registry:
    """Name -> (schema, handler). The root is fixed for the life of a run, so paths cannot wander."""

    def __init__(self, root, config=None, schemas=None, handlers=None, delegate=None, stop=None):
        self.root = root
        self.config = config
        self.schemas_list = list(schemas if schemas is not None else SCHEMAS)
        self.stop = stop
        table = {}
        for module_handlers in (handlers if handlers is not None else ROOT_HANDLERS):
            table.update(module_handlers)
        self.handlers = table
        self.delegate = delegate
        if delegate is not None:
            self.schemas_list.append(delegate.schema())

    def names(self):
        known = {schema["function"]["name"] for schema in self.schemas_list}
        return sorted(name for name in self.handlers if name in known)

    def schemas(self, allowed=None):
        if allowed is None:
            return [schema for schema in self.schemas_list
                    if schema["function"]["name"] in self.handlers
                    or schema["function"]["name"] == "delegate_task"]
        keep = set(allowed)
        return [schema for schema in self.schemas_list if schema["function"]["name"] in keep]

    def call(self, name, arguments):
        arguments = dict(arguments or {})
        try:
            if name == "delegate_task":
                if self.delegate is None:
                    return Observation(ok=False, text="subagents are not enabled in this session")
                text, meta = self.delegate.run(arguments)
                return Observation(ok=True, text=str(text), meta=dict(meta or {}))
            handler = self.handlers.get(name)
            if handler is None:
                return Observation(ok=False, text="unknown tool %r (have: %s)"
                                   % (name, ", ".join(sorted(self.handlers))))
            text, meta = handler(self.root, arguments, self.config)
            return Observation(ok=True, text=str(text), meta=dict(meta or {}))
        except ValueError as exc:
            return Observation(ok=False, text=str(exc))
        except OSError as exc:
            return Observation(ok=False, text="%s: %s" % (type(exc).__name__, exc))
        except Exception as exc:  # a tool must never take the loop down with it
            return Observation(ok=False, text="%s failed: %s: %s"
                               % (name, type(exc).__name__, exc))


def default_registry(root, config=None, delegate=None, stop=None):
    return Registry(root, config, delegate=delegate, stop=stop)
