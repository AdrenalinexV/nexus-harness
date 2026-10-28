"""El eval se examina a si mismo: si una tarea rota pasara, la tabla no valdria nada.

Lo que se mide:
* las siete tareas golden pasan con el modelo guionizado (y la negativa cierra en rojo, como debe);
* una tarea cuyo guion no hace nada FALLA, y el motivo nombra el exit;
* una tarea que exige un contenido que no esta FALLA, y lo dice;
* la tabla markdown se puede pegar y no oculta un fallo.
"""
from .. import evalgym
from ..eval_tasks import TASKS, Task, selected


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


def test_the_whole_suite_passes_deterministically(failures):
    payload = evalgym.run()
    check("corren todas", payload["total"], len(TASKS), failures)
    check("y pasan todas", payload["passed"], len(TASKS), failures)
    check("el agregado dice ok", payload["ok"], True, failures)
    failed = [(row["id"], row["reasons"]) for row in payload["rows"] if not row["ok"]]
    check("sin fallos escondidos", failed, [], failures)


def test_the_negative_task_really_ends_red(failures):
    payload = evalgym.run(names=["over-400-is-rejected"])
    row = payload["rows"][0]
    check("el fichero de 402 lineas se rechaza", row["exit"], 10, failures)
    check("y la tarea se considera cumplida", row["ok"], True, failures)


def test_an_idle_script_fails_the_task(failures):
    idle = Task(id="idle", goal="no hagas nada", files={"calc.py": "x = 1\n"},
                test='python -c "import sys; sys.exit(3)"', script=[])
    row = evalgym.run_task(idle)
    check("sin trabajo no hay verde", row.ok, False, failures)
    check("y el motivo es el exit", any("exit" in reason for reason in row.reasons), True, failures)


def test_a_missing_expected_content_fails(failures):
    lying = Task(id="lying", goal="di que esta hecho", files={"calc.py": "x = 1\n"},
                 test='python -c "print(1)"', script=[], contains={"calc.py": ["def mul"]})
    row = evalgym.run_task(lying)
    check("el contenido que falta se detecta", row.ok, False, failures)
    check("con el nombre del fichero", any("calc.py" in reason for reason in row.reasons), True,
          failures)


def test_the_table_is_readable_and_honest(failures):
    payload = evalgym.run(names=["fix-subtraction", "add-function"])
    table = evalgym.render_markdown(payload)
    check("nombra las tareas", table.count("`fix-subtraction`"), 1, failures)
    check("dice el total", "2/2 tareas resueltas" in table, True, failures)
    check("y no inventa fallos", "FAIL" in table, False, failures)


def test_a_script_only_task_is_declared_not_failed(failures):
    """Con un modelo real, una tarea que exige obedecer una orden destructiva se OMITE y se dice."""
    task = __import__("nexus_harness.eval_tasks", fromlist=["by_id"]).by_id("respect-policy")
    row = evalgym.run_task(task, model="lmstudio:modelo-que-no-existe")
    check("se omite", row.skipped, True, failures)
    check("sin contar como fallo", row.ok, True, failures)
    check("y se explica", "no medible" in " ".join(row.reasons), True, failures)


def test_repeats_report_pass_at_k_and_stability(failures):
    payload = evalgym.run(names=["fix-subtraction"], repeat=2)
    check("una tarea, dos intentos", (payload["total"], len(payload["rows"])), (1, 2), failures)
    check("pass@k cuenta la tarea", payload["passed"], 1, failures)
    check("y la estabilidad tambien", payload["stable"], 1, failures)


def test_selection_reports_unknown_ids(failures):
    chosen, missing = selected(["fix-subtraction", "no-existe"])
    check("elige la que existe", [task.id for task in chosen], ["fix-subtraction"], failures)
    check("y declara la que no", missing, ["no-existe"], failures)
    everything, none = selected(None)
    check("sin filtro corren todas", len(everything), len(TASKS), failures)
    check("y no falta ninguna", none, [], failures)


def run():
    failures = []
    test_the_whole_suite_passes_deterministically(failures)
    test_the_negative_task_really_ends_red(failures)
    test_an_idle_script_fails_the_task(failures)
    test_a_missing_expected_content_fails(failures)
    test_the_table_is_readable_and_honest(failures)
    test_a_script_only_task_is_declared_not_failed(failures)
    test_repeats_report_pass_at_k_and_stability(failures)
    test_selection_reports_unknown_ids(failures)
    return failures
