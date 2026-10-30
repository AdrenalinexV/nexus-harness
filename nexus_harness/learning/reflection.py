"""Reflexion: convertir un turno en una regla, y solo con lo que el turno OBSERVO.

El arnes tenia la forja de skills y el detector de patrones, pero nadie los llamaba: aprender dependia
de que el modelo decidiera usar una herramienta. Eso no es un reflejo, es una sugerencia.

Aqui hay dos reflejos, y los dos son deterministas (ningun modelo decide que se aprende):

* **Fallo repetido** -> skill. Tres fallos del MISMO patron (herramienta/check + extension + palabras
  del error) escriben una `SKILL.md` con las observaciones del turno: el comando que fallo, los
  ficheros y el motivo. Se apoya en `skill_forge`, que ya registra procedencia y sha256.
* **Exito tras reparar** -> leccion. Un turno que empezo rojo y acabo verde deja una linea con el
  comando que lo probo; el planificador del bucle autonomo las lee antes de decidir el siguiente paso.

Lo que NO se hace: inventar una regla sin `exit` observado, o escribir memoria en cada turno verde. Una
memoria que crece sola deja de ser memoria y pasa a ser ruido con factura en cada prompt.
"""
import json
import re
import time
from pathlib import Path

from nexus_harness.tools import skill_forge
from nexus_harness.core.outcomes import record_skills
from nexus_harness.tools.skill_forge import ForgeTrigger
from nexus_harness.context.skill_router import EXTENSIONS
from nexus_harness.verify import oracle

COUNTERS_REL = Path(".nexus") / "harness" / "forge_trigger.json"
LESSONS_REL = Path(".nexus") / "harness" / "lessons.jsonl"
MAX_LESSONS = 500
HEAD_WORDS = 6


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _head(text, words=HEAD_WORDS):
    return " ".join(re.findall(r"[A-Za-z0-9_.:/-]+", str(text or ""))[:words])[:160]


def _language(files):
    """El lenguaje dominante de los ficheros tocados, para nombrar la skill."""
    for name in files or ():
        suffix = Path(str(name)).suffix.lower()
        if suffix in EXTENSIONS:
            return EXTENSIONS[suffix]
    return "proyecto"


class Reflection:
    """Los dos reflejos, con sus contadores en disco para que sobrevivan al turno."""

    def __init__(self, root, threshold=3, outcomes=None):
        self.root = Path(root)
        self.trigger = ForgeTrigger(threshold)
        self.outcomes = outcomes
        self._load()

    # -- contadores ----------------------------------------------------------------------------
    def _path(self, rel):
        return self.root / rel

    def _load(self):
        try:
            data = json.loads(self._path(COUNTERS_REL).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        self.trigger.counts = {str(k): int(v) for k, v in (data.get("counts") or {}).items()}
        self.trigger.asked = {str(k): str(v) for k, v in (data.get("asked") or {}).items()}

    def _save(self):
        path = self._path(COUNTERS_REL)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"counts": self.trigger.counts, "asked": self.trigger.asked},
                                       indent=1, sort_keys=True), encoding="utf-8")
            return True
        except OSError:
            return False

    # -- reflejo de fallo ----------------------------------------------------------------------
    def observe_failure(self, check, detail, files, command=""):
        """Cuenta un fallo. Al tercero del mismo patron, forja la skill que faltaba."""
        files = list(files or ())
        hit = self.trigger.hit(str(check or "gate"), files[0] if files else "", detail or "")
        self._save()
        row = {"fires": False, "count": hit["count"], "signature": hit["signature"]}
        if not hit["fires"]:
            return row
        topic = "%s %s" % (_language(files), check or "gate")
        observations = ["El gate fallo en `%s`: %s" % (check, _head(detail, 12))]
        if command:
            observations.append("Comando de verificacion: `%s` debe salir 0." % command)
        if files:
            observations.append("Ficheros implicados: %s" % ", ".join(files[:6]))
        forged = skill_forge.forge(self.root, topic, reason="tres fallos del mismo patron",
                                   observations=observations)
        row.update({"fires": True, "forged": forged.get("created", False),
                    "skill": forged.get("name", ""), "path": forged.get("path", "")})
        return row

    # -- reflejo de exito ----------------------------------------------------------------------
    def lesson(self, checks, files, repairs, command="", judgement="", tag=""):
        """Una regla accionable de un turno que empezo rojo y acabo verde. Devuelve la fila."""
        row = {"at": _now(), "project": self.root.name, "repairs": int(repairs or 0),
               "judgement": str(judgement or ""), "tag": str(tag or ""),
               "checks": [str(one.get("name")) for one in checks or () if not one.get("ok")],
               "files": list(files or ())[:8], "command": str(command or ""),
               "rule": self._rule(checks, files, repairs, command)}
        path = self._path(LESSONS_REL)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        except OSError:
            return {}
        return row

    def _rule(self, checks, files, repairs, command):
        """El texto de la leccion: que se rompio, cuanto costo, y con que se prueba."""
        broken = [str(one.get("name")) for one in checks or () if not one.get("ok")]
        target = ", ".join(list(files or ())[:3]) or "el proyecto"
        proof = ("comprueba con `%s`" % command) if command else "declara un comando de prueba"
        if broken:
            return ("En %s, tocar %s rompe %s: %s antes de cerrar (costo %s reparacion(es))."
                    % (self.root.name, target, ", ".join(broken), proof, repairs))
        return ("En %s, tras reparar %s, %s antes de cerrar." % (self.root.name, target, proof))

    # -- el turno ------------------------------------------------------------------------------
    def after_turn(self, exit, checks=(), files=(), repairs=0, judgement="", command="",
                   tag=""):
        """El reflejo completo de un turno. Nunca lanza: aprender no puede tumbar el trabajo."""
        try:
            return self._after_turn(exit, checks, files, repairs, judgement, command, tag)
        except Exception as exc:  # noqa: BLE001 -- un reflejo roto se declara, no se propaga
            return {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}

    def _after_turn(self, exit, checks, files, repairs, judgement, command, tag):
        files = list(files or ())
        if exit is None:
            return {"ok": False, "reason": "sin exit observado: no se apunta nada"}
        if int(exit) != 0:
            broken = [one for one in checks or () if not one.get("ok")]
            results = [self.observe_failure(one.get("name"), one.get("detail"), files, command)
                       for one in broken] or [self.observe_failure("gate", "exit %s" % exit,
                                                                   files, command)]
            return {"ok": True, "failures": len(results),
                    "forged": [row for row in results if row.get("fires")]}
        if int(repairs or 0) <= 0:
            return {"ok": True, "reason": "verde a la primera: no hay regla que sacar"}
        return {"ok": True, "lesson": self.lesson(checks, files, repairs, command, judgement, tag)}


def command_for(config, root=None):
    """El comando con el que se prueba este proyecto: declarado o descubierto. Vacio si no hay."""
    declared = str(getattr(config, "test_command", None) or "").strip()
    if declared:
        return declared
    found = oracle.detect(Path(root) if root else Path(getattr(config, "default_root", ".")))
    return str(found.get("command") or "")


def lessons(root, limit=5):
    """Las ultimas `limit` lecciones del proyecto, en orden cronologico."""
    try:
        lines = (Path(root) / LESSONS_REL).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines[-MAX_LESSONS:]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows[-int(limit):]


def lessons_block(root, limit=5):
    """El bloque que lee el planificador: reglas medidas, sin adjetivos."""
    rows = lessons(root, limit)
    if not rows:
        return ""
    lines = ["## Lecciones medidas de este proyecto"]
    for row in rows:
        lines.append("- %s" % (row.get("rule") or ""))
    return "\n".join(lines)


def learn(config, payload, tag="", skills=None, goal=""):
    """El reflejo de un turno ya cerrado, con la forma que devuelven Chat y Triad.

    `payload` es el diccionario del turno: `exit`, `verdict.checks`, `touched`, `repairs` y
    `judgement.verdict`. Un turno sin gate no tiene checks y no deja regla: no se inventa evidencia.
    """
    root = Path(getattr(config, "default_root", ".") or ".")
    verdict = payload.get("verdict") or {}
    judgement = payload.get("judgement") or {}
    from nexus_harness.tools.recall import remember_turn

    exit_code = payload.get("exit")
    if exit_code is not None:
        remember_turn(root, goal or payload.get("goal") or "", exit_code,
                      payload.get("touched") or (), payload.get("repairs") or 0,
                      project=root.name)
    record_skills(skills, root, exit_code, judgement.get("verdict", ""), tag)
    return Reflection(root).after_turn(
        payload.get("exit"), checks=verdict.get("checks") or (),
        files=payload.get("touched") or (), repairs=payload.get("repairs") or 0,
        judgement=judgement.get("verdict", ""), command=command_for(config, root), tag=tag)
