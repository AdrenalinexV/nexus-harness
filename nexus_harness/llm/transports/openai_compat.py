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
import json

from ...core import streaming
from ...core.message import Message, Reply, ToolCall, Usage
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

    def payload(self, messages, tools, temperature, max_tokens, stream=True):
        body = {"model": self.model, "stream": bool(stream),
                "messages": [message.to_openai() for message in messages],
                "temperature": temperature, "max_tokens": max_tokens}
        if stream:
            # Sin esto el usage no llega en un stream y el turno queda "sin medir". El motor que
            # rechaza el campo se reintenta sin el en `stream()`.
            body["stream_options"] = {"include_usage": True}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        return body

    def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        """El mismo `Reply` de siempre, plegado del stream: no hay un segundo camino."""
        return streaming.fold(self.stream(messages, tools, temperature, max_tokens))

    def stream(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        """Eventos segun llegan. Si el motor ignora `stream`, cae al cuerpo unico y lo convierte."""
        body = self.payload(messages, tools, temperature, max_tokens)
        try:
            for event in self.iter_events(http.stream_lines(
                    "%s/chat/completions" % self.base_url, body, headers=self.headers(),
                    timeout=self.timeout)):
                yield event
        except http.TransportError as exc:
            # Un motor local que rechaza `stream_options` (campo desconocido) no debe costar el turno:
            # se reintenta sin el, y el usage queda sin medir en vez de romper.
            if exc.status == 400 and "stream_options" in str(exc.body or ""):
                body.pop("stream_options", None)
                for event in self.iter_events(http.stream_lines(
                        "%s/chat/completions" % self.base_url, body, headers=self.headers(),
                        timeout=self.timeout)):
                    yield event
            else:
                raise

    def iter_events(self, chunks):
        """El SSE de OpenAI como eventos. Acepta FRAGMENTOS: un JSON cortado a la mitad no lo rompe."""
        calls, order = {}, []
        usage, model, finish, emitted, saw_data, broken, plain = Usage(), "", "", False, False, 0, []
        for line in streaming.lines(chunks):
            stripped = line.strip()
            if not stripped:
                continue
            if not stripped.startswith("data:"):
                if not saw_data:
                    plain.append(stripped)
                continue
            saw_data = True
            payload = stripped[5:].strip()
            if payload == "[DONE]":
                break
            try:
                data = json.loads(payload)
            except ValueError:
                broken += 1
                continue
            if data.get("error"):
                error = data["error"]
                message = error.get("message", error) if isinstance(error, dict) else error
                raise http.TransportError("%s: %s" % (self.name, message), body=str(error))
            model = str(data.get("model") or model)
            if data.get("usage"):
                usage = Usage.from_openai(data["usage"])
            for choice in data.get("choices") or []:
                if int(choice.get("index") or 0) != 0:
                    continue
                delta = choice.get("delta") or {}
                piece = delta.get("content")
                if piece:
                    emitted = True
                    yield streaming.Event(streaming.DELTA, text=piece)
                thinking = delta.get("reasoning_content") or delta.get("reasoning")
                if thinking:
                    emitted = True
                    yield streaming.Event(streaming.REASONING, text=thinking)
                for item in delta.get("tool_calls") or []:
                    index = int(item.get("index") or 0)
                    slot = calls.get(index)
                    if slot is None:
                        slot = {"id": "", "name": "", "arguments": ""}
                        calls[index] = slot
                        order.append(index)
                    slot["id"] = str(item.get("id") or slot["id"])
                    function = item.get("function") or {}
                    slot["name"] = str(function.get("name") or slot["name"])
                    slot["arguments"] += str(function.get("arguments") or "")
                finish = str(choice.get("finish_reason") or finish)
        if not saw_data and not emitted:
            # El motor ignoro `stream` y contesto un cuerpo unico: el parser de siempre ya sabe leerlo.
            raw = "".join(plain).strip()
            if raw:
                try:
                    data = json.loads(raw)
                except ValueError:
                    raise http.TransportError("%s: respuesta sin SSE y sin JSON: %r"
                                              % (self.name, raw[:200])) from None
                for event in streaming.as_events(self.parse(data)):
                    yield event
                return
        if broken and not emitted:
            raise http.TransportError("%s: %d lineas de stream ilegibles" % (self.name, broken))
        for index in order:
            slot = calls[index]
            yield streaming.Event(streaming.TOOL_CALL, call=ToolCall.from_openai(
                {"id": slot["id"],
                 "function": {"name": slot["name"], "arguments": slot["arguments"]}}))
        yield streaming.Event(streaming.DONE, usage=usage, model=model or self.model,
                              raw={"finish": finish, "chunks": len(order)})

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

    def window(self, timeout=4):
        """La ventana cargada del motor, o 0 si este servidor no la publica."""
        from ..llm.context_window import of
        return of(self, timeout=timeout)


def conversation(messages):
    """Public alias so a transport does not have to import `Message` to be typed."""
    return [Message(**message) if isinstance(message, dict) else message for message in messages]
