"""Chat: a turn that only talks must not run the gate; a turn that edits must, and repair itself.

Measured with the fake gate so the count is exact, and with the real toolbox so the patch actually lands
on disk. The conversation is persisted and reloaded, because a desktop chat that forgets is a demo.
"""
from .fakes import FakeRouter, FakeGate, ScriptedProvider, ScriptedSkills, TempProject, reply
from .. import checkpoint
from ..chat import Chat
from ..config import HarnessConfig
from ..platform.events import Bus
from ..gate import Check, Verdict
from ..memory import Memory
from ..toolbox import file_ops as files
from ..tools import default_registry
from ..platform.transcripts import Transcripts
from ..judge import Judge


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def verdict(ok, name="tests"):
    from ..gate import EXIT_GREEN, EXIT_RED
    check_row = Check(name, ok, "forced", exit=EXIT_GREEN if ok else EXIT_RED)
    return Verdict(ok=ok, exit=EXIT_GREEN if ok else EXIT_RED, checks=[check_row],
                   failures="" if ok else "tests: exit 1", at="2026-10-24T00:00:00Z")


def build(root, worker, gate, judge=None, memory=None):
    config = HarnessConfig(default_root=root, roles={"director": "fake:d", "worker": "fake:w",
                                                     "judge": "fake:j"},
                           max_steps=4, max_repairs=1, lang="es", temperature=0.0, secrets={})
    router = FakeRouter(workers=worker, judge=judge)
    bus = Bus()
    chat = Chat(router, config, default_registry(root, config), gate, ScriptedSkills(),
                bus=bus, memory=memory, transcripts=Transcripts(root), judge=judge and
                Judge(router, "es"))
    return chat, bus


def test_talk_only_does_not_gate(failures):
    with TempProject() as root:
        worker = ScriptedProvider([reply("Hola. ¿Qué quieres que haga?")])
        gate = FakeGate()
        memory = Memory(root / "memory.md")
        memory.add("El operador prefiere respuestas cortas")
        chat, bus = build(root, worker, gate, memory=memory)
        session = chat.new("prueba")
        turn = chat.send("hola")
        check("the turn answers", turn["reply"], "Hola. ¿Qué quieres que haga?", failures)
        check("and does not run the gate", gate.calls, 0, failures)
        check("the system prompt carries the memory", "Memoria del operador" in
              worker.calls[0]["messages"][0]["content"], True, failures)
        check("the conversation is persisted", (root / ".nexus" / "harness" / "chat" /
                                                (session["id"] + ".json")).is_file(), True,
              failures)
        saved = chat.transcripts.load(session["id"])
        check("with both messages", [row["role"] for row in saved["messages"]],
              ["user", "assistant"], failures)
        check("and a count of turns", saved["turns"], 1, failures)


def test_edit_runs_gate_and_repairs(failures):
    with TempProject() as root:
        patch = reply(tools=[("c1", "patch_replace", {
            "path": "calc.py", "old_string": "return a - b", "new_string": "return a + b"})])
        worker = ScriptedProvider([patch, reply("Corregido: el test lo demuestra.")])
        gate = FakeGate(verdicts=[verdict(False), verdict(True)])
        judge = ScriptedProvider([reply('{"verdict": "approve", "reason": "verde"}')])
        chat, bus = build(root, worker, gate, judge=judge)
        chat.new("arregla")
        turn = chat.send("arregla la resta")
        check("the patch landed", "a + b" in files.read_text(root / "calc.py"), True, failures)
        check("the gate ran twice (red, then green)", gate.calls, 2, failures)
        check("one repair was spent", turn["repairs"], 1, failures)
        check("the turn is green", turn["exit"], 0, failures)
        check("the judge was asked only after the green gate",
              turn["judgement"].get("verdict"), "approve", failures)
        check("the tool call is in the history",
              any(row["role"] == "tool" for row in [m.to_openai() for m in chat.history]), True,
              failures)
        check("the repair is on the record",
              "chat.repair" in [event["kind"] for event in bus.all()], True, failures)


def test_a_turn_leaves_an_undoable_checkpoint(failures):
    """El turno deja diario; `undo` devuelve el codigo y **no** toca la conversacion."""
    with TempProject() as root:
        patch = reply(tools=[("c1", "patch_replace", {
            "path": "calc.py", "old_string": "return a - b", "new_string": "return a + b"})])
        worker = ScriptedProvider([patch, reply("Hecho.")])
        chat, _bus = build(root, worker, FakeGate(verdicts=[verdict(True)]))
        session = chat.new("con diario")
        before = files.read_text(root / "calc.py")
        turn = chat.send("suma en vez de restar")
        check("el turno nombra su diario", bool(turn["checkpoint"]), True, failures)
        check("el diario anota el fichero tocado", [entry["path"] for entry in chat.checkpoint.entries],
              ["calc.py"], failures)
        check("y el diario queda desarmado al cerrar el turno", checkpoint.active(), None, failures)
        transcript = root / ".nexus" / "harness" / "chat" / (session["id"] + ".json")
        check("la conversacion se persistio fuera del diario", transcript.is_file(), True, failures)
        report = chat.checkpoint.undo()
        check("undo restaura los bytes de antes del turno", files.read_text(root / "calc.py"), before,
              failures)
        check("y el fichero habia cambiado durante el turno", before != "def add(a, b):\n    return a + b\n",
              True, failures)
        check("y lo declara", (report["ok"], report["restored"]), (True, 1), failures)
        check("sin llevarse la conversacion por delante", transcript.is_file(), True, failures)


def test_stop_and_reload(failures):
    with TempProject() as root:
        worker = ScriptedProvider([reply("primero"), reply("segundo")])
        chat, _bus = build(root, worker, FakeGate())
        session = chat.new("dos turnos")
        chat.send("uno")
        chat.send("dos")
        check("two turns are stored", chat.transcripts.load(session["id"])["turns"], 2, failures)
        chat.stop()
        check("stop is observable", chat.stopped, True, failures)
        other, _bus2 = build(root, ScriptedProvider([reply("otra charla")]), FakeGate())
        loaded = other.load(session["id"])
        check("a conversation reloads", loaded["id"], session["id"], failures)
        check("with its four messages", len(other.history), 4, failures)
        check("and a new send clears the stop flag",
              other.send("tres")["stopped"], False, failures)


def test_project_survives_a_state_read(failures):
    """Opening a conversation in another project must survive the cockpit's own polling."""
    from ..cockpit import Cockpit
    with TempProject() as root:
        (root / "otro").mkdir()
        (root / "otro" / "calc.py").write_text("x = 1\n", encoding="utf-8")
        config = HarnessConfig(default_root=root, workspace=root, secrets={},
                               roles={"director": "fake:d", "worker": "fake:w", "judge": "fake:j"})
        cockpit = Cockpit(config)
        cockpit.router = FakeRouter(workers=ScriptedProvider([reply("hola")]))
        session = cockpit.new_chat("otra", project="otro")
        cockpit.state()
        cockpit.chat_state()
        chat = cockpit.chat_for()
        check("the chat keeps its project", str(chat.config.default_root),
              str(root / "otro"), failures)
        check("and its session", chat.session["id"], session["id"], failures)


def run():
    failures = []
    test_project_survives_a_state_read(failures)
    test_talk_only_does_not_gate(failures)
    test_edit_runs_gate_and_repairs(failures)
    test_a_turn_leaves_an_undoable_checkpoint(failures)
    test_stop_and_reload(failures)
    return failures
