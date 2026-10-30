"""El servidor de lenguaje, cuando existe: errores al instante tras un patch, y `definition`.

La idea viene de donde el operador la vio (`agent/lsp/edit_check.py` y `sync_diagnostics.py` de Hermes):
el veredicto se pregunta DESPUES de escribir y con presupuesto corto -- un servidor lento no retiene la
escritura, solo no da veredicto. Aqui es sincrono y sin dependencias: un hilo lector y una cola, JSON-RPC
2.0 con `Content-Length`, que es lo unico que el protocolo exige.

Sin servidor instalado se dice (`server_for` devuelve None con su motivo) y se cae al mapa AST de
`repo_map`: un arnes que finge diagnosticos es peor que uno que no los tiene.
"""
import atexit
import json
import os
import queue
import shutil
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path

# `(extensiones, argv, languageId)`. Solo servidores que hablan LSP por stdio y existen de verdad.
SERVERS = (
    ((".py", ".pyi"), (("pyright-langserver", "--stdio"), ("basedpyright-langserver", "--stdio"),
                       ("pylsp",)), "python"),
    ((".ts", ".tsx", ".js", ".jsx"), (("typescript-language-server", "--stdio"),), "typescript"),
    ((".go",), (("gopls",),), "go"),
    ((".rs",), (("rust-analyzer",),), "rust"),
    ((".c", ".h", ".cc", ".cpp", ".hpp"), (("clangd",),), "cpp"),
)
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
DEFAULT_TIMEOUT = 1.2
CLIENTS = {}


class LspError(RuntimeError):
    """Un servidor que contesta algo que no es lo que pedimos."""


def server_for(path, which=None):
    """`(argv, language_id)` para este fichero, o `(None, motivo)`. Se mira el PATH, no se supone."""
    suffix = Path(str(path)).suffix.lower()
    which = which or shutil.which
    for extensions, candidates, language in SERVERS:
        if suffix not in extensions:
            continue
        for argv in candidates:
            found = which(argv[0])
            if found:
                return (argv[0],) + tuple(argv[1:]), language
        return None, "no hay servidor LSP para %s (probado: %s)" % (
            suffix, ", ".join(candidate[0] for candidate in candidates))
    return None, "extension %r sin servidor LSP configurado" % (suffix or "?")


def _frame(payload):
    body = json.dumps(payload).encode("utf-8")
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


def _path_of(uri):
    text = str(uri or "")
    if text.startswith("file://"):
        text = urllib.parse.unquote(urllib.parse.urlsplit(text).path)
        if os.name == "nt" and text.startswith("/") and len(text) > 2 and text[2] == ":":
            text = text[1:]
    return text


class Client:
    """Un proceso LSP y la conversacion con el. Sincrono: una peticion, una espera con tope."""

    def __init__(self, root, argv, language_id, timeout=20.0):
        self.root = str(Path(root))
        self.argv = list(argv)
        self.language_id = language_id
        self.timeout = float(timeout)
        self._queue = queue.Queue()
        self._diagnostics = {}
        self._versions = {}
        self._opened = set()
        self._next_id = 0
        self._process = subprocess.Popen(self.argv, cwd=self.root, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         bufsize=0, creationflags=CREATE_NO_WINDOW)
        self._reader = threading.Thread(target=self._read, args=(self._process.stdout,),
                                        daemon=True, name="lsp-reader")
        self._reader.start()
        self._initialize()

    # -- protocolo ---------------------------------------------------------------------------
    def _read(self, stream):
        while True:
            headers = {}
            while True:
                line = stream.readline()
                if not line:
                    self._queue.put(None)
                    return
                text = line.decode("ascii", errors="replace").strip()
                if not text:
                    break
                key, _, value = text.partition(":")
                headers[key.strip().lower()] = value.strip()
            try:
                size = int(headers.get("content-length") or 0)
                body = stream.read(size) if size else b""
                self._queue.put(json.loads(body.decode("utf-8", errors="replace")))
            except (ValueError, OSError):
                self._queue.put(None)
                return

    def _send(self, payload):
        if self._process.stdin is None or self._process.poll() is not None:
            raise LspError("el servidor LSP ya no corre")
        self._process.stdin.write(_frame(payload))
        self._process.stdin.flush()

    def _request(self, method, params, timeout=None):
        self._next_id += 1
        want = self._next_id
        self._send({"jsonrpc": "2.0", "id": want, "method": method, "params": params})
        return self._wait(want, timeout or self.timeout)

    def _notify(self, method, params):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _wait(self, want, timeout):
        deadline = time.time() + float(timeout)
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError("sin respuesta a la peticion %d en %.1fs" % (want, timeout))
            try:
                message = self._queue.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError("sin respuesta a la peticion %d en %.1fs" % (want, timeout)) from None
            if message is None:
                raise LspError("el servidor LSP cerro la conexion")
            if message.get("method") == "textDocument/publishDiagnostics":
                params = message.get("params") or {}
                self._diagnostics[str(params.get("uri") or "")] = list(params.get("diagnostics") or [])
                continue
            if message.get("id") == want:
                if message.get("error"):
                    raise LspError(str(message["error"]))
                return message.get("result")

    def _initialize(self):
        root_uri = Path(self.root).resolve().as_uri()
        self._request("initialize", {
            "processId": os.getpid(), "rootUri": root_uri,
            "capabilities": {"textDocument": {"publishDiagnostics": {}, "definition": {}}},
            "workspaceFolders": [{"uri": root_uri, "name": os.path.basename(self.root)}],
        })
        self._notify("initialized", {})

    # -- documentos --------------------------------------------------------------------------
    def open(self, path, text=None):
        """Abre o re-sincroniza el documento. Version monotona: un didChange viejo no pisa uno nuevo."""
        path = str(Path(path))
        uri = Path(path).resolve().as_uri()
        body = text if text is not None else Path(path).read_text(encoding="utf-8", errors="replace")
        if uri not in self._opened:
            self._opened.add(uri)
            self._versions[uri] = 1
            self._notify("textDocument/didOpen", {"textDocument": {
                "uri": uri, "languageId": self.language_id, "version": 1, "text": body}})
        else:
            self._versions[uri] += 1
            self._notify("textDocument/didChange", {
                "textDocument": {"uri": uri, "version": self._versions[uri]},
                "contentChanges": [{"text": body}]})
        return uri

    def diagnostics(self, path, text=None, timeout=DEFAULT_TIMEOUT):
        """Los diagnosticos del fichero tras sincronizarlo. `None` = no hubo veredicto en el tope."""
        uri = self.open(path, text)
        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            if uri in self._diagnostics:
                return self._diagnostics[uri]
            try:
                message = self._queue.get(timeout=max(0.01, deadline - time.time()))
            except queue.Empty:
                break
            if message is None:
                raise LspError("el servidor LSP cerro la conexion")
            if message.get("method") == "textDocument/publishDiagnostics":
                params = message.get("params") or {}
                self._diagnostics[str(params.get("uri") or "")] = list(params.get("diagnostics") or [])
        return self._diagnostics.get(uri)

    def definition(self, path, line, character, text=None, timeout=8.0):
        """Definiciones en `(path, linea 1-based, caracter 1-based)`."""
        uri = self.open(path, text)
        result = self._request("textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": {"line": max(0, int(line) - 1), "character": max(0, int(character) - 1)}},
            timeout=timeout)
        return _locations(result)

    def references(self, path, line, character, text=None, timeout=8.0):
        """Dónde se usa el símbolo de esa posición (incluida su declaración)."""
        uri = self.open(path, text)
        result = self._request("textDocument/references", {
            "textDocument": {"uri": uri},
            "position": {"line": max(0, int(line) - 1), "character": max(0, int(character) - 1)},
            "context": {"includeDeclaration": True}}, timeout=timeout)
        return _locations(result)

    def close(self):
        """Cierra el servidor. Devuelve los fallos: un cierre que se traga un error no es un cierre."""
        errors = []
        try:
            if self._process.poll() is None:
                self._request("shutdown", None, timeout=1.0)
                self._notify("exit", None)
        except (LspError, TimeoutError, OSError) as exc:
            errors.append("%s: %s" % (type(exc).__name__, exc))
        finally:
            try:
                self._process.terminate()
            except OSError as exc:
                errors.append("terminate: %s" % exc)
        return errors


def _locations(result):
    rows = result if isinstance(result, list) else ([result] if result else [])
    out = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        uri = item.get("targetUri") or item.get("uri")
        span = item.get("targetSelectionRange") or item.get("targetRange") or item.get("range") or {}
        start = span.get("start") or {}
        out.append({"path": _path_of(uri), "line": int(start.get("line", 0)) + 1,
                    "character": int(start.get("character", 0)) + 1})
    return out


def client_for(root, path, timeout=20.0):
    """Cliente cacheado por (raiz, servidor). Devuelve `(client, reason)`; `client` None si no hay."""
    argv, language = server_for(path)
    if not argv:
        return None, language
    key = (str(Path(root)), argv[0])
    client = CLIENTS.get(key)
    if client is not None and client._process.poll() is None:
        return client, ""
    try:
        client = Client(root, argv, language, timeout=timeout)
    except (OSError, LspError, TimeoutError) as exc:
        return None, "no se pudo arrancar %s: %s: %s" % (argv[0], type(exc).__name__, exc)
    CLIENTS[key] = client
    return client, ""


def diagnose(root, path, timeout=DEFAULT_TIMEOUT):
    """`(diagnosticos, motivo)`. `diagnosticos` None = sin veredicto (lento o sin servidor)."""
    client, reason = client_for(root, path)
    if client is None:
        return None, reason
    try:
        return client.diagnostics(path, timeout=timeout), ""
    except (LspError, TimeoutError, OSError) as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)


def references(root, path, line, character, timeout=8.0):
    """`(usos, motivo)`. Sin servidor, el llamante cae a la busqueda por nombre en el AST."""
    client, reason = client_for(root, path)
    if client is None:
        return [], reason
    try:
        return client.references(path, line, character, timeout=timeout), ""
    except (LspError, TimeoutError, OSError) as exc:
        return [], "%s: %s" % (type(exc).__name__, exc)


def resolve(root, path, line, character, timeout=8.0):
    """`(definiciones, motivo)`. Sin servidor, el llamante cae al mapa AST y lo dice."""
    client, reason = client_for(root, path)
    if client is None:
        return [], reason
    try:
        return client.definition(path, line, character, timeout=timeout), ""
    except (LspError, TimeoutError, OSError) as exc:
        return [], "%s: %s" % (type(exc).__name__, exc)


def close_all():
    """Cierra los servidores al salir: un proceso LSP huerfano sobrevive a la ventana."""
    for key, client in list(CLIENTS.items()):
        try:
            client.close()
        finally:
            CLIENTS.pop(key, None)


atexit.register(close_all)
