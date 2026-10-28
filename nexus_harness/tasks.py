"""Bandeja de tareas local: el punto donde un bot, un cron o una persona dejan trabajo.

El daemon autonomo necesita una entrada que no sea "abre la ventana y escribe". Esta es deliberadamente
aburrida: un JSONL append-only en `.nexus/harness/inbox.jsonl`, con estados `queued -> claimed ->
done|failed`. Cualquier integracion (Discord, Telegram, un webhook, un `cron`) solo tiene que anadir
una linea con la misma forma; no necesita hablar con el motor.

Tres reglas:

* **Una tarea se reclama UNA vez.** `claim()` reescribe el fichero de forma atomica y marca la fila; dos
  daemons no pueden coger la misma tarea (ademas del cerrojo del daemon).
* **Una firma evita el bucle.** Si la misma mejora se encola cada tick, la bandeja acaba con 400 lineas
  identicas y el operador deja de mirarla. La firma se compara contra lo que sigue abierto.
* **Una linea rota no rompe la bandeja.** Se salta y se cuenta; el trabajo de los demas sigue.
"""
import json
import os
import time
import uuid
from pathlib import Path

REL = Path(".nexus") / "harness" / "inbox.jsonl"
STATES = ("queued", "claimed", "done", "failed")
MAX_ROWS = 2000


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _clean(text, limit=400):
    return " ".join(str(text or "").split())[:limit]


class Inbox:
    """La bandeja de un proyecto (o del workspace). Append-only al entrar, reescritura al cambiar estado."""

    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / REL

    # -- lectura -------------------------------------------------------------------------------
    def rows(self):
        """Todas las filas legibles, en orden de llegada. Las rotas se cuentan, no se inventan."""
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        rows = []
        for line in lines[-MAX_ROWS:]:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("id"):
                rows.append(row)
        return rows

    def open(self):
        return [row for row in self.rows() if row.get("state") in ("queued", "claimed")]

    def status(self):
        rows = self.rows()
        counts = {state: len([row for row in rows if row.get("state") == state]) for state in STATES}
        return {"path": str(self.path), "total": len(rows), "counts": counts,
                "open": [{"id": row["id"], "project": row.get("project"), "goal": row.get("goal")}
                         for row in self.open()][:10]}

    # -- escritura -----------------------------------------------------------------------------
    def add(self, project, goal, source="cli", priority=5, evidence="", signature=""):
        """Encola una tarea. Devuelve la fila, o la existente si la firma ya esta abierta."""
        goal = _clean(goal)
        if not goal:
            return {"ok": False, "reason": "una tarea sin objetivo no es una tarea"}
        signature = _clean(signature, 120)
        if signature:
            for row in self.open():
                if row.get("signature") == signature:
                    return dict(row, duplicate=True, ok=True)
        row = {"id": uuid.uuid4().hex[:12], "at": _now(), "state": "queued",
               "project": _clean(project, 120), "goal": goal, "source": _clean(source, 40),
               "priority": int(priority or 5), "evidence": _clean(evidence, 300),
               "signature": signature, "exit": None, "note": ""}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        except OSError as exc:
            return {"ok": False, "reason": "%s: %s" % (type(exc).__name__, exc)}
        return dict(row, ok=True, duplicate=False)

    def claim(self, limit=1):
        """Marca hasta `limit` tareas como reclamadas y las devuelve. Atomico por reescritura."""
        wanted = max(1, int(limit or 1))
        rows = self.rows()
        claimed = []
        for row in sorted(rows, key=lambda item: int(item.get("priority") or 5)):
            if len(claimed) >= wanted:
                break
            if row.get("state") != "queued":
                continue
            row["state"] = "claimed"
            row["claimed_at"] = _now()
            row["claimed_by"] = _host()
            claimed.append(row)
        if claimed:
            self._save(rows)
        return claimed

    def close(self, task_id, exit_code, note=""):
        """Cierra una tarea con el exit REAL. Devuelve la fila cerrada, o `None` si no existe."""
        rows = self.rows()
        for row in rows:
            if row.get("id") != str(task_id):
                continue
            row["exit"] = int(exit_code)
            row["state"] = "done" if int(exit_code) == 0 else "failed"
            row["closed_at"] = _now()
            row["note"] = _clean(note, 300)
            self._save(rows)
            return row
        return None

    def release(self, task_id, note=""):
        """Devuelve una tarea reclamada a la cola (el daemon murio a mitad)."""
        rows = self.rows()
        for row in rows:
            if row.get("id") == str(task_id) and row.get("state") == "claimed":
                row["state"] = "queued"
                row["note"] = _clean(note, 300)
                self._save(rows)
                return row
        return None

    def _save(self, rows):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text("".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n"
                                    for row in rows), encoding="utf-8")
            os.replace(temp, self.path)
            return True
        except OSError:
            return False


def _host():
    import socket
    try:
        return socket.gethostname()[:60]
    except OSError:
        return "?"
