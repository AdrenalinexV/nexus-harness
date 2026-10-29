"""Memoria por capas: lo que el arnes sabe del operador y del proyecto, sin pagarlo en cada prompt.

El fallo que arregla: `memory.md` es un bloque plano que viaja entero en cada turno y crece hasta el
techo; la historia (que paso, cuando, con que exit) no se guardaba en ningun sitio consultable.

Aqui hay cuatro capas, y cada una se paga distinto:

* **core** — hechos estables del operador (2-6 lineas). Viaja SIEMPRE en el prefijo, con techo duro.
* **episode** — un turno cerrado: proyecto, objetivo, exit, ficheros. **No** viaja: se recupera por
  consulta cuando hace falta.
* **fact** — una preferencia o regla aprendida, con su evidencia y su confianza. Se recupera igual.
* **procedure** — puntero a una skill (nombre, ruta, sha256); el cuerpo vive en su `SKILL.md`.

La recuperacion es **FTS5** (BM25) con un presupuesto de caracteres: se traen las filas que responden a
la consulta y se cortan al presupuesto, con recibo. Sin consulta relevante no se trae nada: cero tokens.

Reglas que la mantienen honesta:

* un `fact` sin evidencia no se escribe (una preferencia inventada envenena todos los turnos);
* la misma frase no se guarda dos veces (hash normalizado);
* `prune` borra episodios viejos por edad, no los "resume" con un modelo: un resumen alucinado en la
  memoria es peor que un episodio que falta.
"""
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path

REL = Path(".nexus") / "harness" / "recall.db"
CORE_CHARS = 700
QUERY_CHARS = 500
MAX_K = 8
PRUNE_DAYS = 120
SPACE = re.compile(r"\s+")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _flat(text, limit=2000):
    return SPACE.sub(" ", str(text or "")).strip()[:limit]


def _hash(text):
    return hashlib.sha256(_flat(text).lower().encode("utf-8", "replace")).hexdigest()[:24]


class Recall:
    """La base de memoria de un proyecto. Sin dependencias: `sqlite3` de la biblioteca estandar."""

    def __init__(self, root, path=None):
        self.root = Path(root)
        self.path = Path(path) if path else self.root / REL
        self._ready = False
        self._fts = True

    # -- esquema -------------------------------------------------------------------------------
    def connect(self):
        if self.path.parent and not self.path.parent.is_dir():
            self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=5)
        connection.row_factory = sqlite3.Row
        if not self._ready:
            self._migrate(connection)
            self._ready = True
        return connection

    def _migrate(self, connection):
        connection.executescript(
            "CREATE TABLE IF NOT EXISTS rows ("
            " id TEXT PRIMARY KEY, kind TEXT NOT NULL, project TEXT DEFAULT '',"
            " text TEXT NOT NULL, evidence TEXT DEFAULT '', confidence REAL DEFAULT 0.5,"
            " at TEXT NOT NULL, hits INTEGER DEFAULT 0);")
        try:
            connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5("
                               " id UNINDEXED, text, project, kind);")
        except sqlite3.OperationalError:
            self._fts = False      # sqlite sin FTS5: se busca con LIKE y se declara
        connection.commit()

    # -- escritura -----------------------------------------------------------------------------
    def add(self, kind, text, evidence="", project="", confidence=0.5):
        """Guarda una fila. Sin evidencia no se guarda un `fact`; un duplicado no se repite."""
        kind = str(kind or "").strip().lower()
        body = _flat(text, 4000)
        if kind not in ("core", "episode", "fact", "procedure"):
            return {"ok": False, "reason": "capa desconocida: %r" % kind}
        if not body:
            return {"ok": False, "reason": "una memoria vacia no dice nada"}
        if kind == "fact" and not _flat(evidence):
            return {"ok": False, "reason": "un hecho sin evidencia no se escribe"}
        digest = _hash("%s|%s" % (kind, body))
        try:
            with self.connect() as connection:
                existing = connection.execute("SELECT id FROM rows WHERE id = ?",
                                              (digest,)).fetchone()
                if existing:
                    return {"ok": True, "id": digest, "duplicate": True}
                connection.execute(
                    "INSERT INTO rows (id, kind, project, text, evidence, confidence, at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (digest, kind, _flat(project, 120), body, _flat(evidence, 600),
                     float(confidence or 0.5), _now()))
                if self._fts:
                    connection.execute("INSERT INTO search (id, text, project, kind) VALUES (?,?,?,?)",
                                       (digest, body, _flat(project, 120), kind))
                connection.commit()
        except sqlite3.Error as exc:
            return {"ok": False, "reason": "%s: %s" % (type(exc).__name__, exc)}
        return {"ok": True, "id": digest, "duplicate": False}

    def forget(self, needle):
        """Borra lo que contenga `needle`. Devuelve cuantas filas se fueron."""
        text = _flat(needle).lower()
        if not text:
            return 0
        try:
            with self.connect() as connection:
                rows = connection.execute("SELECT id, text FROM rows").fetchall()
                doomed = [row["id"] for row in rows if text in str(row["text"]).lower()]
                for row_id in doomed:
                    connection.execute("DELETE FROM rows WHERE id = ?", (row_id,))
                    if self._fts:
                        connection.execute("DELETE FROM search WHERE id = ?", (row_id,))
                connection.commit()
        except sqlite3.Error:
            return 0
        return len(doomed)

    # -- lectura -------------------------------------------------------------------------------
    def core(self, limit=CORE_CHARS):
        """Los hechos estables, recortados. Es lo unico que viaja sin que nadie pregunte."""
        try:
            with self.connect() as connection:
                rows = connection.execute(
                    "SELECT text FROM rows WHERE kind = 'core' ORDER BY at DESC LIMIT 12").fetchall()
        except sqlite3.Error:
            return ""
        lines, budget = [], int(limit)
        for row in rows:
            line = "- %s" % _flat(row["text"], 400)
            if len(line) > budget:
                break
            lines.append(line)
            budget -= len(line)
        return "\n".join(reversed(lines))

    def search(self, query, k=MAX_K, budget=QUERY_CHARS):
        """Las filas que responden a la consulta, en orden BM25 y cortadas al presupuesto."""
        terms = [word for word in re.findall(r"[a-zA-Z0-9_]{3,}", _flat(query).lower())][:12]
        if not terms:
            return []
        try:
            with self.connect() as connection:
                rows = self._query(connection, terms, k)
        except sqlite3.Error:
            return []
        picked, used = [], 0
        for row in rows:
            item = {"id": row["id"], "kind": row["kind"], "project": row["project"],
                    "text": _flat(row["text"], 600), "at": row["at"],
                    "confidence": round(float(row["confidence"] or 0.5), 2)}
            cost = len(item["text"]) + 40
            if used + cost > int(budget) and picked:
                break
            picked.append(item)
            used += cost
        return picked

    def _query(self, connection, terms, k):
        if self._fts:
            match = " OR ".join('"%s"' % term for term in terms)
            try:
                return connection.execute(
                    "SELECT rows.* FROM search JOIN rows ON rows.id = search.id"
                    " WHERE search MATCH ? ORDER BY bm25(search), rows.at DESC LIMIT ?",
                    (match, int(k))).fetchall()
            except sqlite3.OperationalError:
                self._fts = False
        like = " OR ".join("lower(text) LIKE ?" for _ in terms)
        params = ["%%%s%%" % term for term in terms]
        return connection.execute(
            "SELECT * FROM rows WHERE %s ORDER BY at DESC LIMIT ?" % like,
            params + [int(k)]).fetchall()

    def block(self, query="", budget=QUERY_CHARS):
        """Lo que se inyecta en un turno: core siempre, y lo relevante a la consulta si cabe."""
        parts = []
        core = self.core()
        if core:
            parts.append("## Lo que sé del operador\n%s" % core)
        if query:
            rows = self.search(query, k=4, budget=budget)
            if rows:
                lines = ["## Memoria relevante"]
                for row in rows:
                    lines.append("- [%s] %s%s" % (row["kind"], row["text"],
                                                  (" (%s)" % row["project"]) if row["project"] else ""))
                parts.append("\n".join(lines))
        return "\n\n".join(parts)

    # -- mantenimiento -------------------------------------------------------------------------
    def prune(self, days=PRUNE_DAYS):
        """Olvida episodios viejos. No los resume: un resumen inventado en memoria es peor."""
        if int(days) <= 0:
            return 0
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                               time.gmtime(time.time() - int(days) * 86400))
        try:
            with self.connect() as connection:
                doomed = [row["id"] for row in connection.execute(
                    "SELECT id FROM rows WHERE kind = 'episode' AND at < ?", (cutoff,)).fetchall()]
                for row_id in doomed:
                    connection.execute("DELETE FROM rows WHERE id = ?", (row_id,))
                    if self._fts:
                        connection.execute("DELETE FROM search WHERE id = ?", (row_id,))
                connection.commit()
        except sqlite3.Error:
            return 0
        return len(doomed)

    def stats(self):
        try:
            with self.connect() as connection:
                total = connection.execute("SELECT COUNT(*) AS n FROM rows").fetchone()["n"]
                by_kind = {row["kind"]: row["n"] for row in connection.execute(
                    "SELECT kind, COUNT(*) AS n FROM rows GROUP BY kind").fetchall()}
        except sqlite3.Error:
            return {"path": str(self.path), "error": "no se pudo leer"}
        return {"path": str(self.path), "rows": total, "kinds": by_kind, "fts": self._fts}

    def as_json(self):
        return json.dumps(self.stats(), sort_keys=True)


def episode_text(goal, exit_code, touched, repairs=0):
    """El texto de un episodio: lo que un turno cerrado deja y sirve para encontrarlo despues."""
    files = ", ".join(sorted(touched or [])[:6]) or "sin ficheros"
    return ("objetivo: %s | exit: %s | reparaciones: %s | ficheros: %s"
            % (_flat(goal, 300) or "(sin objetivo)", exit_code, int(repairs or 0), files))


def remember_turn(root, goal, exit_code, touched=(), repairs=0, project=""):
    """Apunta el episodio de un turno. Se llama al cerrar, no en cada paso."""
    return Recall(root).add("episode", episode_text(goal, exit_code, touched, repairs),
                            evidence="turno cerrado con exit %s" % exit_code, project=project)
