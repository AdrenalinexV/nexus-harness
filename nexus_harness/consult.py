"""La consulta: cuando el arnes no debe decidir solo, pregunta y sigue con lo que le digan.

Un daemon que se para en la primera duda no es autonomo; uno que decide por su cuenta lo que no le
corresponde es peor. Esta es la tercera via: escribe la pregunta, la manda por los canales del
operador, espera respuesta con plazo y, si no llega, aplica el **defecto declarado** (nunca uno
inventado) y lo deja escrito.

Cuatro reglas estructurales:

* **El registro es append-only** (`questions.jsonl`): preguntar y contestar son eventos, y el estado
  actual es un fold. Un corte a mitad no deja un JSON corrupto ni una pregunta a medias.
* **Sin canal no se bloquea.** Si el operador no tiene Discord/Telegram/bridge, se devuelve el defecto
  al instante y se anota `no_channel`: un turno no espera a un mensajero que no existe.
* **La primera respuesta gana.** Que conteste el movil y luego un bot no cambia el resultado.
* **Todo lo que sale va redactado**, con la misma funcion que usa el deploy del VPS.
"""
import json
import os
import time
import uuid
from pathlib import Path

from .vps_deployer import redact

REL = Path(".nexus") / "harness" / "questions.jsonl"
MAX_ROWS = 500
DEFAULT_DEADLINE = 900


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _append(root, event):
    path = Path(root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def events(root):
    """Todos los eventos, en orden. Una linea rota se salta: no invalida las demas."""
    path = Path(root) / REL
    if not path.is_file():
        return []
    rows = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-(MAX_ROWS * 4):]:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("id"):
                rows.append(row)
    except OSError:
        return []
    return rows


def fold(rows):
    """El estado actual de cada pregunta: el primero que contesta gana y nadie lo pisa."""
    found = {}
    for row in rows:
        qid = row.get("id")
        if not qid:
            continue
        current = found.get(qid)
        if current is None:
            found[qid] = dict(row) if row.get("event") == "asked" else {"id": qid, "state": "unknown"}
            continue
        if row.get("event") == "asked" and not current.get("text"):
            current.update({k: v for k, v in row.items() if v not in (None, "")})
        elif row.get("event") == "answered" and current.get("state") != "answered":
            current.update({"state": "answered", "answer": row.get("answer"),
                            "source": row.get("source") or "?", "answered_at": row.get("at")})
        elif row.get("event") == "expired" and current.get("state") == "pending":
            current.update({"state": "expired", "answer": current.get("default"),
                            "source": "default", "answered_at": row.get("at")})
    return found


def questions(root):
    return fold(events(root))


def pending(root):
    return [row for row in questions(root).values() if row.get("state") == "pending"]


def get(root, qid):
    return questions(root).get(str(qid or ""))


def options_of(question):
    return [str(item) for item in (question.get("options") or [])]


def ask(root, text, options=(), default="", project="", deadline_s=DEFAULT_DEADLINE,
        now=None, secrets=()):
    """Registra una pregunta y devuelve su fila. No habla con nadie: eso es `announce`.

    `now` es epoch (segundos). Se guardan las dos formas: `at` para que un humano lea la hora y
    `expires` para que el plazo se pueda medir sin depender del reloj del sistema en una suite.
    """
    body = redact(str(text or "").strip(), secrets)[:2000]
    if not body:
        return {"ok": False, "reason": "pregunta vacia"}
    moment = float(time.time() if now is None else now)
    qid = uuid.uuid4().hex[:8]
    row = {"event": "asked", "id": qid, "at": _now(), "asked_epoch": moment,
           "expires": moment + int(deadline_s or DEFAULT_DEADLINE), "text": body,
           "options": [str(item)[:120] for item in options][:6], "default": str(default or "")[:120],
           "project": str(project or ""), "deadline_s": int(deadline_s or DEFAULT_DEADLINE),
           "state": "pending"}
    _append(root, row)
    return row



def answer(root, qid, text, source="?", now=None):
    """Contesta. Si ya estaba contestada, no la cambia: devuelve `already`."""
    wanted = get(root, qid)
    if not wanted:
        return {"ok": False, "reason": "esa pregunta no existe: %s" % qid}
    if wanted.get("state") == "answered":
        return {"ok": True, "already": True, "answer": wanted.get("answer")}
    if wanted.get("state") == "expired":
        return {"ok": True, "already": True, "answer": wanted.get("answer")}
    body = str(text or "").strip()[:400]
    if not body:
        return {"ok": False, "reason": "respuesta vacia"}
    _append(root, {"event": "answered", "id": wanted["id"], "answer": body, "source": source,
                   "at": _now() if now is None else now})
    return {"ok": True, "id": wanted["id"], "answer": body, "source": source}


def match(option_values, text):
    """Traduce lo que escribio el operador a la opcion declarada. `1` es la primera opcion."""
    raw = str(text or "").strip()
    low = raw.lower()
    for value in option_values:
        if low == value.lower() or low == value.lower()[:40]:
            return value
    if low.isdigit():
        index = int(low) - 1
        if 0 <= index < len(option_values):
            return option_values[index]
    return raw


def resolve(root, wanted, option_values=(), now=None):
    """Cierra la pregunta con el defecto si el plazo vencio. Devuelve la fila resultante."""
    if wanted.get("state") != "pending":
        return wanted
    try:
        expires = float(wanted.get("expires") or 0)
    except (TypeError, ValueError):
        return wanted
    if not expires:
        expires = float(wanted.get("asked_epoch") or 0) + int(wanted.get("deadline_s") or DEFAULT_DEADLINE)
    moment = float(time.time() if now is None else now)
    if moment < expires:
        return wanted
    _append(root, {"event": "expired", "id": wanted["id"], "at": _now()})
    return get(root, wanted["id"]) or wanted



def wait(root, qid, poll=None, sleep=None, now=None, clock=None, max_polls=450,
         should_stop=None):
    """Espera a que haya respuesta. `poll()` devuelve las respuestas nuevas o `[]`.

    Devuelve `{state, answer, source}`. Un `poll` que revienta cuenta como "sin novedad": un canal
    roto no puede tumbar el bucle que lo llamo. `max_polls` es el techo de seguridad del turno, no el
    plazo: el plazo lo pone la pregunta.
    """
    sleeper = sleep or time.sleep
    tick = clock or time.time
    polls = 0
    while True:
        if should_stop and should_stop():
            return {"state": "stopped", "answer": "", "source": "stop"}
        row = get(root, qid)
        if not row:
            return {"state": "missing", "answer": "", "source": "missing"}
        if row.get("state") == "answered":
            return {"state": "answered", "answer": row.get("answer"), "source": row.get("source")}
        if row.get("state") == "expired":
            return {"state": "expired", "answer": row.get("answer"), "source": "default"}
        if poll:
            try:
                found = poll() or []
            except Exception as exc:  # noqa: BLE001 -- un canal caido es una observacion
                found = [{"error": "%s: %s" % (type(exc).__name__, exc)}]
            fresh = [item for item in found if item.get("id") and item.get("text")]
            if fresh:
                for item in fresh:
                    answer(root, item["id"], item.get("text"), item.get("source") or "channel")
                continue
        row = resolve(root, row, now=tick())
        if row.get("state") == "expired":
            return {"state": "expired", "answer": row.get("answer"), "source": "default"}
        polls += 1
        if polls >= int(max_polls or 1):
            return {"state": "pending", "answer": "", "source": "gave_up"}
        sleeper(2)




def describe(question, channel_hint=""):
    """El texto que viaja al operador: sin adornos, con las opciones numeradas y el plazo."""
    lines = ["\u2753 Nexus necesita una decision", ""]
    if question.get("project"):
        lines.append("proyecto: %s" % question["project"])
    lines.append(str(question.get("text") or "").strip())
    options = options_of(question)
    if options:
        lines.append("")
        for index, value in enumerate(options, 1):
            lines.append("  %d) %s" % (index, value))
    lines.append("")
    lines.append("responde: /answer %s <texto o numero>" % question.get("id"))
    lines.append("plazo: %s min \u00b7 si no hay respuesta: %s"
                 % (int(question.get("deadline_s") or 0) // 60, question.get("default") or "parar"))
    if channel_hint:
        lines.append(channel_hint)
    return "\n".join(lines)[:1900]


def parse_reply(text, open_ids):
    """`/answer ab12cd 2` o, si solo hay una pregunta abierta, el texto suelto."""
    raw = str(text or "").strip()
    if not raw:
        return None, ""
    lowered = raw.lower()
    if lowered.startswith("/answer") or lowered.startswith("/respuesta"):
        parts = raw.split(None, 2)
        if len(parts) >= 2 and parts[1] in open_ids:
            return parts[1], (parts[2] if len(parts) > 2 else "")
        if len(parts) >= 2:
            return parts[1], (parts[2] if len(parts) > 2 else "")
    if len(open_ids) == 1:
        return open_ids[0], raw
    for qid in open_ids:
        if qid in lowered:
            return qid, raw.replace(qid, "").strip(" :")
    return None, raw


def state_path(root):
    return Path(root) / REL


def purge(root, keep=MAX_ROWS):
    """Deja lo abierto y las ultimas `keep` lineas. Devuelve cuantas quito."""
    path = state_path(root)
    if not path.is_file() or not keep:
        return 0
    rows = events(root)
    live = {row["id"] for row in pending(root)}
    first = max(0, len(rows) - int(keep))
    kept = [row for index, row in enumerate(rows) if row.get("id") in live or index >= first]
    if len(kept) == len(rows):
        return 0
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(row, ensure_ascii=False) + os.linesep for row in kept),
                   encoding="utf-8")
    tmp.replace(path)
    return len(rows) - len(kept)

