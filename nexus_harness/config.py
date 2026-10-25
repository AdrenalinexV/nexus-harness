"""Where the keys are, which model plays which role, and how big a session is.

Three layers, in the order they win: the environment, `~/.nexus/harness.json`, and the defaults in
this file. Keys are never written here -- they are read from the Nexus vault (`~/.nexus/secrets.json`)
or from the environment, exactly like the protocol does, so a key has one home on this machine.

A role is a spec string: `provider:model`. `lmstudio:kat-coder-...` is a local server; `deepseek:...`
is a cloud one. The model name is passed through untouched, because a model id is an identifier and
not something to normalise.
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

NEXUS_HOME = Path(os.environ.get("NEXUS_HOME") or (Path.home() / ".nexus"))
SECRETS_FILE = NEXUS_HOME / "secrets.json"
CONFIG_FILE = NEXUS_HOME / "harness.json"
WORKSPACE_DEFAULT = Path(os.environ.get("NEXUS_WORKSPACE") or r"C:\Proyectos")

# The roles are three different jobs, so they get three different models by default: a reasoning model
# plans, a coder edits, and the judge is deliberately NOT the coder -- a model grading its own work
# agrees with itself.
DEFAULT_ROLES = {
    "director": "lmstudio:qwen3.8-27b-heretic-abliterated-uncensored",
    "worker": "lmstudio:kat-coder-v2.5-dev-35b-a3b-abliterated-uncensored-philadelphia-class",
    "judge": "lmstudio:qwen3.8-27b-heretic-abliterated-uncensored",
}

DEFAULTS = {
    "port": 8765,
    "host": "127.0.0.1",
    "budget_limit": 60000,
    "relay_threshold": 0.70,
    # The ramp before the relay's cliff: the transcript is compacted in place once it passes this
    # share of the budget, so a long turn keeps its footing instead of arriving jadeando at 70 %.
    "compact_threshold": 0.55,
    "max_steps": 14,
    "max_repairs": 3,
    "max_children": 3,
    "subagent_steps": 8,
    "subagent_depth": 1,
    "tool_workers": 4,
    "shell_timeout": 180,
    "test_command": None,
    "lang": "es",
    "temperature": 0.2,
    "max_tokens": 4096,
    "request_timeout": 300,
}

ENV_PREFIX = "NEXUS_HARNESS_"


def load_secrets(path=None):
    """The vault's flat key/value file, plus the environment (which wins)."""
    secrets = {}
    location = Path(path) if path else SECRETS_FILE
    if location.is_file():
        try:
            data = json.loads(location.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if isinstance(data, dict):
            secrets = {str(key): str(value) for key, value in data.items()
                       if isinstance(value, (str, int, float))}
    for key, value in os.environ.items():
        if key.endswith("_API_KEY") or key.endswith("_TOKEN"):
            secrets[key] = value
    return secrets


def _coerce(name, value):
    default = DEFAULTS.get(name)
    if isinstance(default, bool):
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int):
        return int(value)
    if isinstance(default, float):
        return float(value)
    return value


@dataclass
class HarnessConfig:
    """Everything a run needs to be reproducible, minus the secrets themselves."""

    roles: dict = field(default_factory=lambda: dict(DEFAULT_ROLES))
    workspace: Path = WORKSPACE_DEFAULT
    default_root: Path = field(default_factory=Path.cwd)
    port: int = 8765
    host: str = "127.0.0.1"
    budget_limit: int = 60000
    relay_threshold: float = 0.70
    compact_threshold: float = 0.55
    max_steps: int = 14
    max_repairs: int = 3
    max_children: int = 3
    subagent_steps: int = 8
    subagent_depth: int = 1
    tool_workers: int = 4
    shell_timeout: int = 180
    test_command: object = None
    lang: str = "es"
    temperature: float = 0.2
    max_tokens: int = 4096
    request_timeout: int = 300
    secrets: dict = field(default_factory=dict)
    source: str = "defaults"

    @classmethod
    def load(cls, path=None, root=None):
        location = Path(path) if path else CONFIG_FILE
        from_file = {}
        if location.is_file():
            try:
                data = json.loads(location.read_text(encoding="utf-8"))
                from_file = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                from_file = {}
        values = {}
        for name in DEFAULTS:
            env_key = ENV_PREFIX + name.upper()
            if env_key in os.environ:
                values[name] = _coerce(name, os.environ[env_key])
            elif name in from_file and from_file[name] is not None:
                values[name] = _coerce(name, from_file[name])
        roles = dict(DEFAULT_ROLES)
        for role, spec in (from_file.get("roles") or {}).items():
            if isinstance(spec, str) and spec.strip():
                roles[str(role)] = spec.strip()
        if str(role_env := os.environ.get(ENV_PREFIX + "ROLES", "")).strip():
            for pair in role_env.split(","):
                if "=" in pair:
                    role, spec = pair.split("=", 1)
                    roles[role.strip()] = spec.strip()
        workspace = Path(from_file.get("workspace") or WORKSPACE_DEFAULT)
        config = cls(roles=roles, workspace=workspace,
                     default_root=Path(root) if root else Path.cwd(),
                     secrets=load_secrets(from_file.get("secrets_file")),
                     source=str(location) if from_file else "defaults", **values)
        return config

    def role_spec(self, role):
        return self.roles.get(role) or DEFAULT_ROLES.get(role, "")

    def secret(self, names):
        """The first non-empty secret among `names` (`None` when the key is not on this machine)."""
        for name in names:
            value = self.secrets.get(name)
            if value:
                return value
        return None

    def public(self):
        """The config as the cockpit shows it: every field, and not one secret."""
        return {"roles": dict(self.roles), "workspace": str(self.workspace),
                "port": self.port, "host": self.host, "budget_limit": self.budget_limit,
                "relay_threshold": self.relay_threshold, "compact_threshold": self.compact_threshold,
                "max_steps": self.max_steps,
                "max_repairs": self.max_repairs, "test_command": self.test_command,
                "max_children": self.max_children, "subagent_steps": self.subagent_steps,
                "tool_workers": self.tool_workers,
                "lang": self.lang, "source": self.source,
                "secret_names": sorted(self.secrets)}
