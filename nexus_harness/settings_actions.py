"""Las acciones de la pantalla de configuracion: lo que no es «guardar un formulario».

Vive aparte de `settings.py` por la ley de 400 lineas: alli se pinta la pantalla y se guarda lo que
manda un panel; aqui se ejecutan los botones que hacen algo mas (optimizar la triada, detectar
modelos, recargar conectores, arrancar el puente, forjar una skill o pasar el doctor).

El contrato es el de siempre: devuelven `(nota, ok, seccion)` y nunca levantan hacia el handler HTTP.
"""
import json
import subprocess
import sys

from .platform import vault
from . import gov, panels
from . import settings_projects, settings_skills, settings_tools, settings_vps

# -- acciones ------------------------------------------------------------------------------------
def action(cockpit, body):
    """Las acciones que no son «guardar». Devuelve `(nota, ok, seccion)`."""
    what = str(body.get("what") or "")
    section = str(body.get("section") or "modelos")
    if what.startswith("vps_"):
        return settings_vps.action(cockpit, body)
    if what.startswith("consult_"):
        from . import settings_autonomy
        return settings_autonomy.action(cockpit, body)
    if what == "about_probe":
        from . import settings_about
        return settings_about.action(cockpit, body)
    if what in ("auto_spec", "project_new", "project_move", "autonomy_start", "autonomy_stop"):
        # Las acciones del panel de proyectos las ejecuta su dueno, con su propia validacion.
        return settings_projects.action(cockpit, body)
    if what == "memory_add":
        answer = cockpit.memory_add(body.get("text"))
        return ("memoria: %s" % ("añadido" if answer.get("ok") else answer.get("reason")),
                bool(answer.get("ok")), "memoria")
    if what == "memory_remove":
        answer = cockpit.memory_remove(body.get("entry"))
        return ("memoria: %s" % ("quitado" if answer.get("ok") else "no estaba"),
                bool(answer.get("ok")), "memoria")
    if what == "mcp_reload":
        answer = panels.mcp_reload(cockpit)
        return ("conectores: %s tools" % answer.get("tools"), bool(answer.get("ok")), "mcp")
    if what == "bridge":
        provider = str(body.get("provider") or "telegram")
        answer = (panels.daemon_toggle(cockpit, provider) if str(body.get("on") or "") == "on"
                  else panels.daemon_stop(cockpit))
        return ("puente: %s" % ("ON" if answer.get("running") else "OFF"),
                bool(answer.get("ok", True)), "puente")
    if what == "optimize":
        note, ok = triad_balance.apply(cockpit)
        return (note, ok, "modelos")
    if what == "recommend":
        from . import triad_recommend
        note, ok = triad_recommend.apply_recommended(cockpit)
        return (note, ok, "modelos")
    if what == "preset":
        from . import triad_presets
        note, ok = triad_presets.apply(cockpit, str(body.get("preset") or ""))
        return (note, ok, "modelos")
    if what == "role_spec":
        from . import model_guide
        note, ok = model_guide.apply(cockpit, body.get("role"), body.get("spec"))
        return (note, ok, "modelos")
    if what == "detect_models":
        found = onboarding.probe_local()
        live = {vendor: len(row.get("models") or [])
                for vendor, row in found.items() if row.get("ready")}
        detail = ", ".join("%s: %d" % (name, count) for name, count in sorted(live.items()))
        return ("detectados %d modelos (%s)" % (sum(live.values()), detail or "ningún servidor respondió"),
                bool(live), "modelos")
    if what == "skill_mode":
        name = str(body.get("name") or "").strip()
        mode = str(body.get("mode") or "").strip()
        if not name or mode not in ("always", "auto", "off"):
            return ("modo inválido para %r" % name, False, "skills")
        if name not in settings_skills._routable_names():
            return ("%s no está en el paquete de routing: no viaja con los turnos" % name,
                    False, "skills")
        always, off = settings_skills._modes()
        always.discard(name)
        off.discard(name)
        if mode == "always":
            always.add(name)
        elif mode == "off":
            off.add(name)
        saved, reason = gov.save_skill_modes(always, off)
        return ("%s → %s%s" % (name, mode, "" if saved else " (no se pudo: %s)" % reason),
                saved, "skills")
    if what in ("mcp_add", "mcp_delete", "mcp_toggle"):
        ok, note = panels.mcp_write(cockpit, what[4:], body)
        return (note, ok, "mcp")
    if what == "key_delete":
        name = str(body.get("key_name") or "").strip()
        if not vault.looks_like_key(name):
            return ("%r no es una clave de la bóveda" % name, False, "seguridad")
        answer = vault.save({name: ""})
        left = answer.get("names") or []
        return ("bóveda: %s borrada (%d claves quedan)" % (name, len(left)),
                name not in left, "seguridad")
    if what == "save_skill":
        answer = panels.skills_save(cockpit, body.get("name"), body.get("text"))
        return ("SKILL.md de %s: %s" % (body.get("name"),
                                        "guardado" if answer.get("ok") else answer.get("reason")),
                bool(answer.get("ok")), "skills")
    if what == "architect":
        return _architect(cockpit, body)
    if what == "doctor":
        return _doctor()
    return ("acción desconocida: %s" % what, False, section)


def _architect(cockpit, body):
    message = str(body.get("message") or "").strip()
    if len(message) < 3:
        return ("escribe qué skill falta o qué mejorar", False, "skills")
    ok, answer = gov.action("/api/architect", {"message": message,
                                               "github": bool(body.get("github"))})
    text = ""
    if isinstance(answer, dict):
        text = str(answer.get("reply") or answer.get("answer") or answer.get("text") or "")
        if not text:
            text = json.dumps(answer, indent=2, ensure_ascii=False)[:4000]
    else:
        text = str(answer)[:4000]
    settings_tools.LAST["architect"] = text or "(sin respuesta)"
    return ("arquitecto: %s" % ("contestó" if ok else "no pudo contestar"), bool(ok), "skills")


def _doctor():
    """Pasa el doctor del protocolo y guarda su cola para el panel. Es lento (~1 min) y se dice."""
    command = [sys.executable, str(gov.PROTOCOL / "nexus" / "cli.py"), "doctor"]
    try:
        done = subprocess.run(command, capture_output=True, text=True, errors="replace",
                              timeout=300, cwd=str(gov.PROTOCOL))
    except (OSError, subprocess.SubprocessError) as exc:
        return ("el doctor no se pudo ejecutar: %s" % exc, False, "stats")
    tail = ((done.stdout or "") + (done.stderr or "")).strip().splitlines()[-14:]
    settings_tools.LAST["doctor"] = "\n".join(tail)
    green = done.returncode == 0 and "green" in (done.stdout or "").lower()
    return ("doctor: %s" % ("verde" if green else "revisar"), green, "stats")
