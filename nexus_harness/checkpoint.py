"""Deshacer un turno: cada escritura deja los bytes que habia antes, y `undo` deja el arbol igual.

Tres decisiones, las tres con una consecuencia medible:

* **La instantanea es del turno, no del fichero.** El diario guarda la PRIMERA version de cada ruta
  dentro del turno, asi que deshacer cinco escrituras sobre el mismo fichero devuelve el original y no
  el penultimo estado -- que es lo unico util cuando el turno entero salio mal.
* **Se guardan bytes, no texto.** Un fichero con BOM y CRLF vuelve con su BOM y sus CRLF, porque el
  blob es lo que habia en disco y la restauracion pasa por `file_ops.atomic_write_bytes`, el mismo
  suelo verificado por sha256 que usa cualquier otra escritura del arnes.
* **Una instantanea que falta es un fallo, no un silencio.** Si el blob desaparecio o su hash no
  cuadra, `undo` lo declara (`ok=False` y la ruta en `skipped`) en vez de contar media restauracion
  como exito. Claude Code falla con `No files were restored` por el mismo motivo.

El diario no es git y no lo pretende: git ya esta en el repositorio del operador y aqui hace falta
poder volver atras **sin** repositorio, en el modo sin dependencias del arnes.
"""
import hashlib
import json
import shutil
from pathlib import Path

from .tools.toolbox import file_ops

MANIFEST = "manifest.json"
BLOBS = "blobs"
KEEP_TURNS = 20


def _digest(payload):
    return hashlib.sha256(payload).hexdigest()


class Journal:
    """Las escrituras de un turno, con los bytes que cada ruta tenia antes de que el turno la tocara."""

    def __init__(self, root, directory, label=""):
        self.root = Path(root).resolve()
        self.directory = Path(directory)
        self.label = label
        self.entries = []
        self.undone = False

    @property
    def name(self):
        return self.directory.name

    def record(self, path, previous):
        """Anota `path` con sus bytes de antes (`None` si no existia). Repetir una ruta no re-anota."""
        relative = file_ops.relative(self.root, path)
        if any(entry["path"] == relative for entry in self.entries):
            return relative
        blob, digest = "", ""
        if previous is not None:
            (self.directory / BLOBS).mkdir(parents=True, exist_ok=True)
            blob = "%s/%03d.bin" % (BLOBS, len(self.entries))
            (self.directory / blob).write_bytes(previous)
            digest = _digest(previous)
        self.entries.append({"path": relative, "existed": previous is not None,
                             "blob": blob, "sha256": digest})
        self.flush()
        return relative

    def flush(self):
        """El manifiesto, en bytes: `atomic_write_bytes` no consulta el diario, asi que no se anota."""
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {"root": str(self.root), "label": self.label, "undone": self.undone,
                   "entries": self.entries}
        file_ops.atomic_write_bytes(self.directory / MANIFEST, json.dumps(payload, indent=1).encode("utf-8"))

    def undo(self):
        """Devuelve el arbol a antes del turno. Informa siempre; no levanta por una ruta que falta."""
        if self.undone:
            return {"ok": True, "turn": self.name, "restored": 0, "deleted": 0, "skipped": [],
                    "note": "ya estaba deshecho"}
        restored, deleted, skipped = 0, 0, []
        for entry in self.entries:
            target = self.root / entry["path"]
            if not entry["existed"]:
                if target.is_file():
                    target.unlink()
                    deleted += 1
                continue
            blob = self.directory / entry["blob"]
            payload = blob.read_bytes() if blob.is_file() else b""
            if not payload or _digest(payload) != entry["sha256"]:
                skipped.append(entry["path"])
                continue
            file_ops.atomic_write_bytes(target, payload)
            restored += 1
        self.undone = True
        self.flush()
        return {"ok": not skipped, "turn": self.name, "restored": restored, "deleted": deleted,
                "skipped": skipped,
                "note": "" if not skipped else "instantanea ausente o corrupta"}

    def as_dict(self):
        return {"turn": self.name, "label": self.label, "undone": self.undone,
                "files": len(self.entries), "paths": [entry["path"] for entry in self.entries]}


def checkpoints_dir(root):
    return Path(root).resolve() / ".nexus" / "checkpoints"


def _slug(label):
    clean = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(label or ""))[:24]
    return clean.strip("-") or "turno"


def _next_dir(base, label):
    numbers = []
    if base.is_dir():
        for item in base.iterdir():
            head = item.name.split("-")[0]
            if item.is_dir() and head.isdigit():
                numbers.append(int(head))
    return base / ("%04d-%s" % (max(numbers, default=0) + 1, _slug(label)))


def begin(root, label="turno"):
    """Un diario nuevo para el turno, en `<root>/.nexus/checkpoints/NNNN-slug`."""
    journal = Journal(root, _next_dir(checkpoints_dir(root), label), label)
    journal.flush()
    prune(root)
    return journal


def load(directory):
    """Reabre un diario desde su manifiesto: es lo que permite deshacer desde otro proceso."""
    payload = json.loads((Path(directory) / MANIFEST).read_text(encoding="utf-8"))
    journal = Journal(payload.get("root") or directory, directory, payload.get("label", ""))
    journal.entries = list(payload.get("entries") or [])
    journal.undone = bool(payload.get("undone"))
    return journal


def history(root):
    """Los diarios del proyecto, del mas nuevo al mas viejo. Un manifiesto ilegible no tumba la lista."""
    base = checkpoints_dir(root)
    found = []
    if base.is_dir():
        for item in base.iterdir():
            if (item / MANIFEST).is_file():
                try:
                    found.append(load(item))
                except (OSError, ValueError):
                    continue
    return sorted(found, key=lambda journal: journal.name, reverse=True)


def latest(root):
    return next(iter(history(root)), None)


def find(root, name):
    return next((journal for journal in history(root) if journal.name == name), None)


def prune(root, keep=KEEP_TURNS):
    """Solo los ultimos `keep` turnos: un diario viejo es disco, no historia."""
    stale = history(root)[keep:]
    for journal in stale:
        shutil.rmtree(journal.directory, ignore_errors=True)
    return [journal.name for journal in stale]


def set_active(journal):
    """Arma (o desarma con `None`) el diario que `file_ops` consulta antes de cada escritura."""
    return file_ops.set_journal(journal)


def active():
    return file_ops.journal()
