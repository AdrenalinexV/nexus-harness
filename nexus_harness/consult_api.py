"""`/api/consult`: la pregunta vista desde fuera, para que se pueda contestar sin abrir la cabina.

Dos verbos y ninguna opinion:

* `GET`  devuelve lo que sigue abierto, lo ultimo que se cerro y **que canales escuchan de verdad**.
  Un operador tiene que poder ver en un JSON si su Telegram contesta o solo recibe.
* `POST` contesta `{id, answer}`. Es el camino que usan los puentes que no tienen gateway propio
  (WhatsApp por Baileys, un bot de Discord, n8n, un cron): todos escriben en el mismo registro que lee
  el bucle, asi que no hay dos verdades sobre lo que decidio el humano.
"""
from . import consult, consult_channels


def _recent(root, limit=10):
    rows = [row for row in consult.questions(root).values() if row.get("state") != "pending"]
    rows.sort(key=lambda row: str(row.get("answered_at") or row.get("at") or ""), reverse=True)
    return rows[:limit]


def get(cockpit):
    root = cockpit.root
    config = cockpit.config
    found = consult_channels.channels(config)
    return 200, {"enabled": bool(getattr(config, "consult_enabled", True)),
                 "deadline": int(getattr(config, "ask_deadline", 900) or 900),
                 "pending": consult.pending(root), "recent": _recent(root),
                 "channels": [{"kind": channel.get("kind"), "sends": bool(channel.get("url")),
                               "hears": bool(channel.get("readable"))} for channel in found]}


def post(cockpit, body):
    body = body if isinstance(body, dict) else {}
    qid = str(body.get("id") or body.get("question") or "").strip()
    answer = str(body.get("answer") or body.get("text") or "").strip()
    if not qid:
        return 400, {"ok": False, "reason": "falta el id de la pregunta"}
    result = consult.answer(cockpit.root, qid, answer, str(body.get("source") or "api"))
    if result.get("ok"):
        question = consult.get(cockpit.root, qid) or {}
        return 200, {"ok": True, "id": qid, "answer": resolve_answer(result, question),
                     "already": bool(result.get("already"))}
    return 404, {"ok": False, "reason": result.get("reason")}


def resolve_answer(result, question):
    """Lo que se guardo, traducido a la opcion declarada cuando el operador escribio un numero."""
    raw = str(result.get("answer") or "")
    options = [str(item) for item in (question.get("options") or [])]
    return consult.match(options, raw) if options else raw
