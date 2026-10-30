"""Lo que el bucle hace cuando el rojo no se arregla solo: preguntar al operador y obedecer.

Sin esto, un daemon autonomo tiene dos finales malos: pararse en la primera duda (no es autonomo) o
decidir por su cuenta lo que no le corresponde (es peor). Aqui la duda se convierte en una pregunta con
tres salidas, cada una con un efecto declarado sobre el proyecto:

* **seguir**   -- otro ciclo, con el motivo del rojo delante para no repetir el mismo parche.
* **revertir** -- se deshace el turno con la instantanea que dejo `checkpoint` y el proyecto queda como
  estaba antes de tocar nada.
* **parar**    -- el proyecto se queda rojo y la cola pasa al siguiente.

Sin canales legibles el defecto es **parar**: un bucle que se inventa una decision cuando nadie
contesta es exactamente lo que este arnes existe para no hacer.
"""
from nexus_harness.verify import checkpoint
from nexus_harness import consult, consult_channels

OPTIONS = ("seguir", "revertir", "parar")


def question_text(name, why, iteration=0):
    lines = ["El proyecto '%s' ha quedado ROJO" % name]
    if iteration:
        lines[0] += " en la vuelta %d" % iteration
    lines.append("motivo: %s" % str(why or "sin detalle")[:600])
    lines.append("¿Qué hago? (seguir = otro intento · revertir = deshacer el turno · parar = dejarlo)")
    return "\n".join(lines)


def ask_about_red(root, name, why, config, iteration=0, asker=None, deadline_s=None,
                  should_stop=None):
    """Devuelve `{decision, asked, answer, source}`. Nunca lanza: un canal roto es `parar`."""
    if not getattr(config, "consult_enabled", True):
        return {"decision": "parar", "asked": False, "answer": "", "source": "disabled",
                "state": "disabled", "question": ""}
    text = question_text(name, why, iteration)
    deadline = int(deadline_s or getattr(config, "ask_deadline", 900) or 900)
    if asker:
        outcome = asker(root, config, text, OPTIONS, "parar", name, deadline)
    else:
        outcome = consult_channels.ask_operator(root, config, text, OPTIONS, "parar", name,
                                                deadline_s=deadline, should_stop=should_stop)
    raw = str(outcome.get("answer") or "")
    decision = consult.match(list(OPTIONS), raw)
    if decision not in OPTIONS:
        decision = "parar"
    return {"decision": decision, "asked": bool(outcome.get("delivered")), "answer": raw,
            "source": outcome.get("source") or "", "state": outcome.get("state") or "",
            "question": outcome.get("id") or ""}


def act(root, decision):
    """Aplica la decision. Devuelve `(sigue, nota)`. `revertir` deshace el ultimo turno escrito."""
    if decision == "seguir":
        return True, "el operador pidio otro intento"
    if decision == "revertir":
        journal = checkpoint.latest(root)
        if journal is None:
            return False, "revertir: no hay instantanea que deshacer, el proyecto se queda como esta"
        report = journal.undo()
        return False, "revertido %s: restaurados %s, borrados %s" % (
            journal.name, report.get("restored"), report.get("deleted"))
    return False, "parado por el operador (o sin respuesta)"

