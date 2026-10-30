"""El tablero: dependencias que bloquean, movimientos que no pasan, y un YOLO que firma el Gate.

Lo que se mide aqui es la diferencia con un Kanban normal: el `done` no lo decide el agente. Hay tres
barreras y las tres se prueban con un intento real de saltarselas:

* un padre pendiente bloquea, y al cerrarse el padre la hija se desbloquea SOLA;
* `review` exige commit y gate verde; `done` exige gate verde y (si hay Juez) su aprobacion;
* la cadena `yolo` solo cierra lo que el gate firma: con un gate rojo devuelve la tarea y para.
"""
import json
from pathlib import Path

from .fakes import TempProject
from ..autonomy.kanvas_runner import run_chain
from ..platform.kanvas import Board, KanvasError
from ..tools import Registry


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


class FakeVerdict:
    def __init__(self, exit_code):
        self.exit = exit_code
        self.ok = exit_code == 0


class FakeGate:
    """Un gate que contesta lo que se le pide, y cuenta las veces: el runner no puede saltarselo."""

    def __init__(self, exit_code=0):
        self.exit_code = exit_code
        self.calls = 0

    def run(self, files):
        self.calls += 1
        return FakeVerdict(self.exit_code)

    def run_command(self, command):
        self.calls += 1
        return FakeVerdict(self.exit_code)


class FakeJudgement:
    def __init__(self, verdict):
        self.verdict = verdict
        self.reason = "fake"


class FakeJudge:
    def __init__(self, verdict="approve"):
        self.verdict = verdict
        self.calls = 0

    def review(self, goal, summary, touched):
        self.calls += 1
        return FakeJudgement(self.verdict)


def _board(root=None):
    board = Board(project="prueba")
    if root is not None:
        board.path = Path(root) / ".nexus" / "kanvas.json"
    board.add("motor", task_id="TK-01", status="todo")
    board.add("api", task_id="TK-02", status="todo", depends_on=["TK-01"])
    board.add("ui", task_id="TK-03", status="todo", depends_on=["TK-02"])
    return board


def test_a_pending_parent_blocks_and_unblocks_alone(failures):
    board = _board()
    check("la hija espera al padre", board.effective(board.get("TK-02")), "blocked", failures)
    check("solo la raiz esta lista", [task.id for task in board.ready()], ["TK-01"], failures)
    check("no se puede reclamar una bloqueada",
          _raises(board.claim, "TK-02"), True, failures)
    board.claim("TK-01")
    board.submit("TK-01", commits=["abc123"], gate=0)
    board.approve("TK-01")
    check("al cerrar el padre, la hija se desbloquea sola",
          board.effective(board.get("TK-02")), "todo", failures)
    check("y la nieta sigue esperando", board.effective(board.get("TK-03")), "blocked", failures)


def test_the_machine_refuses_what_it_should(failures):
    board = _board()
    board.claim("TK-01")
    check("sin commit no hay review", _raises(board.submit, "TK-01", [], 0), True, failures)
    check("con el gate rojo tampoco", _raises(board.submit, "TK-01", ["c1"], 10), True, failures)
    check("y no se puede saltar a done", _raises(board.move, "TK-01", "done"), True, failures)
    board.submit("TK-01", ["c1"], 0)
    check("review exige que el gate lo haya dicho", board.get("TK-01").evidence["gate"], 0, failures)
    board.approve("TK-01")
    check("done es final", _raises(board.move, "TK-01", "doing"), True, failures)
    check("`blocked` no se escribe a mano", _raises(board.move, "TK-02", "blocked"), True, failures)


def test_a_cycle_cannot_be_created(failures):
    from ..platform.kanvas import Task

    board = _board()
    check("una dependencia de si misma se rechaza",
          _raises(board.add, "imposible", task_id="TK-09", depends_on=["TK-09"]), True, failures)
    check("y el tablero no queda a medias", len(board.tasks), 3, failures)
    loop = Board(project="ciclo")
    loop.tasks = [Task(id="A", title="a", depends_on=["B"]), Task(id="B", title="b", depends_on=["A"])]
    check("un ciclo escrito a mano se detecta", len(loop.cycles()), 1, failures)
    check("y no rompe el calculo de listas", isinstance(loop.ready(), list), True, failures)


def test_the_file_survives_a_reload(failures):
    with TempProject() as root:
        board = Board.load(root)
        board.add("persistente", task_id="TK-01", status="todo")
        board.save()
        again = Board.load(root)
        check("el tablero se relee del JSON", [task.id for task in again.tasks], ["TK-01"], failures)
        payload = json.loads((Path(root) / ".nexus" / "kanvas.json").read_text(encoding="utf-8"))
        check("y el fichero lleva formato y proyecto", payload.get("format"), 1, failures)


def test_yolo_closes_only_what_the_gate_signs(failures):
    with TempProject() as root:
        board = _board(root)
        board.toggle_yolo("TK-01", chain=True)
        gate, judge = FakeGate(0), FakeJudge("approve")
        report = run_chain(root, lambda task: {"exit": 0, "touched": ["a.py"], "summary": "hecho"},
                           gate=gate, judge=judge, board=board, limit=4)
        check("la cadena cierra las tres", report["done"], ["TK-01", "TK-02", "TK-03"], failures)
        check("y todas quedan done", [task.status for task in board.tasks], ["done"] * 3, failures)
        check("el gate se consulto por cada tarea", gate.calls, 3, failures)
        check("y quedo escrito en el fichero",
              len(json.loads((Path(root) / ".nexus" / "kanvas.json").read_text("utf-8"))["tasks"]), 3,
              failures)


def test_a_red_gate_stops_the_chain(failures):
    with TempProject() as root:
        board = _board(root)
        board.toggle_yolo("TK-01", chain=True)
        report = run_chain(root, lambda task: {"exit": 10, "touched": ["a.py"]},
                           gate=FakeGate(10), judge=FakeJudge("approve"), board=board, limit=4)
        check("nada se cierra con el gate rojo", report["done"], [], failures)
        check("la tarea vuelve al obrero", board.get("TK-01").status, "doing", failures)
        check("y la cadena para con motivo", bool(report["stopped"]), True, failures)
        check("la hija sigue bloqueada", board.effective(board.get("TK-02")), "blocked", failures)


def test_a_judge_reject_sends_it_back(failures):
    with TempProject() as root:
        board = _board(root)
        board.toggle_yolo("TK-01")
        report = run_chain(root, lambda task: {"exit": 0, "touched": ["a.py"]},
                           gate=FakeGate(0), judge=FakeJudge("reject"), board=board, limit=2)
        check("sin Juez de acuerdo no hay done", report["done"], [], failures)
        check("el motivo nombra al Juez", "Juez" in report["stopped"], True, failures)


def test_the_tool_is_the_only_door_for_agents(failures):
    with TempProject() as root:
        registry = Registry(root)
        first = registry.call("kanvas_board", {"action": "decompose", "tasks": [
            {"id": "TK-01", "title": "motor", "track": "core"},
            {"id": "TK-02", "title": "api", "track": "core", "depends_on": ["TK-01"]}]})
        check("decompose crea el grafo", first.ok, True, failures)
        check("y lo dice", "TK-02" in first.text, True, failures)
        claim = registry.call("kanvas_board", {"action": "claim", "task": "TK-02"})
        check("reclamar una bloqueada es una observacion, no un crash", claim.ok, False, failures)
        check("con el motivo", "padres pendientes" in claim.text, True, failures)
        done = registry.call("kanvas_board", {"action": "approve", "task": "TK-01"})
        check("la herramienta no aprueba: no existe", done.ok, False, failures)
        check("y la salida dice por que", "no existe" in done.text, True, failures)


def test_the_page_serves_the_graph(failures):
    """La vista: `/kanvas` sirve el SVG del grafo, y la API devuelve el tablero con su resumen."""
    import threading
    import urllib.error
    import urllib.request

    from .fakes import FakeRouter
    from ..cockpit import Cockpit
    from ..config import HarnessConfig
    from ..ui import build

    with TempProject() as root:
        config = HarnessConfig(default_root=root, workspace=root, roles={
            "director": "fake:d", "worker": "fake:w", "judge": "fake:j"}, host="127.0.0.1",
            port=0, lang="es", secrets={})
        cockpit = Cockpit(config)
        cockpit.router = FakeRouter()
        board = Board.load(root)
        board.add("motor", task_id="TK-01", status="todo")
        board.add("api", task_id="TK-02", status="todo", depends_on=["TK-01"])
        board.save()
        server = build(cockpit, port=0, token="t0k")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % server.server_address[1]
        headers = {"X-Nexus-Token": "t0k", "Content-Type": "application/json"}
        try:
            page = urllib.request.urlopen(urllib.request.Request(base + "/kanvas", headers=headers),
                                          timeout=10).read().decode("utf-8")
            check("la pagina trae el lienzo del grafo", 'id="k-edges"' in page, True, failures)
            check("y su script", 'src="kanvas.js"' in page, True, failures)
            payload = json.loads(urllib.request.urlopen(
                urllib.request.Request(base + "/api/kanvas", headers=headers), timeout=10).read())
            check("la API devuelve el tablero", [row["id"] for row in payload["tasks"]],
                  ["TK-01", "TK-02"], failures)
            check("con el estado efectivo", [row["status"] for row in payload["tasks"]],
                  ["todo", "blocked"], failures)
            body = json.dumps({"action": "approve", "task": "TK-01"}).encode("utf-8")
            try:
                urllib.request.urlopen(urllib.request.Request(
                    base + "/api/kanvas", data=body, headers=headers, method="POST"), timeout=10)
                code = 200
            except urllib.error.HTTPError as exc:
                code = exc.code
            check("aprobar sin evidencia se rechaza con 409", code, 409, failures)
        finally:
            server.shutdown()
            server.server_close()


def _raises(func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except KanvasError:
        return True
    return False


def run():
    failures = []
    for test in (test_a_pending_parent_blocks_and_unblocks_alone, test_the_machine_refuses_what_it_should,
                 test_a_cycle_cannot_be_created, test_the_file_survives_a_reload,
                 test_yolo_closes_only_what_the_gate_signs, test_a_red_gate_stops_the_chain,
                 test_a_judge_reject_sends_it_back, test_the_tool_is_the_only_door_for_agents,
                 test_the_page_serves_the_graph):
        test(failures)
    return failures
