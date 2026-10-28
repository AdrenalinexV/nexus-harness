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
from .events import Bus
from .gate import Gate
from .judge import Judge
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

    def as_dict(self):
        return {"id": self.id, "ok": self.ok, "exit": self.exit, "expect_exit": self.expect_exit,
                "reasons": list(self.reasons), "steps": self.steps, "repairs": self.repairs,
                "tokens": self.tokens, "seconds": round(self.seconds, 2),
                "touched": list(self.touched), "detail": self.detail}


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


def _grade(task, result, events, root):
    """Lo que la tarea exige, comprobado en disco y en el bus. Nunca por el resumen del modelo."""
    reasons = []
    if result.exit != task.expect_exit:
        detail = str((result.verdict or {}).get("failures") or "").strip()
        reasons.append("exit %s, esperaba %s%s" % (result.exit, task.expect_exit,
                                                   (": " + detail[:300]) if detail else ""))
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
    if task.needs_refusal:
        refused = [event for event in events if event.get("kind") == "tool.call"
                   and not event.get("payload", {}).get("ok", True)
                   and "refused" in str(event.get("payload", {}).get("result", ""))]
        if not refused:
            reasons.append("no hubo negativa de politica en el turno")
    return reasons


def run_task(task, model=None):
    """Ejecuta una tarea y devuelve su `Row`. No lanza: un fallo del arnes es un FAIL, no un crash."""
    started = time.time()
    row = Row(id=task.id, expect_exit=task.expect_exit)
    try:
        with TempProject(dict(task.files)) as root:
            config = _config(root, task, real=bool(model))
            router = _router(config, task, model)
            bus = Bus()
            triad = Triad(router, config, gate=Gate(root, config), judge=Judge(router, "es"),
                          skills=ScriptedSkills(), bus=bus)
            result = triad.run(task.goal)
            row.exit, row.steps, row.repairs = result.exit, result.steps, result.repairs
            row.tokens = int((result.tokens or {}).get("total", 0) or 0)
            row.touched = list(result.touched or [])
            row.detail = str((result.verdict or {}).get("failures") or "")[:600]
            row.reasons = _grade(task, result, bus.all(), root)
    except Exception as exc:  # noqa: BLE001 -- el eval mide el arnes, tambien sus caidas
        row.reasons = ["el arnes lanzo %s: %s" % (type(exc).__name__, exc)]
    row.ok = not row.reasons
    row.seconds = time.time() - started
    return row


def run(names=None, model=None, tasks=None):
    """Corre las tareas pedidas. Devuelve el agregado y las filas, con lo que se debe declarar."""
    chosen, missing = selected(names)
    if tasks is not None:
        chosen = list(tasks)
    rows = [run_task(task, model=model) for task in chosen]
    passed = len([row for row in rows if row.ok])
    return {"suite": "core", "model": str(model or "guionizado"), "passed": passed,
            "total": len(rows), "ok": bool(rows) and passed == len(rows),
            "missing": missing, "rows": [row.as_dict() for row in rows]}


def render_markdown(payload):
    """La tabla que se pega en un documento o en un PR. Sin adjetivos: numeros y motivos."""
    lines = ["### Eval · %s" % payload["model"], "",
             "| tarea | resultado | exit | pasos | reparaciones | tokens |",
             "|---|---|---|---|---|---|"]
    for row in payload["rows"]:
        lines.append("| `%s` | %s | %s/%s | %d | %d | %s |"
                     % (row["id"], "OK" if row["ok"] else "FAIL", row["exit"],
                        row["expect_exit"], row["steps"], row["repairs"],
                        "{:,}".format(row["tokens"]).replace(",", ".")))
    lines.append("")
    lines.append("**%d/%d tareas resueltas.**" % (payload["passed"], payload["total"]))
    failed = [row for row in payload["rows"] if not row["ok"]]
    for row in failed:
        lines.append("- `%s`: %s" % (row["id"], "; ".join(row["reasons"])))
    return "\n".join(lines)
