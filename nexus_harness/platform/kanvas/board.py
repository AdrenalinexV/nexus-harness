"""El tablero: carriles, tareas y una maquina de estados que no se puede saltar a la torera.

La idea viene de Kanvas (XMihura/Kanvas) y del Kanban de Hermes: el plan vive en un fichero JSON
versionable, no en la cabeza de una sesion, y los agentes no lo editan a mano -- pasan por reglas. Aqui
la diferencia es quien firma el `done`: **nadie lo pone sin evidencia verde del Gate**, ni el operador
por la cara. En modo `yolo` el motor exige ademas el veredicto del Juez.

Tres decisiones que sostienen el resto:

* **`blocked` se calcula, no se escribe.** Una tarea cuyos padres no estan `done` esta bloqueada aunque
  su estado guardado sea `todo`; en cuanto el ultimo padre cierra, se desbloquea sola. Guardar
  `blocked` a mano seria una segunda verdad que se queda vieja al primer cambio de padre.
* **`done` es final.** Reabrir es crear otra tarea con nota: un tablero que se reescribe no audita nada.
* **Un fichero, atomico.** `.nexus/kanvas.json` se escribe con `os.replace`, asi que un turno que muere
  a mitad no deja medio tablero.

Nada de red, nada de dependencias: solo stdlib, para que el tablero se pueda leer y validar desde un
script, desde el CLI o desde el `.exe` congelado.
"""
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

BOARD_REL = Path(".nexus") / "kanvas.json"
FORMAT = 1
STATUSES = ("proposed", "blocked", "todo", "doing", "review", "done")
STORED = ("proposed", "todo", "doing", "review", "done")
AGENTS = ("director", "obrero", "subagent", "human")
# Lo que la maquina permite. `blocked` no aparece como destino: se calcula.
ALLOWED = {
    "proposed": ("todo",),
    "todo": ("doing", "proposed"),
    "doing": ("review", "todo"),
    "review": ("done", "doing"),
    "done": (),
}


class KanvasError(ValueError):
    """Un movimiento que el tablero no permite, con la razon escrita."""


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class Task:
    """Un nodo del grafo. Los estados viven en `status`; `yolo` autoriza el cierre automatico."""

    id: str
    title: str
    track: str = "core"
    status: str = "proposed"
    depends_on: list = field(default_factory=list)
    yolo: bool = False
    verify_cmd: str = ""
    assigned_to: str = ""
    commits: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, row):
        return cls(id=str(row.get("id") or ""), title=str(row.get("title") or ""),
                   track=str(row.get("track") or "core"), status=str(row.get("status") or "proposed"),
                   depends_on=[str(item) for item in row.get("depends_on") or []],
                   yolo=bool(row.get("yolo")), verify_cmd=str(row.get("verify_cmd") or ""),
                   assigned_to=str(row.get("assigned_to") or ""),
                   commits=[str(item) for item in row.get("commits") or []],
                   notes=list(row.get("notes") or []), evidence=dict(row.get("evidence") or {}))

    def as_dict(self):
        return {"id": self.id, "title": self.title, "track": self.track, "status": self.status,
                "depends_on": list(self.depends_on), "yolo": self.yolo,
                "verify_cmd": self.verify_cmd, "assigned_to": self.assigned_to,
                "commits": list(self.commits), "notes": list(self.notes),
                "evidence": dict(self.evidence)}


class Board:
    """El tablero de un proyecto: carriles, tareas y las reglas. Sin red y sin reloj propio."""

    def __init__(self, project="", tracks=None, tasks=None, path=None, updated_at=""):
        self.project = str(project or "")
        self.tracks = [dict(row) for row in (tracks or DEFAULT_TRACKS)]
        self.tasks = list(tasks or [])
        self.path = Path(path) if path else None
        self.updated_at = updated_at or _now()

    # -- carga y guardado ---------------------------------------------------------------------
    @classmethod
    def load(cls, root):
        """El tablero del proyecto, o uno vacio con los carriles por defecto. Nunca lanza por ausencia."""
        path = Path(root) / BOARD_REL
        if not path.is_file():
            return cls(project=Path(root).name, tracks=DEFAULT_TRACKS, path=path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise KanvasError("%s no es JSON valido: %s" % (path, exc)) from exc
        return cls(project=str(data.get("project") or Path(root).name),
                   tracks=data.get("tracks") or DEFAULT_TRACKS,
                   tasks=[Task.from_dict(row) for row in data.get("tasks") or []],
                   path=path, updated_at=str(data.get("updated_at") or ""))

    def save(self, path=None):
        """Escribe el fichero entero de una vez: un turno que muere a mitad no deja medio tablero."""
        target = Path(path or self.path or BOARD_REL)
        self.updated_at = _now()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"format": FORMAT, "project": self.project, "updated_at": self.updated_at,
                   "tracks": self.tracks, "tasks": [task.as_dict() for task in self.tasks]}
        temp = target.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, target)
        self.path = target
        return target

    # -- consultas ----------------------------------------------------------------------------
    def get(self, task_id):
        for task in self.tasks:
            if task.id == str(task_id):
                return task
        return None

    def _done(self, task_id):
        task = self.get(task_id)
        return bool(task and task.status == "done")

    def pending_parents(self, task):
        """Los padres que aun no estan `done`. Un id que no existe cuenta como pendiente: no se finge."""
        return [parent for parent in task.depends_on if not self._done(parent)]

    def effective(self, task):
        """El estado que se PINTA: `blocked` se deriva de los padres, no se guarda."""
        if task.status == "done":
            return "done"
        if task.status != "proposed" and self.pending_parents(task):
            return "blocked"
        return task.status

    def ready(self, yolo_only=False):
        """Tareas que se pueden empezar ahora: `todo`, padres cerrados, y (si se pide) marcadas yolo."""
        return [task for task in self.tasks
                if self.effective(task) == "todo" and (task.yolo or not yolo_only)]

    def stats(self):
        counts = {status: 0 for status in STATUSES}
        for task in self.tasks:
            counts[self.effective(task)] = counts.get(self.effective(task), 0) + 1
        total = len(self.tasks)
        done = counts.get("done", 0)
        return {"total": total, "done": done, "percent": (done * 100 // total) if total else 0,
                "counts": counts, "tracks": [row.get("id") for row in self.tracks]}

    def cycles(self):
        """Los ciclos del grafo, si los hay. Se comprueban al crear, no al pintar."""
        state, found = {}, []

        def walk(node, trail):
            if state.get(node) == 1:
                found.append(trail[trail.index(node):] + [node])
                return
            if state.get(node) == 2:
                return
            state[node] = 1
            task = self.get(node)
            for parent in (task.depends_on if task else []):
                walk(parent, trail + [parent])
            state[node] = 2

        for task in self.tasks:
            walk(task.id, [task.id])
        return found

    def as_dict(self):
        """Lo que consume la cabina: tareas con su estado EFECTIVO y el resumen ya contado."""
        rows = []
        for task in self.tasks:
            row = task.as_dict()
            row["status"] = self.effective(task)
            row["stored_status"] = task.status
            row["pending"] = self.pending_parents(task)
            rows.append(row)
        return {"project": self.project, "updated_at": self.updated_at, "tracks": self.tracks,
                "tasks": rows, "stats": self.stats()}

    # -- mutaciones ---------------------------------------------------------------------------
    def add(self, title, track="core", depends_on=None, task_id="", status="proposed", yolo=False,
            verify_cmd="", assigned_to="", by="director"):
        """Crea una tarea. El id se acuna si no viene; las dependencias tienen que existir y no cerrar ciclo."""
        title = str(title or "").strip()
        if not title:
            raise KanvasError("una tarea sin titulo no se puede ejecutar")
        track = str(track or "core")
        if track not in {row.get("id") for row in self.tracks}:
            raise KanvasError("el carril %r no existe (hay: %s)"
                              % (track, ", ".join(row.get("id") or "" for row in self.tracks)))
        if status not in ("proposed", "todo"):
            # Crear algo ya `done` seria el atajo que este tablero existe para cerrar: se nace propuesto
            # o en la cola, y se cierra con evidencia como todo el mundo.
            raise KanvasError("una tarea nace `proposed` o `todo`, no %r" % status)
        parents = [str(item) for item in depends_on or []]
        missing = [parent for parent in parents if self.get(parent) is None]
        if missing:
            raise KanvasError("dependencias inexistentes: %s" % ", ".join(missing))
        if task_id and self.get(task_id) is not None:
            raise KanvasError("la tarea %s ya existe" % task_id)
        task = Task(id=task_id or self._next_id(), title=title, track=track, status=status,
                    depends_on=parents, yolo=bool(yolo), verify_cmd=str(verify_cmd or ""),
                    assigned_to=str(assigned_to or ""))
        self.tasks.append(task)
        if self.cycles():
            self.tasks.pop()
            raise KanvasError("esa dependencia cierra un ciclo")
        task.notes.append({"at": _now(), "by": str(by or "director"), "text": "creada"})
        return task

    def _next_id(self):
        numbers = [int(task.id.split("-")[-1]) for task in self.tasks
                   if task.id.startswith("TK-") and task.id.split("-")[-1].isdigit()]
        return "TK-%02d" % ((max(numbers) if numbers else 0) + 1)

    def move(self, task_id, status, by="director", evidence=None):
        """El unico porton. Valida destino, dependencias, firma y evidencia. Devuelve la tarea."""
        task = self.get(task_id)
        if task is None:
            raise KanvasError("no existe la tarea %r" % task_id)
        by = str(by or "director")
        if by not in AGENTS:
            raise KanvasError("quien firma debe ser uno de %s, no %r" % (", ".join(AGENTS), by))
        if status == "blocked":
            raise KanvasError("`blocked` se calcula con las dependencias; no se pone a mano")
        if status not in STORED:
            raise KanvasError("estado invalido: %r (validos: %s)" % (status, ", ".join(STORED)))
        if status not in ALLOWED.get(task.status, ()):
            raise KanvasError("%s no puede pasar de %s a %s" % (task.id, task.status, status))
        if status in ("doing", "review", "done"):
            pending = self.pending_parents(task)
            if pending:
                raise KanvasError("%s tiene padres pendientes: %s" % (task.id, ", ".join(pending)))
        if status in ("review", "done"):
            self._require_evidence(task, status, evidence or {}, by)
        task.status = status
        if status == "doing":
            task.assigned_to = str((evidence or {}).get("assigned_to") or task.assigned_to or "obrero")
        task.notes.append({"at": _now(), "by": by, "text": "-> %s" % status})
        return task

    def _require_evidence(self, task, status, evidence, by):
        """Sin commit y sin gate verde no hay revision; sin gate verde y Juez no hay `done`."""
        gate = evidence.get("gate", (task.evidence or {}).get("gate"))
        judge = evidence.get("judge", (task.evidence or {}).get("judge"))
        commits = evidence.get("commits") or task.commits
        # Un commit es la prueba de siempre; un diff de ficheros tocados con gate verde tambien lo es (el
        # Triad del modo yolo no siempre commitea: el commit es del operador o del turno de noche).
        touched = list(evidence.get("touched") or (task.evidence or {}).get("touched") or [])
        if status == "review" and not (commits or touched):
            raise KanvasError("%s no pasa a review sin un commit o un diff adjunto" % task.id)
        if gate is None:
            raise KanvasError("%s no pasa a %s sin resultado del gate" % (task.id, status))
        if int(gate) != 0:
            raise KanvasError("%s no pasa a %s con el gate en exit %s: repara primero"
                              % (task.id, status, gate))
        if status == "done" and judge and judge != "approve":
            raise KanvasError("%s no pasa a done: el Juez dijo %r" % (task.id, judge))
        if status == "done" and not (commits or touched):
            raise KanvasError("%s no pasa a done sin evidencia (commits o diff)" % task.id)
        if evidence:
            task.evidence = {"gate": int(gate), "judge": judge or "", "commits": list(commits),
                             "touched": touched, "at": _now(), "by": by}
            for commit in commits:
                if commit not in task.commits:
                    task.commits.append(commit)

    def claim(self, task_id, by="obrero"):
        """`todo` -> `doing`. Reclamar una propuesta implica aceptarla: pasa antes por `todo`.

        Es el unico atajo del tablero y esta escrito: el agente que dice "lo tomo" esta haciendo el
        triaje que en Kanvas hace una persona, y sin el la propuesta se quedaria muerta para siempre.
        """
        task = self.get(task_id)
        if task is None:
            raise KanvasError("no existe la tarea %r" % task_id)
        if task.status == "proposed":
            self.move(task_id, "todo", by=by)
        return self.move(task_id, "doing", by=by, evidence={"assigned_to": by})

    def submit(self, task_id, commits=(), gate=10, judge="", by="obrero", touched=()):
        """El agente pide revision con lo que tiene: commits, ficheros tocados y el exit real del gate."""
        return self.move(task_id, "review", by=by,
                         evidence={"commits": list(commits), "gate": int(gate), "judge": judge,
                                   "touched": list(touched)})

    def approve(self, task_id, by="human", judge=""):
        """El cierre: humano con 1 clic en modo normal, o el motor en `yolo` con Juez verde."""
        return self.move(task_id, "done", by=by, evidence={"judge": judge} if judge else None)

    def send_back(self, task_id, by="human", reason=""):
        """Devuelve el trabajo al obrero. Si ya esta en `doing`, solo se anota el motivo.

        El ejecutor `yolo` reclama antes de correr, asi que un gate rojo devuelve una tarea que YA esta
        en `doing`; mover `doing -> doing` no es un movimiento, es una nota.
        """
        task = self.get(task_id)
        if task is None:
            raise KanvasError("no existe la tarea %r" % task_id)
        if task.status != "doing":
            task = self.move(task_id, "doing", by=by)
        if reason:
            self.note(task_id, reason, by=by)
        return task

    def note(self, task_id, text, by="director"):
        task = self.get(task_id)
        if task is None:
            raise KanvasError("no existe la tarea %r" % task_id)
        task.notes.append({"at": _now(), "by": str(by or "director"), "text": str(text or "")[:600]})
        return task

    def toggle_yolo(self, task_id, chain=False, by="human"):
        """Marca (o desmarca) una tarea; con `chain`, toda su descendencia."""
        task = self.get(task_id)
        if task is None:
            raise KanvasError("no existe la tarea %r" % task_id)
        wanted = not task.yolo
        task.notes.append({"at": _now(), "by": by,
                           "text": "yolo %s%s" % ("on" if wanted else "off", " (cadena)" if chain else "")})
        for target in [task] + (self.descendants(task.id) if chain else []):
            target.yolo = wanted
            # Autorizar la ejecucion ES el triaje: una propuesta marcada yolo pasa a `todo` para que el
            # ejecutor la vea lista. Sin esto, "activar yolo en cadena" no arrancaria ninguna.
            if wanted and target.status == "proposed":
                self.move(target.id, "todo", by=by)
        return task

    def descendants(self, task_id):
        """Las tareas que dependen (directa o indirectamente) de esta, en orden estable."""
        found, seen, pending = [], {str(task_id)}, [str(task_id)]
        while pending:
            current = pending.pop(0)
            for task in self.tasks:
                if current in task.depends_on and task.id not in seen:
                    seen.add(task.id)
                    found.append(task)
                    pending.append(task.id)
        return found


DEFAULT_TRACKS = ({"id": "core", "title": "Core Engine"}, {"id": "ui", "title": "UI & UX"},
                  {"id": "tests", "title": "Tests & Gate"}, {"id": "release", "title": "Release"})
