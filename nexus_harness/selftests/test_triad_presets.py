"""La triada como decisión de máquina: VRAM, presets, selectores reales y los tres modos del juez.

Lo que esta suite defiende, y por qué cada cosa:

* el peso de un modelo local se ESTIMA desde su id, y un id sin tamaño no inventa un número;
* dos pesos locales distintos son «swapping» y se dice cuánto cuesta, porque en una GPU de 16 GB un 27B
  y un 35B no conviven y el turno paga la recarga en cada fase;
* los tres presets resuelven roles contra lo que hay (local vivo, clave en la bóveda) y NO guardan un
  rol que no se puede servir;
* el panel pinta un `<select>` de verdad, el modo del juez y el toggle del obrero residente — y avisa
  cuando el juez es el mismo modelo que el director;
* `judge_mode = gate` no gasta ninguna llamada: devuelve `skipped` sin tocar el router.

Determinista: sin red, sin GPU y sin LM Studio. El hardware y el sondeo local entran inyectados.
"""
from ..platform import hardware_probe
from .. import settings_models, triad_presets, triad_recommend
from ..config import HarnessConfig
from ..judge import ADVERSARY, NullJudge, judge_for
from ..core.message import Message


# La lista viva de fallos. Existe para que cada `check()` pueda escribirse sin arrastrar el parametro
# por todas partes, y `run()` la reapunta a la lista que devuelve: una sola verdad por ejecucion.
CURRENT = []


def check(name, got, expected, failures=None):
    target = CURRENT if failures is None else failures
    if got != expected:
        target.append("%s: %r, esperaba %r" % (name, got, expected))


FAKE_HW = {"gpus": [{"name": "NVIDIA GeForce RTX 5070 Ti", "total_mb": 16303, "free_mb": 2048}],
           "memory": {"total_mb": 32768, "free_mb": 12000},
           "cpu": {"name": "test", "cores": 16}}
FAKE_STATE = {
    "local": {
        "lmstudio": {"ready": True, "error": "",
                     "models": ["qwen3.8-27b-heretic-abliterated-uncensored",
                                "kat-coder-v2.5-dev-35b-a3b-abliterated-uncensored-philadelphia-class",
                                "qwen2.5-coder-14b-instruct"],
                     "loaded": ["kat-coder-v2.5-dev-35b-a3b-abliterated-uncensored-philadelphia-class"]},
        "ollama": {"ready": False, "error": "connection refused", "models": [], "loaded": []},
    },
    "roles": {},
}


def state_for(cfg):
    """El estado que `onboarding.status` produce, con los roles ya resueltos de la config."""
    roles = {}
    for role, spec in cfg.roles.items():
        vendor, model = triad_presets.split_spec(spec)
        roles[role] = {"spec": spec, "vendor": vendor, "model": model,
                       "cloud": vendor not in triad_presets.LOCAL, "ready": True}
    return dict(FAKE_STATE, roles=roles)


def config(**extra):
    values = dict(default_root=".", roles={
        "director": "lmstudio:qwen3.8-27b-heretic-abliterated-uncensored",
        "worker": "lmstudio:kat-coder-v2.5-dev-35b-a3b-abliterated-uncensored-philadelphia-class",
        "judge": "lmstudio:qwen3.8-27b-heretic-abliterated-uncensored",
    }, budget_limit=60000, lang="es", secrets={})
    values.update(extra)
    return HarnessConfig(**values)


class Cockpit:
    """Lo mínimo que el panel toca: config, router (ventana) y recarga."""

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
    for problem in hardware_probe.selftest():
        failures.append("hardware_probe.selftest: %s" % problem)
    for problem in triad_presets.selftest():
        failures.append("triad_presets.selftest: %s" % problem)


def test_hardware_is_measured_from_the_engine(failures):
    text = "NVIDIA GeForce RTX 5070 Ti, 16303, 2048\n"
    rows = hardware_probe.gpus(lambda command, timeout=4: text)
    check("la GPU se lee del csv", rows[0]["name"], "NVIDIA GeForce RTX 5070 Ti")
    check("con su VRAM total", rows[0]["total_mb"], 16303)
    check("y la libre, que es la que decide", rows[0]["free_mb"], 2048)
    check("sin nvidia-smi no hay GPU inventada", hardware_probe.gpus(lambda c, timeout=4: ""), [])
    report = hardware_probe.report(lambda c, timeout=4: text,
                                   memory_reader=lambda: {"total_mb": 32768, "free_mb": 12000})
    check("el informe suma memoria y cpu", bool(report["memory"] and report["cpu"]), True)
    check("la barra dice GB y estado", "15.9 GB VRAM" in hardware_probe.headline(report, "Óptimo"), True)
    check("un modelo de 35b q4 pesa ~20 GB", triad_presets.weight_gb("c-35b-a3b@q4_k_m"), 19.7)
    check("un id sin parametros no inventa peso", triad_presets.weight_gb("kat-coder"), 0.0)


def test_the_collision_names_the_cost(failures):
    info = triad_presets.collision(config().roles, FAKE_HW, ["qwen3.8-27b-heretic-abliterated-uncensored"])
    check("dos pesos distintos son swapping", info["swapping"], True)
    check("el total se suma por modelo", info["local_gb"], round(
        triad_presets.weight_gb("qwen3.8-27b-heretic-abliterated-uncensored")
        + triad_presets.weight_gb("kat-coder-v2.5-dev-35b-a3b-abliterated-uncensored-philadelphia-class"), 1))
    check("y se estiman segundos por fase", info["seconds"] > 0, True)
    check("el estado lo dice", "Alerta de swapping" in triad_presets.state_text(info, FAKE_HW), True)
    same = {"director": "lmstudio:a-8b", "worker": "lmstudio:a-8b", "judge": "lmstudio:a-8b"}
    check("un solo peso no hace swapping",
          triad_presets.collision(same, FAKE_HW, ["a-8b"])["swapping"], False)


def test_the_presets_resolve_against_this_machine(failures):
    cfg = config()
    cloud = triad_presets.plan("cloud", cfg, FAKE_STATE, FAKE_HW)
    check("sin clave de nube el preset cloud no promete nada", cloud["ok"], False)
    check("y lo dice", any("clave" in note for note in cloud["notes"]), True)

    cfg_deepseek = config(secrets={"DEEPSEEK_API_KEY": "sk-test"})
    cloud = triad_presets.plan("cloud", cfg_deepseek, FAKE_STATE, FAKE_HW)
    check("con clave de nube resuelve los tres roles", cloud["ok"], True)
    check("y el juez es otro modelo, no el mismo", cloud["roles"]["judge"] != cloud["roles"]["director"], True)

    local = triad_presets.plan("local", cfg, FAKE_STATE, FAKE_HW)
    check("el preset local usa un solo peso", len(set(local["roles"].values())), 1)
    check("y baja el juez a gate, porque se juzgaria a si mismo", local["judge_mode"], "gate")
    check("el elegido cabe en la VRAM", triad_presets.fits(
        triad_presets.split_spec(local["roles"]["worker"])[1], FAKE_HW), True)
    check("el que NO cabe se descarta", triad_presets.fits(
        "kat-coder-v2.5-dev-35b-a3b-abliterated-uncensored-philadelphia-class", FAKE_HW), False)

    hybrid = triad_presets.plan("hybrid", cfg_deepseek, FAKE_STATE, FAKE_HW)
    check("el hibrido deja el obrero en local", hybrid["roles"]["worker"].startswith("lmstudio:"), True)
    check("y el director en nube", hybrid["roles"]["director"].startswith("deepseek:"), True)


def test_the_catalog_marks_what_is_loaded(failures):
    cfg = config()
    rows = triad_presets.catalog("lmstudio", "worker", FAKE_STATE, cfg)
    labels = [label for _value, label in rows]
    check("lista los modelos vivos", len(rows), 3)
    check("y marca el que esta en VRAM", any("cargado en VRAM" in label for label in labels), True)
    cloud = triad_presets.catalog("deepseek", "worker", FAKE_STATE, cfg)
    check("el catalogo de nube avisa si falta la clave",
          any("sin clave" in label for _value, label in cloud), True)


def test_the_panel_shows_hardware_presets_and_selects(failures):
    cfg = config()
    html = settings_models.panel(Cockpit(cfg), "", state_for(cfg), FAKE_HW)
    body = html[2]
    check("hay barra de hardware", "Diagnóstico de hardware" in body, True)
    check("y dice la GPU", "RTX 5070 Ti" in body, True)
    check("y el veredicto de swapping", "Alerta de swapping" in body, True)
    check("hay perfiles de 1 clic", "Perfiles recomendados" in body, True)
    for preset in ("cloud", "hybrid", "local"):
        check("el preset %s esta" % preset, 'name="preset" value="%s"' % preset in body, True)
    check("el modelo es un <select> real", '<select name="model"' in body, True)
    check("y acepta un id libre", 'name="model_free"' in body, True)
    check("el juez tiene sus tres modos", body.count('name="judge_mode"'), 1)
    check("con las tres etiquetas", all(label in body for label, _text in settings_models.MODE_LABELS), True)
    check("el obrero tiene el toggle residente", 'name="worker_resident"' in body, True)
    check("y avisa de que el juez es el mismo modelo", "se aprueba a sí mismo" in body, True)

    calm = config(roles={"director": "lmstudio:a-8b", "worker": "lmstudio:a-8b",
                         "judge": "deepseek:deepseek-reasoner"}, secrets={"DEEPSEEK_API_KEY": "k"})
    body = settings_models.panel(Cockpit(calm), "", state_for(calm), FAKE_HW)[2]
    check("sin colision no hay alerta", "Alerta de swapping" in body, False)
    check("ni aviso de juez clonado", "se aprueba a sí mismo" in body, False)


def test_the_judge_modes_are_real(failures):
    cfg = config(judge_mode="gate")
    null = judge_for(Router(), cfg)
    check("gate no construye un juez que llame", isinstance(null, NullJudge), True)
    verdict = null.review("objetivo", "resumen", [], "evidencia")
    check("y contesta skipped sin gastar", (verdict.verdict, verdict.ok), ("skipped", True))
    fast = judge_for(Router(), config(judge_mode="fast"))
    check("fast si es un juez", fast.mode, "fast")
    adversary = judge_for(Router(), config(judge_mode="adversary"))
    check("adversary tiene su propio contrato", adversary.mode, "adversary")
    check("y su prompt es el estricto", "ADVERSARIO" in ADVERSARY["es"], True)


def test_the_save_path_honours_the_free_id(failures):
    """`model_free` manda sobre el `<select>`: el catalogo propone, no encierra."""
    from .. import settings

    cfg = config()
    cockpit = Cockpit(cfg)
    applied, saved_numbers = {}, {}
    original = settings.onboarding.apply
    original_save = settings.onboarding.save_settings
    settings.onboarding.apply = lambda config_, payload: (
        applied.update(payload.get("roles") or {}) or {"ok": True, "notes": [],
                                                       "saved": {"roles": payload.get("roles")}})
    # `save_settings` escribe en `~/.nexus/harness.json`: una suite que no lo intercepta le cambia la
    # configuracion al operador (paso, y se vio como un `judge_mode: adversary` que nadie eligio).
    settings.onboarding.save_settings = lambda changes: (
        saved_numbers.update(changes or {}) or (dict(changes or {}), []))
    try:
        settings.save(cockpit, {"section": "modelos", "role": "worker", "vendor": "lmstudio",
                                "model": "del-select", "model_free": "escrito-a-mano",
                                "judge_mode": "adversary"})
    finally:
        settings.onboarding.apply = original
        settings.onboarding.save_settings = original_save
    check("el id libre gana", applied.get("worker"), "lmstudio:escrito-a-mano")
    check("y el modo del juez se guarda", saved_numbers.get("judge_mode"), "adversary")


def test_the_worker_can_be_pinned_to_the_resident(failures):
    from .. import settings

    cfg = config(worker_resident=True, roles={
        "director": "lmstudio:un-8b",
        "worker": "lmstudio:otro-35b",
        "judge": "lmstudio:un-8b"})
    cockpit = Cockpit(cfg)
    applied = {}
    original = settings.onboarding.apply
    settings.onboarding.apply = lambda config_, payload: (
        applied.update(payload.get("roles") or {}) or
        {"ok": True, "notes": [], "saved": {"roles": payload.get("roles")}})
    try:
        notes = settings._pin_worker(cockpit)
    finally:
        settings.onboarding.apply = original
    check("el obrero se fija al director local", applied.get("worker"), "lmstudio:un-8b")
    check("y se declara", any("obrero fijado" in note for note in notes), True)


def test_a_cloud_director_is_left_alone(failures):
    from .. import settings

    cfg = config(worker_resident=True, secrets={"DEEPSEEK_API_KEY": "k"}, roles={
        "director": "deepseek:deepseek-chat", "worker": "lmstudio:x-8b",
        "judge": "deepseek:deepseek-reasoner"})
    check("con director de nube no se toca el obrero", settings._pin_worker(Cockpit(cfg)),
          ["worker_resident: el director no es local, no se toca el obrero"])


def test_the_recommendation_picks_by_physics_not_by_taste(failures):
    """Con un peso local que cabe, la recomendacion es local; sin local, hibrida; sin nada, se dice."""
    cfg = config()
    local = triad_recommend.recommend(cfg, state_for(cfg), FAKE_HW)
    check("con local vivo recomienda local", local["id"], "local", failures)
    check("y resuelve los tres roles", sorted(local["roles"]), ["director", "judge", "worker"],
          failures)
    check("el juez queda en gate (mismo peso)", local["judge_mode"], "gate", failures)
    check("la linea se puede imprimir", "director=" in triad_recommend.recommend_text(local), True,
          failures)

    dead_local = {"local": {"lmstudio": {"ready": False, "error": "refused", "models": [],
                                        "loaded": []}},
                  "roles": {}}
    cloud_cfg = config(secrets={"OPENROUTER_API_KEY": "sk-test"})
    cloud = triad_recommend.recommend(cloud_cfg, dead_local, FAKE_HW)
    check("sin local pero con clave, no se queda en local", cloud["id"] in ("hybrid", "cloud"), True,
          failures)
    check("y lo dice en el motivo", bool(cloud["reason"]), True, failures)

    nothing = triad_recommend.recommend(config(), dead_local, FAKE_HW)
    check("sin nada listo no inventa triada", nothing["ok"], False, failures)
    check("y nombra lo que falta", "proveedor" in (nothing["reason"] or ""), True, failures)
    check("el texto lo declara", triad_recommend.recommend_text(nothing).startswith("sin tríada"),
          True, failures)


def run():
    global CURRENT
    failures = []
    CURRENT = failures
    for test in (test_module_selftests, test_hardware_is_measured_from_the_engine,
                 test_the_collision_names_the_cost, test_the_presets_resolve_against_this_machine,
                 test_the_catalog_marks_what_is_loaded,
                 test_the_panel_shows_hardware_presets_and_selects, test_the_judge_modes_are_real,
                 test_the_save_path_honours_the_free_id,
                 test_the_worker_can_be_pinned_to_the_resident,
                 test_a_cloud_director_is_left_alone,
                 test_the_recommendation_picks_by_physics_not_by_taste):
        test(failures)
    return failures


class Router:
    """Un router que no se llama: si el juez `gate` lo tocara, el contador lo delataria."""

    def __init__(self):
        self.calls = 0

    def info(self, role):
        return type("Info", (), {"ready": True, "model": "m", "why_not_ready": ""})()

    def role(self, role):
        self.calls += 1
        return self

    def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        raise AssertionError("el juez de gate no debe llamar al modelo")
