"""Un doc no puede contradecir al motor. Este comando lo comprueba, y por eso puede fallar.

    python tools/doc_truth.py [--check|--write]

**Por qué existe.** `README.md` decía «50 suites» y «49» en dos líneas distintas, el CI repetía «49»,
la propuesta de arquitectura también, y la real era 55 — y el titular del eval contaba las dos omitidas
como resueltas. Ninguno de esos números lo había medido nadie: se copiaron de un run anterior y
sobrevivieron a la sesión que iba a desmentirlos. Un documento que publica cifras a mano es una
promesa caducada; la única forma de que no vuelva es que el número se lea de la fuente y que el build
se ponga rojo cuando no cuadre.

**Dos clases de documento, y las dos se declaran aquí:**

* `CURRENT` — habla del árbol de hoy. Cada cifra que publique está en `RULES` con la regla que la
  genera; si no coincide, rojo.
* `SNAPSHOT` — retrata un commit pasado. No se le exige que cuadre (sería reescribir historia), pero
  sí que **diga qué commit retrata**: la marca `SNAPSHOT_MARK` con un sha que exista en el repo. Un
  doc histórico sin fecha es un número viejo con la misma autoridad que uno nuevo.

Un documento que cita una cifra y no está en ninguna de las dos listas también es rojo: así no se
puede añadir una cifra nueva sin decidir de qué clase es.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # el propio paquete, para `platform.console` sin instalar nada
    sys.path.insert(0, str(ROOT))
MARK = "Congelado en `%s`"

# --- documentos que hablan del árbol de HOY ------------------------------------------------------
CURRENT = ("README.md", "docs/ARCHITECTURE.md", "docs/ARCHITECTURE_V2_PROPOSAL.md",
           "docs/COMPETITIVE_AUDIT_V2.md", "docs/DOSSIER_RELEASE.md", "docs/EVAL.md",
           "docs/BACKLOG.md", ".github/workflows/verify.yml")

# --- documentos que retratan un commit pasado ----------------------------------------------------
# El sha es el árbol que describen. Si no existe en `git log`, la marca es decorativa y no vale.
SNAPSHOT = {
    "docs/AUTONOMOUS_RUN.md": "5e83a9a",
    "docs/FUTURE_AUDIT.md": "5e83a9a",
    "docs/INFORME_PARA_PERSONAS.md": "5e83a9a",
    "docs/NIGHT_REPORT.md": "5e83a9a",
    "docs/NIGHT_SHIFT.md": "5e83a9a",
    "docs/CONTEXT_SAVINGS_AUDIT.md": "5e83a9a",
    "docs/COMPETITIVE.md": "5e83a9a",
    "docs/AUDIT.md": "5e83a9a",
    "docs/FORENSICS.md": "5e83a9a",
}

# --- documentos que NARRAN corridas pasadas dentro de un flujo vivo -------------------------------
# No publican «el estado de hoy»: cuentan lo que midió una tarea concreta. No se les exige cuadrar
# (sería reescribir el registro), pero sí que su cabecera diga cuándo fue — una fecha o un commit.
NARRATIVE = ("docs/UI_BACKLOG.md", "docs/UI_REWORK.md", "docs/UI_HANDOVER.md", "docs/UI_GUIDE.md",
             "docs/DESKTOP.md", "docs/MORNING_REPORT.md", "docs/RESEARCH.md")
DATED = re.compile(r"\d{4}-\d{2}-\d{2}|\b[0-9a-f]{7}\b")

# Shas que no se pudieron comprobar porque el clon es superficial (CI con fetch-depth 1).
SHALLOW = []
# Claves cuya fuente no está en esta máquina (el ahorro vive en un artefacto local, gitignored).
UNMEASURED = set()

# Una cifra medida se detecta con estos patrones: si un doc las cita, tiene que estar clasificado.
SMELL = re.compile(r"\b\d+ suites\b|\bfiles=\d+|\bsuites=\d+|\b\d+ ficheros\b|\b\d+ módulos\b")


def _sh(command):
    return subprocess.run(command, cwd=str(ROOT), capture_output=True, text=True, errors="replace")


def measured():
    """Las cifras, cada una de su fuente. Ninguna se teclea."""
    sys.path.insert(0, str(ROOT))
    from nexus_harness.selftests import SUITES

    lint = _sh([sys.executable, str(ROOT / "tools" / "lint_harness.py")])
    line = (lint.stdout or "").strip().splitlines()[-1] if lint.stdout.strip() else ""
    counts = dict(chunk.split("=") for chunk in line.split() if "=" in chunk and chunk.split("=")[0].isalpha())
    # El ahorro sale de un artefacto LOCAL (`.nexus/harness/benchmark_ab.json`, gitignored): en un clon
    # limpio no existe. Eso no es «0 %» ni un verde: es **no medido**, y se dice con esas palabras.
    ab = _sh([sys.executable, str(ROOT / "tools" / "benchmark_ab_savings.py"), "--doc-only"])
    import json
    note = ""
    savings = {}
    if ab.returncode == 0 and ab.stdout.strip():
        try:
            savings = json.loads(ab.stdout.strip().splitlines()[-1])
        except ValueError:
            note = "benchmark_ab_savings no devolvio JSON"
    if not savings:
        note = note or "falta .nexus/harness/benchmark_ab.json en esta maquina (artefacto local)"
    subdirs = [p for p in (ROOT / "nexus_harness").iterdir()
               if p.is_dir() and not p.name.startswith((".", "__"))]
    engine = [p for p in (ROOT / "nexus_harness").rglob("*.py")
              if "selftests" not in p.parts and "__pycache__" not in p.parts]
    return {
        "suites": len(SUITES),
        "files": int(counts.get("files", 0)),
        "findings": int(counts.get("findings", 0)),
        "flat": len(list((ROOT / "nexus_harness").glob("*.py"))),
        "dirs": len(subdirs),
        "loc": sum(len(p.read_text(encoding="utf-8", errors="replace").splitlines()) for p in engine),
        "savings": float(savings["savings_pct"]) if "savings_pct" in savings else None,
        "multiplier": float(savings["window_life_multiplier"]) if "window_life_multiplier" in savings else None,
        "note": note,
    }


# (documento, patrón con UN grupo numérico, clave de `measured()`)
RULES = (
    ("README.md", r"the same (\d+) suites", "suites"),
    ("README.md", r"# (\d+) deterministic suites", "suites"),
    (".github/workflows/verify.yml", r"all (\d+) suites", "suites"),
    ("docs/ARCHITECTURE.md", r"(\d+) deterministic suites", "suites"),
    ("docs/ARCHITECTURE_V2_PROPOSAL.md", r"verify: GREEN` — (\d+) suites", "suites"),
    ("docs/ARCHITECTURE_V2_PROPOSAL.md", r"tiene ~?(\d+) módulos planos", "flat"),
    ("docs/COMPETITIVE_AUDIT_V2.md", r"`verify` \((\d+) suites\)", "suites"),
    ("docs/COMPETITIVE_AUDIT_V2.md", r"lint 0 hallazgos / (\d+) suites", "suites"),
    ("docs/DOSSIER_RELEASE.md", r"suites=(\d+) failures=0", "suites"),
    ("docs/DOSSIER_RELEASE.md", r"files=(\d+) findings=", "files"),
    ("docs/DOSSIER_RELEASE.md", r"en (\d+) ficheros", "files"),
    ("docs/DOSSIER_RELEASE.md", r"(\d+) suites, 0 hallazgos", "suites"),
    ("docs/DOSSIER_RELEASE.md", r"Suites deterministas \| \*\*(\d+),", "suites"),
    ("docs/DOSSIER_RELEASE.md", r"−(\d+[,.]\d) % de tokens", "savings"),
    ("docs/BACKLOG.md", r"Medido hoy: (\d+) suites", "suites"),
    ("docs/BACKLOG.md", r"· (\d+) ficheros ·", "files"),
)


def _same(stated, real):
    try:
        value = float(str(stated).replace(",", "."))
    except ValueError:
        return False
    return abs(value - float(real)) <= 0.05


def _render(stated, real):
    """Respeta el estilo que el doc ya usaba (coma o punto) para que `--write` no reformatee."""
    text = "%g" % real
    return text.replace(".", ",") if "," in stated else text


def check_current(values):
    problems = []
    covered = set()
    for doc, pattern, key in RULES:
        path = ROOT / doc
        if not path.is_file():
            problems.append("%s no existe (regla en doc_truth RULES)" % doc)
            continue
        text = path.read_text(encoding="utf-8")
        hits = re.findall(pattern, text)
        if not hits:
            problems.append("%s: la regla /%s/ ya no casa con nada — la frase cambió, actualiza RULES" % (doc, pattern))
            continue
        covered.add(doc)
        if values.get(key) is None:
            # No medido no es rojo ni verde: se dice y se sigue. El ahorro vive en un artefacto local.
            UNMEASURED.add(key)
            continue
        for stated in hits:
            if not _same(stated, values[key]):
                problems.append("%s: publica %r en /%s/ y la fuente mide %s=%s"
                                % (doc, stated, pattern, key, _render(str(stated), values[key])))
    return problems, covered


def _self_consistent():
    """Dos docs cuya cifra sale de SU PROPIA tabla: si el titular no cuadra con la tabla, es rojo."""
    problems = []
    eval_doc = (ROOT / "docs" / "EVAL.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| `[^`]+` \| (OK|SKIP|FAIL) \|", eval_doc, re.M)
    head = re.search(r"\*\*(\d+)/(\d+) tareas resueltas · (\d+) omitidas", eval_doc)
    if not head:
        problems.append("docs/EVAL.md: no encuentro el titular «N/M tareas resueltas · K omitidas»")
    elif rows:
        ok, skip = rows.count("OK"), rows.count("SKIP")
        if (int(head.group(1)), int(head.group(2)), int(head.group(3))) != (ok, len(rows), skip):
            problems.append("docs/EVAL.md: el titular dice %d/%d resueltas y %d omitidas; su propia tabla dice "
                            "%d OK, %d total, %d SKIP" % (int(head.group(1)), int(head.group(2)),
                                                          int(head.group(3)), ok, len(rows), skip))
    return problems


MEANS = (("Media simple", lambda w, v: sum(v) / len(v)),
         ("Media ponderada", lambda w, v: sum(x * y for x, y in zip(w, v)) / sum(w)))


def _matrix():
    """La matriz del dossier leída como la leería un humano: por columna (herramienta), no por fila."""
    text = (ROOT / "docs" / "DOSSIER_RELEASE.md").read_text(encoding="utf-8")
    section = text.split("## 3. La matriz", 1)[-1].split("###", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| **") and "×" in line]
    if len(rows) < 5:
        return None, None, section
    weights, per_axis = [], []
    for line in rows:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        weights.append(float(re.search(r"×([\d.,]+)", cells[0]).group(1).replace(",", ".")))
        per_axis.append([float(cell.replace("*", "").replace(",", ".").strip()) for cell in cells[1:]])
    tools = list(zip(*per_axis))
    return weights, tools, section


def _means(write_it=False):
    """La media publicada del dossier tiene que ser la media de SU matriz, no un número aparte."""
    weights, tools, section = _matrix()
    if weights is None:
        return ["docs/DOSSIER_RELEASE.md: no reconozco la matriz de §3 (¿cambió el formato?)"]
    problems, updated = [], section
    for label, fn in MEANS:
        stated = re.findall(r"\*\*(Media simple|Media ponderada)\*\* \| ([^|]+)\|", section)
        values = next((cell for name, cell in stated if name == label), None)
        if values is None:
            problems.append("docs/DOSSIER_RELEASE.md: falta la fila «%s»" % label)
            continue
        declared = [float(v.replace(",", ".")) for v in re.findall(r"[\d.,]+", values)
                    if re.fullmatch(r"\d+[.,]\d", v)]
        comma = "," in str(values)
        real = [("%.1f" % fn(weights, tool)).replace(".", ",") if comma else "%.1f" % fn(weights, tool)
                for tool in tools]
        for index, value in enumerate(declared):
            if index >= len(tools):
                break
            if abs(fn(weights, tools[index]) - value) > 0.05:
                problems.append("docs/DOSSIER_RELEASE.md §3: «%s» columna %d publica %.1f y su matriz da %.2f"
                                % (label, index + 1, value, fn(weights, tools[index])))
        if write_it and declared:
            real[0] = "**%s**" % real[0].strip("*")
            row = re.compile(r"\| \*\*" + label + r"\*\* \|[^\n]*")
            updated = row.sub("| **%s** | " % label + " | ".join(real) + " |", updated, count=1)
    if write_it and updated != section:
        text = (ROOT / "docs" / "DOSSIER_RELEASE.md").read_text(encoding="utf-8")
        (ROOT / "docs" / "DOSSIER_RELEASE.md").write_text(text.replace(section, updated, 1), encoding="utf-8")
    return problems


def check_snapshots():
    problems = []
    for doc, sha in SNAPSHOT.items():
        path = ROOT / doc
        if not path.is_file():
            problems.append("%s está en SNAPSHOT y no existe" % doc)
            continue
        text = path.read_text(encoding="utf-8")
        if (MARK % sha) not in text:
            problems.append("%s cita cifras pero no dice qué commit retrata: falta `%s`" % (doc, MARK % sha))
        if _sh(["git", "cat-file", "-e", sha + "^{commit}"]).returncode != 0:
            # Un clon superficial no tiene el commit, y eso no es una mentira del doc: es que no se
            # pudo mirar. Se dice "no comprobado" en la línea de resumen en vez de inventar un rojo.
            if _sh(["git", "rev-parse", "--is-shallow-repository"]).stdout.strip() == "true":
                SHALLOW.append(sha)
            else:
                problems.append("%s declara el commit %s, que no existe en este repo" % (doc, sha))
    return problems


def check_narrative():
    """Un doc que narra corridas pasadas tiene que decir cuándo: si no, su cifra se lee como de hoy."""
    problems = []
    for doc in NARRATIVE:
        path = ROOT / doc
        if not path.is_file():
            problems.append("%s está en NARRATIVE y no existe" % doc)
            continue
        head = path.read_text(encoding="utf-8", errors="replace")[:600]
        if not DATED.search(head):
            problems.append("%s narra cifras y su cabecera no trae fecha ni commit: parece hablar de hoy" % doc)
    return problems


def classify():
    """Todo doc que cite una cifra medida tiene que estar en CURRENT, SNAPSHOT o NARRATIVE."""
    problems = []
    docs = [p for p in ROOT.rglob("*.md")
            if not any(part.startswith(".") or part == "node_modules" for part in p.parts)]
    docs.append(ROOT / ".github" / "workflows" / "verify.yml")
    for path in docs:
        rel = path.relative_to(ROOT).as_posix()
        if rel in CURRENT or rel in SNAPSHOT or rel in NARRATIVE:
            continue
        if rel.startswith(("docs/VERIFICATION", "docs/AUDIT_2026")):
            continue
        if path.is_file() and SMELL.search(path.read_text(encoding="utf-8", errors="replace")):
            problems.append("%s cita cifras medidas y no está clasificado en doc_truth (CURRENT o SNAPSHOT)" % rel)
    return problems


def write(values):
    changed = []
    for doc, pattern, key in RULES:
        if values.get(key) is None:
            continue  # no medido: reescribir con 0 seria inventar la cifra, justo lo que se persigue
        path = ROOT / doc
        text = path.read_text(encoding="utf-8")

        def swap(match):
            stated = match.group(1)
            return match.group(0).replace(stated, _render(stated, values[key]), 1)

        updated, count = re.subn(pattern, swap, text)
        if count and updated != text:
            path.write_text(updated, encoding="utf-8")
            changed.append("%s (%d)" % (doc, count))
    return changed


def check():
    """La verificación entera, sin escribir nada: la usan el comando y la suite del gate."""
    values = measured()
    problems, covered = check_current(values)
    problems += _self_consistent() + _means() + check_snapshots() + check_narrative() + classify()
    return problems, values, covered


def main(argv=None):
    # Un diagnostico en UTF-8 no puede morir en una consola cp1252: el hallazgo no es el glifo.
    from nexus_harness.platform.console import enable_utf8
    enable_utf8()
    parser = argparse.ArgumentParser(prog="doc_truth")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="falla si un doc contradice al motor (por defecto)")
    group.add_argument("--write", action="store_true", help="reescribe las cifras con el valor medido")
    args = parser.parse_args(argv)
    if args.write:
        changed = write(measured())
        _means(write_it=True)
        print("reescritos: %s" % (", ".join(changed) or "ninguno"))
    problems, values, covered = check()
    for problem in problems:
        print("- %s" % problem)
    pending = ""
    if UNMEASURED:
        pending = " (no medido: %s — %s)" % (", ".join(sorted(UNMEASURED)), values.get("note") or "sin fuente")
    print("doc_truth: %s — suites=%d files=%d flat=%d dirs=%d loc=%d savings=%s reglas=%d docs=%d%s%s"
          % ("GREEN" if not problems else "RED (%d)" % len(problems), values["suites"], values["files"],
             values["flat"], values["dirs"], values["loc"],
             "no medido" if values["savings"] is None else "%.1f%%" % values["savings"],
             len(RULES), len(covered),
             "" if not SHALLOW else " (sha no comprobado: clon superficial)", pending))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
