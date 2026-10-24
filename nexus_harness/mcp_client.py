"""MCP over stdio: other people's tools, without asking the model to guess.

The Model Context Protocol is a JSON-RPC conversation. This client keeps the smallest honest version of
it -- `initialize`, `tools/list`, `tools/call` -- and none of the ceremony that would make it a second
framework:

* **One process per server, no console.** `CREATE_NO_WINDOW` on Windows, stderr to a log file (stdout
  carries protocol frames and nothing else, so a stray print in a server cannot corrupt our parsing --
  it corrupts only its own).
* **Framing is one JSON object per line.** That is what `nexus/mcp/server.py` speaks and what the
  reference SDKs emit over stdio; a client that insisted on `Content-Length` headers would only talk to
  itself.
* **Every call has a deadline.** A server that stops answering is disconnected and reported, never
  awaited forever; one retry after a clean restart covers the common "the server died between calls".
* **Tools are namespaced** `mcp__<server>__<tool>`, so a server cannot shadow `read_file` or `apply_patch`.

Discovery is cached per process and refreshed on `reload()`. `selftest` in this repo runs a fake server
in-process, so the client's contract is measured without needing anybody else's binary.
"""
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

CONFIG = Path(os.environ.get("NEXUS_HOME") or (Path.home() / ".nexus")) / "mcp.json"
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "nexus-harness", "version": "0.3.0"}
DEFAULT_TIMEOUT = 25
WINDOWS_FLAGS = 0x08000000 if os.name == "nt" else 0
LOG_DIR = Path(".nexus") / "harness" / "logs"


def default_servers(protocol_home=r"C:\Proyectos\NexusProtocol"):
    """The protocol's own MCP server is the one a fresh install can actually use."""
    return {"nexus": {"command": "python", "args": ["-m", "nexus.mcp.server", "--root", "."],
                      "cwd": protocol_home, "enabled": True,
                      "description": "NexusProtocol: gate verdicts, lint and relay, read-only"}}


def load_config(path=None):
    """`{"servers": {name: {...}}}` from `~/.nexus/mcp.json`, with the protocol server as default."""
    location = Path(path) if path else CONFIG
    if not location.is_file():
        return {"servers": default_servers()}
    try:
        data = json.loads(location.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"servers": default_servers()}
    servers = data.get("servers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return {"servers": default_servers()}
    return {"servers": {str(name): dict(spec) for name, spec in servers.items()
                        if isinstance(spec, dict)}}


class McpError(RuntimeError):
    """A server said no, or stopped answering. Carries the server's own message when it has one."""


class McpServer:
    """One stdio server: process, reader thread, pending requests by id."""

    def __init__(self, name, command, args=None, cwd=None, env=None, timeout=DEFAULT_TIMEOUT):
        self.name = name
        self.command = str(command)
        self.args = [str(item) for item in (args or [])]
        self.cwd = str(cwd) if cwd else None
        self.env = dict(env or {})
        self.timeout = float(timeout)
        self.process = None
        self.tools = []
        self.error = ""
        self._pending = {}
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._queue = queue.Queue()
        self._reader = None
        self._next_id = 0
        self._log = ""

    # -- lifecycle ---------------------------------------------------------------------------
    def start(self):
        if self.process is not None and self.process.poll() is None:
            return self
        cwd = Path(self.cwd or os.getcwd())
        log_dir = cwd / LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log = str(log_dir / ("mcp-%s.log" % self.name))
        stderr = open(self._log, "w", encoding="utf-8", errors="replace")
        kwargs = {"creationflags": WINDOWS_FLAGS} if os.name == "nt" else {"start_new_session": True}
        try:
            self.process = subprocess.Popen(
                [self.command] + self.args, cwd=str(cwd), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=stderr, text=True, encoding="utf-8",
                errors="replace", bufsize=1, env=dict(os.environ, **self.env), **kwargs)
        except OSError as exc:
            stderr.close()
            raise McpError("could not start %r: %s" % (self.command, exc))
        self._reader = threading.Thread(target=self._pump, args=(self.process,), daemon=True,
                                        name="mcp-%s" % self.name)
        self._reader.start()
        self._handshake()
        self.tools = self.list_tools()
        return self

    def _pump(self, process):
        """Read frames, hand replies to whoever is waiting, drop notifications."""
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                frame = json.loads(line)
            except ValueError:
                continue  # a server that prints prose: its problem, not a protocol error
            if not isinstance(frame, dict) or "id" not in frame:
                continue
            with self._lock:
                slot = self._pending.pop(frame["id"], None)
            if slot is not None:
                slot.set(frame)
        with self._lock:
            waiting = list(self._pending.items())
            self._pending.clear()
        for ident, slot in waiting:
            slot.set({"jsonrpc": "2.0", "id": ident,
                      "error": {"code": -32000, "message": "server closed the connection"}})

    def _request(self, method, params=None, timeout=None):
        if self.process is None or self.process.poll() is not None:
            raise McpError("%s is not running" % self.name)
        with self._lock:
            self._next_id += 1
            ident = "%s-%d" % (self.name, self._next_id)
            slot = _Slot()
            self._pending[ident] = slot
        payload = json.dumps({"jsonrpc": "2.0", "id": ident, "method": method,
                              "params": params or {}}) + "\n"
        try:
            with self._write_lock:
                self.process.stdin.write(payload)
                self.process.stdin.flush()
        except (OSError, ValueError) as exc:
            with self._lock:
                self._pending.pop(ident, None)
            raise McpError("%s: write failed (%s)" % (self.name, exc))
        frame = slot.wait(timeout or self.timeout)
        if frame is None:
            with self._lock:
                self._pending.pop(ident, None)
            raise McpError("%s did not answer %s within %ss" % (self.name, method, self.timeout))
        if "error" in frame:
            error = frame["error"] or {}
            raise McpError("%s: %s" % (self.name, error.get("message") or "error"))
        return frame.get("result") or {}

    def _handshake(self):
        self._request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                     "clientInfo": CLIENT_INFO})
        self._notify("notifications/initialized")

    def _notify(self, method, params=None):
        if self.process is None or self.process.poll() is not None:
            return
        try:
            with self._write_lock:
                self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method,
                                                     "params": params or {}}) + "\n")
                self.process.stdin.flush()
        except (OSError, ValueError):
            return

    def list_tools(self):
        result = self._request("tools/list", {}, timeout=max(self.timeout, 30))
        rows = result.get("tools") or []
        return [row for row in rows if isinstance(row, dict) and row.get("name")]

    def call(self, tool, arguments=None):
        """One `tools/call`, with one restart when the server has died between calls."""
        try:
            return self._call_once(tool, arguments)
        except McpError as exc:
            if "did not answer" not in str(exc) and "closed" not in str(exc):
                raise
            self.stop()
            self.start()
            return self._call_once(tool, arguments)

    def _call_once(self, tool, arguments):
        result = self._request("tools/call", {"name": tool, "arguments": dict(arguments or {})},
                               timeout=max(self.timeout, 60))
        pieces = []
        for item in result.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "text":
                pieces.append(str(item.get("text") or ""))
            elif isinstance(item, dict) and item.get("type") == "resource":
                pieces.append(json.dumps(item.get("resource") or {}, ensure_ascii=False)[:4000])
        if result.get("isError"):
            raise McpError("%s/%s: %s" % (self.name, tool, "\n".join(pieces) or "tool error"))
        return "\n".join(pieces) or "(no content)"

    def stop(self):
        process, self.process = self.process, None
        if process is None:
            return False
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True, timeout=10, creationflags=WINDOWS_FLAGS)
            else:
                process.terminate()
        except (OSError, subprocess.SubprocessError):
            process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        return True


class _Slot:
    """A one-shot result box: `wait` returns the frame or `None` after the deadline."""

    def __init__(self):
        self._event = threading.Event()
        self._frame = None

    def set(self, frame):
        self._frame = frame
        self._event.set()

    def wait(self, timeout):
        self._event.wait(timeout)
        return self._frame


class McpManager:
    """Every configured server, the tools they advertise, and the dispatch by namespaced name."""

    def __init__(self, config=None, root=None, timeout=DEFAULT_TIMEOUT, enabled=True):
        self.config = config or load_config()
        self.root = Path(root or os.getcwd())
        self.timeout = timeout
        self.enabled = enabled
        self.servers = {}
        self.errors = {}
        self._lock = threading.Lock()

    def start(self):
        """Bring up every enabled server; a failure is recorded, never raised at the operator."""
        for name, spec in (self.config.get("servers") or {}).items():
            if spec.get("enabled") is False:
                continue
            server = McpServer(name, spec.get("command", ""), spec.get("args"),
                               cwd=spec.get("cwd") or self.root, env=spec.get("env"),
                               timeout=spec.get("timeout") or self.timeout)
            try:
                with self._lock:
                    self.servers[name] = server.start()
                self.errors.pop(name, None)
            except (McpError, OSError) as exc:
                self.errors[name] = str(exc)
        return self

    def reload(self):
        self.stop()
        self.start()
        return self.describe()

    def stop(self):
        with self._lock:
            servers, self.servers = list(self.servers.values()), {}
        return sum(1 for server in servers if server.stop())

    # -- tools -------------------------------------------------------------------------------
    def schemas(self):
        rows = []
        for name, server in self.servers.items():
            for tool in server.tools:
                schema = tool.get("inputSchema") or {"type": "object", "properties": {}}
                rows.append({"type": "function", "function": {
                    "name": self.qualified(name, tool["name"]),
                    "description": ("[MCP %s] %s" % (name, tool.get("description") or ""))[:900],
                    "parameters": schema}})
        return rows

    @staticmethod
    def qualified(server, tool):
        return "mcp__%s__%s" % (server, tool)

    def handles(self, name):
        return str(name).startswith("mcp__")

    def call(self, name, arguments=None):
        parts = str(name).split("__")
        if len(parts) < 3:
            raise McpError("malformed MCP tool name %r" % name)
        server_name, tool = parts[1], "__".join(parts[2:])
        with self._lock:
            server = self.servers.get(server_name)
        if server is None:
            raise McpError("no MCP server %r (running: %s)"
                           % (server_name, ", ".join(sorted(self.servers)) or "none"))
        return server.call(tool, arguments)

    def describe(self):
        rows = []
        for name, server in self.servers.items():
            rows.append({"name": name, "ready": True, "tools": [tool["name"] for tool in server.tools],
                         "pid": getattr(server.process, "pid", None), "error": ""})
        for name, error in self.errors.items():
            rows.append({"name": name, "ready": False, "tools": [], "pid": None, "error": error})
        return {"enabled": self.enabled, "servers": rows,
                "tools": len(self.schemas()), "config": str(CONFIG)}
