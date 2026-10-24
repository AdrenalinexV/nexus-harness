"""The mobile bridge: a `/task` sent from a phone becomes a run of this harness.

The protocol already owns the queue (`nexus/hive/queue.py`): the remote listener writes an item with
`state: queued`, and nothing on that side is allowed to start it. This module is the side that may:

1. read the open items of the workspace queue (read-only until claimed);
2. claim ONE at a time (`max_workers` is a cap, not a suggestion) by marking it `dispatched`;
3. run it through the triad on the project the item names;
4. close it with the exit code the gate actually observed.

An item is never closed green because the run returned: the exit code stored is the one `Triad.run`
produced, so a red gate stays visible in the queue the phone reads.
"""
import os
import sys
from pathlib import Path

NEXUS_SOURCE = Path(os.environ.get("NEXUS_PROTOCOL") or r"C:\Proyectos\NexusProtocol")
MAX_WORKERS = 1


def _queue():
    if str(NEXUS_SOURCE) not in sys.path:
        sys.path.insert(0, str(NEXUS_SOURCE))
    try:
        from nexus.hive import queue
        return queue
    except ImportError:
        return None


def _fleet_projects(home=None):
    """name -> path from the fleet index, so a queue item can name a project, not a path."""
    import json
    location = Path(home) if home else Path(os.environ.get("NEXUS_HOME") or (Path.home() / ".nexus"))
    try:
        data = json.loads((location / "fleet.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = data.get("projects") or []
    return {str(row.get("name") or "").lower(): str(row.get("path") or "")
            for row in rows if row.get("name") and row.get("path")}


class Bridge:
    def __init__(self, workspace, home=None, bus=None, max_workers=MAX_WORKERS):
        self.workspace = Path(workspace)
        self.home = home
        self.bus = bus
        self.max_workers = max(1, int(max_workers))
        self.runs = []

    @property
    def available(self):
        return _queue() is not None

    def _emit(self, kind, detail="", **payload):
        if self.bus is not None:
            self.bus.emit(kind, detail, **payload)

    def pending(self, limit=10):
        module = _queue()
        if module is None:
            return []
        items = module.open_items(module.load(str(self.workspace)))
        return [{"project": item.get("project"), "criterion": item.get("criterion"),
                 "state": item.get("state"), "created_at": item.get("created_at")}
                for item in items[:limit]]

    def resolve(self, project):
        """Where that project name lives: inside the workspace, or wherever the fleet index says."""
        name = str(project or "").strip()
        if not name:
            return None
        direct = Path(name)
        if direct.is_absolute() and direct.is_dir():
            return direct
        inside = self.workspace / name
        if inside.is_dir():
            return inside
        known = _fleet_projects(self.home).get(name.lower())
        if known and Path(known).is_dir():
            return Path(known)
        return None

    def tick(self, runner):
        """Claim and run what fits under the cap. Returns one row per item attempted."""
        module = _queue()
        if module is None:
            return [{"ok": False, "reason": "nexus queue not importable"}]
        state = module.load(str(self.workspace))
        open_items = module.open_items(state)
        free = self.max_workers - len(module.dispatched(state))
        rows = []
        for item in open_items[:max(0, free)]:
            root = self.resolve(item.get("project"))
            if root is None:
                rows.append({"ok": False, "project": item.get("project"),
                             "reason": "project not found under %s" % self.workspace})
                continue
            module.dispatch(state, item)
            module.save(str(self.workspace), state)
            self._emit("bridge.claim", "%s: %s" % (item.get("project"),
                                                   str(item.get("criterion"))[:80]),
                       project=str(root))
            try:
                exit_code = int(runner(str(item.get("criterion") or ""), root))
            except Exception as exc:  # a crashing runner closes red, it does not stay dispatched
                self._emit("bridge.error", "%s: %s" % (type(exc).__name__, exc))
                exit_code = 10
            _close_item(item, exit_code)
            module.save(str(self.workspace), state)
            row = {"ok": exit_code == 0, "project": item.get("project"),
                   "criterion": item.get("criterion"), "exit": exit_code,
                   "root": str(root)}
            self.runs.append(row)
            self._emit("bridge.close", "exit %s" % exit_code, **row)
            rows.append(row)
            break  # one per tick: two workers on one repository is the failure mode
        return rows

    def status(self):
        return {"available": self.available, "workspace": str(self.workspace),
                "max_workers": self.max_workers, "pending": self.pending(),
                "runs": self.runs[-5:]}


def _close_item(item, exit_code):
    """Close THIS item, not every open item of the project.

    `nexus.hive.queue.close()` closes all of a project's open items, which is right for a worker that
    takes a repository and wrong here: a tick runs one criterion. Closing the rest would mark work as
    done that nobody started -- the exact lie the protocol's queue exists to prevent.
    """
    item["state"] = "closed"
    item["exit"] = int(exit_code)
    item["closed_at"] = _moment().isoformat()
    return item


def _moment():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc)
