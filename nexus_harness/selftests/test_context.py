"""Contexto: el prefijo no se reescribe y el presupuesto se mide con el sesgo del modelo.

Dos cosas se prueban aqui, y las dos se midieron como fallo antes de existir este modulo:

* el mensaje `system` era distinto en CADA paso de un turno (se reconstruia con los ficheros
  tocados), asi que la cache de prefijo del proveedor se invalidaba en cada llamada;
* el presupuesto se media con `chars / 4`, sin corregir el sesgo real de cada modelo.
"""
import tempfile
from pathlib import Path

from .fakes import FakeGate, FakeRouter, ScriptedProvider, TempProject, reply
from ..chat import Chat
from ..config import HarnessConfig
from ..context_compiler import DELTA_MARKER, TurnWindow, build_prefix
from ..events import Bus
from ..tokenizer import Calibration, count, estimate
from ..tools import default_registry


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


class GrowingSkills:
    """Las skills que entran cambian con los ficheros: es el caso que rompia el prefijo."""

    def __init__(self):
        self.seen = []

    def select(self, files):
        from .fakes import FakeInjection
        self.seen.append(sorted(files))
        names = ["nexus-verification"] + (["python-%s" % len(files)] if files else [])
        return FakeInjection(names=names, brief="## skills\n- %s" % ", ".join(names),
                             tokens=8 * len(names))


def build(root, worker, skills):
    config = HarnessConfig(default_root=root, roles={"director": "fake:d", "worker": "fake:w",
                                                     "judge": "fake:j"},
                           max_steps=5, max_repairs=0, lang="es", temperature=0.0, secrets={})
    router = FakeRouter(workers=worker)
    chat = Chat(router, config, default_registry(root, config), FakeGate(), skills,
                bus=Bus())
    return chat


def test_prefix_is_byte_identical_across_steps(failures):
    """El contrato de la cache: el byte 0 no cambia aunque el turno descubra ficheros."""
    with TempProject({"a.py": "x = 1\n", "b.py": "y = 2\n"}) as root:
        worker = ScriptedProvider([
            reply("leo a", tools=[("c1", "read_file", {"path": "a.py"})]),
            reply("leo b", tools=[("c2", "read_file", {"path": "b.py"})]),
            reply("terminado"),
        ])
        skills = GrowingSkills()
        chat = build(root, worker, skills)
        chat.new("prefijo")
        chat.send("mira a y b")
        systems = [call["messages"][0]["content"] for call in worker.calls]
        check("hubo tres llamadas", len(systems), 3, failures)
        check("el system es identico en las tres", len(set(systems)), 1, failures)
        check("y no esta vacio", bool(systems[0]), True, failures)
        deltas = [row["content"] for call in worker.calls for row in call["messages"]
                  if str(row.get("content") or "").startswith(DELTA_MARKER)]
        check("el contexto que cambio viaja como delta", len(deltas) >= 1, True, failures)
        check("las skills se pidieron en cada paso", len(skills.seen), 3, failures)
        check("hay mas de un delta distinto", len(set(deltas)) >= 2, True, failures)
        for call in worker.calls:
            local = [row["content"] for row in call["messages"]
                     if str(row.get("content") or "").startswith(DELTA_MARKER)]
            check("una llamada no repite el mismo delta", len(local), len(set(local)), failures)


def test_a_delta_never_rewrites_the_prefix(failures):
    prefix = build_prefix([("rules", "reglas"), ("facts", "raiz")])
    window = TurnWindow(prefix)
    first = window.messages([])[0].content
    window.note("skills", "una skill")
    window.note("skills", "otra skill")
    check("el system sigue siendo el prefijo", window.messages([])[0].content, first, failures)
    check("los deltas van al final", len(window.deltas), 2, failures)
    check("repetir el mismo delta no lo duplica", window.note("skills", "otra skill"), False,
          failures)


def test_section_budget_clips_and_says_so(failures):
    prefix = build_prefix([("rules", "palabra " * 4000), ("facts", "raiz: /tmp")])
    rules = prefix.sections[0]
    check("la seccion se marca recortada", rules.clipped, True, failures)
    check("y lo declara en el texto", "recortado por presupuesto" in prefix.text, True, failures)
    check("las demas secciones no se tocan", prefix.sections[1].clipped, False, failures)


def test_calibration_learns_the_models_bias(failures):
    """El error del contador baja del 5 % cuando el modelo ya tiene muestras."""
    with tempfile.TemporaryDirectory(prefix="token-cal-") as workspace:
        cal = Calibration(Path(workspace) / "cal.json")
        text = ("def arreglar(fichero, linea):\n    return fichero + linea\n" * 12)
        base = estimate(text)
        real = int(base * 1.28)
        for _sample in range(20):
            cal.observe("modelo-x", base, real)
        corrected = count(text, "modelo-x", cal)
        error = abs(corrected - real) / float(real)
        check("el error baja del 5 %% (%.1f %%)" % (100 * error), error < 0.05, True, failures)
        naive_error = abs(base - real) / float(real)
        check("y mejora al cociente crudo", naive_error > error, True, failures)
        check("un modelo sin muestras no hereda nada", cal.factor("otro"), 1.0, failures)


def test_a_blocked_skill_router_does_not_break_the_turn(failures):
    """Sin skills se trabaja; un router que lanza es una observacion, no un turno caido."""
    from ..turn_context import inject_skills

    class Exploding:
        def select(self, files):
            raise RuntimeError("catalogo roto")

    events = []
    text, tokens = inject_skills(Exploding(), ["a.py"], lambda kind, detail, **kw:
                                 events.append((kind, kw)))
    check("no hay bloque", text, "", failures)
    check("ni tokens", tokens, 0, failures)
    check("y el fallo se declara", events and events[0][0] == "skills.injected", True, failures)


def run():
    failures = []
    test_prefix_is_byte_identical_across_steps(failures)
    test_a_delta_never_rewrites_the_prefix(failures)
    test_section_budget_clips_and_says_so(failures)
    test_calibration_learns_the_models_bias(failures)
    test_a_blocked_skill_router_does_not_break_the_turn(failures)
    return failures
