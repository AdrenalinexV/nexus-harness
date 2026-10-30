"""Ir a la definicion: el servidor de lenguaje si lo hay, y el mapa AST si no -- con su motivo.

La herramienta no elige: pregunta a LSP por una posicion (`path` + `line` + `character`), y si no hay
servidor o no contesta, cae a `repo_map` buscando el simbolo por nombre. El fallback se declara en la
primera linea de la respuesta; un resultado que no dice de donde viene es un resultado que miente.
"""
import ast
from pathlib import Path

from ...platform import lsp


def _identifier_at(path, line, character):
    """El identificador bajo una posicion 1-based. Es lo que convierte una posicion en un simbolo."""
    try:
        rows = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        text = rows[max(0, int(line) - 1)]
    except (OSError, IndexError):
        return ""
    column = min(max(0, int(character) - 1), max(0, len(text) - 1))
    start, end = column, column
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
        start -= 1
    while end < len(text) and (text[end].isalnum() or text[end] == "_"):
        end += 1
    return text[start:end]


def _render(rows):
    """`fichero:linea` y, cuando hay columna, `:columna`. El AST no da columna y no se inventa."""
    out = []
    for row in rows:
        path = row.get("path") or "?"
        line = int(row.get("line") or 0)
        column = int(row.get("character") or 0)
        out.append("%s:%d:%d" % (path, line, column) if column else "%s:%d" % (path, line))
    return "\n".join(out) or "(sin resultado)"


def definition(root, args, config):
    """`definition`. Acepta `path`+`line`(+`character`) o `symbol`; con los dos, LSP primero."""
    symbol = str(args.get("symbol") or "").strip()
    path = str(args.get("path") or "").strip()
    line = int(args.get("line") or 0)
    character = int(args.get("character") or 0)
    reasons = []
    if path and line:
        found, reason = lsp.resolve(root, path, line, character)
        if found:
            return _render(found), {"files": [], "source": "lsp", "count": len(found)}
        reasons.append(reason or "el servidor no dio definicion en esa posicion")
        if not symbol:
            # Sin LSP, una posicion todavia sirve: se lee el identificador de ahi y se busca en el AST.
            symbol = _identifier_at(path, line, character)
    if symbol:
        found, reason = ast_definition(root, symbol)
        if found:
            note = "; ".join(item for item in reasons if item)
            header = "[mapa AST, no LSP: %s]\n" % note if note else "[mapa AST]\n"
            return header + _render(found), {"files": [], "source": "ast", "count": len(found)}
        reasons.append(reason or "sin coincidencias")
    raise ValueError("no definition: %s" % ("; ".join(item for item in reasons if item)
                                            or "hacen falta symbol o path+line"))


HANDLERS = {"definition": definition}

SKIP = {".git", "node_modules", ".nexus", "__pycache__", ".venv", ".build", "dist", "build",
        "target", "engine", "site-packages", ".mypy_cache", ".pytest_cache"}


def ast_definition(root, name, limit=400):
    """El plan B: buscar `def`/`class` con el AST, acotado. Se declara fallback, nunca LSP.

    No usa `context.repo_map` porque `tools` esta a la IZQUIERDA de `context` y una capa no mira a su
    derecha; el escaneo es el mismo AST, con su propio tope, y el motivo de la degradacion viaja en la
    primera linea de la respuesta.
    """
    needle = str(name or "").strip()
    if not needle:
        return [], "sin simbolo que buscar"
    base = Path(root)
    seen = 0
    for path in sorted(base.rglob("*.py")):
        if set(path.relative_to(base).parts[:-1]) & SKIP:
            continue
        seen += 1
        if seen > limit:
            break
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                    and node.name == needle:
                return [{"path": path.relative_to(base).as_posix(), "line": node.lineno,
                         "character": 0}], ""
    return [], "no se encontro %r en el mapa AST" % needle
