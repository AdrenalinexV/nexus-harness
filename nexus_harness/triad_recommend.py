"""La triada recomendada, sin que el operador tenga que elegir: la decide la maquina, no el gusto.

Un harness que pide tres modelos al arrancar esta pidiendo un examen de arquitectura a alguien que
solo quiere trabajar. Esta capa responde una pregunta -- **con lo que hay en ESTE ordenador y ESTAS
claves, que triada se sostiene** -- y la deja aplicada en un clic.

El orden no es preferencia, es fisica y coste:

1. **local**  -- si un peso cabe entero en la VRAM: 0 s de swapping y $0 por turno.
2. **hybrid** -- obrero local + juicio en la nube: cuando lo local no llega pero hay una clave.
3. **cloud**  -- todo en la nube: cuando no hay ningun modelo local vivo.

Si no hay proveedor listo se dice, y no se propone nada: una triada que falla en la primera llamada es
peor que un aviso honesto.

Vive aparte de `triad_presets` por la ley de 400: aquel decide QUE cabe, este decide QUE HACER.
"""
from . import hardware_probe, onboarding
from .triad_presets import PRESETS, plan


def recommend(config, state=None, hardware=None):
    """La tríada que ESTA máquina puede sostener hoy, sin que el operador elija nada.

    Devuelve `{id, title, roles, judge_mode, notes, ok, reason}`. `state` y `hardware` entran
    inyectados en las suites: sin eso, la recomendación solo se podría probar en un PC con GPU.
    """
    from .onboarding import status as probe_status
    state = state if state is not None else probe_status(config, root=config.default_root)
    hardware = hardware or hardware_probe.report()
    tried = []
    for name in ("local", "hybrid", "cloud"):
        result = plan(name, config, state, hardware)
        tried.append("%s: %s" % (name, "; ".join(result["notes"]) or "ok"))
        if result["ok"]:
            title = next((row[1] for row in PRESETS if row[0] == name), name)
            return {"id": name, "title": title, "roles": result["roles"],
                    "judge_mode": result["judge_mode"], "notes": result["notes"], "ok": True,
                    "reason": "recomendado por hardware y proveedores listos"}
    return {"id": "", "title": "sin tríada posible", "roles": {}, "judge_mode": "gate",
            "notes": tried, "ok": False,
            "reason": "no hay ningún proveedor listo: pon una clave en Seguridad o arranca LM Studio"}


def recommend_text(info):
    """La recomendación en una línea, para un CLI o una nota del panel."""
    if not info.get("ok"):
        return "sin tríada: %s" % info.get("reason")
    roles = ", ".join("%s=%s" % (role, spec) for role, spec in sorted(info["roles"].items()))
    return "%s (%s) · %s" % (info["id"], info.get("title") or "", roles)


def apply_specs(config, info):
    """Guarda la tríada recomendada sin cockpit (el CLI no tiene uno). Devuelve `(nota, ok)`."""
    if not info.get("ok"):
        return (info.get("reason") or "no hay tríada que aplicar", False)
    answer = onboarding.apply(config, {"roles": info["roles"]})
    saved = answer.get("saved", {}).get("roles") or {}
    numbers = onboarding.save_settings({"judge_mode": info.get("judge_mode") or "gate"})
    detail = ", ".join("%s=%s" % (role, spec) for role, spec in sorted(saved.items()))
    notes = list(info.get("notes") or []) + list(numbers[1] or [])
    return ("%s%s" % (detail or "sin cambios", (" · " + " · ".join(notes)) if notes else ""),
            bool(saved))


def apply_recommended(cockpit):
    """Un clic: calcula la recomendación de ESTA máquina y la guarda. Devuelve `(nota, ok)`."""
    info = recommend(cockpit.config)
    note, ok = apply_specs(cockpit.config, info)
    cockpit.reload_config()
    return ("recomendado %s: %s" % (info.get("id") or "?", note), ok)
