"""Compactacion determinista: el transcript se condensa antes de quedarse sin sitio.

The suite measures the real module (`nexus_harness.compaction`), never a stand-in:

* below the threshold nothing happens, and that is recorded, not silent;
* a transcript over it compacts to the SAME bytes twice -- a digest that changes between runs is not
  a digest, it is a second guess;
* the head and the goal survive, the tail survives verbatim, and every `tool` message keeps the
  `tool_calls` parent that answers it: an orphan is a 400 from every OpenAI-shaped server;
* the loop actually calls it, and the run keeps going green after the cut.
"""
from .fakes import FakeGate, FakeRouter, ScriptedProvider, ScriptedSkills, TempProject, reply
from ..compaction import DIGEST_HEADER, Compactor, compact, estimate
from ..config import HarnessConfig
from ..platform.events import Bus
from ..llm.judge import Judge
from ..core.message import Message, ToolCall
from ..tools import default_registry
from ..triad_loop import Triad

BIG = "linea de relleno con el contenido suficiente para ocupar sitio\n" * 110


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def tool_turn(index, path, size=400):
    """An assistant tool call and its `tool` result, exactly as the loop writes them."""
    call = ToolCall(id="c%d" % index, name="read_file", arguments={"path": path},
                    raw_arguments='{"path": "%s"}' % path)
    return [Message(role="assistant", content="", tool_calls=[call]),
            Message(role="tool", content="x" * size, tool_call_id=call.id, name="read_file")]


def transcript(turns=6, size=400):
    messages = [Message(role="system", content="reglas " * 40),
                Message(role="user", content="OBJETIVO: arreglar calc.py")]
    for index in range(turns):
        messages += tool_turn(index, "src/mod_%d.py" % index, size)
    return messages


def digest_index(messages):
    for position, message in enumerate(messages):
        if message.role == "user" and message.text_content().startswith(DIGEST_HEADER):
            return position
    return -1


def test_estimate_is_pure(failures):
    messages = transcript(turns=2)
    check("estimate is repeatable", estimate(messages), estimate(messages), failures)
    check("a bigger transcript estimates bigger",
          estimate(transcript(turns=4))[1] > estimate(transcript(turns=1))[1], True, failures)
    check("a fresh transcript costs something", estimate(messages)[1] > 0, True, failures)


def test_below_threshold_does_nothing(failures):
    messages = transcript(turns=1)
    result = compact(messages, limit=100000, threshold=0.55)
    check("nothing is applied", result.applied, False, failures)
    check("the transcript is untouched", [m.role for m in result.messages],
          [m.role for m in messages], failures)
    check("the reason says why", result.reason, "under threshold", failures)


def test_compaction_is_deterministic(failures):
    messages = transcript(turns=6)
    first = compact(messages, limit=600, threshold=0.55, keep_tail=2)
    second = compact(messages, limit=600, threshold=0.55, keep_tail=2)
    check("it compacts", first.applied, True, failures)
    check("twice to the same bytes", [m.to_openai() for m in first.messages],
          [m.to_openai() for m in second.messages], failures)
    check("and the digest is identical", first.digest, second.digest, failures)
    check("the digest names the tool it dropped", "read_file x5" in first.digest, True, failures)
    check("and the files it saw", "src/mod_0.py" in first.digest, True, failures)


def test_keeps_head_goal_and_tail(failures):
    messages = transcript(turns=6)
    result = compact(messages, limit=600, threshold=0.55, keep_tail=2)
    check("the system message survives", result.messages[0].role, "system", failures)
    check("the goal survives", "OBJETIVO" in result.messages[1].text_content(), True, failures)
    check("the tail survives verbatim", result.messages[-1].to_openai(),
          messages[-1].to_openai(), failures)
    check("it shrank", result.after < result.before, True, failures)
    check("with the dropped count on the record", result.dropped, 10, failures)
    check("and the digest sits between the goal and the tail", digest_index(result.messages), 2,
          failures)


def test_never_orphans_a_tool_message(failures):
    """An odd tail would land on a `tool` message; the cut has to walk back to its assistant."""
    result = compact(transcript(turns=6), limit=600, threshold=0.55, keep_tail=3)
    parents, orphan = set(), []
    for message in result.messages:
        if message.role == "assistant":
            parents.update(call.id for call in message.tool_calls or ())
        elif message.role == "tool" and message.tool_call_id not in parents:
            orphan.append(message.tool_call_id)
    check("no tool message is left without its parent", orphan, [], failures)
    check("and the kept tail starts on an assistant",
          result.messages[digest_index(result.messages) + 1].role, "assistant", failures)


def test_zero_limit_is_unmeasured(failures):
    result = compact(transcript(turns=6), limit=0)
    check("no budget means no compaction", result.applied, False, failures)
    check("and it is not a percentage", result.ratio, None, failures)
    check("the reason is explicit", "unmeasured" in result.reason, True, failures)


def test_compactor_rewrites_the_live_list(failures):
    messages = transcript(turns=6)
    compactor = Compactor(limit=600, threshold=0.55, keep_tail=2)
    result = compactor.maybe(messages)
    check("it applied", result.applied, True, failures)
    check("the live list was rewritten", len(messages), len(result.messages), failures)
    check("the count is kept", compactor.count, 1, failures)
    check("the history keeps the record", len(compactor.history), 1, failures)
    check("a second pass under the threshold does nothing", compactor.maybe(messages).applied, False,
          failures)
    check("a disabled compactor says so", Compactor(enabled=False).maybe(messages).reason,
          "compaction disabled", failures)


def test_triad_compacts_before_the_relay(failures):
    with TempProject({"notas.txt": BIG, "calc.py": "def add(a, b):\n    return a + b\n"}) as root:
        config = HarnessConfig(default_root=root, test_command="python -c \"pass\"",
                               max_steps=6, max_repairs=1, budget_limit=600, compact_threshold=0.55,
                               roles={"director": "fake:d", "worker": "fake:w", "judge": "fake:j"},
                               lang="es", temperature=0.0, secrets={})
        worker = ScriptedProvider([reply(tools=[("c1", "read_file", {"path": "notas.txt"})]),
                                   reply(tools=[("c2", "read_file", {"path": "notas.txt"})]),
                                   reply("Listo: verificado con el gate.")])
        judge = ScriptedProvider([reply('{"verdict": "approve", "reason": "verde"}')])
        router = FakeRouter(workers=worker, judge=judge)
        bus = Bus(clock=lambda: 0.0)
        compactor = Compactor(limit=600, threshold=0.55, keep_tail=2)
        triad = Triad(router, config, registry=default_registry(root, config), gate=FakeGate(ok=True),
                      judge=Judge(router, "es"), skills=ScriptedSkills(), bus=bus,
                      compactor=compactor)
        result = triad.run("lee las notas y confirma")
        check("the run stays green after the cut", result.ok, True, failures)
        check("the compactor actually ran", compactor.count >= 1, True, failures)
        kinds = [event["kind"] for event in bus.all()]
        check("the cockpit saw it", "context.compacted" in kinds, True, failures)
        seen = worker.calls[-1]["messages"]
        check("the transcript the worker saw was compacted", len(seen) < 8, True, failures)
        check("and it carries the digest",
              any(DIGEST_HEADER in str(row.get("content")) for row in seen), True, failures)


def test_chat_compacts_its_history(failures):
    """The conversation loop is the other place a window fills; it compacts the same way."""
    from ..chat import Chat
    from ..platform.transcripts import Transcripts
    with TempProject({"notas.txt": BIG, "calc.py": "def add(a, b):\n    return a + b\n"}) as root:
        config = HarnessConfig(default_root=root, test_command="python -c \"pass\"", max_steps=6,
                               max_repairs=1, budget_limit=600, compact_threshold=0.55,
                               roles={"director": "fake:d", "worker": "fake:w", "judge": "fake:j"},
                               lang="es", temperature=0.0, secrets={})
        worker = ScriptedProvider([reply(tools=[("c1", "read_file", {"path": "notas.txt"})]),
                                   reply(tools=[("c2", "read_file", {"path": "notas.txt"})]),
                                   reply("Leídas las notas.")])
        router = FakeRouter(workers=worker)
        bus = Bus(clock=lambda: 0.0)
        chat = Chat(router, config, default_registry(root, config), FakeGate(ok=True),
                    ScriptedSkills(), bus=bus, transcripts=Transcripts(root))
        chat.compactor = Compactor(limit=600, threshold=0.55, keep_tail=2)
        chat.new("notas")
        turn = chat.send("lee las notas")
        check("the turn answers", turn["reply"], "Leídas las notas.", failures)
        check("the history was compacted", chat.compactor.count >= 1, True, failures)
        check("the cockpit saw it", "context.compacted" in [e["kind"] for e in bus.all()], True,
              failures)
        check("and the digest is in the persisted history",
              any(DIGEST_HEADER in str(row.to_openai().get("content")) for row in chat.history), True,
              failures)


def run():
    failures = []
    for test in (test_estimate_is_pure, test_below_threshold_does_nothing,
                 test_compaction_is_deterministic, test_keeps_head_goal_and_tail,
                 test_never_orphans_a_tool_message, test_zero_limit_is_unmeasured,
                 test_compactor_rewrites_the_live_list, test_triad_compacts_before_the_relay,
                 test_chat_compacts_its_history):
        test(failures)
    return failures
