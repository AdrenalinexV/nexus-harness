"""La contabilidad de un turno de chat: tokens, calibracion del contador y libro de ahorro.

Vivia dentro de `chat.py`, que llego a 388 lineas justo cuando el paso 11 pide sitio. No es el bucle:
son cuatro piezas que solo leen lo que el turno ya produjo (`reply`, `usage`, `messages`). Acceden a los
mismos atributos que el chat ya tenia (`savings`, `tokens`, `router`, `engine`, `_emit`), asi que el
cambio es de sitio, no de contrato -- el mismo trato que `core.turn_support` con el bucle de la triada.
"""
from .compaction import estimate
from ..platform.tokenizer import calibration, count_messages


class ChatAccounting:
    """Tokens, calibracion y ahorro de un turno. No decide nada: mide lo que ya paso."""

    def _count_savings(self, reply, messages):
        """Cierra la request en el libro de ahorro del turno (baseline, ahorro y multiplicador).

        Ademas calibra el contador: compara la estimacion propia con el `prompt_tokens` que el
        proveedor devolvio, para que el proximo presupuesto (55/70 %) mida con el sesgo de ESTE modelo
        y no con un `chars / 4` que se desvia un 20-30 %.
        """
        model = self._model_of("worker") or str(getattr(reply, "model", "") or "")
        measured = bool(getattr(reply.usage, "measured", False))
        sent = int(getattr(reply.usage, "prompt", 0) or 0) or estimate(messages)[1]
        if measured and sent > 0:
            calibration().observe(model, count_messages(messages, model), sent)
        first_map = 0 if self.savings.repomap_tokens else self._map_tokens
        row = self.savings.request(sent, injected_skill_tokens=self._injected_tokens,
                                   repomap_tokens=first_map, measured=measured,
                                   cached_tokens=int(getattr(reply.usage, "cached", 0) or 0))
        self._emit("context.savings", self.savings.note(), row=row, totals=self.savings.as_dict())
        return row

    def _model_of(self, role):
        """El id del modelo de un rol, sin romper el turno si el router no puede decirlo."""
        try:
            return str(self.router.info(role).model or "")
        except Exception:  # noqa: BLE001 -- la calibracion es una mejora, no un requisito
            return ""

    @property
    def window_tokens(self):
        """La ventana que el motor declaro en este turno. 0 = no la publica, y entonces no hay recorte."""
        return int(getattr(self.engine, "window", 0) or 0)

    def _count(self, usage):
        """Suma los tokens del turno. Sin esto, el libro de turnos no puede decir cuanto costo."""
        self.turn_tokens["prompt"] += int(getattr(usage, "prompt", 0) or 0)
        self.turn_tokens["completion"] += int(getattr(usage, "completion", 0) or 0)
