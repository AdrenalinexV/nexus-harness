"""Ollama's native `/api/chat`, which is not the OpenAI shape in two ways that matter.

1. `thinking` (qwen3, deepseek-r1, tev) arrives as `message.thinking`, and only here: the `/v1` shim
   drops it. A reasoning model used through the shim looks like a model that thinks silently.
2. Tool calls come back with `arguments` already a dict, and tool results are ordinary messages with
   `role: "tool"`.

Everything else is the same request: model, messages, stream=false, an `options` block for sampling.
"""
from ..core.message import Message, Reply, ToolCall, Usage
from . import http


class Ollama:
    kind = "ollama"

    def __init__(self, model, base_url="http://127.0.0.1:11434", api_key="", name="ollama",
                 timeout=240, extra_headers=None, requires_key=False):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.timeout = timeout
        self.api_key = api_key or ""
        self.extra_headers = dict(extra_headers or {})
        self.requires_key = requires_key

    @property
    def ready(self):
        return bool(self.model)

    @property
    def why_not_ready(self):
        return "" if self.model else "no model configured"

    def headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer %s" % self.api_key
        headers.update(self.extra_headers)
        return headers

    def to_native(self, message):
        payload = {"role": message.role, "content": message.content}
        if message.tool_calls:
            payload["tool_calls"] = [{"function": {"name": call.name,
                                                   "arguments": call.arguments}}
                                     for call in message.tool_calls]
        return payload

    def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        body = {"model": self.model, "stream": False,
                "messages": [self.to_native(message) for message in messages],
                "options": {"temperature": temperature, "num_predict": max_tokens}}
        if tools:
            body["tools"] = tools
        data = http.post_json("%s/api/chat" % self.base_url, body, headers=self.headers(),
                              timeout=self.timeout)
        return self.parse(data)

    def parse(self, data):
        if data.get("error"):
            raise http.TransportError("%s: %s" % (self.name, data["error"]),
                                      body=str(data["error"]))
        message = data.get("message") or {}
        calls = []
        for index, item in enumerate(message.get("tool_calls") or []):
            function = item.get("function") or {}
            arguments = function.get("arguments")
            calls.append(ToolCall(id=str(item.get("id") or "call_%d" % index),
                                  name=str(function.get("name") or ""),
                                  arguments=arguments if isinstance(arguments, dict) else {},
                                  raw_arguments=str(arguments or "{}")))
        return Reply(text=str(message.get("content") or "").strip(),
                     tool_calls=calls,
                     reasoning=str(message.get("thinking") or "").strip(),
                     usage=Usage(prompt=int(data.get("prompt_eval_count") or 0),
                                 completion=int(data.get("eval_count") or 0)),
                     model=str(data.get("model") or self.model), raw=data)

    def models(self, timeout=5):
        try:
            data = http.get_json("%s/api/tags" % self.base_url, timeout=timeout, retries=0)
        except http.TransportError:
            return []
        return sorted(str(item.get("name")) for item in data.get("models") or [] if item.get("name"))

    def window(self, timeout=4):
        """La ventana con la que Ollama cargo el modelo (`/api/ps`), o 0 si aun no esta cargado."""
        from ..context_window import of
        return of(self, timeout=timeout)


def text_of(message):
    """Native tool results are plain text; this keeps the loop free of transport detail."""
    return Message(role="tool", content=message.content, tool_call_id=message.tool_call_id)
