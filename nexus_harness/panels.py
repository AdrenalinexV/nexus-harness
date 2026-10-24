"""The four product surfaces, kept out of the cockpit so neither file has to grow a second job.

Each function is a thin, testable seam over a module that does the work:

* `onboarding_*` -> `onboarding.py` (probe, apply, governance)
* `mcp_*` -> `mcp_client.py` (servers, tools, reload)
* `skills_*` -> NexusProtocol's `nexus.skills.editor` (read/validate/save a SKILL.md)
* `daemon_*` -> NexusProtocol's `nexus.hive.daemon_control` (the mobile bridge ON/OFF)

The pattern is the same in all four: **the UI gets facts, never secrets**, every failure comes back as
text the operator can act on, and nothing here raises into the HTTP handler.
"""
import os
import sys
from pathlib import Path

from . import onboarding, vault

NEXUS_SOURCE = Path(os.environ.get("NEXUS_PROTOCOL") or r"C:\Proyectos\NexusProtocol")


def _protocol(module_path):
    """Import a module from NexusProtocol, or `None` with the reason in the caller's text."""
    if str(NEXUS_SOURCE) not in sys.path:
        sys.path.insert(0, str(NEXUS_SOURCE))
    try:
        module = __import__(module_path, fromlist=["*"])
        return module
    except ImportError:
        return None


# -- onboarding ------------------------------------------------------------------------------
def onboarding_status(cockpit):
    payload = onboarding.status(cockpit.config, root=cockpit.root)
    payload["projects"] = onboarding.projects(cockpit.config.workspace)
    payload["mcp"] = mcp_status(cockpit)
    return payload


def onboarding_apply(cockpit, payload):
    result = onboarding.apply(cockpit.config, payload)
    if result.get("ok") and (result.get("saved") or {}).get("config_file"):
        cockpit.reload_config()
    return result


# -- MCP -------------------------------------------------------------------------------------
def mcp_status(cockpit):
    """The panel asks for connectors, so the connectors are what it gets: start them if nobody has.

    Deferring start-up to the first chat meant the sidebar showed "sin conectores" on a machine whose
    connectors were fine, which is a lie the operator cannot debug.
    """
    manager = getattr(cockpit, "mcp_manager", None)
    if manager is None:
        manager = cockpit.mcp()
    return manager.describe()


def mcp_reload(cockpit):
    manager = getattr(cockpit, "mcp_manager", None)
    if manager is None:
        return {"ok": False, "reason": "MCP is not enabled in this session"}
    described = manager.reload()
    registry = getattr(getattr(cockpit, "chat", None), "registry", None)
    if registry is not None:
        registry.refresh_mcp()
    return dict(described, ok=True)


# -- skills ----------------------------------------------------------------------------------
def _editor():
    return _protocol("nexus.skills.editor")


def skills_list(cockpit):
    editor = _editor()
    if editor is None:
        return {"ok": False, "reason": "NexusProtocol is not importable", "skills": []}
    rows = editor.list_skills(str(NEXUS_SOURCE))
    last = getattr(getattr(cockpit, "chat", None), "last_turn", None)
    live = set(getattr(last, "skills", None) or [])
    for row in rows:
        row["in_ram"] = row["name"] in live
    return {"ok": True, "skills": rows, "root": str(NEXUS_SOURCE)}


def skills_read(cockpit, name):
    editor = _editor()
    if editor is None:
        return {"ok": False, "reason": "NexusProtocol is not importable"}
    try:
        return editor.read_skill(str(name or ""), str(NEXUS_SOURCE))
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}


def skills_save(cockpit, name, text):
    editor = _editor()
    if editor is None:
        return {"ok": False, "reason": "NexusProtocol is not importable"}
    try:
        result = editor.save_skill(str(name or ""), str(text or ""), str(NEXUS_SOURCE))
    except ValueError as exc:
        return {"ok": False, "reason": str(exc)}
    cockpit.bus.emit("skills.saved", "%s (%s)" % (name, result.get("sha256", "")[:12]))
    return dict(result, ok=True)


# -- mobile bridge daemon --------------------------------------------------------------------
def _daemon():
    return _protocol("nexus.hive.daemon_control")


def daemon_status(cockpit):
    module = _daemon()
    if module is None:
        return {"ok": False, "running": False, "reason": "NexusProtocol is not importable"}
    rows = module.status(str(cockpit.root))
    rows["ok"] = True
    rows["toggle"] = "detener" if rows.get("running") else "arrancar"
    return rows


def daemon_toggle(cockpit, provider="telegram"):
    module = _daemon()
    if module is None:
        return {"ok": False, "running": False, "reason": "NexusProtocol is not importable"}
    result = module.toggle(str(cockpit.root), provider=provider or "telegram")
    cockpit.bus.emit("daemon.toggle", "ON" if result.get("running") else "OFF",
                     running=result.get("running"), pid=result.get("pid"))
    return result


def daemon_stop(cockpit):
    module = _daemon()
    if module is None:
        return {"ok": False, "running": False, "reason": "NexusProtocol is not importable"}
    result = module.stop(str(cockpit.root))
    cockpit.bus.emit("daemon.toggle", "OFF", running=False)
    return result


def keys_state():
    """Only names: the modal must be able to say what is saved without ever showing a value."""
    return {"names": vault.names()}
