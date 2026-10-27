"""Poda deslizante con recibo: el historial deja de reenviarse entero en cada paso.

El coste que no se ve: en el paso 8, un turno multi-paso reenvia COMPLETO lo que leyo en los pasos 1 a
5. Los tokens de entrada crecen de forma cuadratica con el numero de pasos (medido con este mismo
contador en `tools/audit_context.py`: 8 pasos con lecturas realistas = 28.042 tokens sin poda frente a
12.823 con poda, **54,3 %** menos), y la ventana se agota antes de terminar la tarea.

La regla es de bytes, no de opinion:

* los ultimos `keep_last_steps` pasos viajan **intactos** (el turno en curso los necesita);
* las salidas de herramientas de pasos anteriores se sustituyen por un recibo de una linea con el
  tamano original, el sha256 y la instruccion de releer si hace falta precision;
* el CONTENIDO del modelo (assistant) nunca se toca: un recibo que borra una decision del modelo
  cambia el hilo, y eso no es ahorrar, es perder el trabajo.

El recibo guarda `chars_before`, asi que el ahorro se puede medir exactamente (no es una estimacion) y
tambien se puede reconstruir el baseline de un harness tradicional que no poda.
"""
import hashlib
from dataclasses import dataclass, field

MARKER = "[Compactado por Nexus"
MIN_CHARS = 400
KEEP_LAST_STEPS = 2
CHARS_PER_TOKEN = 4
MAX_LINE = 160


def _sha(text):
    return hashlib.sha256(str(text or "").encode("utf-8", "replace")).hexdigest()


def _one_line(text, limit=MAX_LINE):
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[:limit - 1] + "\u2026"


def _path_of(message, table):
    call_id = str(getattr(message, "tool_call_id", "") or "")
    if call_id and call_id in table:
        return table[call_id]
    return str(getattr(message, "name", "") or "?")


def _line_range(text):
    total = str(text or "").count("\n") + 1
    return "L1-%d" % total if total > 1 else "L1"


def receipt(tool, path, body, reason=""):
    """El recibo de una salida podada: herramienta, fichero, rango, precio y hash.

    Formato exacto (una linea, para que no ocupe sitio en el prompt):
    `[Compactado por Nexus: read_file 'x.py' L1-180 (4.210 chars -> 45 chars) | sha256:ab12… | Re-lee
    si necesitas lineas exactas]`

    La longitud del propio recibo se resuelve con dos pasadas: el numero de digitos del "despues"
    cambia el tamano del texto que lo contiene, y un dato que se mide a si mismo tiene que converger.
    """
    text = str(body or "")
    digest = _sha(text)
    head = ("%s: %s '%s' %s (%d chars -> " % (MARKER, tool or "tool", path or "?", _line_range(text),
                                              len(text)))
    tail = " chars) | sha256:%s | Re-lee si necesitas lineas exactas]" % digest[:16]
    if reason:
        tail = tail[:-1] + " | %s]" % _one_line(reason, 60)
    after = 1
    for _pass in range(3):
        after = len(head) + len(str(after)) + len(tail)
    return "%s%d%s" % (head, after, tail)


@dataclass
class PruneReport:
    """Que se podo, cuanto pesaba y cuanto pesa: los dos numeros que hacen medible el ahorro."""

    pruned: int = 0
    chars_before: int = 0
    chars_after: int = 0
    bytes_saved: int = 0
    receipts: list = field(default_factory=list)
    steps_seen: int = 0

    @property
    def tokens_saved(self):
        return max(0, self.bytes_saved) // CHARS_PER_TOKEN

    def as_dict(self):
        return {"pruned": self.pruned, "chars_before": self.chars_before,
                "chars_after": self.chars_after, "tokens_saved": self.tokens_saved,
                "steps": self.steps_seen}


def steps_of(messages):
    """`[(indice_assistant, [indices_tool])]` en orden. Un paso es una llamada y sus resultados."""
    steps, current = [], None
    for index, message in enumerate(messages or []):
        role = str(getattr(message, "role", "") or "")
        if role == "assistant":
            current = (index, [])
            if getattr(message, "tool_calls", None):
                steps.append(current)
                continue
            current = None
        elif role == "tool" and (current is not None or steps):
            if current is None:
                current = (index, [])
                steps.append(current)
            current[1].append(index)
    return steps


def prune(messages, keep_last_steps=KEEP_LAST_STEPS, min_chars=MIN_CHARS):
    """Poda en el sitio las salidas antiguas. Devuelve el `PruneReport` con los bytes reales."""
    table = {}
    for message in messages or []:
        for call in getattr(message, "tool_calls", None) or ():
            arguments = getattr(call, "arguments", None)
            if isinstance(arguments, dict) and arguments.get("path"):
                table[str(getattr(call, "id", ""))] = str(arguments["path"])
    steps = steps_of(messages)
    keep = set()
    if int(keep_last_steps) > 0:
        # `steps[-0:]` devuelve la lista ENTERA (en Python `-0 == 0`), asi que el caso "no protejas
        # ningun paso" se resuelve aqui y no con un slice: con el slice, `keep_last_steps=0` protegia
        # todos los pasos y la poda no podaba nada (medido: pruned=0 con 5000 chars en la salida).
        for _head, indexes in steps[-int(keep_last_steps):]:
            keep.update(indexes)
    report = PruneReport(steps_seen=len(steps))
    for _head, indexes in steps:
        for index in indexes:
            if index in keep:
                continue
            message = messages[index]
            body = message.text_content() if hasattr(message, "text_content") else str(message.content)
            if MARKER in body or len(body) <= int(min_chars):
                continue
            text = receipt(str(getattr(message, "name", "") or "tool"),
                           _path_of(message, table), body)
            report.pruned += 1
            report.chars_before += len(body)
            report.chars_after += len(text)
            report.receipts.append(text)
            message.content = text
    report.bytes_saved = report.chars_before - report.chars_after
    return report


def selftest():
    import tempfile

    from .message import Message, ToolCall

    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    def step(index, size=4000):
        call = ToolCall(id="c%d" % index, name="read_file", arguments={"path": "f%d.py" % index},
                        raw_arguments='{"path": "f%d.py"}' % index)
        return [Message(role="assistant", content="", tool_calls=[call]),
                Message(role="tool", content="x" * size, tool_call_id=call.id, name="read_file")]

    messages = [Message(role="system", content="reglas"), Message(role="user", content="arregla")]
    for index in range(5):
        messages.extend(step(index))
    report = prune(messages)
    check("se podan los pasos antiguos", report.pruned, 3)
    check("los dos ultimos pasos siguen intactos", [len(messages[i].content) for i in (9, 11)],
          [4000, 4000])
    check("el recibo es una linea", len(report.receipts[0].splitlines()), 1)
    check("el recibo dice la herramienta", "read_file" in report.receipts[0], True)
    check("el recibo dice el fichero", "f0.py" in report.receipts[0], True)
    check("el recibo dice el rango", "L1" in report.receipts[0], True)
    check("el recibo dice los chars antes", "4000 chars" in report.receipts[0], True)
    check("el recibo lleva sha256", "sha256:" in report.receipts[0], True)
    check("el recibo invita a releer", "Re-lee" in report.receipts[0], True)
    check("el ahorro se mide en bytes",
          report.bytes_saved > 3 * 3800 and report.bytes_saved < 3 * 4001, True)
    check("los tokens ahorrados son los bytes/4", report.tokens_saved,
          report.bytes_saved // CHARS_PER_TOKEN)
    check("podar dos veces no cambia nada", prune(messages).bytes_saved, 0)
    modelo = [len(m.content) for m in messages if m.role in ("system", "user", "assistant")]
    prune(messages, keep_last_steps=0)
    check("el contenido del modelo no se toca",
          [len(m.content) for m in messages if m.role in ("system", "user", "assistant")], modelo)

    short = [Message(role="assistant", content="", tool_calls=[ToolCall(id="z", name="shell")]),
             Message(role="tool", content="ok", tool_call_id="z", name="shell")]
    check("una salida corta no se poda", prune(short).pruned, 0)
    check("y sigue corta", short[1].content, "ok")

    with tempfile.TemporaryDirectory(prefix="pruner-") as workspace:
        from pathlib import Path
        (Path(workspace) / "f0.py").write_text("x" * 4000, encoding="utf-8")
        three = [Message(role="system", content="reglas")]
        for index in range(3):
            three.extend(step(index))
        window = prune(three, keep_last_steps=2)
        check("con 3 pasos solo se poda el primero", window.pruned, 1)
        check("y el recibo trae el camino real", "f0.py" in window.receipts[0], True)
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("context_pruner: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
