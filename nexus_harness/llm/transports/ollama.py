"""Ollama's native `/api/chat`, which is not the OpenAI shape in two ways that matter.

1. `thinking` (qwen3, deepseek-r1, tev) arrives as `message.thinking`, and only here: the `/v1` shim
   drops it. A reasoning model used through the shim looks like a model that thinks silently.
2. Tool calls come back with `arguments` already a dict, and tool results are ordinary messages with
   `role: "tool"`.

Everything else is the same request: model, messages, stream=false, an `options` block for sampling.
"""
import json

from ...core import streaming
from ...core.message import Message, Reply, ToolCall, Usage
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

    def payload(self, messages, tools, temperature, max_tokens, stream=True):
        body = {"model": self.model, "stream": bool(stream),
                "messages": [self.to_native(message) for message in messages],
                "options": {"temperature": temperature, "num_predict": max_tokens}}
        if tools:
            body["tools"] = tools
        return body

    def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        """El mismo `Reply` de siempre, plegado del stream: no hay un segundo camino."""
        return streaming.fold(self.stream(messages, tools, temperature, max_tokens))

    def stream(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        """Eventos segun llegan. El NDJSON de Ollama trae el usage en el ultimo chunk."""
        body = self.payload(messages, tools, temperature, max_tokens)
        for event in self.iter_events(http.stream_lines(
                "%s/api/chat" % self.base_url, body, headers=self.headers(),
                timeout=self.timeout)):
            yield event

    def iter_events(self, chunks):
        """El NDJSON de Ollama como eventos. Acepta FRAGMENTOS: un JSON partido no lo rompe."""
        calls, order = {}, []
        usage, model, emitted, broken = Usage(), self.model, False, 0
        for line in streaming.lines(chunks):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
            except ValueError:
                broken += 1
                continue
            if data.get("error"):
                raise http.TransportError("%s: %s" % (self.name, data["error"]),
                                          body=str(data["error"]))
            model = str(data.get("model") or model)
            message = data.get("message") or {}
            piece = message.get("content")
            if piece:
                emitted = True
                yield streaming.Event(streaming.DELTA, text=piece)
            thinking = message.get("thinking")
            if thinking:
                emitted = True
                yield streaming.Event(streaming.REASONING, text=thinking)
            for index, item in enumerate(message.get("tool_calls") or []):
                slot = calls.get(index)
                if slot is None:
                    slot = {"id": "", "name": "", "arguments": None, "raw": ""}
                    calls[index] = slot
                    order.append(index)
                slot["id"] = str(item.get("id") or slot["id"] or "call_%d" % index)
                function = item.get("function") or {}
                slot["name"] = str(function.get("name") or slot["name"])
                arguments = function.get("arguments")
                if isinstance(arguments, dict):
                    slot["arguments"] = arguments
                elif arguments is not None:
                    slot["raw"] += str(arguments)
            if data.get("done"):
                usage = Usage(prompt=int(data.get("prompt_eval_count") or 0),
                              completion=int(data.get("eval_count") or 0))
        if broken and not emitted and not order:
            raise http.TransportError("%s: %d lineas de stream ilegibles" % (self.name, broken))
        for index in order:
            slot = calls[index]
            arguments = slot["arguments"]
            if arguments is None:
                raw = slot["raw"] or "{}"
                try:
                    arguments = json.loads(raw)
                except ValueError:
                    arguments = {}
            yield streaming.Event(streaming.TOOL_CALL, call=ToolCall(
                id=slot["id"], name=slot["name"],
                arguments=arguments if isinstance(arguments, dict) else {},
                raw_arguments=str(arguments or "{}")))
        yield streaming.Event(streaming.DONE, usage=usage, model=model,
                              raw={"finish": "done", "chunks": len(order)})

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
        from ..llm.context_window import of
        return of(self, timeout=timeout)


def text_of(message):
    """Native tool results are plain text; this keeps the loop free of transport detail."""
    return Message(role="tool", content=message.content, tool_call_id=message.tool_call_id)
