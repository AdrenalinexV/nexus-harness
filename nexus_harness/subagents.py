"""Subagents: the work that would flood the Director's context, done in another window.

A subagent is not a second harness. It is the same provider, a *smaller* toolset and a closed history:
it reads, searches and summarizes, and only its summary comes back. That is the whole point -- a repo
with 200 files cannot be pasted into one context, but "find every caller of X and tell me what breaks"
fits in four lines once somebody else has read them.

Four decisions, and each one exists because its absence is a known failure:

* **Parallel by default** (`tasks=[...]` -> one thread each), because three independent reads that take
  20 s each are 20 s of work, not 60. The pool is bounded by `config.max_children`.
* **Bounded turns** (`config.subagent_steps`), because a child that loops forever is a parent that never
  answers.
* **Cancellation is inherited** from the same `threading.Event` as the Detener button, and it is checked
  between steps: stopping must not wait for a child to finish thinking.
* **Depth is one** -- a child cannot delegate -- so the fan-out cannot become a fork bomb.

Isolation is optional and honest: with `isolate=True` the child works inside a real `git worktree`, so
its edits cannot race the Director's. When git cannot create the worktree the task fails with git's own
message rather than pretending to be isolated.
"""
import os
import subprocess
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .core.message import Message
from .tools import SCHEMAS, ROOT_HANDLERS, Registry

SUBAGENT_SYSTEM = """Eres un subagente de investigación de Nexus-Harness. Trabajas en una ventana de
contexto aislada: el Director no verá tus lecturas, solo tu resumen final.

Reglas:
- Inspecciona con `read_file`, `search_files` y `list_dir` antes de concluir nada.
- No inventes: si no lo has leído, di que no lo has visto.
- Cuando termines, responde en <=120 palabras: qué has encontrado, qué ficheros importan y qué
  debería hacer el Director. Sin preámbulo, sin ofertas de ayuda."""

READ_TOOLS = ("read_file", "search_files", "list_dir", "fetch_url", "web_search")
EDIT_TOOLS = ("patch_replace", "apply_patch", "apply_blocks", "write_file", "shell")
WINDOWS_FLAGS = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


@dataclass
class ChildResult:
    index: int
    goal: str = ""
    ok: bool = True
    summary: str = ""
    steps: int = 0
    files: list = field(default_factory=list)
    worktree: str = ""
    error: str = ""

    def render(self):
        head = "child %d [%s]" % (self.index, "ok" if self.ok else "failed")
        body = self.summary or self.error or "(no summary)"
        line = "%s: %s" % (head, body)
        if self.files:
            line += "\n  files: %s" % ", ".join(self.files[:12])
        if self.worktree:
            line += "\n  worktree: %s" % self.worktree
        return line


class Delegate:
    """`delegate_task` as a tool: one task or a batch, in parallel, with a closed history each."""

    def __init__(self, router, config, stop=None, bus=None, root=None, depth=0):
        self.router = router
        self.config = config
        self.stop = stop or threading.Event()
        self.bus = bus
        self.root = Path(root or getattr(config, "default_root", "."))
        self.depth = int(depth)

    # -- schema ------------------------------------------------------------------------------
    def schema(self):
        task = {"type": "object", "properties": {
            "goal": {"type": "string", "description": "What this child must find out or do"},
            "context": {"type": "string", "description": "Background the child needs"},
            "allow_edit": {"type": "boolean", "description": "Give it the editing tools too"}},
            "required": ["goal"]}
        return {"type": "function", "function": {
            "name": "delegate_task",
            "description": ("Delegate to isolated subagents that run in parallel and return only their "
                            "summary. Use it for reading-heavy or independent work; never for a single "
                            "file you could read yourself."),
            "parameters": {"type": "object", "properties": {
                "goal": {"type": "string", "description": "Single-task shorthand"},
                "context": {"type": "string"},
                "tasks": {"type": "array", "items": task,
                          "description": "Independent tasks, one child each, run in parallel"},
                "isolate": {"type": "boolean",
                            "description": "Run each child inside its own git worktree"}},
                "required": []}}}

    # -- entry point -------------------------------------------------------------------------
    def run(self, args):
        tasks = self._tasks(args)
        if self.depth >= int(getattr(self.config, "subagent_depth", 1)):
            raise ValueError("delegation depth %d reached: children cannot delegate" % self.depth)
        isolate = bool(args.get("isolate"))
        limit = max(1, min(int(getattr(self.config, "max_children", 3)), len(tasks)))
        self._emit("subagent.start", "%d task(s), %d in parallel" % (len(tasks), limit),
                   tasks=[task["goal"][:120] for task in tasks])
        results = self._dispatch(tasks, min(limit, len(tasks)), isolate)
        touched = sorted({name for result in results for name in result.files})
        text = "\n\n".join(result.render() for result in results)
        self._emit("subagent.end", "%d/%d ok" % (sum(1 for r in results if r.ok), len(results)),
                   files=touched)
        return text, {"files": touched,
                      "children": [{"index": r.index, "ok": r.ok, "steps": r.steps,
                                    "worktree": r.worktree} for r in results]}

    def _tasks(self, args):
        raw = args.get("tasks")
        if isinstance(raw, list) and raw:
            tasks = [{"goal": str(item.get("goal") or ""), "context": str(item.get("context") or ""),
                      "allow_edit": bool(item.get("allow_edit"))}
                     for item in raw if isinstance(item, dict) and str(item.get("goal") or "").strip()]
            if not tasks:
                raise ValueError("tasks is a list but no entry has a non-empty goal")
            return tasks[:8]
        goal = str(args.get("goal") or "").strip()
        if not goal:
            raise ValueError("delegate_task needs `goal` or a non-empty `tasks` list")
        return [{"goal": goal, "context": str(args.get("context") or ""), "allow_edit": False}]

    def _dispatch(self, tasks, workers, isolate):
        if workers <= 1:
            return [self._one(index, task, isolate) for index, task in enumerate(tasks, 1)]
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="subagent") as pool:
            futures = [pool.submit(self._one, index, task, isolate)
                       for index, task in enumerate(tasks, 1)]
            return [future.result() for future in futures]

    # -- one child ---------------------------------------------------------------------------
    def _one(self, index, task, isolate):
        result = ChildResult(index=index, goal=task["goal"])
        try:
            root = self._worktree(index) if isolate else self.root
            if isolate:
                result.worktree = str(root)
            self._loop(index, task, root, result)
        except (ValueError, OSError, RuntimeError) as exc:
            result.ok, result.error = False, "%s: %s" % (type(exc).__name__, exc)
        self._emit("subagent.result", "child %d %s" % (index, "ok" if result.ok else "failed"),
                   child=result.render()[:600])
        return result

    def _tools(self, allow_edit):
        wanted = set(READ_TOOLS) | (set(EDIT_TOOLS) if allow_edit else set())
        return [schema for schema in SCHEMAS if schema["function"]["name"] in wanted]

    def _loop(self, index, task, root, result):
        registry = Registry(root, self.config, schemas=self._tools(task["allow_edit"]),
                            handlers=ROOT_HANDLERS, stop=self.stop)
        messages = [Message(role="system", content=SUBAGENT_SYSTEM),
                    Message(role="user", content=self._brief(task, root))]
        steps = max(1, int(getattr(self.config, "subagent_steps", 8)))
        for _step in range(steps):
            if self.stop.is_set():
                result.summary = result.summary or "(stopped by the operator)"
                return
            reply = self.router.role("worker").chat(
                messages, tools=registry.schemas(), temperature=self.config.temperature,
                max_tokens=min(int(self.config.max_tokens), 1600))
            result.steps += 1
            messages.append(reply.as_message())
            if reply.text:
                result.summary = reply.text
            if not reply.wants_tools:
                return
            for call in reply.tool_calls:
                observation = (registry.call(call.name, call.arguments) if not call.parse_error
                               else _bad(call))
                result.files = sorted(set(result.files) | set(observation.files))
                messages.append(Message(role="tool", content=_text(observation),
                                        tool_call_id=call.id, name=call.name))
                self._emit("subagent.tool", "child %d -> %s" % (index, call.name),
                           ok=observation.ok, result=observation.text[:400])
        self._emit("subagent.limit", "child %d used %d steps" % (index, steps))

    def _brief(self, task, root):
        lines = ["OBJETIVO:", task["goal"]]
        if task.get("context"):
            lines += ["", "CONTEXTO:", task["context"]]
        lines += ["", "RAÍZ DEL PROYECTO: %s" % root]
        if self.depth:  # a nested child is told so, and has no delegate tool anyway
            lines += ["", "(nivel de delegación %d)" % self.depth]
        return "\n".join(lines)

    # -- git worktree ------------------------------------------------------------------------
    def _worktree(self, index):
        """A real `git worktree` for this child, or an error that says why not."""
        base = self.root / ".nexus" / "harness" / "worktrees"
        base.mkdir(parents=True, exist_ok=True)
        target = base / ("child-%d-%s" % (index, uuid.uuid4().hex[:6]))
        completed = subprocess.run(
            ["git", "worktree", "add", "--detach", str(target), "HEAD"], cwd=str(self.root),
            capture_output=True, text=True, errors="replace", timeout=120,
            creationflags=WINDOWS_FLAGS)
        if completed.returncode != 0:
            raise RuntimeError("git worktree add failed: %s"
                               % ((completed.stderr or completed.stdout or "").strip()[:300]))
        return target

    def _emit(self, kind, detail="", **payload):
        if self.bus is not None:
            self.bus.emit(kind, detail, **payload)


def _text(observation):
    return ("ok: " if observation.ok else "error: ") + observation.text


def _bad(call):
    from .tools import Observation
    return Observation(ok=False, text="tool arguments are unusable: %s" % call.parse_error)
