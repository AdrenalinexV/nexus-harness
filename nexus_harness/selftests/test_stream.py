"""El contrato de streaming: eventos mientras llega, `Reply` al final, y el mismo `Reply` por los dos caminos.

Lo que esta suite defiende, en una frase: **`chat()` no puede desviarse de `stream()` porque no tiene otra
fuente**. Si un transporte se inventa el `Reply` por un lado y los eventos por otro, la cabina pinta una
cosa y el transcript guarda otra; esta suite es la que lo impide.

Los parsers de cada formato (SSE de OpenAI, NDJSON de Ollama, `content_block_delta` de Anthropic) se
prueban en la suite de su transporte contra el mismo JSON cortado a la mitad. Aqui se mide el pliegue,
que es comun a los cuatro.
"""
import json

from ..core import streaming
from ..core.message import Reply, ToolCall, Usage


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


class Whole:
    """Un transporte viejo: solo `chat`. Es el doble de test y el transporte de terceros."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        self.calls += 1
        return self.reply


class Parted(Whole):
    """El mismo transporte, pero con el contrato nuevo: `stream()` es la fuente y `chat()` lo pliega."""

    def stream(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        yield streaming.Event(streaming.DELTA, text="Hola")
        yield streaming.Event(streaming.DELTA, text=" mundo")
        yield streaming.Event(streaming.REASONING, text="porque si")
        yield streaming.Event(streaming.TOOL_CALL,
                              call=ToolCall(id="call_1", name="read_file",
                                            arguments={"path": "calc.py"}, raw_arguments='{"path": "calc.py"}'))
        yield streaming.Event(streaming.DONE, usage=Usage(prompt=10, completion=5),
                              model="fake:parted", raw={"finish": "tool_calls", "chunks": 4})

    def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        return streaming.fold(self.stream(messages, tools, temperature, max_tokens))


def same_reply(label, got, expected, failures):
    """Lo que tiene que coincidir. `raw` NO: en un stream no hay cuerpo entero, hay un resumen."""
    for field in ("text", "reasoning", "model"):
        check("%s: %s" % (label, field), getattr(got, field), getattr(expected, field), failures)
    check("%s: tool_calls" % label,
          [(call.id, call.name, call.arguments) for call in got.tool_calls],
          [(call.id, call.name, call.arguments) for call in expected.tool_calls], failures)
    check("%s: usage" % label,
          (got.usage.prompt, got.usage.completion),
          (expected.usage.prompt, expected.usage.completion), failures)


def test_fold_rebuilds_the_same_reply(failures):
    expected = Reply(text="Hola mundo", reasoning="porque si",
                     tool_calls=[ToolCall(id="call_1", name="read_file",
                                          arguments={"path": "calc.py"},
                                          raw_arguments='{"path": "calc.py"}')],
                     usage=Usage(prompt=10, completion=5), model="fake:parted")
    transport = Parted(None)
    same_reply("fold(stream())", transport.chat([]), expected, failures)


def test_one_path_two_modes(failures):
    """El `Reply` del contrato nuevo y el del viejo son el mismo objeto, campo a campo."""
    old = Whole(Reply(text="Hola mundo", reasoning="porque si",
                      tool_calls=[ToolCall(id="call_1", name="read_file",
                                           arguments={"path": "calc.py"},
                                           raw_arguments='{"path": "calc.py"}')],
                      usage=Usage(prompt=10, completion=5), model="fake:parted"))
    new = Parted(None)
    same_reply("contrato viejo vs nuevo", new.chat([]), old.chat([]), failures)


def test_a_chat_only_transport_becomes_a_stream(failures):
    reply = Reply(text="una sola pieza", reasoning="", usage=Usage(prompt=3, completion=2),
                  model="fake:whole")
    transport = Whole(reply)
    events = list(streaming.stream_of(transport, []))
    check("el fallback no vuelve a llamar a chat", transport.calls, 1, failures)
    check("el fallback trae delta y done",
          [event.kind for event in events], [streaming.DELTA, streaming.DONE], failures)
    same_reply("fold del fallback", streaming.fold(events), reply, failures)


def test_a_native_stream_is_used_as_is(failures):
    transport = Parted(None)
    events = list(streaming.stream_of(transport, []))
    check("el stream nativo no se convierte en un bloque",
          [event.kind for event in events],
          [streaming.DELTA, streaming.DELTA, streaming.REASONING, streaming.TOOL_CALL,
           streaming.DONE], failures)


def test_lines_survive_a_split_json(failures):
    """El fixture que corta el JSON en dos: exactamente el fallo que rompia el parser de una pieza."""
    chunks = ['data: {"choices": [{"delta": {"content": "Ho', 'la"}}]}\n\ndata: [DONE]\n']
    check("una linea partida se reensambla", list(streaming.lines(chunks)),
          ['data: {"choices": [{"delta": {"content": "Hola"}}]}', "", "data: [DONE]"], failures)
    check("un salto de linea final sin texto no pierde la ultima linea",
          list(streaming.lines(['{"a": 1}', '\n', '{"b"'])), ['{"a": 1}', '{"b"'], failures)


def test_an_event_serializes_flat(failures):
    event = streaming.Event(streaming.TOOL_CALL,
                            call=ToolCall(id="c1", name="read_file", arguments={"path": "a.py"}))
    payload = event.as_dict()
    check("el evento viaja plano", payload,
          {"kind": "tool_call", "tool": {"id": "c1", "name": "read_file",
                                        "arguments": {"path": "a.py"}}}, failures)
    check("y es serializable", json.loads(json.dumps(payload)), payload, failures)


def test_stop_cuts_the_live_stream(failures):
    """`close_all()` no marca una bandera: cierra el handle que abrio la conexion."""
    class Handle:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class Stuck(Handle):
        def close(self):
            raise OSError("el socket ya no esta")

    first, second, stuck = Handle(), Handle(), Stuck()
    streaming.register(first)
    streaming.register(second)
    streaming.register(stuck)
    check("tres en vuelo", streaming.in_flight(), 3, failures)
    report = streaming.close_all()
    check("cierra las dos que se dejan", report["closed"], 2, failures)
    check("y declara la que no", len(report["failed"]), 1, failures)
    check("la que fallo se nombra", "OSError" in report["failed"][0], True, failures)
    check("y las cerro de verdad", (first.closed, second.closed), (True, True), failures)
    check("el registro queda vacio", streaming.in_flight(), 0, failures)
    streaming.forget(first)
    check("olvidar un handle que no estaba no rompe", streaming.in_flight(), 0, failures)


def test_a_hung_stream_is_cut_by_close_all(failures):
    """El criterio del paso 10: 3 deltas, el modelo se cuelga, Detener corta de verdad en <=1 s.

    Un servidor local entrega tres lineas SSE y despues espera. El lector esta bloqueado dentro de
    `readline()`: si `close_all()` solo pusiera una bandera, seguiria ahi. Se mide el tiempo real y que
    el SERVIDOR vea caer la conexion -- sin eso, "cortado" seria una palabra nuestra, no un hecho.
    """
    import http.server
    import threading
    import time

    from ..llm.transports import http as transport_http

    class Hung(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        timeout = 10
        seen = []

        def log_message(self, *args):  # el servidor de prueba no ensucia la salida del gate
            return None

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            for index in range(3):
                self.wfile.write(b'data: {"choices": [{"delta": {"content": "%d"}}]}\n' % index)
                self.wfile.flush()
            Hung.seen.append("sent")
            try:
                while self.rfile.read(1):
                    continue
            except OSError:
                Hung.seen.append("client-gone")
            else:
                Hung.seen.append("client-gone")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hung)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d/v1/chat/completions" % server.server_address[1]
    received, finished = [], threading.Event()

    def read():
        try:
            for line in transport_http.stream_lines(url, {"model": "prueba"}, timeout=10):
                received.append(line)
        except Exception as exc:  # noqa: BLE001 -- el hallazgo ES la excepcion
            received.append("EXC:%s" % type(exc).__name__)
        finally:
            finished.set()

    threading.Thread(target=read, daemon=True).start()
    deadline = time.time() + 5
    while len(received) < 3 and time.time() < deadline:
        time.sleep(0.02)
    check("el stream entrega las tres lineas antes de que el modelo termine",
          len(received) >= 3, True, failures)
    started = time.time()
    streaming.close_all()
    finished.wait(2.0)
    elapsed = time.time() - started
    check("cortar el socket termina el iterador en menos de 1 s", elapsed < 1.0, True, failures)
    check("el iterador no mintio con una excepcion", [r for r in received if r.startswith("EXC:")], [], failures)
    check("el servidor ve caer la conexion", "client-gone" in Hung.seen, True, failures)
    check("el registro queda vacio", streaming.in_flight(), 0, failures)
    server.shutdown()
    server.server_close()


def run():
    failures = []
    test_fold_rebuilds_the_same_reply(failures)
    test_one_path_two_modes(failures)
    test_a_chat_only_transport_becomes_a_stream(failures)
    test_a_native_stream_is_used_as_is(failures)
    test_lines_survive_a_split_json(failures)
    test_an_event_serializes_flat(failures)
    test_stop_cuts_the_live_stream(failures)
    test_a_hung_stream_is_cut_by_close_all(failures)
    return failures
