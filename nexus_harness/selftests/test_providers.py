"""Providers: spec parsing, the three parsers, and a router that refuses what it cannot build."""
from ..config import HarnessConfig
from ..providers import Router, SpecError, parse_spec
from ..transports.anthropic import Anthropic
from ..transports.ollama import Ollama
from ..transports.openai_compat import OpenAICompatible


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def test_specs(failures):
    check("provider:model", parse_spec("lmstudio:kat-coder"), ("lmstudio", "kat-coder"), failures)
    check("bare model -> local default", parse_spec("qwen3"), ("lmstudio", "qwen3"), failures)
    check("a model id with colons survives", parse_spec("ollama:tev1:0.8b"),
          ("ollama", "tev1:0.8b"), failures)
    for bad in ("", "  ", "nope:model", "lmstudio:"):
        try:
            parse_spec(bad)
            failures.append("parse_spec(%r) should have raised" % bad)
        except SpecError:
            continue


def test_openai_parser(failures):
    transport = OpenAICompatible("m", "http://127.0.0.1:1234/v1", api_key="", name="lmstudio",
                                 requires_key=False)
    reply = transport.parse({"model": "m", "choices": [{"message": {
        "content": "hola", "reasoning_content": "pensé esto",
        "tool_calls": [{"id": "c1", "function": {"name": "read_file",
                                                 "arguments": "{\"path\": \"a.py\"}"}}]}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3}})
    check("content", reply.text, "hola", failures)
    check("reasoning_content travels", reply.reasoning, "pensé esto", failures)
    check("arguments parsed", reply.tool_calls[0].arguments, {"path": "a.py"}, failures)
    check("usage measured", (reply.usage.prompt, reply.usage.completion), (12, 3), failures)
    empty = transport.parse({"choices": [{"message": {"content": None}}]})
    check("a null content is empty text, not None", empty.text, "", failures)


def test_ollama_parser(failures):
    transport = Ollama("tev1:0.8b")
    reply = transport.parse({"model": "tev1:0.8b",
                             "message": {"content": "", "thinking": "razonando",
                                         "tool_calls": [{"function": {"name": "search",
                                                                      "arguments": {"pattern": "x"}}}]},
                             "prompt_eval_count": 7, "eval_count": 2})
    check("native thinking", reply.reasoning, "razonando", failures)
    check("native tool args are already a dict", reply.tool_calls[0].arguments,
          {"pattern": "x"}, failures)
    check("native usage", reply.usage.total, 9, failures)


def test_anthropic_conversion(failures):
    transport = Anthropic("claude", api_key="k")
    from ..message import Message, ToolCall
    messages = [Message(role="system", content="eres juez"),
                Message(role="user", content="objetivo"),
                Message(role="assistant", content="",
                        tool_calls=[ToolCall(id="t1", name="read_file",
                                             arguments={"path": "a.py"})]),
                Message(role="tool", content="contenido", tool_call_id="t1"),
                Message(role="tool", content="más", tool_call_id="t1")]
    system, turns = transport.convert(messages)
    check("system is a top-level field", system, "eres juez", failures)
    check("tool results merge into the user turn after the call",
          [turn["role"] for turn in turns], ["user", "assistant", "user"], failures)
    check("both tool results are in one message", len(turns[-1]["content"]), 2, failures)
    reply = transport.parse({"model": "claude", "content": [
        {"type": "thinking", "thinking": "dudo"},
        {"type": "text", "text": "vale"},
        {"type": "tool_use", "id": "t2", "name": "shell", "input": {"command": "ls"}}],
        "usage": {"input_tokens": 4, "output_tokens": 2}})
    check("blocks split into text/reasoning/tools",
          (reply.text, reply.reasoning, reply.tool_calls[0].name), ("vale", "dudo", "shell"),
          failures)


def test_router(failures):
    clean = HarnessConfig(secrets={}, roles={"director": "anthropic:claude-x",
                                             "worker": "lmstudio:kat",
                                             "judge": "nope:bad"})
    router = Router(clean)
    check("a cloud role without a key is not ready", router.info("director").ready, False, failures)
    check("and says why", "no API key" in router.info("director").why_not_ready, True, failures)
    check("a local role needs no key", router.info("worker").ready, True, failures)
    check("an unknown vendor is reported, not raised",
          router.info("judge").ready, False, failures)
    keyed = HarnessConfig(secrets={"ANTHROPIC_API_KEY": "sk-test"},
                          roles={"director": "anthropic:claude-x", "worker": "lmstudio:kat",
                                 "judge": "lmstudio:kat"})
    check("a key from the vault makes it ready", Router(keyed).info("director").ready, True,
          failures)
    swapped = Router(keyed)
    swapped.swap("worker", "ollama:tev1:0.8b")
    check("swap changes the model", swapped.info("worker").model, "tev1:0.8b", failures)


def test_a_custom_provider_is_one_more_row(failures):
    """Libertad de proveedor: cualquier endpoint OpenAI-compatible es una fila de la tabla."""
    config = HarnessConfig(roles={"worker": "groq:llama-3.3-70b"},
                           providers={"groq": {"base_url": "https://api.groq.com/openai/v1",
                                               "keys": ["GROQ_API_KEY"]}},
                           secrets={"GROQ_API_KEY": "k-test"})
    router = Router(config)
    info = router.info("worker")
    check("el proveedor propio se resuelve", (info.vendor, info.model),
          ("groq", "llama-3.3-70b"), failures)
    check("con su clave, esta listo", info.ready, True, failures)
    built = router.for_spec("groq:llama-3.3-70b")
    check("y se construye como openai-compatible", isinstance(built, OpenAICompatible), True,
          failures)
    check("apuntando a su base_url", built.base_url, "https://api.groq.com/openai/v1", failures)
    check("y aparece como nube lista", "groq" in router.catalog()["cloud_ready"], True, failures)


def test_a_broken_provider_is_skipped_with_a_reason(failures):
    """Un proveedor mal declarado no tumba el arnes: se descarta y los demas siguen."""
    config = HarnessConfig(providers={"roto": {"wire": "paloma", "base_url": "http://x"},
                                      "bien": {"base_url": "http://127.0.0.1:9000/v1",
                                               "local": True}})
    router = Router(config)
    check("el roto se declara", any("roto" in problem for problem in router.vendor_problems), True,
          failures)
    check("el bueno entra", "bien" in router.vendors, True, failures)
    check("sin base_url tampoco entra", Router(HarnessConfig(
        providers={"sin-url": {"wire": "openai"}})).vendor_problems != [], True, failures)


def run():
    failures = []
    for test in (test_specs, test_openai_parser, test_ollama_parser, test_anthropic_conversion,
                 test_router, test_a_custom_provider_is_one_more_row,
                 test_a_broken_provider_is_skipped_with_a_reason):
        test(failures)
    return failures
