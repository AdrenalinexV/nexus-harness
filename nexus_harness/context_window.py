"""La ventana REAL del motor, preguntada al servidor en vez de tecleada en un formulario.

El fallo que arregla, medido: LM Studio tenia cargado `qwen3.8-27b` con 64.256 tokens de ventana, la
configuracion decia 60.000 y el prompt que el arnes envio llevaba 66.889. El motor contesto

    400 {"error":"Engine protocol predict request returned 400: ... request (68052 tokens)
         exceeds the available context size (64256 tokens), try increasing it"}

y el turno murio con un `TransportError` crudo: ni compactacion, ni relevo, ni explicacion. Un limite
que nadie compara con la ventana del motor no es un presupuesto, es una promesa.

Aqui vive la unica comparacion, con tres piezas:

* `of(transport)` -- que ventana tiene de verdad el motor que sirve ese rol (`loaded_context_length`
  en LM Studio, `context_length` en Ollama). Un servidor que no lo publica devuelve 0: no se inventa.
* `fit(limit, window, max_tokens)` -- el presupuesto util: el menor entre lo configurado y lo que cabe
  dejando sitio a la respuesta. Con `window=0` no recorta nada, porque no hay dato.
* `overflow(exc)` -- cuando el motor dice que no cabe, saca su ventana del propio error. Eso convierte
  un 400 opaco en aprendizaje: el siguiente intento ya sabe cuanto tiene que cortar.
* `shrink(messages, budget)` -- ultimo recurso determinista: recorta los cuerpos mas grandes (cabeza +
  cola, con marca de lo que falta) hasta que el prompt entra. Nunca toca roles ni la ultima peticion.

Ninguna de estas funciones levanta: un motor apagado es `0`, no una excepcion en mitad de un turno.
"""
import json
import re

from .transports import http

LMSTUDIO_MODELS = "/api/v0/models"
OLLAMA_PS = "/api/ps"
# Colchon sobre el hueco de salida: la plantilla del chat tambien come tokens que nadie cuenta.
MARGIN = 0.05
MIN_BUDGET = 2000
MIN_CLIP = 400
KNOWN_KEYS = ("n_ctx", "context_length", "loaded_context_length", "max_context_length")
EXCEEDS = re.compile(r"exceeds the available context size \((\d+)\s*tokens\)", re.I)
MAXIMUM = re.compile(r"maximum context length is (\d+)\s*tokens", re.I)


def _root(base_url):
    """`http://host:1234/v1` -> `http://host:1234`: el descubrimiento no vive bajo `/v1`."""
    url = str(base_url or "").rstrip("/")
    return url[:-3] if url.endswith("/v1") else url


def _digits(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def lmstudio_window(payload, model=""):
    """Ventana cargada del modelo, de `/api/v0/models`. Solo cuenta si esta CARGADO.

    `max_context_length` es lo que el fichero podria aceptar; lo que decide si un prompt cabe es
    `loaded_context_length`, y confundirlos es volver a prometer de mas.
    """
    rows = (payload or {}).get("data") if isinstance(payload, dict) else payload
    best = 0
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        if model and str(row.get("id") or "") != str(model):
            continue
        if str(row.get("state") or "").lower() not in ("", "loaded"):
            continue
        best = max(best, _digits(row.get("loaded_context_length")))
    return best


def ollama_window(payload, model=""):
    """Ventana de un modelo ya cargado, de `/api/ps`."""
    rows = (payload or {}).get("models") if isinstance(payload, dict) else payload
    best = 0
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        names = (str(row.get("name") or ""), str(row.get("model") or ""))
        if model and str(model) not in names:
            continue
        best = max(best, _digits(row.get("context_length")))
    return best


LOCAL_HOSTS = ("127.0.0.1", "localhost", "0.0.0.0", "[::1]")


def _local(root):
    return any(host in root for host in LOCAL_HOSTS)


def of(transport, timeout=4):
    """La ventana del motor que sirve `transport`, o 0 si no la publica o no esta.

    Solo se pregunta a servidores locales: un proveedor de nube no expone su ventana en un endpoint
    barato, y adivinarla es exactamente lo que este modulo existe para no hacer.
    """
    kind = str(getattr(transport, "kind", "") or "")
    model = str(getattr(transport, "model", "") or "")
    root = _root(getattr(transport, "base_url", ""))
    if not root or not _local(root):
        return 0
    endpoints = ((OLLAMA_PS,) if kind == "ollama" else (LMSTUDIO_MODELS, OLLAMA_PS))
    for endpoint in endpoints:
        try:
            payload = http.get_json(root + endpoint, timeout=timeout, retries=0)
        except Exception:  # noqa: BLE001 -- un motor que no contesta no puede tumbar un turno
            continue
        found = (ollama_window if endpoint == OLLAMA_PS else lmstudio_window)(payload, model)
        if found:
            return found
    return 0


def fit(limit, window, max_tokens, margin=MARGIN):
    """Presupuesto util: ni mas de lo configurado, ni mas de lo que cabe con la respuesta dentro.

    `window=0` significa "no hay dato", y entonces se respeta lo configurado: recortar por una ventana
    desconocida seria adivinar. Un techo declarado y una ventana conocida se resuelven con `min`.
    """
    limit, window, max_tokens = _digits(limit), _digits(window), _digits(max_tokens)
    if window <= 0:
        return limit
    room = max(MIN_BUDGET, window - max_tokens - int(window * float(margin)))
    return min(limit, room) if limit > 0 else room


def _walk(data, depth=0):
    """Recorre dicts, listas y JSON anidado DENTRO de cadenas (LM Studio envuelve el error del motor)."""
    if depth > 4:
        return
    if isinstance(data, str):
        text = data.strip()
        if text[:1] in ("{", "["):
            try:
                yield from _walk(json.loads(text), depth + 1)
            except ValueError:
                return
        return
    if isinstance(data, dict):
        yield data
        for value in data.values():
            yield from _walk(value, depth + 1)
    elif isinstance(data, list):
        for value in data:
            yield from _walk(value, depth + 1)


def overflow(exc):
    """La ventana que el motor confeso al rechazar el prompt; 0 si el fallo era otra cosa."""
    body = str(getattr(exc, "body", "") or "")
    if not body.strip():
        return 0
    try:
        parsed = json.loads(body)
    except ValueError:
        parsed = body
    found = 0
    for row in _walk(parsed):
        for key in KNOWN_KEYS:
            found = max(found, _digits(row.get(key)) or 0)
    if found:
        return found
    for pattern in (EXCEEDS, MAXIMUM):
        match = pattern.search(body)
        if match:
            return _digits(match.group(1))
    return 0


def _clip(text, limit):
    """Cabeza + cola con marca de lo que falta: el final de una salida es donde esta la respuesta."""
    body = str(text or "")
    if len(body) <= limit:
        return body
    limit = max(MIN_CLIP, int(limit))
    if len(body) <= limit:
        return body
    head = int(limit * 0.6)
    tail = limit - head
    return "%s\n... (%d chars recortados por ventana del motor)\n%s" % (
        body[:head], len(body) - limit, body[-tail:])


def shrink(messages, budget, model=""):
    """Recorta cuerpos hasta que el prompt quepa en `budget` tokens. Determinista y sin perder roles.

    Nunca toca el `system` (es el contrato del turno), ni el ultimo mensaje del operador (es la
    pregunta), ni un mensaje con adjuntos (sus partes no son texto recortable). El resto se recorta en
    varias pasadas: primero los cuerpos mas grandes que la media, y el tope baja a la mitad si aun no
    cabe, asi que termina siempre.
    """
    from .platform.tokenizer import count_messages

    body = list(messages or ())
    budget = _digits(budget)
    if not body or budget <= 0:
        return body
    total = count_messages(body, model)
    if total <= budget:
        return body
    protected = {0}
    for position in range(len(body) - 1, -1, -1):
        if body[position].role == "user":
            protected.add(position)
            break
    candidates = [position for position, message in enumerate(body)
                  if position not in protected and isinstance(message.content, str)]
    if not candidates:
        return body
    cap = max(MIN_CLIP, int(budget * 4 / float(len(body))))
    for _round in range(8):
        for position in candidates:
            message = body[position]
            body[position] = type(message)(
                role=message.role, content=_clip(message.content, cap),
                tool_calls=message.tool_calls, tool_call_id=message.tool_call_id,
                name=message.name)
        total = count_messages(body, model)
        if total <= budget or cap <= MIN_CLIP:
            break
        cap = max(MIN_CLIP, cap // 2)
    return body


def selftest():
    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    loaded = {"data": [{"id": "m", "state": "loaded", "loaded_context_length": 64256,
                        "max_context_length": 262144}]}
    idle = {"data": [{"id": "m", "state": "not-loaded", "max_context_length": 262144}]}
    check("la ventana cargada manda", lmstudio_window(loaded, "m"), 64256)
    check("un modelo sin cargar no promete ventana", lmstudio_window(idle, "m"), 0)
    check("otro modelo no se confunde", lmstudio_window(loaded, "otro"), 0)
    check("ollama publica su ventana", ollama_window({"models": [{"model": "q", "context_length": 8192}]},
                                                     "q"), 8192)
    check("el presupuesto no pasa de la ventana", fit(60000, 64256, 4096) <= 60000, True)
    check("con ventana pequena se recorta", fit(60000, 8192, 2048) < 8192, True)
    check("sin dato de ventana se respeta lo configurado", fit(60000, 0, 4096), 60000)
    check("sin limite configurado manda la ventana", fit(0, 64256, 4096) > 2000, True)

    class Fatiga(RuntimeError):
        body = ('{"error":"Engine protocol predict request returned 400: {\\"error\\":{\\"code\\":400,'
                '\\"message\\":\\"request (68052 tokens) exceeds the available context size (64256 '
                'tokens), try increasing it\\"}}"}')

    class Otro(RuntimeError):
        body = '{"error":"model not found"}'

    check("el 400 del motor ensena su ventana", overflow(Fatiga()), 64256)
    check("otro error no se confunde con ventana", overflow(Otro()), 0)
    check("sin cuerpo no hay ventana", overflow(RuntimeError()), 0)

    from .core.message import Message
    big = [Message(role="system", content="reglas " * 100),
           Message(role="user", content="hazlo"),
           Message(role="tool", content="x" * 40000, tool_call_id="c1", name="read_file")]
    from .platform.tokenizer import count_messages
    before = count_messages(big, "")
    shrunk = shrink(big, 3000, "")
    check("recorta hasta caber", count_messages(shrunk, "") <= 3000, True)
    check("y de verdad habia que recortar", before > 3000, True)
    check("el system sobrevive entero", shrunk[0].content, big[0].content)
    check("la peticion sobrevive entera", shrunk[1].content, "hazlo")
    check("la marca dice que falta", "recortados" in shrunk[2].content, True)
    check("ya cabe: no se toca", shrink(big, 10 ** 9, ""), big)
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("context_window: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
