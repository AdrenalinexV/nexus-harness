"""La politica zero-trust de comandos: lo que el arnes se niega a correr, y por que la negativa es una observacion.

Cinco propiedades, cada una con una falsificacion posible:

* lo **catastrofico** se niega en los tres modos -- incluido `unrestricted`, porque ese modo es un
  permiso para ser temerario, no para formatear un disco;
* lo **temerario** se niega en `read_only` y `standard` y solo pasa si el operador lo pide por su
  nombre (`unrestricted`), asi que la config se mide por su efecto y no por su texto;
* `read_only` **no escribe**: niega cualquier mutacion y sigue dejando leer;
* la negativa es una **observacion** (`ok=False`, empieza por `refused`) y **no ejecuta nada**: se
  decide antes de que exista un subproceso, y eso se comprueba con el arbol de verdad;
* el trabajo normal **no se bloquea**: `mkdir` pasa en `standard` y un `rm -rf` pasa en `unrestricted`.
"""
import os

from .fakes import TempProject
from ..platform import policy
from ..config import HarnessConfig
from ..tools.toolbox import shell_session
from ..tools import Registry


def check(name, got, expected, failures):
    if got != expected:
        failures.append("%s: %r, esperaba %r" % (name, got, expected))


CATASTROPHIC_SAMPLES = (
    ("rm -rf /", "borrar la raiz"),
    ("shutdown /s /t 0", "apagar la maquina"),
    ("format c:", "formatear una unidad"),
    (":(){ :|:& };:", "bomba fork"),
    ("dd if=/dev/zero of=/dev/sda", "escribir sobre un disco"),
)


def test_levels(failures):
    check("una lectura pasa en el modo por defecto", policy.classify("ls -la").allowed, True, failures)
    check("y el modo por defecto es standard", policy.classify("ls").mode, "standard", failures)
    for mode in policy.MODES:
        for command, what in CATASTROPHIC_SAMPLES:
            verdict = policy.classify(command, mode)
            check("%s se niega en %s" % (what, mode), verdict.allowed, False, failures)
    check("y la regla que lo para es 'catastrophic'",
          policy.classify("rm -rf /", "unrestricted").level, "catastrophic", failures)
    check("un --force se niega en standard",
          policy.classify("git push --force origin main").allowed, False, failures)
    check("y su regla es 'reckless'", policy.classify("git push --force origin main").level,
          "reckless", failures)
    check("un rm -rf se niega en standard", policy.classify("rm -rf build").allowed, False, failures)
    check("pero se permite cuando el operador lo pide",
          policy.classify("git push --force origin main", "unrestricted").allowed, True, failures)
    check("un borrado simple pasa en standard", policy.classify("rm build/old.log").allowed, True, failures)
    check("en read_only no se borra", policy.classify("rm build/old.log", "read_only").allowed,
          False, failures)
    check("ni se commitea", policy.classify("git commit -m x", "read_only").allowed, False, failures)
    check("ni se redirige", policy.classify("echo hola > out.txt", "read_only").allowed, False, failures)
    check("ni se instalan dependencias",
          policy.classify("pip install requests", "read_only").allowed, False, failures)
    check("pero se lee el repositorio", policy.classify("git status", "read_only").allowed, True, failures)
    check("una flecha no es una redireccion",
          policy.classify('echo "a -> b"', "read_only").allowed, True, failures)
    check("un modo inventado cae al de por defecto",
          policy.classify("git push --force x", "yolo").mode, "standard", failures)
    check("un comando vacio no pasa", policy.classify("   ").allowed, False, failures)
    check("la negativa dice como se levanta", "shell_policy" in policy.refusal(
        policy.classify("rm -rf /")), True, failures)


def test_config_decides_the_mode(failures, root):
    check("sin config, el modo es standard", policy.mode_of(None), "standard", failures)
    check("y una config sin el campo tambien", policy.mode_of(HarnessConfig()), "standard", failures)
    check("un modo ilegible en la config no es un permiso",
          policy.mode_of(HarnessConfig(shell_policy="root")), "standard", failures)
    try:
        shell_session.shell(root, "rm build/old.log", None, HarnessConfig(shell_policy="read_only"))
        refused = ""
    except ValueError as exc:
        refused = str(exc)
    check("read_only niega por la via de la config", "refused [read_only/mutating]" in refused,
          True, failures)
    session = shell_session.session_for(root)
    session.reset()
    try:
        session.run("git push --force origin main", background=True)
        refused_bg = ""
    except ValueError as exc:
        refused_bg = str(exc)
    check("y un comando en segundo plano se niega antes de nacer",
          "refused [standard/reckless]" in refused_bg, True, failures)


def test_the_normal_work_still_runs(failures, root):
    session = shell_session.session_for(root)
    session.reset()
    _text, meta = shell_session.shell(root, "mkdir probe_dir", None,
                                      HarnessConfig(shell_policy="standard"))
    check("mkdir pasa en standard", meta.get("exit"), 0, failures)
    check("y el directorio existe", os.path.isdir(str(root / "probe_dir")), True, failures)
    _text, meta = shell_session.shell(root, "rm -rf probe_dir", None,
                                      HarnessConfig(shell_policy="unrestricted"))
    check("rm -rf pasa en unrestricted", meta.get("exit"), 0, failures)
    check("y borra de verdad", os.path.exists(str(root / "probe_dir")), False, failures)


def test_refusal_is_an_observation(failures, root):
    registry = Registry(root)
    result = registry.call("shell", {"command": "touch pwned.txt && rm -rf /"})
    check("la herramienta no levanta: devuelve una observacion", result.ok, False, failures)
    check("que empieza por 'refused'", result.text.startswith("refused"), True, failures)
    check("nada se ejecuto antes de la negativa", os.path.exists(str(root / "pwned.txt")), False,
          failures)
    allowed = registry.call("shell", {"command": "echo hola"})
    check("una lectura sigue siendo una observacion ok", allowed.ok, True, failures)
    check("con su salida", "hola" in allowed.text, True, failures)


def run():
    failures = []
    with TempProject() as root:
        test_levels(failures)
        test_config_decides_the_mode(failures, root)
        test_the_normal_work_still_runs(failures, root)
        test_refusal_is_an_observation(failures, root)
    return failures
