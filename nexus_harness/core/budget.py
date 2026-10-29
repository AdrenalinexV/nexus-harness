"""Presupuesto de coste: el turno tiene un techo en dolares y lo respeta.

El presupuesto que ya existia mide **tokens** contra el limite de la ventana (`compaction.py`) o contra
el umbral del relevo (`session_relay.py`). Eso es higiene de contexto, no dinero: un turno autonomo con
un modelo de nube puede gastar sin que nada lo pare, porque `max_steps` limita el *numero* de llamadas
y no su *precio*, y el precio no es el mismo arriba que abajo (una entrada de 100k tokens y una salida
de 100k tokens no cuestan lo mismo).

Aqui el techo es en USD y la parada es dura: la comprobacion vive **antes** de cada llamada al modelo,
asi que cruzar el techo no pide una llamada mas -- la corta. Tres reglas que se copian del resto del
harness, porque son las que impiden que un numero bonito mienta:

* un modelo sin precio conocido **no cuesta cero**: la llamada se cuenta como `unpriced` y se declara,
  igual que un presupuesto sin medir no es 0 %;
* la inferencia local (`lmstudio:`, `ollama:`) si es gratis, y se dice con un precio de 0 **declarado**,
  que es distinto de no saberlo;
* `limit_usd=0` es "sin tope declarado" (`unbounded`), no un tope de cero -- y por eso `exceeded` es
  falso aunque se haya gastado una fortuna: nadie declaro un techo que cruzar.

La tabla de precios es una **foto**, no una verdad eterna: se escribe aqui, se puede pisar desde
`~/.nexus/harness.json` y envejece. Por eso un modelo que no esta en ella no se inventa: se marca.
"""
from dataclasses import dataclass, field

USD_PER_MILLION = 1_000_000.0
# Un token de entrada servido de cache se cobra a una fraccion declarada del precio de entrada. Es la
# horquilla que publican los proveedores (10 %); no se aplica a la salida, que nunca se cachea.
CACHE_DISCOUNT = 0.1

# (USD por 1M tokens de entrada, USD por 1M de salida). Emparejamiento por subcadena, gana la mas larga.
PRICES = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1": (2.00, 8.00),
    "o3-mini": (1.10, 4.40),
    "claude-opus": (15.00, 75.00),
    "claude-sonnet": (3.00, 15.00),
    "claude-haiku": (0.80, 4.00),
    "deepseek-reasoner": (0.55, 2.19),
    "deepseek-chat": (0.27, 1.10),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-pro": (1.25, 5.00),
    "mistral-large": (2.00, 6.00),
    "qwen-max": (1.60, 6.40),
}

# Un motor local no cobra por token: es un precio de 0 declarado, no un precio desconocido.
LOCAL_PREFIXES = ("lmstudio:", "ollama:", "local:", "fake:", "llamacpp:", "vllm:")


def price_of(model):
    """`(usd_in, usd_out)` por 1M tokens, o `None` cuando ese modelo no tiene precio conocido."""
    text = str(model or "").strip().lower()
    if not text:
        return None
    if text.startswith(LOCAL_PREFIXES):
        return (0.0, 0.0)
    best = None
    for key, price in PRICES.items():
        if key in text and (best is None or len(key) > len(best[0])):
            best = (key, price)
    return best[1] if best else None


def cost_of(model, usage):
    """`(usd, priced)` de una respuesta. Sin uso medido no hay precio: `unmeasured`, no `0`."""
    price = price_of(model)
    if price is None or usage is None:
        return 0.0, False
    prompt = int(getattr(usage, "prompt", 0) or 0)
    completion = int(getattr(usage, "completion", 0) or 0)
    if prompt <= 0 and completion <= 0:
        return 0.0, False
    cached = min(prompt, max(0, int(getattr(usage, "cached", 0) or 0)))
    billable = prompt - cached
    usd = (billable * price[0] + cached * price[0] * CACHE_DISCOUNT + completion * price[1])
    return usd / USD_PER_MILLION, True


@dataclass
class CostBudget:
    """Acumula el gasto del run y decide la parada dura. `observe` suma, `stop` corta."""

    limit_usd: float = 0.0
    spent: float = 0.0
    calls: int = 0
    priced_calls: int = 0
    unpriced_calls: int = 0
    cached_tokens: int = 0
    prompt_tokens: int = 0
    reason: str = ""
    history: list = field(default_factory=list)

    @property
    def bounded(self):
        return float(self.limit_usd or 0.0) > 0.0

    @property
    def ratio(self):
        """Gasto sobre techo, o `None` cuando no hay techo declarado (no es 0 %)."""
        return (self.spent / float(self.limit_usd)) if self.bounded else None

    @property
    def exceeded(self):
        return bool(self.bounded and self.spent >= float(self.limit_usd))

    def observe(self, usage, model=""):
        """Anota una respuesta. Devuelve el estado, como el medidor de tokens."""
        usd, priced = cost_of(model, usage)
        self.calls += 1
        self.cached_tokens += max(0, int(getattr(usage, "cached", 0) or 0))
        self.prompt_tokens += max(0, int(getattr(usage, "prompt", 0) or 0))
        if priced:
            self.spent += usd
            self.priced_calls += 1
        else:
            self.unpriced_calls += 1
        self.history.append({"model": str(model or ""), "usd": round(usd, 9), "priced": priced,
                             "cached": max(0, int(getattr(usage, "cached", 0) or 0))})
        return self.state()

    def stop(self, where=""):
        """La parada dura: se llama *antes* de cada llamada al modelo. `True` si hay que parar."""
        if not self.exceeded:
            return False
        if not self.reason:
            self.reason = ("presupuesto de coste agotado: %.6f >= %.6f USD%s"
                           % (self.spent, float(self.limit_usd),
                              (" en %s" % where) if where else ""))
        return True

    def state(self):
        return {"spent": round(self.spent, 9), "limit": float(self.limit_usd or 0.0),
                "ratio": self.ratio, "calls": self.calls, "priced_calls": self.priced_calls,
                "unpriced_calls": self.unpriced_calls, "cached_tokens": self.cached_tokens,
                "cache_ratio": (round(self.cached_tokens / float(self.prompt_tokens), 3)
                                if self.prompt_tokens else None),
                "exceeded": self.exceeded,
                "state": "unbounded" if not self.bounded else "bounded",
                "reason": self.reason}
