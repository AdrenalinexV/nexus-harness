"""Que hardware hay en ESTA maquina, medido ahora y no supuesto por la configuracion.

El fallo que evita: la cabina decia "Director 27B · Obrero 35B · Juez 27B" como si fuera gratis. En una
GPU de 16 GB esos dos pesos no caben a la vez, asi que LM Studio descarga uno y carga otro en cada
cambio de fase: el turno se pasa la vida esperando, y el operador cree que el arnes es lento.

Tres numeros, y cada uno con su fuente:

* **GPU y VRAM** -- `nvidia-smi --query-gpu`, la unica fuente que da *libre* ahora mismo (32 bit de
  memoria de un driver no se inventa). Sin NVIDIA instalada, la lista vuelve vacia: no hay GPU que
  anunciar.
* **RAM total y libre** -- `GlobalMemoryStatusEx` por `ctypes` en Windows, `/proc/meminfo` fuera.
* **CPU** -- `platform`, que es stdlib y no arranca un proceso.

`runner` es inyectable a proposito: la suite prueba el parser y el calculo sin ejecutar `nvidia-smi`,
porque una prueba que depende de la GPU de quien la lanza no prueba el codigo, prueba la maquina.
"""
import ctypes
import os
import platform
import re
import subprocess

NVIDIA = ("nvidia-smi", "--query-gpu=name,memory.total,memory.free",
          "--format=csv,noheader,nounits")
ROW = re.compile(r"^(?P<name>.+?),\s*(?P<total>\d+)\s*,\s*(?P<free>\d+)\s*$")
WINDOWS_FLAGS = 0x08000000 if os.name == "nt" else 0


def run(command, timeout=4):
    """Ejecuta y devuelve la salida estandar, o cadena vacia. Un sondeo no tiene permitido lanzar."""
    try:
        done = subprocess.run(list(command), capture_output=True, text=True, timeout=timeout,
                              errors="replace", creationflags=WINDOWS_FLAGS)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (done.stdout or "").strip()


def parse_gpus(text):
    """`[{name, total_mb, free_mb}]` de la salida de `nvidia-smi` en modo csv."""
    found = []
    for line in str(text or "").splitlines():
        match = ROW.match(line.strip())
        if not match:
            continue
        found.append({"name": match.group("name").strip(),
                      "total_mb": int(match.group("total")),
                      "free_mb": int(match.group("free"))})
    return found


def gpus(runner=None):
    return parse_gpus((runner or run)(NVIDIA))


def _windows_memory():
    """`(total_mb, free_mb)` del sistema. `free` es "disponible", que es lo que de verdad se puede pedir."""
    class Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                    ("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong),
                    ("total_page", ctypes.c_ulonglong), ("free_page", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong), ("free_virtual", ctypes.c_ulonglong),
                    ("available_extended", ctypes.c_ulonglong)]

    status = Status()
    status.length = ctypes.sizeof(Status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return 0, 0
    # `ullAvailPhys` es la RAM DISPONIBLE (incluye cache reclamable). `ullAvailExtendedVirtual` es un
    # campo reservado que Windows deja a 0: leerlo daba "0.0 GB libres" con 20 GB de sobra.
    return int(status.total // (1024 * 1024)), int(status.free // (1024 * 1024))


def _posix_memory():
    values = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                values[key.strip()] = rest.strip()
    except OSError:
        return 0, 0

    def mb(name):
        digits = re.sub(r"[^\d]", "", values.get(name, "0") or "0")
        return int(digits or 0) // 1024

    return mb("MemTotal"), mb("MemAvailable")


def memory():
    """RAM total y disponible del sistema, en MB."""
    total, free = _windows_memory() if os.name == "nt" else _posix_memory()
    return {"total_mb": max(0, total), "free_mb": max(0, free)}


def cpu():
    return {"name": platform.processor() or platform.machine() or "CPU",
            "cores": os.cpu_count() or 0}


def report(runner=None, memory_reader=None):
    """Todo lo que la cabina necesita, en una sola llamada. Nunca levanta."""
    return {"gpus": gpus(runner), "memory": (memory_reader or memory)(), "cpu": cpu()}


def gb(megabytes):
    """`16303` -> `'16.0 GB'`. Media unidad decimal es mas honesta que redondear a 16."""
    try:
        return "%.1f GB" % (max(0, int(megabytes)) / 1024.0)
    except (TypeError, ValueError):
        return "0.0 GB"


def vram_total_mb(report_):
    return sum(int(gpu.get("total_mb") or 0) for gpu in (report_ or {}).get("gpus") or ())


def vram_free_mb(report_):
    return sum(int(gpu.get("free_mb") or 0) for gpu in (report_ or {}).get("gpus") or ())


def headline(report_, state=""):
    """La frase de la barra superior. Dice lo que hay; `state` es el veredicto de la triada."""
    gpus_found = (report_ or {}).get("gpus") or []
    if gpus_found:
        parts = ["%s (%s VRAM · %s libres)" % (gpu["name"], gb(gpu["total_mb"]), gb(gpu["free_mb"]))
                 for gpu in gpus_found]
        gpu_text = " + ".join(parts)
    else:
        gpu_text = "sin GPU NVIDIA visible (nvidia-smi no contesto)"
    ram = (report_ or {}).get("memory") or {}
    cpu_row = (report_ or {}).get("cpu") or {}
    text = "GPU: %s | RAM: %s libre de %s | %s núcleos" % (
        gpu_text, gb(ram.get("free_mb")), gb(ram.get("total_mb")), cpu_row.get("cores") or "?")
    return "%s | %s" % (text, state) if state else text


def selftest():
    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    sample = ("NVIDIA GeForce RTX 5070 Ti, 16303, 2180\n"
              "NVIDIA GeForce RTX 3060, 12288, 11000\n")
    rows = parse_gpus(sample)
    check("dos tarjetas", len(rows), 2)
    check("el nombre se conserva", rows[0]["name"], "NVIDIA GeForce RTX 5070 Ti")
    check("la vram total", rows[0]["total_mb"], 16303)
    check("y la libre, que es la que importa", rows[0]["free_mb"], 2180)
    check("una salida vacia no inventa tarjetas", parse_gpus(""), [])
    check("un driver que contesta basura no rompe", parse_gpus("no devices were found"), [])
    check("sin nvidia-smi devuelve vacio", gpus(lambda command, timeout=4: ""), [])
    check("gb formatea en decimales", gb(16303), "15.9 GB")
    check("vram total suma tarjetas", vram_total_mb({"gpus": rows}), 28591)
    check("la ram del sistema se mide", memory()["total_mb"] > 0, True)
    fake = {"gpus": rows, "memory": {"total_mb": 32768, "free_mb": 12000},
            "cpu": {"name": "test", "cores": 16}}
    text = headline(fake, "Óptimo")
    check("la frase nombra la gpu", "RTX 5070 Ti" in text, True)
    check("y los GB libres", "2.1 GB libres" in text, True)
    check("y el estado", text.endswith("Óptimo"), True)
    check("sin gpu se dice, no se finge", "sin GPU" in headline({"gpus": [], "memory": {},
                                                                "cpu": {}}), True)
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("hardware_probe: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
