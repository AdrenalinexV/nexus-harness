"""Una respuesta que llega por partes: eventos mientras el modelo habla, y un `Reply` al final.

El contrato viejo era una dataclass plana: el modelo habla entero y entonces lo ves. Eso hace imposibles
las dos cosas que el operador pide -- ver el texto mientras se escribe y cortar una request en vuelo --
y obliga a cada llamante a saber ensamblar. Aqui hay un solo camino:

    transporte.stream(messages, ...)  ->  eventos (delta, reasoning, tool_call, done)
    transporte.chat(messages, ...)    ->  fold(stream(...))  ->  el MISMO Reply de siempre

`fold` no es un adaptador de conveniencia: es la definicion. El `Reply` nunca existe a medias porque se
construye de una vez al final, y `chat()` no puede desviarse de `stream()` porque no tiene otra fuente.

Un `Reply` ya entero tambien es un stream (`stream_of` lo convierte en eventos): asi los dobles de test
y cualquier transporte de terceros que solo sepa `chat` siguen valiendo sin aprender el contrato nuevo.
"""
import threading
from dataclasses import dataclass, field

from .message import Reply, Usage

DELTA = "delta"
REASONING = "reasoning"
TOOL_CALL = "tool_call"
DONE = "done"
KINDS = (DELTA, REASONING, TOOL_CALL, DONE)


@dataclass
class Event:
    """Un paso de la respuesta mientras llega. `kind` manda; los demas campos son su carga.

    `raw` no puede ser el cuerpo entero de la respuesta porque ese cuerpo no existe: en un stream hay
    trozos. El `done` lleva un resumen (`finish`, numero de chunks) que sirve para diagnosticar sin
    fingir que hubo una sola pieza.
    """

    kind: str
    text: str = ""
    call: object = None
    usage: object = None
    model: str = ""
    raw: dict = field(default_factory=dict)

    def as_dict(self):
        """La forma que viaja al bus y al SSE: plana y serializable, sin objetos del transporte."""
        payload = {"kind": self.kind}
        if self.text:
            payload["text"] = self.text
        if self.call is not None:
            payload["tool"] = {"id": getattr(self.call, "id", ""),
                               "name": getattr(self.call, "name", ""),
                               "arguments": getattr(self.call, "arguments", {})}
        if self.usage is not None:
            payload["usage"] = {"prompt": getattr(self.usage, "prompt", 0),
                                "completion": getattr(self.usage, "completion", 0)}
        if self.model:
            payload["model"] = self.model
        return payload


def fold(events):
    """Pliega el stream en el `Reply` de siempre: texto y razon concatenados, usage del `done`."""
    text, reasoning, calls = [], [], []
    usage, model, raw = Usage(), "", {}
    for event in events:
        kind = getattr(event, "kind", "")
        if kind == DELTA:
            text.append(str(getattr(event, "text", "") or ""))
        elif kind == REASONING:
            reasoning.append(str(getattr(event, "text", "") or ""))
        elif kind == TOOL_CALL and getattr(event, "call", None) is not None:
            calls.append(event.call)
        elif kind == DONE:
            usage = getattr(event, "usage", None) or usage
            model = str(getattr(event, "model", "") or model)
            raw = getattr(event, "raw", None) or raw
    return Reply(text="".join(text).strip(), tool_calls=calls,
                 reasoning="".join(reasoning).strip(), usage=usage, model=model, raw=raw)


def stream_of(transport, messages, tools=None, temperature=0.2, max_tokens=2048):
    """El stream de CUALQUIER transporte: nativo si lo tiene, o uno de un solo bloque si no.

    Los dobles de test y los transportes de terceros solo saben `chat`. Convertirlos aqui -- y no en
    cada llamante -- es lo que hace que "un camino, dos modos" sea cierto tambien para ellos: nadie
    necesita aprender el contrato nuevo para seguir funcionando.
    """
    native = getattr(transport, "stream", None)
    if callable(native):
        return native(messages, tools=tools, temperature=temperature, max_tokens=max_tokens)
    reply = transport.chat(messages, tools=tools, temperature=temperature, max_tokens=max_tokens)
    return as_events(reply)


def as_events(reply):
    """Un `Reply` ya entero como stream: un delta por campo. Sin red y sin estado.

    Un transporte de terceros puede contestar un `str` donde el contrato pide un `Reply`; se toma como
    el texto en vez de reventar con un `AttributeError` en mitad del turno. El `Done` sigue llevando
    `usage` y `model` vacios: no se inventa una medida que el transporte no dio.
    """
    if isinstance(reply, str):
        if reply:
            yield Event(DELTA, text=reply)
        yield Event(DONE)
        return
    if getattr(reply, "text", ""):
        yield Event(DELTA, text=reply.text)
    if getattr(reply, "reasoning", ""):
        yield Event(REASONING, text=reply.reasoning)
    for call in getattr(reply, "tool_calls", None) or []:
        yield Event(TOOL_CALL, call=call)
    yield Event(DONE, usage=getattr(reply, "usage", None), model=getattr(reply, "model", "") or "",
                raw=getattr(reply, "raw", None) or {})


def lines(chunks):
    """Reensambla lineas de fragmentos arbitrarios: un JSON cortado a la mitad no rompe el parser.

    El parser de cada transporte recibe FRAGMENTOS, no lineas: es el unico contrato que se puede probar
    sin red y el unico que sobrevive a un `read()` que parte el `data: {...}` por la mitad.
    """
    buffer = ""
    for chunk in chunks:
        if not chunk:
            continue
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            yield line.rstrip("\r")
    if buffer:
        yield buffer.rstrip("\r")


# -- respuestas en vuelo -------------------------------------------------------------------------
# El boton Detener tiene que cortar el socket, no solo una bandera que el bucle mira entre pasos. Quien
# abre la conexion registra aqui un objeto con `.close()`; `close_all()` los corta todos.
_LIVE = []
_LOCK = threading.Lock()


def register(handle):
    """Anota una respuesta en vuelo. `handle.close()` tiene que cortarla de verdad, no marcarla."""
    with _LOCK:
        _LIVE.append(handle)
    return handle


def forget(handle):
    """Olvida una respuesta que ya termino. Devuelve si estaba registrada: no estar no es un fallo."""
    with _LOCK:
        try:
            _LIVE.remove(handle)
        except ValueError:
            return False
    return True


def close_all():
    """Corta TODA respuesta en vuelo. Devuelve `{"closed": n, "failed": [...]}`.

    Es global por la misma razon que `process_manager`: Detener significa "para todo lo que este
    gastando", no "para lo que este gastando este hilo". El iterador cortado termina con
    `TransportError`, no con un texto a medias. Un handle que no se deja cerrar se declara en
    `failed` en vez de tragarselo: un socket que sobrevive al boton Detener es el dato que importa.
    """
    with _LOCK:
        handles, _LIVE[:] = list(_LIVE), []
    closed, failed = 0, []
    for handle in handles:
        try:
            handle.close()
            closed += 1
        except Exception as exc:  # noqa: BLE001 -- se declara; no se traga
            failed.append("%s: %s" % (type(exc).__name__, exc))
    return {"closed": closed, "failed": failed}


def in_flight():
    """Cuantas respuestas estan abiertas ahora mismo. Cero es el estado sano entre turnos."""
    with _LOCK:
        return len(_LIVE)
