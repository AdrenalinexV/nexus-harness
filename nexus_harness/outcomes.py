"""Resultados por skill: lo que convierte un catalogo en memoria.

El fallo que arregla: `skill_router` puntuaba por lexico y extension, y nada mas. Una skill que viajo
en doce turnos rojos puntuaba exactamente igual que una que resolvio doce, asi que el arnes no podia
mejorar con el uso por mucho que forjase skills nuevas.

Aqui se apunta, por turno, QUE skills viajaron y como acabo: `(skill, project, exit, judge)`, una linea
por skill y turno en `.nexus/harness/skill_outcomes.jsonl`. De ahi sale un multiplicador bayesiano
suavizado que el enrutador aplica al score:

    rate  = (wins + PRIOR_WINS) / (uses + PRIOR_USES)      # sin muestras, 0,5: neutral
    boost = 0.7 + 0.6 * rate                                # entre 0,7 y 1,3

Suavizado y no proporcion cruda: una skill con 1 uso y 1 acierto no es mejor que una con 20 y 17. Y el
multiplicador esta acotado: la evidencia ajusta el orden, no lo secuestra.

Regla que no se relaja: un turno sin `exit` observado no apunta nada. Un resultado inventado envenena
el ranking para siempre.
"""
import json
import os
import time
from pathlib import Path

REL = Path(".nexus") / "harness" / "skill_outcomes.jsonl"
PRIOR_WINS, PRIOR_USES = 2.0, 4.0
MIN_BOOST, MAX_BOOST = 0.7, 1.3
MAX_ROWS = 5000


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _path(root):
    home = Path(os.environ.get("NEXUS_HOME") or (Path.home() / ".nexus"))
    return Path(root) / REL if root else home / "harness" / "skill_outcomes.jsonl"


class Outcomes:
    """El libro de resultados de las skills de un proyecto. Append-only y tolerante a basura."""

    def __init__(self, root=None, path=None):
        self.root = Path(root) if root else None
        self.path = Path(path) if path else _path(self.root)
        self._rates = None

    # -- escritura -----------------------------------------------------------------------------
    def record(self, names, exit, judge="", tag="", at=None):
        """Una fila por skill que viajo en un turno con veredicto. Devuelve cuantas se escribieron."""
        names = sorted({str(name) for name in names or () if str(name or "").strip()})
        if not names or exit is None:
            return 0
        try:
            code = int(exit)
        except (TypeError, ValueError):
            return 0
        row = {"at": at or _now(), "project": self.root.name if self.root else "",
               "exit": code, "judge": str(judge or ""), "tag": str(tag or ""),
               "win": code == 0, "skills": names}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        except OSError:
            return 0
        self._rates = None
        return len(names)

    # -- lectura -------------------------------------------------------------------------------
    def rows(self):
        """Todas las filas legibles. Una linea rota se salta: el libro no se cae por una coma."""
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
            if isinstance(row, dict) and row.get("skills"):
                rows.append(row)
        return rows

    def rates(self):
        """`{skill: {uses, wins, rate}}` con el suavizado ya aplicado a `rate`."""
        if self._rates is not None:
            return self._rates
        uses, wins = {}, {}
        for row in self.rows():
            for name in row.get("skills") or ():
                uses[name] = uses.get(name, 0) + 1
                if row.get("win"):
                    wins[name] = wins.get(name, 0) + 1
        self._rates = {name: {"uses": total, "wins": wins.get(name, 0),
                              "rate": round((wins.get(name, 0) + PRIOR_WINS) / (total + PRIOR_USES), 3)}
                       for name, total in uses.items()}
        return self._rates

    def multiplier(self, name):
        """El factor que el enrutador aplica al score de una skill. Sin muestras, neutral (1,0)."""
        row = self.rates().get(str(name or ""))
        if not row:
            return 1.0
        boost = 0.7 + 0.6 * float(row["rate"])
        return round(min(MAX_BOOST, max(MIN_BOOST, boost)), 3)

    def summary(self, limit=20):
        """Las skills con mas uso y su tasa, para la pantalla y para el informe."""
        rows = [dict(name=name, **data) for name, data in self.rates().items()]
        rows.sort(key=lambda item: (-item["uses"], item["name"]))
        return rows[:limit]

    def as_dict(self):
        return {"path": str(self.path), "rows": len(self.rows()), "skills": len(self.rates()),
                "top": self.summary(5)}


def record_skills(skills, root, exit, judge="", tag=""):
    """Apunta el resultado del turno para las skills que viajaron. Una linea por skill."""
    entries = getattr(skills, "last", None) or []
    names = [entry.get("name") for entry in entries
             if isinstance(entry, dict) and entry.get("name")]
    if not names or exit is None:
        return 0
    return Outcomes(root).record(names, exit, judge, tag)
