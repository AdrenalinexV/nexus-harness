"""One wire, five vendors: OpenAI, DeepSeek, OpenRouter, LM Studio and Ollama's `/v1` shim.

The compatibility layer is the industry's actual standard, so it is the default. Two details are not
optional for this harness:

* **Reasoning models.** `qwen3` and `kat-coder` answer with `reasoning_content` (some servers call it
  `reasoning`) alongside `content`. Dropping it would hide the only evidence of *how* the model
  decided; feeding it back into `content` would poison the next turn. It travels in `Reply.reasoning`
  and stops there.
* **Local servers answer 404 on `/models` and 400 on unknown fields.** `models()` therefore tolerates
  a failure, and no field except `model` and `messages` is guaranteed to survive.
"""
from ..message import Message, Reply, ToolCall, Usage
from . import http


class OpenAICompatible:
    """A chat completion endpoint that speaks the OpenAI shape."""

    kind = "openai"

    def __init__(self, model, base_url, api_key="", name="openai", timeout=240,
                 extra_headers=None, requires_key=True):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.name = name
        self.timeout = timeout
        self.extra_headers = dict(extra_headers or {})
        self.requires_key = requires_key

    @property
    def ready(self):
        return bool(self.model) and (bool(self.api_key) or not self.requires_key)

    @property
    def why_not_ready(self):
        if not self.model:
            return "no model configured"
        if self.requires_key and not self.api_key:
            return "no API key for %s" % self.name
        return ""

    def headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer %s" % self.api_key
        headers.update(self.extra_headers)
        return headers

    def payload(self, messages, tools, temperature, max_tokens):
        body = {"model": self.model, "stream": False,
                "messages": [message.to_openai() for message in messages],
                "temperature": temperature, "max_tokens": max_tokens}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        return body

    def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        body = self.payload(messages, tools, temperature, max_tokens)
        data = http.post_json("%s/chat/completions" % self.base_url, body,
                              headers=self.headers(), timeout=self.timeout)
        return self.parse(data)

    def parse(self, data):
        choices = data.get("choices") or []
        if not choices:
            error = (data.get("error") or {}).get("message") or str(data)[:300]
            raise http.TransportError("%s returned no choices: %s" % (self.name, error), body=error)
        message = choices[0].get("message") or {}
        calls = [ToolCall.from_openai(item) for item in message.get("tool_calls") or []]
        usage = data.get("usage") or {}
        return Reply(text=str(message.get("content") or "").strip(),
                     tool_calls=calls,
                     reasoning=str(message.get("reasoning_content")
                                   or message.get("reasoning") or "").strip(),
                     usage=Usage.from_openai(usage),
                     model=str(data.get("model") or self.model), raw=data)

    def models(self, timeout=8):
        """The ids this server offers; an unreachable server is an empty list, not an exception."""
        try:
            data = http.get_json("%s/models" % self.base_url, headers=self.headers(),
                                 timeout=timeout, retries=0)
        except http.TransportError:
            return []
        return sorted(str(item.get("id")) for item in data.get("data") or [] if item.get("id"))


def conversation(messages):
    """Public alias so a transport does not have to import `Message` to be typed."""
    return [Message(**message) if isinstance(message, dict) else message for message in messages]
