"""The terminal: what persists, what gets clipped, and what a background process really is.

Three properties, three bugs they prevent:

* **cwd persistence** -- `cd` in one call must be honoured by the next, or every second command fails
  with "no such file" and the model starts prefixing `cd` to everything;
* **head+tail clipping** -- 40 000 chars of output must not enter the transcript whole, but the last
  lines (the ones that say why it failed) must survive, and the full log must be on disk;
* **background lifecycle** -- spawn, poll while it runs, kill, and observe a real exit. A harness that
  cannot stop what it started is a harness that owns the machine.
"""
import os
import time

from .fakes import TempProject
from ..toolbox import process_manager, shell_session


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def test_cwd_persists(failures, root):
    (root / "sub").mkdir()
    session = shell_session.session_for(root)
    session.reset()
    session.run("cd sub")
    check("the first cd is captured", session.cwd.endswith("sub") or
          session.cwd.endswith("sub\\") or session.cwd.endswith("sub/"), True, failures)
    out, meta = session.run("pwd || cd")
    check("the next command runs there", "sub" in (out + str(meta.get("cwd"))), True, failures)
    session.reset()
    check("reset returns to the root", session.cwd, str(root), failures)


def test_env_persists(failures, root):
    session = shell_session.session_for(root)
    session.reset()
    session.run("export NEXUS_PROBE=abc123")
    check("the export was absorbed", session.env.get("NEXUS_PROBE"), "abc123", failures)
    out, _meta = session.run("echo $NEXUS_PROBE")
    check("and the next command sees it", "abc123" in out, True, failures)
    session.reset()


def test_massive_output_is_clipped(failures, root):
    session = shell_session.session_for(root)
    session.reset()
    command = "python -c \"print('x' * 40000)\""
    out, meta = session.run(command)
    check("the output is clipped", len(out) < 14000, True, failures)
    check("and says how much was dropped", "chars clipped" in out, True, failures)
    log = meta.get("log") or ""
    check("a full log was written", os.path.isfile(log), True, failures)
    if os.path.isfile(log):
        size = len(open(log, encoding="utf-8", errors="replace").read())
        check("the log has everything", size >= 40000, True, failures)


def test_background_lifecycle(failures, root):
    manager = process_manager.manager_for(root)
    text, meta = manager.spawn(
        "python -c \"import time,sys; print('up', flush=True); time.sleep(6)\"", "probe")
    session_id = meta["session_id"]
    check("the spawn returns an id", bool(session_id), True, failures)
    check("and says running", meta.get("status"), "running", failures)
    deadline = time.time() + 8
    while time.time() < deadline and "up" not in manager.poll(session_id)[0]:
        time.sleep(0.2)
    polled, poll_meta = manager.poll(session_id)
    check("poll sees its output", "up" in polled, True, failures)
    check("while it still runs", poll_meta.get("status"), "running", failures)
    listed, _ = manager.listing()
    check("it is in the list", session_id in listed, True, failures)
    killed, kill_meta = manager.kill(session_id)
    check("kill reports the id", session_id in killed, True, failures)
    check("and it is no longer running", kill_meta.get("status"), "exited", failures)
    check("with no exit code left unset", kill_meta.get("exit_code") is not None, True, failures)


def test_write_to_background(failures, root):
    manager = process_manager.manager_for(root)
    text, meta = manager.spawn(
        "python -c \"import sys; line = sys.stdin.readline(); print('got:' + line.strip(), "
        "flush=True)\"", "stdin")
    session_id = meta["session_id"]
    time.sleep(0.6)
    manager.write(session_id, "hola\n")
    deadline = time.time() + 6
    seen = ""
    while time.time() < deadline:
        seen, poll_meta = manager.poll(session_id)
        if "got:hola" in seen or poll_meta.get("status") != "running":
            break
        time.sleep(0.2)
    check("the child received stdin", "got:hola" in seen, True, failures)
    manager.kill(session_id)


def run():
    failures = []
    with TempProject() as root:
        test_cwd_persists(failures, root)
        test_env_persists(failures, root)
        test_massive_output_is_clipped(failures, root)
        test_background_lifecycle(failures, root)
        test_write_to_background(failures, root)
    return failures
