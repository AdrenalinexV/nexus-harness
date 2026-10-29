"""MCP: a real child process, a real handshake, a real tool call, and a clean stop.

The server here is a 20-line Python program written to a temp file, so the suite measures this client
against the protocol as spoken -- `initialize`, `tools/list`, `tools/call`, one JSON object per line --
without needing anybody else's binary or network.
"""
import shutil
import sys
import time

from .fakes import TempProject
from ..tools.mcp_client import McpError, McpManager, McpServer
from ..tools import default_registry

FAKE_SERVER = r'''
import json, sys
TOOLS = [{"name": "echo",
          "description": "devuelve el texto",
          "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}}]
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        request = json.loads(line)
    except ValueError:
        continue
    if "id" not in request:
        continue
    method = request.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = request.get("params") or {}
        if params.get("name") != "echo":
            print(json.dumps({"jsonrpc": "2.0", "id": request["id"],
                              "error": {"code": -32601, "message": "no such tool"}}), flush=True)
            continue
        text = (params.get("arguments") or {}).get("text")
        result = {"content": [{"type": "text", "text": "echo: %s" % text}]}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"],
                          "error": {"code": -32601, "message": "no such method"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
'''


def check(name, got, expect, failures=None):
    if got != expect:
        message = "%s: %r, esperaba %r" % (name, got, expect)
        if failures is None:
            raise AssertionError(message)
        failures.append(message)


def interpreter():
    """An interpreter that can run a script: the frozen engine cannot, so fall back to the PATH."""
    if not getattr(sys, "frozen", False):
        return sys.executable
    return shutil.which("python") or shutil.which("python3") or ""


def _config(root):
    script = root / "fake_mcp.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    return {"servers": {"fake": {"command": interpreter(), "args": [str(script)],
                                 "timeout": 20, "enabled": True}}}


def test_discovery_and_call(failures, root):
    manager = McpManager(_config(root), root=root).start()
    try:
        described = manager.describe()
        check("the server is up", described["servers"][0]["ready"], True)
        check("its tools were listed", described["servers"][0]["tools"], ["echo"])
        check("and counted", described["tools"], 1)
        schema = manager.schemas()[0]["function"]
        check("tools are namespaced", schema["name"], "mcp__fake__echo")
        check("the schema travels", "text" in schema["parameters"]["properties"], True)
        check("a call returns the server's text", manager.call("mcp__fake__echo", {"text": "hola"}),
              "echo: hola")
        try:
            manager.call("mcp__fake__nope", {})
            failures.append("an unknown tool was accepted")
        except McpError as exc:
            check("the refusal names the tool", "no such tool" in str(exc), True, failures)
        registry = default_registry(root, mcp=manager)
        names = [row["function"]["name"] for row in registry.schemas()]
        check("the registry advertises it", "mcp__fake__echo" in names, True, failures)
        observation = registry.call("mcp__fake__echo", {"text": "desde el registro"})
        check("and dispatches through the registry", observation.text, "echo: desde el registro",
              failures)
    finally:
        manager.stop()


def test_a_dead_server_is_reported(failures, root):
    config = {"servers": {"broken": {"command": "nexus-harness-no-such-binary", "args": []}}}
    manager = McpManager(config, root=root, timeout=5).start()
    described = manager.describe()
    check("it is listed as not ready", described["servers"][0]["ready"], False)
    check("with the reason", bool(described["servers"][0]["error"]), True)
    check("and no tools", described["tools"], 0)
    manager.stop()


def test_stop_kills_the_child(failures, root):
    script = root / "fake_mcp.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    server = McpServer("solo", interpreter(), [str(script)], cwd=root, timeout=15).start()
    process = server.process
    check("it started", process.poll(), None)
    server.stop()
    deadline = time.time() + 10
    while time.time() < deadline and process.poll() is None:
        time.sleep(0.1)
    check("stop ends the process", process.poll() is not None, True)
    check("and the handle is cleared", server.process, None)
    answered = True
    try:
        server.call("echo", {"text": "x"})
    except McpError:
        answered = False
    check("a stopped server does not answer", answered, False, failures)


def run():
    failures = []
    if not interpreter():
        # A frozen app on a machine with no Python: no stdio MCP server can be started at all. That is
        # a property of the host, not a regression, and it is reported instead of hidden.
        print("    (skipped: no python interpreter on PATH for stdio MCP servers)")
        return failures
    with TempProject() as root:
        test_discovery_and_call(failures, root)
    with TempProject() as root:
        test_a_dead_server_is_reported(failures, root)
    with TempProject() as root:
        test_stop_kills_the_child(failures, root)
    return failures
