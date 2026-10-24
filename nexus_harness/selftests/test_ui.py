"""The cockpit: a real HTTP server on an ephemeral port, driven over real sockets.

No browser, no screenshot: the contract is a page, six endpoints and a run that shows up in the
transcript. `urllib` is enough to hold the server to it, and port 0 keeps the suite from colliding with
a cockpit somebody has open.
"""
import json
import threading
import time
import urllib.error
import urllib.request

from .fakes import FakeRouter, ScriptedProvider, TempProject, reply
from ..config import HarnessConfig
from ..ui import Cockpit, build

TEST_COMMAND = 'python -c "import calc, sys; sys.exit(0 if calc.add(2, 3) == 5 else 1)"'


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def _call(base, path, payload=None, timeout=10):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(base + path, data=data,
                                     method="POST" if data is not None else "GET",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def test_endpoints(failures):
    with TempProject({"calc.py": "def add(a, b):\n    return a + b\n"}) as root:
        config = HarnessConfig(default_root=root, workspace=root, test_command=None,
                               roles={"director": "fake:d", "worker": "fake:w", "judge": "fake:j"},
                               host="127.0.0.1", port=0, lang="es", secrets={})
        worker = ScriptedProvider([reply("no toco nada, ya suma"), reply("confirmado")])
        judge = ScriptedProvider([reply('{"verdict": "approve", "reason": "ok"}'),
                                  reply('{"verdict": "approve", "reason": "ok"}')])
        cockpit = Cockpit(config, runner=lambda goal, path: 0)
        cockpit.router = FakeRouter(workers=worker, judge=judge)
        server = build(cockpit, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:%d" % server.server_address[1]
        try:
            status, body = _call(base, "/")
            check("the page is served", status, 200, failures)
            check("and it is the cockpit", "NEXUS" in body and "Cabina" in body, True, failures)
            check("the page embeds its stylesheet", "--accent" in body, True, failures)
            status, body = _call(base, "/api/state")
            state = json.loads(body)
            check("state is json", status, 200, failures)
            check("state carries the roles", sorted(state["roles"]), ["director", "judge", "worker"],
                  failures)
            check("state carries the model catalogue", "options" in state["models"], True, failures)
            check("state carries the bridge", "pending" in state["bridge"], True, failures)
            check("no secret leaks into the page state", "TYPESAFE_API_KEY" in body, False, failures)
            status, _body = _call(base, "/api/run", {"goal": ""})
            check("an empty goal is a 400, not a queue", status, 400, failures)
            status, _body = _call(base, "/api/run", {"goal": "x", "project": "no-existe"})
            check("a project that is not there is refused", status, 400, failures)
            check("and the lock was released", cockpit._running, False, failures)
            status, body = _call(base, "/api/run", {"goal": "deja calc.py sumando",
                                                    "test_command": TEST_COMMAND})
            check("a run is accepted", status, 202, failures)
            deadline = time.time() + 25
            result = None
            while time.time() < deadline:
                _status, body = _call(base, "/api/state")
                candidate = json.loads(body)
                if candidate.get("run"):
                    result = candidate
                    break
                time.sleep(0.2)
            check("the run finished and is published", result is not None, True, failures)
            if result:
                check("the run is green", result["run"]["exit"], 0, failures)
                checks = {row["name"]: row for row in result["run"]["verdict"]["checks"]}
                check("the per-run test command reached the gate",
                      checks.get("tests", {}).get("ok"), True, failures)
                check("and it is not the empty 'not configured' pass",
                      checks.get("tests", {}).get("blocking"), True, failures)
                check("the plan is in the state", bool(result["run"].get("plan")), True, failures)
                check("skills were injected", bool(result["run"].get("skills")), True, failures)
            _status, body = _call(base, "/api/events?since=0")
            events = json.loads(body)["events"]
            kinds = [event["kind"] for event in events]
            check("the transcript has the triad", "director.plan" in kinds and "gate.verdict" in kinds,
                  True, failures)
            check("and the close", "run.end" in kinds, True, failures)
            status, _body = _call(base, "/api/roles", {"role": "nope", "spec": "fake:x"})
            check("an unknown role is refused", status, 400, failures)
            status, _body = _call(base, "/api/roles", {"role": "worker", "spec": "ollama:tev1:0.8b"})
            check("a role can be swapped live", status, 200, failures)
            status, body = _call(base, "/api/bridge", {})
            check("the bridge answers", status, 200, failures)
            check("with an empty queue it ran nothing", json.loads(body)["ran"], 0, failures)
            status, _body = _call(base, "/api/nowhere")
            check("an unknown route is 404", status, 404, failures)
            check("the run lock was released", cockpit._running, False, failures)
        finally:
            server.shutdown()
            server.server_close()


def test_page_assets(failures):
    from ..ui_css import CSS
    from ..ui_html import page
    from ..ui_js import JS
    html = page(CSS, JS)
    check("no token left", "__CSS__" in html or "__JS__" in html, False, failures)
    check("no external asset", "http://" in JS or "https://" in JS, False, failures)
    check("the feed exists", 'id="feed"' in html, True, failures)


def run():
    failures = []
    test_page_assets(failures)
    test_endpoints(failures)
    return failures
