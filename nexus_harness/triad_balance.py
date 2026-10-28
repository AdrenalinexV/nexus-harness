"""El reparto de la GPU: cuánto puede usar el arnés, quién se queda qué y sin recargas.

El problema que resuelve, medido en esta máquina: 15,9 GB de VRAM y tres roles que sumaban 34,9 GB de
pesos locales. La cabina decía «elige tú»; esto decide con una regla explícita y la deja escrita.

**El techo manda.** `ceiling` es el porcentaje de VRAM que el arnés puede tocar (75 % por defecto: el
25 % restante es de Windows, del juego o del coach en tiempo real). De ese presupuesto `B`:

* **75 % para el peso pesado** (director y obrero comparten UN modelo residente: 0 s de swapping),
* **25 % para un juez micro distinto**, que es lo único que hace que la auditoría cruzada sea real con
  dos pesos en VRAM a la vez,
* y si el micro no cabe, el juez baja a `gate` (0 GB) en vez de fingir que audita.

**Se adapta a dónde pongas el director.** Con el director en nube, la GPU está libre para obrero y juez
locales ($0 por turno, auditoría cruzada nube contra local). Con el director local y pesado, el juez se
va a nube flash o a otro peso pequeño, y el obrero se pega al residente para no recargar nunca.

Nada de esto pide un modelo nuevo: elige entre los que el operador YA tiene instalados y los proveedores
que la máquina YA usa (`provider_discovery`). Si no hay nada que cumpla, lo dice; no inventa un id.
"""
from . import triad_presets

CEILINGS = (75, 50, 0)
HEAVY_SHARE = 0.75
LIGHT_SHARE = 0.25
MICRO_MAX_GB = 4.5      # el techo de un «micro auditor»: 7B q4 son ~4,2 GB
LOCAL = triad_presets.LOCAL_SET


def budget(hardware, ceiling=75):
    """`B` y su reparto: VRAM total, presupuesto del arnés, peso pesado y juez, reserva del PC."""
    vram = round(sum(int(gpu.get("total_mb") or 0) for gpu in (hardware or {}).get("gpus") or ()) / 1024.0, 1)
    try:
        share = max(0, min(100, int(ceiling)))
    except (TypeError, ValueError):
        share = 75
    harness = round(vram * share / 100.0, 1)
    return {"vram_gb": vram, "ceiling": share, "harness_gb": harness,
            "heavy_gb": round(harness * HEAVY_SHARE, 1),
            "light_gb": round(harness * LIGHT_SHARE, 1),
            "reserve_gb": round(vram - harness, 1)}


def installed(state):
    """Los modelos locales instalados, con el proveedor que los sirve."""
    rows = []
    for vendor, row in ((state or {}).get("local") or {}).items():
        if not row.get("ready"):
            continue
        for model in row.get("models") or ():
            if triad_presets.weight_gb(model):
                rows.append((vendor, model, triad_presets.weight_gb(model)))
    return rows


def pick_heavy(rows, max_gb, exclude=()):
    """El mayor modelo local que cabe en el presupuesto pesado. `(vendor, modelo, gb)` o vacío."""
    fits = [row for row in rows if row[2] <= max_gb and row[1] not in exclude]
    return max(fits, key=lambda row: row[2]) if fits else ("", "", 0.0)


def pick_light(rows, max_gb, exclude=()):
    """El juez: el mayor que cabe en su cuota Y sigue siendo un micro (<= 7B)."""
    fits = [row for row in rows if row[2] <= max_gb and row[1] not in exclude
            and triad_presets.params_b(row[1]) and triad_presets.params_b(row[1]) <= 8]
    return max(fits, key=lambda row: row[2]) if fits else ("", "", 0.0)


def cloud_roles(ready):
    """`(worker, judge)` de nube, con el juez en otro proveedor que el director si se puede."""
    ready = {name for name in ready if name not in LOCAL}
    worker = triad_presets.pick("worker", ready)
    judge = triad_presets.pick("judge", ready - {worker[0]} if worker[0] else ready)
    if not judge[0] and worker[0]:
        # Una sola clave: el juez sera otro MODELO del mismo router, nunca el mismo spec que el obrero.
        judge = triad_presets.pick_other("judge", worker[0], worker[1])
    return worker, judge


def _spec(vendor, model):
    return "%s:%s" % (vendor, model) if vendor and model else ""


def optimize(config, state, hardware, ready=None):
    """El plan completo: los tres roles, el modo del juez, el reparto y las notas.

    El **director es el ancla**: lo que el operador eligió no se cambia aquí. Lo que se recalcula es la
    pareja obrero/juez a su alrededor, que es justo lo que nadie quiere cuadrar a mano.
    """
    from . import provider_discovery
    ceiling = getattr(config, "hardware_ceiling", 75)
    bias = str(getattr(config, "triad_bias", "ahorro") or "ahorro")
    room = budget(hardware, ceiling)
    rows = installed(state)
    ready = ready if ready is not None else triad_presets.vendors_ready(config, state)
    local_vendor = next((vendor for vendor in triad_presets.LOCAL if vendor in ready), "")
    director_spec = str(config.role_spec("director") or "")
    director_vendor, director_model = triad_presets.split_spec(director_spec)
    director_local = director_vendor in LOCAL
    roles, notes = {"director": director_spec}, []
    judge_mode = "fast"

    heavy = pick_heavy(rows, room["heavy_gb"])
    # El juez tampoco puede ser el modelo del obrero: dos roles con el mismo peso no se auditan, se
    # repiten. Se excluyen los dos (director y pesado) y se busca otro.
    taken = {heavy[1]} | ({director_model} if director_local else set())
    light = pick_light(rows, room["light_gb"], exclude=taken)
    worker_cloud, judge_cloud = cloud_roles(ready)
    wants_cloud = room["harness_gb"] <= 0 or bias == "velocidad"

    if director_local:
        roles["worker"] = director_spec
        if triad_presets.weight_gb(director_model) > room["heavy_gb"] and room["heavy_gb"] > 0:
            notes.append("el director (%s GB) no cabe en el presupuesto pesado (%s GB): o bajas el "
                         "modelo o subes el techo" % (triad_presets.weight_gb(director_model),
                                                      room["heavy_gb"]))
        # Un segundo peso SOLO si director + juez caben juntos en el techo: si el director ya se lo
        # come, cargar un juez al lado no audita, obliga a LM Studio a descargar el director.
        together = triad_presets.weight_gb(director_model) + light[2] if light[0] else 0.0
        fits_together = bool(light[0]) and together <= room["harness_gb"]
        if fits_together:
            roles["judge"] = _spec(light[0], light[1])
            notes.append("juez local distinto del director: auditoría cruzada real con 2 pesos en VRAM "
                         "(%s GB en total, dentro del techo)" % round(together, 1))
        elif light[0]:
            notes.append("no cabe un juez local junto al director (%s GB > %s GB de techo): cargarlo "
                         "obligaría a descargar el director" % (round(together, 1),
                                                                room["harness_gb"]))
        if roles.get("judge"):
            pass
        elif judge_cloud[0]:
            roles["judge"] = _spec(*judge_cloud)
            notes.append("el juez se va a nube flash: no cabe un segundo peso dentro del techo")
        else:
            judge_mode = "gate"
            notes.append("sin segunda familia disponible: el juez queda en gate determinista")
        notes.append("obrero = director: 0 s de swapping entre fases")
    elif wants_cloud:
        roles["worker"] = _spec(*worker_cloud) or _spec(heavy[0], heavy[1])
        roles["judge"] = _spec(*judge_cloud) or _spec(*light[:2])
        if not roles["worker"]:
            notes.append("no hay ni nube configurada ni modelo local: falta una clave o un servidor")
    else:
        roles["worker"] = _spec(heavy[0], heavy[1])
        if light[0]:
            roles["judge"] = _spec(light[0], light[1])
            notes.append("obrero local + juez local distinto: $0 por turno y 2 pesos en VRAM")
        elif judge_cloud[0]:
            roles["judge"] = _spec(*judge_cloud)
            notes.append("no cabe un juez local en su cuota: el juez usa nube barata")
        else:
            judge_mode = "gate"
            notes.append("sin juez local ni clave de nube: gate determinista")
    pending = provider_discovery.pending_key(config)
    if pending:
        notes.append("proveedor(es) detectado(s) sin clave visible: %s (pégala en Seguridad una vez)"
                     % ", ".join(pending))
    # Con el juez en `gate` no hace falta un modelo: el gate determinista ES el juez. Contarlo como
    # «sin resolver» seria pedirle al operador un modelo que el plan decidio no usar.
    needed = ("director", "worker") if judge_mode == "gate" else ("director", "worker", "judge")
    missing = [role for role in needed if not roles.get(role)]
    if missing:
        notes.append("sin resolver: %s" % ", ".join(missing))
    plan = {"roles": {role: spec for role, spec in roles.items() if spec},
            "judge_mode": judge_mode, "notes": notes, "budget": room,
            "ok": not missing, "bias": bias, "local_vendor": local_vendor}
    plan["segments"] = segments(plan["roles"], hardware)
    return plan


def segments(roles, hardware):
    """La barra de ocupación: pesado, juez y lo que queda libre para el PC.

    Se cuenta por PESO, no por rol: director y obrero compartiendo modelo ocupan una vez, que es
    exactamente la razón por la que el reparto existe.
    """
    room = budget(hardware, 75)
    vram = room["vram_gb"] or 0.0
    heavy, judge = {}, {}
    for role in ("director", "worker"):
        vendor, model = triad_presets.split_spec((roles or {}).get(role) or "")
        if vendor in LOCAL and model:
            heavy[model] = triad_presets.weight_gb(model)
    vendor, model = triad_presets.split_spec((roles or {}).get("judge") or "")
    if vendor in LOCAL and model and model not in heavy:
        judge[model] = triad_presets.weight_gb(model)
    heavy_gb = round(sum(heavy.values()), 1)
    judge_gb = round(sum(judge.values()), 1)
    used = round(heavy_gb + judge_gb, 1)
    reserve = round(max(0.0, vram - used), 1)

    def pct(value):
        return round(100.0 * value / vram, 1) if vram else 0.0

    return [{"key": "heavy", "label": "Director/Obrero", "gb": heavy_gb, "pct": pct(heavy_gb),
             "models": sorted(heavy)},
            {"key": "judge", "label": "Juez", "gb": judge_gb, "pct": pct(judge_gb),
             "models": sorted(judge)},
            {"key": "free", "label": "Reserva libre para tu PC", "gb": reserve, "pct": pct(reserve),
             "models": []}]


def apply(cockpit, ready=None):
    """Aplica el plan al config vivo. Devuelve `(nota, ok)`."""
    from . import hardware_probe, onboarding
    state = onboarding.status(cockpit.config, root=cockpit.config.default_root)
    hardware = hardware_probe.report()
    plan = optimize(cockpit.config, state, hardware, ready)
    if not plan["roles"]:
        return ("; ".join(plan["notes"]) or "no hay con qué repartir", False)
    answer = onboarding.apply(cockpit.config, {"roles": plan["roles"]})
    saved = answer.get("saved", {}).get("roles") or {}
    numbers = onboarding.save_settings({"judge_mode": plan["judge_mode"]})
    cockpit.reload_config()
    detail = ", ".join("%s=%s" % (role, spec) for role, spec in sorted(saved.items()))
    notes = list(plan["notes"]) + list(numbers[1])
    return ("tríada reequilibrada: %s%s" % (detail or "sin cambios",
                                            (" · " + " · ".join(notes)) if notes else ""),
            bool(saved))


def selftest():
    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    hardware = {"gpus": [{"name": "g", "total_mb": 16303, "free_mb": 2000}]}
    room = budget(hardware, 75)
    check("la vram se lee del sondeo", room["vram_gb"], 15.9)
    check("el techo por defecto deja el 25 % al PC", room["harness_gb"], 11.9)
    check("y el 75 % de ese presupuesto es el peso pesado", room["heavy_gb"], 8.9)
    check("el juez tiene su cuarto", room["light_gb"], 3.0)
    check("lo reservado para el PC", room["reserve_gb"], 4.0)
    check("techo 50 % = modo ligero", budget(hardware, 50)["harness_gb"], 8.0)
    check("techo 0 % = todo nube", budget(hardware, 0)["harness_gb"], 0.0)
    check("sin GPU no hay presupuesto", budget({"gpus": []}, 75)["harness_gb"], 0.0)

    rows = [("lmstudio", "grande-35b@q4_k_m", 19.7), ("lmstudio", "medio-14b-instruct", 7.9),
            ("lmstudio", "micro-4b", 2.3), ("lmstudio", "auditor-24b@q4", 13.5)]
    check("el pesado es el mayor que CABE", pick_heavy(rows, 8.9)[1], "medio-14b-instruct")
    check("un 35B no entra en 8,9 GB", pick_heavy(rows, 8.9)[2] <= 8.9, True)
    check("el juez es un micro, no un 24B", pick_light(rows, 3.0)[1], "micro-4b")
    check("y si no cabe ninguno, vacio", pick_light(rows, 1.0)[0], "")

    class Config:
        roles = {"director": "orca:deepseek/deepseek-v4.1-flash", "worker": "lmstudio:x",
                 "judge": "orca:otro"}
        providers = {}
        secrets = {}
        hardware_ceiling = 75
        triad_bias = "ahorro"

        def role_spec(self, role):
            return self.roles.get(role, "")

    state = {"local": {"lmstudio": {"ready": True, "loaded": ["medio-14b-instruct"],
                                    "models": [row[1] for row in rows]}}}
    plan = optimize(Config(), state, hardware, ready={"lmstudio", "orca"})
    check("director en nube: el obrero va local", plan["roles"]["worker"].startswith("lmstudio:"), True)
    check("y el juez local es OTRO peso", plan["roles"]["judge"].startswith("lmstudio:"), True)
    check("con dos modelos distintos en VRAM",
          len(set(plan["roles"][role] for role in ("worker", "judge"))), 2)
    check("el plan cabe en el techo", plan["budget"]["harness_gb"] >= 0, True)
    check("la barra suma lo usado y la reserva",
          round(sum(seg["gb"] for seg in plan["segments"]), 1), 15.9)
    check("el director no se toca", plan["roles"]["director"], "orca:deepseek/deepseek-v4.1-flash")

    class LocalConfig(Config):
        roles = {"director": "lmstudio:medio-14b-instruct", "worker": "lmstudio:x",
                 "judge": "lmstudio:x"}
        secrets = {"HERMES_CUSTOM_ORCA_API_KEY": "k"}
        providers = {"orca": {"wire": "openai", "base_url": "https://x/v1", "local": False}}

        def role_spec(self, role):
            return self.roles.get(role, "")

    plan = optimize(LocalConfig(), state, hardware, ready={"lmstudio", "orca"})
    check("director local: el obrero se pega al residente",
          plan["roles"]["worker"], "lmstudio:medio-14b-instruct")
    check("y el juez es un micro distinto", plan["roles"]["judge"], "lmstudio:micro-4b")
    check("sin swapping: un solo peso pesado", plan["segments"][0]["gb"], 7.9)

    class NoJudge(Config):
        triad_bias = "velocidad"

    plan = optimize(NoJudge(), state, hardware, ready={"lmstudio", "orca"})
    check("modo velocidad manda el obrero a nube", plan["roles"]["worker"].startswith("orca:"), True)

    store = budget(hardware, 0)
    check("techo 0 no deja nada local", store["harness_gb"], 0.0)
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("triad_balance: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
