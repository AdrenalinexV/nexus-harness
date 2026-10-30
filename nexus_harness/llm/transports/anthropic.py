"""Anthropic's Messages API: the one place the three-transport fiction has to work.

Three differences the conversion must absorb, or the loop breaks on the first tool call:

* `system` is a top-level field, not a message. It is collected here.
* Tool results are *user* content blocks of type `tool_result`, and they must follow the assistant
  turn that asked for them -- so consecutive turns are merged into one message instead of emitted as
  two (the API rejects two user messages in a row).
* Tools carry `input_schema`, not `parameters`.

`thinking` blocks are kept in `Reply.reasoning` but never replayed: a signature-less thinking block
is rejected by the API on the next turn.
"""
from ...core.message import Reply, ToolCall, Usage
from . import http

API_VERSION = "2023-06-01"


class Anthropic:
    kind = "anthropic"

    def __init__(self, model, base_url="https://api.anthropic.com", api_key="", name="anthropic",
                 timeout=240, extra_headers=None, requires_key=True):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.name = name
        self.timeout = timeout
        self.extra_headers = dict(extra_headers or {})
        self.requires_key = requires_key

    @property
    def ready(self):
        return bool(self.model) and bool(self.api_key)

    @property
    def why_not_ready(self):
        if not self.model:
            return "no model configured"
        return "" if self.api_key else "no API key for anthropic"

    def headers(self):
        headers = {"Content-Type": "application/json", "anthropic-version": API_VERSION}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        headers.update(self.extra_headers)
        return headers

    def to_blocks(self, message):
        blocks = []
        if message.role == "tool":
            return [{"type": "tool_result", "tool_use_id": message.tool_call_id,
                     "content": message.content}]
        if message.content:
            blocks.append({"type": "text", "text": message.content})
        for call in message.tool_calls:
            blocks.append({"type": "tool_use", "id": call.id, "name": call.name,
                           "input": call.arguments})
        return blocks or [{"type": "text", "text": "(empty)"}]

    def convert(self, messages):
        system = "\n\n".join(message.content for message in messages if message.role == "system")
        turns = []
        for message in messages:
            if message.role == "system":
                continue
            role = "user" if message.role == "tool" else message.role
            blocks = self.to_blocks(message)
            if turns and turns[-1]["role"] == role:
                turns[-1]["content"].extend(blocks)
            else:
                turns.append({"role": role, "content": list(blocks)})
        return system.strip(), turns

    def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        system, turns = self.convert(messages)
        body = {"model": self.model, "max_tokens": max_tokens, "temperature": temperature,
                "messages": turns}
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [{"name": tool["function"]["name"],
                              "description": tool["function"].get("description", ""),
                              "input_schema": tool["function"]["parameters"]}
                             for tool in tools]
        data = http.post_json("%s/v1/messages" % self.base_url, body, headers=self.headers(),
                              timeout=self.timeout)
        return self.parse(data)

    def parse(self, data):
        if data.get("error"):
            error = data["error"]
            raise http.TransportError("%s: %s" % (self.name, error.get("message", error)),
                                      body=str(error))
        text, reasoning, calls = [], [], []
        for block in data.get("content") or []:
            kind = block.get("type")
            if kind == "text":
                text.append(str(block.get("text") or ""))
            elif kind in ("thinking", "redacted_thinking"):
                reasoning.append(str(block.get("thinking") or ""))
            elif kind == "tool_use":
                calls.append(ToolCall(id=str(block.get("id") or ""),
                                      name=str(block.get("name") or ""),
                                      arguments=block.get("input") or {},
                                      raw_arguments=str(block.get("input") or {})))
        usage = data.get("usage") or {}
        return Reply(text="\n".join(part for part in text if part).strip(), tool_calls=calls,
                     reasoning="\n".join(part for part in reasoning if part).strip(),
                     usage=Usage.from_anthropic(usage),
                     model=str(data.get("model") or self.model), raw=data)

    def models(self, timeout=10):
        try:
            data = http.get_json("%s/v1/models" % self.base_url, headers=self.headers(),
                                 timeout=timeout, retries=0)
        except http.TransportError:
            return []
        return sorted(str(item.get("id")) for item in data.get("data") or [] if item.get("id"))
