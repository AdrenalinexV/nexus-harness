"""La API del tablero: leer, mover y lanzar la cadena `yolo`.

El tablero vive en `platform/kanvas` (datos y reglas); esto es la puerta HTTP de la cabina y el unico
sitio que arranca el ejecutor autonomo. `approve` solo se sirve por aqui: es el clic del operador, y no
existe como herramienta del modelo -- un agente que firma su propio `done` es el agujero que el tablero
cierra.
"""
import threading
from pathlib import Path

from . import projects
from .platform.kanvas import Board, KanvasError

STOP = threading.Event()


def _root(cockpit, project=None):
    """El proyecto del cuerpo, o el de la ventana. Un nombre relativo se busca en el workspace."""
    if not project:
        return Path(cockpit.root)
    candidate = Path(str(project))
    if not candidate.is_absolute():
        candidate = Path(cockpit.config.workspace) / str(project)
    return candidate if candidate.is_dir() else Path(cockpit.root)


def _emit(cockpit, kind, detail, **payload):
    cockpit.bus.emit(kind, detail, **payload)


def portfolio(cockpit):
    """La cola de proyectos con el estado de SU tablero: es el kanvas general que ordena el autopilot."""
    rows = []
    for row in projects.queue(cockpit.config):
        try:
            board = Board.load(row["root"])
            stats = board.stats()
            alive = [task for task in board.tasks if board.effective(task) in ("doing", "review")]
            ready = board.ready()
        except KanvasError as exc:
            rows.append({"name": row["name"], "position": row["position"], "error": str(exc)})
            continue
        rows.append({"name": row["name"], "position": row["position"], "root": row["root"],
                     "percent": stats["percent"], "done": stats["done"], "total": stats["total"],
                     "next": (alive[0].title if alive else (ready[0].title if ready else ""))[:90]})
    return rows


def get(cockpit, query=None):
    board = Board.load(_root(cockpit, (query or {}).get("project")))
    return 200, dict(board.as_dict(), path=str(board.path or ""), portfolio=portfolio(cockpit))


def post(cockpit, body):
    """Una accion, un cambio validado. Devuelve `(status, payload)` como el resto de la API."""
    body = body if isinstance(body, dict) else {}
    action = str(body.get("action") or "").strip()
    if action == "move_project":
        names, note = projects.move(cockpit.config, str(body.get("project") or ""),
                                    str(body.get("dir") or "up"))
        cockpit.config.project_order = list(names)
        _emit(cockpit, "kanvas.move", note or "cola reordenada", action=action,
              task=str(body.get("project") or ""))
        return 200, {"ok": not note, "detail": note or "cola reordenada", "portfolio": portfolio(cockpit)}
    if action == "yolo_run":
        return start_chain(cockpit, body.get("project"))
    if action == "yolo_stop":
        STOP.set()
        cockpit.stop()
        return 200, {"ok": True, "stopped": True}
    root = _root(cockpit, body.get("project"))
    board = Board.load(root)
    task_id = str(body.get("task") or body.get("task_id") or "").strip()
    try:
        if action == "add":
            task = board.add(body.get("title"), track=body.get("track") or "core",
                             depends_on=body.get("depends_on") or [],
                             verify_cmd=body.get("verify_cmd") or "", by="human")
            detail = "creada %s" % task.id
        elif action == "decompose":
            rows = [row for row in body.get("tasks") or [] if isinstance(row, dict)]
            created = [board.add(row.get("title"), track=row.get("track") or "core",
                                 depends_on=row.get("depends_on") or [],
                                 task_id=row.get("id") or "", by="director") for row in rows[:40]]
            detail = "descompuesto en %d" % len(created)
        elif action == "approve":
            task = board.approve(task_id, by="human")
            detail = "%s aprobada" % task.id
        elif action == "send_back":
            task = board.send_back(task_id, by="human", reason=body.get("reason") or "")
            detail = "%s devuelta al obrero" % task.id
        elif action == "claim":
            task = board.claim(task_id, by="obrero")
            detail = "%s en curso" % task.id
        elif action == "note":
            task = board.note(task_id, body.get("text") or "", by="human")
            detail = "nota en %s" % task.id
        elif action == "yolo_all":
            marked = 0
            for task in board.tasks:
                if board.effective(task) == "done":
                    continue
                if not task.yolo:
                    board.toggle_yolo(task.id, chain=True, by="human")
                    marked += 1
            detail = "yolo en cadena: %d tareas" % marked
        elif action == "toggle_yolo":
            task = board.toggle_yolo(task_id, chain=bool(body.get("chain")), by="human")
            detail = "%s yolo=%s" % (task.id, task.yolo)
        else:
            return 400, {"ok": False, "reason": "accion desconocida: %r" % action}
    except KanvasError as exc:
        return 409, {"ok": False, "reason": str(exc)}
    board.save()
    _emit(cockpit, "kanvas.move", detail, action=action, task=task_id)
    return 200, dict(board.as_dict(), ok=True, detail=detail)


def start_chain(cockpit, project=None):
    """Arranca el ejecutor `yolo` en un hilo, bajo el mismo cap que un turno de chat."""
    root = _root(cockpit, project)
    board = Board.load(root)
    ready = board.ready(yolo_only=True)
    if not ready:
        return 400, {"ok": False, "reason": "no hay tareas con yolo listas (marca alguna con ⚡)"}
    if not cockpit.reserve():
        return 409, {"ok": False, "reason": "a job is already in flight"}
    STOP.clear()
    threading.Thread(target=_chain_worker, args=(cockpit, root), daemon=True,
                     name="kanvas-yolo").start()
    return 202, {"ok": True, "ready": [task.id for task in ready]}


def _chain_worker(cockpit, root):
    """La cadena entera, con el cap liberado pase lo que pase: un hilo muerto no deja la cabina ocupada."""
    from .autonomy.kanvas_runner import run_chain
    from .llm.judge import judge_for
    from .runner import run_triad
    from .verify.gate import Gate

    report = {}
    try:
        config = cockpit.config
        result_box = {}

        def run_task(task):
            goal = "%s: %s" % (task.id, task.title)
            result, _triad = run_triad(config, root, goal, cockpit.router, bus=cockpit.bus)
            result_box["last"] = result.as_dict()
            return result.as_dict()

        report = run_chain(root, run_task, gate=Gate(root, config),
                           judge=judge_for(cockpit.router, config), bus=cockpit.bus,
                           stop=STOP.is_set)
        cockpit.last = result_box.get("last") or cockpit.last
    except Exception as exc:  # noqa: BLE001 -- la cabina tiene que ver el fallo, no un hilo mudo
        cockpit.bus.emit("worker.error", "cadena yolo: %s: %s" % (type(exc).__name__, exc))
        report = {"done": [], "sent_back": [], "stopped": "%s: %s" % (type(exc).__name__, exc)}
    finally:
        cockpit.release()
    _emit(cockpit, "kanvas.chain", "cadena terminada: %d cerradas" % len(report.get("done") or []),
          **{key: report.get(key) for key in ("done", "sent_back", "stopped", "remaining", "steps")})
