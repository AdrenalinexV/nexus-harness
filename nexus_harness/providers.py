"""The router: a role in, a provider out.

Six vendors, three wires. The table below is the whole configuration surface -- a new OpenAI-compatible
endpoint is one row, not a class -- and the only vendor-specific knowledge left is *where the key
lives* and *which wire it speaks*.

Nothing here retries, remembers or caches an answer: a router that caches replies is a router that
makes a deterministic test lie.
"""
import os
from dataclasses import dataclass

from .transports.anthropic import Anthropic
from .transports.ollama import Ollama
from .transports.openai_compat import OpenAICompatible

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


class SpecError(ValueError):
    """A role spec that cannot become a provider, named precisely enough to fix."""


def parse_spec(spec):
    """`provider:model` -> `(vendor, model)`. A bare model means the configured local default."""
    text = str(spec or "").strip()
    if not text:
        raise SpecError("empty model spec")
    if ":" in text:
        vendor, model = text.split(":", 1)
        vendor, model = vendor.strip().lower(), model.strip()
    else:
        vendor, model = "lmstudio", text
    if vendor not in VENDORS:
        raise SpecError("unknown provider %r (known: %s)" % (vendor, ", ".join(sorted(VENDORS))))
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

    def build(self, spec):
        vendor, model = parse_spec(spec)
        table = VENDORS[vendor]
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

    def role(self, role):
        """The transport for a role; a role swapped at runtime is picked up on the next call."""
        spec = self.config.role_spec(role)
        cached = self._cache.get(role)
        if cached is not None and cached[0] == spec:
            return cached[1]
        transport = self._transports.get(spec) or self.build(spec)
        self._cache[role] = (spec, transport)
        return transport

    def swap(self, role, spec):
        """Point a role at another model. Returns the new `RoleInfo`; raises `SpecError` if invalid."""
        parse_spec(spec)
        self.config.roles[role] = str(spec).strip()
        self._cache.pop(role, None)
        return self.info(role)

    def info(self, role):
        spec = self.config.role_spec(role)
        try:
            vendor, model = parse_spec(spec)
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
        cloud = [vendor for vendor, table in VENDORS.items()
                 if not table["local"] and self.config.secret(table["keys"])]
        return {"options": options, "local": local, "cloud_ready": sorted(cloud),
                "roles": self.describe()}


def available(router, role):
    """A role is usable when its provider is ready; the loop treats `False` as a hard stop, not a retry."""
    return router.info(role).ready


def env_override(role):
    """`NEXUS_HARNESS_ROLE_DIRECTOR=...` beats the file, because a shell is easier to change."""
    return os.environ.get("NEXUS_HARNESS_ROLE_%s" % role.upper())
