"""Background processes that outlive the tool call that started them.

A build, a dev server, a CLI waiting for input: all of them are the same object here -- a session id, a
Popen, a reader thread and a log file. The model starts it once (`background=True`), then talks to it
with `process_manage(action="poll"|"write"|"kill"|"list")`, because the alternative is a harness that
blocks for ten minutes on `npm run dev` and calls that work.

Three things are not negotiable on Windows:

* `CREATE_NO_WINDOW` on every spawn, so the desktop app never flashes a console over the operator;
* `taskkill /T /F` to kill, because `Popen.terminate()` kills the bash wrapper and leaves the tree behind;
* the child's output goes to a **file**, not only to a pipe -- a process whose parent dies must still have
  somewhere to write (that is also what makes a long log survivable: `poll` shows head+tail, the file has
  everything).
"""
import os
import subprocess
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

from . import output_clip

MAX_SESSIONS = 32
BUFFER_CHARS = 200_000
FINISHED_TTL = 1800
WINDOWS_FLAGS = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


@dataclass
class ProcessSession:
    id: str
    command: str
    cwd: str
    process: object = None
    log: str = ""
    started: float = field(default_factory=time.time)
    exit_code: object = None
    _buffer: list = field(default_factory=list)
    _lock: object = field(default_factory=threading.Lock)
    _thread: object = None

    @property
    def running(self):
        return self.exit_code is None and self.process is not None and self.process.poll() is None

    def read(self):
        with self._lock:
            return "".join(self._buffer)

    def record(self, text):
        with self._lock:
            self._buffer.append(text)
            excess = sum(len(item) for item in self._buffer) - BUFFER_CHARS
            while excess > 0 and len(self._buffer) > 1:
                excess -= len(self._buffer.pop(0))

    def uptime(self):
        return round(time.time() - self.started, 1)


class ProcessManager:
    """One manager per project root: sessions belong to a repository, not to the application."""

    def __init__(self, root, log_label="proc"):
        self.root = str(root)
        self.log_label = log_label
        self._sessions = OrderedDict()
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------------------------
    def spawn(self, command, label=""):
        command = str(command or "").strip()
        if not command:
            raise ValueError("empty command")
        session = ProcessSession(id="p" + uuid.uuid4().hex[:8], command=command, cwd=self.root)
        session.log = str(output_clip.log_path(self.root, label or self.log_label))
        handle = open(session.log, "w", encoding="utf-8", errors="replace", newline="")
        kwargs = {"creationflags": WINDOWS_FLAGS} if os.name == "nt" else {"start_new_session": True}
        try:
            session.process = subprocess.Popen(
                command, shell=True, cwd=self.root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                bufsize=1, env=dict(os.environ), **kwargs)
        except OSError as exc:
            handle.close()
            raise ValueError("could not start %r: %s" % (command, exc))
        session._thread = threading.Thread(target=self._pump, args=(session, handle), daemon=True,
                                           name="proc-%s" % session.id)
        session._thread.start()
        with self._lock:
            self._sessions[session.id] = session
            self._prune()
        return ("started %s (pid %s, log %s). Use process_manage(action=\"poll\", session_id=\"%s\") "
                "to read it, \"kill\" to stop it." % (session.id, session.process.pid, session.log,
                                                     session.id),
                {"files": [], "session_id": session.id, "pid": session.process.pid,
                 "status": "running", "log": session.log})

    def _pump(self, session, handle):
        """Reader thread: every line to the buffer and to the log, then the exit code."""
        try:
            for line in session.process.stdout:
                session.record(line)
                handle.write(line)
                handle.flush()
        except (ValueError, OSError) as exc:
            session.record("\n[reader stopped: %s]\n" % exc)
        finally:
            try:
                session.exit_code = session.process.wait()
            except OSError:
                session.exit_code = -1
            try:
                handle.close()
            except OSError as exc:
                session.record("\n[log close failed: %s]\n" % exc)

    # -- queries -----------------------------------------------------------------------------
    def get(self, session_id):
        with self._lock:
            session = self._sessions.get(str(session_id or ""))
        if session is None:
            raise ValueError("unknown session %r (active: %s)"
                             % (session_id, ", ".join(self.list_ids()) or "none"))
        return session

    def list_ids(self):
        with self._lock:
            return [item.id for item in self._sessions.values()]

    def _prune(self):
        """Finished sessions fall off after half an hour or when the table is full."""
        now = time.time()
        for key, session in list(self._sessions.items()):
            if session.exit_code is not None and now - session.started > FINISHED_TTL:
                self._sessions.pop(key, None)
        while len(self._sessions) > MAX_SESSIONS:
            self._sessions.popitem(last=False)

    def poll(self, session_id):
        session = self.get(session_id)
        text = session.read()
        clipped, path = output_clip.clip_with_log(self.root, text, "poll-%s" % session.id)
        status = "running" if session.running else "exited"
        header = "%s %s (pid %s, %ss)" % (session.id, status,
                                          getattr(session.process, "pid", "?"), session.uptime())
        body = clipped or "(no output yet)"
        meta = {"files": [], "session_id": session.id, "status": status,
                "exit_code": session.exit_code, "log": session.log}
        if path:
            body += "\n(full output: %s)" % path
        return "%s\n%s" % (header, body), meta

    def write(self, session_id, data):
        session = self.get(session_id)
        if not session.running:
            raise ValueError("%s has exited; nothing to write to" % session.id)
        payload = str(data or "")
        try:
            session.process.stdin.write(payload)
            session.process.stdin.flush()
        except (AttributeError, OSError, ValueError) as exc:
            raise ValueError("could not write to %s: %s" % (session.id, exc))
        return "wrote %d chars to %s" % (len(payload), session.id), \
            {"files": [], "session_id": session.id, "status": "running"}

    def kill(self, session_id, timeout=10):
        session = self.get(session_id)
        if not session.running:
            return ("%s had already exited (code %s)" % (session.id, session.exit_code),
                    {"files": [], "session_id": session.id, "status": "exited",
                     "exit_code": session.exit_code})
        pid = session.process.pid
        self._terminate(pid)
        try:
            session.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            session.record("\n[kill: still alive after %ss]\n" % timeout)
        session.exit_code = session.process.poll()
        text = session.read()
        clipped, path = output_clip.clip_with_log(self.root, text, "kill-%s" % session.id)
        body = "killed %s (pid %s)" % (session.id, pid)
        if clipped.strip():
            body += "\nlast output:\n%s" % clipped[-2000:]
        return body, {"files": [], "session_id": session.id, "status": "exited",
                      "exit_code": session.exit_code, "log": path or session.log}

    @staticmethod
    def _terminate(pid):
        """Tree kill: on Windows the shell wrapper dies alone unless `taskkill /T` is used."""
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                               text=True, timeout=10, creationflags=WINDOWS_FLAGS)
            else:
                os.killpg(os.getpgid(pid), 15)
        except (OSError, subprocess.SubprocessError):
            return False
        return True

    def listing(self):
        with self._lock:
            sessions = list(self._sessions.values())
        if not sessions:
            return "(no background processes)", {"files": []}
        rows = ["%s  %-8s pid=%-7s %6ss  %s" % (item.id, "running" if item.running else "exited",
                                                getattr(item.process, "pid", "?"), item.uptime(),
                                                item.command[:80]) for item in sessions]
        return "\n".join(rows), {"files": [], "sessions": [item.id for item in sessions]}

    def kill_all(self):
        """Stop everything this manager started. Called when the operator presses Detener."""
        killed = 0
        with self._lock:
            sessions = list(self._sessions.values())
        for session in sessions:
            if session.running:
                self._terminate(session.process.pid)
                killed += 1
        return killed


_MANAGERS = {}
_MANAGER_LOCK = threading.Lock()


def manager_for(root):
    """The manager a tool call gets: one per project root, created on first use."""
    key = str(root)
    with _MANAGER_LOCK:
        manager = _MANAGERS.get(key)
        if manager is None:
            manager = _MANAGERS[key] = ProcessManager(root)
        return manager


def kill_all_managers():
    """Every background process this process owns, across every project."""
    with _MANAGER_LOCK:
        managers = list(_MANAGERS.values())
    return sum(manager.kill_all() for manager in managers)


def process_manage(root, action, session_id="", data="", label=""):
    manager = manager_for(root)
    action = str(action or "list").strip().lower()
    if action == "list":
        return manager.listing()
    if action == "poll":
        return manager.poll(session_id)
    if action == "write":
        return manager.write(session_id, data)
    if action == "kill":
        return manager.kill(session_id)
    raise ValueError("unknown action %r (use list, poll, write or kill)" % action)


HANDLERS = {"process_manage": lambda root, args, config: process_manage(
    root, args.get("action", "list"), args.get("session_id", ""), args.get("data", ""))}
