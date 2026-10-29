"""First run: what this machine actually has, and one screen to accept it.

A harness that opens with three empty role boxes asks the operator to do the machine's work. So this
module answers the only two questions worth asking on day one:

* **which local servers are alive**, and which models they really have downloaded -- probed over HTTP
  with a short timeout, never guessed from a config file that may describe another machine;
* **which project to govern**, with the governance files checked on disk instead of promised.

`apply()` then writes exactly three things: the role specs and project into `~/.nexus/harness.json`,
cloud keys into the DPAPI store (`vault.py`, write-only), and -- when the operator asks for it -- the
project's governance skeleton through `NexusProtocol`'s Auto-Spec generator. Every refusal is returned
as text next to what did land, because a silent half-configuration is worse than a loud no.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .platform import vault
from .config import CONFIG_FILE, DEFAULT_ROLES, HarnessConfig, WORKSPACE_DEFAULT
from .providers import VENDORS, SpecError, parse_spec

PROBES = {
    "lmstudio": ("http://127.0.0.1:1234/v1/models", "openai"),
    "ollama": ("http://127.0.0.1:11434/api/tags", "ollama"),
}
GOVERNANCE = (".ai/PROJECT_RULES.md", ".ai/CURRENT_SPEC.json")
WINDOWS_FLAGS = 0x08000000 if os.name == "nt" else 0


def _get(url, timeout=1.5):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _models(vendor, payload):
    rows = payload.get("data") if vendor == "lmstudio" else payload.get("models")
    names = []
    for row in rows or []:
        if isinstance(row, dict):
            names.append(str(row.get("id") or row.get("name") or "").strip())
    return sorted(name for name in names if name)


LOADED_PROBES = {"lmstudio": "http://127.0.0.1:1234/api/v0/models",
                 "ollama": "http://127.0.0.1:11434/api/ps"}


def _loaded(vendor, timeout=1.5):
    """Los ids que el servidor tiene CARGADOS ahora mismo (VRAM ocupada), no solo descargados.

    Es lo que separa "tengo 22 modelos" de "tengo 1 en VRAM": elegir un rol para un modelo que hay que
    cargar antes de responder cuesta decenas de segundos, y el panel tiene que poder decirlo. Se pide al
    endpoint que publica el estado (`/api/v0/models`, `/api/ps`); `/v1/models` no lo trae.
    """
    url = LOADED_PROBES.get(vendor)
    if not url:
        return []
    try:
        payload = _get(url, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return []
    rows = payload.get("data") if vendor == "lmstudio" else payload.get("models")
    found = []
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        state = str(row.get("state") or "").lower()
        name = str(row.get("id") or row.get("name") or row.get("model") or "").strip()
        if name and (state == "loaded" or row.get("size_vram")):
            found.append(name)
    return sorted(set(found))


def probe_local(timeout=1.5):
    """`{vendor: {url, ready, models, error}}` for every local server this harness knows."""
    found = {}
    for vendor, (url, _wire) in PROBES.items():
        try:
            payload = _get(url, timeout)
            found[vendor] = {"url": url, "ready": True, "models": _models(vendor, payload),
                             "loaded": _loaded(vendor, timeout), "error": ""}
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            found[vendor] = {"url": url, "ready": False, "models": [], "loaded": [],
                             "error": "%s: %s" % (type(exc).__name__, exc)}
    return found


def _governance(root):
    root = Path(root)
    present = {name: (root / name).is_file() for name in GOVERNANCE}
    return {"root": str(root), "complete": all(present.values()), "files": present}


def status(config=None, root=None, probe=True):
    """Everything the onboarding modal renders, measured now."""
    config = config or HarnessConfig.load(root=root)
    project = Path(root or config.default_root)
    roles = {}
    for role, spec in config.roles.items():
        try:
            vendor, model = parse_spec(spec)
            roles[role] = {"spec": spec, "vendor": vendor, "model": model,
                           "cloud": not VENDORS[vendor].get("local", False)}
        except SpecError as exc:
            roles[role] = {"spec": spec, "vendor": "", "model": "", "error": str(exc)}
    return {"ok": True, "local": probe_local() if probe else {},
            "roles": roles, "defaults": dict(DEFAULT_ROLES),
            "project": str(project), "exists": project.is_dir(),
            "workspace": str(config.workspace or WORKSPACE_DEFAULT),
            "governance": _governance(project),
            "keys": vault.names(), "config_file": str(CONFIG_FILE)}


def projects(workspace=None):
    """Directories the operator can pick from, without leaving the modal to type a path."""
    base = Path(workspace or WORKSPACE_DEFAULT)
    try:
        return sorted(name for name in os.listdir(base)
                      if (base / name).is_dir() and not name.startswith((".", "_")))
    except OSError:
        return []


def _write_config(changes):
    location = Path(CONFIG_FILE)
    current = {}
    if location.is_file():
        try:
            loaded = json.loads(location.read_text(encoding="utf-8"))
            current = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            current = {}
    current.update(changes)
    location.parent.mkdir(parents=True, exist_ok=True)
    location.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
    return str(location)


def _govern(root):
    """Ask NexusProtocol for its Auto-Spec generator; say so plainly when it is not there."""
    source = os.environ.get("NEXUS_PROTOCOL") or r"C:\Proyectos\NexusProtocol"
    if source not in sys.path:
        sys.path.insert(0, source)
    try:
        from nexus.gates import auto_spec
    except ImportError as exc:
        return {"ok": False, "reason": "NexusProtocol is not importable from %s (%s)" % (source, exc)}
    try:
        result = auto_spec.synthesize(str(root))
    except (OSError, ValueError) as exc:
        return {"ok": False, "reason": "auto-spec failed: %s" % exc}
    return {"ok": True, "spec": result.get("spec"), "sha256": result.get("sha256"),
            "test_command": result.get("test_command"), "language": result.get("language")}


def governance(root):
    """El Auto-Spec de un proyecto, por su nombre publico: `_govern` sigue siendo el que lo hace."""
    return _govern(root)


def save_settings(changes):
    """Guarda ajustes del arnes en `~/.nexus/harness.json`. Devuelve `(guardado, notas)`.

    Con lista blanca y con tipos, y no por burocracia: un ajuste guardado con el tipo equivocado no
    falla al guardar, falla al ARRANCAR -- y entonces el operador tiene un motor que no arranca y un
    fichero de configuracion que el no escribio. Lo que no este aqui (`secrets`, `secrets_file`) no lo
    escribe un formulario, punto.
    """
    from .platform import policy
    typed = {"budget_limit": int, "relay_threshold": float, "compact_threshold": float,
             "cost_limit": float, "max_steps": int, "max_repairs": int, "max_children": int,
             "subagent_steps": int, "subagent_depth": int, "tool_workers": int,
             "shell_timeout": int, "request_timeout": int, "max_tokens": int,
             "temperature": float, "lang": str, "workspace": str,
             "worker_resident": bool, "hardware_ceiling": int, "triad_auto_adapt": bool,
             "triad_bias": str, "ask_deadline": int, "consult_enabled": bool}
    out, saved, notes = {}, {}, []
    for name, value in (changes or {}).items():
        if name == "judge_mode":
            from .judge import MODES
            mode = str(value or "").strip().lower()
            if mode not in MODES:
                notes.append("judge_mode: %r no es uno de %s" % (value, ", ".join(MODES)))
                continue
            out[name] = saved[name] = mode
        elif name == "triad_bias":
            mode = str(value or "").strip().lower()
            if mode not in ("ahorro", "velocidad"):
                notes.append("triad_bias: %r no es ahorro ni velocidad" % (value,))
                continue
            out[name] = saved[name] = mode
        elif name == "hardware_ceiling":
            try:
                share = int(float(str(value).strip()))
            except (TypeError, ValueError):
                notes.append("hardware_ceiling: %r no es un porcentaje" % (value,))
                continue
            if share not in (0, 50, 75):
                notes.append("hardware_ceiling: %r no es 0, 50 ni 75" % (value,))
                continue
            out[name] = saved[name] = share
        elif name in ("worker_resident", "consult_enabled", "triad_auto_adapt"):
            out[name] = saved[name] = str(value).strip().lower() in ("1", "true", "yes", "on")
        elif name == "shell_policy":
            mode = str(value or "").strip().lower()
            if mode not in policy.MODES:
                notes.append("shell_policy: %r no es uno de %s" % (value, ", ".join(policy.MODES)))
                continue
            out[name] = saved[name] = mode
        elif name == "project_tests":
            if not isinstance(value, dict):
                notes.append("project_tests: se esperaba un objeto {proyecto: comando}")
                continue
            clean = {str(key).strip(): str(command).strip()
                     for key, command in value.items()
                     if str(key).strip() and str(command).strip()}
            out[name] = saved[name] = clean
        elif name == "test_command":
            out[name] = saved[name] = str(value or "").strip()
        elif name == "project_order":
            if not isinstance(value, (list, tuple)):
                notes.append("project_order: se esperaba una lista de nombres")
                continue
            clean_names = [str(item).strip() for item in value if str(item or "").strip()]
            out[name] = saved[name] = clean_names
        elif name in typed:
            try:
                out[name] = saved[name] = typed[name](str(value).strip())
            except (TypeError, ValueError):
                notes.append("%s: %r no vale como %s" % (name, value, typed[name].__name__))
        else:
            notes.append("%s: esta pantalla no cambia ese ajuste" % name)
    if out:
        saved["config_file"] = str(_write_config(out))
    return saved, notes


def apply(config, payload):
    """Accept what the operator chose. Returns what landed, what did not, and the new config."""
    payload = dict(payload or {})
    notes, saved = [], {}
    roles = payload.get("roles") or {}
    changes = {}
    if roles:
        checked = {}
        for role in ("director", "worker", "judge"):
            spec = str(roles.get(role) or "").strip()
            if not spec:
                continue
            try:
                parse_spec(spec)
            except SpecError as exc:
                notes.append("%s: %s" % (role, exc))
                continue
            checked[role] = spec
        if checked:
            changes["roles"] = checked
            saved["roles"] = checked
    project = str(payload.get("project") or "").strip()
    if project:
        candidate = Path(project)
        if not candidate.is_absolute():
            candidate = Path(payload.get("workspace") or WORKSPACE_DEFAULT) / project
        if not candidate.is_dir():
            notes.append("project: %s is not a directory" % candidate)
        else:
            changes["project"] = str(candidate)
            saved["project"] = str(candidate)
    if payload.get("test_command"):
        changes["test_command"] = str(payload["test_command"])
        saved["test_command"] = changes["test_command"]
    if changes:
        saved["config_file"] = _write_config(changes)

    keys = {str(name): str(value) for name, value in (payload.get("keys") or {}).items()
            if vault.looks_like_key(name) and str(value).strip()}
    if keys:
        stored = vault.save(keys)
        saved["keys"] = stored["names"]
        saved["sealed"] = stored["sealed"]
        if not stored["sealed"]:
            notes.append("DPAPI is unavailable: keys were written as plain JSON with owner-only "
                         "permissions")
    rejected = [name for name in (payload.get("keys") or {}) if not vault.looks_like_key(name)]
    if rejected:
        notes.append("ignored key names (need a *_API_KEY/*_TOKEN/*_SECRET suffix): %s"
                     % ", ".join(sorted(rejected)))

    if payload.get("governance") and saved.get("project"):
        saved["governance"] = _govern(saved["project"])
        if not saved["governance"].get("ok"):
            notes.append("governance: %s" % saved["governance"].get("reason"))

    fresh = HarnessConfig.load(root=saved.get("project") or (config.default_root if config else None))
    return {"ok": bool(saved), "saved": saved, "notes": notes,
            "status": status(fresh, root=fresh.default_root, probe=payload.get("probe", True))}


def selftest():
    """No network, no real config: the probe shape, the key rules and the governance report."""
    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    found = probe_local(timeout=0.05)
    check("both local vendors are probed", sorted(found), ["lmstudio", "ollama"])
    check("a dead port is not ready", all(not row["ready"] or row["models"] for row in found.values()),
          True)
    check("keys must look like keys", vault.looks_like_key("OPENAI_API_KEY"), True)
    check("names are not keys", vault.looks_like_key("project"), False)
    check("governance reports files", sorted(_governance(Path("."))) , ["complete", "files", "root"])
    return problems


HANDLERS = {}
