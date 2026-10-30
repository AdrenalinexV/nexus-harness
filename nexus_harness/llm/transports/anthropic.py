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
import json

from ...core import streaming
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

    def payload(self, messages, tools, temperature, max_tokens, stream=True):
        system, turns = self.convert(messages)
        body = {"model": self.model, "max_tokens": max_tokens, "temperature": temperature,
                "messages": turns, "stream": bool(stream)}
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [{"name": tool["function"]["name"],
                              "description": tool["function"].get("description", ""),
                              "input_schema": tool["function"]["parameters"]}
                             for tool in tools]
        return body

    def chat(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        """El mismo `Reply` de siempre, plegado del stream: no hay un segundo camino."""
        return streaming.fold(self.stream(messages, tools, temperature, max_tokens))

    def stream(self, messages, tools=None, temperature=0.2, max_tokens=2048):
        """Eventos segun llegan. El usage viaja partido: entrada en `message_start`, salida al final."""
        body = self.payload(messages, tools, temperature, max_tokens)
        for event in self.iter_events(http.stream_lines(
                "%s/v1/messages" % self.base_url, body, headers=self.headers(),
                timeout=self.timeout)):
            yield event

    def iter_events(self, chunks):
        """El SSE de Anthropic como eventos. Acepta FRAGMENTOS: un JSON partido no lo rompe.

        `parse()` une los bloques de texto con un salto de linea. El stream tiene que hacer lo mismo o
        `fold(stream())` no daria el mismo `Reply`: por eso, al empezar un bloque nuevo cuando ya habia
        texto, se emite un `\\n` antes de su primer trozo.
        """
        blocks, order = {}, []
        prompt, completion, cached = 0, 0, 0
        model, finish, emitted, saw_data, broken, plain = self.model, "", False, False, 0, []
        text_block = reasoning_block = None
        for line in streaming.lines(chunks):
            stripped = line.strip()
            if not stripped or stripped.startswith("event:") or stripped.startswith(":"):
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
            if data.get("type") == "error" or data.get("error"):
                error = data.get("error") or {}
                message = error.get("message", error) if isinstance(error, dict) else error
                raise http.TransportError("%s: %s" % (self.name, message), body=str(error))
            kind = str(data.get("type") or "")
            if kind == "message_start":
                message = data.get("message") or {}
                model = str(message.get("model") or model)
                usage = message.get("usage") or {}
                prompt = int(usage.get("input_tokens") or 0)
                cached = int(usage.get("cache_read_input_tokens") or 0)
            elif kind == "content_block_start":
                index = int(data.get("index") or 0)
                block = data.get("content_block") or {}
                blocks[index] = {"type": block.get("type"), "id": str(block.get("id") or ""),
                                 "name": str(block.get("name") or ""), "json": "",
                                 "input": block.get("input") or {}}
                order.append(index)
            elif kind == "content_block_delta":
                index = int(data.get("index") or 0)
                slot = blocks.setdefault(index, {"type": "text", "id": "", "name": "",
                                                 "json": "", "input": {}})
                delta = data.get("delta") or {}
                delta_type = str(delta.get("type") or "")
                if delta_type == "text_delta":
                    piece = str(delta.get("text") or "")
                    if piece:
                        if text_block is not None and text_block != index and emitted:
                            yield streaming.Event(streaming.DELTA, text="\n")
                        text_block = index
                        emitted = True
                        yield streaming.Event(streaming.DELTA, text=piece)
                elif delta_type == "thinking_delta":
                    piece = str(delta.get("thinking") or "")
                    if piece:
                        if reasoning_block is not None and reasoning_block != index and emitted:
                            yield streaming.Event(streaming.REASONING, text="\n")
                        reasoning_block = index
                        emitted = True
                        yield streaming.Event(streaming.REASONING, text=piece)
                elif delta_type == "input_json_delta":
                    slot["json"] += str(delta.get("partial_json") or "")
            elif kind == "message_delta":
                usage = data.get("usage") or {}
                completion = int(usage.get("output_tokens") or completion)
                finish = str((data.get("delta") or {}).get("stop_reason") or finish)
            elif kind == "message_stop":
                break
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
        if broken and not emitted and not order:
            raise http.TransportError("%s: %d lineas de stream ilegibles" % (self.name, broken))
        for index in order:
            slot = blocks[index]
            if slot.get("type") != "tool_use":
                continue
            arguments = slot["input"]
            if slot["json"]:
                try:
                    arguments = json.loads(slot["json"])
                except ValueError:
                    arguments = {}
            yield streaming.Event(streaming.TOOL_CALL, call=ToolCall(
                id=slot["id"], name=slot["name"], arguments=arguments,
                raw_arguments=str(arguments or {})))
        yield streaming.Event(streaming.DONE,
                              usage=Usage(prompt=prompt, completion=completion, cached=cached),
                              model=model, raw={"finish": finish, "chunks": len(order)})

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
