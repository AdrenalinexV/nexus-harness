"""El oraculo: descubrir con que se prueba este proyecto, y negarse a decir "verde" sin prueba.

Dos fallos que arregla, y el segundo es el caro:

1. Un proyecto con `pytest.ini` o `package.json` no tenia por que declarar a mano su comando: el
   arnes puede leerlo del repositorio, que es donde esta la verdad.
2. Sin comando declarado, `gate.tests()` devolvia `ok=True, blocking=False`. Eso es un **falso verde**:
   el gate decia "verde" habiendo comprobado solo el lint y la ley de 400 lineas. Un rojo honesto vale
   mas que un verde que no probo nada.

La regla nueva, y no se negocia: si el turno toco ficheros y no hay ni runner ni humo posible, el gate
devuelve `20` (*no verificable*), no `0`. Un proyecto al que no se le puede medir el comportamiento se
arregla declarando su comando, no relajando el gate.
"""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

TIMEOUT = 240
SMOKE_TIMEOUT = 60
WINDOWS_FLAGS = 0x08000000 if os.name == "nt" else 0

# Orden: el mas especifico primero. Cada fila es `(fichero, comprobacion opcional, comando)`.
RUNNERS = (
    ("pytest.ini", None, "python -m pytest -q"),
    ("pyproject.toml", "tool.pytest", "python -m pytest -q"),
    ("tox.ini", None, "python -m pytest -q"),
    ("setup.cfg", "tool:pytest", "python -m pytest -q"),
    ("package.json", "scripts.test", "npm test --silent"),
    ("Cargo.toml", None, "cargo test -q"),
    ("go.mod", None, "go test ./..."),
    ("composer.json", None, "vendor/bin/phpunit"),
    ("phpunit.xml", None, "vendor/bin/phpunit"),
    ("Makefile", "test:", "make test"),
)
SKIP_PARTS = {".git", "node_modules", "__pycache__", ".venv", ".nexus", "dist", "build", "target"}


def _mentions(path, needle):
    try:
        return needle in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def detect(root):
    """`{command, source}` del runner que este repositorio ya declara, o `{}` si no hay ninguno."""
    base = Path(root)
    package = base / "package.json"
    if package.is_file() and _npm_test(package):
        return {"command": "npm test --silent", "source": "package.json"}
    for name, needle, command in RUNNERS:
        path = base / name
        if name == "package.json" or not path.is_file():
            continue
        if needle and not _mentions(path, needle):
            continue
        return {"command": command, "source": name}
    tests = base / "tests"
    if tests.is_dir() and any(tests.rglob("test_*.py")):
        return {"command": "python -m pytest -q", "source": "tests/"}
    return {}


def _npm_test(path):
    """Un `package.json` solo es runner si declara un script `test` de verdad."""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return False
    scripts = data.get("scripts") if isinstance(data, dict) else None
    return bool(isinstance(scripts, dict) and str(scripts.get("test") or "").strip())


def python_files(root, touched):
    """Los `.py` que el turno toco y siguen existiendo, en orden estable."""
    base = Path(root)
    found = []
    for name in sorted(set(touched or ())):
        path = base / str(name)
        if path.suffix == ".py" and path.is_file() and not (SKIP_PARTS & set(path.parts)):
            found.append(str(name).replace("\\", "/"))
    return found


def smoke_script(root, files):
    """Un script que IMPORTA cada fichero tocado. Ejecutarlo es comportamiento, no sintaxis.

    Se importa por ruta (`spec_from_file_location`) para no exigir que el proyecto sea un paquete, y
    se hace en un subproceso: si el modulo tiene efectos al importar, el que se entera es el gate y no
    el proceso del arnes.
    """
    lines = ["import importlib.util, sys", "problems = []", "root = %r" % str(Path(root))]
    for index, name in enumerate(files):
        lines.extend([
            "path = root + '/' + %r" % name,
            "spec = importlib.util.spec_from_file_location('nexus_smoke_%d', path)" % index,
            "module = importlib.util.module_from_spec(spec)",
            "try:",
            "    spec.loader.exec_module(module)",
            "except BaseException as exc:",
            "    problems.append(%r + ': ' + type(exc).__name__ + ': ' + str(exc))" % name,
        ])
    lines.extend([
        "print('smoke: %%d/%%d importables' %% (%d - len(problems), %d))"
        % (len(files), len(files)),
        "print('\\n'.join(problems))",
        "sys.exit(0 if not problems else 10)",
    ])
    return "\n".join(lines)


def smoke(root, files):
    """`(ok, detail)`: importa los ficheros tocados en un subproceso aislado."""
    files = python_files(root, files)
    if not files:
        return None, "sin ficheros python que probar"
    cache = Path(tempfile.mkdtemp(prefix="nexus-smoke-"))
    environment = dict(os.environ, PYTHONPYCACHEPREFIX=str(cache), PYTHONDONTWRITEBYTECODE="1")
    try:
        completed = subprocess.run(["python", "-c", smoke_script(root, files)], cwd=str(root),
                                   capture_output=True, text=True, errors="replace",
                                   timeout=SMOKE_TIMEOUT, env=environment,
                                   creationflags=WINDOWS_FLAGS)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "no se pudo ejecutar el humo: %s: %s" % (type(exc).__name__, exc)
    finally:
        shutil.rmtree(cache, ignore_errors=True)
    output = ((completed.stdout or "") + (completed.stderr or "")).strip()
    return completed.returncode == 0, output[-2000:] or "sin salida"


def write_report(root, payload, rel=".nexus/harness/oracle.json"):
    """Deja el plan y su resultado en disco: una decision del gate se puede auditar despues."""
    path = Path(root) / rel
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False),
                        encoding="utf-8")
        return str(path)
    except OSError:
        return ""
