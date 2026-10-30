"""El commit de un paso: uno, limpio, y sujeto a `before_commit` antes de tocar el repositorio.

Vivía dentro de `autonomy.py`, que llegó a 399 líneas. Sacarlo no es mudar código para esquivar la ley de
400: un commit es infraestructura — identidad local, `git commit` y el punto de extensión que una
organización usa para firmar o vetar — y no tiene nada que ver con planificar trabajo.
"""
import os
import subprocess

from . import hooks as hooks_mod


def commit(root, message):
    """Un commit limpio del paso, con identidad local para no depender de la configuración del usuario."""
    # `before_commit` corre ANTES de tocar el repo: un hook que devuelve 10/20 impide el commit y el
    # turno lo dice. Es el punto donde una organización mete su firma, su linter o su "esto no se sube".
    stop = hooks_mod.blocked(hooks_mod.Hooks.load(root).at("before_commit", {"message": message},
                                                          cwd=root))
    if stop is not None:
        return False, "hook %s (%s): %s" % (stop.name, stop.verdict, stop.message)
    flags = 0x08000000 if os.name == "nt" else 0
    try:
        done = subprocess.run(["git", "-C", str(root), "-c", "user.name=Nexus Harness",
                               "-c", "user.email=nexus@localhost", "commit", "-q", "-am", message],
                              capture_output=True, text=True, errors="replace", timeout=90,
                              creationflags=flags)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "%s: %s" % (type(exc).__name__, exc)
    if done.returncode != 0:
        return False, ((done.stdout or "") + (done.stderr or "")).strip()[:300]
    return True, ""
