"""Subagents: real concurrency, a closed history, a bounded turn budget and a clean stop.

The parallelism assertion is a `threading.Barrier`, not a timer. Two children that really run at the
same time meet at the barrier and both proceed; two that run in sequence deadlock until it breaks --
so the test proves overlap instead of hoping a stopwatch agrees.

The stop assertion sends the same `threading.Event` the Detener button sets, and checks the child
returns without ever calling the model again. Cancellation that waits for a 30-second completion is
not cancellation.
"""
import threading
import time

from .fakes import FakeRouter, ScriptedProvider, TempProject, last_user, reply
from ..config import HarnessConfig
from ..tools.subagents import Delegate, SUBAGENT_SYSTEM


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


class BarrierProvider:
    """Waits for its sibling at a barrier: proof of overlap, not a measurement of wall time."""

    def __init__(self, barrier, delay=0.0):
        self.barrier = barrier
        self.delay = delay
        self.threads = set()
        self.broken = False
        self.calls = 0
        self.model = "fake:barrier"

    def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        self.calls += 1
        self.threads.add(threading.current_thread().name)
        if self.delay:
            time.sleep(self.delay)
        try:
            self.barrier.wait(timeout=8)
        except threading.BrokenBarrierError:
            self.broken = True
        return reply(text="encontrado: %s" % last_user(messages).splitlines()[1][:40])


class CountingProvider:
    """Never blocks; counts how many times a child asked the model."""

    def __init__(self):
        self.calls = 0
        self.model = "fake:counting"

    def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        self.calls += 1
        time.sleep(0.25)
        return reply(text="resumen listo")


def config_for(root, **overrides):
    values = dict(default_root=root, roles={"director": "fake:d", "worker": "fake:w",
                                            "judge": "fake:j"}, max_steps=4, max_repairs=1,
                  subagent_steps=3, max_children=3, subagent_depth=1, lang="es",
                  temperature=0.0, secrets={})
    values.update(overrides)
    return HarnessConfig(**values)


def test_parallel(failures):
    with TempProject() as root:
        provider = BarrierProvider(threading.Barrier(2))
        router = FakeRouter(workers=provider)
        delegate = Delegate(router, config_for(root), root=root)
        started = time.time()
        text, meta = delegate.run({"tasks": [{"goal": "lee a.py"}, {"goal": "lee b.py"}]})
        elapsed = time.time() - started
        check("the children overlapped (barrier met)", provider.broken, False, failures)
        check("two children reported", len(meta.get("children") or []), 2, failures)
        check("both are ok", all(item["ok"] for item in meta["children"]), True, failures)
        check("two distinct threads did the work", len(provider.threads), 2, failures)
        check("and each child is in the text", text.count("child "), 2, failures)
        check("the wall clock stayed sane", elapsed < 15, True, failures)


def test_bounded_turns(failures):
    """A child that keeps calling tools stops at subagent_steps, not at the end of the afternoon."""
    with TempProject() as root:
        router = FakeRouter(workers=ScriptedProvider([
            reply(tools=[("t%d" % index, "read_file", {"path": "calc.py"})]) for index in range(6)
        ]))
        delegate = Delegate(router, config_for(root, subagent_steps=2), root=root)
        text, meta = delegate.run({"goal": "mira calc.py para siempre"})
        check("the child stopped at its budget", meta["children"][0]["steps"], 2, failures)
        check("and it still reported", bool(text), True, failures)


def test_stop_is_immediate(failures):
    with TempProject() as root:
        stop = threading.Event()
        provider = CountingProvider()
        router = FakeRouter(workers=provider)
        delegate = Delegate(router, config_for(root), stop=stop, root=root)
        stop.set()
        text, meta = delegate.run({"goal": "algo largo"})
        check("no model call was made after stop", provider.calls, 0, failures)
        check("the child says it was stopped", "stopped" in text, True, failures)
        check("and the batch completes", len(meta.get("children") or []), 1, failures)


def test_depth_limit(failures):
    with TempProject() as root:
        delegate = Delegate(FakeRouter(), config_for(root), root=root, depth=1)
        try:
            delegate.run({"goal": "delegar otra vez"})
            failures.append("a child was allowed to delegate")
        except ValueError as exc:
            check("the refusal explains the depth", "depth" in str(exc), True, failures)


def test_toolset_is_bounded(failures):
    with TempProject() as root:
        router = FakeRouter(workers=ScriptedProvider([reply(tools=[(
            "c1", "read_file", {"path": "calc.py"})]), reply("listo: calc.py resta en vez de sumar")]))
        delegate = Delegate(router, config_for(root), root=root)
        _text, meta = delegate.run({"goal": "qué hace calc.py"})
        seen = router.role("worker").calls[0]["tools"]
        check("a read-only child gets no editing tools", "write_file" in seen, False, failures)
        check("but it can read and search", {"read_file", "search_files"} <= set(seen), True,
              failures)
        check("and no delegate tool (depth is one)", "delegate_task" in seen, False, failures)
        check("the summary came back", meta["children"][0]["ok"], True, failures)
        check("the child read a real file", "calc.py" in (meta.get("files") or []), True, failures)


def test_system_prompt_is_isolated(failures):
    with TempProject() as root:
        router = FakeRouter(workers=ScriptedProvider([reply("nada que hacer")]))
        delegate = Delegate(router, config_for(root), root=root)
        delegate.run({"goal": "inspecciona"})
        first = router.role("worker").calls[0]["messages"]
        check("the child opens with its own system prompt", first[0]["content"], SUBAGENT_SYSTEM,
              failures)
        check("and a single user brief", [row["role"] for row in first], ["system", "user"], failures)


def run():
    failures = []
    test_parallel(failures)
    test_bounded_turns(failures)
    test_stop_is_immediate(failures)
    test_depth_limit(failures)
    test_toolset_is_bounded(failures)
    test_system_prompt_is_isolated(failures)
    return failures
