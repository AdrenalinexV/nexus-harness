"""Ir a la definicion y a los usos: LSP si lo hay, y el mapa AST si no -- con su motivo.

La herramienta no elige: pregunta a LSP por una posicion, y si no hay servidor o no contesta, cae a
una busqueda por NOMBRE en el AST. El fallback se declara en la primera linea de la respuesta, porque un
resultado que no dice de donde viene es un resultado que miente -- y los usos por nombre no son
resolucion de simbolos: lo dice la propia respuesta.
"""
import ast
import re
import keyword
from pathlib import Path

from ...platform import lsp


def _identifier_at(path, line, character):
    """El identificador bajo una posicion 1-based. Una columna 0 no es un dato: se busca el primero.

    Sin columna util (0, fuera de la linea, o sobre un espacio) devuelve el primer identificador de la
    linea que no sea palabra reservada: `return build_prefix(...)` da `build_prefix`, no `return`.
    """
    try:
        rows = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        text = rows[max(0, int(line) - 1)]
    except (OSError, IndexError):
        return ""
    column = max(0, int(character) - 1)
    if column < len(text) and (text[column].isalnum() or text[column] == "_"):
        start, end = column, column
        while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
            start -= 1
        while end < len(text) and (text[end].isalnum() or text[end] == "_"):
            end += 1
        return text[start:end]
    for match in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", text):
        if not keyword.iskeyword(match.group(0)):
            return match.group(0)
    return ""


def _render(rows):
    """`fichero:linea` y, cuando hay columna, `:columna`. El AST no da columna y no se inventa."""
    out = []
    for row in rows:
        path = row.get("path") or "?"
        line = int(row.get("line") or 0)
        column = int(row.get("character") or 0)
        out.append("%s:%d:%d" % (path, line, column) if column else "%s:%d" % (path, line))
    return "\n".join(out) or "(sin resultado)"


def ast_references(root, name, limit=400):
    """Usos del NOMBRE en el AST del proyecto. No es resolucion de simbolos: se dice en la respuesta."""
    needle = str(name or "").strip()
    if not needle:
        return [], "sin simbolo que buscar"
    base = Path(root)
    found, seen = [], 0
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
        for node in ast.walk(tree):
            name_of = node.id if isinstance(node, ast.Name) else (
                node.attr if isinstance(node, ast.Attribute) else "")
            if name_of == needle:
                found.append({"path": path.relative_to(base).as_posix(),
                              "line": int(getattr(node, "lineno", 0) or 0), "character": 0})
    return found, "" if found else "no se encontro %r en el AST" % needle


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


def references(root, args, config):
    """`references`: todos los usos de un símbolo. LSP primero; si no hay servidor, usos por nombre en el AST.

    La respuesta declara de dónde viene. Sin servidor, "usos por nombre" NO es resolución de símbolos: un
    `x` de otro módulo con el mismo nombre aparece también, y decirlo es parte del resultado.
    """
    symbol = str(args.get("symbol") or "").strip()
    path = str(args.get("path") or "").strip()
    line = int(args.get("line") or 0)
    character = int(args.get("character") or 0)
    reasons = []
    if path and line:
        found, reason = lsp.references(root, path, line, character)
        if found:
            return _render(found), {"files": [], "source": "lsp", "count": len(found)}
        reasons.append(reason or "el servidor no dio usos en esa posicion")
        if not symbol:
            symbol = _identifier_at(path, line, character)
    if symbol:
        found, reason = ast_references(root, symbol)
        if found:
            note = "; ".join(item for item in reasons if item)
            header = "[mapa AST, no LSP: %s]\n" % note if note else "[mapa AST]\n"
            return header + _render(found), {"files": [], "source": "ast", "count": len(found)}
        reasons.append(reason or "sin coincidencias")
    raise ValueError("no references: %s" % ("; ".join(item for item in reasons if item)
                                            or "hacen falta symbol o path+line"))


HANDLERS = {"definition": definition, "references": references}

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
