"""Las herramientas de memoria: consultar la historia sin cargarla, y apuntar lo aprendido.

`recall` es la que importa: el modelo pregunta por lo que paso o por una preferencia y recibe solo las
filas que responden, con su capa y su fecha. No hay bloque de historia en el prompt.
`remember` existe para que una regla observada no se pierda al cerrar el turno, y exige evidencia: una
preferencia inventada envenena todos los turnos futuros.
"""
from pathlib import Path

from ..recall import Recall


def recall_tool(root, args, config=None):
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("recall necesita `query` (que quieres recordar)")
    limit = max(1, min(12, int(args.get("limit") or 6)))
    rows = Recall(root).search(query, k=limit)
    if not rows:
        return ("nada en memoria para %r (puedes apuntarlo con remember)" % query,
                {"files": [], "matches": 0})
    lines = ["- [%s] %s%s" % (row["kind"], row["text"],
                              (" · %s" % row["at"]) if row.get("at") else "") for row in rows]
    return "\n".join(lines), {"files": [], "matches": len(rows)}


def remember_tool(root, args, config=None):
    text = str(args.get("text") or "").strip()
    evidence = str(args.get("evidence") or "").strip()
    kind = str(args.get("kind") or "fact").strip().lower()
    result = Recall(root).add(kind, text, evidence=evidence, project=Path(root).name,
                              confidence=float(args.get("confidence") or 0.6))
    if not result.get("ok"):
        raise ValueError(result.get("reason") or "no se pudo guardar")
    if result.get("duplicate"):
        return "ya estaba en memoria", {"files": [], "id": result["id"], "duplicate": True}
    return "guardado en memoria (%s)" % kind, {"files": [], "id": result["id"]}


HANDLERS = {"recall": recall_tool, "remember": remember_tool}
