"""El daemon y su bandeja: trabajo autonomo que reanuda, se para y no miente.

Lo que se mide aqui, que es justo lo que hace inservible un agente de fondo cuando falla:

* una tarea se reclama UNA vez y se cierra con el exit real;
* una firma repetida no llena la bandeja de duplicados;
* un proyecto sin spec se queda con una spec congelada de su propio repo, o no se toca;
* un proyecto con criterios verdes NO gasta una llamada: encola mejoras;
* un segundo daemon se niega a arrancar (cerrojo con pid);
* el tick deja estado en disco y manda el aviso.
"""
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from .fakes import TempProject
from ..core import tasks
from .. import improve
from ..config import HarnessConfig
from ..autonomy.daemon import Daemon


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def _snapshot(root, reason="autonomy"):
    """Un backup de mentira: los proyectos de prueba no son git y el ciclo exige red antes de editar."""
    return {"ok": True, "kind": "test", "ref": "test", "reason": ""}


class FakeNotifier:
    ready = True

    def __init__(self):
        self.sent = []

    def send(self, text, kind="info"):
        self.sent.append(text)
        return [{"ok": True, "channel": "fake", "detail": "ok"}]


def _spec(root, cas, goal="objetivo"):
    path = Path(root) / ".ai" / "CURRENT_SPEC.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"format": "nexus.spec/1", "goal": goal, "cas": cas}),
                    encoding="utf-8")


GREEN = [{"id": "CA1", "title": "pasa", "command": ["python", "-c", "pass"], "expect_exit": 0}]
RED = [{"id": "CA1", "title": "falla", "command": ["python", "-c", "import sys; sys.exit(1)"],
        "expect_exit": 0}]


def _workspace(projects=("Alpha",)):
    root = Path(tempfile.mkdtemp(prefix="nexus-daemon-"))
    for name in projects:
        (root / name).mkdir(parents=True)
    return root


def test_the_inbox_is_claimed_once_and_closed_with_its_exit(failures):
    with TempProject() as root:
        box = tasks.Inbox(root)
        first = box.add("Alpha", "arregla el test", signature="s1")
        check("la tarea entra", first["state"], "queued", failures)
        repeated = box.add("Alpha", "otra vez lo mismo", signature="s1")
        check("la firma repetida no duplica", repeated.get("duplicate"), True, failures)
        check("y la bandeja tiene una", len(box.open()), 1, failures)
        claimed = box.claim(1)
        check("se reclama una", len(claimed), 1, failures)
        check("y queda marcada", claimed[0]["state"], "claimed", failures)
        check("nadie mas la reclama", box.claim(1), [], failures)
        closed = box.close(first["id"], 10, "rojo a proposito")
        check("se cierra con su exit", (closed["state"], closed["exit"]), ("failed", 10), failures)
        check("y no queda abierta", box.open(), [], failures)
        (root / tasks.REL).write_text((root / tasks.REL).read_text(encoding="utf-8") + "{roto\n",
                                      encoding="utf-8")
        check("una linea rota no rompe la bandeja", len(box.rows()), 1, failures)


def test_improve_finds_real_gaps_and_does_not_repeat_them(failures):
    with TempProject({"a.py": "x = 1  # TODO uno\n# TODO dos\n# FIXME tres\n# TODO cuatro\n# TODO cinco\n# TODO seis\n",
                      "big.py": "y = 1\n" * 360}) as root:
        found = improve.signals(root)
        titles = " ".join(signal["title"] for signal in found)
        check("ve los TODO", "TODO" in titles, True, failures)
        check("ve el fichero grande", "divide big.py" in titles, True, failures)
        check("y ve que no hay runner", "como se prueba" in titles, True, failures)
        box = tasks.Inbox(root)
        added = improve.queue(root, inbox=box, limit=3)
        check("encola las mejores", len(added) >= 2, True, failures)
        again = improve.queue(root, inbox=box, limit=3)
        check("no repite lo ya abierto", again, [], failures)


def test_a_tick_runs_an_inbox_task(failures):
    workspace = _workspace()
    try:
        calls = []

        def runner(goal, root):
            calls.append((goal, str(root)))
            return {"ok": True, "exit": 0}

        config = HarnessConfig(workspace=workspace, default_root=workspace / "Alpha",
                               project_order=["Alpha"])
        daemon = Daemon(config, runner=runner, interval=0, notifier=FakeNotifier(),
                        snapshot=_snapshot)
        daemon.inbox.add("Alpha", "haz la tarea de la bandeja")
        row = daemon.tick()
        check("la tarea manda sobre el proyecto", len(calls), 1, failures)
        check("y el objetivo es el de la tarea", "bandeja" in calls[0][0], True, failures)
        check("cerro en verde", row["exit"], 0, failures)
        check("no queda nada abierto", daemon.inbox.open(), [], failures)
        check("y aviso", len(daemon.notifier.sent), 1, failures)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_a_green_project_costs_zero_calls_and_queues_improvements(failures):
    workspace = _workspace()
    old = os.environ.get("NEXUS_HOME")
    os.environ["NEXUS_HOME"] = str(workspace / "home")
    try:
        calls = []
        _spec(workspace / "Alpha", GREEN)
        (workspace / "Alpha" / "a.py").write_text("x = 1\n" * 60 + "# TODO uno\n# TODO dos\n"
                                                  "# TODO tres\n# TODO cuatro\n# TODO cinco\n",
                                                  encoding="utf-8")
        config = HarnessConfig(workspace=workspace, default_root=workspace / "Alpha",
                               project_order=["Alpha"])
        daemon = Daemon(config, runner=lambda goal, root: calls.append(1) or {"ok": True},
                        interval=0, snapshot=_snapshot)
        row = daemon.tick()
        check("no se ejecuta nada", calls, [], failures)
        check("el estado lo dice", row["status"], "ya verde", failures)
        check("y el proyecto ya tiene tareas", len(daemon.inbox.open()) >= 1, True, failures)
        state = json.loads((daemon.state_path).read_text(encoding="utf-8"))
        check("el estado queda en disco", state["rounds"], 1, failures)
    finally:
        if old is None:
            os.environ.pop("NEXUS_HOME", None)
        else:
            os.environ["NEXUS_HOME"] = old
        shutil.rmtree(workspace, ignore_errors=True)


def test_a_red_project_runs_one_cycle(failures):
    workspace = _workspace()
    calls = []
    try:
        _spec(workspace / "Alpha", RED)
        config = HarnessConfig(workspace=workspace, default_root=workspace / "Alpha",
                               project_order=["Alpha"])
        daemon = Daemon(config, runner=lambda goal, root: calls.append(goal) or {"ok": True},
                        interval=0, iterations=1, snapshot=_snapshot)
        row = daemon.tick()
        check("se ejecuta un ciclo", len(calls), 1, failures)
        check("con el objetivo de la spec", "objetivo" in calls[0], True, failures)
        check("el estado es trabajo", row["status"], "trabajo", failures)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_a_second_daemon_refuses_to_start(failures):
    workspace = _workspace()
    old = os.environ.get("NEXUS_HOME")
    os.environ["NEXUS_HOME"] = str(workspace / "home")
    try:
        config = HarnessConfig(workspace=workspace, default_root=workspace / "Alpha")
        first = Daemon(config, runner=lambda goal, root: {"ok": True}, interval=0)
        first.lock_path.parent.mkdir(parents=True, exist_ok=True)
        first.lock_path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
        outcome = first.run(rounds=1)
        check("el segundo se niega", outcome["ok"], False, failures)
        check("y dice por que", "daemon vivo" in outcome["reason"], True, failures)
        first.lock_path.unlink()
        check("sin cerrojo arranca", first.run(rounds=1)["ok"], True, failures)
        check("y lo deja limpio", first.lock_path.is_file(), False, failures)
    finally:
        if old is None:
            os.environ.pop("NEXUS_HOME", None)
        else:
            os.environ["NEXUS_HOME"] = old
        shutil.rmtree(workspace, ignore_errors=True)


def test_a_missing_spec_is_frozen_from_the_repo(failures):
    workspace = _workspace()
    try:
        (workspace / "Alpha" / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        (workspace / "Alpha" / "calc.py").write_text("def add(a, b):\n    return a + b\n",
                                                     encoding="utf-8")
        (workspace / "Alpha" / "tests").mkdir()
        (workspace / "Alpha" / "tests" / "test_calc.py").write_text(
            "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 6\n", encoding="utf-8")
        config = HarnessConfig(workspace=workspace, default_root=workspace / "Alpha",
                               project_order=["Alpha"])
        daemon = Daemon(config, runner=lambda goal, root: {"ok": True}, interval=0,
                        snapshot=_snapshot)
        row = daemon.tick()
        check("congela una spec", row["status"], "spec congelada", failures)
        check("con criterios ejecutables", row["criteria"] >= 1, True, failures)
        check("y el fichero existe", (workspace / "Alpha" / ".ai" / "CURRENT_SPEC.json").is_file(),
              True, failures)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def run():
    failures = []
    test_the_inbox_is_claimed_once_and_closed_with_its_exit(failures)
    test_improve_finds_real_gaps_and_does_not_repeat_them(failures)
    test_a_tick_runs_an_inbox_task(failures)
    test_a_green_project_costs_zero_calls_and_queues_improvements(failures)
    test_a_red_project_runs_one_cycle(failures)
    test_a_second_daemon_refuses_to_start(failures)
    test_a_missing_spec_is_frozen_from_the_repo(failures)
    return failures
