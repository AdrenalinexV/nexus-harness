"""LSP: el protocolo con un servidor de verdad (falso), el fallback con su motivo, y la nota tras editar.

No hay pyright/pylsp en esta maquina, asi que el servidor que se arranca aqui es un proceso Python que
habla JSON-RPC por stdio igual que uno real: `initialize`, `didOpen` -> `publishDiagnostics`,
`textDocument/definition`, `shutdown`. Eso mide el protocolo, el framing y los plazos; no mide lo que
diria pyright, y por eso no se afirma.
"""
import sys
from pathlib import Path

from .fakes import TempProject
from ..platform import lsp
from ..tools.toolbox import lsp_tools

FAKE = r'''
import json, pathlib, sys
root, target = sys.argv[1], sys.argv[2]
def read():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        text = line.decode().strip()
        if not text:
            break
        key, _, value = text.partition(":")
        headers[key.strip().lower()] = value.strip()
    return json.loads(sys.stdin.buffer.read(int(headers["content-length"])))
def send(obj):
    body = json.dumps(obj).encode()
    sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n%s" % (len(body), body))
    sys.stdout.buffer.flush()
while True:
    message = read()
    if message is None:
        break
    method, mid = message.get("method"), message.get("id")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": mid, "result": {"capabilities": {"textDocumentSync": 1}}})
    elif method in ("textDocument/didOpen", "textDocument/didChange"):
        uri = (message["params"].get("textDocument") or {}).get("uri")
        send({"jsonrpc": "2.0", "method": "textDocument/publishDiagnostics",
              "params": {"uri": uri, "diagnostics": [
                  {"range": {"start": {"line": 1, "character": 4},
                             "end": {"line": 1, "character": 8}},
                   "severity": 1, "message": "undefined name 'x'", "source": "fake"}]}})
    elif method == "textDocument/definition":
        send({"jsonrpc": "2.0", "id": mid, "result": [
            {"uri": pathlib.Path(target).as_uri(),
             "range": {"start": {"line": 2, "character": 4}, "end": {"line": 2, "character": 9}}}]})
    elif method == "shutdown":
        send({"jsonrpc": "2.0", "id": mid, "result": None})
    elif method == "exit":
        break
'''


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def test_the_protocol_with_a_fake_server(failures):
    with TempProject({"a.py": "def target():\n    return 1\n\nx = 1\n"}) as root:
        fake = Path(root) / "fake_lsp.py"
        fake.write_text(FAKE, encoding="utf-8")
        target = str((Path(root) / "a.py").resolve())
        client = lsp.Client(root, [sys.executable, str(fake), str(root), target], "python")
        try:
            diags = client.diagnostics(str(Path(root) / "a.py"), timeout=5)
            check("el diagnostico llega por publishDiagnostics",
                  (diags or [{}])[0].get("message"), "undefined name 'x'", failures)
            check("con su rango (0-based, como el protocolo)",
                  ((diags or [{}])[0].get("range") or {}).get("start", {}).get("line"), 1, failures)
            found = client.definition(str(Path(root) / "a.py"), 4, 1, timeout=5)
            check("definition devuelve fichero y linea 1-based",
                  (Path(found[0]["path"]).name, found[0]["line"]) if found else None,
                  ("a.py", 3), failures)
        finally:
            client.close()


def test_without_a_server_it_says_why(failures):
    argv, reason = lsp.server_for("x.py", which=lambda name: None)
    check("sin servidor instalado no hay argv", argv, None, failures)
    check("y el motivo nombra los que se probaron", "pyright-langserver" in reason, True, failures)
    check("una extension desconocida tambien se explica",
          lsp.server_for("x.zzz", which=lambda name: None)[0], None, failures)
    found, reason = lsp_tools.ast_definition(".", "no_existe_jamas_123")
    check("el mapa AST no inventa: sin coincidencia, vacio", found, [], failures)
    check("y lo dice", bool(reason), True, failures)


def test_the_ast_fallback_finds_a_definition(failures):
    with TempProject({"m.py": "import os\n\ndef build_prefix():\n    return ''\n"}) as root:
        found, reason = lsp_tools.ast_definition(root, "build_prefix")
        check("el fallback encuentra el simbolo", found,
              [{"path": "m.py", "line": 3, "character": 0}], failures)
        check("sin motivo porque encontro", reason, "", failures)


def test_locations_normalize_both_shapes(failures):
    plain = lsp._locations({"uri": "file:///tmp/a.py", "range": {"start": {"line": 9, "character": 2}}})
    check("Location suelto", (plain[0]["line"], plain[0]["character"]), (10, 3), failures)
    link = lsp._locations([{"targetUri": "file:///tmp/b.py",
                            "targetSelectionRange": {"start": {"line": 0, "character": 0}}}])
    check("LocationLink usa targetSelectionRange", link[0]["path"].endswith("b.py"), True, failures)
    check("una respuesta vacia no revienta", lsp._locations(None), [], failures)


def test_a_write_leaves_the_verdict_in_the_observation(failures):
    """El gancho del registro: tras escribir, los problemas del servidor van en el texto que lee el modelo."""
    from ..tools import Registry

    with TempProject() as root:
        registry = Registry(root)
        original = lsp.diagnose

        def fake_diagnose(_root, _path, timeout=None):
            return ([{"range": {"start": {"line": 2, "character": 4}},
                      "message": "undefined name 'x'"}], "")

        lsp.diagnose = fake_diagnose
        try:
            result = registry.call("write_file", {"path": "calc.py", "content": "x = 1\n"})
        finally:
            lsp.diagnose = original
        check("la escritura pasa", result.ok, True, failures)
        check("y la nota del servidor va en el texto", "[lsp] 1 problema(s)" in result.text, True,
              failures)
        check("con su linea", (result.meta.get("lsp") or [{}])[0].get("line"), 3, failures)


def run():
    failures = []
    test_the_protocol_with_a_fake_server(failures)
    test_without_a_server_it_says_why(failures)
    test_the_ast_fallback_finds_a_definition(failures)
    test_locations_normalize_both_shapes(failures)
    test_a_write_leaves_the_verdict_in_the_observation(failures)
    return failures
