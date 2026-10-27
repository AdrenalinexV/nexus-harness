"""La barra de estado en vivo de la esquina: que esta pasando AHORA, no un "en reposo" muerto.

El chat ya cuenta lo que ocurre en una tira dentro del hilo, pero para saber si el motor esta
trabajando habia que bajar la vista y leer. Esto es lo mismo, en una linea, donde el ojo ya esta: la
fase activa, la herramienta en curso y el progreso.

Dos mitades, y la segunda importa tanto como la primera:

* **En marcha**: se deduce del ULTIMO evento del bus, no de un estado que alguien tenga que acordarse
  de apagar. Si el ultimo evento es un `tool.call`, la fase es la herramienta; si es un
  `gate.verdict`, es el gate.
* **Parado**: no se dice "en reposo". Se dice como acabo el ultimo turno con lo que de verdad se
  midio (gate, juez, contexto) y si el Autopilot esta ON, con su proyecto y su iteracion.

Todo lo que entra aqui viene de un evento o de una medida; nada se estima. Un turno sin gate no dice
"verde": dice "sin gate" (`ok: None`), porque un check que no corrio no es un check que paso.
"""
import time
from pathlib import Path

LIVE_PHASES = {"tool.start": ("tool", "🔧"), "tool.call": ("tool", "🔧"),
               "tool.parallel": ("tool", "🔧"), "director.plan": ("planning", "⚡"),
               "director.error": ("planning", "⚡"), "repair": ("repair", "🔧"),
               "chat.repair": ("repair", "🔧"), "gate.verdict": ("gate", "⚖️"),
               "judge.verdict": ("judge", "⚖️"), "autonomy.backup": ("backup", "💾"),
               "autonomy.plan": ("planning", "⚡"), "autonomy.step": ("autonomy", "🚀"),
               "autonomy.commit": ("commit", "✅"), "chat.user": ("thinking", "⚡"),
               "run.start": ("thinking", "⚡"), "worker.turn": ("thinking", "⚡"),
               "phase.start": ("thinking", "🚀"), "session.relay": ("relay", "🔄"),
               "context.pruned": ("compacting", "🧹")}
# `skills.injected` NO es una fase: ocurre en cada llamada al modelo y tapaba la herramienta en curso
# con una lista de nombres de skills. Es informacion del hilo, no del estado del motor.
FINISHED = ("chat.turn", "run.end", "autonomy.done", "autonomy.stopped", "worker.error",
            "budget.stop")


def _int(value, default=0):
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _tail(events, kinds, depth=40):
    """El ultimo evento de esos tipos, sin recorrer 600 eventos en cada sondeo."""
    for event in reversed(list(events or [])[-depth:]):
        if event.get("kind") in kinds:
            return event
    return None


def _tool_target(args):
    """El fichero o el comando de una llamada, en una sola palabra legible."""
    if not isinstance(args, dict):
        return ""
    for key in ("path", "file", "target", "command", "pattern", "url", "name"):
        value = args.get(key)
        if value:
            text = str(value).strip().replace("\\", "/")
            return text.split("/")[-1] if key in ("path", "file", "target") else text[:40]
    return ""


def _phase_line(event, config):
    """`(fase, glifo, texto)` para un evento en curso. Puro: dos eventos iguales dan dos textos iguales."""
    kind = event.get("kind")
    payload = event.get("payload") or {}
    phase, glyph = LIVE_PHASES.get(kind, ("thinking", "⚡"))
    if kind == "tool.start":
        target = _tool_target(payload.get("args"))
        return phase, glyph, "Obrero usando %s%s…" % (event.get("detail") or "tool",
                                                      (" en %s" % target) if target else "")
    if kind == "session.relay":
        return "relay", "🔄", "Relevo automático de contexto: %s · continuando…" % (
            event.get("detail") or "sesión nueva")
    if kind == "context.pruned":
        return "compacting", "🧹", "Podando salidas antiguas: %s" % (event.get("detail") or "")
    if kind == "tool.call" and str(event.get("detail") or "") == "forge_or_update_skill":
        return "skills", "🧠", "Nueva skill auto-forjada (con su sha256)"
    if kind == "tool.call":
        target = _tool_target(payload.get("args"))
        return phase, glyph, "Obrero: %s%s terminó" % (event.get("detail") or "tool",
                                                       (" · %s" % target) if target else "")
    if kind == "tool.parallel":
        names = [str(name) for name in (payload.get("names") or [])][:3]
        return phase, glyph, ("Obrero: %s en paralelo…" % " + ".join(names) if names
                              else "Obrero: %s…" % (event.get("detail") or "lecturas en paralelo"))
    if kind == "director.plan":
        return phase, glyph, "Director: plan listo (%d líneas)" % len(str(event.get("detail") or "").splitlines())
    if kind in ("repair", "chat.repair"):
        limit = _int(getattr(config, "max_repairs", 0))
        attempt = str(event.get("detail") or "").strip()
        number = "".join(ch for ch in attempt if ch.isdigit()) or "1"
        return phase, glyph, "Obrero reparando el Gate (%s/%s)…" % (number, limit or "?")
    if kind == "gate.verdict":
        verdict = payload.get("verdict") or {}
        checks = verdict.get("checks") or []
        green = len([one for one in checks if one.get("ok")])
        return phase, glyph, "Gate: %d/%d checks en verde (exit %s)" % (
            green, len(checks), verdict.get("exit", event.get("detail") or "?"))
    if kind == "judge.verdict":
        criteria = _int(payload.get("criteria"))
        return phase, glyph, ("Juez auditando la spec (%d criterios)…" % criteria if criteria
                              else "Juez auditando el resultado…")
    if kind == "autonomy.backup":
        return phase, glyph, "Creando backup automático…"
    if kind == "autonomy.plan":
        return phase, glyph, "Director leyendo la spec y el objetivo…"
    if kind == "autonomy.step":
        return phase, glyph, str(event.get("detail") or "Iteración en curso…")[:110]
    if kind == "autonomy.commit":
        return phase, glyph, "Commit limpio del paso %s" % (event.get("detail") or "")
    if kind == "chat.user":
        return phase, glyph, "Director leyendo el pedido…"
    return phase, glyph, str(event.get("detail") or kind or "")[:110]


def summary(last, budget=None, criteria=0):
    """Como acabo el ultimo turno, en una linea: gate, juez y contexto. Solo lo medido."""
    last = last or {}
    verdict = last.get("verdict") or {}
    judgement = last.get("judgement") or {}
    # Un motor recien arrancado trae un `Turn` vacio (exit 0, cero pasos). Eso NO es "un turno sin
    # gate": es que todavia no hay turnos, y decirlo mal seria inventar un historial.
    if not _int(last.get("steps")) and not verdict and not last.get("touched"):
        return {"text": "", "tone": "idle", "ok": None}
    parts, tone = [], "idle"
    if verdict:
        ok = bool(verdict.get("ok"))
        parts.append(("Gate OK" if ok else "Gate ROJO (exit %s)" % verdict.get("exit", "?")))
        tone = "ok" if ok else "bad"
    elif last:
        parts.append("sin Gate (no tocó ficheros)")
    verdict_word = str(judgement.get("verdict") or "")
    if verdict_word == "approve":
        parts.append("Juez VERDE")
    elif verdict_word == "reject":
        parts.append("Juez RECHAZA")
        # Gate verde con juez que objeta NO es un verde: es un aviso, y se pinta como tal.
        tone = "warn" if tone == "ok" else tone
    ratio = (budget or {}).get("ratio")
    if isinstance(ratio, (int, float)):
        parts.append("Contexto %d%%" % int(round(float(ratio) * 100)))
    if criteria and verdict:
        parts.append("%d criterios en spec" % criteria)
    # El glifo sale del tono FINAL, no del gate: "✅ ... Juez RECHAZA" era una contradiccion en la
    # misma frase, y la pildora se pinta con el tono.
    glyph = {"ok": "✅", "bad": "❌", "warn": "⚠️"}.get(tone, "")
    text = " · ".join(parts)
    return {"text": ("%s %s" % (glyph, text)).strip(), "tone": tone,
            "ok": verdict.get("ok") if verdict else None}


DIFF_LIMIT = 12
DIFF_MAX_BYTES = 512 * 1024


def _diff_stat(root, name):
    """`+lineas/-lineas` por fichero del turno, leyendo el diario del checkpoint y el fichero actual.

    Es un diff medido, no una captura: el diario guarda los bytes de ANTES de cada escritura, asi que
    comparar blob contra disco es exactamente lo que cambio el turno. Un fichero enorme (o un
    binario) no se compara: se declara, porque tardar dos segundos en pintar una pildora es peor que
    decir "no medido".
    """
    if not root or not name:
        return [], {}
    from . import checkpoint
    journal = checkpoint.find(root, name)
    if journal is None:
        return [], {}
    import difflib
    rows, added, removed = [], 0, 0
    for entry in journal.entries[:DIFF_LIMIT]:
        target = Path(root) / entry["path"]
        try:
            after = target.read_bytes()
        except OSError:
            after = b""
        blob = journal.directory / entry["blob"] if entry.get("blob") else None
        try:
            before = blob.read_bytes() if blob is not None and blob.is_file() else b""
        except OSError:
            before = b""
        if len(before) > DIFF_MAX_BYTES or len(after) > DIFF_MAX_BYTES:
            rows.append({"path": entry["path"], "added": None, "removed": None,
                         "note": "no medido: fichero grande"})
            continue
        change = list(difflib.unified_diff(before.decode("utf-8", "replace").splitlines(),
                                           after.decode("utf-8", "replace").splitlines(),
                                           lineterm="", n=0))
        plus = len([line for line in change if line.startswith("+") and not line.startswith("+++")])
        minus = len([line for line in change if line.startswith("-") and not line.startswith("---")])
        added += plus
        removed += minus
        rows.append({"path": entry["path"], "added": plus, "removed": minus,
                     "created": not entry.get("existed")})
    return rows, {"added": added, "removed": removed, "files": len(rows)}


def detail(last, budget=None, root=None):
    """Lo que se abre al pulsar la pildora: ficheros, diff, gate y tokens del ultimo turno."""
    last = last or {}
    verdict = last.get("verdict") or {}
    judgement = last.get("judgement") or {}
    # Los tokens del turno viajan en `tokens` (chat) o dentro de `cost` (run). Si no estan, se dice
    # "sin medir": un turno sin contador no costo cero.
    tokens = last.get("tokens")
    if not isinstance(tokens, dict) or not tokens:
        tokens = (last.get("cost") or {}).get("tokens")
    if not isinstance(tokens, dict) or not tokens:
        total = _int((budget or {}).get("used"))
        tokens = {"prompt": None, "completion": None, "total": total or None}
    checks = [{"name": str(one.get("name") or "?"), "ok": bool(one.get("ok")),
               "detail": str(one.get("detail") or "")[:600]}
              for one in verdict.get("checks") or []]
    diff_rows, diff_totals = _diff_stat(root, str(last.get("checkpoint") or ""))
    return {"files": [str(name) for name in (last.get("touched") or [])][:12],
            "files_total": len(last.get("touched") or []),
            "diff": diff_rows, "diff_totals": diff_totals,
            "gate": {"exit": verdict.get("exit"), "ok": verdict.get("ok"), "checks": checks,
                     "failures": str(verdict.get("failures") or "")[:1200]},
            "judge": {key: judgement.get(key) for key in ("verdict", "reason", "model")},
            "tokens": tokens,
            "steps": _int(last.get("steps")), "repairs": _int(last.get("repairs")),
            "exit": last.get("exit"), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def state(events, running=False, config=None, last=None, budget=None, autopilot=None,
          criteria=0, root=None):
    """El cuerpo entero de `/api/activity`: fase, progreso, autopilot y el resumen del ultimo turno."""
    events = list(events or [])
    auto = dict(autopilot or {})
    live = _tail(events, set(LIVE_PHASES))
    finished = _tail(events, set(FINISHED), depth=12)
    last_event = events[-1] if events else {}
    working = bool(running) or bool(auto.get("running"))
    finished_summary = summary(last, budget, criteria)
    if not working and not last and last_event.get("kind") in FINISHED:
        # Sin `last` en memoria pero con un cierre en el bus (motor recien arrancado que cerro un run):
        # se dice lo que dijo el evento, que es lo unico medido que hay.
        finished_summary = {"text": str(last_event.get("detail") or "turno terminado"),
                            "tone": "info", "ok": None}
    if working and live and (not finished or _seq(live) >= _seq(finished)):
        phase, glyph, text = _phase_line(live, config)
        tone = "warn"
    elif working:
        phase, glyph, text, tone = "thinking", "⚡", "Motor trabajando…", "warn"
    elif finished_summary.get("text"):
        # Parado CON historia: la pildora enseña como acabo el ultimo turno, que es lo que el operador
        # viene a mirar ("¿salio verde?"). El detalle esta a un clic.
        phase, glyph, tone = "idle", {"ok": "✅", "bad": "❌", "warn": "⚠️"}.get(
            finished_summary.get("tone"), "🟢"), finished_summary.get("tone") or "idle"
        text = finished_summary["text"]
    else:
        phase, glyph = "idle", "🟢"
        where = ""
        if auto.get("running"):
            where = " · Autopilot %s %d/%d" % (auto.get("project") or "", _int(auto.get("iteration")),
                                               _int(auto.get("iterations")))
        elif auto.get("last"):
            where = " · Autopilot OFF"
        text = "Listo%s" % where
        tone = "idle"
    return {"phase": phase, "glyph": glyph, "label": text, "tone": tone,
            "running": bool(running), "autopilot": public_autopilot(auto),
            "progress": progress(auto, criteria),
            "summary": finished_summary,
            "detail": detail(last, budget, root),
            "seq": _seq(last_event)}


def public_autopilot(auto):
    """Lo que enseña la interfaz del Autopilot: encendido, proyecto, iteracion y limite."""
    auto = dict(auto or {})
    return {"running": bool(auto.get("running")), "project": str(auto.get("project") or ""),
            "iteration": _int(auto.get("iteration")), "iterations": _int(auto.get("iterations")),
            "queue": [str(name) for name in auto.get("queue") or []],
            "done": bool(auto.get("done")), "note": str(auto.get("note") or "")[:200],
            "last": str(auto.get("last") or "")[:200]}


def progress(auto, criteria=0):
    """La barra: iteraciones del bucle y, si la spec los declara, sus criterios."""
    auto = dict(auto or {})
    total = _int(auto.get("iterations"))
    done = _int(auto.get("iteration"))
    steps = _int(auto.get("steps_done"))
    if total:
        return {"kind": "iterations", "done": min(done, total), "total": total,
                "label": "%d/%d iteraciones" % (min(done, total), total),
                "steps": steps}
    if criteria:
        return {"kind": "criteria", "done": steps, "total": _int(criteria),
                "label": "%d/%d criterios" % (steps, _int(criteria)), "steps": steps}
    return {}


def _seq(event):
    return _int((event or {}).get("seq"))
