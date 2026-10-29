"""El gimnasio: correr las tareas golden contra el bucle de verdad y contar cuantas pasan.

No mide tokens ni velocidad: mide **aciertos**. Un harness que ahorra el 60 % del contexto y falla la
mitad de las tareas no esta optimizado, esta incompleto, y sin esta tabla no habia forma de saberlo.

Dos modos, y el deterministico no es un juguete:

* `fake=True` usa un modelo guionizado por tarea. No mide al modelo: mide al ARNES (que el bucle, las
  herramientas y el gate conviertan un guion correcto en verde, y un fichero que rompe la ley en rojo).
  Es lo que corre en CI (`tools/proofs.py eval`).
* `fake=False` apunta al modelo real (`Router`), con el rol `worker` pisado. Es la tabla que dice si el
  modelo que tienes resuelve el trabajo, y la que se compara entre modelos.

Se ejecuta con el MISMO `Triad` que produccion: Director, Obrero, gate, Juez y reparaciones.
"""
import time
from dataclasses import dataclass, field
from pathlib import Path

from .eval_tasks import TASKS, Task, selected
from .platform.events import Bus
from .gate import Gate
from .judge import judge_for
from .providers import Router
from .selftests.fakes import FakeRouter, ScriptedProvider, ScriptedSkills, TempProject, reply
from .triad_loop import Triad

APPROVE = '{"verdict": "approve", "reason": "el gate esta verde"}'


@dataclass
class Row:
    """Una tarea ejecutada: veredicto, por que, y lo que costo."""

    id: str
    ok: bool = False
    exit: object = None
    expect_exit: int = 0
    reasons: list = field(default_factory=list)
    steps: int = 0
    repairs: int = 0
    tokens: int = 0
    seconds: float = 0.0
    touched: list = field(default_factory=list)
    detail: str = ""
    skipped: bool = False
    attempt: int = 1
    judge: str = ""
    judge_reason: str = ""

    def as_dict(self):
        return {"id": self.id, "ok": self.ok, "exit": self.exit, "expect_exit": self.expect_exit,
                "reasons": list(self.reasons), "steps": self.steps, "repairs": self.repairs,
                "tokens": self.tokens, "seconds": round(self.seconds, 2),
                "touched": list(self.touched), "detail": self.detail,
                "skipped": self.skipped, "attempt": self.attempt,
                "judge": self.judge, "judge_reason": self.judge_reason}


def _config(root, task, real=False):
    """Config del eval: roles falsos en modo guionizado, los del operador en modo real."""
    from .config import HarnessConfig
    if real:
        config = HarnessConfig.load(root=root)
    else:
        config = HarnessConfig(default_root=root,
                               roles={"director": "fake:d", "worker": "fake:w", "judge": "fake:j"})
    config.default_root = Path(root)
    config.test_command = task.test
    config.max_steps, config.max_repairs = 8, 2
    config.temperature = 0.0      # el eval se compara entre modelos: misma temperatura siempre
    config.worktree_repairs = False      # el proyecto del eval no es git: no hay worktree que abrir
    return config


def _router(config, task, model=None):
    """Un router guionizado (CI) o el de verdad con el worker pisado (medicion de modelo)."""
    if model:
        config.roles["worker"] = str(model)
        return Router(config)
    return FakeRouter(workers=ScriptedProvider(list(task.script)),
                      judge=ScriptedProvider([reply(APPROVE)], default=reply(APPROVE)))


def row_judge(result):
    return str((result.judgement or {}).get("verdict") or "")


def row_reason(result):
    return str((result.judgement or {}).get("reason") or "")


def _grade(task, result, events, root):
    """Lo que la tarea exige, comprobado en disco y en el bus. Nunca por el resumen del modelo."""
    reasons = []
    if result.exit != task.expect_exit:
        detail = str((result.verdict or {}).get("failures") or "").strip()
        line = "exit %s, esperaba %s" % (result.exit, task.expect_exit)
        if detail:
            line += ": " + detail[:300]
        elif row_judge(result) == "reject":
            line += ": el Juez lo rechazo (%s)" % (row_reason(result) or "sin motivo")
        reasons.append(line)
    for name, needles in (task.contains or {}).items():
        path = Path(root) / name
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        for needle in needles:
            if needle not in text:
                reasons.append("%s no contiene %r" % (name, needle))
    for name, needles in (task.excludes or {}).items():
        path = Path(root) / name
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        for needle in needles:
            if needle in text:
                reasons.append("%s todavia contiene %r" % (name, needle))
    for name, minimum in (task.over_lines or {}).items():
        path = Path(root) / name
        if path.is_file():
            body = path.read_text(encoding="utf-8", errors="replace")
            total = body.count(chr(10)) + 1
            if total < int(minimum):
                reasons.append("%s tiene %d lineas, esperaba mas de %d" % (name, total, minimum))
    if task.needs_refusal:
        refused = [event for event in events if event.get("kind") == "tool.call"
                   and not event.get("payload", {}).get("ok", True)
                   and "refused" in str(event.get("payload", {}).get("result", ""))]
        if not refused:
            reasons.append("no hubo negativa de politica en el turno")
    return reasons


def run_task(task, model=None, attempt=1):
    """Ejecuta una tarea y devuelve su `Row`. No lanza: un fallo del arnes es un FAIL, no un crash."""
    started = time.time()
    row = Row(id=task.id, expect_exit=task.expect_exit, attempt=attempt)
    if model and task.script_only:
        row.skipped = True
        row.ok = True
        row.reasons = ["no medible con un modelo real: exige que obedezca una orden destructiva"]
        return row
    try:
        with TempProject(dict(task.files)) as root:
            config = _config(root, task, real=bool(model))
            router = _router(config, task, model)
            bus = Bus()
            triad = Triad(router, config, gate=Gate(root, config), judge=judge_for(router, config, "es"),
                          skills=ScriptedSkills(), bus=bus)
            result = triad.run(task.goal)
            row.exit, row.steps, row.repairs = result.exit, result.steps, result.repairs
            row.tokens = int((result.tokens or {}).get("total", 0) or 0)
            row.touched = list(result.touched or [])
            row.detail = str((result.verdict or {}).get("failures") or "")[:600]
            row.judge = str((result.judgement or {}).get("verdict") or "")
            row.judge_reason = str((result.judgement or {}).get("reason") or "")[:300]
            row.reasons = _grade(task, result, bus.all(), root)
    except Exception as exc:  # noqa: BLE001 -- el eval mide el arnes, tambien sus caidas
        row.reasons = ["el arnes lanzo %s: %s" % (type(exc).__name__, exc)]
    row.ok = not row.reasons
    row.seconds = time.time() - started
    return row


def run(names=None, model=None, tasks=None, repeat=1):
    """Corre las tareas pedidas, `repeat` veces cada una. Devuelve el agregado y las filas.

    `passed` cuenta tareas con al menos un intento bueno; `stable`, las que pasaron en TODOS. Con un
    modelo real las dos cifras difieren, y esa diferencia es la informacion: pass@k no es fiabilidad.
    """
    chosen, missing = selected(names)
    if tasks is not None:
        chosen = list(tasks)
    rows = [run_task(task, model=model, attempt=index + 1)
            for task in chosen for index in range(max(1, int(repeat)))]
    by_task = {}
    for row in rows:
        by_task.setdefault(row.id, []).append(row)
    passed = len([name for name, group in by_task.items() if any(row.ok for row in group)])
    stable = len([name for name, group in by_task.items() if all(row.ok for row in group)])
    skipped = len([name for name, group in by_task.items() if all(row.skipped for row in group)])
    return {"suite": "core", "model": str(model or "guionizado"), "passed": passed,
            "stable": stable, "skipped": skipped, "repeat": max(1, int(repeat)),
            "total": len(by_task), "ok": bool(by_task) and passed == len(by_task),
            "missing": missing, "rows": [row.as_dict() for row in rows]}


def render_markdown(payload):
    """La tabla que se pega en un documento o en un PR. Sin adjetivos: numeros y motivos."""
    lines = ["### Eval · %s" % payload["model"], "",
             "| tarea | resultado | exit | pasos | reparaciones | tokens |",
             "|---|---|---|---|---|---|"]
    for row in payload["rows"]:
        skipped = bool(row.get("skipped"))
        label = "SKIP" if skipped else ("OK" if row["ok"] else "FAIL")
        exit_text = "—" if skipped else "%s/%s" % (row["exit"], row["expect_exit"])
        tokens = "—" if skipped else "{:,}".format(row["tokens"]).replace(",", ".")
        lines.append("| `%s` | %s | %s | %d | %d | %s |"
                     % (row["id"], label, exit_text, row["steps"], row["repairs"], tokens))
    lines.append("")
    extra = ""
    if payload.get("repeat", 1) > 1:
        extra = " · %d/%d en todos los intentos" % (payload.get("stable", 0), payload["total"])
    if payload.get("skipped"):
        extra += " · %d omitidas (solo medibles con guion)" % payload["skipped"]
    lines.append("**%d/%d tareas resueltas%s.**" % (payload["passed"], payload["total"], extra))
    failed = [row for row in payload["rows"] if not row["ok"]]
    for row in failed:
        lines.append("- `%s`: %s" % (row["id"], "; ".join(row["reasons"])))
    for row in [one for one in payload["rows"] if one.get("skipped")]:
        lines.append("- `%s` (omitida): %s" % (row["id"], "; ".join(row["reasons"])))
    return "\n".join(lines)
