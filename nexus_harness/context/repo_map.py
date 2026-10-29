"""Mapa AST del repositorio: 1.500 tokens que valen por veinte `list_dir` a ciegas.

El Director gasta turnos enteros averiguando donde vive cada cosa. Un mapa simbolico le da de una vez
lo que el AST ya sabe: ficheros, clases con sus bases, funciones con su firma y linea, e imports. No
es un resumen con modelo (que puede inventar un nombre que no existe): sale de `ast.parse`, y si un
fichero no parsea se dice con su error en vez de omitirse en silencio.

**Cache por `mtime`.** Recalcular 100 ficheros en cada turno es tirar el turno. La firma de la cache es
`(ruta, mtime_ns, tamano)` de cada fichero: si nada cambio, se sirve el mapa guardado; si cambio un
solo fichero, se reconstruye (barato: el AST de un repositorio de este tamano tarda milisegundos).
El fichero de cache vive en `.nexus/harness/repo_map.json`.
"""
import ast
import json
import os
from pathlib import Path

CACHE_REL = Path(".nexus") / "harness" / "repo_map.json"
CHARS_PER_TOKEN = 4
MAX_TOKENS = 1500
MAX_FILES = 400
SKIP = {".git", ".nexus", "node_modules", "__pycache__", "dist", "build", ".venv", "venv",
        "archive"}


def _line(node):
    return int(getattr(node, "lineno", 0) or 0)


def _args(node):
    """Firma corta: nombres de argumentos, sin valores por defecto ni anotaciones (ruido)."""
    arguments = getattr(node, "args", None)
    if arguments is None:
        return "()"
    names = [arg.arg for arg in list(getattr(arguments, "posonlyargs", []))
             + list(arguments.args or [])]
    if arguments.vararg:
        names.append("*" + arguments.vararg.arg)
    if arguments.kwarg:
        names.append("**" + arguments.kwarg.arg)
    return "(%s)" % ", ".join(names[:6])


def file_symbols(path):
    """`(doc, imports, symbols, error)` de un `.py`. Un fichero ilegible es un error, no un vacio."""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "", [], [], "%s: %s" % (type(exc).__name__, exc)
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return "", [], [], "SyntaxError linea %s: %s" % (exc.lineno, exc.msg)
    doc = (ast.get_docstring(tree) or "").strip().splitlines()
    imports, symbols = [], []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", None) or ""
            names = [alias.name for alias in node.names][:3]
            imports.append(module or ",".join(names))
        elif isinstance(node, ast.ClassDef):
            bases = [getattr(base, "id", getattr(base, "attr", "?")) for base in node.bases][:3]
            symbols.append({"kind": "class", "name": node.name, "line": _line(node),
                            "bases": bases})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append({"kind": "def", "name": node.name, "line": _line(node),
                            "args": _args(node)})
    return (doc[0][:120] if doc else ""), sorted(set(imports))[:12], symbols, ""


def scan(root, limit=MAX_FILES):
    """Todas las filas del mapa, en orden estable de ruta."""
    base = Path(root)
    rows = []
    if not base.is_dir():
        return rows
    for path in sorted(base.rglob("*.py")):
        parts = set(path.relative_to(base).parts[:-1])
        if parts & SKIP or path.name == "setup.py":
            continue
        relative = path.relative_to(base).as_posix()
        try:
            stat = path.stat()
        except OSError:
            continue
        doc, imports, symbols, error = file_symbols(path)
        rows.append({"path": relative, "mtime_ns": int(stat.st_mtime_ns), "size": int(stat.st_size),
                     "doc": doc, "imports": imports, "symbols": symbols, "error": error})
        if len(rows) >= limit:
            break
    return rows


def signature(rows):
    """La firma de la cache: cambia en cuanto cambia un fichero, y solo entonces."""
    import hashlib
    text = "\n".join("%s|%s|%s" % (row["path"], row["mtime_ns"], row["size"]) for row in rows)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render(rows, max_tokens=MAX_TOKENS):
    """El mapa en texto compacto. Si no cabe, se corta por fichero y se dice cuanto quedo fuera."""
    budget = int(max_tokens) * CHARS_PER_TOKEN
    lines, used, omitted = [], 0, 0
    for row in rows:
        head = row["path"]
        if row["error"]:
            line = "%s: ERROR %s" % (head, row["error"][:80])
        else:
            items = []
            for symbol in row["symbols"][:12]:
                if symbol["kind"] == "class":
                    extra = ("(%s)" % ", ".join(symbol["bases"])) if symbol["bases"] else ""
                    items.append("L%d class %s%s" % (symbol["line"], symbol["name"], extra))
                else:
                    items.append("L%d def %s%s" % (symbol["line"], symbol["name"],
                                                   symbol.get("args") or "()"))
            tail = (" | " + ", ".join(items)) if items else ""
            imports = (" imports: %s" % ", ".join(row["imports"][:6])) if row["imports"] else ""
            line = "%s%s%s" % (head, imports, tail)
        if used + len(line) + 1 > budget:
            omitted += 1
            continue
        lines.append(line)
        used += len(line) + 1
    if omitted:
        lines.append("... %d ficheros omitidos por presupuesto (lee su fichero si los necesitas)"
                     % omitted)
    return "\n".join(lines)


class RepoMap:
    """Construye, cachea y sirve el mapa. `build()` devuelve `{text, tokens, cached, files}`."""

    def __init__(self, root, max_tokens=MAX_TOKENS, cache_path=None):
        self.root = Path(root)
        self.max_tokens = int(max_tokens)
        self.cache_path = Path(cache_path) if cache_path else self.root / CACHE_REL
        self.last = {}

    def build(self, force=False):
        rows = scan(self.root)
        stamp = signature(rows)
        cached = {}
        if not force:
            try:
                cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cached = {}
        if cached.get("signature") == stamp and cached.get("text"):
            text = str(cached["text"])
            self.last = {"text": text, "tokens": len(text) // CHARS_PER_TOKEN,
                         "cached": True, "files": len(rows), "signature": stamp,
                         "errors": int(cached.get("errors", 0))}
            return self.last
        text = render(rows, self.max_tokens)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"signature": stamp, "text": text, "files": len(rows),
                   "errors": sum(1 for row in rows if row["error"]), "rows": 0}
        temporary = self.cache_path.with_name(".repo_map.json.tmp")
        temporary.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
        temporary.replace(self.cache_path)
        self.last = {"text": text, "tokens": len(text) // CHARS_PER_TOKEN, "cached": False,
                     "files": len(rows), "signature": stamp, "errors": payload["errors"]}
        return self.last

    def brief(self):
        """Lo que se inyecta en el prompt del Director: el mapa, nunca vacio por un fallo de cache."""
        result = self.build()
        return result["text"]


def selftest():
    import tempfile

    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    with tempfile.TemporaryDirectory(prefix="repo-map-") as workspace:
        root = Path(workspace)
        (root / "pkg").mkdir()
        (root / "pkg" / "core.py").write_text(
            '"""Nucleo del paquete."""\nimport json\n\n\nclass Store(dict):\n'
            '    def save(self, path):\n        return path\n\n\n'
            'def build(a, b=1, *rest, **opts):\n    return a\n', encoding="utf-8")
        (root / "pkg" / "broken.py").write_text("def oops(:\n", encoding="utf-8")
        (root / "tools").mkdir()
        (root / "tools" / "run.py").write_text("import pkg.core\n\ndef main():\n    pass\n",
                                               encoding="utf-8")
        mapper = RepoMap(root)
        first = mapper.build()
        check("el mapa no esta cacheado la primera vez", first["cached"], False)
        check("ve los tres ficheros", first["files"], 3)
        check("la clase aparece con su base", "class Store(dict)" in first["text"], True)
        check("la firma de la funcion aparece", "def build(a, b, *rest, **opts)" in first["text"],
              True)
        check("los imports aparecen", "imports: json" in first["text"], True)
        check("un fichero roto se declara, no se omite", "ERROR SyntaxError" in first["text"], True)
        check("la doc se queda fuera del cuerpo pero el mapa existe", "Nucleo" not in first["text"],
              True)
        second = mapper.build()
        check("la segunda vez sale de cache", second["cached"], True)
        check("y el texto es identico", second["text"], first["text"])
        before = (root / "pkg" / "core.py").stat().st_mtime_ns
        (root / "pkg" / "core.py").write_text(
            "def only(a):\n    return a\n", encoding="utf-8")
        os.utime(root / "pkg" / "core.py", ns=(before + 10_000_000, before + 10_000_000))
        third = mapper.build()
        check("tocar un fichero invalida la cache", third["cached"], False)
        check("y el mapa refleja lo nuevo", "def only(a)" in third["text"], True)
        check("lo viejo desaparece", "class Store" in third["text"], False)
        capped = RepoMap(root, max_tokens=20).build(force=True)
        check("bajo presupuesto no entran los tres ficheros", capped["text"].count("\n") < 3, True)
        check("y dice cuanto omitio", "omitidos" in capped["text"], True)
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("repo_map: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
