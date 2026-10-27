"""La reparacion del Obrero, dentro de un worktree: o vuelve verde y se promueve, o no vuelve.

`triad_loop` esta en su techo de 400 lineas, asi que la reparacion aislada vive aqui y el bucle solo
la llama. El contrato es el de `worktree_sandbox.Sandbox.attempt`, con una diferencia: el gate que
decide es el del proyecto (`triad.gate`), no un comando adivinado, porque es el mismo juez que
decidira en el arbol principal. Un sandbox que pasa un gate distinto al real no prueba nada.

Se activa con `config.worktree_repairs = True` (y solo si la raiz es un repositorio git). Sin esa
bandera el comportamiento es el de siempre: reparar en el sitio. Un arnes que cambia de estrategia de
escritura sin que se lo pidan es un arnes que rompe flujos que ya funcionaban.
"""
from pathlib import Path

from .compaction import estimate
from .message import Message
from .worktree_sandbox import Sandbox, _run


def is_git_repo(root):
    """`git rev-parse --is-inside-work-tree` de verdad, no la existencia de un `.git` a mano."""
    code, output = _run(["git", "rev-parse", "--is-inside-work-tree"], root)
    return code == 0 and output.strip() == "true"


def isolated_repair(triad, messages, max_steps):
    """Corre el Obrero en un worktree y devuelve `(text, steps)`.

    Si el gate del proyecto sale verde alli, los ficheros se copian al arbol principal y se re-mide
    alli (un promote que no se vuelve a medir es una promesa, no una prueba). Si sale rojo o el
    Obrero lanza, el worktree se descarta y el arbol principal no se toca: el bucle recibira el rojo
    de verdad y decidira con el.
    """
    root = Path(getattr(triad.config, "default_root", triad.registry.root))
    if not is_git_repo(root):
        triad._emit("repair.sandbox", "sin git: se repara en el arbol principal", ok=False)
        return triad._work(messages, max_steps)

    sandbox = Sandbox(root, name="repair")
    made = sandbox.create()
    if not made["ok"]:
        triad._emit("repair.sandbox", "no se pudo crear el worktree: %s" % made["reason"],
                    ok=False)
        return triad._work(messages, max_steps)

    original = (triad.registry.root, triad.gate.root)
    triad._emit("repair.sandbox", str(sandbox.path), ok=True, branch=sandbox.branch)
    steps = 0
    # Motor 4: el Obrero trabaja sobre una COPIA del transcript. Sus lecturas, sus errores y sus
    # intentos intermedios se quedan aqui; al hilo principal solo vuelve un recibo de una linea. Es la
    # diferencia entre "reparar sin ensuciar la ventana" y "reparar en el mismo hilo y pagar 40k tokens
    # de logs de error que ya no sirven para nada".
    shadow = list(messages)
    before_tokens = estimate(shadow)[1]
    try:
        triad.registry.root = sandbox.path
        triad.gate.root = sandbox.path
        text, steps = triad._work(shadow, max_steps)
        kept_out = max(0, estimate(shadow)[1] - before_tokens)
        if kept_out:
            triad.savings.observe_isolation(kept_out)
            triad._emit("repair.isolated", "la reparacion no entro en la ventana principal",
                        tokens_kept_out=kept_out, steps=steps)
        touched = sandbox.changed()
        verdict = triad.gate.run(sorted(set(list(triad.touched) + touched)))
        if not verdict.ok:
            triad._emit("repair.sandbox.red", "gate rojo dentro del worktree",
                        exit=verdict.exit, failures=verdict.failures[:600])
            return text, steps
        triad.registry.root, triad.gate.root = original
        _close_shadow(messages, shadow, text)
        promoted = sandbox.promote(touched)
        if not promoted["ok"]:
            triad._emit("repair.sandbox.red", promoted["reason"], ok=False)
            return text, steps
        again = triad.gate.run(sorted(set(list(triad.touched) + promoted["copied"])))
        triad.touched.update(promoted["copied"])
        triad._emit("repair.sandbox.promoted", "%d ficheros" % len(promoted["copied"]),
                    files=promoted["copied"], exit=again.exit, ok=again.ok)
        return text, steps
    except Exception as exc:  # noqa: BLE001 -- un fallo del sandbox no puede tumbar el run
        triad._emit("repair.sandbox.error", "%s: %s" % (type(exc).__name__, exc), ok=False)
        _close_shadow(messages, shadow, "")   # el hilo principal se queda con el recibo, no con el fallo
        return "", steps
    finally:
        triad.registry.root, triad.gate.root = original
        if sandbox.path.exists():
            sandbox.discard()


def _close_shadow(messages, shadow, text):
    """Deja UNA linea en el hilo principal con lo que la reparacion hizo. Nada mas vuelve de alli."""
    if len(shadow) <= len(messages) + 1:
        return
    detail = " ".join(str(text or "").split())[:300] or "sin resumen del Obrero"
    messages.append(Message(role="user", content="[reparacion aislada en worktree] %s" % detail))


def selftest():
    import tempfile

    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    with tempfile.TemporaryDirectory(prefix="repair-guard-") as workspace:
        root = Path(workspace)
        _run(["git", "init", "-q", "-b", "main"], root)
        (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / ".gitignore").write_text(".nexus/\n", encoding="utf-8")
        _run(["git", "add", "-A"], root)
        _run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"], root)
        check("un repo git se detecta", is_git_repo(root), True)
        check("una carpeta suelta no", is_git_repo(root / "nada"), False)
    return problems
