"""La llamada al modelo y su red de seguridad de ventana, en un solo sitio.

Vivia dentro de `chat.py`, que ya iba por 447 lineas: la ley de 400 no se negocia, y ademas el
`Triad` necesitaba exactamente la misma proteccion y no la tenia. Aqui vive la unica version.

Dos responsabilidades, y las dos son de tamaño, no de estilo:

* `fit()` -- el presupuesto de un turno se resuelve contra la ventana **real** del motor
  (`context_window`), no contra la cifra que alguien tecleo. Si el motor no la publica, se respeta lo
  configurado y se dice que no hay dato.
* `ask()` -- si el motor contesta 400 porque el prompt no cabe, el error ya dice cuanto tiene
  (`exceeds the available context size (64256 tokens)`): se aprende, se poda de verdad el historial y
  se repite UNA vez. Un fallo que no sea de tamaño sube intacto, porque disfrazarlo de respuesta es
  peor que el fallo.

El modulo no conoce el bucle: recibe el prompt, lo reescribe si hace falta y avisa con `resync`
para que el llamante vuelva a separar historia de deltas.
"""
from . import context_window
from .transports import http


class TurnEngine:
    """Una llamada al worker con el presupuesto medido y la recuperacion de ventana incluida."""

    def __init__(self, router, config, compactor=None, registry=None, emit=None, role="worker",
                 relay=None):
        self.router = router
        self.config = config
        # El rol que se llama por defecto. El `Triad` lo usa tambien para el director y el juez.
        self.role = role
        self.compactor = compactor
        self.registry = registry
        self._emit = emit or (lambda *args, **kwargs: None)
        # El relevo de sesion mide el MISMO presupuesto: dos numeros distintos serian dos verdades.
        self.relay = relay
        self.window = 0
        self.last_report = {}

    # -- el presupuesto del turno ----------------------------------------------------------------
    def fit(self, learned=0):
        """El presupuesto en tokens de este turno, ajustado a la ventana real del motor.

        `learned` es la ventana que el motor confeso en un 400 y manda sobre el endpoint. Sin dato se
        respeta lo configurado: recortar por una ventana desconocida es adivinar.
        """
        probe = getattr(self.router, "window", None)
        window = int(learned or 0)
        if not window and callable(probe):
            try:
                window = int(probe("worker") or 0)  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001 -- un router mudo deja el presupuesto como estaba
                window = 0
        limit = context_window.fit(getattr(self.config, "budget_limit", 0), window,
                                   getattr(self.config, "max_tokens", 0))
        self.window = window
        if self.compactor is not None:
            self.compactor.model = self._model() or self.compactor.model
            if limit and limit != self.compactor.limit:
                self._emit("context.window", "presupuesto %d sobre una ventana de %s"
                           % (limit, window or "?"), limit=limit, window=window)
                self.compactor.limit = limit
        if self.relay is not None and getattr(self.relay, "meter", None) is not None:
            self.relay.meter.limit = limit
        self.last_report = {"limit": limit, "window": window}
        return limit

    def _model(self):
        try:
            return str(self.router.info("worker").model or "")
        except Exception:  # noqa: BLE001 -- el nombre del modelo solo afina la calibracion
            return ""

    # -- la llamada ------------------------------------------------------------------------------
    def tools(self, enabled=True):
        if not enabled or self.registry is None:
            return None
        return self.registry.schemas()

    def call(self, messages, tools=None, role=None, max_tokens=None):
        """Una llamada, sin red. El transporte del rol ya trae la cartera de relevo detras."""
        return self.router.role(role or self.role).chat(
            messages, tools=self.tools() if isinstance(tools, bool) else tools,
            temperature=getattr(self.config, "temperature", 0.2),
            max_tokens=max_tokens or getattr(self.config, "max_tokens", 2048))

    def ask(self, messages, tools=None, resync=None, role=None, max_tokens=None):
        """La llamada, y si el prompt no cabe: podar hasta que quepa y repetir una vez."""
        try:
            return self.call(messages, tools, role=role, max_tokens=max_tokens)
        except http.TransportError as exc:
            n_ctx = context_window.overflow(exc)
            if not n_ctx:
                raise
            limit = self.fit(learned=n_ctx)
            kept, report = self.compactor.hard(messages, limit=limit) if self.compactor is not None \
                else (context_window.shrink(messages, limit, self._model()), {})
            messages[:] = kept
            self.last_report = dict(report, limit=limit, window=n_ctx)
            if resync is not None:
                resync(messages)
            self._emit("context.overflow",
                       "el motor solo tiene %d tokens: presupuesto %d" % (n_ctx, limit),
                       window=n_ctx, limit=limit, compaction=report)
            try:
                return self.call(messages, tools, role=role, max_tokens=max_tokens)
            except http.TransportError as second:
                if not context_window.overflow(second):
                    raise
                raise http.TransportError(
                    "el prompt sigue sin caber en los %d tokens que el motor declaro: sube la "
                    "ventana del modelo en el servidor (LM Studio: Context Length) o baja el limite "
                    "de contexto" % n_ctx, status=second.status, body=second.body) from second


BULK = "relleno de una salida de herramienta que ocupa sitio de verdad en la ventana " * 3000


def selftest():
    """La recuperacion, con un motor falso que rechaza el primer prompt por tamaño."""
    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    class Config:
        budget_limit = 60000
        max_tokens = 4096
        temperature = 0.2

    class Fatiga(http.TransportError):
        pass

    class Motor:
        def __init__(self):
            self.calls = []

        def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
            self.calls.append(list(messages))
            if len(self.calls) == 1:
                raise Fatiga("400", status=400,
                             body='{"error":"Engine protocol predict request returned 400: {\\"error'
                                  '\\":{\\"message\\":\\"request (68052 tokens) exceeds the available '
                                  'context size (64256 tokens)\\"}}"}')
            return "respuesta"

    class Router:
        def __init__(self):
            self.motor = Motor()

        def window(self, role):
            return 64256

        def role(self, role):
            return self.motor

        def info(self, role):
            return type("I", (), {"model": "m"})()

    class Registry:
        def schemas(self):
            return []

    from .compaction import Compactor
    from .core.message import Message

    late = [Message(role="system", content="reglas " * 50), Message(role="user", content="hazlo")]
    late += [Message(role="tool", content=BULK, tool_call_id="c%d" % index, name="read_file")
             for index in range(4)]
    router = Router()
    compactor = Compactor(limit=60000, threshold=0.55, model="m")
    engine = TurnEngine(router, Config, compactor, Registry())
    check("el presupuesto cabe en la ventana", engine.fit() <= 64256 - 4096, True)
    seen = {}
    before = [Message(role=m.role, content=m.content) for m in late]
    reply = engine.ask(late, True, resync=lambda messages: seen.update(count=len(messages)))
    check("reintenta y contesta", reply, "respuesta")
    check("hubo dos llamadas", len(router.motor.calls), 2)
    check("el reintento lleva menos texto",
          sum(len(str(m.content)) for m in router.motor.calls[1])
          < sum(len(str(m.content)) for m in before), True)
    check("avisa al llamante para re-sincronizar", "count" in seen, True)
    check("aprende la ventana del error", engine.window, 64256)
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("turn_engine: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
