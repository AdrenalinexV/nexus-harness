"""Forja de skills: el harness escribe la que le falta y la registra con su SHA-256.

Un agente que tropieza tres veces con el mismo patron tecnico no necesita otro reintento: necesita la
regla que le faltaba. Este modulo la escribe, pero con dos limites que lo mantienen honesto:

* **No inventa conocimiento.** El cuerpo sale de lo que el turno OBSERVO (ficheros, extensiones,
  comandos fallidos) y del borrador deterministico del protocolo (`architect_chat.fallback_draft`).
  Una skill forjada sin modelo dice de donde salio; no finge haber consultado GitHub.
* **Queda registrada con procedencia.** `origin="forged"` y `sha256` del texto exacto en el libro del
  protocolo (`nexus/skills/provenance.py`), o en un `provenance.jsonl` local si el protocolo no esta.
  Un `SKILL.md` sin hash es un fichero que nadie puede auditar.

La skill se escribe en `<root>/.nexus/skills/<slug>/SKILL.md`, que es la primera raiz que mira
`skill_router`, asi que una skill forjada compite por el turno siguiente como cualquier otra.

`ForgeTrigger` es el detector: firma normalizada del fallo (herramienta + extension + primeras
palabras del error) y contador. A los 3 golpes del MISMO patron pide forja; dos fallos distintos no
suman nunca, porque eso convertiria el ruido en doctrina.
"""
import json
import re
from pathlib import Path

from .relay_state import sha256_text, utc_now
from .skill_router import FORGED_REL, parse_frontmatter

NEXUS_SOURCE = Path(r"C:\Proyectos\NexusProtocol")
THRESHOLD = 3
PROVENANCE_LOCAL = Path(".nexus") / "skills-provenance.jsonl"
SLUG = re.compile(r"[^a-z0-9]+")


def slug_of(topic):
    """Nombre de carpeta estable: minusculas, guiones, sin acentos ni simbolos raros."""
    clean = SLUG.sub("-", str(topic or "").strip().lower()
                     .replace("á", "a").replace("é", "e").replace("í", "i")
                     .replace("ó", "o").replace("ú", "u").replace("ñ", "n"))
    return clean.strip("-")[:60] or "skill-sin-nombre"


def _protocol(modname):
    """Un modulo del protocolo, o `None` sin romper la forja. La ausencia se declara, no se disfraza."""
    import sys
    if str(NEXUS_SOURCE) not in sys.path:
        sys.path.insert(0, str(NEXUS_SOURCE))
    try:
        return __import__(modname, fromlist=["*"])
    except Exception:  # noqa: BLE001 -- sin protocolo hay forja local, con su procedencia local
        return None


def draft_for(topic, observations=()):
    """`(name, description, body, source)`. Sin modelo: el borrador del protocolo o el nuestro."""
    architect = _protocol("nexus.skills.architect_chat")
    name = slug_of(topic)
    # Lo OBSERVADO manda: si el turno trae evidencia del repositorio, el borrador generico del
    # protocolo la diluiria. El borrador del protocolo se usa cuando no hay nada observado.
    if architect is not None and not observations:
        try:
            draft, problems = architect.fallback_draft(str(topic))
            if not problems and draft.get("body"):
                return (slug_of(draft.get("name") or name), str(draft.get("description") or topic),
                        str(draft["body"]), "nexus.skills.architect_chat.fallback_draft")
        except Exception:  # noqa: BLE001 -- se cae al borrador local, y el `source` lo dice
            architect = None
    lines = ["# %s" % str(topic).strip().capitalize()[:80], "",
             "Reglas observadas en este repositorio (no son doctrina de terceros):", ""]
    for item in list(observations)[:12]:
        lines.append("- %s" % str(item).strip())
    if not observations:
        lines.append("- Cada afirmacion se comprueba con un comando y su exit code antes de escribirla.")
    return name, str(topic), "\n".join(lines) + "\n", "harness.skill_forge.local"


def render(name, description, body, reason="", topic=""):
    """El `SKILL.md`: frontmatter valido (name/description) y un cuerpo con su motivo."""
    head = ["---", "name: %s" % name, "description: %s" % " ".join(str(description).split())[:300],
            "---", ""]
    tail = [] if not reason else ["", "<!-- forjada: %s · motivo: %s -->" % (utc_now(),
                                                                           " ".join(reason.split())[:200])]
    return "\n".join(head) + str(body).rstrip() + "\n" + "\n".join(tail) + "\n"


def register(root, name, text, source=""):
    """Apunta la skill con su sha256. Devuelve la fila escrita; nunca deja el registro a medias."""
    row = {"name": name, "origin": "forged", "sha256": sha256_text(text), "source": source,
           "at": utc_now()}
    provenance = _protocol("nexus.skills.provenance")
    if provenance is not None:
        try:
            data = provenance.load(root=str(root))
            provenance.record(data, name, "forged", text, source=source or None)
            provenance.save(data, root=str(root))
            row["ledger"] = "protocol"
            return row
        except Exception as exc:  # noqa: BLE001 -- se registra localmente y se dice por que
            row["ledger_note"] = "%s: %s" % (type(exc).__name__, exc)
    path = Path(root) / PROVENANCE_LOCAL
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    row["ledger"] = "local"
    return row


def forge(root, topic, reason="", observations=(), overwrite=False):
    """Escribe la skill. `{ok, name, path, sha256, source, ledger}`; una existente NO se pisa."""
    root = Path(root)
    name, description, body, source = draft_for(topic, observations)
    # La carpeta la fija el TEMA, no el nombre que devuelva el borrador: dos forjas del mismo tema
    # tienen que caer en el mismo sitio o la segunda pisaria a la primera sin saberlo.
    slug = slug_of(topic)
    folder = root / FORGED_REL / slug
    path = folder / "SKILL.md"
    if path.is_file() and not overwrite:
        text = path.read_text(encoding="utf-8", errors="replace")
        return {"ok": True, "name": name, "path": str(path), "sha256": sha256_text(text),
                "source": source, "ledger": "existing", "created": False}
    text = render(name, description, body, reason=reason, topic=topic)
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    row = register(root, name, text, source)
    asked = parse_frontmatter(text)
    ok = bool(asked[0].get("name")) and bool(asked[0].get("description"))
    return {"ok": ok, "name": name, "path": str(path), "sha256": row["sha256"], "source": source,
            "ledger": row.get("ledger"), "created": True, "reason": reason}


class ForgeTrigger:
    """Cuenta fallos por patron. Tres del mismo patron piden skill; dos distintos no piden nada."""

    def __init__(self, threshold=THRESHOLD):
        self.threshold = int(threshold)
        self.counts = {}
        self.asked = {}

    @staticmethod
    def signature(tool, path, error):
        """`(herramienta, extension, primeras palabras)` normalizado: misma causa, misma firma."""
        ext = Path(str(path or "")).suffix.lower() or "?"
        head = " ".join(re.findall(r"[a-zA-Z]{4,}", str(error or ""))[:4]).lower()
        return "%s|%s|%s" % (str(tool or "?"), ext, head or "sin-detalle")

    def hit(self, tool, path, error="", topic=""):
        """Registra un fallo y devuelve `{fires, count, signature, topic}`. Puro salvo su contador."""
        key = self.signature(tool, path, error)
        self.counts[key] = self.counts.get(key, 0) + 1
        count = self.counts[key]
        fires = count >= self.threshold and key not in self.asked
        if fires:
            self.asked[key] = topic or key
        return {"fires": fires, "count": count, "signature": key,
                "topic": self.asked.get(key, topic or key)}

    def status(self):
        return {"counts": dict(self.counts), "asked": dict(self.asked)}


def selftest():
    import tempfile

    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    with tempfile.TemporaryDirectory(prefix="skill-forge-") as workspace:
        root = Path(workspace)
        result = forge(root, "Rust + Tauri v2", reason="tres fallos en src/main.rs",
                       observations=["cargo test antes de declarar hecho",
                             "un comando, su salida y su exit code"])
        check("la skill se crea", result["created"], True)
        check("el frontmatter es valido", result["ok"], True)
        check("queda en .nexus/skills", ".nexus/skills/rust-tauri-v2/SKILL.md" in
              result["path"].replace("\\", "/"), True)
        text = Path(result["path"]).read_text(encoding="utf-8")
        check("el cuerpo lleva lo observado", "cargo test" in text, True)
        check("el motivo queda escrito", "tres fallos" in text, True)
        check("el sha256 es el del fichero", result["sha256"], sha256_text(text))
        again = forge(root, "Rust + Tauri v2")
        check("una skill existente no se pisa", again["created"], False)
        check("y su sha no cambia", again["sha256"], result["sha256"])
        ledger = root / ".nexus" / "skills-provenance.jsonl"
        rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
        check("la procedencia se registra", rows[-1]["sha256"], result["sha256"])
        check("el origen es forged", rows[-1]["origin"], "forged")
        check("el slug sanea acentos", slug_of("Diseño de API"), "diseno-de-api")

    trigger = ForgeTrigger(threshold=3)
    first = trigger.hit("shell", "src/main.rs", "cannot find crate")
    check("el primer fallo no forja", first["fires"], False)
    check("dos fallos distintos no suman", trigger.hit("shell", "web/app.ts", "type error")["count"], 1)
    check("el segundo del mismo patron no forja", trigger.hit(
        "shell", "src/lib.rs", "cannot find crate")["fires"], False)
    third = trigger.hit("shell", "src/api.rs", "cannot find crate", topic="rust workspaces")
    check("el tercero del mismo patron forja", third["fires"], True)
    check("y no vuelve a pedirlo", trigger.hit("shell", "src/x.rs", "cannot find crate")["fires"],
          False)
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("skill_forge: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
