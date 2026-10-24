"""A shell that remembers where it was, and never opens a console window.

Every call is one fresh subprocess, because a long-lived PTY you cannot interrupt is worse than a
subprocess per command. What persists is what a developer actually relies on:

* **the working directory.** The wrapper appends a `pwd` probe to every command and reads it back, so
  `cd src` in one call is honoured by the next one -- across bash and cmd, without parsing the command;
* **the environment the model set explicitly.** Lines that begin with `export K=V` (or `set K=V`) are
  applied to the child's environment and remembered, which is the honest subset: no child process can
  leak an arbitrary variable back to its parent, and pretending otherwise would be a lie the next
  command pays for.

Output is clipped head+tail (`output_clip`), the full text goes to `.nexus/harness/logs/`, and long
runs go to `process_manager` when `background=True`. Every Windows spawn carries
`CREATE_NO_WINDOW`: zero black consoles, which is the difference between an app and a batch file.
"""
import os
import re
import shutil
import subprocess
import threading

from . import output_clip, process_manager

DEFAULT_TIMEOUT = 180
CWD_MARK = "__NEXUS_CWD__"
MSYS_PATH = re.compile(r"^/(?:cygdrive/)?([a-zA-Z])(/.*)?$")
EXPORT = re.compile(r"^\s*(?:export|set)\s+([A-Za-z_][A-Za-z0-9_]*)=(.+?)\s*$")
FORBIDDEN = (
    (r"format\s+[a-z]:", "formatting a drive"),
    (r"\brm\s+-rf\s+/(\s|$)", "deleting the filesystem root"),
    (r"remove-item\s+.*-recurse\s+.*c:\\?\s*$", "deleting C:\\ recursively"),
    (r"\bshutdown\b", "shutting the machine down"),
    (r":\(\)\s*\{\s*:\|:&\s*\}", "fork bomb"),
)
WINDOWS_FLAGS = 0x08000000 if os.name == "nt" else 0


class ShellSession:
    """Per-root state: where the last command finished, and what it exported."""

    def __init__(self, root):
        self.root = str(root)
        self.cwd = str(root)
        self.env = {}
        self._lock = threading.Lock()

    # -- state -------------------------------------------------------------------------------
    def snapshot(self):
        return {"cwd": self.cwd, "env": dict(self.env), "root": self.root}

    def reset(self):
        with self._lock:
            self.cwd, self.env = self.root, {}
        return self.snapshot()

    def _shell(self):
        if os.name == "nt":
            return shutil.which("bash") or shutil.which("bash.exe")
        return shutil.which("bash") or "/bin/sh"

    # -- command preparation -----------------------------------------------------------------
    def _absorb_exports(self, command):
        """`export K=V` lines: kept as environment, removed from the script that runs."""
        kept, environment = [], dict(self.env)
        for line in str(command).splitlines():
            match = EXPORT.match(line)
            if match:
                environment[match.group(1)] = match.group(2).strip("'\"")
            else:
                kept.append(line)
        with self._lock:
            self.env = environment
        return "\n".join(kept), environment

    def _wrap(self, command):
        """Command + cwd probe, in the dialect of the shell we are about to use.

        On Windows git-bash reports `/tmp/...` for paths under its own mount; `pwd -W` reports the
        native path Python can actually open, which is the only form worth remembering.
        """
        probe = "$(pwd -W)" if os.name == "nt" else "$PWD"
        shell = self._shell()
        if shell:
            return [shell, "-c", "%s\nprintf '\\n%s%%s\\n' \"%s\"\n"
                    % (command, CWD_MARK, probe)], shell
        if os.name == "nt":
            return ["%s & echo %s%%CD%%" % (command, CWD_MARK)], "cmd"
        return ["%s\nprintf '\\n%s%%s\\n' \"$PWD\"" % (command, CWD_MARK)], "/bin/sh"

    @staticmethod
    def _native(path):
        """`/c/Users/x` -> `C:/Users/x`: bash reports MSYS paths, Python opens native ones."""
        match = MSYS_PATH.match(path or "")
        if not match or os.name != "nt":
            return path
        return "%s:%s" % (match.group(1).upper(), match.group(2) or "/")

    def _harvest(self, output):
        """Pull the marker line out of the output and adopt the directory it names."""
        if CWD_MARK not in output:
            return output
        body, _mark, tail = output.rpartition(CWD_MARK)
        candidate = self._native(tail.strip().splitlines()[0].strip() if tail.strip() else "")
        if candidate and os.path.isdir(candidate):
            with self._lock:
                self.cwd = candidate
        return body.rstrip("\n")

    # -- running -----------------------------------------------------------------------------
    def run(self, command, timeout=None, background=False, label=""):
        command = str(command or "").strip()
        if not command:
            raise ValueError("empty command")
        for pattern, reason in FORBIDDEN:
            if re.search(pattern, command.lower()):
                raise ValueError("refused: %s" % reason)
        script, _shell = self._absorb_exports(command)
        if background:
            text, meta = process_manager.manager_for(self.root).spawn(script, label or "shell")
            meta["cwd"] = self.cwd
            return text, meta
        return self._foreground(script, timeout or DEFAULT_TIMEOUT, label)

    def _foreground(self, script, timeout, label):
        argv, _shell = self._wrap(script)
        kwargs = {"creationflags": WINDOWS_FLAGS} if os.name == "nt" else {}
        environment = dict(os.environ, **self.env)
        try:
            completed = subprocess.run(
                argv, shell=isinstance(argv, str), cwd=self.cwd, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=timeout,
                env=environment, **kwargs)
        except subprocess.TimeoutExpired:
            raise ValueError("command timed out after %ss in %s" % (timeout, self.cwd))
        except OSError as exc:
            # A cwd that vanished (deleted temp dir, unmounted drive) must not wedge every later call.
            if os.path.isdir(self.root):
                self.cwd = self.root
            raise ValueError("could not run in %s: %s" % (self.cwd, exc))
        raw = (completed.stdout or "")
        if (completed.stderr or "").strip():
            raw += "\n[stderr]\n" + completed.stderr
        text = self._harvest(raw)
        clipped, path = output_clip.clip_with_log(self.root, text, label or "shell")
        body = clipped.strip() or "(no output)"
        if path:
            body += "\n(full output: %s)" % path
        return body, {"exit": completed.returncode, "cwd": self.cwd, "files": [],
                      "log": path, "env_keys": sorted(self.env)}


_SESSIONS = {}
_SESSIONS_LOCK = threading.Lock()


def session_for(root):
    key = str(root)
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(key)
        if session is None:
            session = _SESSIONS[key] = ShellSession(root)
        return session


def reset(root):
    return session_for(root).reset()


def shell(root, command, timeout=None, config=None, background=False):
    limit = timeout or getattr(config, "shell_timeout", DEFAULT_TIMEOUT)
    return session_for(root).run(command, limit, background=bool(background))


HANDLERS = {"shell": lambda root, args, config: shell(
    root, args.get("command", ""), args.get("timeout"), config, args.get("background", False))}
