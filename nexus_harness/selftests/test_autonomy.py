"""El bucle autonomo: backup primero, verde o alto, y el progreso escrito SOLO despues del gate.

El planificador y el ejecutor entran inyectados a proposito: un bucle que solo se puede probar con un
modelo encendido no se prueba nunca. Lo que se mide aqui es el orden de las decisiones, que es donde
vive el peligro: editar sin red, dar por hecho lo que no se verifico, o insistir sobre rojo.
"""
import json
import shutil
import tempfile
from pathlib import Path

from .. import autonomy, ledger, projects
from ..config import HarnessConfig
from ..events import Bus


def check(name, got, expect, failures):
    if got != expect:
        failures.append("%s: %r, esperaba %r" % (name, got, expect))


class FakeSnapshot:
    """Un snapshot que apunta lo que se le pide y puede negarse, para probar el fail-closed."""

    def __init__(self, ok=True, log=None):
        self.ok, self.calls = ok, []
        self.log = log if log is not None else []

    def __call__(self, root, reason="autonomy"):
        self.calls.append(str(root))
        self.log.append("backup")
        return {"ok": self.ok, "kind": "tag", "ref": "nexus-backup-test",
                "reason": "" if self.ok else "sin red"}


class ScriptedRunner:
    """Devuelve los exit que se le dan, en orden, y apunta cada llamada."""

    def __init__(self, exits, log=None):
        self.exits, self.calls = list(exits), []
        self.log = log if log is not None else []

    def __call__(self, goal, root):
        self.calls.append((goal, str(root)))
        self.log.append("run")
        code = self.exits.pop(0) if self.exits else 0
        return {"ok": code == 0, "exit": code, "repairs": 0, "steps": 2,
                "verdict": {"ok": code == 0, "exit": code, "checks": []},
                "judgement": {"verdict": "approve"}, "touched": ["a.py"]}


class JudgeRejectRunner(ScriptedRunner):
    """Gate VERDE y Juez en contra: el bucle tiene que decir cual de los dos freno."""

    def __call__(self, goal, root):
        self.calls.append((goal, str(root)))
        return {"ok": False, "exit": 10, "repairs": 0, "steps": 4,
                "verdict": {"ok": True, "exit": 0, "checks": []},
                "judgement": {"verdict": "reject", "reason": "no toco un solo fichero"},
                "touched": []}


def _project(workspace, name, criteria=3):
    root = Path(workspace) / name
    (root / ".ai").mkdir(parents=True)
    (root / ".ai" / "CURRENT_SPEC.json").write_text(
        json.dumps({"format": "nexus.spec/1", "id": "spec-x", "goal": "objetivo %s" % name,
                    "cas_count": criteria, "cas_sha256": "c" * 64}), encoding="utf-8")
    return root


def test_plan_parse(failures):
    plan = autonomy.parse_plan('{"done": false, "step": "arreglar calc.py"}')
    check("the step is read", plan["step"], "arreglar calc.py", failures)
    check("done is read", plan["done"], False, failures)
    fenced = autonomy.parse_plan('```json\n{"done": true, "step": ""}\n```')
    check("a fenced JSON is still JSON", fenced["done"], True, failures)
    prose = autonomy.parse_plan("1. escribe el test que falta\n2. luego arregla\n")
    check("without JSON the first line is the step", prose["step"], "1. escribe el test que falta",
          failures)
    check("and it says so", "sin JSON" in prose["why"], True, failures)
    broken = autonomy.parse_plan("{no es json}")
    check("broken JSON does not crash", broken["done"], False, failures)


def test_backup_before_edit(failures):
    workspace = Path(tempfile.mkdtemp(prefix="nexus-autonomy-"))
    try:
        _project(workspace, "Alpha")
        log = []
        config = HarnessConfig(workspace=workspace, default_root=workspace)
        runner = ScriptedRunner([0, 0], log=log)
        ap = autonomy.Autopilot(config, runner=runner,
                                planner=lambda root, goal, prog: {"step": "hacer el paso", "done": False},
                                bus=Bus(), snapshot=FakeSnapshot(log=log))
        ap._loop(["Alpha"], "objetivo", 2)
        check("two cycles, two backups", log.count("backup"), 2, failures)
        check("each backup happens BEFORE its run", log, ["backup", "run", "backup", "run"], failures)
        check("the loop finished", ap.state()["running"], False, failures)
        check("with its steps counted", ap.state()["steps_done"], 2, failures)
        progress = projects.progress(workspace / "Alpha")
        check("the progress file has both steps", len(progress["steps"]), 2, failures)
        check("and both are verified", [one["ok"] for one in progress["steps"]], [True, True],
              failures)
        check("the iterations are counted", progress["iterations"], 2, failures)
        rows = ledger.TurnLedger(workspace / "Alpha").rows()
        check("every cycle is measured in the ledger", len(rows), 2, failures)
        check("with its source declared", rows[0]["source"], "autonomy", failures)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_red_stops_and_moves_on(failures):
    workspace = Path(tempfile.mkdtemp(prefix="nexus-autonomy-"))
    try:
        _project(workspace, "Alpha")
        _project(workspace, "Beta")
        bus = Bus()
        runner = ScriptedRunner([10, 0])
        ap = autonomy.Autopilot(HarnessConfig(workspace=workspace, default_root=workspace),
                                runner=runner,
                                planner=lambda root, goal, prog: {"step": "paso en %s" % Path(root).name,
                                                                  "done": False},
                                bus=bus, snapshot=FakeSnapshot())
        ap._loop(["Alpha", "Beta"], "objetivo", 2)
        check("a red gate does not repeat on the same project", [call[1] for call in runner.calls][0]
              .endswith("Alpha"), True, failures)
        check("the second project ran", any(str(call[1]).endswith("Beta") for call in runner.calls),
              True, failures)
        alpha = projects.progress(workspace / "Alpha")
        check("the red step is recorded as failed", alpha["steps"][0]["ok"], False, failures)
        check("and it was NOT marked done", alpha["done"], False, failures)
        beta = projects.progress(workspace / "Beta")
        check("the next project advanced", beta["steps"][0]["ok"], True, failures)
        check("the bus says why it moved on", any("rojo" in str(event["detail"]).lower()
                                                 for event in bus.all()), True, failures)
        check("the pill gets its phase", any(event["kind"] == "autonomy.step" for event in bus.all()),
              True, failures)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_no_backup_no_edit(failures):
    workspace = Path(tempfile.mkdtemp(prefix="nexus-autonomy-"))
    try:
        _project(workspace, "Alpha")
        runner = ScriptedRunner([0])
        ap = autonomy.Autopilot(HarnessConfig(workspace=workspace, default_root=workspace),
                                runner=runner,
                                planner=lambda root, goal, prog: {"step": "algo", "done": False},
                                bus=Bus(), snapshot=FakeSnapshot(ok=False))
        ap._loop(["Alpha"], "objetivo", 1)
        check("without a snapshot nothing is executed", runner.calls, [], failures)
        check("and it is said, with the reason", "sin backup" in ap.state()["last"], True, failures)
        check("no progress is invented", projects.progress(workspace / "Alpha")["steps"], [], failures)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_done_and_limits(failures):
    workspace = Path(tempfile.mkdtemp(prefix="nexus-autonomy-"))
    try:
        _project(workspace, "Alpha")
        runner = ScriptedRunner([0, 0, 0])
        ap = autonomy.Autopilot(HarnessConfig(workspace=workspace, default_root=workspace),
                                runner=runner,
                                planner=lambda root, goal, prog: {"done": True, "step": ""},
                                bus=Bus(), snapshot=FakeSnapshot())
        ap._loop(["Alpha"], "objetivo", 3)
        check("a project the Director calls complete is not touched", runner.calls, [], failures)
        check("and it is marked done", projects.progress(workspace / "Alpha")["done"], True, failures)

        _project(workspace, "Beta")
        ap2 = autonomy.Autopilot(HarnessConfig(workspace=workspace, default_root=workspace),
                                 runner=ScriptedRunner([0, 0, 0]),
                                 planner=lambda root, goal, prog: {"step": "otra vez", "done": False},
                                 bus=Bus(), snapshot=FakeSnapshot())
        ap2._loop(["Beta"], "objetivo", 3)
        check("the iteration limit is respected", ap2.state()["steps_done"], 3, failures)
        check("and the project is not marked done by iteration alone",
              projects.progress(workspace / "Beta")["done"], False, failures)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_start_refusals(failures):
    workspace = Path(tempfile.mkdtemp(prefix="nexus-autonomy-"))
    try:
        config = HarnessConfig(workspace=workspace, default_root=workspace)
        empty = autonomy.Autopilot(config, runner=ScriptedRunner([]), bus=Bus())
        ok, reason = empty.start()
        check("an empty queue is refused, not silently accepted", ok, False, failures)
        check("with a reason a human can act on", "proyecto" in reason.lower(), True, failures)
        no_runner = autonomy.Autopilot(config, runner=None, bus=Bus())
        ok, reason = no_runner.start(project="Alpha")
        check("without an executor the loop refuses", ok, False, failures)
        check("and says which piece is missing", "ejecutor" in reason.lower(), True, failures)
        check("stopping something that is not running is not an error", no_runner.stop(), False,
              failures)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_thread_runs_and_finishes(failures):
    import time

    workspace = Path(tempfile.mkdtemp(prefix="nexus-autonomy-"))
    try:
        _project(workspace, "Alpha")
        ap = autonomy.Autopilot(HarnessConfig(workspace=workspace, default_root=workspace),
                                runner=ScriptedRunner([0]),
                                planner=lambda root, goal, prog: {"step": "un paso", "done": False},
                                bus=Bus(), snapshot=FakeSnapshot())
        ok, payload = ap.start(project="Alpha", iterations=1)
        check("the loop is accepted", ok, True, failures)
        check("and reports the queue it will walk", payload.get("queue"), ["Alpha"], failures)
        deadline = time.time() + 20
        while time.time() < deadline and ap.state()["running"]:
            time.sleep(0.05)
        check("the thread finishes on its own", ap.state()["running"], False, failures)
        check("having done its step", ap.state()["steps_done"], 1, failures)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_judge_rejection_is_not_called_a_red_gate(failures):
    workspace = Path(tempfile.mkdtemp(prefix="nexus-autonomy-judge-"))
    try:
        _project(workspace, "Alpha")
        bus = Bus()
        ap = autonomy.Autopilot(HarnessConfig(workspace=workspace, default_root=workspace),
                                runner=JudgeRejectRunner([]),
                                planner=lambda root, goal, prog: {"step": "auditar", "done": False},
                                bus=bus, snapshot=FakeSnapshot())
        finished = ap._project("Alpha", "objetivo", 1)
        check("el rechazo del juez para el proyecto", finished, False, failures)
        last = ap.state()["last"]
        check("y no se llama gate rojo", "Juez rechazo" in last, True, failures)
        check("con su motivo", "no toco un solo fichero" in last, True, failures)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _spec_with_cas(workspace, name, cas):
    """Un proyecto con criterios EJECUTABLES en su spec (la forma que escribe `spec_synth`)."""
    root = _project(workspace, name)
    (root / ".ai" / "CURRENT_SPEC.json").write_text(json.dumps(
        {"format": "nexus.spec/1", "id": "spec-%s" % name, "goal": "objetivo %s" % name,
         "cas": cas, "cas_sha256": "c" * 64}), encoding="utf-8")
    return root


def _ca(title, command, expect=0):
    return {"id": "CA1", "title": title, "command": command, "expect_exit": expect,
            "evidence": {"exit": 1, "at": "2026-10-27T00:00:00Z"}}


def test_the_graph_decides_the_order(failures):
    """Dos nodos con dependencia: primero n1, luego n2, y los dos quedan apuntados."""
    workspace = Path(tempfile.mkdtemp(prefix="nexus-autonomy-graph-"))
    try:
        _project(workspace, "Alpha")
        runner = ScriptedRunner([0, 0, 0])
        plan = {"nodes": [{"id": "n1", "step": "escribe el test", "depends_on": []},
                          {"id": "n2", "step": "arregla calc", "depends_on": ["n1"]}],
                "done": False, "step": "escribe el test"}
        ap = autonomy.Autopilot(HarnessConfig(workspace=workspace, default_root=workspace),
                                runner=runner, planner=lambda root, goal, prog: plan,
                                bus=Bus(), snapshot=FakeSnapshot())
        ap._loop(["Alpha"], "objetivo", 2)
        progress = projects.progress(workspace / "Alpha")
        check("los dos nodos quedan hechos", progress.get("nodes"), ["n1", "n2"], failures)
        check("el primero que corrio fue n1", "escribe el test" in runner.calls[0][0], True,
              failures)
        check("y despues n2", "arregla calc" in runner.calls[1][0], True, failures)
        check("cada paso lleva su nodo", [row.get("node") for row in progress["steps"]],
              ["n1", "n2"], failures)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_a_ready_node_is_not_repeated(failures):
    """Con n1 hecho, el ciclo siguiente no vuelve a n1 aunque el plan sea el mismo."""
    workspace = Path(tempfile.mkdtemp(prefix="nexus-autonomy-ready-"))
    try:
        _project(workspace, "Alpha")
        plan = {"nodes": [{"id": "n1", "step": "uno", "depends_on": []},
                          {"id": "n2", "step": "dos", "depends_on": ["n1"]}], "done": False}
        runner = ScriptedRunner([0, 0])
        ap = autonomy.Autopilot(HarnessConfig(workspace=workspace, default_root=workspace),
                                runner=runner, planner=lambda root, goal, prog: plan,
                                bus=Bus(), snapshot=FakeSnapshot())
        ap._loop(["Alpha"], "objetivo", 2)
        check("no repite el primero", ("uno" in runner.calls[0][0]
                                       and "dos" in runner.calls[1][0]), True, failures)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_the_project_ends_when_the_criteria_pass(failures):
    """La parada es el exit de los criterios, no el silencio del Director: cero llamadas al modelo."""
    workspace = Path(tempfile.mkdtemp(prefix="nexus-autonomy-criteria-"))
    try:
        _spec_with_cas(workspace, "Alpha", [_ca("el proyecto importa",
                                                ["python", "-c", "pass"])])
        runner = ScriptedRunner([0, 0])
        ap = autonomy.Autopilot(HarnessConfig(workspace=workspace, default_root=workspace),
                                runner=runner,
                                planner=lambda root, goal, prog: {"nodes": [{"id": "n1",
                                                                             "step": "sobra"}],
                                                                  "done": False},
                                bus=Bus(), snapshot=FakeSnapshot())
        finished = ap._project("Alpha", "objetivo", 3)
        check("el proyecto se cierra", finished, True, failures)
        check("sin gastar una sola llamada", runner.calls, [], failures)
        progress = projects.progress(workspace / "Alpha")
        check("y queda marcado como hecho", progress["done"], True, failures)
        check("con el criterio medido", progress["steps"][0]["criteria"], 1, failures)
        check("y el motivo en el estado", "criterios" in ap.state()["last"], True, failures)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_a_finding_grows_the_spec(failures):
    """Un criterio nuevo se valida y se ANADE; el congelado sigue donde estaba."""
    workspace = Path(tempfile.mkdtemp(prefix="nexus-autonomy-grow-"))
    try:
        _spec_with_cas(workspace, "Alpha", [_ca("falla hoy", ["python", "-c", "import sys; sys.exit(1)"])])
        plan = {"nodes": [{"id": "n1", "step": "arregla calc", "depends_on": []}],
                "done": False,
                "new_criterion": {"title": "el doble tambien", "expect_exit": 0,
                                  "command": "python -c \"import sys; sys.exit(2)\""}}
        ap = autonomy.Autopilot(HarnessConfig(workspace=workspace, default_root=workspace),
                                runner=ScriptedRunner([0]), planner=lambda root, goal, prog: plan,
                                bus=Bus(), snapshot=FakeSnapshot())
        ap._project("Alpha", "objetivo", 1)
        spec = json.loads((workspace / "Alpha" / ".ai" / "CURRENT_SPEC.json").read_text(
            encoding="utf-8"))
        check("la spec crece a dos criterios", len(spec["cas"]), 2, failures)
        check("el viejo no se toca", spec["cas"][0]["title"], "falla hoy", failures)
        check("el nuevo entra con su origen", spec["cas"][1]["source"], "director", failures)
        check("y la spec dice quien la amplio", spec.get("grown_by"), "autonomy", failures)
        check("el sha cubre el conjunto", spec["cas_sha256"], __import__(
            "nexus_harness.spec_synth", fromlist=["_sha"])._sha(spec["cas"]), failures)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_a_cycled_plan_does_not_run(failures):
    workspace = Path(tempfile.mkdtemp(prefix="nexus-autonomy-cycle-"))
    try:
        _project(workspace, "Alpha")
        runner = ScriptedRunner([0])
        plan = {"nodes": [{"id": "a", "step": "x", "depends_on": ["b"]},
                          {"id": "b", "step": "y", "depends_on": ["a"]}], "done": False}
        ap = autonomy.Autopilot(HarnessConfig(workspace=workspace, default_root=workspace),
                                runner=runner, planner=lambda root, goal, prog: plan,
                                bus=Bus(), snapshot=FakeSnapshot())
        finished = ap._project("Alpha", "objetivo", 2)
        check("un plan imposible para el proyecto", finished, False, failures)
        check("y no se ejecuta nada", runner.calls, [], failures)
        check("con el motivo en el estado", "no se puede ejecutar" in ap.state()["last"], True,
              failures)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def run():
    failures = []
    test_plan_parse(failures)
    test_backup_before_edit(failures)
    test_red_stops_and_moves_on(failures)
    test_no_backup_no_edit(failures)
    test_done_and_limits(failures)
    test_start_refusals(failures)
    test_thread_runs_and_finishes(failures)
    test_judge_rejection_is_not_called_a_red_gate(failures)
    test_the_graph_decides_the_order(failures)
    test_a_ready_node_is_not_repeated(failures)
    test_the_project_ends_when_the_criteria_pass(failures)
    test_a_finding_grows_the_spec(failures)
    test_a_cycled_plan_does_not_run(failures)
    return failures
