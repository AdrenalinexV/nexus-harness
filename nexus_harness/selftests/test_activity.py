"""La barra de estado en vivo: que diga la fase real, y que no diga "en reposo" cuando hay trabajo.

Es una funcion pura de tres cosas: los eventos del bus, si el motor esta ocupado y el ultimo turno. Por
eso se puede medir sin navegador y sin esperas: se le dan los eventos y se mira que contesta.
"""
from .. import activity
from ..config import HarnessConfig


def check(name, got, expect, failures):
    if got != expect:
        failures.append("%s: %r, esperaba %r" % (name, got, expect))


def ev(seq, kind, detail="", **payload):
    return {"seq": seq, "at": 0.0, "kind": kind, "detail": detail, "payload": payload}


CONFIG = HarnessConfig(max_repairs=3)


def test_idle(failures):
    state = activity.state([], running=False, config=CONFIG)
    check("idle says it is ready", state["label"].startswith("Listo"), True, failures)
    check("and never the dead word", "reposo" in state["label"].lower(), False, failures)
    check("the glyph is the green dot", state["glyph"], "🟢", failures)
    check("with the autopilot declared OFF", state["label"].endswith("Autopilot OFF"), False, failures)
    off = activity.state([], running=False, config=CONFIG, autopilot={"last": "cerrado"})
    check("an autopilot that ran and stopped is said", "Autopilot OFF" in off["label"], True, failures)


def test_live_phases(failures):
    tool = activity.state([ev(1, "tool.start", "patch", args={"path": "src/patch_v4a.py"})],
                          running=True, config=CONFIG)
    check("the tool phase is the tool", tool["phase"], "tool", failures)
    check("and it names the file", "patch_v4a.py" in tool["label"], True, failures)
    check("the pill is amber while working", tool["tone"], "warn", failures)

    repair = activity.state([ev(2, "chat.repair", "intento 2")], running=True, config=CONFIG)
    check("a repair says which of how many", "2/3" in repair["label"], True, failures)
    check("and is a repair", repair["phase"], "repair", failures)

    parallel = activity.state([ev(7, "tool.parallel", "2 llamadas en paralelo",
                                 names=["read_file", "search"])], running=True, config=CONFIG)
    check("parallel reads name their tools", "read_file + search" in parallel["label"], True,
          failures)
    noisy = activity.state([ev(8, "skills.injected", "nexus-verification"),
                            ev(9, "tool.start", "patch", args={"path": "a.py"})],
                           running=True, config=CONFIG)
    check("an injected skill list does not hide the tool in progress", "patch" in noisy["label"],
          True, failures)

    gate = activity.state([ev(3, "gate.verdict", "exit 0", verdict={"exit": 0, "checks": [
        {"name": "lint", "ok": True}, {"name": "tests", "ok": True}]})], running=True, config=CONFIG)
    check("the gate counts checks it actually ran", "2/2" in gate["label"], True, failures)

    judge = activity.state([ev(4, "judge.verdict", "approve", criteria=17)],
                           running=True, config=CONFIG)
    check("the judge names the spec criteria", "17 criterios" in judge["label"], True, failures)

    backup = activity.state([ev(5, "autonomy.backup", "backup tag")], running=False, config=CONFIG,
                            autopilot={"running": True, "project": "Nexus-Harness",
                                       "iteration": 2, "iterations": 5})
    check("a backup in progress is a phase", backup["phase"], "backup", failures)
    check("and the pill works when only the loop is busy", "backup" in backup["label"].lower(), True,
          failures)
    check("with its progress", backup["progress"]["label"], "2/5 iteraciones", failures)


def test_finished_turn(failures):
    last = {"exit": 0, "steps": 4, "repairs": 1,
            "verdict": {"ok": True, "exit": 0, "checks": [{"name": "lint", "ok": True,
                                                           "detail": "0 findings"}],
                        "failures": ""},
            "judgement": {"verdict": "approve", "reason": "verde"},
            "touched": ["src/a.py", "src/b.py"],
            "tokens": {"prompt": 900, "completion": 120, "total": 1020}}
    state = activity.state([ev(9, "chat.turn", "exit 0", turn=last)], running=False,
                           config=CONFIG, last=last, budget={"ratio": 0.18, "used": 10800})
    check("the summary is the measured result",
          state["summary"]["text"], "✅ Gate OK · Juez VERDE · Contexto 18%", failures)
    check("its tone follows the gate", state["summary"]["tone"], "ok", failures)
    check("and it is what the pill SHOWS when idle, not an empty 'Listo'",
          state["label"], "✅ Gate OK · Juez VERDE · Contexto 18%", failures)
    check("with the glyph of its result", state["glyph"], "✅", failures)
    detail = state["detail"]
    check("the popover lists the files", detail["files"], ["src/a.py", "src/b.py"], failures)
    check("and the gate checks", detail["gate"]["checks"][0]["name"], "lint", failures)
    check("and the tokens", detail["tokens"]["total"], 1020, failures)
    check("and the verdict of the judge", detail["judge"]["verdict"], "approve", failures)


def test_red_and_unmeasured(failures):
    red = {"exit": 10, "verdict": {"ok": False, "exit": 10, "checks": [], "failures": "tests: exit 1"},
           "judgement": {}, "touched": ["a.py"]}
    state = activity.state([], running=False, config=CONFIG, last=red, budget={"ratio": 0.71})
    check("a red gate is red, not 'ready'", "Gate ROJO" in state["summary"]["text"], True, failures)
    check("and the tone says so", state["summary"]["tone"], "bad", failures)
    no_gate = {"exit": 0, "steps": 2, "verdict": {}, "judgement": {}, "touched": []}
    quiet = activity.state([], running=False, config=CONFIG, last=no_gate, budget={})
    check("a turn without gate does not claim verde", "sin Gate" in quiet["summary"]["text"], True,
          failures)
    check("and no context percentage is invented", "%" in quiet["summary"]["text"], False, failures)
    fresh = activity.state([], running=False, config=CONFIG, last={"exit": 0, "steps": 0,
                                                                  "verdict": {}, "touched": []})
    check("an engine that never ran a turn does not invent one", fresh["summary"]["text"], "",
          failures)


def test_diff_of_the_turn(failures):
    """El popover dice QUE cambio: el diario del checkpoint guarda los bytes de antes."""
    import shutil
    import tempfile
    from pathlib import Path

    from ..verify import checkpoint

    root = Path(tempfile.mkdtemp(prefix="nexus-diff-"))
    try:
        target = root / "a.py"
        target.write_text("uno\ndos\ntres\n", encoding="utf-8")
        journal = checkpoint.begin(root, "turno")
        journal.record(target, b"uno\ndos\ntres\n")
        target.write_text("uno\ndos\ncuatro\nextra\n", encoding="utf-8")
        rows, totals = activity._diff_stat(root, journal.name)
        check("the file is measured", rows[0]["path"], "a.py", failures)
        check("two lines added", rows[0]["added"], 2, failures)
        check("one line removed", rows[0]["removed"], 1, failures)
        check("the totals add up", (totals["added"], totals["removed"]), (2, 1), failures)
        check("a turn with no checkpoint reports no diff", activity._diff_stat(root, ""), ([], {}),
              failures)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_public_shapes(failures):
    auto = activity.public_autopilot({"running": True, "project": "X", "iteration": 2,
                                      "iterations": 4, "queue": ["X", "Y"]})
    check("the loop is published", (auto["running"], auto["project"], auto["iterations"]),
          (True, "X", 4), failures)
    check("with its queue", auto["queue"], ["X", "Y"], failures)
    check("and no private keys", "steps_done" in auto, False, failures)
    check("criteria progress when the loop has none",
          activity.progress({}, 17)["label"], "0/17 criterios", failures)


def run():
    failures = []
    test_idle(failures)
    test_live_phases(failures)
    test_finished_turn(failures)
    test_red_and_unmeasured(failures)
    test_public_shapes(failures)
    return failures
