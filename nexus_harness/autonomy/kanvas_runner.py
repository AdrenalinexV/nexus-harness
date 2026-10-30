"""El modo YOLO: una rama del tablero se ejecuta sola, y el `done` lo firman el Gate y el Juez.

Kanvas deja que el humano confie o que el agente se autodeclare `done`. Aqui el cierre automatico exige
DOS cosas y las dos se miden: el gate del proyecto en verde (lint Nexus, ley de 400, tests) y el Juez
independiente sin objeciones. Si cualquiera de las dos falla, la tarea VUELVE al obrero con el motivo
escrito y el bucle se detiene en vez de encadenar la siguiente: seguir construyendo sobre rojo es como
se pierde un dia.

El ejecutor no sabe llamar al modelo: recibe `run_task(tarea) -> {exit, commits, touched, summary}`.
Asi la suite mide la gobernanza con dobles y en produccion la conecta la cabina con su Triad.
"""
from ..platform.kanvas import Board, KanvasError


def _emit(bus, kind, detail="", **payload):
    if bus is not None:
        bus.emit(kind, detail, **payload)


def run_chain(root, run_task, gate, judge=None, board=None, limit=8, bus=None, by="obrero",
              stop=None):
    """Ejecuta las tareas `yolo` que esten listas, en orden de grafo, hasta que no quede ninguna.

    Devuelve un informe: `done` (ids cerrados), `stopped` (por que se paro) y `remaining`.
    """
    board = board or Board.load(root)
    report = {"project": board.project, "done": [], "sent_back": [], "stopped": "", "steps": 0}
    for _ in range(max(1, int(limit))):
        if stop is not None and stop():
            report["stopped"] = "detenido por el operador"
            break
        ready = board.ready(yolo_only=True)
        if not ready:
            break
        task = ready[0]
        board.claim(task.id, by=by)
        board.save()
        report["steps"] += 1
        _emit(bus, "kanvas.claim", "%s: %s" % (task.id, task.title), task=task.id, title=task.title,
              track=task.track)
        try:
            result = run_task(task) or {}
        except Exception as exc:  # noqa: BLE001 -- un obrero que revienta se declara, no se esconde
            board.send_back(task.id, by=by, reason="el obrero fallo: %s: %s" % (type(exc).__name__, exc))
            board.save()
            report["sent_back"].append(task.id)
            report["stopped"] = "%s: el obrero fallo (%s)" % (task.id, type(exc).__name__)
            _emit(bus, "kanvas.stopped", report["stopped"], task=task.id)
            break
        verdict = _gate(task, result, gate)  # el veredicto de la Triada manda si ya lo trae
        exit_code = int(getattr(verdict, "exit", verdict if isinstance(verdict, int) else 10))
        summary = str(result.get("summary") or "")[:2000]
        touched = list(result.get("touched") or [])
        judge_verdict = ""
        judged = result.get("judgement") or {}
        if exit_code == 0 and judge is not None and not judged:
            judgement = judge.review(task.title, summary, touched)
            judge_verdict = str(getattr(judgement, "verdict", "") or "")
        else:
            judge_verdict = str(judged.get("verdict") or "")
        commits = [str(item) for item in result.get("commits") or []]
        _emit(bus, "kanvas.gate", "%s: exit %s%s" % (task.id, exit_code,
                                                    ", juez %s" % judge_verdict if judge_verdict else ""),
              task=task.id, gate=exit_code, judge=judge_verdict)
        if exit_code == 0 and judge_verdict in ("", "approve"):
            try:
                # El cierre pasa por `review` como el de un humano: misma evidencia, mismo rastro. Un
                # salto directo a `done` seria un atajo que el tablero no permite ni al motor.
                board.submit(task.id, commits=commits, gate=0, judge=judge_verdict, by=by,
                             touched=touched)
                board.move(task.id, "done", by=by, evidence={"gate": 0, "judge": judge_verdict,
                                                            "commits": commits, "touched": touched})
            except KanvasError as exc:
                board.send_back(task.id, by=by, reason=str(exc))
                board.save()
                report["sent_back"].append(task.id)
                report["stopped"] = "%s: %s" % (task.id, exc)
                break
            board.save()
            report["done"].append(task.id)
            _emit(bus, "kanvas.done", "%s cerrada por el gate" % task.id, task=task.id)
            continue
        reason = "gate exit %s" % exit_code if exit_code else "el Juez dijo %r" % judge_verdict
        board.send_back(task.id, by=by, reason="rechazo automatico: %s" % reason)
        board.save()
        report["sent_back"].append(task.id)
        report["stopped"] = "%s: %s" % (task.id, reason)
        _emit(bus, "kanvas.stopped", report["stopped"], task=task.id, gate=exit_code)
        break
    report["remaining"] = len([task for task in board.tasks if board.effective(task) != "done"])
    return report


def _gate(task, result, gate):
    """El veredicto de ESTA tarea: el que ya trae la Triada, su `verify_cmd`, o el gate del proyecto."""
    if result.get("verdict") is not None:
        return result["verdict"]
    if task.verify_cmd:
        return gate.run_command(task.verify_cmd) if hasattr(gate, "run_command") else gate.run(
            list(result.get("touched") or []))
    return gate.run(list(result.get("touched") or []))
