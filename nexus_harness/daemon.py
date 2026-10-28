"""El daemon: trabajo autonomo cuando nadie esta mirando.

Tres piezas que la competencia ya trata como obligatorias y que aqui faltaban juntas:

* **Trigger** (no hace falta una persona): intervalo, `--once` para cron, o una tarea de la bandeja.
* **Estado durable**: `.nexus/harness/daemon.json` dice que paso en el ultimo tick, y el progreso de
  cada proyecto vive en su `.nexus/harness/progress.json`, asi que un reinicio **reanuda** lo que estaba
  a medias en vez de empezar de cero.
* **Guarda fail-closed**: si no hay backup no se edita (lo aplica `Autopilot`), ningun tick puede tirar
  el proceso, y un segundo daemon se niega a arrancar (cerrojo con pid).

Orden de un tick, y es deliberado:

1. **Bandeja primero**: lo que pidio una persona (o un bot) manda sobre lo que el daemon cree que toca.
2. **Spec**: si el proyecto no tiene criterios ejecutables, se intentan congelar los del propio repo
   (test/build detectados). Sin criterios no se inventa trabajo.
3. **Criterios**: si ya pasan, el proyecto no se toca; se buscan mejoras y se encolan.
4. **Trabajo**: se ejecuta un ciclo del `Autopilot` (con su backup, gate y commit).

Nada de esto llama a un modelo si no hay trabajo: un daemon en reposo cuesta cero tokens.
"""
import json
import os
import time
from pathlib import Path

from . import improve, projects, spec_synth
from .autonomy import Autopilot
from .notify import Notifier, summary
from .tasks import Inbox

STATE_NAME = "daemon.json"
LOCK_NAME = "daemon.lock"
AUTONOMY_LOG = Path(".nexus") / "harness" / "autonomy.jsonl"


def home():
    base = Path(os.environ.get("NEXUS_HOME") or (Path.home() / ".nexus"))
    return base / "harness"


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _alive(pid):
    """¿Sigue vivo ese proceso? En Windows se pregunta al kernel; en POSIX, senal 0."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def default_runner(config):
    """El ejecutor real: una triada completa por tarea. Se importa aqui para no cargar el motor en tests."""
    from .providers import Router
    from .runner import run_triad

    def run(goal, root):
        result, _triad = run_triad(config, Path(root), goal, Router(config))
        return result.as_dict()

    return run


class Daemon:
    """Un bucle sincrono y observable. `tick()` hace una ronda; `run()` repite con espera."""

    def __init__(self, config, runner=None, planner=None, notifier=None, bus=None,
                 interval=None, iterations=None, scan=None, clock=None, snapshot=None):
        self.config = config
        self.workspace = Path(config.workspace)
        self.interval = int(interval if interval is not None
                            else getattr(config, "daemon_interval", 300) or 300)
        self.iterations = int(iterations if iterations is not None
                              else getattr(config, "daemon_iterations", 2) or 2)
        self.scan = int(scan if scan is not None else getattr(config, "daemon_scan", 3) or 3)
        self.inbox = Inbox(self.workspace)
        self.notifier = notifier if notifier is not None else Notifier(config=config)
        self.bus = bus
        if planner is None and runner is None:
            # Produccion: el planificador es el Director real. En pruebas se inyecta un runner y el
            # planificador de reserva convierte el objetivo en un unico paso (sin modelo).
            from .autonomy import model_planner
            from .providers import Router
            planner = model_planner(Router(config), config)
        self.autopilot = Autopilot(config, runner=runner or default_runner(config),
                                   planner=planner or self._fallback_planner, bus=bus,
                                   snapshot=snapshot)
        self.state_path = home() / STATE_NAME
        self.lock_path = home() / LOCK_NAME
        self.rounds = 0
        self.started = ""
        self.last = {}

    # -- cerrojo y estado -----------------------------------------------------------------------
    def _acquire(self):
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            if self.lock_path.is_file():
                try:
                    holder = json.loads(self.lock_path.read_text(encoding="utf-8")).get("pid")
                except (OSError, ValueError):
                    holder = None
                if _alive(holder):
                    return False, "ya hay un daemon vivo (pid %s)" % holder
            self.lock_path.write_text(json.dumps({"pid": os.getpid(), "at": _now()}),
                                      encoding="utf-8")
            return True, ""
        except OSError as exc:
            return False, "no se pudo tomar el cerrojo: %s: %s" % (type(exc).__name__, exc)

    def _release(self):
        try:
            if self.lock_path.is_file():
                holder = json.loads(self.lock_path.read_text(encoding="utf-8")).get("pid")
                if holder == os.getpid():
                    self.lock_path.unlink()
        except (OSError, ValueError):
            return False
        return True

    def _save(self, payload):
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(payload, indent=1, sort_keys=True,
                                                  ensure_ascii=False), encoding="utf-8")
            return True
        except OSError:
            return False

    def status(self):
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return {"state": data, "lock": self.lock_path.is_file(),
                "inbox": self.inbox.status(), "interval": self.interval,
                "iterations": self.iterations}

    # -- un tick --------------------------------------------------------------------------------
    def _fallback_planner(self, root, goal, progress):
        """Sin Director: el objetivo ES el paso. Un id nuevo por ciclo para no bloquearse con el previo."""
        index = len((progress or {}).get("steps") or []) + 1
        step = str(goal or "").strip() or "avanza el objetivo del proyecto"
        return {"nodes": [{"id": "s%d" % index, "step": step, "depends_on": []}],
                "done": False, "why": "planificador de reserva: el objetivo es el paso"}

    def _candidates(self):
        """Quién entra en la cola: lo declarado, lo gobernado y lo que parece un proyecto.

        `projects.order()` solo devuelve proyectos CON spec, y el daemon existe para crear esa spec:
        mirar solo esa lista era una paradoja (nunca veria un proyecto nuevo). Los marcadores son
        baratos y honestos: si una carpeta tiene `.git`, un manifiesto o `.ai`, es un proyecto.
        """
        markers = {".git", ".ai", "pyproject.toml", "package.json", "Cargo.toml", "go.mod",
                   "composer.json", "Makefile"}
        declared = [str(name) for name in (getattr(self.config, "project_order", None) or [])
                    if (self.workspace / str(name)).is_dir()]
        governed = list(projects.order(self.config))
        scanned = []
        try:
            for path in sorted(self.workspace.iterdir()):
                if not path.is_dir() or path.name.startswith("."):
                    continue
                try:
                    names = {child.name for child in path.iterdir()}
                except OSError:
                    continue
                if markers & names:
                    scanned.append(path.name)
        except OSError:
            scanned = []
        seen, ordered = set(), []
        for name in declared + governed + scanned:
            if name and name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered

    def _resolve(self, project):
        name = str(project or "").strip()
        if not name:
            return None
        direct = Path(name)
        if direct.is_absolute() and direct.is_dir():
            return direct
        inside = self.workspace / name
        return inside if inside.is_dir() else None

    def _notify(self, payload):
        if not getattr(self.notifier, "ready", False):
            return []
        return self.notifier.send(summary(payload), kind=payload.get("status") or "info")

    def _task_tick(self):
        """Lo que pidio una persona manda. Devuelve la fila o `None` si la bandeja esta vacia."""
        claimed = self.inbox.claim(1)
        if not claimed:
            return None
        task = claimed[0]
        root = self._resolve(task.get("project")) or self.workspace
        self.bus and self.bus.emit("daemon.task", str(task.get("goal"))[:120], task=task["id"])
        try:
            exit_code = 0
            result = self.autopilot.run_goal(root, str(task.get("goal") or ""), 1)
            exit_code = 0 if result.get("ok") or result.get("done") else 10
            note = str(result.get("why") or result.get("step") or "")[:200]
        except Exception as exc:  # noqa: BLE001 -- una tarea rota cierra roja, no para el daemon
            exit_code, note = 10, "%s: %s" % (type(exc).__name__, exc)
        closed = self.inbox.close(task["id"], exit_code, note)
        row = {"ok": exit_code == 0, "task": task["id"], "project": task.get("project"),
               "exit": exit_code, "note": note, "status": "tarea"}
        if closed is None:
            row["ok"], row["note"] = False, "la tarea desaparecio de la bandeja al cerrarla"
        return row

    def _project_tick(self):
        """El primer proyecto gobernado que tenga algo que hacer. Devuelve la fila o `None`."""
        names = self._candidates()
        for name in list(names)[:max(1, self.scan)]:
            root = self.workspace / name
            if not root.is_dir():
                continue
            spec = projects.spec_of(root)
            if not spec.get("present"):
                frozen = spec_synth.synthesize(root, name, config=self.config,
                                               candidates=spec_synth.project_candidates(root, self.config),
                                               write=True)
                if frozen.get("written"):
                    return {"ok": True, "project": name, "status": "spec congelada",
                            "criteria": len(frozen["spec"]["cas"]),
                            "next": "ejecutar el primer ciclo"}
                improve.queue(root, self.config, inbox=self.inbox)
                continue
            rows = spec_synth.evaluate(root, config=self.config)
            if spec_synth.met(rows):
                added = improve.queue(root, self.config, inbox=self.inbox)
                return {"ok": True, "project": name, "status": "ya verde",
                        "criteria": len(rows),
                        "next": (added[0]["goal"][:120] if added else "sin mejoras pendientes")}
            goal = spec.get("goal") or name
            outcome = self.autopilot.run_project(name, goal, self.iterations)
            return {"ok": bool(outcome.get("ok") or outcome.get("done")), "project": name,
                    "status": "trabajo", "exit": 0 if outcome.get("ok") else 10,
                    "note": str(outcome.get("why") or "")[:200],
                    "next": "siguiente ciclo" if outcome.get("ok") else "revisar el rojo"}
        return None

    def tick(self):
        """Un tick completo. Nunca lanza: un error se convierte en fila con su motivo."""
        started = time.time()
        row = {"ok": False, "status": "sin trabajo", "note": ""}
        try:
            row = self._task_tick() or self._project_tick() or row
        except Exception as exc:  # noqa: BLE001 -- el daemon no muere por un proyecto roto
            row = {"ok": False, "status": "error", "note": "%s: %s" % (type(exc).__name__, exc)}
        row["seconds"] = round(time.time() - started, 2)
        row["at"] = _now()
        self.rounds += 1
        self.last = row
        notices = self._notify({"status": row.get("status"), "project": row.get("project"),
                                "task": row.get("task"), "exit": row.get("exit"),
                                "rounds": self.rounds, "criteria": row.get("criteria"),
                                "note": row.get("note"), "next": row.get("next")})
        self._save({"pid": os.getpid(), "started": self.started or _now(), "last_tick": row["at"],
                    "rounds": self.rounds, "status": row.get("status"), "last": row,
                    "notices": notices[-3:], "interval": self.interval,
                    "iterations": self.iterations})
        return row

    # -- el bucle -------------------------------------------------------------------------------
    def run(self, stop=None, rounds=None):
        """Repite ticks hasta `rounds`, hasta que `stop` se ponga, o hasta que el operador pare."""
        ok, why = self._acquire()
        if not ok:
            return {"ok": False, "reason": why, "rounds": 0, "rows": []}
        self.started = _now()
        rows, done = [], 0
        try:
            while True:
                if stop is not None and stop.is_set():
                    break
                rows.append(self.tick())
                done += 1
                if rounds is not None and done >= int(rounds):
                    break
                if stop is not None:
                    if stop.wait(self.interval):
                        break
                elif self.interval > 0:
                    time.sleep(self.interval)
                else:
                    break
        finally:
            self._release()
        return {"ok": True, "rounds": done, "rows": rows,
                "stopped": bool(stop is not None and stop.is_set())}
