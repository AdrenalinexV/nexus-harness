"""El Obrero edita dentro de un `git worktree` y solo vuelve al arbol si el gate sale verde.

Reparar un fallo directamente en el arbol principal tiene un problema que no se ve: si el intento sale
mal, el usuario se queda con un repositorio a medio romper y sin forma barata de saber que toco el
agente. Un worktree de git resuelve eso con maquinaria que ya existe:

    crear rama+worktree  ->  el Obrero edita ahi  ->  gate ahi  ->  verde: promote  |  rojo: discard

`promote` copia los ficheros cambiados al arbol principal y solo entonces retira el worktree; `discard`
lo retira sin tocar nada. La copia se hace fichero a fichero (no un merge de git) porque el arbol
principal suele tener trabajo sin commitear cuando el Obrero entra, y un `merge` se negaria o pediria
intervencion. Lo que garantiza la correccion no es el merge: es que el gate se midio DENTRO del
worktree antes de copiar, y que la lista de ficheros promovidos es exactamente la que cambio.

Los worktrees viven en `.nexus/harness/worktrees/<id>`, que ya esta en `.gitignore`-landia: no
aparecen como basura en el repositorio ni en `git status`.
"""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

BASE_REL = Path(".nexus") / "harness" / "worktrees"
WINDOWS_FLAGS = 0x08000000 if os.name == "nt" else 0
DEFAULT_GATE = "python tools/lint_harness.py"
KEEP = ("findings=0",)


def _run(command, cwd, timeout=300):
    """`(exit, salida)`. Nunca lanza: un worktree roto se informa, no tumba el bucle."""
    try:
        done = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True,
                              errors="replace", timeout=timeout, creationflags=WINDOWS_FLAGS)
    except subprocess.TimeoutExpired:
        return 124, "timeout tras %ss" % timeout
    except OSError as exc:
        return 127, "%s: %s" % (type(exc).__name__, exc)
    return done.returncode, ((done.stdout or "") + (done.stderr or "")).strip()


def reap(root, max_age_minutes=180):
    """Borra worktrees HUERFANOS (proceso matado a la fuerza) y sus ramas. Devuelve sus nombres.

    Un `finally` no corre cuando el proceso recibe un kill duro, y el worktree se queda: 3,4 MB de
    copia del repositorio que el lint contaba como codigo propio (medido: 237 ficheros en vez de 115).
    La edad es el criterio, no la existencia: un worktree de hace un minuto puede ser de otro turno.
    """
    import time as _time

    base = Path(root) / BASE_REL
    removed = []
    if not base.is_dir():
        return removed
    _run(["git", "worktree", "prune"], root)
    now = _time.time()
    for path in sorted(base.iterdir()):
        if not path.is_dir():
            continue
        try:
            age = (now - path.stat().st_mtime) / 60.0
        except OSError:
            continue
        if age < float(max_age_minutes):
            continue
        _run(["git", "worktree", "remove", "--force", str(path)], root)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        removed.append(path.name)
    code, branches = _run(["git", "for-each-ref", "--format=%(refname:short)",
                           "refs/heads/nexus/sandbox/"], root)
    if code == 0:
        for branch in branches.splitlines():
            if branch.strip():
                _run(["git", "branch", "-D", branch.strip()], root)
    return removed


def _slug(text):
    clean = "".join(char if char.isalnum() or char in "-_" else "-" for char in str(text or ""))
    return clean.strip("-")[:40] or "wt"


class Sandbox:
    """Un worktree con nombre, su rama y las tres operaciones que importan."""

    def __init__(self, root, name="job", gate=DEFAULT_GATE, base=None):
        self.root = Path(root)
        self.name = "%s-%s" % (_slug(name), time.strftime("%H%M%S"))
        self.branch = "nexus/sandbox/%s" % self.name
        self.gate_command = gate
        self.base = Path(base) if base else self.root / BASE_REL
        self.path = self.base / self.name
        self.created = False
        self.last = {}

    # -- ciclo de vida ---------------------------------------------------------------------------
    def create(self):
        """Crea rama y worktree desde HEAD. `{ok, path, exit, reason}`; idempotente por nombre."""
        reap(self.root)
        self.base.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            return {"ok": False, "exit": 1, "reason": "el worktree ya existe: %s" % self.path}
        code, output = _run(["git", "worktree", "add", "-b", self.branch, str(self.path), "HEAD"],
                            self.root)
        self.created = code == 0
        self.last = {"ok": self.created, "exit": code, "path": str(self.path),
                     "branch": self.branch, "reason": output[-600:]}
        return self.last

    def changed(self):
        """Los ficheros que el Obrero toco dentro del worktree, en orden estable."""
        if not self.created:
            return []
        code, output = _run(["git", "status", "--porcelain"], self.path)
        if code != 0:
            return []
        files = []
        for line in output.splitlines():
            # `git status --porcelain` es "XY PATH", pero git no siempre emite los dos caracteres
            # cuando uno es espacio ("M app.py" vs " M app.py"): cortar por indice fijo se comia la
            # primera letra del fichero (medido: `app.py` -> `pp.py`). Se quita el prefijo por patron.
            path = re.sub(r"^[ MADRCU?!]{1,2}\s+", "", line).strip().strip('"')
            if " -> " in path:                       # renombrado: cuenta el destino
                path = path.split(" -> ", 1)[1]
            if path:
                files.append(path)
        return sorted(set(files))

    def gate(self):
        """Corre el gate DENTRO del worktree. `{ok, exit, tail}`; verde = exit 0 y `findings=0`."""
        code, output = _run(self.gate_command, self.path)
        ok = code == 0 and all(token in output for token in KEEP)
        self.last = {"ok": ok, "exit": code, "tail": output[-900:], "command": self.gate_command}
        return self.last

    def promote(self, files=None):
        """Copia al arbol principal lo cambiado. Devuelve `{ok, copied, reason}`."""
        files = list(files) if files is not None else self.changed()
        if not files:
            return {"ok": False, "copied": [], "reason": "el worktree no cambio nada"}
        copied = []
        for relative in files:
            source = self.path / relative
            target = self.root / relative
            if not source.is_file():
                return {"ok": False, "copied": copied,
                        "reason": "desaparecio %s antes de copiarlo" % relative}
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(relative)
        return {"ok": True, "copied": copied, "reason": ""}

    def discard(self):
        """Retira el worktree y su rama. Nunca deja el arbol principal tocado."""
        code, output = _run(["git", "worktree", "remove", "--force", str(self.path)], self.root)
        _run(["git", "branch", "-D", self.branch], self.root)
        self.created = False
        return {"ok": code == 0 or not self.path.exists(), "exit": code,
                "reason": output[-400:]}

    # -- el ciclo completo -----------------------------------------------------------------------
    def attempt(self, work, files=None):
        """`work(path)` edita dentro del worktree; luego gate, promote o discard. Cierra siempre.

        Devuelve `{ok, exit, files, promoted, reason}`. Un `work` que lanza se trata como gate rojo:
        el worktree se descarta y el arbol principal queda como estaba.
        """
        made = self.create()
        if not made["ok"]:
            return {"ok": False, "exit": made["exit"], "files": [], "promoted": [],
                    "reason": "no se pudo crear el worktree: %s" % made["reason"]}
        try:
            try:
                work(self.path)
            except Exception as exc:  # noqa: BLE001 -- el fallo del Obrero es un rojo, no un crash
                self.discard()
                return {"ok": False, "exit": 1, "files": [], "promoted": [],
                        "reason": "el trabajo fallo dentro del sandbox: %s: %s"
                                  % (type(exc).__name__, exc)}
            touched = self.changed()
            verdict = self.gate()
            if not verdict["ok"]:
                self.discard()
                return {"ok": False, "exit": verdict["exit"], "files": touched, "promoted": [],
                        "reason": "gate rojo dentro del worktree"}
            promoted = self.promote(files if files is not None else touched)
            self.discard()
            promoted["files"] = touched
            return {"ok": bool(promoted["ok"]), "exit": verdict["exit"], "files": touched,
                    "promoted": promoted.get("copied") or [], "reason": promoted.get("reason") or ""}
        finally:
            if self.path.exists():
                self.discard()


def selftest():
    import tempfile

    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    with tempfile.TemporaryDirectory(prefix="worktree-") as workspace:
        root = Path(workspace)
        _run(["git", "init", "-q", "-b", "main"], root)
        (root / "tools").mkdir()
        (root / "tools" / "lint_harness.py").write_text(
            "import sys\nprint('files=1 findings=0 max_lines=400')\nsys.exit(0)\n", encoding="utf-8")
        (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "tools" / "bad_gate.py").write_text(
            "print('findings=1')\nraise SystemExit(1)\n", encoding="utf-8")
        (root / ".gitignore").write_text(".nexus/\n", encoding="utf-8")
        _run(["git", "add", "-A"], root)
        _run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], root)

        good = Sandbox(root, name="op", gate="python tools/lint_harness.py")
        result = good.attempt(lambda path: (path / "app.py").write_text("VALUE = 2\n",
                                                                        encoding="utf-8"))
        check("un cambio con gate verde se promueve", result["ok"], True)
        check("y llega al arbol principal", (root / "app.py").read_text(encoding="utf-8"),
              "VALUE = 2\n")
        check("la lista de promovidos es la real", result["promoted"], ["app.py"])
        check("el worktree se retira", result["files"], ["app.py"])
        check("no queda el directorio", any((root / BASE_REL).glob("*")), False)

        bad = Sandbox(root, name="mal", gate="python tools/bad_gate.py")
        bad_result = bad.attempt(lambda path: (path / "app.py").write_text("VALUE = 3\n",
                                                                          encoding="utf-8"),
                                 files=["app.py"])
        check("gate rojo NO promueve", bad_result["ok"], False)
        check("el arbol principal queda intacto", (root / "app.py").read_text(encoding="utf-8"),
              "VALUE = 2\n")

        class Boom:
            def __call__(self, path):
                (path / "app.py").write_text("ROTO = (\n", encoding="utf-8")
                raise RuntimeError("el obrero se cayo")
        exploded = Sandbox(root, name="boom").attempt(Boom())
        check("un Obrero que lanza no rompe el arbol", exploded["ok"], False)
        check("y el fichero sigue como estaba", (root / "app.py").read_text(encoding="utf-8"),
              "VALUE = 2\n")
        code, branches = _run(["git", "branch", "--list", "nexus/sandbox/*"], root)
        check("no quedan ramas de sandbox", branches.strip(), "")

        # Un kill duro no corre el `finally`: el worktree se queda. `reap` lo limpia por edad.
        orphan = Sandbox(root, name="huerfano")
        orphan.create()
        check("el worktree huerfano existe", orphan.path.is_dir(), True)
        check("reap no toca uno recien creado", reap(root, max_age_minutes=60), [])
        import os
        import time as _time
        past = _time.time() - 4 * 3600
        os.utime(orphan.path, (past, past))
        removed = reap(root, max_age_minutes=60)
        check("reap borra el huerfano viejo", removed, [orphan.name])
        check("y no queda el directorio", orphan.path.exists(), False)
        check("ni su rama", _run(["git", "branch", "--list", "nexus/sandbox/*"], root)[1].strip(), "")
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("worktree_sandbox: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
