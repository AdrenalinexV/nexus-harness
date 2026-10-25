"""El instalador, medido: se instala de verdad en una sala de usar y tirar y se comparan bytes.

Por que asi, y no leyendo la instalacion que ya haya en el equipo:

1. La prueba tiene que correr en un equipo limpio. Una prueba que exige una instalacion previa mide
   el equipo, no el instalador.
2. La prueba tiene que poder repetirse cada noche. Instalar en `%LOCALAPPDATA%\\NexusHarnessVerify`
   deja intacta la instalacion real del usuario y se desinstala al terminar.
3. `--version` no vale como comparacion, y se midio: la instalacion decia `0.1.0` mientras el repo
   decia `0.3.0` (rojo, bien), pero dos `0.3.0` distintos se habrian dado por buenos -- y el
   instalador llego a llevar un motor con 16 suites mientras el fuente corria 17. El sha256 no tiene
   ese hueco: o el fichero instalado ES el del repositorio, o no lo es.
4. Un motor no es una app de escritorio: se comprueba ademas que la ventana instalada es un binario
   de interfaz (subsistema GUI del PE), que es lo que el usuario ve.

Lo unico que esta prueba toca fuera de su sala es el registro de HKCU que el propio instalador
escribe (la entrada de "Agregar o quitar programas" y `Software\\Nexus`). Se fotografia antes y se
devuelve como estaba al terminar, para que verificar no le cambie nada al usuario.

    python tools/installer_verify.py --selftest     # PE, sha256 y el registro de ida y vuelta
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
GUI_SUBSYSTEM = 2
CONSOLE_SUBSYSTEM = 3
# Lo que el instalador de NSIS escribe en HKCU: la entrada de desinstalacion y la clave del fabricante.
HKCU_TREES = (r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Nexus Harness", r"Software\Nexus")
ROOM_NAME = "NexusHarnessVerify"


def sha256(path):
    """El sha256 del fichero, o "" si no se puede leer (que no es lo mismo que "distinto")."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def pe_subsystem(path):
    """El subsistema del PE: 2 = interfaz (ventana), 3 = consola. None si no es un PE legible."""
    try:
        head = Path(path).read_bytes()[:4096]
    except OSError:
        return None
    if len(head) < 0x40 or head[:2] != b"MZ":
        return None
    offset = int.from_bytes(head[0x3C:0x40], "little")
    if offset + 0x5E > len(head) or head[offset:offset + 4] != b"PE\0\0":
        return None
    # Cabecera COFF (20 bytes) + OptionalHeader hasta el campo Subsystem (0x44 dentro del optional).
    return int.from_bytes(head[offset + 0x5C:offset + 0x5E], "little")


def _run(argv, timeout):
    """Un subproceso sin ventana: en Windows nadie quiere una consola negra por detras."""
    creation = CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        return subprocess.run([str(part) for part in argv], capture_output=True, text=True,
                              errors="replace", timeout=timeout, creationflags=creation)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def _tail(proc, limit=200):
    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return "           : %s" % (text[-limit:] if text else "sin salida")


def _wait_gone(path, seconds):
    """Espera a que un directorio desaparezca: el desinstalador de NSIS se copia a TEMP y vuelve."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not Path(path).exists():
            return True
        time.sleep(0.5)
    return not Path(path).exists()


def _clean(room, lines):
    """Deja la sala vacia: si quedo algo de una pasada anterior, se quita aqui."""
    if not room.exists():
        lines.append("sala       : %s (no existia)" % room)
        return True
    if (room / "uninstall.exe").is_file():
        _run([room / "uninstall.exe", "/S"], 300)
        _wait_gone(room, 30)
    if room.exists():
        shutil.rmtree(room, ignore_errors=True)
        _wait_gone(room, 10)
    if room.exists():
        lines.append("sala       : %s no se pudo vaciar (fichero en uso)" % room)
        return False
    lines.append("sala       : %s venia de una pasada anterior y se vacio" % room)
    return True


# -- registro: se fotografia antes y se devuelve como estaba -------------------------------------
def _values(key, winreg):
    rows, index = {}, 0
    while True:
        try:
            name, data, kind = winreg.EnumValue(key, index)
        except OSError:
            return rows
        index += 1
        rows[name] = (kind, data)


def _walk(key, path, out, winreg):
    out[path] = _values(key, winreg)
    index = 0
    while True:
        try:
            name = winreg.EnumKey(key, index)
        except OSError:
            return
        index += 1
        child = winreg.OpenKey(key, name, 0, winreg.KEY_READ)
        _walk(child, path + "\\" + name, out, winreg)
        winreg.CloseKey(child)


def _snapshot():
    """Lo que el instalador escribe en HKCU, tal y como esta ahora. None si no hay winreg."""
    try:
        import winreg
    except ImportError:
        return None
    taken = {}
    for tree in HKCU_TREES:
        try:
            root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, tree, 0, winreg.KEY_READ)
        except OSError:
            continue
        _walk(root, tree, taken, winreg)
        winreg.CloseKey(root)
    return taken


def _drop(tree, winreg, problems):
    """Borra un arbol del registro entero, y apunta lo que se resista (una clave abierta, por ejemplo)."""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, tree, 0, winreg.KEY_READ)
    except OSError:
        return
    names, index = [], 0
    while True:
        try:
            names.append(winreg.EnumKey(key, index))
        except OSError:
            break
        index += 1
    winreg.CloseKey(key)
    for name in names:
        _drop(tree + "\\" + name, winreg, problems)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, tree)
    except OSError as exc:
        problems.append("%s: %s" % (tree, exc))


def _restore(taken):
    """Devuelve el registro a la foto: borra el arbol entero y lo reescribe (no quedan restos).

    Devuelve la lista de problemas (vacia = quedo como estaba), o None si no hay winreg y no se pudo
    ni intentar. Un problema aqui se dice en voz alta: es la diferencia entre "no lo toque" y
    "creo que no lo toque".
    """
    if taken is None:
        return None
    import winreg
    problems = []
    for tree in HKCU_TREES:
        _drop(tree, winreg, problems)
    for path, rows in sorted(taken.items(), key=lambda row: row[0].count("\\")):
        try:
            key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE)
            for name, (kind, data) in rows.items():
                winreg.SetValueEx(key, name, 0, kind, data)
            winreg.CloseKey(key)
        except OSError as exc:
            problems.append("%s: %s" % (path, exc))
    return problems


# -- la prueba ----------------------------------------------------------------------------------
def _inspect(room, engine, lines):
    installed = room / "engine" / "nexus-harness-engine.exe"
    window = room / "nexus-harness-desktop.exe"
    for path, what in ((installed, "motor"), (window, "ventana")):
        if not path.is_file():
            return 10, lines + ["la instalacion no dejo el %s en %s" % (what, path)]
    subsystem = pe_subsystem(window)
    lines.append("ventana    : %s subsystem=%r (%d = interfaz)" % (window.name, subsystem, GUI_SUBSYSTEM))
    if subsystem != GUI_SUBSYSTEM:
        return 10, lines + ["la ventana instalada no es una app de interfaz"]
    repo_sha, installed_sha = sha256(engine), sha256(installed)
    lines.append("motor      : repo     sha256=%s" % (repo_sha[:12] or "ilegible"))
    lines.append("           : instalado sha256=%s" % (installed_sha[:12] or "ilegible"))
    if not repo_sha or repo_sha != installed_sha:
        return 10, lines + ["el motor instalado NO es el del repositorio"]
    return 0, lines


def _uninstall(room, lines, timeout):
    uninstaller = room / "uninstall.exe"
    if not uninstaller.is_file():
        return 10, lines + ["la instalacion no dejo desinstalador en %s" % room]
    proc = _run([uninstaller, "/S"], timeout)
    lines.append("desinstalar: exit %s" % proc.returncode)
    if proc.returncode != 0:
        return 10, lines + [_tail(proc)]
    if not _wait_gone(room, 30):
        return 10, lines + ["la desinstalacion dejo %s en pie (algo lo tiene abierto)" % room]
    lines.append("sala       : eliminada, sin fichero bloqueado")
    return 0, lines


def verify(installer, engine, room=None, timeout=900):
    """Instala en silencio en una sala limpia, compara el motor y la ventana, y desinstala.

    Devuelve `(exit, lineas)`: 0 verde, 10 el instalador no cumple lo prometido, 20 no verificable.
    """
    installer, engine = Path(installer), Path(engine)
    if not installer.is_file():
        return 20, ["no hay instalador en %s" % installer]
    if not engine.is_file():
        return 20, ["no hay motor en %s" % engine]
    if room is None:
        room = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / ROOM_NAME
    room = Path(room)
    if " " in str(room):
        return 20, ["la sala %s lleva espacios y NSIS exige /D= sin comillas" % room]
    lines = []
    taken = _snapshot()
    code = 20
    try:
        if not _clean(room, lines):
            return 20, lines
        proc = _run([installer, "/S", "/D=%s" % room], timeout)
        lines.append("instalador : %s -> exit %s" % (installer.name, proc.returncode))
        if proc.returncode != 0:
            return 10, lines + [_tail(proc)]
        code, lines = _inspect(room, engine, lines)
        if code == 0:
            code, lines = _uninstall(room, lines, timeout)
    finally:
        problems = _restore(taken)
        if problems is None:
            lines.append("registro   : sin winreg, no se pudo preservar")
        elif problems:
            lines.append("registro   : NO se pudo devolver como estaba (%s)" % "; ".join(problems))
        else:
            lines.append("registro   : devuelto como estaba")
    if code == 0:
        lines.append("ok: el instalador deja el motor del repositorio y una ventana de interfaz, "
                     "y se desinstala limpio")
    return code, lines


def selftest():
    """Lo medible sin instalar: el PE, el sha256 y el registro de ida y vuelta."""
    root = Path(__file__).resolve().parents[1]
    engine = root / "dist" / "nexus-harness-engine.exe"
    window = root / "apps" / "desktop" / "src-tauri" / "target" / "release" / "nexus-harness-desktop.exe"
    problems = []
    if pe_subsystem(engine) != CONSOLE_SUBSYSTEM:
        problems.append("el motor no lee como consola: %r" % pe_subsystem(engine))
    if pe_subsystem(window) != GUI_SUBSYSTEM:
        problems.append("la ventana no lee como interfaz: %r" % pe_subsystem(window))
    if pe_subsystem(Path(__file__)) is not None:
        problems.append("un .py no es un PE, y se leyo como tal")
    if not sha256(engine) or sha256(engine) == sha256(Path(__file__)):
        problems.append("el sha256 no distingue dos ficheros distintos")
    taken = _snapshot()
    if taken is None:
        problems.append("sin winreg no se puede preservar el registro")
    else:
        _restore(taken)
        if _snapshot() != taken:
            problems.append("el registro no vuelve como estaba")
    return problems


def main(argv=None):
    """La interfaz de linea de comandos: `--selftest` lo medible sin instalar, `--verify` la prueba.

    `nightshift.py install --check` lanza `--verify` en su propio proceso, y no lo importa: la prueba
    ejecuta un instalador de Windows y merece una frontera clara (y el motor congelado no tiene por que
    cargar codigo que solo sirve para verificar un instalador).
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--selftest"]:
        problems = selftest()
        for row in problems:
            print("FALLO %s" % row)
        print("installer_verify: %s" % ("OK" if not problems else "%d fallos" % len(problems)))
        return 0 if not problems else 10
    if args[:1] == ["--verify"] and len(args) == 3:
        code, lines = verify(args[1], args[2])
        print("\n".join(lines))
        return code
    print(__doc__.strip().splitlines()[-1])
    return 20


if __name__ == "__main__":
    sys.exit(main())
