"""Un cerrojo para el turno de noche: dos sesiones sobre el mismo arbol no se pisan sin saberlo.

Lo que se midio (25-oct-2026), porque es la razon de que este fichero exista: una sesion de noche
lanzada por cron y otra interactiva trabajaron a la vez sobre el mismo checkout -- editaron
`nexus_harness/selftests/__init__.py`, `tools/nightshift.py` y el estado generado en los mismos
minutos, y una reemplazo el arreglo de la otra antes de que se pudiera commitear. El cerrojo no impide
trabajar; hace que la segunda sesion lo SEPA al entrar en vez de descubrirlo con un commit roto.

Como funciona
------------
- Fichero `.nexus/harness/nightshift.lock` con PID y hora, creado con `O_EXCL`: el que llega primero
  escribe, el segundo recibe `EEXIST`. No hay carrera entre "leer si existe" y "crear".
- Un cerrojo cuyo dueno ya no existe se HEREDA, con aviso en el propio fichero: un candado que
  sobrevive a su proceso es un candado que bloquea la noche entera. Lo mismo si supera `TTL_HORAS`
  (un turno que llevara seis horas sin soltarlo no esta corriendo; el PID puede haberse reciclado).
- Solo lo toman los comandos que ESCRIBEN estado. `status` y `next` son lecturas y no lo tocan: una
  lectura no debe fallar porque otra sesion este trabajando -- saber donde va la noche nunca debe
  depender de poder escribir.
"""
import datetime
import json
import os
from pathlib import Path

RELATIVE = Path(".nexus") / "harness" / "nightshift.lock"
TTL_HORAS = 6


class LockHeld(RuntimeError):
    """Otra sesion tiene el cerrojo. El mensaje nombra a quien, para que se pueda mirar."""


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def alive(pid):
    """¿Existe el proceso? En Windows con `OpenProcess` y sin senales: `os.kill(pid, 0)` alli no
    pregunta, termina el proceso -- un cerrojo no puede ser el sitio donde alguien descubre eso."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    import ctypes
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def owner(path):
    """El dueno del cerrojo: `{pid, at, note}`. Un fichero ilegible o a medias es dueno desconocido."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _stale(data, path):
    """¿Se puede heredar? Por dueno muerto o por antiguedad. Devuelve el motivo, o ""."""
    if data is None:
        return "" if not Path(path).is_file() else "el fichero no se puede leer"
    if not alive(data.get("pid")):
        return "su proceso (%s) ya no existe" % data.get("pid")
    try:
        started = datetime.datetime.fromisoformat(str(data.get("at")))
    except (TypeError, ValueError):
        return "no declara cuando empezo"
    if _now() - started > datetime.timedelta(hours=TTL_HORAS):
        return "lleva mas de %sh sin soltarse" % TTL_HORAS
    return ""


def _text(note):
    payload = {"pid": os.getpid(), "at": _now().isoformat(timespec="seconds"), "note": note,
               "cwd": str(Path.cwd())}
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _create(path, note):
    """Escribe el cerrojo con `O_EXCL`: el segundo que llega recibe `FileExistsError`, no una carrera."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(handle, _text(note).encode("utf-8"))
    finally:
        os.close(handle)


def _replace(path, note):
    """Heredar es un REEMPLAZO atomico, no borrar-y-escribir: entre esas dos cosas hay una ventana sin
    cerrojo por la que entraria una tercera sesion."""
    temporary = Path(path).with_name(Path(path).name + ".%s.tmp" % os.getpid())
    temporary.write_text(_text(note), encoding="utf-8")
    os.replace(str(temporary), str(path))


def take(root, note=""):
    """Toma el cerrojo para `root`. Devuelve la ruta, o levanta `LockHeld` nombrando a quien lo tiene.

    No hay `--force`: heredarlo es automatico cuando el dueno murio, y saltarse a proposito un cerrojo
    VIVO es exactamente la carrera que este fichero existe para evitar.
    """
    path = Path(root) / RELATIVE
    try:
        _create(path, note)
        return path
    except FileExistsError:
        data = owner(path)
        reason = _stale(data, path)
        if not reason:
            raise LockHeld("el turno de noche ya esta en marcha: pid %s desde %s (%s)"
                           % (data.get("pid"), data.get("at"), data.get("note") or "sin nota"))
        _replace(path, "%s (heredado: %s)" % (note, reason))
        return path


def release(path):
    """Suelta el cerrojo SOLO si es nuestro. El de otro no se toca: podria estar trabajando."""
    data = owner(path)
    if data is None or data.get("pid") != os.getpid():
        return False
    try:
        Path(path).unlink()
    except OSError:
        return False
    return True


def selftest(root, run_command, check):
    """El cerrojo medido, con dos comandos reales: devuelve la lista de fallos.

    Vive aqui y no en `nightshift.py` por el mismo motivo por el que vive el cerrojo: el fichero de la
    maquina de estados esta en su techo de 400 lineas, y una suite de 26 lineas no puede ser lo que lo
    empuje por encima. `run_command` es `nightshift.main`, pasado como funcion para pinchar la
    integracion de verdad (que el comando que ESCRIBE tome el cerrojo) sin importarlo desde aqui.
    """
    problems = []
    held = take(root, note="suite")
    check("el cerrojo se toma", held.is_file(), True)
    check("y dice quien lo tiene", owner(held)["pid"], os.getpid())
    try:
        take(root, note="segunda")
        problems.append("una segunda sesion entro con el cerrojo tomado")
    except LockHeld as exc:
        check("la segunda no entra, y lo dice", "ya esta en marcha" in str(exc), True)
    check("un comando que ESCRIBE no corre con el cerrojo tomado", run_command(["check", "a"]), 20)
    check("y una lectura si corre", run_command(["next"]), 0)
    check("soltarlo lo suelta", release(held), True)
    check("y el fichero desaparece", held.is_file(), False)
    check("con el cerrojo libre el comando que escribe corre", run_command(["check", "a"]), 0)
    check("y no lo deja puesto", held.is_file(), False)
    # Un cerrojo de un proceso que ya no existe se HEREDA: si no, un candado sobrevive a su dueno.
    dead = json.dumps({"pid": 999999, "at": "2020-01-01T00:00:00+00:00"})
    held.write_text(dead, encoding="utf-8")
    inherited = take(root, note="nueva")
    check("un cerrojo huerfano se hereda", owner(inherited)["pid"], os.getpid())
    check("con el motivo escrito en la nota", "heredado" in owner(inherited)["note"], True)
    held.write_text(dead, encoding="utf-8")
    check("el cerrojo de otro no se suelta", release(held), False)
    check("y sigue donde estaba", held.is_file(), True)
    release(held)
    return problems
