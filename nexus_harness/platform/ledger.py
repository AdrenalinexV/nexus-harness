"""El libro de turnos del arnes: una linea por turno, en el proyecto donde ocurrio.

Por que un fichero aparte del transcript: el transcript guarda la CONVERSACION (lo que hay que
repintar), y esto guarda la MEDIDA (que paso con el gate, cuanto costo, si hubo que reparar). Son dos
preguntas distintas y mezclarlas hace que un cambio de formato de chat reescriba el historial de
calidad.

Formato: JSON por linea en `<proyecto>/.nexus/harness/ledger.jsonl`, solo se anade. Un turno escrito a
medias se descarta al leer (la linea tiene que ser JSON valido): el libro no adivina.

Un cero no es una medida: `aggregate()` devuelve `{"turns": 0}` y la pantalla lo dice con palabras en
vez de dibujar un anillo vacio.
"""
import json
import uuid
import time
from pathlib import Path

LEDGER_REL = Path(".nexus") / "harness" / "ledger.jsonl"
MAX_ROWS = 4000


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class TurnLedger:
    """Un libro por proyecto. `append()` nunca lanza: perder una medida no puede tumbar un turno."""

    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / LEDGER_REL

    def append(self, record):
        row = {"at": _now()}
        row.update({key: value for key, value in (record or {}).items() if value is not None})
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            return False
        return True

    def rows(self, limit=MAX_ROWS):
        if not self.path.is_file():
            return []
        out = []
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        for line in text.splitlines()[-int(limit):]:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
        # Lo que se lee es lo que se suma: `improve.py` consume `rows()` directo, y una corrida anotada
        # por dos escritores inflaba el consumo medido casi al doble (medido: 411.886 vs 205.943).
        return dedupe(out)


SAVINGS_FIELDS = ("tokens_sent", "tokens_baseline", "tokens_saved", "cached_tokens", "dormant_tokens", "pruned_tokens",
                  "isolated_tokens", "repomap_tokens", "requests")


def _savings_of(turn):
    """Los campos de ahorro de un turno o corrida. Sin `savings` no se inventa un cero: se omite."""
    savings = turn.get("savings")
    if not isinstance(savings, dict) or not savings:
        return {}
    row = {name: _int(savings.get(name)) for name in SAVINGS_FIELDS}
    row["tokens_sent"] = _int(savings.get("sent"))
    row["tokens_baseline"] = _int(savings.get("baseline"))
    row["tokens_saved"] = _int(savings.get("saved"))
    row["requests"] = _int(savings.get("requests"))
    for name in ("savings_pct", "context_multiplier"):
        value = savings.get(name)
        if isinstance(value, (int, float)):
            row[name] = round(float(value), 2)
    return row


def from_turn(turn, project="", session="", source="chat"):
    """La medida de un turno de chat o de una corrida de la triada, con los nombres del libro."""
    turn = turn or {}
    verdict = turn.get("verdict") or {}
    judgement = turn.get("judgement") or {}
    budget = turn.get("cost") or turn.get("budget") or {}
    direct = turn.get("tokens") if isinstance(turn.get("tokens"), dict) else {}
    nested = budget.get("tokens") if isinstance(budget.get("tokens"), dict) else {}
    prompt = _int(direct.get("prompt")) or _int(nested.get("prompt")) or _int(budget.get("prompt"))
    completion = (_int(direct.get("completion")) or _int(nested.get("completion"))
                  or _int(budget.get("completion")))
    exit_code = turn.get("exit")
    # La identidad de la CORRIDA, no del apunte: dos escritores (runner y bucle autonomo) anotan la
    # misma con el mismo `id`/`started`/checkpoint aunque escriban en segundos distintos. Sin identidad
    # declarada, esta escritura ES la corrida: dos ciclos seguidos no pueden colapsar en uno.
    identity = str(turn.get("id") or turn.get("started") or turn.get("checkpoint") or "")
    return {"project": _name(project), "session": session or "", "source": source,
            "run": identity or uuid.uuid4().hex,
            "exit": None if exit_code is None else _int(exit_code),
            "gate": bool(verdict.get("ok")) if verdict else None,
            "judge": (judgement or {}).get("verdict") or "",
            "repairs": _int(turn.get("repairs")),
            "steps": _int(turn.get("steps")),
            "prompt_tokens": prompt, "completion_tokens": completion,
            "tokens": prompt + completion,
            "touched": len(turn.get("touched") or []), **_savings_of(turn)}


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _name(project):
    text = str(project or "").replace("\\", "/").rstrip("/")
    return text.split("/")[-1] if text else ""


def aggregate(rows):
    """Los cuatro numeros que la pantalla necesita, contados de las filas que existen."""
    first_pass = repaired = blocked = 0
    tokens = prompt = completion = 0
    sent = baseline = saved = dormant = pruned = isolated = repomap = requests = 0
    by_project = {}
    for row in rows or []:
        exit_code = row.get("exit")
        repairs = _int(row.get("repairs"))
        if exit_code in (0, None) and not repairs:
            first_pass += 1
        elif exit_code in (0, None):
            repaired += 1
        else:
            blocked += 1
        tokens += _int(row.get("tokens"))
        prompt += _int(row.get("prompt_tokens"))
        completion += _int(row.get("completion_tokens"))
        sent += _int(row.get("tokens_sent"))
        baseline += _int(row.get("tokens_baseline"))
        saved += _int(row.get("tokens_saved"))
        dormant += _int(row.get("dormant_tokens"))
        pruned += _int(row.get("pruned_tokens"))
        isolated += _int(row.get("isolated_tokens"))
        repomap += _int(row.get("repomap_tokens"))
        requests += _int(row.get("requests"))
        name = row.get("project") or "(sin proyecto)"
        bucket = by_project.setdefault(name, {"turns": 0, "tokens": 0, "first_pass": 0,
                                              "repaired": 0, "blocked": 0, "green": 0})
        bucket["turns"] += 1
        bucket["tokens"] += _int(row.get("tokens"))
        # Los nombres del bucket son los MISMOS que los de la fila: un alias (`sent` vs
        # `tokens_sent`) hacia que la barra de enviados del grafico leyera 0 con 4.859 evitados.
        for field in ("tokens_sent", "tokens_baseline", "tokens_saved", "requests"):
            bucket[field] = bucket.get(field, 0) + _int(row.get(field))
        if exit_code in (0, None) and not repairs:
            bucket["first_pass"] += 1
            bucket["green"] += 1
        elif exit_code in (0, None):
            bucket["repaired"] += 1
            bucket["green"] += 1
        else:
            bucket["blocked"] += 1
    rows_count = len(rows or [])
    measured = {"sent": sent, "baseline": baseline, "saved": saved, "dormant": dormant,
                "pruned": pruned, "isolated": isolated, "repomap": repomap, "requests": requests}
    return {"turns": rows_count, "first_pass": first_pass, "repaired": repaired,
            "blocked": blocked, "tokens": tokens, "prompt_tokens": prompt,
            "completion_tokens": completion, "by_project": by_project,
            "savings": measured,
            "savings_pct": (round(100.0 * saved / baseline, 1) if baseline else None),
            "context_multiplier": (round(baseline / float(sent), 2) if sent else None)}


def dedupe(rows):
    """Colapsa la MISMA corrida escrita dos veces (paso: el ejecutor y el bucle autonomo la anotaban).

    La clave es la medida entera del turno, no su etiqueta de sesion: dos filas con el mismo instante,
    proyecto, tokens, pasos y ficheros tocados son la misma corrida contada dos veces, y sumarlas
    inflaba el consumo medido al doble (medido: 411.886 en vez de 205.943). Se conserva la primera, que
    es la que trae la sesion real del chat o de la triada.
    """
    seen, out = set(), []
    for row in rows or []:
        run = str(row.get("run") or "")
        key = ((run,) + (row.get("tokens"), row.get("steps"), row.get("touched"), row.get("exit"))
               if run else
               (row.get("at"), row.get("project"), row.get("tokens"), row.get("prompt_tokens"),
                row.get("steps"), row.get("touched"), row.get("exit")))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def history(workspace, names=(), extra=()):
    """Las filas de todos los proyectos mirados, con proyecto unico y de mas viejo a mas nuevo."""
    roots = [Path(workspace) / name for name in names or []]
    roots += [Path(path) for path in extra or []]
    rows, seen = [], set()
    for root in roots:
        for row in TurnLedger(root).rows():
            row.setdefault("project", _name(root))
            key = (row.get("at"), row.get("session"), row.get("project"), row.get("tokens"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    rows.sort(key=lambda row: str(row.get("at") or ""))
    return dedupe(rows)
