"""Qué modelo poner en cada rol, con la razón y sin inventar: solo lo que esta máquina tiene o puede pedir.

La pantalla de modelos ya listaba catálogos, pero el operador tenía que decidir entre 22 ids de LM Studio,
24 de Ollama y una escalera de nube. Esto no elige por él: **ordena** lo disponible y dice por qué, y
deja el clic. Dos reglas que lo mantienen honesto:

* un modelo local que no cabe en la VRAM declarada no se recomienda (se lista igual, con su motivo);
* el Juez recomendado nunca es el mismo modelo que el Director: juzgarse a sí mismo no es auditar.
"""
from . import triad_presets

CODER = ("cod", "coder", "code", "starcoder", "qwen2.5-coder", "kat-coder")
SMALL_GB = 8.0


def _cloud_key(config, vendor):
    table = triad_presets.vendors_table(config).get(vendor) or {}
    return bool(config.secret(table.get("keys") or ()))


def _vram(hardware):
    total = sum(int(gpu.get("total_mb") or 0)
                for gpu in (hardware or {}).get("gpus") or ()) / 1024.0
    return total * getattr(triad_presets, "VRAM_SHARE", 0.75)


def _local_rows(role, state, hardware, director_spec=""):
    """Cada local con dos preguntas: ¿cabe solo? ¿cabe JUNTO al director? La segunda es la que duele."""
    rows = []
    vram = _vram(hardware)
    director_weight = (triad_presets.weight_gb(triad_presets.split_spec(director_spec)[1])
                       if director_spec and triad_presets.split_spec(director_spec)[0]
                       in triad_presets.LOCAL else 0.0)
    for vendor, info in ((state or {}).get("local") or {}).items():
        for model in info.get("models") or []:
            size = triad_presets.weight_gb(model)
            fits = triad_presets.fits(model, hardware)
            together = bool(size) and (not vram or size + director_weight <= vram)
            name = model.lower()
            score, why = 0.0, []
            if together:
                score += 6
                why.append("cabe junto al Director" if director_weight else "cabe en la VRAM")
            elif fits:
                score += 1
                why.append("cabe solo: con el Director obliga a recargar (±32 s por fase)")
            else:
                score -= 6
                why.append("no cabe en la VRAM (recarga entre fases)" if size else "no medible")
            if role == "worker" and any(mark in name for mark in CODER):
                score += 4
                why.append("especializado en código")
            if role == "judge" and size and size <= SMALL_GB:
                score += 2
                why.append("pequeño y rápido")
            if role == "director" and size:
                score += min(4.0, size / 8.0)
                why.append("cuanto más grande, mejor planifica")
            rows.append({"spec": "%s:%s" % (vendor, model), "kind": "local", "size": size,
                         "ok": bool(fits), "why": " · ".join(why), "score": score})
    return rows


def _cloud_rows(role, config, director_spec):
    rows = []
    director_vendor = triad_presets.split_spec(director_spec)[0] if director_spec else ""
    for vendor, model in triad_presets.LADDERS.get(role, ()):
        has_key = _cloud_key(config, vendor)
        score, why = (5.0 if has_key else -5.0), []
        why.append("clave en la bóveda" if has_key else "falta la clave (Seguridad)")
        if role == "judge" and vendor and vendor != director_vendor:
            score += 4
            why.append("familia distinta a la del Director: audita de verdad")
        if role == "judge" and vendor == director_vendor:
            score -= 3
            why.append("misma familia que el Director: auditoría floja")
        if role == "worker":
            score += 1 if "cod" in model.lower() else 0
        rows.append({"spec": "%s:%s" % (vendor, model), "kind": "cloud", "size": 0.0,
                     "ok": has_key, "why": " · ".join(why), "score": score})
    return rows


def options(role, state, hardware, config, director_spec=""):
    """Las opciones ordenadas para un rol. `ok` = se puede aplicar ahora mismo con lo que hay."""
    rows = _local_rows(role, state, hardware, director_spec) + _cloud_rows(role, config,
                                                                               director_spec)
    director_vendor = triad_presets.split_spec(director_spec)[0] if director_spec else ""
    if role == "worker" and director_vendor in triad_presets.LOCAL:
        # La respuesta a "dos pesos no caben": el obrero usa el que ya está cargado. Cero GB extra.
        rows.append({"spec": "resident", "kind": "local", "size": 0.0, "ok": True, "score": 7.5,
                     "why": "0 GB extra: repara con el peso del Director, sin recargar entre fases"})
    if role == "judge":
        rows.append({"spec": "gate", "kind": "gate", "size": 0.0, "ok": True, "score": 5.5,
                     "why": "gate local, $0 y 0 ms: no hay auditoría de modelo, y se dice"})
    rows.sort(key=lambda row: (-row["score"], row["spec"]))
    return rows[:5]


def apply(cockpit, role, spec):
    """Aplica una opción al rol. `gate` no es un modelo: es el modo del Juez sin llamada."""
    role = str(role or "").strip()
    spec = str(spec or "").strip()
    if role not in ("director", "worker", "judge"):
        return ("rol %r no válido (director, worker o judge)" % role, False)
    if spec == "resident":
        if role != "worker":
            return ("`resident` solo vale para el Obrero", False)
        saved = onboarding_save({"worker_resident": True})
        cockpit.reload_config()
        return ("obrero = modelo residente del Director (%s)" % ("guardado" if saved else "falló"),
                bool(saved))
    if spec == "gate":
        if role != "judge":
            return ("`gate` solo vale para el Juez", False)
        answer = onboarding_save({"judge_mode": "gate"})
        cockpit.reload_config()
        return ("juez = gate determinista (%s)" % ("guardado" if answer else "no se pudo guardar"),
                bool(answer))
    try:
        info = cockpit.swap(role, spec)
    except Exception as exc:  # noqa: BLE001 -- un spec inválido se declara, no tumba la pantalla
        return ("%s no se pudo aplicar: %s: %s" % (spec, type(exc).__name__, exc), False)
    cockpit.reload_config()
    ready = bool(getattr(info, "ready", False))
    return ("%s = %s%s" % (role, spec, "" if ready else " (sin clave todavía)"), True)


def onboarding_save(changes):
    from . import onboarding
    saved = onboarding.save_settings(changes)[0]
    return bool(saved)
