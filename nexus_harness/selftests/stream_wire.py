"""El streaming por el cable: cancelacion del socket, SSE y un turno entero de punta a punta.

Vive aparte de `test_stream` por la ley de 400 lineas y por responsabilidad: alli se mide el pliegue y
los parsers (sin red); aqui se abre un puerto local y se comprueba que los eventos llegan, en orden, y
que Detener corta una conexion de verdad. `test_stream.run()` llama a `run()` de este modulo: para el
operador sigue siendo UNA suite (`selftest stream`).
"""
import json as jsonlib
import threading
import time
import urllib.error
import urllib.request

from ..core import streaming
from ..core.message import Usage


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


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


def test_the_sse_endpoint_serves_the_bus(failures):
    """La decision (b) del operador: el bus por `/api/events/stream`, con token y con `id:`.

    Un evento tiene que llegar con su `seq` como id -- es lo que permite que el navegador reanude con
    `Last-Event-ID` sin repetir ni perder -- y la ruta tiene que negarse sin credencial como el resto
    de `/api/*`.
    """
    import threading
    import urllib.error
    import urllib.request

    from .fakes import FakeRouter, ScriptedProvider, TempProject, reply
    from ..cockpit import Cockpit
    from ..config import HarnessConfig
    from ..ui import build

    with TempProject() as root:
        config = HarnessConfig(default_root=root, workspace=root, test_command=None,
                               roles={"director": "fake:d", "worker": "fake:w", "judge": "fake:j"},
                               host="127.0.0.1", port=0, lang="es", secrets={})
        cockpit = Cockpit(config)
        cockpit.router = FakeRouter(workers=ScriptedProvider([reply("hola")]))
        event = cockpit.bus.emit("worker.delta", "Hola", step=0)
        server = build(cockpit, port=0, token="t0k")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % server.server_address[1]
        try:
            request = urllib.request.Request(
                base + "/api/events/stream?since=%d" % (event.seq - 1),
                headers={"X-Nexus-Token": "t0k"})
            with urllib.request.urlopen(request, timeout=10) as response:
                check("el content-type es SSE",
                      response.headers.get("Content-Type", "").startswith("text/event-stream"),
                      True, failures)
                block = []
                for _ in range(8):
                    line = response.readline().decode("utf-8")
                    block.append(line)
                    if not line.strip() and any(row.startswith("id: ") for row in block):
                        break
                text = "".join(block)
                check("el evento viaja con su seq como id", ("id: %d" % event.seq) in text, True,
                      failures)
                check("y con su payload", '"kind": "worker.delta"' in text, True, failures)
            try:
                urllib.request.urlopen(base + "/api/events/stream", timeout=5)
                failures.append("la ruta SSE sin token deberia dar 401")
            except urllib.error.HTTPError as exc:
                check("sin token es 401", exc.code, 401, failures)
        finally:
            server.shutdown()
            server.server_close()


def test_a_whole_turn_streams_over_http(failures):
    """De punta a punta: POST /api/chat, y por SSE llegan los deltas ANTES del cierre del turno.

    Es la medida de la cabina sin navegador: si el orden del cable es este, el DOM pinta texto antes
    del `done`; si los deltas no viajan, la interfaz no tiene nada que pintar por mucho que sepa.
    """
    import json as jsonlib
    import threading
    import time
    import urllib.request

    from .fakes import FakeRouter, TempProject
    from ..cockpit import Cockpit
    from ..config import HarnessConfig
    from ..core import streaming as core_streaming
    from ..core.message import Usage
    from ..ui import build

    class Streaming:
        model = "fake:stream"

        def stream(self, messages, tools=None, temperature=0.2, max_tokens=2048):
            for piece in ("Ho", "la", "!"):
                yield core_streaming.Event(core_streaming.DELTA, text=piece)
            yield core_streaming.Event(core_streaming.DONE, usage=Usage(prompt=10, completion=3))

        def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
            return core_streaming.fold(self.stream(messages, tools, temperature, max_tokens))

    with TempProject() as root:
        config = HarnessConfig(default_root=root, workspace=root, test_command=None,
                               roles={"director": "fake:d", "worker": "fake:w", "judge": "fake:j"},
                               host="127.0.0.1", port=0, lang="es", temperature=0.0,
                               max_steps=2, max_repairs=1, secrets={})
        cockpit = Cockpit(config)
        cockpit.router = FakeRouter(workers=Streaming())
        server = build(cockpit, port=0, token="t0k")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % server.server_address[1]
        headers = {"Content-Type": "application/json", "X-Nexus-Token": "t0k"}
        try:
            body = jsonlib.dumps({"text": "saluda"}).encode("utf-8")
            started = urllib.request.Request(base + "/api/chat", data=body, headers=headers,
                                             method="POST")
            with urllib.request.urlopen(started, timeout=10) as response:
                check("el turno se acepta", response.status, 202, failures)
            events, kinds = [], []
            deadline = time.time() + 10
            request = urllib.request.Request(base + "/api/events/stream?since=0",
                                             headers={"X-Nexus-Token": "t0k"})
            with urllib.request.urlopen(request, timeout=15) as stream:
                while time.time() < deadline and "chat.turn" not in kinds:
                    line = stream.readline().decode("utf-8")
                    if not line.startswith("data: "):
                        continue
                    event = jsonlib.loads(line[6:])
                    events.append(event)
                    kinds.append(event.get("kind"))
            check("el turno cierra por SSE", "chat.turn" in kinds, True, failures)
            check("los deltas viajan por el cable", kinds.count("worker.delta"), 3, failures)
            check("y antes del cierre",
                  kinds.index("worker.delta") < kinds.index("chat.turn"), True, failures)
            check("el texto se pinta en orden",
                  "".join(row.get("detail", "") for row in events
                          if row.get("kind") == "worker.delta"), "Hola!", failures)
        finally:
            server.shutdown()
            server.server_close()


def run(failures):
    for test in (test_a_hung_stream_is_cut_by_close_all, test_the_sse_endpoint_serves_the_bus,
                 test_a_whole_turn_streams_over_http):
        test(failures)
    return failures
