"""A sidecar engine must not outlive the shell that started it.

The failure this file exists to prevent is concrete and was observed: a PyInstaller one-file build is
two processes, so killing the bootloader left the engine alive, holding its own `.exe` open, and the
next install silently kept the old binary. `POST /api/shutdown` fixed the orderly path; this fixes the
accidental one -- a crash, a Task Manager kill, a shell that dies without saying goodbye.

The rule: **when the shell launches us (a launch token is present), watch the parent and leave with
it.** A CLI `serve` the operator started by hand sets no token and keeps running, which is what a
server started from a terminal should do.

Liveness is re-checked, never assumed: on Windows `os.kill(pid, 0)` is not a no-op, so the probe opens
the process with the right access and treats "still there" as alive. A recycled PID is a theoretical
risk here and an accepted one: the worst case is that the engine exits too early, and an engine that
stops when its parent is gone is never a surprise.
"""
import os
import threading
import time

CHECK_SECONDS = 2.0
WATCHER_NAME = "nexus-parent-watch"


def parent_alive(pid):
    """True while that PID belongs to a live process."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes  # noqa: PLC0415 - Windows-only path

        kernel32 = ctypes.windll.kernel32
        process = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not process:
            return False
        code = ctypes.c_ulong()
        alive = bool(kernel32.GetExitCodeProcess(process, ctypes.byref(code))) and code.value == 259
        kernel32.CloseHandle(process)
        return alive
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def watched_pid(environ=None):
    """Which PID this engine should follow.

    A frozen one-file build is two processes, so `os.getppid()` is the bootloader -- a process that
    lives exactly as long as the engine and therefore watches nothing. The shell passes its own PID in
    `NEXUS_HARNESS_PARENT`; `os.getppid()` remains the answer for an unfrozen run.
    """
    environ = os.environ if environ is None else environ
    declared = str(environ.get("NEXUS_HARNESS_PARENT") or "").strip()
    if declared.isdigit() and int(declared) > 0:
        return int(declared)
    return os.getppid()


def watch_parent(exit_hook=None, probe=None, sleep=time.sleep, parent=None):
    """Start the watcher thread. Returns `False` when there is no parent worth watching."""
    parent = watched_pid() if parent is None else int(parent)
    if parent <= 0:
        return False
    probe = probe or parent_alive

    def loop():
        while True:
            sleep(CHECK_SECONDS)
            if not probe(parent):
                (exit_hook or (lambda: os._exit(0)))()
                return

    threading.Thread(target=loop, name=WATCHER_NAME, daemon=True).start()
    return True


def arm_if_sidecar(environ=None):
    """Arm the watcher only for a shell-launched engine (a launch token is the marker)."""
    environ = os.environ if environ is None else environ
    if str(environ.get("NEXUS_HARNESS_TOKEN") or "").strip():
        return watch_parent()
    return False


def selftest():
    """The probe and the loop, without killing anything: both directions are simulated."""
    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    check("our own pid is alive", parent_alive(os.getpid()), True)
    check("pid 0 is not a process", parent_alive(0), False)
    check("junk is not a process", parent_alive("no"), False)

    fired = []
    alive = {"value": True}
    watch_parent(exit_hook=lambda: fired.append("left"), probe=lambda _pid: alive["value"],
                 sleep=lambda _seconds: None)
    deadline = time.time() + 5
    while time.time() < deadline and not fired:
        time.sleep(0.05)
    check("the watcher stays quiet while the parent lives", fired, [])
    alive["value"] = False
    deadline = time.time() + 5
    while time.time() < deadline and not fired:
        time.sleep(0.05)
    check("and leaves once the parent is gone", fired, ["left"])
    check("no token means no watcher", arm_if_sidecar({"NEXUS_HARNESS_TOKEN": ""}), False)
    check("the declared parent wins over the bootloader",
          watched_pid({"NEXUS_HARNESS_PARENT": "1234"}), 1234)
    check("junk in the declaration falls back to the real parent",
          watched_pid({"NEXUS_HARNESS_PARENT": "not-a-pid"}), os.getppid())
    return problems


if __name__ == "__main__":
    import json
    import sys

    found = selftest()
    print(json.dumps({"ok": not found, "problems": found}, indent=2))
    sys.exit(0 if not found else 1)
