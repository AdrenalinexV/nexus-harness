"""The triad: a red gate wakes the worker, a green one closes the turn.

Measured here with the REAL gate (protocol lint + line law + a real test command) and a scripted
model, so what passes is the loop's logic:

* attempt 1 is a plausible sentence and nothing else -- the gate says red, the loop repairs without
  asking anyone;
* attempt 2 patches the bug, the gate goes green, the judge approves, the run exits 0;
* a worker that never repairs ends at exit 10, with the repair count it actually spent.
"""
from .fakes import FakeRouter, ScriptedProvider, ScriptedSkills, TempProject, reply
from ..config import HarnessConfig
from ..events import Bus
from ..gate import Gate
from ..judge import Judge
from ..tools import default_registry
from ..triad_loop import Triad

TEST_COMMAND = 'python -c "import calc, sys; sys.exit(0 if calc.add(2, 3) == 5 else 1)"'
PATCH = reply(tools=[("c1", "patch", {"path": "calc.py", "search": "return a - b",
                                     "replace": "return a + b"})])


def config_for(root, **overrides):
    values = dict(default_root=root, roles={"director": "fake:d", "worker": "fake:w",
                                            "judge": "fake:j"},
                  test_command=TEST_COMMAND, max_steps=6, max_repairs=2, lang="es",
                  temperature=0.0, secrets={})
    values.update(overrides)
    return HarnessConfig(**values)


def build(root, worker, judge=None, **overrides):
    config = config_for(root, **overrides)
    router = FakeRouter(workers=worker, judge=judge)
    skills = ScriptedSkills()
    bus = Bus(clock=lambda: 0.0)
    triad = Triad(router, config, registry=default_registry(root, config),
                  gate=Gate(root, config), judge=Judge(router, "es"),
                  skills=skills, bus=bus)
    return triad, bus, skills


def test_repair_then_green(failures):
    with TempProject() as root:
        worker = ScriptedProvider([reply("Hecho, debería funcionar."), PATCH,
                                   reply("Corregido: el test lo demuestra.")])
        triad, bus, skills = build(root, worker)
        result = triad.run("arregla add() para que sume")
        check("the run is green", result.ok, True, failures)
        check("exit 0", result.exit, 0, failures)
        check("one repair was spent", result.repairs, 1, failures)
        check("the file actually changed", "a + b" in (root / "calc.py").read_text(encoding="utf-8"),
              True, failures)
        kinds = [event["kind"] for event in bus.all()]
        check("the gate spoke twice", kinds.count("gate.verdict"), 2, failures)
        check("the loop repaired", "repair" in kinds, True, failures)
        check("the tool ran", "tool.call" in kinds, True, failures)
        check("the judge spoke", "judge.verdict" in kinds, True, failures)
        check("skills were injected per call", len(skills.seen) >= 3, True, failures)
        check("and the last injection knows the touched file",
              any("calc.py" in files for files in skills.seen), True, failures)
        check("the worker was asked with tools", bool(worker.calls[0]["tools"]), True, failures)
        check("the judge saw the gate evidence", result.judgement.get("verdict"), "approve",
              failures)


def test_stuck_worker_ends_red(failures):
    with TempProject() as root:
        worker = ScriptedProvider([], default=reply("No pienso tocar nada."))
        triad, bus, _skills = build(root, worker, max_repairs=1)
        result = triad.run("arregla add()")
        check("a worker that never repairs ends red", result.exit, 10, failures)
        check("and not ok", result.ok, False, failures)
        check("with one repair spent", result.repairs, 1, failures)
        check("the gate was asked twice", [event["kind"] for event in bus.all()]
              .count("gate.verdict"), 2, failures)
        check("the judge never ran on a red gate",
              "judge.verdict" in [event["kind"] for event in bus.all()], False, failures)
        check("the file is untouched", "a - b" in (root / "calc.py").read_text(encoding="utf-8"),
              True, failures)


def test_judge_rejects_once(failures):
    with TempProject() as root:
        worker = ScriptedProvider([PATCH, reply("listo"), reply("listo otra vez")])
        judge = ScriptedProvider([reply('{"verdict": "reject", "reason": "no hay prueba"}'),
                                  reply('{"verdict": "approve", "reason": "ahora sí"}')])
        triad, _bus, _skills = build(root, worker, judge=judge, max_repairs=2)
        result = triad.run("arregla add()")
        check("a rejection spends a repair and the run still closes green", result.ok, True,
              failures)
        check("the final verdict is approve", result.judgement.get("verdict"), "approve", failures)


def test_unready_role_is_reported(failures):
    with TempProject() as root:
        config = config_for(root)
        worker = ScriptedProvider([reply("x")])
        worker.ready = False
        router = FakeRouter(workers=worker)
        bus = Bus()
        triad = Triad(router, config, registry=default_registry(root, config),
                      gate=Gate(root, config), judge=Judge(router, "es"),
                      skills=ScriptedSkills(), bus=bus)
        result = triad.run("nada")
        check("a blocked worker ends red instead of pretending", result.exit, 10, failures)
        check("and the reason is on the record",
              "worker.blocked" in [event["kind"] for event in bus.all()], True, failures)


def test_closing_summary_when_steps_run_out(failures):
    """14 steps of tool calls and no sentence leaves the judge nothing to approve: ask for two lines."""
    with TempProject({"calc.py": "def add(a, b):\n    return a + b\n"}) as root:
        worker = ScriptedProvider([reply(tools=[("c1", "read_file", {"path": "calc.py"})]),
                                   reply("Resumen: no hacía falta cambiar nada; lo demuestra el test.")])
        triad, bus, _skills = build(root, worker, max_steps=1)
        result = triad.run("verifica que add suma")
        check("the run still closes green", result.ok, True, failures)
        check("the summary is not empty", bool(result.summary), True, failures)
        check("the closing call was offered no tools", worker.calls[1]["tools"], [], failures)
        check("and it is on the record", "worker.close" in [event["kind"] for event in bus.all()],
              True, failures)


def test_gate_sees_a_same_size_fix(failures):
    """The trap: `a - b` -> `a + b` keeps the size, so stale bytecode passes Python's cache check."""
    import os
    with TempProject() as root:
        config = config_for(root)
        gate = Gate(root, config)
        check("buggy code is red", gate.run(["calc.py"]).ok, False, failures)
        stamp = os.stat(root / "calc.py").st_mtime
        (root / "calc.py").write_bytes(b"def add(a, b):\r\n    return a + b\r\n")
        os.utime(root / "calc.py", (stamp, stamp))
        verdict = gate.run(["calc.py"])
        check("a same-size fix in the same second is green", verdict.ok, True, failures)


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def run():
    failures = []
    for test in (test_repair_then_green, test_stuck_worker_ends_red, test_judge_rejects_once,
                 test_unready_role_is_reported, test_closing_summary_when_steps_run_out,
                 test_gate_sees_a_same_size_fix):
        test(failures)
    return failures
