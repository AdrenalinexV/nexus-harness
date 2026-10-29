"""The router: a role in, a provider out.

Six vendors, three wires. The table below is the whole configuration surface -- a new OpenAI-compatible
endpoint is one row, not a class -- and the only vendor-specific knowledge left is *where the key
lives* and *which wire it speaks*.

Nothing here retries, remembers or caches an answer: a router that caches replies is a router that
makes a deterministic test lie.
"""
import os
from dataclasses import dataclass

from .portfolio import FailoverTransport, Portfolio
from ..transports.anthropic import Anthropic
from ..transports.ollama import Ollama
from ..transports.openai_compat import OpenAICompatible

VENDORS = {
    "lmstudio": {"wire": "openai", "base_url": "http://127.0.0.1:1234/v1",
                 "keys": ("LMSTUDIO_API_KEY",), "local": True},
    "ollama": {"wire": "ollama", "base_url": "http://127.0.0.1:11434",
               "keys": ("OLLAMA_API_KEY",), "local": True},
    "openai": {"wire": "openai", "base_url": "https://api.openai.com/v1",
               "keys": ("OPENAI_API_KEY",), "local": False},
    "deepseek": {"wire": "openai", "base_url": "https://api.deepseek.com/v1",
                 "keys": ("DEEPSEEK_API_KEY", "OPENAI_API_KEY"), "local": False},
    "openrouter": {"wire": "openai", "base_url": "https://openrouter.ai/api/v1",
                   "keys": ("OPENROUTER_API_KEY",), "local": False,
                   "headers": {"HTTP-Referer": "https://nexus.local",
                               "X-Title": "Nexus-Harness"}},
    "anthropic": {"wire": "anthropic", "base_url": "https://api.anthropic.com",
                  "keys": ("ANTHROPIC_API_KEY",), "local": False},
}

ROLES = ("director", "worker", "judge")
WIRES = ("openai", "anthropic", "ollama")


class SpecError(ValueError):
    """A role spec that cannot become a provider, named precisely enough to fix."""


def merged_vendors(config):
    """Los proveedores de serie MAS los que declare el operador. Devuelve `(tabla, problemas)`.

    Un proveedor propio mal declarado no puede tumbar el arnes entero: se descarta, se apunta el motivo
    y los demas siguen funcionando. La libertad de proveedor es una tabla, no un `if` por marca.
    """
    table = {name: dict(row) for name, row in VENDORS.items()}
    problems = []
    custom = getattr(config, "providers", None) or {}
    if not isinstance(custom, dict):
        return table, ["`providers` no es un objeto"]
    for name, row in custom.items():
        label = str(name or "").strip().lower()
        try:
            if not label:
                raise SpecError("proveedor sin nombre")
            if not isinstance(row, dict) or not str(row.get("base_url") or "").strip():
                raise SpecError("falta base_url")
            wire = str(row.get("wire") or "openai").strip().lower()
            if wire not in WIRES:
                raise SpecError("wire %r no es uno de %s" % (wire, ", ".join(WIRES)))
            keys = row.get("keys") or ["%s_API_KEY" % label.upper().replace("-", "_")]
            table[label] = {"wire": wire, "base_url": str(row["base_url"]).strip(),
                            "keys": tuple(str(key) for key in keys),
                            "local": bool(row.get("local")), "headers": row.get("headers") or {}}
        except SpecError as exc:
            problems.append("%s: %s" % (label or "?", exc))
    return table, problems


def parse_spec(spec, vendors=None):
    """`provider:modelo` -> `(vendor, model)`. Un modelo suelto usa el local por defecto."""
    table = vendors or VENDORS
    text = str(spec or "").strip()
    if not text:
        raise SpecError("empty model spec")
    if ":" in text:
        vendor, model = text.split(":", 1)
        vendor, model = vendor.strip().lower(), model.strip()
    else:
        vendor, model = "lmstudio", text
    if vendor not in table:
        raise SpecError("unknown provider %r (known: %s)" % (vendor, ", ".join(sorted(table))))
    if not model:
        raise SpecError("spec %r names a provider but no model" % text)
    return vendor, model


@dataclass
class RoleInfo:
    role: str
    spec: str
    vendor: str
    model: str
    ready: bool
    why_not_ready: str


class Router:
    """Resolves a role to a live transport, once, and reports why it cannot."""

    def __init__(self, config, transports=None):
        self.config = config
        self._transports = dict(transports or {})
        self._cache = {}
        self._by_spec = {}
        self._windows = {}
        # La tabla de proveedores: los de serie + los que declare el operador en `providers`.
        self.vendors, self.vendor_problems = merged_vendors(config)
        # La cartera de cada rol: la escalera declarada en `role_ladders`, o el spec unico de siempre.
        self.portfolio = Portfolio(config)

    def build(self, spec):
        vendor, model = parse_spec(spec, self.vendors)
        table = self.vendors[vendor]
        api_key = self.config.secret(table["keys"]) or ""

        if table["wire"] == "ollama":
            return Ollama(model, base_url=table["base_url"], api_key=api_key, name=vendor,
                          timeout=self.config.request_timeout,
                          extra_headers=table.get("headers"))
        if table["wire"] == "anthropic":
            return Anthropic(model, base_url=table["base_url"], api_key=api_key, name=vendor,
                             timeout=self.config.request_timeout,
                             extra_headers=table.get("headers"))
        return OpenAICompatible(model, base_url=table["base_url"], api_key=api_key, name=vendor,
                                timeout=self.config.request_timeout,
                                extra_headers=table.get("headers"),
                                requires_key=not table["local"])

    def for_spec(self, spec):
        """El transporte de un spec concreto, cacheado: es lo que la cartera usa por peldano."""
        text = str(spec or "").strip()
        cached = self._by_spec.get(text) or self._transports.get(text)
        if cached is None:
            cached = self.build(text)
            self._by_spec[text] = cached
        return cached

    def role(self, role):
        """Transporte del rol con su cartera detras: primario y peldanos siguientes, en orden."""
        spec = self.config.role_spec(role)
        ladder = self.portfolio.after(role, spec)
        key = (spec, tuple(ladder))
        cached = self._cache.get(role)
        if cached is not None and cached[0] == key:
            return cached[1]
        transport = FailoverTransport(self, role, ladder)
        self._cache[role] = (key, transport)
        return transport

    def swap(self, role, spec):
        """Point a role at another model. Returns the new `RoleInfo`; raises `SpecError` if invalid."""
        parse_spec(spec, self.vendors)
        self.config.roles[role] = str(spec).strip()
        self._cache.pop(role, None)
        return self.info(role)

    def escalate(self, role, budget=None, reason=""):
        """Sube un peldano de la cartera si hay adonde y presupuesto. Devuelve el `Move`."""
        move = self.portfolio.escalate(role, budget=budget, reason=reason)
        if move.ok:
            self.config.roles[role] = move.spec
            self._cache.pop(role, None)
        return move

    def ladder(self, role):
        return self.portfolio.ladder(role)

    def window(self, role, timeout=4):
        """La ventana REAL del motor de ese rol, cacheada por spec.

        La cache importa: sin ella cada paso del turno preguntaria al servidor, y un modelo que se
        acaba de cargar no cambiaria de ventana a mitad de turno. Un cambio de modelo invalida la
        entrada porque la clave es el spec.
        """
        try:
            spec = self.config.role_spec(role)
        except Exception:  # noqa: BLE001 -- sin spec no hay ventana, y eso no es un fallo del turno
            return 0
        cached = self._windows.get(role)
        if cached is not None and cached[0] == spec:
            return cached[1]
        try:
            found = int(self.role(role).window(timeout=timeout) or 0)
        except Exception:  # noqa: BLE001
            found = 0
        self._windows[role] = (spec, found)
        return found

    def info(self, role):
        spec = self.config.role_spec(role)
        try:
            vendor, model = parse_spec(spec, self.vendors)
            transport = self.role(role)
            return RoleInfo(role, spec, vendor, model, transport.ready, transport.why_not_ready)
        except SpecError as exc:
            return RoleInfo(role, spec, "", "", False, str(exc))

    def describe(self):
        return {role: self.info(role).__dict__ for role in ROLES}

    def probe(self):
        """Which models the local servers actually offer right now. Empty is a valid answer."""
        found = {"lmstudio": [], "ollama": []}
        for vendor in found:
            try:
                transport = self.build("%s:probe" % vendor)
            except SpecError:
                continue
            found[vendor] = transport.models()
        return found

    def catalog(self):
        """For the cockpit's model picker: local ids labelled with their vendor, plus role defaults."""
        local = self.probe()
        options = ["%s:%s" % (vendor, model)
                   for vendor, models in local.items() for model in models]
        for role in ROLES:
            spec = self.config.role_spec(role)
            if spec and spec not in options:
                options.append(spec)
        cloud = [vendor for vendor, table in self.vendors.items()
                 if not table["local"] and self.config.secret(table["keys"])]
        return {"options": options, "local": local, "cloud_ready": sorted(cloud),
                "roles": self.describe()}


def available(router, role):
    """A role is usable when its provider is ready; the loop treats `False` as a hard stop, not a retry."""
    return router.info(role).ready


def env_override(role):
    """`NEXUS_HARNESS_ROLE_DIRECTOR=...` beats the file, because a shell is easier to change."""
    return os.environ.get("NEXUS_HARNESS_ROLE_%s" % role.upper())
