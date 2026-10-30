"""Hooks: el motor deja de ser un producto cerrado y pasa a tener puntos de extensión de verdad.

Un hook es un **programa del usuario** que el motor llama en un momento concreto, con un contrato que no
depende del lenguaje en que esté escrito: JSON por la entrada, un mensaje por la salida, y un código de
salida que significa lo mismo en todos los puntos.

    [[hook]]
    at = "pre_verify"                        # before_turn | after_tool | before_commit | pre_verify
    command = "python tools/no_todo.py"      # lo que se ejecuta, con el cwd del proyecto

**Contrato de salida** (el mismo que el gate usa para todo lo demás, para no inventar vocabulario):

    0   pasó: el motor sigue
    10  rojo: el motor se para (el gate sale rojo, el turno se aborta, el commit no se hace)
    20  no se pudo medir: también para (fail-closed). Un hook roto no es un hook que aprueba
    30  declarado no verificable: se anota y NO se para (el hook dice "esto no aplica aquí")

**Entrada**: un JSON con `point`, `project` y `payload` (lo que ese punto sepa). La ÚLTIMA línea no vacía
de la salida es el mensaje que se enseña; lo demás se ignora, así un hook puede loguear a su gusto.

**Fail-closed, sin excepciones:** si el fichero de configuración existe y no se puede leer, o declara un
punto que no existe, o un comando vacío, el motor **no** se queda sin hooks en silencio: cada punto
devuelve 20 con el motivo. Un motor que ignora su configuración rota es peor que uno que no la tiene.
"""
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

CONFIG_NAME = "nexus_harness.toml"
POINTS = ("before_turn", "after_tool", "before_commit", "pre_verify")

EXIT_OK = 0
EXIT_BLOCK = 10
EXIT_UNMEASURED = 20
EXIT_NOT_APPLICABLE = 30

DEFAULT_TIMEOUT = 60


@dataclass
class HookResult:
    """Lo que un hook contestó. `blocking` se decide por el código, no por el punto."""
    name: str
    point: str
    code: int
    message: str = ""

    @property
    def ok(self):
        return self.code in (EXIT_OK, EXIT_NOT_APPLICABLE)

    @property
    def blocks(self):
        return not self.ok

    @property
    def verdict(self):
        return {EXIT_OK: "ok", EXIT_BLOCK: "rojo", EXIT_UNMEASURED: "no verificable",
                EXIT_NOT_APPLICABLE: "no aplica"}.get(self.code, "desconocido(%d)" % self.code)

    def as_dict(self):
        return {"name": self.name, "point": self.point, "code": self.code,
                "verdict": self.verdict, "message": self.message}


@dataclass
class Hook:
    name: str
    point: str
    command: str


class Hooks:
    """Los hooks declarados por un proyecto, y la forma de ejecutar los de un punto."""

    def __init__(self, specs=(), error="", timeout=DEFAULT_TIMEOUT):
        self.specs = list(specs)
        self.error = error
        self.timeout = timeout

    # -- carga --------------------------------------------------------------------------------
    @classmethod
    def load(cls, root, timeout=DEFAULT_TIMEOUT):
        path = Path(root) / CONFIG_NAME
        if not path.is_file():
            return cls((), "", timeout)  # inerte: no hay fichero, no hay hooks, y eso no es un fallo
        try:
            import tomllib
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 -- un toml roto es un fallo de configuración, se reporta
            return cls((), "%s no se pudo leer: %s: %s" % (CONFIG_NAME, type(exc).__name__, exc), timeout)
        rows = data.get("hook") or []
        if isinstance(rows, dict):
            rows = [rows]
        specs, problems = [], []
        for index, row in enumerate(rows):
            point = str(row.get("at") or "").strip()
            command = str(row.get("command") or "").strip()
            name = str(row.get("name") or "hook%d" % (index + 1)).strip()
            if point not in POINTS:
                problems.append("%s: `at = %r` no es un punto (%s)" % (name, point, ", ".join(POINTS)))
                continue
            if not command:
                problems.append("%s: sin `command`" % name)
                continue
            specs.append(Hook(name, point, command))
        return cls(specs, "; ".join(problems), timeout)

    # -- consulta -----------------------------------------------------------------------------
    def empty(self):
        return not self.specs and not self.error

    def names(self, point):
        return [spec.name for spec in self.specs if spec.point == point]

    def at(self, point, payload=None, cwd=None):
        """Ejecuta los hooks de `point`. Nunca lanza: un hook que revienta es un 20, no una excepción."""
        if self.error:
            # Config declarada y rota: fail-closed en TODOS los puntos, con el mismo motivo.
            return [HookResult("config", point, EXIT_UNMEASURED, self.error)]
        results = []
        for spec in self.specs:
            if spec.point != point:
                continue
            results.append(self._run(spec, payload or {}, cwd))
        return results

    def _run(self, spec, payload, cwd):
        # `shell=True` con un comando que viene del `nexus_harness.toml` DEL PROPIO PROYECTO: es el mismo
        # modelo de confianza que el `test_command` que el gate ya ejecuta, y el que tienen Make, npm
        # scripts o pre-commit. El texto no llega de una petición: lo escribe quien declara el hook en su
        # rama. Escaparlo obligaría a inventar un lenguaje de plantillas para ganar nada.
        body = json.dumps({"point": spec.point, "project": str(cwd or ""), "payload": payload},
                          ensure_ascii=False)
        flags = 0x08000000 if os.name == "nt" else 0
        try:
            done = subprocess.run(spec.command, shell=True, input=body, cwd=cwd, timeout=self.timeout,
                                  capture_output=True, text=True, errors="replace",
                                  creationflags=flags)
        except subprocess.TimeoutExpired:
            return HookResult(spec.name, spec.point, EXIT_UNMEASURED,
                              "timeout tras %ss: no se pudo medir" % self.timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            return HookResult(spec.name, spec.point, EXIT_UNMEASURED,
                              "no se pudo ejecutar: %s: %s" % (type(exc).__name__, exc))
        lines = [row.strip() for row in (done.stdout or "").splitlines() if row.strip()]
        message = lines[-1][:400] if lines else ""
        code = done.returncode
        if code not in (EXIT_OK, EXIT_BLOCK, EXIT_UNMEASURED, EXIT_NOT_APPLICABLE):
            # Un código que el contrato no define no puede leerse como aprobado ni como rojo: es un
            # hook roto, y el motor lo trata como "no se pudo medir".
            return HookResult(spec.name, spec.point, EXIT_UNMEASURED,
                              "código %d fuera del contrato (0/10/20/30): %s" % (code, message))
        return HookResult(spec.name, spec.point, code, message)


def blocked(results):
    """El primer resultado que para el motor, o None. Se usa para decidir en una línea."""
    for result in results:
        if result.blocks:
            return result
    return None
