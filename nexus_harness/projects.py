"""Los proyectos del workspace: quien manda, en que orden, y como nace uno nuevo gobernado.

Tres cosas viven aqui, y las tres son estado que sobrevive a un reinicio:

* **El orden de prioridad** (`project_order` en `~/.nexus/harness.json`). El operador arrastra las
  tarjetas y este orden es el que obedece el bucle autonomo: primero el #1, luego el #2. Se guarda por
  el escritor de siempre (`onboarding.save_settings`), no con un `open(...,'w')` a mano, para que un
  ajuste tenga una sola puerta.
* **La creacion de un proyecto gobernado**: carpeta, `git init` con su primer commit, `.ai/` con sus
  reglas y el Auto-Spec del protocolo. Un proyecto sin esos dos ficheros no esta gobernado, y la
  pantalla lo dice con esas palabras.
* **El progreso del bucle autonomo** (`<proyecto>/.nexus/harness/autonomy.json`): que pasos estan
  hechos, cuantas iteraciones se gastaron y con que resultado. Se escribe DESPUES de un gate verde,
  nunca antes: marcar hecho lo que no se ha probado es la unica mentira que este arnes no se permite.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import backup, onboarding

SPEC_REL = Path(".ai") / "CURRENT_SPEC.json"
RULES_REL = Path(".ai") / "PROJECT_RULES.md"
PROGRESS_REL = Path(".nexus") / "harness" / "autonomy.json"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")

RULES_TEMPLATE = """# %(name)s — reglas del proyecto

Gobernado por Nexus Protocol desde el primer commit. Lo que un humano revisa, en una pagina.

## Leyes

- Ningun fichero pasa de 400 lineas (`nexus/checks/rules_lint.py`).
- Nada de codigo muerto ni bloques comentados: git guarda lo que se quita.
- Una afirmacion no es una prueba: la prueba es un comando con su `exit 0`.
- Objetivo inicial: %(goal)s

## APPROVED DEPENDENCIES

- nexus -- el gobernador (lint, spec, gate). Se importa, nunca se copia.
"""


def _run(root, *args, timeout=90):
    """Un comando de git sin consola. Windows: CREATE_NO_WINDOW, o el operador ve un parpadeo negro."""
    flags = 0x08000000 if os.name == "nt" else 0
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              errors="replace", timeout=timeout, creationflags=flags)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "%s: %s" % (type(exc).__name__, exc)
    return done.returncode, ((done.stdout or "") + (done.stderr or "")).strip()


def spec_of(root):
    """Lo que el proyecto tiene congelado, leido del disco. Acepta los dos formatos de spec."""
    path = Path(root) / SPEC_REL
    empty = {"present": False, "goal": "", "criteria": 0, "sha": "", "tests": "", "format": ""}
    if not path.is_file():
        return empty
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(empty, present=True, error="ilegible")
    if not isinstance(spec, dict):
        return dict(empty, present=True, error="formato desconocido")
    criteria = spec.get("cas_count")
    if criteria is None:
        criteria = len(spec.get("cas") or spec.get("criteria") or [])
    tests = spec.get("tests") if isinstance(spec.get("tests"), dict) else {}
    return {"present": True, "goal": str(spec.get("goal") or ""),
            "criteria": int(criteria or 0),
            "sha": str(spec.get("cas_sha256") or spec.get("sha256") or "")[:16],
            "tests": str(tests.get("command") or ""),
            "format": str(spec.get("format") or spec.get("schema") or ""),
            "id": str(spec.get("id") or "")}


def governed(workspace):
    """Las carpetas del workspace que tienen spec: esas son las que se pueden poner en cola."""
    base = Path(workspace)
    try:
        names = sorted(path.name for path in base.iterdir()
                       if path.is_dir() and not path.name.startswith((".", "_")))
    except OSError:
        return []
    return [name for name in names if (base / name / SPEC_REL).is_file()]


def plain(workspace, governed_names=()):
    """Las demas: existen, no estan gobernadas. Se listan, no se esconden."""
    base = Path(workspace)
    known = set(governed_names or governed(workspace))
    try:
        return sorted(path.name for path in base.iterdir()
                      if path.is_dir() and not path.name.startswith((".", "_"))
                      and path.name not in known)
    except OSError:
        return []


def order(config):
    """El orden que manda: primero lo declarado y que existe, luego el resto por nombre."""
    names = governed(config.workspace)
    declared = [str(name) for name in (getattr(config, "project_order", None) or [])]
    first = [name for name in declared if name in names]
    return first + [name for name in names if name not in first]


def save_order(config, names):
    """Guarda la cola. Devuelve `(guardado, notas)`; lo que no es un proyecto del workspace se cae."""
    valid = set(governed(config.workspace))
    clean, dropped = [], []
    for name in names or []:
        name = str(name or "").strip()
        if not name or name in clean:
            continue
        (clean if name in valid else dropped).append(name)
    for name in order(config):
        if name not in clean:
            clean.append(name)
    saved, notes = onboarding.save_settings({"project_order": clean})
    if dropped:
        notes = list(notes) + ["fuera de la cola (no gobernados o inexistentes): %s"
                               % ", ".join(dropped)]
    return clean if "project_order" in saved else [], notes


def move(config, name, direction="up"):
    """Sube o baja un proyecto un puesto. Se usa cuando no hay raton: el teclado tambien ordena."""
    current = order(config)
    if name not in current:
        return current, "«%s» no está en la cola" % name
    index = current.index(name)
    target = index - 1 if str(direction) == "up" else index + 1
    if target < 0 or target >= len(current):
        return current, "«%s» ya está en el extremo" % name
    current[index], current[target] = current[target], current[index]
    saved, notes = save_order(config, current)
    return saved or current, notes[0] if notes else ""


def progress(root):
    """Lo que el bucle autonomo dejo escrito. `steps` es la historia, no una promesa."""
    path = Path(root) / PROGRESS_REL
    if not path.is_file():
        return {"steps": [], "iterations": 0, "done": False, "goal": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"steps": [], "iterations": 0, "done": False, "goal": "", "error": "ilegible"}
    data.setdefault("steps", [])
    data.setdefault("iterations", 0)
    data.setdefault("done", False)
    return data


def save_progress(root, payload):
    path = Path(root) / PROGRESS_REL
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
                        encoding="utf-8")
    except OSError:
        return False
    return True


def queue(config):
    """La cola con todo lo que la pantalla necesita: puesto, spec, test, backups y progreso."""
    rows = []
    tests = dict(getattr(config, "project_tests", None) or {})
    for index, name in enumerate(order(config), start=1):
        root = Path(config.workspace) / name
        rows.append({"position": index, "name": name, "root": str(root),
                     "spec": spec_of(root), "test": tests.get(name, ""),
                     "backups": len(backup.listing(root, limit=3)),
                     "progress": progress(root)})
    return rows


def _git_init(root):
    """`git init` y un primer commit con identidad local: sin HEAD no hay snapshot que restaurar."""
    if shutil.which("git") is None:
        return False, "git no está en el PATH: el proyecto se crea sin repositorio"
    code, detail = _run(root, "init", "-q")
    if code != 0:
        return False, "git init falló: %s" % detail
    _run(root, "add", "-A")
    code, detail = _run(root, "-c", "user.name=Nexus Harness", "-c", "user.email=nexus@localhost",
                        "commit", "-q", "-m", "primer commit: proyecto gobernado por Nexus Harness")
    return code == 0, "" if code == 0 else "sin commit inicial: %s" % detail


def create(config, name, goal="", workspace=None):
    """Crea `workspace/<nombre>` gobernado: carpetas, git, reglas y Auto-Spec. `{ok, ...}`."""
    clean = str(name or "").strip()
    if not NAME_RE.match(clean):
        return {"ok": False, "reason": "nombre inválido: letras, números, espacio, punto, guion "
                                       "y guion bajo (máx. 64), empezando por letra o número"}
    base = Path(workspace or config.workspace)
    root = base / clean
    if root.exists():
        return {"ok": False, "reason": "ya existe %s" % root}
    try:
        (root / ".ai").mkdir(parents=True)
        (root / RULES_REL).write_text(RULES_TEMPLATE % {"name": clean, "goal": goal or "por definir"},
                                      encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "reason": "no se pudo crear %s: %s" % (root, exc)}
    git_ok, git_note = _git_init(root)
    governance = onboarding.governance(root)
    # Al final de la cola: un proyecto recien creado no puede adelantar al que el operador puso el #1.
    saved, notes = save_order(config, list(order(config)) + [clean])
    return {"ok": True, "name": clean, "root": str(root), "git": git_ok, "git_note": git_note,
            "governance": governance, "order": saved,
            "notes": list(notes) + ([str(governance.get("reason") or "")] if not governance.get("ok")
                                    else [])}
