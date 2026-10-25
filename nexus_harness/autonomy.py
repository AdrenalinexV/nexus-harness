"""El bucle autonomo iterativo: coger el proyecto #1 de la cola y dejarlo terminado, o decir por que no.

El orden de un ciclo es el que hace que esto sea seguro, y no es negociable:

    backup -> leer spec y progreso -> planificar el siguiente paso -> ejecutar la triada
           -> gate verde: commit limpio + progreso  |  gate rojo: el Obrero repara; si sigue rojo, alto

* **El backup va primero.** Un bucle que edita sin red de seguridad es un bucle que algun dia se lleva
  la tarde de trabajo. Si el snapshot no se puede hacer, no se edita: se dice y se para.
* **El progreso se escribe DESPUES del verde.** Un paso marcado como hecho sin gate es una mentira con
  formato JSON.
* **Rojo no es "casi".** La triada ya intenta reparar `max_repairs` veces; si aun asi sale rojo, ese
  proyecto se queda como esta y se pasa al siguiente de la cola. Insistir sobre rojo es quemar tokens
  para producir el mismo hallazgo.
* **El plan es inyectable.** En produccion lo hace el Director con la spec delante; en las suites es
  una funcion de tres lineas, porque un bucle que solo se puede probar con un modelo encendido no se
  prueba nunca.

Todo lo que pasa se emite al bus con el prefijo `autonomy.`, que es lo que alimenta la barra de estado
en vivo de la esquina.
"""
import threading
import time
from pathlib import Path

from . import backup, ledger, projects

AUTONOMY_LOG = Path(".nexus") / "harness" / "autonomy.jsonl"

PLANNER_PROMPT = """Eres el Director de un harness de ingenieria autonomo. Tienes un proyecto, su spec
congelada y la lista de pasos YA hechos y verificados. Decide UNA cosa: el siguiente paso pendiente.

Responde SOLO con JSON, sin texto alrededor:
{"done": false, "step": "una frase imperativa, concreta, con el fichero que toca"}

Si todos los criterios de la spec ya estan cumplidos y verificados, responde {"done": true, "step": ""}.
No inventes criterios que la spec no pide. No propongas reescribir lo que ya esta verde."""


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_plan(text):
    """El JSON del Director, tolerante con las vallas de markdown. Sin JSON, el texto es el paso."""
    raw = str(text or "").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        import json
        try:
            data = json.loads(raw[start:end + 1])
        except ValueError:
            data = None
        if isinstance(data, dict):
            done = bool(data.get("done"))
            step = str(data.get("step") or data.get("next") or "").strip()
            return {"done": done, "step": step, "why": "plan del director"}
    line = next((line.strip() for line in raw.splitlines() if line.strip()), "")
    return {"done": False, "step": line, "why": "plan sin JSON: se usa la primera linea"}


def model_planner(router, config):
    """El planificador de verdad: el Director, con la spec y el progreso delante."""
    from .message import Message

    def plan(root, goal, progress):
        spec = projects.spec_of(root)
        done = [str(step.get("step") or "") for step in (progress or {}).get("steps") or []
                if step.get("ok")]
        prompt = ("PROYECTO: %s\nOBJETIVO: %s\nSPEC: %s (%d criterios)\nPASOS HECHOS:\n%s\n"
                  "PASOS FALLIDOS: %s"
                  % (Path(root).name, goal or spec.get("goal") or "(sin objetivo)",
                     spec.get("id") or spec.get("format") or "(sin spec)", spec.get("criteria", 0),
                     "\n".join("- " + step for step in done[-12:]) or "(ninguno)",
                     len([one for one in (progress or {}).get("steps") or [] if not one.get("ok")])))
        try:
            reply = router.role("director").chat(
                [Message(role="system", content=PLANNER_PROMPT),
                 Message(role="user", content=prompt)],
                temperature=0.1, max_tokens=min(int(getattr(config, "max_tokens", 4096) or 4096), 600))
        except Exception as exc:  # noqa: BLE001 -- el bucle informa del motivo, no se cae
            return {"done": False, "step": "", "why": "el Director no contesto: %s: %s"
                    % (type(exc).__name__, exc)}
        result = parse_plan(getattr(reply, "text", ""))
        result["model"] = getattr(reply, "model", "")
        return result

    return plan


def _commit(root, message):
    """Un commit limpio del paso, con identidad local para no depender de la configuracion del usuario."""
    import os
    import subprocess
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


class Autopilot:
    """El bucle, en un hilo, con una cola. Refuses a second loop: dos escritores es el fallo que la cola evita."""

    def __init__(self, config, runner=None, planner=None, bus=None, snapshot=None):
        self.config = config
        self._runner = runner
        self._planner = planner
        self.bus = bus
        self._snapshot = snapshot or backup.snapshot
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._state = {"running": False, "project": "", "iteration": 0, "iterations": 0,
                       "queue": [], "done": False, "note": "", "last": "", "steps_done": 0}

    # -- estado -------------------------------------------------------------------------------
    def _emit(self, kind, detail="", **payload):
        if self.bus is not None:
            self.bus.emit(kind, detail, **payload)

    def _update(self, **values):
        with self._lock:
            self._state.update(values)
            return dict(self._state, queue=list(self._state.get("queue") or []))

    def state(self):
        with self._lock:
            return dict(self._state, queue=list(self._state.get("queue") or []))

    def stop(self):
        if not self.state().get("running"):
            return False
        self._stop.set()
        self._emit("autonomy.stopping", "interrupcion pedida")
        return True

    # -- arranque -----------------------------------------------------------------------------
    def queue_for(self, project="", queue=None):
        """La cola a recorrer: lo que se pide, o la del operador, o el #1 de la prioridad."""
        if queue:
            names = [str(name).strip() for name in queue if str(name or "").strip()]
        elif project:
            names = [str(project).strip()]
        else:
            names = projects.order(self.config)[:1]
        seen, clean = set(), []
        for name in names:
            if name and name not in seen:
                seen.add(name)
                clean.append(name)
        return clean

    def start(self, project="", goal="", iterations=3, queue=None):
        """Arranca el bucle. Devuelve `(aceptado, estado)`; se niega si ya hay uno en marcha."""
        names = self.queue_for(project, queue)
        if not names:
            return False, "no hay ningun proyecto gobernado en la cola"
        if self._runner is None:
            return False, "el motor no tiene ejecutor de triada: no se puede correr en autonomo"
        limit = max(1, min(int(iterations or 3), 50))
        with self._lock:
            if self._state["running"]:
                return False, "ya hay un bucle autonomo en marcha"
            self._state.update({"running": True, "queue": names, "iterations": limit,
                                "iteration": 0, "project": names[0], "done": False, "note": "",
                                "steps_done": 0, "last": ""})
        self._stop.clear()
        thread = threading.Thread(target=self._loop, args=(names, str(goal or ""), limit),
                                  name="nexus-autonomy", daemon=True)
        try:
            thread.start()
        except RuntimeError as exc:
            self._update(running=False, note="no se pudo arrancar: %s" % exc)
            return False, "no se pudo arrancar el bucle: %s" % exc
        return True, self.state()

    # -- el bucle -----------------------------------------------------------------------------
    def _loop(self, names, goal, limit):
        stopped = False
        try:
            self._emit("autonomy.start", "cola: %s" % ", ".join(names), queue=names,
                       iterations=limit)
            for name in names:
                if self._stop.is_set():
                    stopped = True
                    break
                finished = self._project(name, goal, limit)
                if self._stop.is_set():
                    stopped = True
                    break
                if not finished:
                    # El motivo exacto lo puso `_project` (sin backup, gate rojo...). Aqui solo se
                    # anade que hay siguiente: pisarlo borraria la unica frase que explica la parada.
                    current = str(self.state().get("last") or "")
                    self._update(last=(current + " · se pasa al siguiente de la cola") if current
                                 else "%s: parado, se pasa al siguiente de la cola" % name)
        except Exception as exc:  # noqa: BLE001 -- un bucle que se cae sin decirlo es peor que rojo
            self._update(note="%s: %s" % (type(exc).__name__, exc))
            self._emit("autonomy.error", "%s: %s" % (type(exc).__name__, exc))
        finally:
            final = self._update(running=False, done=not stopped)
            self._emit("autonomy.stopped" if stopped else "autonomy.done",
                       "detenido" if stopped else "cola terminada", state=final)

    def _project(self, name, goal, limit):
        """Recorre un proyecto hasta su limite. `False` = se quedo rojo (o sin backup)."""
        root = Path(self.config.workspace) / name
        if not root.is_dir():
            self._update(last="%s no existe en el workspace" % name)
            self._emit("autonomy.error", "proyecto inexistente: %s" % name)
            return False
        criteria = projects.spec_of(root).get("criteria") or 0
        self._update(project=name, iteration=0)
        self._emit("autonomy.project", name, root=str(root), criteria=criteria)
        for index in range(1, int(limit) + 1):
            if self._stop.is_set():
                return True
            self._update(iteration=index)
            outcome = self._cycle(name, root, goal, index, int(limit))
            if outcome.get("done") or outcome.get("finished"):
                return True
            if not outcome.get("ok"):
                self._update(last="%s: %s" % (name, outcome.get("why") or "rojo"))
                self._emit("autonomy.red", str(outcome.get("why") or "rojo"), project=name,
                           iteration=index)
                return False
        return True

    def _cycle(self, name, root, goal, index, limit):
        """Un ciclo completo. Devuelve `{ok, done, why, ...}`; nunca lanza hacia el bucle."""
        net = self._snapshot(root, "autonomy")
        # `backup_kind` y no `kind`: `_emit(kind, detail, **payload)` ya usa ese nombre para el tipo de
        # evento, y reusarlo en el payload revienta con "multiple values for argument 'kind'".
        self._emit("autonomy.backup", "backup %s" % net.get("kind"),
                   ok=bool(net.get("ok")), backup_kind=net.get("kind"), ref=net.get("ref"),
                   reason=net.get("reason") or "")
        if not net.get("ok"):
            return {"ok": False, "why": "sin backup no se edita: %s" % (net.get("reason") or "?")}
        progress = projects.progress(root)
        plan = self._plan(root, goal, progress)
        step = str(plan.get("step") or "").strip()
        self._emit("autonomy.plan", step or "(sin paso)", done=bool(plan.get("done")),
                   why=plan.get("why") or "")
        if plan.get("done") and not step:
            self._record(root, goal, progress, {"step": "proyecto completo", "ok": True},
                         done=True)
            self._update(done=True, last="%s: 100%% (el Director no deja pasos)" % name)
            return {"ok": True, "done": True}
        if not step:
            return {"ok": False, "why": "el planificador no propuso ningun paso (%s)"
                    % (plan.get("why") or "sin motivo")}
        self._emit("autonomy.step", step, project=name, iteration=index, limit=limit)
        prompt = ("%s\n\nPASO %d/%d de la cola autonoma en %s:\n%s\n\nCuando termines, el gate tiene "
                  "que salir verde: no declares hecho lo que no has probado."
                  % (goal or projects.spec_of(root).get("goal") or name, index, limit, name, step))
        result = self._runner(prompt, str(root)) or {}
        ok = bool(result.get("ok")) or int(result.get("exit") or 0) == 0
        ledger.TurnLedger(root).append(ledger.from_turn(result, name, "autonomy", "autonomy"))
        if not ok:
            self._record(root, goal, progress, {"step": step, "ok": False,
                                                "exit": result.get("exit")}, done=False)
            return {"ok": False, "why": "gate rojo (exit %s) tras %s reparaciones"
                    % (result.get("exit"), result.get("repairs", 0))}
        committed, note = _commit(root, "nexus autonomo: %s" % step[:120])
        # `note` y no `detail`: `_emit` ya tiene un parametro con ese nombre (ver `autonomy.backup`).
        self._emit("autonomy.commit", step[:120], ok=committed, note=note)
        steps_done = self._record(root, goal, progress,
                                  {"step": step, "ok": True, "exit": result.get("exit"),
                                   "commit": committed, "touched": result.get("touched") or []},
                                  done=False)
        self._update(steps_done=steps_done, last="%s: paso %d verde" % (name, index))
        return {"ok": True, "done": False, "step": step}

    def _plan(self, root, goal, progress):
        if self._planner is not None:
            return self._planner(root, goal, progress) or {}
        return {"done": False, "step": "", "why": "sin planificador configurado"}

    def _record(self, root, goal, progress, step, done=False):
        """Escribe el progreso del proyecto: solo lo verificado llega aqui."""
        progress = dict(progress or {})
        steps = list(progress.get("steps") or [])
        steps.append(dict(step, at=_now()))
        data = {"goal": goal or progress.get("goal") or "", "steps": steps,
                "iterations": int(progress.get("iterations") or 0) + 1,
                "done": bool(done) or bool(progress.get("done")),
                "updated_at": _now()}
        projects.save_progress(root, data)
        return len([one for one in steps if one.get("ok")])
