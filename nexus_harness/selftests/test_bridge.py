"""The bridge: a `/task` queued by the protocol's remote listener becomes a run with an exit code.

The queue is the protocol's file (`.nexus/hive/queue.json`), written by `nexus/hive/queue.py`. This
suite writes it with that same module and then holds the harness to four promises:

* one item at a time (`max_workers` is a cap, not a suggestion);
* a claimed item is closed with the exit the runner produced, not with "it ran";
* an unknown project stays queued and visible instead of vanishing;
* a runner that crashes closes red instead of staying dispatched forever.
"""
import os
import sys
from pathlib import Path

from . import require_protocol
from .fakes import TempProject
from ..bridge import Bridge

# `NEXUS_PROTOCOL` first: a path written into a test file is a test that only runs on one machine.
NEXUS_SOURCE = Path(os.environ.get("NEXUS_PROTOCOL") or r"C:\Proyectos\NexusProtocol")
if str(NEXUS_SOURCE) not in sys.path:
    sys.path.insert(0, str(NEXUS_SOURCE))


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def _queue():
    from nexus.hive import queue
    return queue


def enqueue(workspace, project, criterion):
    module = _queue()
    state = module.load(str(workspace))
    item, _created = module.enqueue(state, project, criterion, _moment())
    module.save(str(workspace), state)
    return item


def _moment():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc)


def test_queue_round_trip(failures):
    with TempProject() as workspace:
        (workspace / "demo").mkdir()
        bridge = Bridge(workspace)
        check("the protocol queue is importable", bridge.available, True, failures)
        enqueue(workspace, "demo", "arregla el test de login")
        pending = bridge.pending()
        check("the queued task is visible", len(pending), 1, failures)
        check("and names its project", pending[0]["project"], "demo", failures)
        calls = []

        def runner(goal, root):
            calls.append((goal, Path(root).name))
            return 0

        rows = bridge.tick(runner)
        check("one item was attempted", len(rows), 1, failures)
        check("the runner got the criterion and the project",
              calls, [("arregla el test de login", "demo")], failures)
        check("and it closed green", rows[0]["exit"], 0, failures)
        check("the queue is empty afterwards", bridge.pending(), [], failures)
        check("the closed item keeps its exit code", _closed_exits(workspace), [0], failures)


def test_cap_and_unknown_project(failures):
    with TempProject() as workspace:
        (workspace / "demo").mkdir()
        bridge = Bridge(workspace)
        enqueue(workspace, "demo", "primera")
        enqueue(workspace, "demo", "segunda")
        enqueue(workspace, "fantasma", "no existe")
        rows = bridge.tick(lambda goal, root: 0)
        check("the cap allows exactly one run", len(rows), 1, failures)
        check("the other two are still visible", len(bridge.pending()), 2, failures)
        rows = bridge.tick(lambda goal, root: 0)
        check("the second run happens on the next tick", len(rows), 1, failures)
        ghost = [item for item in bridge.pending() if item["project"] == "fantasma"]
        check("an unknown project stays queued", len(ghost), 1, failures)
        check("and the run says why", bridge.tick(lambda goal, root: 0)[0].get("ok"), False,
              failures)


def test_crashing_runner_closes_red(failures):
    with TempProject() as workspace:
        (workspace / "demo").mkdir()
        bridge = Bridge(workspace)
        enqueue(workspace, "demo", "esto revienta")

        def boom(goal, root):
            raise RuntimeError("modelo caído")

        rows = bridge.tick(boom)
        check("a crash is reported", rows[0]["exit"], 10, failures)
        check("and the item is not left dispatched", _states(workspace), ["closed"], failures)
        check("with the red exit stored for the phone to read", _closed_exits(workspace), [10],
              failures)


def test_red_run_is_not_closed_green(failures):
    with TempProject() as workspace:
        (workspace / "demo").mkdir()
        bridge = Bridge(workspace)
        enqueue(workspace, "demo", "gate rojo")
        rows = bridge.tick(lambda goal, root: 10)
        check("the exit the runner produced is the one stored", rows[0]["exit"], 10, failures)
        check("and the status is the one the queue shows", bridge.status()["runs"][-1]["ok"], False,
              failures)


def _states(workspace):
    return [item.get("state") for item in _queue().load(str(workspace)).get("items", [])]


def _closed_exits(workspace):
    return [item.get("exit") for item in _queue().load(str(workspace)).get("items", [])
            if item.get("state") == "closed"]


def run():
    require_protocol("nexus.hive.queue")
    failures = []
    for test in (test_queue_round_trip, test_cap_and_unknown_project,
                 test_crashing_runner_closes_red, test_red_run_is_not_closed_green):
        test(failures)
    return failures
