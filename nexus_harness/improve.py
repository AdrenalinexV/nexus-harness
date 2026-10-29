"""Buscador de mejoras: lo que el daemon encola cuando un proyecto ya esta verde.

El fallo que evita: un bucle autonomo que termina los criterios y se queda mirando la pared. Si el
trabajo verificado se acaba, lo siguiente que puede hacer sin inventarse un objetivo es **medir el
proyecto y proponer huecos concretos**: sin runner de tests, con TODO acumulados, con ficheros al borde
de la ley de 400, o con el ultimo turno en rojo.

Todo es determinista y barato (lectura de disco, sin modelo). Cada propuesta lleva su **firma**, para
que el daemon no encole la misma mejora cada cinco minutos; la bandeja descarta duplicados abiertos.

Lo que NO hace: escribir criterios en la spec. Una propuesta es una tarea para que el bucle la trabaje
con su gate delante; congelar criterios sin ejecutarlos seria volver al principio del problema.
"""
from pathlib import Path

from .platform import ledger
from . import oracle, tasks
from .spec_synth import SPEC_REL

MAX_FILES = 400
BIG_FILE = 350
TODO = ("TODO", "FIXME", "XXX", "HACK")
SKIP = {".git", ".nexus", "node_modules", "__pycache__", ".venv", "dist", "build", "target"}


def _python_files(root):
    base = Path(root)
    found = []
    for path in base.rglob("*.py"):
        if SKIP & set(path.parts):
            continue
        found.append(path)
        if len(found) >= MAX_FILES:
            break
    return found


def _relative(root, path):
    try:
        return str(Path(path).relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)


def signals(root, config=None, todo_threshold=5):
    """Las mejoras que este proyecto pide a gritos, con su evidencia y su firma."""
    base = Path(root)
    found = []
    files = _python_files(base)
    if files and not oracle.detect(base) and not getattr(config, "test_command", None):
        found.append({
            "title": "declara como se prueba este proyecto",
            "goal": "Anade un runner de tests al proyecto (pytest.ini, package.json con script test, "
                    "Cargo.toml, go.mod o un test_command en la configuracion) para que el gate pueda "
                    "medir comportamiento y no solo lint.",
            "signature": "oracle:sin-runner",
            "evidence": "%d ficheros python y ningun runner detectado" % len(files),
            "priority": 2})

    todos = {}
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hits = sum(text.count(marker) for marker in TODO)
        if hits:
            todos[_relative(base, path)] = hits
    if sum(todos.values()) >= todo_threshold:
        worst = sorted(todos.items(), key=lambda pair: -pair[1])[:3]
        found.append({
            "title": "reduce los TODO/FIXME acumulados",
            "goal": "Resuelve o convierte en issue los TODO/FIXME de %s (los tres ficheros con mas "
                    "marcas), dejando el gate verde." % ", ".join(name for name, _ in worst),
            "signature": "todos:%d" % sum(todos.values()),
            "evidence": "%d marcas en %d ficheros" % (sum(todos.values()), len(todos)),
            "priority": 6})

    for path in files:
        try:
            total = path.read_text(encoding="utf-8", errors="replace").count("\n") + 1
        except OSError:
            continue
        if total > BIG_FILE:
            name = _relative(base, path)
            found.append({
                "title": "divide %s antes de que rompa la ley" % name,
                "goal": "Divide %s (%d lineas) por responsabilidad, sin cambiar su comportamiento y "
                        "con el gate verde al terminar." % (name, total),
                "signature": "big:%s" % name,
                "evidence": "%d lineas (techo 400)" % total,
                "priority": 4})
            break

    reds = [row for row in ledger.TurnLedger(base).rows()[-20:] if row.get("exit") == 10]
    if reds:
        found.append({
            "title": "repara el ultimo turno rojo",
            "goal": "El ultimo turno autonomo de este proyecto cerro en rojo (%s). Reproduce el fallo, "
                    "arréglalo y deja el gate verde." % (reds[-1].get("at") or "sin fecha"),
            "signature": "red:%s" % (reds[-1].get("at") or ""),
            "evidence": "%d turnos rojos en las ultimas 20 filas" % len(reds),
            "priority": 3})

    if not (base / SPEC_REL).is_file():
        found.append({
            "title": "congela una spec ejecutable",
            "goal": "Convierte el objetivo del proyecto en criterios ejecutables y congelalos en "
                    ".ai/CURRENT_SPEC.json (python -m nexus_harness spec).",
            "signature": "spec:ausente",
            "evidence": "no hay %s" % SPEC_REL.as_posix(),
            "priority": 1})
    return sorted(found, key=lambda row: int(row["priority"]))


def queue(root, config=None, inbox=None, limit=5, todo_threshold=5):
    """Encola las mejores propuestas que no esten ya abiertas. Devuelve las filas anadidas."""
    box = inbox or tasks.Inbox(root)
    added = []
    for signal in signals(root, config, todo_threshold)[:max(1, int(limit))]:
        row = box.add(project=Path(root).name, goal=signal["goal"], source="improve",
                      priority=signal["priority"], evidence=signal["evidence"],
                      signature=signal["signature"])
        if row.get("ok") and not row.get("duplicate"):
            added.append(row)
    return added
