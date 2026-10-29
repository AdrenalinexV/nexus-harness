"""Compilar el contexto del turno: un prefijo congelado y un delta que solo crece por el final.

El fallo que arregla: `chat.py` y `triad_loop.py` reconstruian el mensaje `system` en CADA paso con el
conjunto de ficheros tocados, que crece. El byte 0 del prompt cambiaba en cada llamada, y con el se
invalidaba la cache de prefijo de DeepSeek, Anthropic y OpenAI: se pagaba la entrada completa N veces
y se perdia el prefill. Medido en el codigo, no supuesto: `messages[0] = ...self._system(...)` dentro
del bucle.

La regla es de bytes:

* **L0 (prefijo)**: reglas del arnes, memoria del operador, mapa de simbolos y hechos del proyecto. Se
  construye UNA vez por turno y no se reescribe hasta el turno siguiente. Su `sha256` es el contrato.
* **L1..Ln (delta)**: lo que cambia mientras el turno avanza (skills que entran al tocar un fichero
  nuevo). Se ANADE al final como un mensaje propio, nunca reescribiendo lo anterior: append-only es
  justo lo que una cache de prefijo sabe aprovechar.

Presupuesto: cada seccion declara su techo en tokens y el compilador recorta por el final de la
seccion (nunca por el principio: el principio es lo estable). Lo recortado se declara en el propio
texto, para que el modelo sepa que falta y pueda pedirlo.
"""
import hashlib
from dataclasses import dataclass, field

from ..core.message import Message
from ..platform.tokenizer import count

DELTA_MARKER = "## Contexto actualizado (NEXUS)"
DEFAULT_MAX_DELTAS = 8
# Techos por seccion, en tokens. Son presupuestos, no sugerencias: el compilador recorta y lo dice.
SECTION_CAPS = {"rules": 900, "memory": 1200, "map": 1500, "facts": 200, "skills": 700}


def sha(text):
    return hashlib.sha256(str(text or "").encode("utf-8", "replace")).hexdigest()


def clip(text, cap_tokens, model=""):
    """Recorta por el final hasta caber en `cap_tokens`, con una nota de lo que se dejo fuera."""
    body = str(text or "")
    if not body:
        return "", 0
    total = count(body, model)
    if total <= cap_tokens:
        return body, total
    # Proporcion de chars por token del propio texto: recorta sin partir la estimacion en seco.
    keep = max(0, int(len(body) * (float(cap_tokens) / max(1, total))))
    shortened = body[:keep].rstrip()
    note = "\n[...recortado por presupuesto: %d -> %d tokens]" % (total, cap_tokens)
    return shortened + note, count(shortened + note, model)


@dataclass
class Section:
    """Una pieza del prefijo: lo que es, lo que cuesta y si cupo."""

    name: str
    text: str
    tokens: int = 0
    cap: int = 0
    clipped: bool = False

    def as_dict(self):
        return {"name": self.name, "tokens": self.tokens, "cap": self.cap,
                "chars": len(self.text), "clipped": self.clipped}


@dataclass
class Prefix:
    """El bloque estable de un turno. `digest` es lo que se compara entre pasos."""

    text: str = ""
    digest: str = ""
    tokens: int = 0
    sections: list = field(default_factory=list)

    def as_dict(self):
        return {"digest": self.digest[:16], "tokens": self.tokens,
                "sections": [section.as_dict() for section in self.sections]}


def build_prefix(parts, model=""):
    """`[(nombre, texto)]` -> `Prefix` con techos por seccion y digest estable."""
    sections, pieces = [], []
    for name, text in parts:
        body = str(text or "").strip()
        if not body:
            continue
        cap = int(SECTION_CAPS.get(name, 0) or 0)
        tokens = count(body, model)
        clipped = False
        if cap and tokens > cap:
            body, tokens = clip(body, cap, model)
            clipped = True
        sections.append(Section(name=name, text=body, tokens=tokens, cap=cap, clipped=clipped))
        pieces.append(body)
    text = "\n\n".join(pieces)
    return Prefix(text=text, digest=sha(text), tokens=sum(one.tokens for one in sections),
                  sections=sections)


class TurnWindow:
    """La ventana de un turno: prefijo fijo + deltas append-only.

    `messages(history)` devuelve exactamente lo que se envia al modelo. `note()` solo anade cuando el
    texto cambia, asi que dos pasos seguidos con los mismos ficheros no duplican contexto.
    """

    def __init__(self, prefix, max_deltas=DEFAULT_MAX_DELTAS, model=""):
        self.prefix = prefix if isinstance(prefix, Prefix) else build_prefix([("rules", prefix)], model)
        self.model = model
        self.max_deltas = max(1, int(max_deltas))
        self.deltas = []
        self._last = {}
        self.dropped = 0

    # -- deltas --------------------------------------------------------------------------------
    def note(self, kind, text):
        """Anade un delta si su texto cambio. `True` cuando se anadio algo."""
        body = str(text or "").strip()
        if not body:
            return False
        if self._last.get(kind) == body:
            return False
        self._last[kind] = body
        block = "%s\n### %s\n%s" % (DELTA_MARKER, kind, body)
        self.deltas.append(Message(role="user", content=block))
        self._cap()
        return True

    def _cap(self):
        """Techo de deltas: los viejos se funden en uno solo, no se pierden en silencio."""
        if len(self.deltas) <= self.max_deltas:
            return
        excess = len(self.deltas) - self.max_deltas + 1
        merged = "\n".join(message.content for message in self.deltas[:excess])
        self.dropped += excess
        body, _tokens = clip("%s\n\n[fragmentos anteriores fundidos]" % merged, 800, self.model)
        self.deltas = [Message(role="user", content=body)] + self.deltas[excess:]

    # -- envio --------------------------------------------------------------------------------
    def messages(self, history):
        """El prompt completo: prefijo, historia y deltas. Nunca toca `history`."""
        head = [Message(role="system", content=self.prefix.text)] if self.prefix.text else []
        return head + list(history or ()) + list(self.deltas)

    def delta_tokens(self):
        return sum(count(message.content, self.model) for message in self.deltas)

    def as_dict(self):
        return {"prefix": self.prefix.as_dict(), "deltas": len(self.deltas),
                "delta_tokens": self.delta_tokens(), "dropped": self.dropped}


def selftest():
    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    prefix = build_prefix([("rules", "reglas del arnes " * 40), ("facts", "raiz: /tmp")])
    check("el prefijo lleva sus secciones", [one.name for one in prefix.sections], ["rules", "facts"])
    check("el prefijo se mide", prefix.tokens > 0, True)
    check("el digest es estable", build_prefix([("rules", "x"), ("facts", "y")]).digest,
          build_prefix([("rules", "x"), ("facts", "y")]).digest)
    check("y cambia si cambia el texto",
          build_prefix([("rules", "x"), ("facts", "y")]).digest !=
          build_prefix([("rules", "x"), ("facts", "z")]).digest, True)

    window = TurnWindow(prefix)
    history = [Message(role="user", content="arregla calc.py")]
    before = window.messages(history)
    check("el system es el prefijo", before[0].content, prefix.text)
    check("el prefijo no cambia al anadir un delta", window.messages(history)[0].content,
          before[0].content)
    check("un delta se anade", window.note("skills", "python: usa pytest"), True)
    check("el mismo delta no se duplica", window.note("skills", "python: usa pytest"), False)
    check("y viaja al final", window.messages(history)[-1].content.endswith("usa pytest"), True)
    check("la historia original no se toca", len(history), 1)
    check("otro delta distinto si entra", window.note("skills", "rust: cargo test"), True)

    long_prefix = build_prefix([("rules", "palabra " * 5000)])
    check("una seccion que se pasa del techo se recorta", long_prefix.sections[0].clipped, True)
    check("y lo dice en el texto", "recortado por presupuesto" in long_prefix.text, True)

    small = TurnWindow(prefix, max_deltas=2)
    for index in range(4):
        small.note("k%d" % index, "delta %d" % index)
    check("los deltas tienen techo", len(small.deltas), 2)
    check("y los fundidos se declaran", small.dropped > 0, True)
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("context_compiler: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
