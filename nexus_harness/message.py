"""The five words a model call is made of, transport-independent.

A `Message` is what the loop keeps; `to_openai()` is what a wire wants. Keeping those two apart is why
three transports can share one loop: the loop never sees a provider's shape, and a transport that
needs a different shape (`tool_use` blocks, native `thinking`) converts instead of leaking.
"""
import json
from dataclasses import dataclass, field

ROLES = ("system", "user", "assistant", "tool")


@dataclass
class ToolCall:
    """One function the model asked for, with its arguments already parsed when that is possible."""

    id: str
    name: str
    arguments: dict = field(default_factory=dict)
    raw_arguments: str = ""
    parse_error: str = ""

    @classmethod
    def from_openai(cls, payload):
        function = payload.get("function") or {}
        raw = function.get("arguments")
        raw_text = raw if isinstance(raw, str) else json.dumps(raw or {})
        arguments, error = {}, ""
        try:
            parsed = json.loads(raw_text) if raw_text.strip() else {}
            if isinstance(parsed, dict):
                arguments = parsed
            else:
                error = "arguments are %s, not an object" % type(parsed).__name__
        except ValueError as exc:
            error = "arguments are not JSON: %s" % exc
        return cls(id=str(payload.get("id") or ""), name=str(function.get("name") or ""),
                   arguments=arguments, raw_arguments=raw_text, parse_error=error)


@dataclass
class Usage:
    """What the call cost. `unmeasured` is a state, not a zero: see `measured`."""

    prompt: int = 0
    completion: int = 0

    @property
    def total(self):
        return self.prompt + self.completion

    @property
    def measured(self):
        return self.total > 0


@dataclass
class Message:
    role: str = "user"
    content: str = ""
    tool_calls: list = field(default_factory=list)
    tool_call_id: str = ""
    name: str = ""

    def to_openai(self):
        payload = {"role": self.role, "content": self.content}
        if self.tool_calls:
            payload["tool_calls"] = [
                {"id": call.id, "type": "function",
                 "function": {"name": call.name,
                              "arguments": call.raw_arguments or json.dumps(call.arguments)}}
                for call in self.tool_calls]
        if self.tool_call_id:
            payload["tool_call_id"] = self.tool_call_id
        if self.name:
            payload["name"] = self.name
        return payload

    @classmethod
    def from_openai(cls, payload):
        calls = [ToolCall.from_openai(item) for item in payload.get("tool_calls") or []]
        return cls(role=str(payload.get("role") or "assistant"),
                   content=str(payload.get("content") or ""),
                   tool_calls=calls, tool_call_id=str(payload.get("tool_call_id") or ""),
                   name=str(payload.get("name") or ""))


@dataclass
class Reply:
    """One model answer: prose, the tools it wants, the reasoning it showed, and what it cost."""

    text: str = ""
    tool_calls: list = field(default_factory=list)
    reasoning: str = ""
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def wants_tools(self):
        return bool(self.tool_calls)

    def as_message(self):
        return Message(role="assistant", content=self.text, tool_calls=self.tool_calls)


def as_text(observation):
    """A tool result as the model reads it: the text, or a declared failure. Never an empty string."""
    if observation.ok:
        return observation.text
    return "ERROR: %s" % observation.text
