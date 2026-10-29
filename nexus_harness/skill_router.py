"""Enrutado de skills por turno: <=10 en RAM, el resto dormidas en disco a coste cero.

El protocolo ya sabe puntuar especialistas contra los ficheros de un turno
(`nexus/skills/routing.py`), pero su respuesta es "los dos mejores". Un harness que ademas forja sus
propias skills necesita dos cosas que ese calculo no da:

1. **Un techo duro.** `MAX_ACTIVE = 10`. Si el techo se rompe, el prompt crece hasta que el modelo
   deja de obedecer al prompt; el techo es la ley, y se aplica DESPUES de ordenar, no antes.
2. **Un catalogo dormido en disco.** Las skills que no viajan se indexan en `.nexus/skills-dormant/`
   con nombre, descripcion, palabras clave y sha256 del `SKILL.md`. Ese indice ocupa bytes en disco y
   CERO tokens en la ventana: se lee solo cuando hace falta mirar que existe.

El enrutado es determinista: misma tarea, mismos ficheros, misma lista. Nada de aleatoriedad ni de
"el modelo elige": una eleccion que cambia entre dos llamadas no se puede probar.

Las skills propias (forjadas) viven en `<root>/.nexus/skills/<name>/SKILL.md` y entran en el mismo
concurso que las del protocolo. Una skill forjada que nunca gana un turno es una skill que no servia.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .core.outcomes import Outcomes
from .relay_state import sha256_text
from .platform.skillfiles import FORGED_REL, parse_frontmatter  # noqa: E402

MAX_ACTIVE = 10
DORMANT_REL = Path(".nexus") / "skills-dormant"
INDEX_NAME = "index.json"
NEXUS_SOURCE = Path(r"C:\Proyectos\NexusProtocol")
# Las raices que de verdad tiene esta maquina: el protocolo, lo forjado y el catalogo que el operador
# ya usa en Hermes. Se declaran aqui y no se inventan rutas: una que no exista simplemente no aporta.
HERMES_ROOTS = (Path.home() / "AppData/Local/hermes/profiles/nexus-harness/skills",
                Path.home() / "AppData/Local/hermes/skills")
MAX_BRIEF_CHARS = 120
STOPWORDS = {"the", "and", "for", "con", "los", "las", "del", "que", "una", "por", "para", "este",
             "esta", "como", "mas", "pero", "sin", "sus", "sea", "hay", "todo", "cada"}
WORD = re.compile(r"[a-záéíóúñ0-9_+#.-]{3,}")
EXTENSIONS = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "react", ".jsx": "react",
    ".sql": "sql", ".rs": "rust", ".go": "go", ".php": "php", ".lua": "lua", ".css": "css",
    ".html": "html", ".yml": "yaml", ".yaml": "yaml", ".json": "json", ".md": "docs",
    ".sh": "shell", ".ps1": "powershell", ".cs": "csharp", ".java": "java", ".exe": "release",
}


def words(text):
    """Palabras significativas, en minusculas y sin duplicados. Puro y ordenado: mismo texto, mismo set."""
    return sorted({token for token in WORD.findall(str(text or "").lower())
                   if token not in STOPWORDS})


def skill_entry(path, root):
    """Una fila del catalogo: lo justo para puntuar sin volver a leer el fichero entero."""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fields, _body = parse_frontmatter(text)
    name = str(fields.get("name") or source.parent.name)
    description = str(fields.get("description") or "")
    keywords = fields.get("keywords") or fields.get("when_to_use") or ""
    return {"name": name, "description": description[:400], "keywords": str(keywords)[:400],
            "path": str(source), "root": str(root), "sha256": sha256_text(text),
            "lines": text.count("\n") + 1, "words": words("%s %s %s" % (name, description, keywords))}


def scan(root, limit=600):
    """Las skills de un arbol, en orden estable. Un `SKILL.md` por directorio, como el protocolo."""
    base = Path(root)
    entries = []
    if not base.is_dir():
        return entries
    for path in sorted(base.rglob("SKILL.md")):
        if ".git" in path.parts or "node_modules" in path.parts:
            continue
        entry = skill_entry(path, base)
        if entry is not None:
            entries.append(entry)
        if len(entries) >= limit:
            break
    return entries


def protocol_roots(project_root=None):
    """Las raices reales del catalogo, si estan en esta maquina. Nunca se inventan rutas."""
    roots = [Path(project_root) / FORGED_REL] if project_root else []
    for candidate in (NEXUS_SOURCE / "skills", NEXUS_SOURCE / "nexus" / "skills") + HERMES_ROOTS:
        if candidate.is_dir():
            roots.append(candidate)
    return roots


@dataclass
class Injection:
    """Lo que viaja con el turno: nombres, texto compacto, coste y por que. Un solo contrato."""

    names: list = field(default_factory=list)
    entries: list = field(default_factory=list)
    brief: str = ""
    tokens: int = 0
    available: bool = True
    note: str = ""

    def as_dict(self):
        return {"names": list(self.names), "tokens": self.tokens, "available": self.available,
                "note": self.note, "chars": len(self.brief)}


def brief_of(entries):
    """El texto que viaja: una linea por skill, con su descripcion recortada.

    No se manda el cuerpo entero: 173 cuerpos son ~446.000 tokens (medido). Lo que el modelo necesita
    al planear es QUE existe y para que sirve; el cuerpo se lee con `read_file` cuando hace falta.
    """
    lines = []
    for entry in entries:
        description = " ".join(str(entry.get("description") or "").split())
        if len(description) > MAX_BRIEF_CHARS:
            description = description[:MAX_BRIEF_CHARS - 1] + "\u2026"
        lines.append("- %s: %s" % (entry.get("name"), description or "(sin descripcion)"))
    if not lines:
        return ""
    return "## Skills de este turno (lee el SKILL.md si necesitas la regla completa)\n%s" \
        % "\n".join(lines)


class SkillRouter:
    """Puntua el catalogo contra la tarea y los ficheros del turno, y aplica el techo de 10."""

    def __init__(self, root=None, roots=None, max_active=MAX_ACTIVE, outcomes=None):
        self.root = Path(root) if root else None
        self.roots = [Path(item) for item in (roots or protocol_roots(root))]
        self.max_active = max(1, int(max_active))
        self.catalog = []
        self.last = []
        # El libro de resultados ajusta el ORDEN; no inventa skills ni sustituye al lexico.
        self.outcomes = outcomes

    def load(self):
        seen, rows = set(), []
        for root in self.roots:
            for entry in scan(root):
                if entry["name"] in seen:
                    continue
                seen.add(entry["name"])
                rows.append(entry)
        self.catalog = rows
        return self

    def score(self, entry, task_words, file_exts):
        """Cuenta de coincidencias. Un acierto en el nombre vale el doble que uno en la descripcion."""
        name = set(words(entry.get("name")))
        body = set(entry.get("words") or [])
        score = 0
        for token in task_words:
            if token in name:
                score += 3
            elif token in body:
                score += 1
        for ext in file_exts:
            if ext in name or ext in body:
                score += 2
        return score

    def raise_score(self, score, name):
        """Ajusta el score con la tasa de exito medida de esa skill (acotada, nunca secuestra)."""
        if self.outcomes is None or score <= 0:
            return score
        try:
            multiplier = float(self.outcomes.multiplier(name))
        except Exception:  # noqa: BLE001 -- un libro ilegible no puede dejar el turno sin skills
            return score
        return int(round(score * multiplier))

    def select(self, task="", files=(), limit=None):
        """La lista que viaja: como mucho `limit` (y nunca mas de `max_active`), ordenada."""
        if not self.catalog:
            self.load()
        cap = min(int(limit or self.max_active), self.max_active)
        task_words = words(task)
        file_exts = sorted({EXTENSIONS.get(Path(str(name)).suffix.lower(), "")
                            for name in files or ()} - {""})
        scored = [(self.raise_score(self.score(entry, task_words, file_exts), entry["name"]), entry)
                  for entry in self.catalog]
        scored = [(score, entry) for score, entry in scored if score > 0]
        scored.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
        self.last = [entry for _score, entry in scored[:cap]]
        return self.last

    def inject(self, files=(), task="", limit=None):
        """El contrato que usa el bucle: nombres, brief medido y coste. Una sola fuente de skills.

        Se enruta tambien con los NOMBRES de los ficheros: un turno sobre `auth.py` lleva las skills
        de auth aunque la frase del operador no diga la palabra.
        """
        if not self.catalog:
            self.load()
        names = sorted(str(item) for item in files or () if str(item).strip())
        picked = self.select(" ".join([str(task or "")] + names), names, limit)
        brief = brief_of(picked)
        return Injection(names=[entry["name"] for entry in picked], entries=picked, brief=brief,
                         tokens=max(0, len(brief) // 4), available=True,
                         note="" if picked else "ninguna skill puntuo para este turno")

    def dormant(self):
        """El catalogo que NO viaja: lo que queda fuera del techo."""
        active = {entry["name"] for entry in self.last}
        return [entry for entry in self.catalog if entry["name"] not in active]

    def save_dormant(self):
        """Escribe el indice dormido en disco. Devuelve `(rutas, bytes)`; idempotente."""
        if self.root is None:
            return [], 0
        folder = self.root / DORMANT_REL
        folder.mkdir(parents=True, exist_ok=True)
        written, total = [], 0
        for entry in self.dormant():
            path = folder / ("%s.json" % entry["sha256"][:16])
            payload = json.dumps({key: entry[key] for key in
                                  ("name", "description", "path", "root", "sha256", "lines")},
                                 indent=2, sort_keys=True, ensure_ascii=False)
            if not path.is_file() or path.read_text(encoding="utf-8") != payload:
                path.write_text(payload, encoding="utf-8")
            written.append(str(path))
            total += len(payload)
        index = folder / INDEX_NAME
        index.write_text(json.dumps({"active": [entry["name"] for entry in self.last],
                                     "dormant": len(written), "catalog": len(self.catalog)},
                                    indent=2, sort_keys=True), encoding="utf-8")
        return written, total

    def status(self):
        return {"catalog": len(self.catalog), "active": [entry["name"] for entry in self.last],
                "dormant": max(0, len(self.catalog) - len(self.last)), "cap": self.max_active,
                "roots": [str(root) for root in self.roots]}


def library(root=None, max_active=MAX_ACTIVE, outcomes=None):
    """El UNICO catalogo del arnes: protocolo, skills forjadas y catalogo de Hermes, con su libro.

    Antes habia dos enrutadores (uno de 2 especialistas y otro de 10 con dormidas) y solo uno corria.
    Este es el que corre, y su `inject()` es el contrato que usan el chat y la triada.
    """
    target = Path(root) if root else None
    book = outcomes if outcomes is not None else (Outcomes(target) if target else None)
    return SkillRouter(target, max_active=max_active, outcomes=book).load()


def selftest():
    import tempfile

    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    with tempfile.TemporaryDirectory(prefix="skill-router-") as workspace:
        root = Path(workspace)
        for name, body in (("fastapi", "python api http servidor"), ("rust-cli", "rust cargo cli"),
                           ("postgres", "sql postgres indices"), ("release", "exe instalador")):
            folder = root / name
            folder.mkdir()
            (folder / "SKILL.md").write_text(
                "---\nname: %s\ndescription: %s\nkeywords: %s\n---\n\ncuerpo\n"
                % (name, body, body), encoding="utf-8")
        for index in range(14):
            extra = root / ("extra%02d" % index)
            extra.mkdir()
            (extra / "SKILL.md").write_text("---\nname: extra%02d\ndescription: python\n---\n"
                                            % index, encoding="utf-8")
        router = SkillRouter(root, roots=[root]).load()
        check("el catalogo ve las 18", len(router.catalog), 18)
        picked = router.select("montar un servidor en python", ["api.py"])
        check("el techo de 10 se respeta", len(picked) <= 10 and len(picked) == 10, True)
        check("fastapi gana el turno", picked[0]["name"], "fastapi")
        check("el orden es estable", [item["name"] for item in picked],
              [item["name"] for item in router.select("montar un servidor en python", ["api.py"])])
        check("el frontmatter se parsea", picked[0]["description"], "python api http servidor")
        written, size = router.save_dormant()
        check("las dormidas se indexan", len(written), 8)
        check("el indice ocupa bytes, no tokens", size > 0, True)
        check("el indice existe", (root / DORMANT_REL / INDEX_NAME).is_file(), True)
        index = json.loads((root / DORMANT_REL / INDEX_NAME).read_text(encoding="utf-8"))
        check("el indice dice cuantas viajan", len(index["active"]), 10)
        check("guardar dos veces no duplica", len(router.save_dormant()[0]), 8)
        check("un turno sin coincidencias no activa nada", router.select("xylofono", []) == [], True)
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("skill_router: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
