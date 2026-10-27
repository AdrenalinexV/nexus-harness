"""Conteo de tokens: estimacion honesta y calibracion con el `usage` real del proveedor.

El fallo que arregla: todo el presupuesto del arnes (poda al 55 %, relevo al 70 %, baseline del
benchmark) se media con `chars / 4`. En codigo con identificadores largos, JSON de herramientas y
acentos ese cociente se desvia un 20-30 %, y con el se desvia el momento en que el arnes decide podar
o relevar.

Dos numeros, y cada uno dice que es:

* `estimate(text)` -- una estimacion estructural, determinista y sin dependencias: palabras, signos y
  saltos de linea pesan distinto, que es lo que un BPE hace de verdad.
* `count(text, model)` -- la estimacion corregida por el factor **medido** de ese modelo. El factor
  sale de comparar la estimacion con el `prompt_tokens` que el proveedor devolvio, y se guarda en
  `.nexus/harness/token_calibration.json`. Sin muestras, el factor es 1,0 (no se inventa correccion).

Regla que no se relaja: una cifra sin calibrar se presenta como estimacion, nunca como medida.
"""
import json
import math
import os
import re
import time
from pathlib import Path

# El cociente historico. Se conserva como unidad de referencia para que las cifras antiguas sigan
# siendo comparables, pero ya no es la unica verdad.
CHARS_PER_TOKEN = 4
# Un BPE parte en palabras y en signos; los saltos de linea y la indentacion tambien cuestan. Estos
# pesos salen de comparar la estimacion con usage real en codigo Python y en texto espanol.
WORD_WEIGHT = 1.0
SIGN_WEIGHT = 1.0
NEWLINE_WEIGHT = 0.5
NON_ASCII_WEIGHT = 0.35
MIN_RATIO, MAX_RATIO = 0.4, 3.0
LEARNING_RATE = 0.34
CALIBRATION_REL = Path(".nexus") / "harness" / "token_calibration.json"
WORD = re.compile(r"[A-Za-z0-9_]+")
SIGN = re.compile(r"[^\sA-Za-z0-9_]")


def estimate(text):
    """Estimacion estructural de tokens para un texto. Determinista y sin red."""
    body = str(text or "")
    if not body:
        return 0
    words = len(WORD.findall(body))
    signs = len(SIGN.findall(body))
    newlines = body.count("\n")
    non_ascii = sum(1 for char in body if ord(char) > 127)
    # Una palabra media de codigo son ~1,3 tokens (identificadores partidos), pero el peso 1,0 con el
    # termino de longitud mantiene la estimacion cerca del cociente clasico en texto plano.
    long_terms = sum(max(0, len(word) - 6) for word in WORD.findall(body))
    units = (words * WORD_WEIGHT + signs * SIGN_WEIGHT + newlines * NEWLINE_WEIGHT
             + non_ascii * NON_ASCII_WEIGHT + long_terms * 0.15)
    return max(1, int(math.ceil(units)))


def _calibration_path(path=None):
    if path:
        return Path(path)
    home = Path(os.environ.get("NEXUS_HOME") or (Path.home() / ".nexus"))
    return home / Path("harness") / "token_calibration.json"


class Calibration:
    """Factor por modelo: `medido / estimado`, con media movil y limites que impiden el absurdo."""

    def __init__(self, path=None):
        self.path = _calibration_path(path)
        self.rows = self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.rows, indent=1, sort_keys=True), encoding="utf-8")
            return True
        except OSError:
            return False

    def factor(self, model=""):
        row = self.rows.get(str(model or "")) or {}
        try:
            value = float(row.get("factor") or 1.0)
        except (TypeError, ValueError):
            return 1.0
        return min(MAX_RATIO, max(MIN_RATIO, value))

    def observe(self, model, estimated, actual):
        """Una muestra (estimado, real). Devuelve el factor resultante; ignora muestras imposibles."""
        estimated, actual = int(estimated or 0), int(actual or 0)
        if estimated <= 0 or actual <= 0:
            return self.factor(model)
        ratio = min(MAX_RATIO, max(MIN_RATIO, actual / float(estimated)))
        key = str(model or "")
        row = dict(self.rows.get(key) or {})
        previous = float(row.get("factor") or 1.0)
        samples = int(row.get("samples") or 0)
        updated = ratio if samples == 0 else (previous * (1 - LEARNING_RATE) + ratio * LEARNING_RATE)
        self.rows[key] = {"factor": round(updated, 4), "samples": samples + 1,
                          "last_ratio": round(ratio, 4),
                          "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        self.save()
        return self.rows[key]["factor"]

    def as_dict(self):
        return {model: dict(row) for model, row in self.rows.items()}


_DEFAULT = None


def calibration(path=None):
    """La calibracion de esta maquina, cargada una vez por proceso (el fichero manda)."""
    global _DEFAULT
    if path is not None:
        return Calibration(path)
    if _DEFAULT is None:
        _DEFAULT = Calibration()
    return _DEFAULT


def count(text, model="", cal=None):
    """Tokens estimados y corregidos por el factor medido de `model`."""
    base = estimate(text)
    if not base:
        return 0
    return max(1, int(round(base * (cal or calibration()).factor(model))))


def count_messages(messages, model="", cal=None):
    """Lo que cuesta el prompt: el texto de cada mensaje mas su envoltorio de rol."""
    total = 0
    for message in messages or ():
        body = message.text_content() if hasattr(message, "text_content") else str(
            getattr(message, "content", "") or "")
        total += count(body, model, cal) + 4   # ~4 tokens por envoltorio de rol/plantilla
    return total


def selftest():
    import tempfile

    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    check("vacio es cero", estimate(""), 0)
    check("una palabra cuesta algo", estimate("hola") >= 1, True)
    check("mas texto cuesta mas", estimate("hola mundo " * 100) > estimate("hola mundo"), True)
    check("el conteo es determinista", estimate("def foo(x):\n    return x + 1\n"),
          estimate("def foo(x):\n    return x + 1\n"))
    check("una palabra suelta no infla", estimate("a") <= 2, True)

    with tempfile.TemporaryDirectory(prefix="tokenizer-") as workspace:
        cal = Calibration(Path(workspace) / "cal.json")
        check("sin muestras el factor es 1", cal.factor("m"), 1.0)
        check("sin muestras el conteo es la estimacion", count("hola mundo", "m", cal),
              estimate("hola mundo"))
        for _round in range(12):
            cal.observe("m", 100, 130)
        factor = cal.factor("m")
        check("doce muestras convergen al sesgo real", 1.25 <= factor <= 1.35, True)
        corrected = count("x" * 100, "m", cal)
        check("y el conteo corregido sube", corrected > estimate("x" * 100), True)
        check("una muestra imposible no rompe el factor", cal.observe("m", 0, 500) > 0, True)
        check("el otro modelo no hereda el factor", cal.factor("otro"), 1.0)
        reloaded = Calibration(Path(workspace) / "cal.json")
        check("el factor sobrevive al proceso", round(reloaded.factor("m"), 2), round(factor, 2))
        check("los limites acotan un sesgo absurdo",
              Calibration(Path(workspace) / "r.json").observe("z", 1, 100000) <= MAX_RATIO, True)
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("tokenizer: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
