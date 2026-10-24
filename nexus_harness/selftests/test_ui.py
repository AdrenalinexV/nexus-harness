"""The API over real sockets: the page, the token, the chat round trip, memory and the guards.

No browser here -- the page is what the desktop window loads, so what matters is that it is served,
that its assets resolve, and that the endpoints it calls answer with the shapes it expects.
"""
import json
import threading
import time
import urllib.error
import urllib.request

from .fakes import FakeRouter, ScriptedProvider, TempProject, reply
from ..cockpit import Cockpit
from ..config import HarnessConfig
from ..ui import build

TOKEN = "test-token-123"


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def _call(base, path, payload=None, token=TOKEN, headers=None):
    request_headers = {"Content-Type": "application/json"}
    if token:
        request_headers["X-Nexus-Token"] = token
    request_headers.update(headers or {})
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(base + path, data=data,
                                     method="POST" if data is not None else "GET",
                                     headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def test_endpoints(failures):
    with TempProject({"calc.py": "def add(a, b):\n    return a + b\n"}) as root:
        config = HarnessConfig(default_root=root, workspace=root, test_command=None,
                               roles={"director": "fake:d", "worker": "fake:w", "judge": "fake:j"},
                               host="127.0.0.1", port=0, lang="es", secrets={})
        cockpit = Cockpit(config)
        cockpit.router = FakeRouter(
            workers=ScriptedProvider([reply("Hola, ¿qué hacemos?"), reply("listo")]),
            judge=ScriptedProvider([reply('{"verdict": "approve", "reason": "ok"}')]))
        server = build(cockpit, port=0, token=TOKEN)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:%d" % server.server_address[1]
        try:
            status, body = _call(base, "/")
            check("the page is served", status, 200, failures)
            check("and is the app", "NEXUS" in body and "app.js" in body, True, failures)
            for asset in ("/app.css", "/app.js"):
                status, _body = _call(base, asset)
                check("%s resolves" % asset, status, 200, failures)
            status, _body = _call(base, "/")
            status, _body = _call(base, "/api/state", token=None)
            check("the api without a token is 401", status, 401, failures)
            status, body = _call(base, "/api/state")
            state = json.loads(body)
            check("with the token it answers", status, 200, failures)
            check("state carries roles and chat", ("roles" in state, "chat" in state),
                  (True, True), failures)
            check("no secret leaks", "API_KEY" in body, False, failures)
            status, _body = _call(base, "/api/events", headers={"Sec-Fetch-Site": "cross-site"})
            check("a cross-site request is refused", status, 403, failures)

            status, _body = _call(base, "/api/chat", {"text": ""})
            check("an empty message is a 400", status, 400, failures)
            status, _body = _call(base, "/api/chat", {"text": "hola"})
            check("a message is accepted", status, 202, failures)
            deadline = time.time() + 20
            answered = False
            while time.time() < deadline:
                _status, body = _call(base, "/api/chat")
                chat = json.loads(body)
                if len(chat.get("messages") or []) >= 2 and not chat.get("busy"):
                    answered = True
                    break
                time.sleep(0.2)
            check("the turn finishes and is stored", answered, True, failures)
            if answered:
                check("with the assistant reply",
                      [row["role"] for row in chat["messages"]], ["user", "assistant"], failures)

            status, body = _call(base, "/api/sessions")
            check("the conversation is listed", len(json.loads(body)["sessions"]), 1, failures)
            status, body = _call(base, "/api/chat/new", {"title": "segunda"})
            second = json.loads(body)["session"]
            check("a new conversation starts", bool(second.get("id")), True, failures)
            status, _body = _call(base, "/api/chat/load", {"id": "chat-nope"})
            check("loading an unknown conversation is 404", status, 404, failures)

            status, body = _call(base, "/api/memory", {"text": "prefiere respuestas cortas"})
            check("memory accepts an entry", json.loads(body)["ok"], True, failures)
            _status, body = _call(base, "/api/memory")
            memory = json.loads(body)
            check("and returns it", memory["entries"], ["prefiere respuestas cortas"], failures)
            _status, body = _call(base, "/api/memory", {"remove": "respuestas cortas"})
            check("and can remove it", json.loads(body)["removed"], 1, failures)

            status, _body = _call(base, "/api/stop", {})
            check("stop answers", status, 200, failures)
            status, _body = _call(base, "/api/nowhere")
            check("an unknown route is 404", status, 404, failures)
            check("the cap was released", cockpit._busy, False, failures)
        finally:
            server.shutdown()
            server.server_close()


def run():
    failures = []
    test_endpoints(failures)
    return failures
