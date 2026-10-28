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
    # El Obrero repara dentro de un `git worktree` y solo vuelve si el gate sale verde alli. En una
    # raiz que no es git se degrada al comportamiento de siempre, declarandolo.
    "worktree_repairs": True,
    # Los cuatro motores de ahorro (skills dormidas, poda, mapa AST, reparacion aislada). Se puede
    # apagar para medir el modo tradicional en el mismo codigo: es lo que hace el benchmark A/B.
    "nexus_engines": True,
    # Techo de coste en USD para el run. 0.0 = sin tope declarado (no un tope de cero): un turno
    # autonomo con un modelo de nube gasta dinero, y esto es lo unico que lo corta.
    "cost_limit": 0.0,
    "max_steps": 14,
    "max_repairs": 3,
    "max_children": 3,
    "subagent_steps": 8,
    "subagent_depth": 1,
    "tool_workers": 4,
    "shell_timeout": 180,
    # Zero-trust command policy (`nexus_harness/policy.py`): read_only | standard | unrestricted.
    # `standard` refuses catastrophic and reckless commands; the opt-in is one line here, on purpose.
    "shell_policy": "standard",
    "test_command": None,
    # Comando de test POR PROYECTO (`{"AXV-AdrenalineX": "npm test"}`). Es lo que pide un proyecto y no
    # lo que pide la maquina: el mismo operador tiene Python, C# y npm en carpetas distintas.
    "project_tests": {},
    # La cola de importancia, en orden: el nombre tal como se llama la carpeta del workspace. La escribe
    # el tablero de arrastrar y soltar (`projects.save_order`) y la obedece el bucle autonomo.
    "project_order": [],
    # La escalera de modelos por rol: `{"worker": ["lmstudio:x", "deepseek:y"]}`. El primer peldano es
    # el spec del rol; los siguientes se prueban si el transporte cae o si el gate se pone rojo dos veces.
    "role_ladders": {},
    # Proveedores propios, mismo contrato que los de serie:
    # {"groq": {"wire": "openai", "base_url": "https://api.groq.com/openai/v1",
    #           "keys": ["GROQ_API_KEY"]}, "mi-vllm": {"wire": "openai",
    #           "base_url": "http://10.0.0.5:8000/v1", "local": true}}
    "providers": {},
    # El daemon autonomo: cada cuanto mira, cuantos ciclos por proyecto y cuantos proyectos por tick.
    "daemon_interval": 300,
    "daemon_iterations": 2,
    "daemon_scan": 3,
    # Avisos: {"discord_webhook": "$NEXUS_DISCORD_WEBHOOK",
    #          "telegram": {"token": "$TELEGRAM_TOKEN", "chat_id": "$TELEGRAM_CHAT"},
    #          "ntfy": "nexus-miusuario"}. Un valor con `$` se resuelve de la boveda.
    "notify": {},
    # El navegador nativo: sin cabeza por defecto (no abre ventanas mientras el daemon trabaja).
    "browser_headless": True,
    # Memoria por capas (SQLite+FTS5): el core viaja siempre con techo; el resto se consulta.
    "recall_enabled": True,
    "lang": "es",
    # El juez de la triada: `gate` (solo gate determinista, $0 y 0 ms), `fast` (una llamada corta) o
    # `adversary` (el mismo contrato con la instruccion de buscar el fallo). Un juez puede ser el mismo
    # modelo que el director, pero entonces no audita: el panel lo avisa y `gate` es la opcion honesta.
    "judge_mode": "fast",
    # El techo de hardware que el arnes puede usar: 75 % de la VRAM por defecto (el 25 % queda para
    # Windows, el juego o el coach en tiempo real), 50 % en modo ligero y 0 % = todo en nube.
    "hardware_ceiling": 75,
    # `ahorro` prefiere lo local dentro del techo ($0 por turno); `velocidad` prefiere la nube barata.
    "triad_bias": "ahorro",
    # Reaccion automatica: al cambiar el director entre local y nube, el obrero y el juez se reajustan.
    "triad_auto_adapt": True,
    # El obrero usa el MISMO modelo que el director cuando es local: un solo peso en VRAM = cero
    # recargas entre fases. Se guarda como intencion, y el panel aplica el spec al guardar.
    "worker_resident": False,
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
    worktree_repairs: bool = True
    nexus_engines: bool = True
    cost_limit: float = 0.0
    max_steps: int = 14
    max_repairs: int = 3
    max_children: int = 3
    subagent_steps: int = 8
    subagent_depth: int = 1
    tool_workers: int = 4
    shell_timeout: int = 180
    shell_policy: str = "standard"
    test_command: object = None
    project_tests: dict = field(default_factory=dict)
    project_order: list = field(default_factory=list)
    role_ladders: dict = field(default_factory=dict)
    providers: dict = field(default_factory=dict)
    daemon_interval: int = 300
    daemon_iterations: int = 2
    daemon_scan: int = 3
    notify: dict = field(default_factory=dict)
    browser_headless: bool = True
    recall_enabled: bool = True
    lang: str = "es"
    judge_mode: str = "fast"
    hardware_ceiling: int = 75
    triad_bias: str = "ahorro"
    triad_auto_adapt: bool = True
    worker_resident: bool = False
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
        # La cola de prioridad es una lista de nombres: si el fichero trae otra cosa (un texto, un
        # objeto), se descarta aqui y el tablero vuelve a su orden alfabetico en vez de reventar.
        if not isinstance(values.get("project_order", []), list):
            values.pop("project_order", None)
        config = cls(roles=roles, workspace=workspace,
                     default_root=Path(root) if root else Path.cwd(),
                     secrets=load_secrets(from_file.get("secrets_file")),
                     source=str(location) if from_file else "defaults", **values)
        # Los proveedores que esta maquina ya usa (Hermes, entorno, boveda) entran sin escribir nada:
        # `orca` deja de ser invisible y pasa a ser un vendor mas del selector y de los presets.
        from .provider_discovery import enrich
        enrich(config)
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
                "worktree_repairs": self.worktree_repairs, "nexus_engines": self.nexus_engines,
                "cost_limit": self.cost_limit, "max_steps": self.max_steps,
                "max_repairs": self.max_repairs, "test_command": self.test_command,
                "project_tests": dict(self.project_tests or {}),
                "project_order": list(self.project_order or []),
                "role_ladders": {role: list(specs) for role, specs in (self.role_ladders or {}).items()
                                 if isinstance(specs, list)},
                "providers": sorted((self.providers or {}).keys()),
                "daemon_interval": self.daemon_interval,
                "daemon_iterations": self.daemon_iterations,
                "daemon_scan": self.daemon_scan,
                "notify_channels": sorted((self.notify or {}).keys()),
                "browser_headless": self.browser_headless,
                "recall_enabled": self.recall_enabled,
                "max_children": self.max_children, "subagent_steps": self.subagent_steps,
                "tool_workers": self.tool_workers, "shell_policy": self.shell_policy,
                "lang": self.lang, "judge_mode": self.judge_mode,
                "hardware_ceiling": self.hardware_ceiling, "triad_bias": self.triad_bias,
                "triad_auto_adapt": self.triad_auto_adapt,
                "worker_resident": self.worker_resident, "source": self.source,
                "secret_names": sorted(self.secrets)}
