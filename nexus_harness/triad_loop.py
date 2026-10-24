"""The triad: Director plans, Worker acts, Gate and Judge decide -- and a red gate wakes the Worker.

This is the whole difference from a normal harness. There, the turn ends when the model stops talking.
Here, the turn ends when the gate says green and the judge does not object; until then the loop keeps
handing the worker the exact failure it produced, with no human in between.

    director  -> plan (one call, no tools)
    worker    -> tool loop (skills injected before every call, files accumulate)
    gate      -> lint + line law + tests          red:  repair, up to max_repairs
    judge     -> approve / reject                 reject: one more repair
    relay     -> if the budget crossed 70 %, the session is replaced and the loop continues

Exit codes are the protocol's: `0` green, `10` red, `20` the harness could not verify.
"""
import time
from dataclasses import dataclass, field

from .gate import EXIT_GREEN, EXIT_UNAVAILABLE, Gate
from .judge import Judge
from .message import Message, as_text
from .tools import default_registry

DIRECTOR_PROMPT = """Eres el Director de un harness de ingeniería autónomo.
Recibes un objetivo y el estado del repositorio. Devuelve un PLAN BREVE (máximo 6 pasos numerados)
que diga qué hay que cambiar y en qué ficheros, y termina con una línea "Criterio: <cómo se sabrá
que está hecho>". No escribas código, no llames herramientas: solo el plan."""

WORKER_PROMPT = """Eres el Obrero de un harness de ingeniería autónomo. Ejecutas el plan con las
herramientas disponibles.

Reglas que no se negocian:
- Ningún fichero puede pasar de 400 líneas. Si un módulo crece, divídelo.
- Para editar usa `patch` con el texto EXACTO que has leído; si falla por ambigüedad, lee más
  contexto y vuelve a intentarlo. `write_file` es para ficheros nuevos o reescrituras completas.
- Inspecciona antes de escribir: `read_file`, `search`, `list_dir`.
- No declares nada terminado: el gate lo comprobará. Cuando hayas terminado, responde con un
  resumen de una frase de lo que cambiaste y qué comando lo demuestra."""

REPAIR_PROMPT = """El gate ha devuelto ROJO (exit 10). Esto es lo que ha observado:

%s

Repara exactamente eso con las herramientas y vuelve a dejarlo. No expliques: actúa."""

JUDGE_REJECT = """El Juez rechazó el trabajo: %s

Corrige lo que señala y deja el repositorio en verde otra vez."""


@dataclass
class RunResult:
    goal: str = ""
    ok: bool = False
    exit: int = 10
    summary: str = ""
    steps: int = 0
    repairs: int = 0
    touched: list = field(default_factory=list)
    sessions: list = field(default_factory=list)
    phases: list = field(default_factory=list)
    verdict: dict = field(default_factory=dict)
    judgement: dict = field(default_factory=dict)
    started: str = ""
    finished: str = ""

    def as_dict(self):
        return {"goal": self.goal, "ok": self.ok, "exit": self.exit, "summary": self.summary,
                "steps": self.steps, "repairs": self.repairs, "touched": self.touched,
                "sessions": self.sessions, "phases": self.phases, "verdict": self.verdict,
                "judgement": self.judgement, "started": self.started, "finished": self.finished}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Triad:
    def __init__(self, router, config, registry=None, gate=None, judge=None, skills=None,
                 bus=None, relay=None):
        self.router = router
        self.config = config
        self.registry = registry or default_registry(config.default_root, config)
        self.gate = gate or Gate(config.default_root, config)
        self.judge = judge if judge is not None else Judge(router, getattr(config, "lang", "es"))
        self.skills = skills
        self.bus = bus
        self.relay = relay
        self.touched = set()
        self.injections = []

    # -- plumbing ---------------------------------------------------------------------------
    def _emit(self, kind, detail="", **payload):
        if self.bus is not None:
            self.bus.emit(kind, detail, **payload)

    def _system(self, base, files):
        if self.skills is None:
            return base
        injection = self.skills.select(sorted(files))
        self.injections.append(injection.as_dict())
        self._emit("skills.injected", ", ".join(injection.names) or "(none)",
                   names=injection.names, tokens=injection.tokens,
                   available=injection.available, note=injection.note)
        return "%s\n\n%s" % (base, injection.brief) if injection.brief else base

    def _ask(self, role, messages, tools=None, max_tokens=None):
        info = self.router.info(role)
        if not info.ready:
            raise RuntimeError("%s is not ready: %s" % (role, info.why_not_ready))
        reply = self.router.role(role).chat(
            messages, tools=tools, temperature=self.config.temperature,
            max_tokens=max_tokens or self.config.max_tokens)
        if reply.reasoning:
            self._emit("%s.reasoning" % role, reply.reasoning[:1200], model=reply.model)
        return reply

    # -- one phase --------------------------------------------------------------------------
    def _work(self, messages, goal_hint, max_steps):
        """Run the worker loop until it stops asking for tools. Returns (text, steps)."""
        text, steps = "", 0
        for step in range(max_steps):
            messages[0] = Message(role="system", content=self._system(WORKER_PROMPT, self.touched))
            try:
                reply = self._ask("worker", messages, tools=self.registry.schemas())
            except RuntimeError as exc:
                self._emit("worker.blocked", str(exc))
                return text or str(exc), steps
            except Exception as exc:
                self._emit("worker.error", "%s: %s" % (type(exc).__name__, exc))
                return text or "%s: %s" % (type(exc).__name__, exc), steps
            steps += 1
            if reply.text:
                text = reply.text
            self._emit("worker.turn", reply.text[:400] or "(tool call)",
                       tool_calls=[call.name for call in reply.tool_calls], step=step)
            messages.append(reply.as_message())
            self._absorb(reply)
            if self.relay is not None:
                self._maybe_relay(messages, text)
            if not reply.wants_tools:
                break
            for call in reply.tool_calls:
                observation = self.registry.call(call.name, call.arguments) \
                    if not call.parse_error else _bad_arguments(call)
                self.touched.update(observation.files)
                messages.append(Message(role="tool", content=as_text(observation),
                                        tool_call_id=call.id, name=call.name))
                self._emit("tool.call", call.name, ok=observation.ok, args=call.arguments,
                           result=observation.text[:600])
        else:
            self._emit("worker.limit", "max_steps=%d reached" % max_steps)
        return text, steps

    def _absorb(self, reply):
        if self.relay is not None:
            self.relay.observe(reply.usage)

    def _maybe_relay(self, messages, text):
        if not self.relay.should_hand_over():
            return
        handover = self.relay.hand_over(reason="budget", summary=text, files=self.touched)
        messages[:] = [Message(role="system", content=self._system(WORKER_PROMPT, self.touched)),
                       Message(role="user", content=handover.prompt)]
        self._emit("session.relay", "%s -> %s" % (handover.from_session, handover.to_session),
                   handover=handover.as_dict())

    # -- verdicts ---------------------------------------------------------------------------
    def _verify(self):
        verdict = self.gate.run(sorted(self.touched))
        self._emit("gate.verdict", "exit %s" % verdict.exit, verdict=verdict.as_dict())
        return verdict

    def _judge(self, goal, summary):
        judgement = self.judge.review(goal, summary, self.touched,
                                      self._last_verdict_text())
        self._emit("judge.verdict", judgement.verdict, judgement=judgement.as_dict())
        return judgement

    def _last_verdict_text(self):
        verdict = getattr(self, "_verdict", None)
        if verdict is None:
            return "(no gate run)"
        return "\n".join("%s: %s" % (check.name, check.detail) for check in verdict.checks)[:1500]

    # -- the run ----------------------------------------------------------------------------
    def run(self, goal, phases=None, max_steps=None, max_repairs=None):
        self.touched = set()
        self.injections = []
        steps_total, repairs = 0, 0
        max_steps = int(max_steps or self.config.max_steps)
        max_repairs = int(max_repairs if max_repairs is not None else self.config.max_repairs)
        result = RunResult(goal=goal, started=_now())
        self._emit("run.start", goal, root=str(self.config.default_root))
        self._emit("router.ready", self.router.info("worker").model,
                   roles={role: self.router.info(role).__dict__ for role in ("director", "worker", "judge")})
        plan = self._plan(goal)
        for phase in (phases or [None]):
            hint, label = goal, "run"
            if phase:
                label = "fase %s" % phase.get("id")
                hint = "%s\n\nFASE %s -- %s\n- %s" % (
                    goal, phase.get("id"), phase.get("title") or "",
                    "\n- ".join(phase.get("items") or []))
                self._emit("phase.start", label, phase=phase)
            messages = [Message(role="system", content=self._system(WORKER_PROMPT, self.touched)),
                        Message(role="user", content="%s\n\nPLAN DEL DIRECTOR:\n%s" % (hint, plan))]
            for attempt in range(max_repairs + 1):
                text, steps = self._work(messages, hint, max_steps)
                steps_total += steps
                verdict = self._verify()
                self._verdict = verdict
                if verdict.ok:
                    break
                if attempt >= max_repairs:
                    break
                repairs += 1
                messages.append(Message(role="user", content=REPAIR_PROMPT % verdict.failures))
                self._emit("repair", "attempt %d" % repairs, failures=verdict.failures[:800])
            if not verdict.ok:
                result.verdict = verdict.as_dict()
                result.exit = verdict.exit
                result.summary = text
                result.steps, result.repairs = steps_total, repairs
                result.touched, result.finished = sorted(self.touched), _now()
                result.phases.append({"id": (phase or {}).get("id", "run"), "ok": False,
                                      "exit": verdict.exit})
                break
            judgement = self._judge(hint, text)
            if judgement.verdict == "reject" and repairs < max_repairs:
                repairs += 1
                messages.append(Message(role="user", content=JUDGE_REJECT % judgement.reason))
                text, steps = self._work(messages, hint, max_steps)
                steps_total += steps
                verdict = self._verify()
                self._verdict = verdict
                judgement = self._judge(hint, text) if verdict.ok else judgement
            self._checkpoint(phase, verdict)
            result.phases.append({"id": (phase or {}).get("id", "run"), "ok": verdict.ok,
                                  "exit": verdict.exit, "judgement": judgement.verdict})
            result.verdict, result.judgement = verdict.as_dict(), judgement.as_dict()
            result.summary = text
            if not verdict.ok or judgement.verdict == "reject":
                result.ok = False
                result.exit = verdict.exit if not verdict.ok else 10
                break
            result.ok, result.exit = True, EXIT_GREEN
        if result.ok:
            result.exit = EXIT_GREEN
        elif result.exit not in (10, EXIT_UNAVAILABLE):
            result.exit = 10
        result.steps, result.repairs = steps_total, repairs
        result.touched, result.finished = sorted(self.touched), _now()
        if self.relay is not None:
            result.sessions = self.relay.store.ids()
        self._emit("run.end", "exit %s" % result.exit, ok=result.ok, summary=result.summary[:600])
        return result

    def _plan(self, goal):
        facts = self._facts()
        prompt = "OBJETIVO:\n%s\n\nESTADO DEL REPOSITORIO:\n%s" % (goal, facts)
        try:
            reply = self._ask("director", [Message(role="system", content=DIRECTOR_PROMPT),
                                           Message(role="user", content=prompt)],
                              max_tokens=min(self.config.max_tokens, 1200))
        except Exception as exc:
            self._emit("director.error", "%s: %s" % (type(exc).__name__, exc))
            return "(sin plan: %s)" % exc
        self._emit("director.plan", reply.text[:1500], model=reply.model)
        return reply.text or "(plan vacío)"

    def _facts(self):
        root = self.config.default_root
        try:
            entries = sorted(path.name for path in root.iterdir())[:40]
        except OSError:
            entries = []
        return "root: %s\nentries: %s" % (root, ", ".join(entries) or "(empty)")

    def _checkpoint(self, phase, verdict):
        if phase is None or self.relay is None:
            return None
        evidence = [{"command": "gate:%s" % check.name, "exit": check.exit}
                    for check in verdict.checks if isinstance(check.exit, int)]
        return self.relay.checkpoint(phase.get("id"), evidence,
                                     note="%s green via triad loop" % phase.get("id"))


def _bad_arguments(call):
    from .tools import Observation
    return Observation(ok=False, text="tool arguments are unusable: %s" % call.parse_error)
