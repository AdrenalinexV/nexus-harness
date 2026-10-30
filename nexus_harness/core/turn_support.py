"""Piezas del turno que no son el bucle: absorber una respuesta, cerrar con un resumen y consultar hooks.

Vivían dentro de `Triad` y se fueron a su módulo cuando el fichero llegó a 399 líneas — no para esquivar
la ley de 400 apretando comentarios, sino porque son otra cosa: `Triad` decide qué hacer, esto sabe
**cómo** anotar lo que pasó. El mixin accede a los mismos atributos que ya tenía el bucle (`_ask`,
`_emit`, `cost`, `tokens`, `relay`, `config`), así que el cambio es de sitio, no de contrato.
"""
import time

from .message import Message
from ..platform import hooks as hooks_mod


class TurnSupport:
    """Lo que el turno necesita saber hacer sin decidir nada."""

    def _absorb(self, reply):
        self.cost.observe(reply.usage, reply.model)
        # Los tokens del run viajan en el resultado: el libro los necesita para su propia grafica.
        self.tokens["prompt"] += int(getattr(reply.usage, "prompt", 0) or 0)
        self.tokens["completion"] += int(getattr(reply.usage, "completion", 0) or 0)
        if self.relay is not None:
            self.relay.observe(reply.usage)

    def _closing_summary(self, messages, fallback, prompt):
        """Una última llamada sin herramientas: un run que acaba en una tool call no deja al juez nada
        que aprobar, y un resumen vacío es un rechazo legítimo. Dos frases cuestan una llamada barata.

        El texto del cierre lo pasa quien llama (`context/triad_brief`), no se importa aquí: `core` está
        a la izquierda de `context` y un import hacia la derecha rompería el invariante de capas.
        """
        try:
            reply = self._ask("worker", list(messages) + [Message(role="user", content=prompt)],
                              tools=None, max_tokens=400)
        except Exception as exc:  # el resumen es una cortesía; su ausencia no es un crash
            self._emit("worker.error", "closing summary failed: %s: %s" % (type(exc).__name__, exc))
            return fallback
        self._absorb(reply)
        if reply.text:
            self._emit("worker.close", reply.text[:400])
        return reply.text or fallback

    def _hook(self, point, payload=None):
        """Ejecuta los hooks de `point` sobre el proyecto del turno. Devuelve el que PARA, o None.

        `before_turn`/`after_tool` se consultan aquí; `pre_verify` en el gate y `before_commit` en el
        commit. Los cuatro leen el mismo `nexus_harness.toml` y hablan el mismo 0/10/20/30.
        """
        root = getattr(self.config, "default_root", None) or "."
        declared = hooks_mod.Hooks.load(root)
        results = declared.at(point, dict(payload or {}, at=time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                        time.gmtime())), cwd=root)
        return hooks_mod.blocked(results)
