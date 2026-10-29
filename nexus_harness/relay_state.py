"""Lo que sobrevive a una sesion: el estado verificado en disco y las salidas podadas.

Dos piezas, y las dos existen por el mismo motivo: un relevo que depende de la memoria del modelo no
es un relevo, es una apuesta.

* **`prune_tool_outputs`** es el nivel 1 del presupuesto (55 %). Las salidas viejas de `read_file`,
  `search_files` y `terminal` se sustituyen por una referencia `(path, lineas, sha256)`. El modelo
  puede releer el fichero si lo necesita, pero el transcript deja de arrastrar kilobytes que ya nadie
  mira. La poda es determinista: mismo contenido, mismo sha, mismos bytes.
* **`RelayState`** es el nivel 2 (70 %). Antes de que la sesion se archive se escribe
  `.nexus/RELAY_STATE.json` con el objetivo, los hitos CERRADOS con su commit, los ficheros tocados,
  el ultimo veredicto del gate y el siguiente paso exacto. El prompt de la sesion hija se sintetiza de
  ese fichero, no de un resumen que alguien escribio de memoria.

`.nexus/RELAY_STATE.json` es un fichero COMPARTIDO con `nexus.hive.relay` (que guarda ahi `phases`,
`checkpoints` y `queue`). Este modulo posee solo la clave `harness` y reescribe el fichero releyendolo
antes: pisar las fases del protocolo con una copia en memoria las borraba (medido: tres cerradas
volvian a una), y un relevo que borra la evidencia del anterior no es un relevo.

El estado se escribe con reemplazo atomico (`.tmp` + `replace`): un relevo a medias no puede dejar el
unico fichero del que depende la sesion siguiente truncado.
"""
import hashlib
import json
import time
from pathlib import Path

from .context.context_pruner import MARKER as PRUNED_MARK, prune
from .platform.digest import sha256_text, utc_now  # noqa: E402

PROTOCOL = "nexus.harness.relay-state/1"
STATE_REL = Path(".nexus") / "RELAY_STATE.json"
PRUNED_MARK = "[salida podada]"
DEFAULT_KEEP_CHARS = 600
OWN_KEY = "harness"




def prune_tool_outputs(messages, keep_chars=DEFAULT_KEEP_CHARS, keep_last=2):
    """Poda las salidas de herramientas grandes. Delega en `context_pruner` (una sola implementacion).

    Se conserva esta puerta porque el relevo la usa con sus propios argumentos (`keep_chars`,
    `keep_last`), y devuelve `(podadas, referencias)` como siempre. La logica de que es un "paso" y de
    que no se toca vive en `context_pruner.prune`, que ademas mide los bytes podados.
    """
    report = prune(messages, keep_last_steps=keep_last, min_chars=keep_chars)
    return report.pruned, list(report.receipts)


def tool_calls_seen(messages):
    """Las herramientas usadas, con su numero: lo que la sesion hija necesita saber que ya se probo."""
    counts = {}
    for message in messages:
        for call in getattr(message, "tool_calls", None) or ():
            counts[call.name] = counts.get(call.name, 0) + 1
    return counts


class RelayState:
    """El estado del relevo, bajo la clave `harness` del fichero que ya usa el protocolo."""

    def __init__(self, root, file_data=None):
        self.root = Path(root)
        self.data = dict(file_data or {})
        own = self.data.get(OWN_KEY)
        self.own = dict(own) if isinstance(own, dict) else {}
        self.own.setdefault("protocol", PROTOCOL)
        self.own.setdefault("goal", "")
        self.own.setdefault("milestones", [])
        self.own.setdefault("files", [])
        self.own.setdefault("last_gate", {})
        self.own.setdefault("next_step", "")
        self.own.setdefault("sessions", [])
        self.own.setdefault("created_at", utc_now())

    @property
    def path(self):
        return self.root / STATE_REL

    # -- escritura -------------------------------------------------------------------------------
    def milestone(self, title, commit="", ok=True, evidence=""):
        self.own["milestones"].append({"title": str(title)[:200], "commit": str(commit or ""),
                                       "ok": bool(ok), "evidence": str(evidence)[:300],
                                       "at": utc_now()})
        self.own["milestones"] = self.own["milestones"][-60:]
        return self

    def gate(self, exit_code, summary="", judge=""):
        self.own["last_gate"] = {"exit": int(exit_code or 0), "summary": str(summary)[:600],
                                 "judge": str(judge)[:600], "at": utc_now()}
        return self

    def touched(self, files):
        current = {str(item) for item in self.own["files"]}
        current.update(str(item) for item in files or () if str(item or "").strip())
        self.own["files"] = sorted(current)[:80]
        return self

    def next(self, step):
        self.own["next_step"] = str(step or "")[:400]
        return self

    def session(self, from_id, to_id, reason=""):
        self.own["sessions"].append({"from": str(from_id), "to": str(to_id),
                                     "reason": str(reason), "at": utc_now()})
        self.own["sessions"] = self.own["sessions"][-20:]
        self.own["updated_at"] = utc_now()
        return self

    def save(self):
        """Relee el fichero y solo pisa `harness`: lo que el protocolo cerro se queda como esta."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        merged = {}
        try:
            disk = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(disk, dict):
                merged = disk
        except (OSError, ValueError):
            merged = {}
        merged[OWN_KEY] = self.own
        self.data = merged
        temporary = self.path.with_name(".RELAY_STATE.json.tmp")
        temporary.write_text(json.dumps(merged, indent=2, sort_keys=True, ensure_ascii=False),
                             encoding="utf-8")
        temporary.replace(self.path)
        return self

    # -- lectura ---------------------------------------------------------------------------------
    @classmethod
    def load(cls, root):
        path = Path(root) / STATE_REL
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return cls(root, data if isinstance(data, dict) else {})

    @property
    def closed(self):
        return [item for item in self.own["milestones"] if item.get("ok")]

    @property
    def goal(self):
        return self.own.get("goal", "")

    def prompt(self):
        """El prompt auto-contenido que arranca la sesion hija. Determinista: solo lee el estado."""
        gate = self.own.get("last_gate") or {}
        lines = ["# Relevo de sesion", "",
                 "Objetivo original: %s" % (self.own.get("goal") or "(sin objetivo declarado)"), ""]
        sessions = self.own.get("sessions") or []
        if sessions:
            last = sessions[-1]
            lines += ["Sesion anterior: %s -> %s (motivo: %s)" % (
                last.get("from"), last.get("to"), last.get("reason") or "presupuesto"), ""]
        lines.append("## Hitos cerrados y verificados")
        if self.closed:
            for item in self.closed[-20:]:
                suffix = (" · commit `%s`" % item["commit"]) if item.get("commit") else ""
                lines.append("- %s%s" % (item.get("title"), suffix))
        else:
            lines.append("- (ninguno todavia: la sesion anterior no cerro hitos con evidencia)")
        lines += ["", "## Ficheros tocados"]
        lines.append(", ".join(self.own.get("files") or []) or "(ninguno)")
        lines += ["", "## Ultimo veredicto del gate"]
        lines.append("exit %s · %s" % (gate.get("exit", "sin medir"),
                                       gate.get("summary") or "sin salida"))
        if gate.get("judge"):
            lines.append("juez: %s" % gate["judge"])
        lines += ["", "## Siguiente paso exacto", self.own.get("next_step") or
                  "Ejecuta el gate y continua desde el estado del repositorio.", "",
                  "No repitas hitos ya cerrados. Verifica con el comando real antes de declarar nada."]
        return "\n".join(lines) + "\n"

    def as_dict(self):
        return {"path": str(self.path), "exists": self.path.is_file(),
                "milestones": len(self.own["milestones"]), "closed": len(self.closed),
                "files": len(self.own["files"]), "next_step": self.own.get("next_step", ""),
                "gate": self.own.get("last_gate") or {}}


# -- CLI de comprobacion -------------------------------------------------------------------------
def selftest():
    """La poda y el estado, medidos con un transcript de verdad en un directorio temporal."""
    import tempfile

    from .core.message import Message, ToolCall

    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    call = ToolCall(id="c1", name="read_file", arguments={"path": "a.py"},
                    raw_arguments='{"path": "a.py"}')
    messages = [Message(role="assistant", content="", tool_calls=[call]),
                Message(role="tool", content="x" * 5000, tool_call_id="c1", name="read_file")]
    pruned, refs = prune_tool_outputs(messages, keep_last=0)
    check("una salida grande se poda", pruned, 1)
    check("la referencia lleva el sha", "sha256:" in refs[0], True)
    check("la referencia nombra el fichero", "a.py" in refs[0], True)
    check("el sha es estable", refs[0], prune_tool_outputs(
        [Message(role="assistant", content="", tool_calls=[call]),
         Message(role="tool", content="x" * 5000, tool_call_id="c1", name="read_file")],
        keep_last=0)[1][0])
    check("la ultima salida se respeta", prune_tool_outputs(messages, keep_last=1)[0], 0)
    check("dos pasadas no podan dos veces", prune_tool_outputs(messages, keep_last=0)[0], 0)

    with tempfile.TemporaryDirectory(prefix="relay-state-") as workspace:
        # El protocolo ya dejo su plan en el fichero: guardar el relevo no puede borrarlo.
        shared = Path(workspace) / STATE_REL
        shared.parent.mkdir(parents=True)
        shared.write_text(json.dumps({"phases": [{"id": "p1", "status": "done"}],
                                      "queue": ["a"]}), encoding="utf-8")
        state = RelayState.load(workspace)
        state.milestone("modulo escrito", commit="abc1234").gate(0, "suites=1 failures=0")
        state.touched(["nexus_harness/a.py"]).next("ejecutar verify")
        state.session("session_01", "session_02").save()
        file_data = json.loads(shared.read_text(encoding="utf-8"))
        check("las fases del protocolo sobreviven", file_data["phases"][0]["status"], "done")
        check("la cola del protocolo sobrevive", file_data["queue"], ["a"])
        loaded = RelayState.load(workspace)
        check("el hito cerrado sobrevive", len(loaded.closed), 1)
        check("el commit viaja", loaded.closed[0]["commit"], "abc1234")
        check("el prompt cita el commit", "abc1234" in loaded.prompt(), True)
        check("el prompt cita el siguiente paso", "ejecutar verify" in loaded.prompt(), True)
        check("el relevo queda registrado", loaded.own["sessions"][-1]["to"], "session_02")
        check("no queda temporal", (Path(workspace) / ".nexus" / ".RELAY_STATE.json.tmp").exists(),
              False)
        loaded.own["goal"] = "dejar el gate verde"
        loaded.save()
        check("el objetivo se guarda", RelayState.load(workspace).goal, "dejar el gate verde")
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("relay_state: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
