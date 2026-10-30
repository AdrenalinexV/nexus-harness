"""El tablero, para los agentes: una herramienta con reglas, no un fichero que se edita a mano.

El Director descompone, el Obrero reclama y entrega, el operador aprueba. Lo que NO hay aqui es
`approve`: un modelo que firma su propio `done` es exactamente el agujero que este tablero cierra. El
cierre ocurre en el tablero (1 clic humano) o en el ejecutor `yolo` de `autonomy/`, que exige Gate verde
y Juez de acuerdo.
"""
from ...platform.kanvas import Board, KanvasError


def _load(root):
    return Board.load(root)


def _line(board, task):
    pending = board.pending_parents(task)
    tail = " (espera %s)" % ", ".join(pending) if pending else ""
    yolo = " ⚡" if task.yolo else ""
    owner = " @" + task.assigned_to if task.assigned_to else ""
    return "%s [%s]%s%s %s%s" % (task.id, board.effective(task), yolo, owner, task.title, tail)


def status(root, args=None, config=None):
    """Resumen + una linea por tarea. Es lo que lee un agente al empezar el turno (o tras un relevo)."""
    board = _load(root)
    stats = board.stats()
    counts = ", ".join("%s=%d" % (name, stats["counts"].get(name, 0)) for name in
                       ("proposed", "blocked", "todo", "doing", "review", "done"))
    head = "%s: %d/%d (%d%%) -- %s" % (board.project or "tablero", stats["done"], stats["total"],
                                       stats["percent"], counts)
    if not board.tasks:
        return head + "\n(vacio: `kanvas_board(action=\"decompose\", tasks=[...])` para empezar)", \
            {"files": [], "board": "vacio", "percent": 0}
    body = "\n".join(_line(board, task) for task in board.tasks)
    ready = [task.id for task in board.ready()]
    return head + "\n" + body + ("\nlistas: %s" % ", ".join(ready) if ready else ""), \
        {"files": [], "percent": stats["percent"], "ready": ready}


def propose(root, args, config=None):
    """Una tarea propuesta. `depends_on` son ids que ya tienen que existir."""
    board = _load(root)
    task = board.add(args.get("title"), track=args.get("track") or "core",
                     depends_on=args.get("depends_on") or [], task_id=args.get("task_id") or "",
                     status=args.get("status") or "proposed", yolo=bool(args.get("yolo")),
                     verify_cmd=args.get("verify_cmd") or "", by=args.get("by") or "director")
    board.save()
    return "propuesta %s [%s] %s" % (task.id, task.track, task.title), {
        "files": [], "task": task.id, "status": task.status}


def decompose(root, args, config=None):
    """Un grafo entero de una vez: `tasks=[{title, track, depends_on, verify_cmd}, ...]`.

    Todo o nada: si una dependencia no existe o cierra un ciclo, no se guarda ninguna. El modelo propone
    la descomposicion; el motor valida el DAG.
    """
    rows = [row for row in (args.get("tasks") or []) if isinstance(row, dict) and row.get("title")]
    if not rows:
        raise KanvasError("decompose necesita `tasks` con al menos un titulo")
    board = _load(root)
    created = []
    for row in rows[:40]:
        task = board.add(row.get("title"), track=row.get("track") or args.get("track") or "core",
                         depends_on=row.get("depends_on") or [], task_id=row.get("id") or "",
                         status=row.get("status") or "proposed", yolo=bool(row.get("yolo")),
                         verify_cmd=row.get("verify_cmd") or "", by=args.get("by") or "director")
        created.append(task)
    board.save()
    return "descompuesto en %d tareas:\n%s" % (len(created), "\n".join(
        "%s %s" % (task.id, task.title) for task in created)), {
        "files": [], "tasks": [task.id for task in created]}


def claim(root, args, config=None):
    """`todo` -> `doing`. Reclama el trabajo antes de tocarlo (para que dos agentes no colisionen)."""
    board = _load(root)
    task = board.claim(args.get("task") or args.get("task_id"), by=args.get("by") or "obrero")
    board.save()
    return "%s en curso con %s: %s" % (task.id, task.assigned_to, task.title), {
        "files": [], "task": task.id, "status": task.status}


def note(root, args, config=None):
    board = _load(root)
    task = board.note(args.get("task") or args.get("task_id"), args.get("text") or "",
                      by=args.get("by") or "obrero")
    board.save()
    return "nota en %s" % task.id, {"files": [], "task": task.id}


def submit_for_gate(root, args, config=None):
    """`doing` -> `review` con la evidencia: commits y el exit REAL del gate. Sin verde, no pasa."""
    board = _load(root)
    commits = args.get("commits") or []
    if isinstance(commits, str):
        commits = [item.strip() for item in commits.replace(",", " ").split() if item.strip()]
    task = board.submit(args.get("task") or args.get("task_id"), commits=commits,
                        gate=int(args.get("gate") if args.get("gate") is not None else 10),
                        judge=args.get("judge") or "", by=args.get("by") or "obrero")
    board.save()
    return "%s en review con gate exit %s y %d commit(s)" % (task.id, task.evidence.get("gate"),
                                                            len(task.commits)), {
        "files": [], "task": task.id, "status": task.status}


def toggle_yolo(root, args, config=None):
    """Marca la tarea (o su cadena) para que el ejecutor autonomo la pueda cerrar con Gate + Juez."""
    board = _load(root)
    task = board.toggle_yolo(args.get("task") or args.get("task_id"), chain=bool(args.get("chain")),
                             by=args.get("by") or "human")
    board.save()
    return "%s yolo=%s%s" % (task.id, task.yolo, " (cadena)" if args.get("chain") else ""), {
        "files": [], "task": task.id, "yolo": task.yolo}


ACTIONS = {"status": status, "propose": propose, "decompose": decompose, "claim": claim,
           "note": note, "submit_for_gate": submit_for_gate, "toggle_yolo": toggle_yolo}


def kanvas_board(root, args, config=None):
    """`kanvas_board(action=...)`. Una accion, un cambio, validado por el motor."""
    action = str((args or {}).get("action") or "status").strip()
    handler = ACTIONS.get(action)
    if handler is None:
        raise KanvasError("accion %r no existe (validas: %s)" % (action, ", ".join(sorted(ACTIONS))))
    return handler(root, args or {}, config)


HANDLERS = {"kanvas_board": kanvas_board}
