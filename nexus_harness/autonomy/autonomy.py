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

from nexus_harness.platform import backup, ledger
from nexus_harness.autonomy import plan_graph
from nexus_harness import projects, spec_synth
from nexus_harness.autonomy import autonomy_ask
from nexus_harness.reflection import lessons_block
from nexus_harness.context.repo_map import RepoMap

AUTONOMY_LOG = Path(".nexus") / "harness" / "autonomy.jsonl"

PLANNER_PROMPT = """Eres el Director de un harness de ingenieria autonomo. Tienes un proyecto, su spec
congelada y los pasos YA hechos y verificados. Devuelve un PLAN CORTO en forma de grafo: entre 1 y 7
nodos, cada uno con su `id` y las dependencias que de verdad tiene (nada de cadenas inventadas).

Responde SOLO con JSON, sin texto alrededor:
{"nodes": [{"id": "n1", "step": "una frase imperativa con el fichero que toca", "depends_on": []},
           {"id": "n2", "step": "...", "depends_on": ["n1"]}],
 "new_criterion": null}

`new_criterion` solo si el trabajo ha descubierto algo que la spec NO mide y se puede comprobar con un
comando: {"title": "...", "command": "...", "expect_exit": 0}. Si no hay nada nuevo, deja null.
Si todos los criterios ya estan cumplidos, responde {"nodes": [], "done": true}.
No inventes criterios que nadie pida. No propongas reescribir lo que ya esta verde."""


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_plan(text):
    """El plan del Director, como grafo. Acepta el formato viejo de un solo paso y degrada a el."""
    return plan_graph.parse_graph(text)


def model_planner(router, config):
    """El planificador de verdad: el Director, con la spec y el progreso delante."""
    from nexus_harness.core.message import Message

    def plan(root, goal, progress):
        spec = projects.spec_of(root)
        done = [str(step.get("step") or "") for step in (progress or {}).get("steps") or []
                if step.get("ok")]
        try:
            # El Director no gasta turnos en `list_dir`: el mapa AST le dice donde vive cada simbolo.
            sketch = RepoMap(root, max_tokens=800).brief()
        except Exception:  # noqa: BLE001 -- sin mapa se planifica igual, solo mas a ciegas
            sketch = "(mapa AST no disponible)"
        taught = lessons_block(root)
        prompt = ("PROYECTO: %s\nOBJETIVO: %s\nSPEC: %s (%d criterios)\nPASOS HECHOS:\n%s\n"
                  "PASOS FALLIDOS: %s\n\nMAPA AST (1.500 tokens max):\n%s\n\n%s"
                  % (Path(root).name, goal or spec.get("goal") or "(sin objetivo)",
                     spec.get("id") or spec.get("format") or "(sin spec)", spec.get("criteria", 0),
                     "\n".join("- " + step for step in done[-12:]) or "(ninguno)",
                     len([one for one in (progress or {}).get("steps") or [] if not one.get("ok")]),
                     sketch, taught))
        try:
            reply = router.role("director").chat(
                [Message(role="system", content=PLANNER_PROMPT),
                 Message(role="user", content=prompt)],
                temperature=0.1, max_tokens=min(int(getattr(config, "max_tokens", 4096) or 4096), 600))
        except Exception as exc:  # noqa: BLE001 -- el bucle informa del motivo, no se cae
            return {"done": False, "step": "", "why": "el Director no contesto: %s: %s"
                    % (type(exc).__name__, exc)}
        # Un modelo de razonamiento puede devolver SOLO `reasoning_content` (Qwen/DeepSeek). Ignorarlo
        # dejaba el plan vacio y el bucle parado con "el planificador no propuso ningun paso": medido.
        result = parse_plan(getattr(reply, "text", "") or getattr(reply, "reasoning", ""))
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

    def run_project(self, name, goal="", iterations=2):
        """Un proyecto, sincrono, hasta `iterations`. Es lo que usa el daemon (nada de hilos).

        `_project` devuelve un bool (lo que necesita el bucle en hilo); aqui se devuelve la fila con su
        motivo, porque el daemon tiene que poder contarlo.
        """
        finished = self._project(name, goal, max(1, int(iterations)))
        return {"ok": bool(finished), "done": bool(finished),
                "why": str(self.state().get("last") or "")}

    def run_goal(self, root, goal, iterations=1):
        """Una corrida suelta sobre una raiz arbitraria: el trabajo de una tarea de la bandeja."""
        root = Path(root)
        return self._cycle(root.name, root, str(goal or ""), 1, max(1, int(iterations)))

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
                why = str(outcome.get("why") or "rojo")
                self._update(last="%s: %s" % (name, why))
                self._emit("autonomy.red", why, project=name, iteration=index)
                # Rojo no arreglado: o se para, o lo decide el operador. Un bucle que se inventa la
                # decision cuando nadie contesta es justo lo que este arnes no hace.
                asked = autonomy_ask.ask_about_red(root, name, why, self.config, index,
                                                   should_stop=self._stop.is_set)
                self._emit("autonomy.ask", str(asked.get("decision") or "?"), project=name,
                           source=asked.get("source"), state=asked.get("state"),
                           question=asked.get("question"))
                sigue, nota = autonomy_ask.act(root, asked["decision"])
                # El motivo NO se pierde al preguntar: la nota del operador se suma, no sustituye.
                self._update(last="%s: %s · %s" % (name, why, nota))
                if not sigue:
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
        # La unica definicion de "terminado": los criterios ejecutables de la spec, no la opinion del
        # Director. Si todos pasan, el proyecto esta hecho y no se gasta una llamada mas.
        rows = spec_synth.evaluate(root, config=self.config)
        if spec_synth.met(rows):
            self._criteria_done(name, root, goal, progress, rows)
            return {"ok": True, "done": True}
        plan = self._plan(root, goal, progress)
        if self._grow(root, plan.get("new_criterion")).get("ok"):
            rows = spec_synth.evaluate(root, config=self.config)
            if spec_synth.met(rows):
                self._criteria_done(name, root, goal, progress, rows)
                return {"ok": True, "done": True}
        nodes = plan.get("nodes") or []
        try:
            nodes = plan_graph.validate(nodes)
        except plan_graph.GraphError as exc:
            return {"ok": False, "why": "el plan no se puede ejecutar: %s" % exc}
        done_ids = [str(one) for one in progress.get("nodes") or []]
        ready = plan_graph.ready(nodes, done_ids)
        node = ready[0] if ready else None
        step = node.step if node is not None else str(plan.get("step") or "").strip()
        self._emit("autonomy.plan", step or "(sin paso)", done=bool(plan.get("done")),
                   why=plan.get("why") or "", nodes=len(nodes), ready=len(ready))
        if plan.get("done") and not step:
            self._record(root, goal, progress, {"step": "proyecto completo", "ok": True},
                         done=True)
            self._update(done=True, last="%s: 100%% (el Director no deja pasos)" % name)
            return {"ok": True, "done": True}
        if not step:
            if nodes:
                return {"ok": False, "why": "el plan no tiene ningun nodo listo: %s"
                        % ", ".join(one.id for one in nodes)}
            return {"ok": False, "why": "el planificador no propuso ningun paso (%s)"
                    % (plan.get("why") or "sin motivo")}
        self._emit("autonomy.step", step, project=name, iteration=index, limit=limit,
                   node=node.id if node is not None else "")
        prompt = ("%s\n\nPASO %d/%d de la cola autonoma en %s:\n%s\n\nCuando termines, el gate tiene "
                  "que salir verde: no declares hecho lo que no has probado."
                  % (goal or projects.spec_of(root).get("goal") or name, index, limit, name, step))
        result = self._runner(prompt, str(root)) or {}
        ok = bool(result.get("ok")) or int(result.get("exit") or 0) == 0
        # Una fila por corrida: si el ejecutor ya la escribio (lo declara en `recorded`), no se repite.
        if not result.get("recorded"):
            ledger.TurnLedger(root).append(ledger.from_turn(result, name, "autonomy", "autonomy"))
        if not ok:
            self._record(root, goal, progress, {"step": step, "ok": False,
                                                "exit": result.get("exit")}, done=False)
            # Un gate verde con el Juez en contra NO es "gate rojo": el operador tiene que saber cual
            # de los dos freno. Medido: el bucle decia "gate rojo (exit 10)" con el gate en exit 0.
            verdict, judgement = result.get("verdict") or {}, result.get("judgement") or {}
            if verdict.get("ok") and judgement.get("verdict") == "reject":
                return {"ok": False, "why": "el Juez rechazo el trabajo: %s"
                        % (judgement.get("reason") or "sin motivo")}
            return {"ok": False, "why": "gate rojo (exit %s) tras %s reparaciones"
                    % (result.get("exit"), result.get("repairs", 0))}
        committed, note = _commit(root, "nexus autonomo: %s" % step[:120])
        # `note` y no `detail`: `_emit` ya tiene un parametro con ese nombre (ver `autonomy.backup`).
        self._emit("autonomy.commit", step[:120], ok=committed, note=note)
        nodes_done = done_ids + ([node.id] if node is not None else [])
        steps_done = self._record(root, goal, progress,
                                  {"step": step, "ok": True, "exit": result.get("exit"),
                                   "commit": committed, "touched": result.get("touched") or [],
                                   "node": node.id if node is not None else ""},
                                  done=False, nodes=nodes_done)
        self._update(steps_done=steps_done, last="%s: paso %d verde" % (name, index))
        rows = spec_synth.evaluate(root, config=self.config)
        if spec_synth.met(rows):
            self._criteria_done(name, root, goal, projects.progress(root), rows)
            return {"ok": True, "done": True}
        return {"ok": True, "done": False, "step": step}

    def _criteria_done(self, name, root, goal, progress, rows):
        """El proyecto termina por criterios medidos, no por silencio del planificador."""
        self._record(root, goal, progress, {"step": "criterios cumplidos", "ok": True,
                                            "criteria": len(rows)}, done=True)
        self._update(done=True, last="%s: %d criterios ejecutables pasan" % (name, len(rows)))
        self._emit("autonomy.criteria", "todos los criterios pasan", criterios=len(rows),
                   rows=[{"id": row["id"], "exit": row["exit"]} for row in rows])

    def _grow(self, root, criterion):
        """Un criterio que el trabajo descubrio se valida y se anade a la spec. Nunca se quita otro."""
        if not criterion:
            return {}
        grown = spec_synth.add_criterion(root, criterion.get("title", ""),
                                        criterion.get("command", ""),
                                        int(criterion.get("expect_exit") or 0), "director",
                                        signature="autonomy", config=self.config)
        self._emit("autonomy.criterion", grown.get("reason") or "criterio anadido",
                   ok=bool(grown.get("ok")), criterion=criterion, reason=grown.get("reason", ""))
        return grown

    def _plan(self, root, goal, progress):
        if self._planner is not None:
            return self._planner(root, goal, progress) or {}
        return {"done": False, "step": "", "why": "sin planificador configurado"}

    def _record(self, root, goal, progress, step, done=False, nodes=None):
        """Escribe el progreso del proyecto: solo lo verificado llega aqui.

        `nodes` es el estado COMPLETO de nodos terminados del grafo (no el delta): el progreso se
        reescribe entero y una lista que crece por acumulacion acabaria contando dos veces.
        """
        progress = dict(progress or {})
        steps = list(progress.get("steps") or [])
        steps.append(dict(step, at=_now()))
        finished = nodes if nodes is not None else progress.get("nodes") or []
        data = {"goal": goal or progress.get("goal") or "", "steps": steps,
                "nodes": sorted({str(one) for one in finished}),
                "iterations": int(progress.get("iterations") or 0) + 1,
                "done": bool(done) or bool(progress.get("done")),
                "updated_at": _now()}
        projects.save_progress(root, data)
        return len([one for one in steps if one.get("ok")])
