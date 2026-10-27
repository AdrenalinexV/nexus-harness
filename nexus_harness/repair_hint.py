"""El modelo falla dos veces en el mismo parche: se le ponen delante las lineas REALES del fichero.

Un modelo que repite el mismo `old_string` que no existe no esta razonando mal: le falta el texto
verdadero, y se lo esta inventando. Repetir el error cuesta un turno; ensenarle las lineas alrededor
del fallo cuesta cien tokens y rompe el bucle.

Dos reglas para que esto no se convierta en ruido:

* **Solo al segundo fallo del MISMO (herramienta, fichero).** Un fallo aislado es informacion
  suficiente: el modelo puede reaccionar. La pista llega cuando ya demostro que no reacciona.
* **La pista son lineas numeradas, no una opinion.** Se busca el numero de linea que el propio error
  menciona (`line 42`, `linea 42`, `:42:`) y se cortan `radius` lineas alrededor. Si no hay numero, se
  ensena el principio del fichero, que es donde suele estar la firma que el parche no encontro.
"""
import re
from pathlib import Path

LINE_HINT = re.compile(r"(?:line|linea|línea|L)\s*[:#]?\s*(\d{1,6})|:(\d{1,6}):", re.I)
MAX_CHARS = 1800
MAX_LINES = 28


def target_path(arguments):
    """El `path`/`file` de la llamada, relativo a la raiz del registro."""
    arguments = arguments if isinstance(arguments, dict) else {}
    for key in ("path", "file", "filename"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def guess_line(error):
    """El primer numero de linea que el error menciona, o 0."""
    match = LINE_HINT.search(str(error or ""))
    if not match:
        return 0
    try:
        return int(match.group(1) or match.group(2) or 0)
    except ValueError:
        return 0


def snippet(root, path, error="", radius=6):
    """Lineas numeradas del fichero alrededor del fallo. `(texto, primera_linea)`; vacio si no hay."""
    root = Path(root)
    target = (root / path) if path else None
    if target is None or not target.is_file():
        return "", 0
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "", 0
    if not lines:
        return "", 0
    line = guess_line(error)
    start = max(1, line - radius) if line else 1
    window = lines[start - 1:start - 1 + MAX_LINES]
    body = "\n".join("%4d | %s" % (start + index, text) for index, text in enumerate(window))
    return body[:MAX_CHARS], start


class RepairHints:
    """Cuenta fallos por (herramienta, fichero) y devuelve la pista a partir del segundo."""

    def __init__(self, root, threshold=2):
        self.root = Path(root)
        self.threshold = int(threshold)
        self.counts = {}
        self.last = ""

    def note(self, tool, arguments, error):
        """La pista para este fallo, o `""` cuando todavia no toca."""
        path = target_path(arguments)
        key = "%s|%s" % (tool, path or "?")
        self.counts[key] = self.counts.get(key, 0) + 1
        if self.counts[key] < self.threshold or not path:
            return ""
        body, start = snippet(self.root, path, error)
        if not body:
            self.last = "no se pudo leer %s para ensenar sus lineas" % path
            return ""
        self.last = "%s desde la linea %d" % (path, start)
        return ("[reparacion] %s fallo %d veces sobre %s. Estas son las lineas REALES del fichero "
                "(no las inventes):\n%s"
                % (tool, self.counts[key], path, body))

    def reset(self, tool=None, arguments=None):
        """Olvida el contador de una llamada (o todos). Se usa cuando el fichero se edito bien."""
        if tool is None:
            self.counts.clear()
            return
        path = target_path(arguments)
        if path:
            # Un fichero que YA se edito bien no tiene por que arrastrar el contador de otra
            # herramienta: el fallo viejo de `patch_replace` no debe dar pista en el `write_file`.
            suffix = "|%s" % path
            for key in [name for name in self.counts if name.endswith(suffix)]:
                self.counts.pop(key, None)
            return
        self.counts.pop("%s|?" % tool, None)

    def status(self):
        return {"counts": dict(self.counts), "last": self.last}


def selftest():
    import tempfile

    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    with tempfile.TemporaryDirectory(prefix="repair-hint-") as workspace:
        root = Path(workspace)
        rows = "\n".join("LINEA_%02d = %d" % (index, index) for index in range(1, 41))
        (root / "calc.py").write_text(rows + "\n", encoding="utf-8")
        hints = RepairHints(root)
        check("el primer fallo no da pista", hints.note("patch_replace", {"path": "calc.py"},
                                                        "old_string not found, line 20"), "")
        hint = hints.note("patch_replace", {"path": "calc.py"}, "old_string not found, line 20")
        check("el segundo fallo si", "[reparacion]" in hint, True)
        check("la pista trae lineas numeradas", "  20 | LINEA_20" in hint, True)
        check("y contexto alrededor", "LINEA_14" in hint and "LINEA_26" in hint, True)
        check("un fichero distinto cuenta aparte",
              hints.note("patch_replace", {"path": "otro.py"}, "line 3"), "")
        check("sin ruta no hay pista", hints.note("shell", {}, "boom"), "")
        check("un fichero inexistente se declara",
              hints.note("patch_replace", {"path": "nope.py"}, "line 1"), "")
        body, start = snippet(root, "calc.py", "line 1")
        check("la ventana empieza en la linea 1", start, 1)
        check("y no se pasa del limite", len(body.splitlines()) <= MAX_LINES, True)
        check("sin numero de linea empieza arriba", snippet(root, "calc.py", "sin pista")[1], 1)
        hints.reset()
        check("reset olvida todo", hints.counts, {})
        check("el error nombra la herramienta y el fichero", "patch_replace" in hint and
              "calc.py" in hint, True)
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("repair_hint: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
