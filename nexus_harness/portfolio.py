"""La cartera: cada rol tiene una escalera de modelos, y una caida no termina el turno.

Dos fallos que arregla:

1. **Roles fijos.** Si el modelo local no rendia, el turno moria ahi: no habia un segundo modelo al que
   pasar. Ahora cada rol declara una escalera (`role_ladders`), y el segundo gate rojo escala al
   siguiente peldano.
2. **Una caida de transporte terminaba el run.** El reintento de `http.py` cubre 429/5xx del MISMO
   endpoint; no cubre "este proveedor no contesta". El `FailoverTransport` prueba los peldanos en orden
   y devuelve el primero que responde, agregando los errores para que el operador sepa que fallo.

Tres reglas que lo mantienen honesto:

* **Ningun escalado sin presupuesto.** Si el techo en USD ya se cruzo, la cartera se niega: escalar a un
  modelo mas caro con el presupuesto agotado es empeorar el problema.
* **Un peldaño sin clave no se salta en silencio**: se declara `not ready` con su motivo y se pasa al
  siguiente, igual que hace `Router.info`.
* **La cartera no inventa modelos.** Si la escalera tiene un solo peldano, no hay escalado: se dice.

La cartera no llama a nadie por su cuenta: es politica (que spec toca) y transporte (a quien preguntar).
"""
from dataclasses import dataclass, field


@dataclass
class Move:
    """El resultado de intentar subir un peldano: si se pudo, a donde y por que no."""

    ok: bool = False
    role: str = ""
    spec: str = ""
    reason: str = ""
    from_spec: str = ""

    def as_dict(self):
        return {"ok": self.ok, "role": self.role, "spec": self.spec,
                "from": self.from_spec, "reason": self.reason}


class Portfolio:
    """Las escaleras por rol, leidas de la configuracion. Pura: no construye transportes."""

    def __init__(self, config):
        self.config = config

    def ladder(self, role):
        """`[spec, ...]` del rol: la escalera declarada, o el spec unico de siempre."""
        declared = getattr(self.config, "role_ladders", None) or {}
        rows = declared.get(role) if isinstance(declared, dict) else None
        specs = [str(one).strip() for one in (rows or []) if str(one or "").strip()]
        primary = str(self.config.role_spec(role) or "").strip()
        if primary and primary not in specs:
            specs.insert(0, primary)
        seen, clean = set(), []
        for spec in specs:
            if spec and spec not in seen:
                seen.add(spec)
                clean.append(spec)
        return clean or ([primary] if primary else [])

    def after(self, role, spec):
        """La escalera desde `spec` hacia abajo: lo que el failover puede probar, en orden."""
        rows = self.ladder(role)
        if spec not in rows:
            return [spec] if spec else rows
        return rows[rows.index(spec):]

    def next_spec(self, role, spec=None):
        """El siguiente peldano despues de `spec` (o del actual), o cadena vacia si no hay."""
        rows = self.ladder(role)
        current = spec or self.config.role_spec(role)
        if current not in rows:
            return rows[0] if rows else ""
        index = rows.index(current) + 1
        return rows[index] if index < len(rows) else ""

    def escalate(self, role, budget=None, reason=""):
        """Sube un peldano si hay a donde y si el presupuesto lo permite."""
        current = str(self.config.role_spec(role) or "")
        following = self.next_spec(role, current)
        if not following:
            return Move(False, role, "", "no hay un modelo siguiente en la escalera de %s" % role,
                        current)
        if budget is not None and getattr(budget, "exceeded", False):
            return Move(False, role, "", "presupuesto de coste agotado: no se escala", current)
        return Move(True, role, following, str(reason or "escalado"), current)

    def state(self):
        return {role: {"current": self.config.role_spec(role), "ladder": self.ladder(role)}
                for role in ("director", "worker", "judge")}


class FailoverTransport:
    """Un transporte con varios peldanos por detras. Misma cara que un transporte normal.

    El bucle no sabe que existe: pide `chat` y recibe una respuesta, o un error que agrega los fallos
    de todos los peldanos. Eso es lo que permite anadir cartera sin tocar `chat.py` ni `triad_loop.py`.
    """

    def __init__(self, router, role, specs):
        self.router = router
        self.role = role
        self.specs = [str(spec) for spec in (specs or []) if str(spec or "").strip()]
        self.used = ""
        self.errors = []

    # -- la cara que el router y el bucle esperan -------------------------------------------------
    @property
    def ready(self):
        return any(self._transport(spec) is not None and self._transport(spec).ready
                   for spec in self.specs)

    @property
    def why_not_ready(self):
        if not self.specs:
            return "la cartera de %s esta vacia" % self.role
        reasons = []
        for spec in self.specs:
            transport = self._transport(spec)
            if transport is None:
                reasons.append("%s: no se pudo construir" % spec)
            elif not transport.ready:
                reasons.append("%s: %s" % (spec, transport.why_not_ready))
        return "; ".join(reasons)

    @property
    def model(self):
        for spec in self.specs:
            transport = self._transport(spec)
            if transport is not None and transport.ready:
                return str(getattr(transport, "model", "") or spec)
        return self.specs[0] if self.specs else ""

    def models(self, timeout=8):
        for spec in self.specs:
            transport = self._transport(spec)
            if transport is None:
                continue
            try:
                found = transport.models(timeout=timeout)
            except Exception:  # noqa: BLE001 -- probar modelos no puede tumbar el catalogo
                continue
            if found:
                return found
        return []

    # -- la llamada ------------------------------------------------------------------------------
    def _transport(self, spec):
        try:
            return self.router.for_spec(spec)
        except Exception:  # noqa: BLE001 -- un spec roto es un peldano menos, no un run caido
            return None

    def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        """Prueba los peldanos en orden. Devuelve la primera respuesta; si no hay, lanza con el detalle."""
        self.errors = []
        for spec in self.specs:
            transport = self._transport(spec)
            if transport is None or not transport.ready:
                self.errors.append("%s: no listo (%s)" % (
                    spec, getattr(transport, "why_not_ready", "sin transporte")))
                continue
            try:
                reply = transport.chat(messages, tools=tools, temperature=temperature,
                                       max_tokens=max_tokens)
            except Exception as exc:  # noqa: BLE001 -- se prueba el siguiente; el error se declara
                self.errors.append("%s: %s: %s" % (spec, type(exc).__name__, exc))
                continue
            self.used = spec
            return reply
        raise RuntimeError("ningun modelo de la cartera de %s respondio: %s"
                           % (self.role, " | ".join(self.errors)[:700] or "sin peldanos"))


def maybe_escalate(router, portfolio, budget, reds, emit=None, threshold=2, role="worker"):
    """Al segundo rojo del turno, sube un peldano si la cartera y el presupuesto lo permiten.

    Se llama desde el chat y desde la triada: una sola politica, dos llamantes. Devuelve el `Move` si
    hubo escalado, `None` si no tocaba.
    """
    if portfolio is None or int(reds or 0) < int(threshold):
        return None
    move = portfolio.escalate(role, budget=budget, reason="%d rojos en el turno" % int(reds))
    if not move.ok:
        if emit is not None:
            emit("router.escalate_refused", move.reason, move=move.as_dict())
        return None
    router.swap(role, move.spec)
    if emit is not None:
        emit("router.escalated", "%s -> %s" % (move.from_spec, move.spec), move=move.as_dict())
    return move
