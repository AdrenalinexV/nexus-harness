"""Stand-ins that make a suite deterministic: a scripted model, a fake router, a temp project.

The loop cannot tell `ScriptedProvider` from a real transport -- same `chat` signature, same `Reply`.
That is the point: a green suite measures the loop's logic, not whether LM Studio happened to be
running at 3 a.m.
"""
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..message import Message, Reply, ToolCall, Usage


def reply(text="", tools=(), reasoning="", prompt=10, completion=5, model="fake:scripted"):
    calls = [ToolCall(id=call[0], name=call[1], arguments=call[2],
                      raw_arguments=json.dumps(call[2])) for call in tools]
    return Reply(text=text, tool_calls=calls, reasoning=reasoning,
                 usage=Usage(prompt=prompt, completion=completion), model=model)


@dataclass
class ScriptedProvider:
    """Replies in order. Running out is a failure of the script, not a silent empty answer."""

    script: list = field(default_factory=list)
    model: str = "fake:scripted"
    calls: list = field(default_factory=list)
    default: object = None
    supports_tools: bool = True

    def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        self.calls.append({"messages": [message.to_openai() for message in messages],
                           "tools": [tool["function"]["name"] for tool in tools or []]})
        if self.script:
            return self.script.pop(0)
        if self.default is not None:
            return self.default
        return reply(text="(script agotado)")

    def models(self, timeout=1):
        return [self.model]


@dataclass
class RoleInfo:
    """Same fields as `providers.RoleInfo`, so `info.__dict__` reads the same in both."""

    role: str
    spec: str
    vendor: str = "fake"
    model: str = "fake:scripted"
    ready: bool = True
    why_not_ready: str = ""


class FakeRouter:
    """A router with no network: every role resolves to its own scripted provider."""

    def __init__(self, workers=None, director=None, judge=None):
        self._providers = {
            "director": director or ScriptedProvider([reply("1. arreglar calc.py")]),
            "worker": workers or ScriptedProvider([reply("nada que hacer")]),
            "judge": judge or ScriptedProvider(
                [reply('{"verdict": "approve", "reason": "el gate está verde"}')]),
        }
        self.swaps = []

    def role(self, role):
        return self._providers[role]

    def info(self, role):
        provider = self._providers[role]
        return RoleInfo(role=role, spec="fake:%s" % role, model=provider.model,
                        ready=getattr(provider, "ready", True))

    def swap(self, role, spec):
        self.swaps.append((role, spec))
        return self.info(role)

    def describe(self):
        return {role: self.info(role).__dict__ for role in self._providers}

    def probe(self):
        return {"lmstudio": [], "ollama": []}


@dataclass
class FakeInjection:
    names: list = field(default_factory=list)
    brief: str = ""
    tokens: int = 0
    available: bool = True
    note: str = ""

    def as_dict(self):
        return {"names": list(self.names), "tokens": self.tokens,
                "available": self.available, "note": self.note}


class ScriptedSkills:
    """Records which file sets asked for skills, so a test can prove injection happened per call."""

    def __init__(self, names=("nexus-verification",)):
        self.seen = []
        self.names = list(names)

    def select(self, files):
        self.seen.append(sorted(files))
        return FakeInjection(names=list(self.names), brief="## reglas\n- verde o nada",
                             tokens=12)


class FakeGate:
    """A gate whose verdict the test decides, so the loop can be measured without a real repo."""

    def __init__(self, verdicts=None, ok=True):
        self.verdicts = list(verdicts or [])
        self.ok = ok
        self.calls = 0

    def run(self, touched=None):
        from ..gate import Check, Verdict
        self.calls += 1
        if self.verdicts:
            return self.verdicts.pop(0)
        checks = [Check("lint", self.ok, "0 findings", exit=0 if self.ok else 10),
                  Check("tests", self.ok, "exit 0", exit=0 if self.ok else 10)]
        return Verdict(ok=self.ok, exit=0 if self.ok else 10, checks=checks,
                       failures="" if self.ok else "tests: exit 1", at="2026-10-24T00:00:00Z")


class TempProject:
    """A throwaway project root with a governance file, so `rules_lint` grades something real."""

    def __init__(self, files=None):
        self.files = dict(files or {"calc.py": "def add(a, b):\n    return a - b\n"})
        self.root = None

    def __enter__(self):
        self.root = Path(tempfile.mkdtemp(prefix="nexus-harness-test-"))
        (self.root / ".ai").mkdir(parents=True, exist_ok=True)
        (self.root / ".ai" / "PROJECT_RULES.md").write_text(
            "# rules\n\n## APPROVED DEPENDENCIES\n\n- nexus -- engine\n", encoding="utf-8")
        for name, content in self.files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return self.root

    def __exit__(self, *_exc):
        shutil.rmtree(self.root, ignore_errors=True)
        return False


def last_user(messages):
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return ""


def digests(messages):
    return [Message.from_openai(item).role for item in messages]
