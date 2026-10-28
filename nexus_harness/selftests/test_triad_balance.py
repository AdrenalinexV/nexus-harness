"""El reparto de la GPU y la reacción automática: el techo manda y el plan se explica solo.

Lo que esta suite fija, y por qué cada cosa importa:

* el techo (75/50/0 %) se traduce en un presupuesto real (B), con su 75 % para el peso pesado y su
  25 % para el juez, y la reserva del PC se calcula, no se promete;
* un juez local SOLO se asigna si director + juez caben juntos en el techo: cargar un segundo peso al
  lado de un 27B no audita, obliga a LM Studio a descargar el director;
* el director es el ancla del operador: el balanceador reajusta obrero y juez, nunca lo que él eligió;
* con el director en nube la GPU queda libre para obrero y juez locales ($0 por turno, auditoría
  cruzada nube contra local), y con el director local pesado el juez se va (o baja a gate);
* `orca` y los endpoints OpenAI-compatibles que esta máquina YA usa se detectan y entran como
  proveedores, sin copiar secretos a otro fichero.

Determinista: hardware y estado local entran inyectados; ni `nvidia-smi` ni LM Studio.
"""
from .. import triad_balance, triad_presets
from ..config import HarnessConfig
from ..provider_discovery import candidates, enrich, pending_key, read_providers

HW = {"gpus": [{"name": "NVIDIA GeForce RTX 5070 Ti", "total_mb": 16303, "free_mb": 2000}],
      "memory": {"total_mb": 32768, "free_mb": 12000}, "cpu": {"name": "t", "cores": 16}}
MODELS = ["grande-35b@q4_k_m", "medio-14b-instruct", "micro-4b", "auditor-24b@q4"]
STATE = {"local": {"lmstudio": {"ready": True, "models": MODELS, "loaded": ["medio-14b-instruct"]},
                   "ollama": {"ready": True, "models": ["micro-4b"], "loaded": []}}}
CURRENT = []


def check(name, got, expected, failures=None):
    target = CURRENT if failures is None else failures
    if got != expected:
        target.append("%s: %r, esperaba %r" % (name, got, expected))


def config(**extra):
    values = dict(default_root=".", roles={
        "director": "orca:deepseek/deepseek-v4.1-flash",
        "worker": "lmstudio:medio-14b-instruct",
        "judge": "orca:glm-4.5"}, secrets={})
    values.update(extra)
    return HarnessConfig(**values)


class Cockpit:
    def __init__(self, cfg):
        self.config = cfg
        self.root = "."
        self.reloads = 0

    def reload_config(self):
        self.reloads += 1
        return self.config

    class _Router:
        @staticmethod
        def window(role="worker", timeout=4):
            return 0

    router = _Router()


def test_module_selftests(failures):
    from .. import provider_discovery
    for problem in triad_balance.selftest():
        failures.append("triad_balance.selftest: %s" % problem)
    for problem in provider_discovery.selftest():
        failures.append("provider_discovery.selftest: %s" % problem)


def test_the_ceiling_becomes_a_budget(failures):
    room = triad_balance.budget(HW, 75)
    check("la vram sale del sondeo", room["vram_gb"], 15.9)
    check("el 75 % para el arnes", room["harness_gb"], 11.9)
    check("el 25 % del presupuesto se queda en el PC", room["reserve_gb"], 4.0)
    check("el peso pesado tiene su 75 %", room["heavy_gb"], 8.9)
    check("el juez su 25 %", room["light_gb"], 3.0)
    check("50 % es el modo ligero", triad_balance.budget(HW, 50)["harness_gb"], 8.0)
    check("0 % no toca la GPU", triad_balance.budget(HW, 0)["harness_gb"], 0.0)
    check("sin GPU no hay presupuesto", triad_balance.budget({"gpus": []}, 75)["harness_gb"], 0.0)


def test_the_heavy_and_the_micro_are_chosen_by_size(failures):
    rows = triad_balance.installed(STATE)
    check("ve los modelos de los dos servidores", len(rows), 5)
    check("el pesado es el mayor que cabe", triad_balance.pick_heavy(rows, 8.9)[1], "medio-14b-instruct")
    check("un 35B no entra en 8,9 GB", triad_balance.pick_heavy(rows, 8.9)[2] <= 8.9, True)
    check("el juez es un micro, no un 24B", triad_balance.pick_light(rows, 3.0)[1], "micro-4b")
    check("con cuota de 1 GB no hay juez", triad_balance.pick_light(rows, 1.0)[0], "")


def test_director_in_cloud_uses_the_free_gpu(failures):
    plan = triad_balance.optimize(config(), STATE, HW, ready={"lmstudio", "ollama", "orca"})
    check("el director no se toca", plan["roles"]["director"], "orca:deepseek/deepseek-v4.1-flash")
    check("el obrero va local", plan["roles"]["worker"].startswith("lmstudio:"), True)
    check("el juez es otro peso local, no el del obrero", plan["roles"]["judge"],
          "lmstudio:micro-4b")
    check("dos pesos distintos en VRAM",
          plan["roles"]["worker"] != plan["roles"]["judge"], True)
    check("el plan esta completo", plan["ok"], True)


def test_the_judge_is_never_the_worker(failures):
    """Dos roles con el mismo peso no se auditan: se repiten.

    Con solo dos modelos instalados y el director en nube, el pesado que cabe es el micro; si el juez
    pudiera repetirlo, el plan saldria «completo» sin ninguna auditoria cruzada.
    """
    thin = {"local": {"lmstudio": {"ready": True, "models": ["grande-35b@q4_k_m", "micro-4b"],
                                   "loaded": []}}}
    plan = triad_balance.optimize(config(), thin, HW, ready={"lmstudio", "orca"})
    check("juez y obrero no comparten peso", plan["roles"].get("worker") != plan["roles"].get("judge"),
          True)
    thick = triad_balance.optimize(config(), STATE, HW, ready={"lmstudio", "ollama"})
    check("con catalogo amplio tambien se separan",
          thick["roles"]["worker"] != thick["roles"]["judge"], True)


def test_director_in_local_pins_the_worker_and_moves_the_judge(failures):
    cfg = config(roles={"director": "lmstudio:medio-14b-instruct",
                        "worker": "lmstudio:grande-35b@q4_k_m",
                        "judge": "lmstudio:auditor-24b@q4"})
    plan = triad_balance.optimize(cfg, STATE, HW, ready={"lmstudio", "ollama"})
    check("el obrero se pega al residente", plan["roles"]["worker"], "lmstudio:medio-14b-instruct")
    check("y el juez es un micro distinto", plan["roles"]["judge"], "lmstudio:micro-4b")
    check("un solo peso pesado = 0 s de swapping", plan["segments"][0]["gb"], 7.9)

    heavy = config(roles={"director": "lmstudio:grande-35b@q4_k_m",
                          "worker": "lmstudio:medio-14b-instruct",
                          "judge": "lmstudio:micro-4b"})
    plan = triad_balance.optimize(heavy, STATE, HW, ready={"lmstudio", "ollama"})
    check("un director de 19,7 GB avisa de que no cabe",
          any("no cabe en el presupuesto pesado" in note for note in plan["notes"]), True)
    check("y NO se le pone un juez que obligue a descargarlo",
          any("obligaría a descargar el director" in note for note in plan["notes"]), True)
    check("el juez queda en gate", plan["judge_mode"], "gate")
    check("y gate cuenta como resuelto", plan["ok"], True)


def test_speed_bias_and_zero_ceiling_go_to_cloud(failures):
    plan = triad_balance.optimize(config(triad_bias="velocidad"), STATE, HW,
                                  ready={"lmstudio", "orca", "deepseek"})
    check("con sesgo de velocidad el obrero va a nube", plan["roles"]["worker"].startswith("orca:")
          or plan["roles"]["worker"].startswith("deepseek:"), True)
    plan = triad_balance.optimize(config(hardware_ceiling=0), STATE, HW,
                                  ready={"lmstudio", "orca", "deepseek"})
    check("con techo 0 % no se usa la GPU", any(
        spec.startswith("lmstudio:") or spec.startswith("ollama:")
        for role, spec in plan["roles"].items() if role == "worker"), False)


def test_the_bar_shows_three_segments_that_add_up(failures):
    plan = triad_balance.optimize(config(), STATE, HW, ready={"lmstudio", "ollama"})
    keys = [seg["key"] for seg in plan["segments"]]
    check("pesado, juez y reserva", keys, ["heavy", "judge", "free"])
    total = round(sum(seg["gb"] for seg in plan["segments"]), 1)
    check("los GB suman la VRAM", total, 15.9)
    check("y los porcentajes tambien", round(sum(seg["pct"] for seg in plan["segments"]), 0), 100.0)


def test_orca_is_detected_and_imported(failures):
    import tempfile
    from pathlib import Path

    sample = """providers:
  orca:
    name: orca
    base_url: https://api.orcarouter.ai/v1
    key_env: HERMES_CUSTOM_ORCA_API_KEY
  ollama:
    name: ollama
    base_url: http://127.0.0.1:11434/v1
    key_env: HERMES_CUSTOM_OLLAMA_API_KEY
model:
  provider: orca
"""
    from .. import provider_discovery
    # El entorno de quien lanza la suite puede tener la clave real de orca (Hermes se la pasa a sus
    # hijos). Esta prueba mide el caso "endpoint sí, clave no", asi que lo fija explicitamente; si no,
    # el resultado depende de la maquina y la suite miente en la mitad de las ejecuciones.
    import os
    saved_env = os.environ.pop("HERMES_CUSTOM_ORCA_API_KEY", None)
    with tempfile.TemporaryDirectory(prefix="orca-") as room:
        path = Path(room) / "config.yaml"
        path.write_text(sample, encoding="utf-8")
        rows = read_providers(path)
        check("lee el bloque providers", [row["name"] for row in rows], ["orca", "ollama"])
        original = provider_discovery.hermes_homes
        provider_discovery.hermes_homes = lambda: [path]
        try:
            cfg = config()
            found = candidates(cfg)
            check("orca se descubre con su endpoint", found[0]["base_url"],
                  "https://api.orcarouter.ai/v1")
            check("y sabe que la clave no es visible", bool(found[0]["secret"]), False)
            check("y se lista como pendiente", pending_key(cfg), ["orca"])
            added = enrich(cfg)
            check("entra como proveedor de primera clase", added, ["orca"])
            check("con cable openai", cfg.providers["orca"]["wire"], "openai")
            check("sin pisar el ollama nativo", "ollama" in cfg.providers, False)
            cfg.secrets["HERMES_CUSTOM_ORCA_API_KEY"] = "sk-de-prueba"
            check("con la clave en la boveda ya no esta pendiente", pending_key(cfg), [])
        finally:
            provider_discovery.hermes_homes = original
            if saved_env is not None:
                os.environ["HERMES_CUSTOM_ORCA_API_KEY"] = saved_env


def test_the_panel_renders_the_balancer(failures):
    from .. import settings_models
    cfg = config()
    body = settings_models.panel(Cockpit(cfg), "", dict(STATE, roles={}), HW)[2]
    check("el techo es un selector", 'name="hardware_ceiling"' in body, True)
    check("y el sesgo del reparto", 'name="triad_bias"' in body, True)
    check("y la reaccion automatica", 'name="triad_auto_adapt"' in body, True)
    check("la barra de VRAM por rol", 'data-vram="1"' in body, True)
    check("con sus tres tramos", all(part in body for part in ('vseg heavy', 'vseg judge', 'vseg free')),
          True)
    check("y el boton de auto-optimizar", 'value="optimize"' in body, True)
    check("los proveedores detectados se ven", 'data-provider="orca"' in body, True)


def test_the_auto_adapt_fires_on_a_class_change(failures):
    from .. import settings
    cfg = config()
    cockpit = Cockpit(cfg)
    applied = {}
    original_apply = settings.onboarding.apply
    original_save = settings.onboarding.save_settings
    original_adapt = settings.triad_balance.apply
    settings.onboarding.save_settings = lambda changes: (dict(changes or {}), [])

    def fake_apply(config_, payload):
        applied.update(payload.get("roles") or {})
        return {"ok": True, "notes": [], "saved": {"roles": dict(payload.get("roles") or {})}}

    calls = []
    settings.onboarding.apply = fake_apply
    settings.triad_balance.apply = lambda c, ready=None: (calls.append(1) or ("rebalanceado", True))
    try:
        settings.save(cockpit, {"section": "modelos", "role": "director",
                                "vendor": "lmstudio", "model": "medio-14b-instruct"})
    finally:
        settings.onboarding.apply = original_apply
        settings.onboarding.save_settings = original_save
        settings.triad_balance.apply = original_adapt
    check("el rol se guarda", applied.get("director"), "lmstudio:medio-14b-instruct")
    check("y la clase cambio: se reequilibra", len(calls), 1)

    cfg_off = config(triad_auto_adapt=False)
    cockpit_off = Cockpit(cfg_off)
    calls.clear()
    settings.onboarding.apply = fake_apply
    settings.triad_balance.apply = lambda c, ready=None: (calls.append(1) or ("x", True))
    try:
        settings.save(cockpit_off, {"section": "modelos", "role": "director",
                                    "vendor": "lmstudio", "model": "medio-14b-instruct"})
    finally:
        settings.onboarding.apply = original_apply
        settings.onboarding.save_settings = original_save
        settings.triad_balance.apply = original_adapt
    check("apagado, no se toca nada", calls, [])


def test_the_same_class_does_not_trigger_it(failures):
    from .. import settings
    cfg = config(roles={"director": "orca:uno", "worker": "orca:dos", "judge": "orca:tres"})
    cockpit = Cockpit(cfg)
    calls = []
    original_apply = settings.onboarding.apply
    original_save = settings.onboarding.save_settings
    original_adapt = settings.triad_balance.apply
    settings.onboarding.save_settings = lambda changes: (dict(changes or {}), [])
    settings.onboarding.apply = lambda config_, payload: {
        "ok": True, "notes": [], "saved": {"roles": dict(payload.get("roles") or {})}}
    settings.onboarding.save_settings = lambda changes: (dict(changes or {}), [])
    settings.triad_balance.apply = lambda c, ready=None: (calls.append(1) or ("x", True))
    try:
        settings.save(cockpit, {"section": "modelos", "role": "director",
                                "vendor": "orca", "model": "otro-modelo"})
    finally:
        settings.onboarding.apply = original_apply
        settings.onboarding.save_settings = original_save
        settings.triad_balance.apply = original_adapt
    check("nube -> nube no reequilibra", calls, [])


def test_the_ceiling_saves_with_types(failures):
    from .. import onboarding
    import tempfile
    from pathlib import Path
    original = onboarding.CONFIG_FILE
    with tempfile.TemporaryDirectory(prefix="techo-") as room:
        onboarding.CONFIG_FILE = Path(room) / "harness.json"
        try:
            saved, notes = onboarding.save_settings({"hardware_ceiling": "50", "triad_bias": "velocidad",
                                                     "triad_auto_adapt": "on"})
            check("el techo se guarda como entero", saved.get("hardware_ceiling"), 50)
            check("el sesgo se valida", saved.get("triad_bias"), "velocidad")
            check("y la reaccion como bool", saved.get("triad_auto_adapt"), True)
            bad, notes2 = onboarding.save_settings({"hardware_ceiling": "33", "triad_bias": "turbo"})
            check("un techo inventado no se guarda", "hardware_ceiling" in bad, False)
            check("ni un sesgo inventado", "triad_bias" in bad, False)
            check("y se explica", len(notes2) >= 2, True)
        finally:
            onboarding.CONFIG_FILE = original


def run():
    global CURRENT
    failures = []
    CURRENT = failures
    for test in (test_module_selftests, test_the_ceiling_becomes_a_budget,
                 test_the_heavy_and_the_micro_are_chosen_by_size,
                 test_director_in_cloud_uses_the_free_gpu, test_the_judge_is_never_the_worker,
                 test_director_in_local_pins_the_worker_and_moves_the_judge,
                 test_speed_bias_and_zero_ceiling_go_to_cloud,
                 test_the_bar_shows_three_segments_that_add_up,
                 test_orca_is_detected_and_imported, test_the_panel_renders_the_balancer,
                 test_the_auto_adapt_fires_on_a_class_change,
                 test_the_same_class_does_not_trigger_it, test_the_ceiling_saves_with_types):
        test(failures)
    return failures
