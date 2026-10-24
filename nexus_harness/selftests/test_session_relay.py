"""Auto-relay: a three-phase task that crosses a session boundary and still ends green.

The scenario is the one every harness fails today. Phase 1 runs, the meter crosses 70 %, and instead
of stopping the run:

* the protocol's state records the budget and the closed phase with the exits the gate observed;
* `NEXT_SESSION_PROMPT.md` is generated from that state;
* `session_01` is archived and `session_02` opens with the prompt as its first user message;
* the loop keeps going through phases 2 and 3 in the new session.

No human, no restart, same run.
"""
from .fakes import FakeRouter, ScriptedProvider, ScriptedSkills, TempProject, reply
from ..config import HarnessConfig
from ..events import Bus
from ..gate import Gate
from ..judge import Judge
from ..session_relay import BudgetMeter, SessionRelay, SessionStore
from ..tools import default_registry
from ..triad_loop import Triad

TEST_COMMAND = 'python -c "import calc, sys; sys.exit(0 if calc.add(2, 3) == 5 else 1)"'
PHASES = [{"id": "f1", "title": "primera", "items": ["mide"]},
          {"id": "f2", "title": "segunda", "items": ["sigue"]},
          {"id": "f3", "title": "tercera", "items": ["cierra"]}]


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def test_meter(failures):
    from ..message import Usage
    meter = BudgetMeter(limit=100, threshold=0.7)
    check("a fresh meter is unmeasured", meter.state()["state"], "unmeasured", failures)
    check("and does not relay", meter.state()["should_relay"], False, failures)
    meter.observe(Usage(prompt=0, completion=0))
    check("a reply with no usage does not become a zero", meter.state()["state"], "unmeasured",
          failures)
    meter.observe(Usage(prompt=60, completion=11))
    check("71/100 crosses 70 %", meter.state()["should_relay"], True, failures)
    zero = BudgetMeter(limit=0, threshold=0.7)
    zero.observe(Usage(prompt=10, completion=1))
    check("a limit of zero is unmeasured, not 100 %", zero.state()["state"], "unmeasured",
          failures)


def test_store(failures):
    with TempProject() as root:
        store = SessionStore(root)
        store.save({"id": "session_01", "status": "active"})
        check("the first id is session_01", store.next_id(), "session_02", failures)
        archived = store.archive("session_01")
        check("archiving moves the file out of the live folder", archived.is_file(), True, failures)
        check("and leaves the live folder empty", store.ids(), [], failures)
        check("the archived copy says so", store.load("session_01"), None, failures)


def test_three_phases_cross_a_cut(failures):
    with TempProject({"calc.py": "def add(a, b):\n    return a + b\n"}) as root:
        config = HarnessConfig(default_root=root, test_command=TEST_COMMAND, max_steps=3,
                               max_repairs=1, budget_limit=100, relay_threshold=0.70,
                               roles={"director": "fake:d", "worker": "fake:w",
                                      "judge": "fake:j"}, lang="es", temperature=0.0,
                               secrets={})
        worker = ScriptedProvider([reply("fase primera", prompt=60, completion=20),
                                   reply("fase segunda", prompt=1, completion=0),
                                   reply("fase tercera", prompt=1, completion=0)])
        judge = ScriptedProvider([reply('{"verdict": "approve", "reason": "verde"}')] * 3)
        router = FakeRouter(workers=worker, judge=judge)
        bus = Bus()
        relay = SessionRelay(root, goal="tres fases", config=config, bus=bus, phases=PHASES)
        relay.start()
        triad = Triad(router, config, registry=default_registry(root, config),
                      gate=Gate(root, config), judge=Judge(router, "es"),
                      skills=ScriptedSkills(), bus=bus, relay=relay)
        result = triad.run("tres fases", phases=PHASES)
        check("the whole task ends green", result.ok, True, failures)
        check("with exit 0", result.exit, 0, failures)
        check("all three phases closed", [phase["ok"] for phase in result.phases],
              [True, True, True], failures)
        check("exactly one handover happened", len(relay.handovers), 1, failures)
        if relay.handovers:
            check("session_01 handed over to session_02",
                  (relay.handovers[0].from_session, relay.handovers[0].to_session),
                  ("session_01", "session_02"), failures)
        check("the protocol closed the phases with exit codes", _closed_phases(root), 3, failures)
        check("the relay prompt exists", (root / ".nexus" / "NEXT_SESSION_PROMPT.md").is_file(),
              True, failures)
        prompt = (root / ".nexus" / "NEXT_SESSION_PROMPT.md").read_text(encoding="utf-8")
        check("the prompt carries the goal", "tres fases" in prompt, True, failures)
        check("the prompt says where the work stands", any(word in prompt for word in
                                                           ("Fase", "fase", "phase", "Phase")),
              True, failures)
        check("session_02 is the live one", relay.store.ids(), ["session_02"], failures)
        check("session_01 is archived",
              (root / ".nexus" / "harness" / "sessions" / "archive" / "session_01.json").is_file(),
              True, failures)
        check("the cockpit saw the relay", "session.relay" in [event["kind"] for event in bus.all()],
              True, failures)
        check("and the worker kept working after it", len(worker.calls) >= 3, True, failures)
        last = relay.store.load(relay.store.ids()[-1]) or {}
        check("the final session was closed with the run's exit",
              (last.get("status"), last.get("exit")), ("closed", 0), failures)


def test_relay_on_a_tool_call_leaves_no_orphan(failures):
    """A handover that lands on a reply asking for a tool must not answer that call in the new session.

    An orphan `tool` message with no `tool_calls` in front of it is rejected by every OpenAI-shaped
    server, so the next session would start with a 400 instead of a prompt.
    """
    with TempProject({"calc.py": "def add(a, b):\n    return a + b\n"}) as root:
        config = HarnessConfig(default_root=root, test_command=TEST_COMMAND, max_steps=3,
                               max_repairs=1, budget_limit=100, relay_threshold=0.70,
                               roles={"director": "fake:d", "worker": "fake:w",
                                      "judge": "fake:j"}, lang="es", temperature=0.0,
                               secrets={})
        worker = ScriptedProvider([
            reply(tools=[("c1", "read_file", {"path": "calc.py"})], prompt=60, completion=20),
            reply("segunda fase ya en la sesión nueva", prompt=1, completion=0)])
        judge = ScriptedProvider([reply('{"verdict": "approve", "reason": "verde"}')] * 2)
        router = FakeRouter(workers=worker, judge=judge)
        bus = Bus()
        relay = SessionRelay(root, goal="dos fases", config=config, bus=bus, phases=PHASES[:2])
        relay.start()
        triad = Triad(router, config, registry=default_registry(root, config),
                      gate=Gate(root, config), judge=Judge(router, "es"),
                      skills=ScriptedSkills(), bus=bus, relay=relay)
        result = triad.run("dos fases", phases=PHASES[:2])
        check("the run still closes green", result.ok, True, failures)
        check("one handover happened", len(relay.handovers), 1, failures)
        roles = [message["role"] for message in worker.calls[1]["messages"]]
        check("the new session starts with a system and a user message only", roles,
              ["system", "user"], failures)
        check("and the drop is on the record",
              "worker.relay" in [event["kind"] for event in bus.all()], True, failures)


def _closed_phases(root):
    import json
    state = root / ".nexus" / "RELAY_STATE.json"
    if not state.is_file():
        return 0
    data = json.loads(state.read_text(encoding="utf-8"))
    return sum(1 for phase in data.get("phases") or [] if phase.get("status") == "done")


def run():
    failures = []
    test_meter(failures)
    test_store(failures)
    test_three_phases_cross_a_cut(failures)
    test_relay_on_a_tool_call_leaves_no_orphan(failures)
    return failures
