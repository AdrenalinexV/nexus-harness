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
from pathlib import Path

from .repair_hint import RepairHints
from .toolbox import (browser, edit, file_ops, memory_tools, patch_v4a, process_manager,
                      repo_search, shell_session, skill_tools, web)

WRITE_TOOLS = frozenset({"write_file", "patch_replace", "apply_blocks", "apply_patch"})
ROOT_HANDLERS = (repo_search.HANDLERS, file_ops.HANDLERS, edit.HANDLERS, patch_v4a.HANDLERS,
                 shell_session.HANDLERS, process_manager.HANDLERS, web.HANDLERS,
                 skill_tools.HANDLERS, browser.HANDLERS, memory_tools.HANDLERS)
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
            "the exit code comes back in the metadata. Use background for servers and long builds. "
            "Destructive commands come back refused with the rule that stopped them (policy mode "
            "`shell_policy`: read_only/standard/unrestricted).",
            {"command": {"type": "string"}, "timeout": {"type": "integer"},
             "background": {"type": "boolean"}}, ["command"]),
    _schema("process_manage",
            "Inspect or control a background process started with shell(background=true).",
            {"action": {"type": "string", "enum": ["list", "poll", "write", "kill"]},
             "session_id": {"type": "string"}, "data": {"type": "string"}}, ["action"]),
    _schema("fetch_url", "Fetch a URL and return its readable text (no browser, no API key).",
            {"url": {"type": "string"}}, ["url"]),
    _schema("browser",
            "Drive a real browser (Edge/Chrome) for pages fetch_url cannot read: JavaScript, login, "
            "cookies, anti-bot walls. Actions: goto (url), extract (text=needle), click (selector), "
            "fill (selector+text), press (text=key), links, screenshot, close, restart. Returns the "
            "visible text as markdown-ish, truncated with a receipt; a blocked page is an error, "
            "not a fake answer. The profile persists in .nexus/browser/profile.",
            {"action": {"type": "string",
                        "enum": ["goto", "extract", "click", "fill", "press", "links",
                                 "screenshot", "close", "restart"]},
             "url": {"type": "string"}, "text": {"type": "string"},
             "selector": {"type": "string"},
             "max_chars": {"type": "integer", "description": "Recorte del texto (500-40000)"}},
            ["action"]),
    _schema("recall",
            "Recall from long-term memory (episodes, learned facts, procedures) only what matches the "
            "query. Nothing is loaded unless you ask; returns the matching rows with their layer and "
            "date.",
            {"query": {"type": "string", "description": "Qué quieres recordar, en palabras"},
             "limit": {"type": "integer"}}, ["query"]),
    _schema("remember",
            "Store one durable fact or preference. `evidence` is mandatory: what did you observe that "
            "proves it (a command and its exit, a file, a user statement).",
            {"text": {"type": "string"}, "evidence": {"type": "string"},
             "kind": {"type": "string", "enum": ["core", "fact", "procedure", "episode"]},
             "confidence": {"type": "number"}}, ["text", "evidence"]),
    _schema("web_search", "Search the web and return titles with links.",
            {"query": {"type": "string"}, "limit": {"type": "integer"}}, ["query"]),
    _schema("forge_or_update_skill",
            "Write a specialist SKILL.md when you learn something critical the turn did not have. "
            "Registered with its sha256 as origin=forged; refuses to overwrite unless overwrite=true.",
            {"topic": {"type": "string", "description": "Domain or stack, e.g. 'Rust + Tauri v2'"},
             "reason": {"type": "string", "description": "Why this skill is needed now"},
             "observations": {"type": "array", "items": {"type": "string"},
                              "description": "Concrete rules observed in THIS repository"},
             "overwrite": {"type": "boolean"}}, ["topic", "reason"]),
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

    def __init__(self, root, config=None, schemas=None, handlers=None, delegate=None, stop=None,
                 mcp=None):
        self.root = root
        self.config = config
        self.mcp = mcp
        self.base_schemas = list(schemas if schemas is not None else SCHEMAS)
        self.schemas_list = list(self.base_schemas)
        self.stop = stop
        table = {}
        for module_handlers in (handlers if handlers is not None else ROOT_HANDLERS):
            table.update(module_handlers)
        self.handlers = table
        self.hints = RepairHints(Path(root))
        self.delegate = delegate
        if delegate is not None:
            self.schemas_list.append(delegate.schema())
        self.refresh_mcp()

    def refresh_mcp(self):
        """Re-read the MCP servers' tools and fold them back into the schema table."""
        self.schemas_list = list(self.base_schemas)
        if self.delegate is not None:
            self.schemas_list.append(self.delegate.schema())
        if self.mcp is not None:
            try:
                self.schemas_list.extend(self.mcp.schemas())
            except Exception:  # a broken connector must not cost the model its own tools
                return self.schemas_list
        return self.schemas_list

    def available(self, name):
        """A tool the model may call: a handler, the delegate, or a live MCP connector."""
        return (name in self.handlers or name == "delegate_task"
                or (self.mcp is not None and self.mcp.handles(name)))

    def names(self):
        return sorted(schema["function"]["name"] for schema in self.schemas_list
                      if self.available(schema["function"]["name"]))

    def schemas(self, allowed=None):
        if allowed is None:
            return [schema for schema in self.schemas_list
                    if self.available(schema["function"]["name"])]
        keep = set(allowed)
        return [schema for schema in self.schemas_list if schema["function"]["name"] in keep]

    def call(self, name, arguments):
        """Una llamada, con la pista de reparacion cuando el mismo fallo se repite."""
        observation = self._dispatch(name, arguments)
        arguments = dict(arguments or {})
        if observation.ok:
            if name in WRITE_TOOLS:
                self.hints.reset(name, arguments)
            return observation
        hint = self.hints.note(name, arguments, observation.text)
        if hint:
            observation.meta["hint"] = hint
        return observation

    def _dispatch(self, name, arguments):
        arguments = dict(arguments or {})
        try:
            if self.mcp is not None and self.mcp.handles(name):
                return Observation(ok=True, text=self.mcp.call(name, arguments),
                                   meta={"files": [], "mcp": True})
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


def default_registry(root, config=None, delegate=None, stop=None, mcp=None):
    return Registry(root, config, delegate=delegate, stop=stop, mcp=mcp)
