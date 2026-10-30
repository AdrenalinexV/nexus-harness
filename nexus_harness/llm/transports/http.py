"""JSON over `urllib`, and a failure that says what happened.

Every transport needs the same four things: a UA header some gateways require, a timeout, a retry on
the two statuses that mean "not now" (429, 5xx), and an error that carries the status and the body so
the caller can print something a human can act on.

Dos clientes, y el motivo de que sean dos:

* `post_json` / `get_json` -- `urllib.request`, que respeta proxies por variable de entorno.
* `stream_lines` -- `http.client`, porque hay que sujetar el socket para poder cerrarlo cuando el
  operador pulsa Detener. Un `urllib` no expone el socket, y una bandera no despierta un `readline()`
  bloqueado. Contrapartida declarada: **el stream no usa el proxy de las variables de entorno**; va
  directo al endpoint del modelo.
"""
import codecs
import contextlib
import http.client
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from ...core import streaming

USER_AGENT = "NexusHarness/0.1 (+local)"
RETRY_STATUS = (429, 500, 502, 503, 504)


class TransportError(RuntimeError):
    """A call that did not produce JSON, with the evidence that says why."""

    def __init__(self, message, status=None, body=""):
        super().__init__(message)
        self.status = status
        self.body = body

    @property
    def retryable(self):
        return self.status in RETRY_STATUS


def _request(url, payload=None, headers=None, timeout=120, method=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
    request.add_header("User-Agent", USER_AGENT)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1500]
        raise TransportError("%s -> HTTP %s: %s" % (url, exc.code, body[:400]),
                             status=exc.code, body=body) from exc
    except urllib.error.URLError as exc:
        raise TransportError("%s unreachable: %s" % (url, exc.reason)) from exc
    except TimeoutError as exc:
        raise TransportError("%s timed out after %ss" % (url, timeout)) from exc
    try:
        return json.loads(raw) if raw.strip() else {}
    except ValueError as exc:
        raise TransportError("%s returned non-JSON: %r" % (url, raw[:200])) from exc


def post_json(url, payload, headers=None, timeout=120, retries=1):
    """POST JSON, retrying once on the statuses that mean the server is busy, not wrong."""
    attempt = 0
    while True:
        try:
            return _request(url, payload, headers, timeout)
        except TransportError as exc:
            if not exc.retryable or attempt >= retries:
                raise
            attempt += 1
            time.sleep(min(2 ** attempt, 8))


class Live:
    """Una conexion HTTP abierta. `close()` corta el socket de verdad, no marca una bandera.

    Un `stream` que se queda colgado tiene el hilo bloqueado dentro de `readline()`: la unica forma de
    despertarlo es tocar el socket desde fuera. Esto es lo que `core.streaming.close_all()` cierra.

    El socket se guarda al abrir, no se lee de `conn` al cerrar: con `Connection: close` (que es como
    responden los motores locales en streaming) `getresponse()` pone `conn.sock = None` y el socket se
    muda al objeto respuesta. Un `close()` que pregunte a `conn` despues no encuentra nada que cortar y
    el lector se queda colgado para siempre -- medido, no supuesto.
    """

    def __init__(self, conn, sock):
        self.conn = conn
        self.sock = sock
        self.closed = False

    def close(self):
        """Shutdown + close. Un socket ya muerto es el estado que buscabamos, no un fallo."""
        self.closed = True
        if self.sock is not None:
            with contextlib.suppress(OSError, ValueError):
                self.sock.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError, ValueError):
                self.sock.close()
        with contextlib.suppress(Exception):
            self.conn.close()


def _connect(url, timeout):
    """`(conn, path)` desde una URL. HTTPS cuando el esquema lo pide; nada mas se adivina."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or "127.0.0.1"
    port = parts.port or (443 if parts.scheme == "https" else 80)
    path = parts.path or "/"
    if parts.query:
        path = "%s?%s" % (path, parts.query)
    factory = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    return factory(host, port, timeout=timeout), path


def stream_lines(url, payload=None, headers=None, timeout=240, method=None):
    """POST JSON y entrega las lineas segun llegan. El socket queda registrado para poder cortarlo.

    Un generador, no una lista: la primera linea tiene que salir antes de que el modelo termine. El
    `finally` desregistra y cierra; si `close_all()` corto el socket mientras estaba bloqueado en
    `readline()`, el bucle termina sin mentir con un `TransportError` que nadie pidio.
    """
    conn, path = _connect(url, timeout)
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"User-Agent": USER_AGENT, "Accept": "text/event-stream"}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request_headers.update(headers or {})
    live = None
    try:
        try:
            conn.request(method or ("POST" if body else "GET"), path, body=body,
                         headers=request_headers)
            # El socket se captura ANTES de `getresponse()`: una respuesta close-delimited se lo lleva y
            # deja `conn.sock` en None. Sin esta referencia no hay nada que cortar cuando el lector esta
            # bloqueado dentro de `readline()`.
            live = streaming.register(Live(conn, getattr(conn, "sock", None)))
            response = conn.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            raise TransportError("%s unreachable: %s" % (url, exc)) from exc
        if response.status >= 400:
            text = response.read().decode("utf-8", errors="replace")[:1500]
            raise TransportError("%s -> HTTP %s: %s" % (url, response.status, text[:400]),
                                 status=response.status, body=text)
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while True:
            try:
                line = response.readline()
            except (OSError, ValueError, http.client.HTTPException) as exc:
                # ValueError entra aqui por 3.13: leer de un file object ya cerrado por Detener lanza
                # "I/O operation on closed file" en vez de un OSError del socket. Es la salida esperada.
                if live.closed:
                    return
                raise TransportError("%s se corto a mitad: %s" % (url, exc)) from exc
            if not line:
                break
            text = decoder.decode(line)
            if text:
                yield text
        tail = decoder.decode(b"", final=True)
        if tail:
            yield tail
    finally:
        if live is not None:
            streaming.forget(live)
            live.close()
        else:
            with contextlib.suppress(Exception):
                conn.close()


def get_json(url, headers=None, timeout=30, retries=1):
    attempt = 0
    while True:
        try:
            return _request(url, None, headers, timeout)
        except TransportError as exc:
            if not exc.retryable or attempt >= retries:
                raise
            attempt += 1
            time.sleep(min(2 ** attempt, 8))
