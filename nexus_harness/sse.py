"""El bus como `text/event-stream`: la cabina ve el turno mientras ocurre.

Decision del paso 10 (brecha C): los deltas viajan al bus como `worker.delta`, y este endpoint los
sirve sin esperar al sondeo de 800 ms. Es una ruta mas que mantener, y por eso vive aparte y con su
propio criterio:

* **Un hilo por cliente.** El servidor ya es `ThreadingHTTPServer`; no se abre nada nuevo.
* **`Last-Event-ID`.** El navegador reanuda solo, y sin perder eventos: el id de cada bloque es el
  `seq` del bus, el mismo numero que usa `/api/events?since=`.
* **Latido cada 5 s.** Un proxy callado corta una conexion sin trafico; un `:` de comentario no entra
  en el `data:` y no ensucia el hilo. Es tambien como la ruta se entera de que el cliente se fue.
* **Duracion maxima.** A los 5 minutos la ruta cierra; el navegador se reconecta con su ultimo id. Una
  conexion eterna es una fuga silenciosa de hilos.
"""
import json
import time

HEARTBEAT = 5.0
POLL = 0.2
MAX_SECONDS = 300.0
RETRY_MS = 1500


def _resume_from(handler, query):
    """El ultimo evento que el cliente ya vio: cabecera de reconexion o `?since=` de la primera vez."""
    candidates = [handler.headers.get("Last-Event-ID") or "", (query.get("since") or [""])[0]]
    for candidate in candidates:
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0


def _write(handler, block):
    """Escribe y vacia. `False` significa que el cliente ya no esta: no es un fallo del motor."""
    try:
        handler.wfile.write(block.encode("utf-8"))
        handler.wfile.flush()
        return True
    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
        return False


def stream(handler, cockpit, query):
    """Sirve `/api/events/stream` hasta que el cliente se va o pasa `MAX_SECONDS`."""
    bus = cockpit.bus
    since = _resume_from(handler, query)
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    # Sin `Content-Length`: el cuerpo es un flujo y termina cuando el servidor cierra. El codigo 200 y
    # las cabeceras ya estan; `end_headers` manda el bloque y a partir de ahi todo es `data:`.
    handler.send_header("Connection", "close")
    handler.end_headers()
    if not _write(handler, "retry: %d\n\n" % RETRY_MS):
        return None
    deadline = time.time() + MAX_SECONDS
    beat = time.time() + HEARTBEAT
    while time.time() < deadline:
        pending = bus.since(since)
        for event in pending:
            since = max(since, int(event.get("seq") or 0))
            block = "id: %d\ndata: %s\n\n" % (since, json.dumps(event, ensure_ascii=False))
            if not _write(handler, block):
                return None
        if not pending:
            time.sleep(POLL)
        if time.time() >= beat:
            beat = time.time() + HEARTBEAT
            if not _write(handler, ": latido\n\n"):
                return None
    return None
