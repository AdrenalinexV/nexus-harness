"""Mutation smoke: un test que no puede ponerse rojo no mide nada.

Se toma el estado CORRECTO de cada tarea (`Task.fixed`) y se le aplican tres mutaciones de linea
deterministas -- un operador cambiado, un numero a cero, una linea menos --. Si el test de la tarea
sigue verde con las tres, el test no prueba lo que dice: es un eval escrito para pasar.

Es barato (unos milisegundos por mutacion) y caza el fallo que ninguna suite de evals suele cazar: la
tarea cuyo comando `print(1)` sale 0 siempre. La ley del repo lo pide en el paso 13: "mutar 3 lineas
pone >=1 test rojo".
"""
import re
import subprocess
from pathlib import Path

from .selftests.fakes import TempProject


def mutants(files):
    """Hasta tres variantes rotas del estado correcto. Deterministas: mismo orden, mismo fallo."""
    out = []

    def add(label, path, broken):
        if broken.strip() and broken != files.get(path):
            out.append((label, dict(files, **{path: broken})))

    for path, text in sorted(files.items()):
        if "+" in text:
            add("operador + -> -", path, text.replace("+", "-", 1))
            break
    for path, text in sorted(files.items()):
        if re.search(r"\d", text):
            add("un numero a cero", path, re.sub(r"\d", "0", text, count=1))
            break
    for path, text in sorted(files.items()):
        lines = text.splitlines()
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            add("sin la ultima linea", path, "\n".join(lines[:-1]) + "\n")
        break
    return out[:3]


def run(task, timeout=60):
    """`[(mutacion, exit)]` del test de la tarea contra cada variante rota."""
    rows = []
    for label, files in mutants(task.fixed):
        with TempProject(dict(task.files)) as root:
            for path, text in files.items():
                target = Path(root) / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8", newline="\n")
            try:
                # `shell=True` sobre `task.test` es el mismo contrato que el gate: el comando lo
                # declara una tarea del repo (o el `test_command` del proyecto), nunca un mensaje del
                # modelo ni una pagina. Sin shell no habria `python -c "..."` ni `bash check.sh`.
                done = subprocess.run(task.test, shell=True, cwd=str(root), capture_output=True,
                                      text=True, errors="replace", timeout=timeout)
                code = done.returncode
            except (OSError, subprocess.TimeoutExpired):
                code = 124
            rows.append((label, code))
    return rows


def survivors(task, timeout=60):
    """Las mutaciones que el test NO vio. Vacio = el test puede fallar; todas = no mide nada."""
    return [label for label, code in run(task, timeout=timeout) if code == 0]
