"""La tríada como una decisión de máquina: qué modelos caben, cuáles se pelean y qué preset toca.

Dos hechos que este módulo convierte en números, porque hasta ahora la cabina los escondía:

1. **El peso de un modelo local se puede estimar** desde su id (`35b` a `q4_k_m` son ~20 GB). Si la
   suma de los modelos locales de los tres roles pasa de la VRAM, LM Studio/Ollama descarga uno y carga
   otro en cada cambio de fase: eso son decenas de segundos por fase y una GPU que no puedes usar para
   nada más mientras el arnés "piensa".
2. **Un juez con el mismo modelo que el director no audita nada**: se aprueba a sí mismo. El catálogo
   por rol empuja a un proveedor o modelo distinto, y cuando no hay segunda opción se dice en voz alta
   (`judge_mode = gate`: solo el gate determinista, $0 y 0 ms, sin fingir auditoría cruzada).

Los ids del catálogo de nube son los que declaró el operador para este arnés; el campo del panel sigue
aceptando cualquier id escrito a mano, y un preset solo propone proveedores cuya clave existe.
"""
import re

from . import onboarding

PARAMS = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*b(?![a-z0-9])", re.I)
QUANT = re.compile(r"q(\d+)(?:_(?:k|0))?(?:_[a-z]+)?", re.I)
DEFAULT_BITS = 4.5
# El driver, el escritorio y el navegador ya comen VRAM: 0.85 es lo que un modelo puede usar sin
# que el driver empiece a paginar (medido en esta maquina: 15.9 GB totales, ~1.5 GB del sistema).
VRAM_SHARE = 0.85
# Estimacion de recarga: en esta maquina un modelo de ~13 GB vuelve a VRAM en ~20 s. Se declara como
# estimacion, nunca como medida: el panel dice "≈" y el numero sale de este factor.
SECONDS_PER_GB = 1.6
LOCAL = ("lmstudio", "ollama")
LOCAL_SET = frozenset(LOCAL)
# (proveedor, modelo) por rol, de mas barato a mas caro. Solo ids que el operador declaro.
LADDERS = {
    # `orca` primero: es el router que esta maquina ya usa (detectado por `provider_discovery`), y el
    # juez va a OTRA familia (GLM) que el director (DeepSeek) para que la auditoria cruzada sea real.
    "director": (("orca", "deepseek/deepseek-v4.1-flash"),
                 ("openrouter", "deepseek/deepseek-v4.1-flash"), ("deepseek", "deepseek-chat"),
                 ("anthropic", "claude-sonnet-4"), ("openai", "gpt-4o")),
    "worker": (("orca", "deepseek/deepseek-v4.1-flash"), ("deepseek", "deepseek-chat"),
               ("openrouter", "qwen-2.5-coder-32b"),
               ("anthropic", "claude-sonnet-4"), ("openai", "gpt-4o")),
    "judge": (("orca", "glm-4.5"), ("openrouter", "glm-4.5"), ("deepseek", "deepseek-reasoner"),
              ("anthropic", "claude-opus-4"), ("openai", "gpt-4o")),
}
PRESETS = (
    ("cloud", "☁️ Cloud ultra-barato · 0 % GPU",
     "Los tres roles en nube barata: 0 MB de VRAM, sirve mientras juegas o usas la GPU en otra cosa."),
    ("hybrid", "⚡ Híbrido élite · un solo peso local",
     "Director y juez en nube (auditoría cruzada de verdad) y el obrero en el ÚNICO modelo local: 0 s "
     "de swapping."),
    ("local", "🏠 100 % local sin swapping · $0",
     "Los tres roles en el mismo modelo residente que cabe en tu VRAM. Sin nube y sin recargas; el "
     "juez se queda en el gate determinista, porque juzgarse a sí mismo no es auditar."),
)


def split_spec(spec):
    """`vendor:modelo` -> `(vendor, modelo)`. Sin `:` el modelo es local (igual que `parse_spec`)."""
    text = str(spec or "").strip()
    if ":" in text:
        vendor, model = text.split(":", 1)
        return vendor.strip(), model.strip()
    return "lmstudio", text


def params_b(model):
    """Parametros en miles de millones segun el id (`35b-a3b` -> 35.0). 0 si el id no lo dice."""
    match = PARAMS.search(str(model or ""))
    if not match:
        return 0.0
    try:
        return float(match.group(1))
    except ValueError:
        return 0.0


def bits(model):
    """Bits por peso segun la cuantizacion del id; `Q4_K_M` -> 4.5. Sin dato, 4.5 (lo mas comun)."""
    match = QUANT.search(str(model or ""))
    if not match:
        return DEFAULT_BITS
    try:
        level = int(match.group(1))
    except ValueError:
        return DEFAULT_BITS
    return {2: 2.6, 3: 3.4, 4: 4.5, 5: 5.5, 6: 6.6, 8: 8.5}.get(level, DEFAULT_BITS)


def weight_gb(model):
    """Peso estimado en GB de un modelo local. 0 si el id no declara parametros: no se adivina."""
    count = params_b(model)
    return round(count * bits(model) / 8.0, 1) if count else 0.0


def local_roles(roles):
    """`{modelo: [roles]}` de los roles servidos por un servidor local."""
    found = {}
    for role, spec in (roles or {}).items():
        vendor, model = split_spec(spec)
        if vendor in LOCAL and model:
            found.setdefault(model, []).append(role)
    return found


def collision(roles, hardware, loaded=()):
    """El veredicto anti-swapping: cuantos pesos locales distintos hay y cuanto cuesta cambiarlos.

    `swapping` es True cuando hay mas de un modelo local distinto entre los roles: LM Studio solo
    mantiene cargado lo que cabe, y con dos pesos que no caben cada cambio de fase cuesta una recarga.
    """
    loaded = {str(name) for name in loaded or ()}
    models = local_roles(roles)
    weights = {model: weight_gb(model) for model in models}
    total = round(sum(weights.values()), 1)
    vram = round(sum(int(gpu.get("total_mb") or 0) for gpu in (hardware or {}).get("gpus") or ()) / 1024.0, 1)
    resident = next((model for model in models if model in loaded), "")
    reloads = max(0, len(models) - 1)
    seconds = 0.0
    if reloads:
        seconds = round(max(weights.get(resident) or max(weights.values(), default=0),
                            0) * SECONDS_PER_GB * reloads, 0)
    oversize = bool(vram) and total > vram * VRAM_SHARE
    return {"swapping": reloads > 0, "models": sorted(models), "weights": weights,
            "local_gb": total, "vram_gb": vram, "oversize": oversize, "resident": resident,
            "reloads": reloads, "seconds": int(seconds), "loaded": sorted(loaded)}


def state_text(info, hardware):
    """La frase de estado de la triada para la barra de hardware."""
    if not info["swapping"]:
        return "Óptimo: un solo peso local"
    if info["oversize"]:
        return ("⚠️ Alerta de swapping de VRAM: %s GB en un motor de %s GB — ≈%d s por fase"
                % (info["local_gb"], info["vram_gb"], int(info["seconds"])))
    return "⚠️ Swapping: %d modelo(s) local(es) distinto(s), ≈%d s por recarga" % (
        len(info["models"]), int(info["seconds"]))


def vendors_table(config):
    """La tabla de proveedores (de serie + los del operador), sin importar el router entero."""
    from .providers import merged_vendors
    return merged_vendors(config)[0]


def vendors_ready(config, state):
    """Los proveedores que ESTA maquina puede usar ahora: local vivo o clave presente."""
    ready = set()
    for vendor, row in ((state or {}).get("local") or {}).items():
        if row.get("ready"):
            ready.add(vendor)
    for vendor, table in vendors_table(config).items():
        if not table.get("local") and config.secret(table.get("keys") or ()):
            ready.add(vendor)
    return ready


def pick(role, ready):
    """El primer escalon del rol cuyo proveedor esta disponible. `("", "")` si no hay ninguno."""
    for vendor, model in LADDERS.get(role, ()):
        if vendor in ready:
            return vendor, model
    return "", ""


def fits(model, hardware):
    """Si ese peso cabe entero en la VRAM detectada. Sin VRAM conocida, no se descarta nada."""
    vram = sum(int(gpu.get("total_mb") or 0) for gpu in (hardware or {}).get("gpus") or ()) / 1024.0
    weight = weight_gb(model)
    return bool(weight) and (not vram or weight <= vram * VRAM_SHARE)


def resident_hint(state, hardware):
    """El modelo local que conviene tener residente: cargado Y que quepa; si no, el mayor que quepa.

    El orden importa: un modelo cargado que NO cabe se derrama a CPU (lento) y ademas ocupa la VRAM que
    necesitaria uno que si cabe. Preferir "el que ya esta" sin mirar el tamaño es como se acaba con un
    35B a 10 tok/s creyendo que es el bueno de la casa.
    """
    rows = ((state or {}).get("local") or {}).values()
    models = [model for row in rows for model in row.get("models") or ()]
    loaded = [model for row in rows for model in row.get("loaded") or ()]
    for model in loaded:
        if fits(model, hardware):
            return model
    fitting = [model for model in models if fits(model, hardware)]
    if fitting:
        return max(fitting, key=weight_gb)
    return loaded[0] if loaded else ""


def plan(name, config, state, hardware):
    """`{roles, judge_mode, notes, ok}` para un preset, con lo que esta maquina tiene de verdad."""
    ready = vendors_ready(config, state)
    local_vendor = next((vendor for vendor in LOCAL if vendor in ready), "")
    resident = resident_hint(state, hardware)
    notes, roles = [], {}
    if name == "cloud":
        for role in ("director", "worker", "judge"):
            vendor, model = pick(role, ready)
            if vendor:
                roles[role] = "%s:%s" % (vendor, model)
        judge_mode = "fast"
        if not roles:
            notes.append("no hay ninguna clave de nube en la bóveda: pon una en Seguridad primero")
    elif name == "hybrid":
        director, model = pick("director", ready - LOCAL_SET)
        judge, judge_model = pick("judge", (ready - LOCAL_SET - {director}) if director else (ready - LOCAL_SET))
        if resident and local_vendor:
            roles["worker"] = "%s:%s" % (local_vendor, resident)
        else:
            worker, worker_model = pick("worker", ready)
            if worker:
                roles["worker"] = "%s:%s" % (worker, worker_model)
                notes.append("sin modelo local cargado: el obrero va a nube")
        if director:
            roles["director"] = "%s:%s" % (director, model)
        if judge:
            roles["judge"] = "%s:%s" % (judge, judge_model)
        elif roles.get("director"):
            roles["judge"] = roles["director"]
            notes.append("sin clave para un juez distinto: el juez comparte modelo (auditoría cruzada "
                         "imposible)")
        judge_mode = "fast" if ready - LOCAL_SET else "gate"
    else:
        if resident and local_vendor:
            for role in ("director", "worker", "judge"):
                roles[role] = "%s:%s" % (local_vendor, resident)
            notes.append("un solo peso local residente: 0 s de swapping, $0")
            if resident not in (state.get("local", {}).get(local_vendor, {}) or {}).get("loaded", []):
                notes.append("ese modelo no esta cargado ahora: la primera llamada lo carga")
            notes.append("el juez usa el mismo peso que el director: queda en gate determinista, que "
                         "es la única auditoría honesta aquí")
        else:
            notes.append("no hay ningún modelo local que quepa entero en la VRAM detectada")
        judge_mode = "gate"
    missing = [role for role in ("director", "worker", "judge") if role not in roles]
    if missing:
        notes.append("sin resolver: %s" % ", ".join(missing))
    if missing:
        # Un proveedor DETECTADO en la maquina pero sin clave visible no es «no hay nube»: es «pega la
        # clave una vez». La diferencia es la que hace que el panel sea util o decorativo.
        from .provider_discovery import pending_key
        pending = pending_key(config)
        if pending:
            notes.append("detectado(s) %s en tu configuración: falta la clave (Seguridad, una vez)"
                         % ", ".join(pending))
    return {"roles": roles, "judge_mode": judge_mode, "notes": notes,
            "ok": not missing, "ready": sorted(ready)}


def catalog(vendor, role, state, config):
    """`[(valor, etiqueta)]` para el `<select>` del rol, con lo que responde AHORA y lo curado."""
    rows = []
    if vendor in LOCAL:
        row = ((state or {}).get("local") or {}).get(vendor) or {}
        loaded = set(row.get("loaded") or ())
        for model in row.get("models") or ():
            mark = " · cargado en VRAM" if model in loaded else ""
            rows.append((model, "%s%s" % (model, mark)))
        if not rows:
            rows.append(("", "(%s no responde ahora mismo)" % vendor))
        return rows
    for vendor_name, model in LADDERS.get(role, ()):
        if vendor_name != vendor:
            continue
        has_key = bool(config.secret(vendors_table(config).get(vendor, {}).get("keys") or ()))
        rows.append((model, "%s%s" % (model, "" if has_key else " · sin clave")))
    return rows or [("", "(sin catálogo para %s)" % vendor)]


def apply(cockpit, name):
    """Aplica un preset al config vivo y devuelve `(nota, ok)`. Guarda roles y modo del juez."""
    info = next((row for row in presets(cockpit) if row["id"] == name), None)
    if info is None:
        return ("preset desconocido: %r" % name, False)
    result = info["plan"]
    if not result["roles"]:
        return ("; ".join(result["notes"]) or "el preset no tiene con qué", False)
    answer = onboarding.apply(cockpit.config, {"roles": result["roles"]})
    saved = answer.get("saved", {}).get("roles") or {}
    numbers = onboarding.save_settings({"judge_mode": result["judge_mode"]})
    cockpit.reload_config()
    detail = ", ".join("%s=%s" % (role, spec) for role, spec in sorted(saved.items()))
    notes = list(result["notes"])
    if numbers[1]:
        notes += numbers[1]
    return ("preset %s: %s%s" % (name, detail or "sin cambios",
                                 (" · " + " · ".join(notes)) if notes else ""), bool(saved))


def presets(cockpit, hardware=None, state=None):
    """Los tres presets con su plan ya calculado (lo que la barra de la cabina pinta).

    `state` se inyecta cuando el llamante ya lo tiene: sondear dos veces los mismos servidores para
    pintar una pantalla es pagar dos veces por el mismo dato.
    """
    from . import hardware_probe
    state = state if state is not None else onboarding.status(cockpit.config,
                                                              root=cockpit.config.default_root)
    hardware = hardware or hardware_probe.report()
    loaded = [model for row in (state.get("local") or {}).values()
              for model in row.get("loaded") or ()]
    rows = []
    for name, title, detail in PRESETS:
        rows.append({"id": name, "title": title, "detail": detail,
                     "plan": plan(name, cockpit.config, state, hardware),
                     "swapping": collision(cockpit.config.roles, hardware, loaded)})
    return rows


def selftest():
    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    check("parametros de un id", params_b("kat-coder-35b-a3b-x"), 35.0)
    check("parametros decimales", params_b("qwen3.8-27b-x"), 27.0)
    check("un id sin tamaño no inventa", params_b("dolphin3.0-llama3.1"), 0.0)
    check("cuantizacion q4", bits("m-27b@q4_k_m"), 4.5)
    check("cuantizacion q6", bits("m-27b@q6_k"), 6.6)
    check("sin cuantizacion, 4.5 por defecto", bits("m-27b"), 4.5)
    check("el peso de un 35b q4", weight_gb("kat-coder-35b-a3b"), 19.7)
    check("un id sin parametros pesa 0", weight_gb("kat-coder"), 0.0)

    hardware = {"gpus": [{"name": "g", "total_mb": 16303, "free_mb": 2000}]}
    basic = {"director": "lmstudio:a-27b", "worker": "lmstudio:b-35b@q4_k_m",
             "judge": "lmstudio:a-27b"}
    info = collision(basic, hardware, loaded=("a-27b",))
    check("dos pesos distintos hacen swapping", info["swapping"], True)
    check("y el peso total se suma una vez por modelo", info["local_gb"], 34.9)
    check("y se sabe cual esta residente", info["resident"], "a-27b")
    check("y se estiman segundos", info["seconds"] > 0, True)
    check("tres roles con un solo modelo no hacen swapping",
          collision({"director": "lmstudio:x-8b", "worker": "lmstudio:x-8b",
                     "judge": "lmstudio:x-8b"}, hardware)["swapping"], False)
    check("un rol de nube no cuenta como local",
          collision({"worker": "deepseek:deepseek-chat"}, hardware)["models"], [])

    class Config:
        roles = dict(basic)
        providers = {}

        def secret(self, names):
            return "k" if any("DEEPSEEK" in str(name) for name in names or ()) else None

    state = {"local": {"lmstudio": {"ready": True, "models": ["a-27b", "b-35b@q4_k_m"],
                                    "loaded": ["a-27b"]}}}
    cloud = plan("cloud", Config(), state, hardware)
    check("cloud resuelve los tres roles con la clave que hay", cloud["ok"], True)
    check("y el juez no es el mismo modelo que el director",
          cloud["roles"]["judge"] != cloud["roles"]["director"], True)
    hybrid = plan("hybrid", Config(), state, hardware)
    check("hibrido deja el obrero en el modelo residente",
          hybrid["roles"]["worker"], "lmstudio:a-27b")
    check("y el director en nube", hybrid["roles"]["director"].startswith("deepseek:"), True)
    local = plan("local", Config(), state, hardware)
    check("local usa un solo peso", len(set(local["roles"].values())), 1)
    check("y el juez baja a gate determinista", local["judge_mode"], "gate")

    # Sin `__file__` dentro del motor congelado, la comprobacion mira el modulo VIVO: si algun dia
    # alguien le mete un cliente HTTP, aqui se ve. Es la unica forma que funciona tambien en el .exe.
    import sys
    module = sys.modules[__name__]
    check("este modulo no habla con la red: solo calcula",
          hasattr(module, "urllib") or hasattr(module, "socket") or hasattr(module, "requests"), False)
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("triad_presets: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
