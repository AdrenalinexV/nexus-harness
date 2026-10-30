"""La jaula: lo que este SO contiene de verdad, y la negativa cuando no hay nada que contenga.

La brecha D decia `policy.classify('rm -rf build','unrestricted') -> allowed=True`: una lista de
palabras prohibidas haciendo de sandbox. Aqui se mide el porton que la cierra:

* sin jaula de **sistema de ficheros**, `unrestricted` se niega con el motivo escrito;
* con jaula, el operador vuelve a tener su permiso (y el SO lo sostiene);
* la firma `NEXUS_UNSANDBOXED=1` tambien lo levanta -- es una decision, no un default;
* la matriz de 3 modos x 3 jaulas (una por SO) da el veredicto esperado en las nueve celdas;
* el Job Object de Windows se mide de verdad: se lleva el proceso, y con tope de memoria el hijo
  muere al pedir mas de lo que tiene.
"""
import os
import subprocess
import sys
import time

from ..platform import policy, sandbox


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


NO_CAGE = sandbox.Cage("none", "ninguno", reason="prueba")
JOB = sandbox.Cage("job", "windows", filesystem=False, processes=True, memory=True)
BWRAP = sandbox.Cage("bwrap", "linux", filesystem=True, processes=True)


def test_the_module_selftest(failures):
    for problem in sandbox.selftest():
        failures.append("sandbox.selftest: %s" % problem)


def test_unrestricted_without_a_cage_is_refused(failures):
    verdict = policy.classify("rm -rf build", "unrestricted")
    check("sin jaula, unrestricted niega rm -rf", verdict.allowed, False, failures)
    check("y la regla se llama 'sandbox'", verdict.level, "sandbox", failures)
    check("y el motivo nombra la falta", "jaula de sistema de ficheros" in verdict.reason, True,
          failures)
    check("y dice como asumirlo", "NEXUS_UNSANDBOXED=1" in policy.refusal(verdict), True, failures)


def test_a_filesystem_cage_gives_the_permission_back(failures):
    check("con bwrap, unrestricted permite rm -rf",
          policy.classify("rm -rf build", "unrestricted", cage=BWRAP).allowed, True, failures)
    check("un Job Object no basta: no aisla ficheros",
          policy.classify("rm -rf build", "unrestricted", cage=JOB).allowed, False, failures)
    check("la firma del operador si basta",
          policy.classify("rm -rf build", "unrestricted", cage=NO_CAGE,
                          allow_unsandboxed=True).allowed, True, failures)
    check("standard sigue negando aunque haya jaula",
          policy.classify("rm -rf build", "standard", cage=BWRAP).allowed, False, failures)
    check("y lo catastrofico no se levanta ni con jaula ni con firma",
          policy.classify("rm -rf /", "unrestricted", cage=BWRAP, allow_unsandboxed=True).allowed,
          False, failures)


def test_the_matrix_has_no_silent_cell(failures):
    """3 modos x 3 jaulas (una por SO). Cada celda con veredicto, y cada fila medida o con motivo."""
    expected = {
        ("read_only", "none"): False, ("read_only", "job"): False, ("read_only", "bwrap"): False,
        ("standard", "none"): False, ("standard", "job"): False, ("standard", "bwrap"): False,
        ("unrestricted", "none"): False, ("unrestricted", "job"): False,
        ("unrestricted", "bwrap"): True,
    }
    for mode in policy.MODES:
        for cage in (NO_CAGE, JOB, BWRAP):
            got = policy.classify("rm -rf build", mode, cage=cage).allowed
            check("%s sobre %s" % (mode, cage.kind), got, expected[(mode, cage.kind)], failures)
    rows = sandbox.matrix()
    check("la matriz tiene una fila por SO", [row["os"] for row in rows],
          ["windows", "linux", "darwin"], failures)
    check("cada fila esta medida o declara por que no",
          all(row.get("measured") or row.get("reason") for row in rows), True, failures)
    check("y solo la de esta maquina se mide",
          len([row for row in rows if row.get("measured")]), 1, failures)


def test_the_job_holds_what_it_says(failures):
    """En Windows se mide con procesos de verdad; en otro SO se declara que no hay Job."""
    guard = sandbox.Guard(memory_mb=256, max_processes=8)
    if os.name != "nt":
        check("fuera de Windows no hay Job, y se dice", bool(guard.reason), True, failures)
        return
    check("el Job se crea", guard.active, True, failures)
    process, guard = sandbox.spawn([sys.executable, "-c", "import time; time.sleep(30)"],
                                  memory_mb=256)
    check("el hijo entra en el Job", guard.active, True, failures)
    guard.close()
    try:
        process.wait(5)
        dead = True
    except subprocess.TimeoutExpired:
        dead = False
    check("cerrar el Job mata el arbol", dead, True, failures)
    hog = sandbox.run([sys.executable, "-c", "blob = bytearray(300 * 1024 * 1024)"],
                      memory_mb=64, timeout=30)
    check("con tope de memoria, el hijo muere al pedir 300 MB", hog.returncode != 0, True, failures)


def test_stop_does_not_leave_a_job_open(failures):
    """Un Job que no se cierra es un proceso que sobrevive al turno: `stop` tiene que cortarlo."""
    if os.name != "nt":
        check("sin Job no hay nada que cerrar", sandbox.Guard().active, False, failures)
        return
    guard = sandbox.Guard()
    process, guard = sandbox.spawn([sys.executable, "-c", "import time; time.sleep(30)"])
    started = time.time()
    guard.close()
    try:
        process.wait(5)
    except subprocess.TimeoutExpired:
        failures.append("el Job no mato el hijo en 5 s")
    check("el corte es inmediato, no espera al timeout", time.time() - started < 5, True, failures)


def run():
    failures = []
    test_the_module_selftest(failures)
    test_unrestricted_without_a_cage_is_refused(failures)
    test_a_filesystem_cage_gives_the_permission_back(failures)
    test_the_matrix_has_no_silent_cell(failures)
    test_the_job_holds_what_it_says(failures)
    test_stop_does_not_leave_a_job_open(failures)
    return failures
