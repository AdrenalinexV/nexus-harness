"""Contabilidad exacta del ahorro: por request, con baseline y multiplicador de contexto.

El fallo que arregla: el libro de turnos guardaba `prompt_tokens` y `completion_tokens`, y **cero**
campos de ahorro. Sin baseline no hay ahorro medible, y sin ahorro medible la tarjeta «tokens
evitados» acababa enseñando el numero del ledger del GOBERNADOR (3.653.208) mientras las barras verdes
dibujaban datos de OTRA fuente (1.091.148). Dos numeros, dos fuentes, ni uno solo del motor.

Aqui se mide lo que de verdad viaja y lo que habria viajado:

    baseline = sent - repo_map + skills_dormidas + podado + aislado

* **`sent`**: los tokens reales del prompt que se enviaron (del `usage` del proveedor cuando lo da, del
  contador determinista cuando no).
* **`- repo_map`**: el mapa AST es un COSTE que este motor anade. Un harness tradicional no lo envia, y
  no se le atribuye ningun ahorro por las lecturas que no hizo: no se puede medir lo que no ocurrio.
* **`skills_dormidas`**: el indice completo de skills instaladas (medido: 173 skills ≈ 3.369 tokens por
  request) menos lo que realmente viaja (el brief de las ≤ 10 seleccionadas).
* **`podado`**: los bytes reales de salidas de herramientas sustituidos por recibos, /4.
* **`aislado`**: los tokens de la reparacion que el Obrero hizo en su worktree y que NO entraron en la
  ventana principal.

Con eso salen tres cifras que un harness tradicional no puede dar: `tokens_saved`, `savings_pct` y
`context_multiplier` (cuantas veces mas cabria una ventana del mismo tamano).
"""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .context_pruner import CHARS_PER_TOKEN
from .skill_router import skill_entry

CACHE_REL = Path(".nexus") / "harness" / "skills_index.json"
DEFAULT_ROOTS = (Path.home() / "AppData/Local/hermes/profiles/nexus-harness/skills",
                 Path.home() / "AppData/Local/hermes/skills",
                 Path("C:/Proyectos/NexusProtocol/skills"))
MAX_SKILLS = 500


def skill_index(roots=None, cache_path=None, force=False):
    """`{skills, index_tokens, body_tokens}` del catalogo instalado. Cacheado por firma de ficheros.

    `index_tokens` es la vara justa: lo que un harness con skills cargadas en cada llamada manda como
    lista (nombre + descripcion). `body_tokens` (medido: ~444.887) se informa pero NO se reclama como
    ahorro: nadie inyecta 444k tokens de cuerpos en cada request, y contarlo seria inflar la cifra.
    """
    paths = [Path(item) for item in (roots or DEFAULT_ROOTS)]
    cache = Path(cache_path) if cache_path else CACHE_REL
    signature = "|".join("%s:%s" % (root, root.stat().st_mtime_ns if root.is_dir() else 0)
                         for root in paths)
    if not force:
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = {}
        if cached.get("signature") == signature and cached.get("skills") is not None:
            cached["cached"] = True
            return cached
    seen, index_chars, body_chars = set(), 0, 0
    for root in paths:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("SKILL.md"))[:MAX_SKILLS]:
            entry = skill_entry(path, root)
            if entry is None or entry["name"] in seen:
                continue
            seen.add(entry["name"])
            index_chars += len(entry["name"]) + len(entry["description"]) + 4
            try:
                body_chars += len(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    data = {"signature": signature, "skills": len(seen), "index_tokens": index_chars // 4,
            "body_tokens": body_chars // 4, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                        time.gmtime()),
            "cached": False}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    except OSError as exc:  # la cache es una comodidad: sin ella se recalcula, y se dice
        data["cache_error"] = "%s: %s" % (type(exc).__name__, exc)
    return data


@dataclass
class SavingsLedger:
    """Por turno o por run: cada request suma, y el ahorro sale de la resta, no de una estimacion."""

    index_tokens: int = 0
    skills_installed: int = 0
    requests: int = 0
    sent: int = 0
    baseline: int = 0
    dormant_tokens: int = 0
    pruned_tokens: int = 0
    isolated_tokens: int = 0
    repomap_tokens: int = 0
    unmeasured_requests: int = 0
    _pending_pruned_chars: int = 0
    per_request: list = field(default_factory=list)

    @classmethod
    def for_root(cls, cache_path=None, force=False):
        data = skill_index(cache_path=cache_path, force=force)
        return cls(index_tokens=int(data.get("index_tokens") or 0),
                   skills_installed=int(data.get("skills") or 0))

    # -- lo que entra en la cuenta -----------------------------------------------------------
    def observe_pruned(self, report):
        """Los bytes podados se cobran en la SIGUIENTE request: es cuando dejan de viajar."""
        chars = int(getattr(report, "bytes_saved", 0) or 0)
        if chars > 0:
            self._pending_pruned_chars += chars
        return chars

    def observe_isolation(self, tokens):
        """Tokens que la reparacion aislada produjo y que no entraron en la ventana principal."""
        value = int(tokens or 0)
        if value > 0:
            self.isolated_tokens += value
        return value

    def request(self, sent_tokens, injected_skill_tokens=0, repomap_tokens=0, measured=True):
        """Cierra una llamada al modelo con sus numeros. Devuelve la fila que se guardo."""
        sent = max(0, int(sent_tokens or 0))
        injected = max(0, int(injected_skill_tokens or 0))
        dormant = max(0, self.index_tokens - injected) if self.index_tokens else 0
        pruned = self._pending_pruned_chars // CHARS_PER_TOKEN
        map_cost = max(0, int(repomap_tokens or 0))
        self._pending_pruned_chars = 0
        row = {"sent": sent, "dormant": dormant, "pruned": pruned, "isolated": self.isolated_tokens,
               "repomap": map_cost, "measured": bool(measured)}
        self.isolated_tokens = 0
        base = max(0, sent - map_cost) + dormant + pruned + row["isolated"]
        row["baseline"] = base
        row["saved"] = max(0, base - sent)
        self.requests += 1
        self.sent += sent
        self.baseline += base
        self.dormant_tokens += dormant
        self.pruned_tokens += pruned
        self.isolated_tokens = 0
        self.repomap_tokens += map_cost
        if not measured:
            self.unmeasured_requests += 1
        self.per_request.append(row)
        self.per_request = self.per_request[-200:]
        return row

    # -- las cifras que la pantalla ensena ---------------------------------------------------
    @property
    def saved(self):
        return max(0, self.baseline - self.sent)

    @property
    def savings_pct(self):
        if not self.baseline:
            return None
        return round(100.0 * self.saved / float(self.baseline), 1)

    @property
    def context_multiplier(self):
        """Cuantas veces mas cabria en la misma ventana: `baseline / sent`."""
        if not self.sent:
            return None
        return round(self.baseline / float(self.sent), 2)

    def as_dict(self):
        return {"requests": self.requests, "sent": self.sent, "baseline": self.baseline,
                "saved": self.saved, "savings_pct": self.savings_pct,
                "context_multiplier": self.context_multiplier,
                "skills_installed": self.skills_installed, "index_tokens": self.index_tokens,
                "dormant_tokens": self.dormant_tokens, "pruned_tokens": self.pruned_tokens,
                "isolated_tokens": self.isolated_tokens, "repomap_tokens": self.repomap_tokens,
                "unmeasured_requests": self.unmeasured_requests}

    def note(self):
        """Una linea para el hilo y para la pildora: lo medido, sin adjetivos."""
        if not self.requests:
            return "sin requests medidas"
        return ("%d requests · enviados %s · baseline %s · ahorro %s%% · contexto x%s"
                % (self.requests, _fmt(self.sent), _fmt(self.baseline),
                   self.savings_pct if self.savings_pct is not None else "sin medir",
                   self.context_multiplier if self.context_multiplier is not None else "sin medir"))


def _fmt(value):
    try:
        return "{:,}".format(int(value)).replace(",", ".")
    except (TypeError, ValueError):
        return str(value)


def selftest():
    import tempfile

    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    ledger = SavingsLedger(index_tokens=3369, skills_installed=173)
    check("sin requests no hay porcentaje", ledger.savings_pct, None)
    ledger.observe_pruned(type("R", (), {"bytes_saved": 4000})())
    row = ledger.request(1000, injected_skill_tokens=363)
    check("la fila trae el baseline", row["baseline"], 1000 + 3006 + 1000)
    check("y el ahorro", row["saved"], 4006)
    check("el porcentaje sale del baseline", ledger.savings_pct, 80.0)
    check("el multiplicador de contexto", ledger.context_multiplier, 5.01)
    check("los tokens de skills dormidas se acumulan", ledger.dormant_tokens, 3006)
    check("los podados se cobran una sola vez", ledger.pruned_tokens, 1000)
    second = ledger.request(1000, injected_skill_tokens=3369)
    check("sin poda pendiente no se vuelve a cobrar", second["pruned"], 0)
    check("y sin skills dormidas el baseline baja", second["baseline"], 1000)
    check("dos requests", ledger.requests, 2)
    isolated = SavingsLedger(index_tokens=3369)
    isolated.observe_isolation(2500)
    row = isolated.request(500, injected_skill_tokens=0)
    check("el aislado entra en el baseline", row["isolated"], 2500)
    check("y se cobra una vez", isolated.request(500)["isolated"], 0)
    mapped = SavingsLedger(index_tokens=0)
    row = mapped.request(5000, repomap_tokens=800)
    check("el mapa AST es coste, no ahorro", row["baseline"], 4200)
    check("y no se puede reclamar como ahorro", row["saved"], 0)
    check("un request sin uso medido se declara",
          SavingsLedger(index_tokens=100).request(10, measured=False)["measured"], False)

    with tempfile.TemporaryDirectory(prefix="skills-index-") as workspace:
        from pathlib import Path
        root = Path(workspace) / "skills"
        for index in range(3):
            folder = root / ("sk%d" % index)
            folder.mkdir(parents=True)
            (folder / "SKILL.md").write_text("---\nname: sk%d\ndescription: %s\n---\n\ncuerpo\n"
                                             % (index, "descripcion larga " * 5), encoding="utf-8")
        cache = Path(workspace) / "cache.json"
        fresh = skill_index(roots=[root], cache_path=cache)
        check("cuenta las skills", fresh["skills"], 3)
        check("mide el indice", fresh["index_tokens"] > 0, True)
        again = skill_index(roots=[root], cache_path=cache)
        check("la segunda vez sale de cache", again["cached"], True)
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("savings: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
