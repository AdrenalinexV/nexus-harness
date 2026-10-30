"""La jaula, y lo que de verdad contiene.

`policy.py` decide si un comando puede existir; esto decide **donde** existe. Son dos cosas distintas y
confundirlas es como un arnes se cree seguro por tener una lista de palabras prohibidas.

Cuatro jaulas, cada una con lo que el SO sabe dar:

* **bwrap** (Linux) -- namespaces + montajes: se lee todo, solo se escribe el proyecto.
* **seatbelt** (macOS) -- `sandbox-exec` con un perfil: escritura solo bajo el proyecto.
* **job** (Windows) -- Job Object: mata el arbol al cerrar, limita memoria e hijos. **No aisla el
  sistema de ficheros**, y eso se dice en voz alta en vez de llamarlo sandbox y dormir tranquilo.
* **none** -- no hay jaula. Y entonces `unrestricted` se **niega**: sin jaula, "sin restricciones" es
  la maquina entera y el operador no lo eligio.

La matriz de capacidades es publica (`matrix()`) porque un SKIP sin motivo es una mentira: cada fila
dice si se midio aqui o por que no. El operador puede levantar la negativa con `NEXUS_UNSANDBOXED=1`,
que es una decision suya, escrita y por turno -- nunca un default.
"""
import ctypes
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass

OVERRIDE_ENV = "NEXUS_UNSANDBOXED"
KINDS = ("bwrap", "seatbelt", "job", "none")
SEATBELT_PROFILE = """(version 1)
(allow default)
(deny file-write*)
(allow file-write* (subpath "%s"))
(allow file-write* (subpath "/private/tmp"))
(allow file-write* (subpath "/tmp"))
"""


@dataclass(frozen=True)
class Cage:
    """Lo que el SO de esta maquina puede sostener, con nombre y con limites declarados."""

    kind: str = "none"
    os: str = ""
    filesystem: bool = False
    processes: bool = False
    memory: bool = False
    reason: str = ""

    @property
    def real(self):
        return self.kind != "none"

    @property
    def holds_filesystem(self):
        """La unica capacidad que convierte `unrestricted` en una promesa y no en una apuesta."""
        return bool(self.real and self.filesystem)

    def as_dict(self):
        return {"kind": self.kind, "os": self.os, "filesystem": self.filesystem,
                "processes": self.processes, "memory": self.memory, "reason": self.reason}


def _probe(argv, timeout=6):
    """`(ok, motivo)`: la jaula funciona en ESTA maquina, medido con un comando de verdad."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, errors="replace",
                              timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)
    if done.returncode == 0:
        return True, ""
    text = ((done.stderr or "") + (done.stdout or "")).strip().splitlines()
    return False, (text[-1][:160] if text else "exit %s" % done.returncode)


def _here():
    return platform.system().lower()


def detect(os_name=None):
    """La jaula de un SO, detectada de verdad: se prueba que existe, no se supone por el nombre."""
    name = (os_name or _here()).lower()
    if name.startswith("win"):
        return _detect_job()
    if name == "linux":
        path = shutil.which("bwrap")
        if not path:
            return Cage("none", "linux", reason="falta bubblewrap: `apt install bubblewrap`")
        # Tener el binario no es poder usarlo: Ubuntu 24 restringe los namespaces sin privilegios y
        # bwrap falla al crear el suyo. Se prueba de verdad antes de prometer una jaula.
        ok, why = _probe([path, "--unshare-all", "--die-with-parent", "--ro-bind", "/", "/", "--",
                          "true"])
        if ok:
            return Cage("bwrap", "linux", filesystem=True, processes=True)
        return Cage("none", "linux", reason="bwrap no puede crear su namespace: %s" % why)
    if name == "darwin":
        path = shutil.which("sandbox-exec")
        if not path:
            return Cage("none", "darwin", reason="falta `sandbox-exec` (viene con macOS)")
        ok, why = _probe([path, "-p", "(version 1)(allow default)", "true"])
        if ok:
            return Cage("seatbelt", "darwin", filesystem=True, processes=True)
        return Cage("none", "darwin", reason="sandbox-exec no arranca: %s" % why)
    return Cage("none", name, reason="sistema no soportado")


def _detect_job():
    """Un Job Object de verdad: se crea y se cierra uno vacio para saber que funciona."""
    guard = Guard(memory_mb=1024, max_processes=16)
    if guard.active:
        guard.close()
        return Cage("job", "windows", filesystem=False, processes=True, memory=True,
                    reason="Job Object: contiene procesos y memoria; no aisla ficheros")
    return Cage("none", "windows", reason=guard.reason or "no se pudo crear un Job Object")


_CURRENT = {}


def current():
    """La jaula de esta maquina, cacheada: detectar crea y cierra un Job cada vez que se pregunta."""
    if "cage" not in _CURRENT:
        _CURRENT["cage"] = detect()
    return _CURRENT["cage"]


def matrix():
    """Una fila por SO. Solo la de esta maquina se mide; las otras dicen por que no."""
    here = _here()
    rows = []
    for name in ("windows", "linux", "darwin"):
        if not here.startswith(name[:3]) and not (name == "darwin" and here == "darwin"):
            rows.append({"os": name, "kind": "no medido", "measured": False,
                         "reason": "no medido: esta maquina corre %s" % here})
            continue
        cage = detect(name)
        rows.append(dict(cage.as_dict(), measured=True))
    return rows


def operator_override():
    """El operador asumio el riesgo a mano para este entorno. No es un default, es una firma."""
    return str(os.environ.get(OVERRIDE_ENV) or "").strip().lower() in ("1", "yes", "true", "on")


# -- Windows: Job Object ------------------------------------------------------------------------
class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong)]


class _BASIC_LIMITS(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_ulong),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_ulong),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_ulong),
                ("SchedulingClass", ctypes.c_ulong)]


class _EXTENDED_LIMITS(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BASIC_LIMITS),
                ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


LIMIT_PROCESS_MEMORY = 0x00000100
LIMIT_ACTIVE_PROCESS = 0x00000008
LIMIT_KILL_ON_CLOSE = 0x00002000
EXTENDED_INFO_CLASS = 9


class Guard:
    """Un Job Object de Windows. `close()` mata lo que siga dentro; en otros SO no hace nada."""

    def __init__(self, memory_mb=1024, max_processes=16):
        self.handle = None
        self.reason = ""
        self.active = False
        if os.name != "nt":
            self.reason = "no es Windows: no hay Job Object"
            return
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except OSError as exc:
            self.reason = "kernel32 no carga: %s" % exc
            return
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            self.reason = "CreateJobObject fallo (%s)" % ctypes.get_last_error()
            return
        info = _EXTENDED_LIMITS()
        info.BasicLimitInformation.LimitFlags = LIMIT_KILL_ON_CLOSE
        if memory_mb:
            info.BasicLimitInformation.LimitFlags |= LIMIT_PROCESS_MEMORY
            info.ProcessMemoryLimit = int(memory_mb) * 1024 * 1024
        if max_processes:
            info.BasicLimitInformation.LimitFlags |= LIMIT_ACTIVE_PROCESS
            info.BasicLimitInformation.ActiveProcessLimit = int(max_processes)
        ok = kernel32.SetInformationJobObject(handle, EXTENDED_INFO_CLASS, ctypes.byref(info),
                                              ctypes.sizeof(info))
        if not ok:
            self.reason = "SetInformationJobObject fallo (%s)" % ctypes.get_last_error()
            kernel32.CloseHandle(handle)
            return
        self._kernel32 = kernel32
        self.handle = handle
        self.active = True

    def assign(self, process):
        """Mete un hijo ya creado en el Job. Devuelve si el SO lo acepto."""
        if not self.active or process is None:
            return False
        handle = getattr(process, "_handle", None)
        if not handle:
            self.reason = "el proceso no expone handle"
            return False
        ok = self._kernel32.AssignProcessToJobObject(self.handle, int(handle))
        if not ok:
            self.reason = "AssignProcessToJobObject fallo (%s)" % ctypes.get_last_error()
        return bool(ok)

    def close(self):
        """Cierra el Job: con KILL_ON_CLOSE, lo que quede dentro muere aqui."""
        if self.active and self.handle:
            self._kernel32.CloseHandle(self.handle)
        self.handle = None
        self.active = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def spawn(argv, shell=False, cwd=None, env=None, creationflags=0, memory_mb=1024,
          max_processes=16):
    """`Popen` dentro de la jaula. Devuelve `(process, guard)`; cerrar el guard mata el arbol."""
    guard = Guard(memory_mb=memory_mb, max_processes=max_processes)
    process = subprocess.Popen(argv, shell=shell, cwd=cwd, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace",
                               creationflags=creationflags)
    guard.assign(process)
    return process, guard


def run(argv, shell=False, cwd=None, env=None, timeout=None, creationflags=0, memory_mb=1024,
        max_processes=16):
    """`subprocess.run`, con el hijo dentro del Job cuando el SO lo permite.

    Si no hay Job, el proceso corre igual: esta funcion no finge una jaula que no existe -- quien
    necesita la garantia la pide con `detect().real`, y `policy` la exige para `unrestricted`.
    """
    process, guard = spawn(argv, shell=shell, cwd=cwd, env=env, creationflags=creationflags,
                           memory_mb=memory_mb, max_processes=max_processes)
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        out, err = process.communicate()
        raise
    finally:
        guard.close()
    return subprocess.CompletedProcess(argv, process.returncode, out, err)


def wrap(argv, root, cage=None):
    """Envuelve un argv en la jaula del SO. Sin jaula devuelve el argv tal cual, sin adornos."""
    cage = cage or current()
    text = str(root)
    if cage.kind == "bwrap":
        base = ["bwrap", "--unshare-all", "--share-net", "--die-with-parent", "--ro-bind", "/", "/",
                "--dev", "/dev", "--proc", "/proc"]
        # `--tmpfs /tmp` tapa el proyecto cuando el proyecto VIVE en /tmp (los TempProject de las
        # suites, y cualquier repo en un tmpfs): se monta el bind del proyecto despues y sin taparlo.
        if not str(Path(text).resolve()).lower().startswith(("/tmp", "/private/tmp")):
            base += ["--tmpfs", "/tmp"]
        return base + ["--bind", text, text, "--chdir", text, "--", *list(argv)]
    if cage.kind == "seatbelt":
        return ["sandbox-exec", "-p", SEATBELT_PROFILE % text, *list(argv)]
    return list(argv)


def selftest():
    """Lo que se puede comprobar sin salir del proceso: deteccion y matriz coherentes."""
    problems = []
    cage = detect()
    if cage.kind not in KINDS:
        problems.append("kind desconocida: %r" % cage.kind)
    if cage.kind == "none" and not cage.reason:
        problems.append("sin jaula y sin motivo: eso es un SKIP que miente")
    if cage.kind == "job" and cage.filesystem:
        problems.append("un Job Object no aisla el sistema de ficheros")
    rows = matrix()
    if len(rows) != 3:
        problems.append("la matriz tiene %d filas, esperaba 3" % len(rows))
    for row in rows:
        if row.get("measured") is False and not row.get("reason"):
            problems.append("fila %s sin medir y sin motivo" % row.get("os"))
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("sandbox: %s" % ("OK" if not found else "%d fallos" % len(found)))
    sys.exit(1 if found else 0)
