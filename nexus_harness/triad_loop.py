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
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .platform import ledger
from . import triad_brief
from .core.budget import CostBudget
from .compaction import Compactor
from .context_compiler import build_prefix
from .platform.tokenizer import calibration, count_messages
from .turn_context import apply_budget, build_turn_prefix, inject_skills
from .turn_engine import TurnEngine
from .gate import EXIT_GREEN, EXIT_UNAVAILABLE, Gate
from .llm.judge import judge_for
from .core.message import Message, as_text
from .llm.portfolio import maybe_escalate
from .reflection import learn
from .repair_guard import isolated_repair
from .savings import CACHE_REL as SKILLS_CACHE, SavingsLedger
from .subagents import Delegate
from .toolbox import process_manager
from .tools import default_registry
from .triad_brief import CLOSE_PROMPT, JUDGE_REJECT, REPAIR_PROMPT, WORKER_PROMPT

@dataclass
class RunResult:
    goal: str = ""
    root: str = ""
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
    budget: dict = field(default_factory=dict)
    cost: dict = field(default_factory=dict)
    tokens: dict = field(default_factory=dict)
    savings: dict = field(default_factory=dict)
    recorded: bool = False
    started: str = ""
    finished: str = ""

    def as_dict(self):
        return {"goal": self.goal, "root": self.root, "ok": self.ok, "exit": self.exit, "summary": self.summary,
                "steps": self.steps, "repairs": self.repairs, "touched": self.touched,
                "sessions": self.sessions, "phases": self.phases, "verdict": self.verdict,
                "judgement": self.judgement, "budget": self.budget, "cost": self.cost,
                "tokens": self.tokens, "savings": self.savings, "recorded": self.recorded,
                "started": self.started, "finished": self.finished}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Triad:
    def __init__(self, router, config, registry=None, gate=None, judge=None, skills=None,
                 bus=None, relay=None, compactor=None):
        self.router = router
        self.config = config
        self.registry = registry or default_registry(config.default_root, config)
        self.gate = gate or Gate(config.default_root, config)
        self.judge = judge if judge is not None else judge_for(router, config)
        self.skills = skills
        self.bus = bus
        self.relay = relay
        self.cost = CostBudget(limit_usd=float(getattr(config, "cost_limit", 0.0) or 0.0))
        self.portfolio = getattr(router, "portfolio", None)
        self.compactor = compactor if compactor is not None else Compactor(
            limit=getattr(config, "budget_limit", 60000),
            threshold=getattr(config, "compact_threshold", 0.55))
        self.engine = TurnEngine(router, config, self.compactor, self.registry, emit=self._emit, relay=relay)
        self.touched = set()
        self.injections = []
        self.tokens = {"prompt": 0, "completion": 0}
        # La contabilidad por request vive aqui: sin baseline no hay ahorro medible.
        self.savings = SavingsLedger.for_root(cache_path=Path(config.default_root) / SKILLS_CACHE)
        self._injected_tokens = 0
        self._stop = threading.Event()
        self.registry.stop = self._stop
        if getattr(self.registry, "delegate", None) is None:
            self.registry.delegate = Delegate(router, config, stop=self._stop, bus=bus,
                                              root=config.default_root)

    def stop(self):
        """Same Detener contract as the chat: loop, subagents and background processes."""
        self._stop.set()
        killed = process_manager.kill_all_managers()
        self._emit("run.stopping", "interrupción pedida", processes_killed=killed)

    @property
    def stopped(self):
        return self._stop.is_set()

    # -- plumbing ---------------------------------------------------------------------------
    def _emit(self, kind, detail="", **payload):
        if self.bus is not None:
            self.bus.emit(kind, detail, **payload)

    def _prefix(self):
        """El prefijo estable del Obrero: reglas, mapa AST y el comando que le mide.

        Se construye una vez por run: reescribirlo en cada paso invalidaria la cache del proveedor.
        """
        if getattr(self, "_prefix_cache", None) is None:
            if not getattr(self.config, "nexus_engines", True):
                from .savings import full_index_brief
                brief = full_index_brief()
                self._injected_tokens = len(brief) // 4
                self._prefix_cache = build_prefix([("rules", WORKER_PROMPT), ("skills", brief)])
            else:
                self._prefix_cache = build_turn_prefix(self.config, WORKER_PROMPT, self.router,
                                                       "worker")
        return self._prefix_cache

    def _system(self, base, files):
        """Prefijo estable + delta en un texto: solo al abrir sesion (run y relevo), no por paso."""
        block, _tokens = inject_skills(self.skills, files, self._emit)
        self._delta_sent = block
        return "\n\n".join(part for part in (self._prefix().text, block) if part)

    def _note_delta(self, messages):
        """Anade el contexto que cambio (skills nuevas) al final, sin tocar el prefijo."""
        block, tokens = inject_skills(self.skills, self.touched, self._emit)
        self._injected_tokens = tokens
        if not block or block == getattr(self, "_delta_sent", ""):
            return False
        if any(str(getattr(one, "content", "")) == block for one in messages[-4:]):
            return False
        messages.append(Message(role="user", content=block))
        return True

    def _ask(self, role, messages, tools=None, max_tokens=None):
        info = self.router.info(role)
        if not info.ready:
            raise RuntimeError("%s is not ready: %s" % (role, info.why_not_ready))
        # La misma red de seguridad que el Chat: si el motor dice que no cabe, se poda y se repite.
        reply = self.engine.ask(messages, tools, role=role, max_tokens=max_tokens)
        self._count_savings(reply, messages)
        if reply.reasoning:
            self._emit("%s.reasoning" % role, reply.reasoning[:1200], model=reply.model)
        return reply

    def _count_savings(self, reply, messages):
        """Cierra la request en el libro de ahorro: lo enviado, el baseline y por que difieren."""
        from .compaction import estimate
        model = getattr(reply, "model", "") or ""
        measured = bool(getattr(reply.usage, "measured", False))
        sent = int(getattr(reply.usage, "prompt", 0) or 0) or estimate(messages)[1]
        if measured and sent > 0:
            calibration().observe(model, count_messages(messages, model), sent)
        _block, map_tokens = triad_brief.map_block(self.config)
        first = 0 if self.savings.repomap_tokens else map_tokens
        row = self.savings.request(sent, injected_skill_tokens=self._injected_tokens,
                                   repomap_tokens=first,
                                   measured=bool(getattr(reply.usage, "measured", False)),
                                   cached_tokens=int(getattr(reply.usage, "cached", 0) or 0))
        self._emit("context.savings", self.savings.note(), row=row, totals=self.savings.as_dict())
        return row

    # -- one phase --------------------------------------------------------------------------
    def _work(self, messages, max_steps):
        """Run the worker loop until it stops asking for tools. Returns (text, steps)."""
        text, steps = "", 0
        for step in range(max_steps):
            if self._stop.is_set():
                self._emit("worker.stopped", "interrupción pedida en el paso %d" % step)
                break
            if self.cost.stop("worker"):
                # Parada dura: ni una llamada mas, y tampoco el resumen de cierre (que costaria otra).
                self._emit("budget.stop", self.cost.reason, budget=self.cost.state())
                break
            messages[0] = Message(role="system", content=self._prefix().text)
            self._note_delta(messages)
            # Nivel 1 del presupuesto: poda deslizante + compactacion, con lo podado medido.
            apply_budget(messages, self.config, self.savings, self.compactor, self._emit)
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
            if self.relay is not None and self._maybe_relay(messages, text):
                # The session changed under this reply. Its tool calls belong to the old transcript and
                # must not be answered here: a `tool` message with no matching `tool_calls` in front is
                # rejected by every OpenAI-shaped server. The new session re-plans from its prompt.
                self._emit("worker.relay", "sesión relevada: las llamadas pendientes se descartan")
                break
            if not reply.wants_tools:
                break
            for call in reply.tool_calls:
                # `tool.start` es lo que la barra en vivo pinta como "en curso": sin el, el hilo solo
                # muestra herramientas que YA acabaron y parece que nada esta pasando.
                self._emit("tool.start", call.name, args=call.arguments)
                observation = self.registry.call(call.name, call.arguments) \
                    if not call.parse_error else _bad_arguments(call)
                self.touched.update(observation.files)
                messages.append(Message(role="tool", content=as_text(observation),
                                        tool_call_id=call.id, name=call.name))
                self._emit("tool.call", call.name, ok=observation.ok, args=call.arguments,
                           result=observation.text[:600])
        else:
            self._emit("worker.limit", "max_steps=%d reached" % max_steps)
            text = self._closing_summary(messages, text)
        return text, steps

    def _closing_summary(self, messages, fallback):
        """One last call without tools: a run that ends on a tool call leaves the judge nothing to
        approve, and an empty summary is a legitimate rejection. Two sentences cost one cheap call."""
        try:
            reply = self._ask("worker", list(messages) + [Message(role="user", content=CLOSE_PROMPT)],
                              tools=None, max_tokens=400)
        except Exception as exc:  # the summary is a courtesy; its absence is not a crash
            self._emit("worker.error", "closing summary failed: %s: %s" % (type(exc).__name__, exc))
            return fallback
        self._absorb(reply)
        if reply.text:
            self._emit("worker.close", reply.text[:400])
        return reply.text or fallback

    def _absorb(self, reply):
        self.cost.observe(reply.usage, reply.model)
        # Los tokens del run viajan en el resultado: el libro los necesita para su propia grafica.
        self.tokens["prompt"] += int(getattr(reply.usage, "prompt", 0) or 0)
        self.tokens["completion"] += int(getattr(reply.usage, "completion", 0) or 0)
        if self.relay is not None:
            self.relay.observe(reply.usage)

    def _maybe_relay(self, messages, text):
        """Replace the conversation with the next session's prompt. True when it happened."""
        if not self.relay.should_hand_over():
            return False
        handover = self.relay.hand_over(reason="budget", summary=text, files=self.touched)
        messages[:] = [Message(role="system", content=self._system(WORKER_PROMPT, self.touched)),
                       Message(role="user", content=handover.prompt)]
        self._emit("session.relay", "%s -> %s" % (handover.from_session, handover.to_session),
                   handover=handover.as_dict())
        return True

    # -- verdicts ---------------------------------------------------------------------------
    def _verify(self):
        verdict = self.gate.run(sorted(self.touched))
        self._emit("gate.verdict", "exit %s" % verdict.exit, verdict=verdict.as_dict())
        if self.relay is not None:  # el gate es la unica opinion que cuenta para el relevo
            self.relay.state.gate(verdict.exit, verdict.failures or "checks: %d" % len(verdict.checks))
            self.relay.state.touched(sorted(self.touched))
            self.relay.state.save()
        return verdict

    def _judge(self, goal, summary):
        judgement = self.judge.review(goal, summary, self.touched, self._last_verdict_text(),
                                      gate_ran=self._verdict is not None,
                                      root=self.config.default_root)
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
        self._prefix_cache, self._delta_sent = None, ""
        steps_total, repairs, reds = 0, 0, 0
        max_steps = int(max_steps or self.config.max_steps)
        max_repairs = int(max_repairs if max_repairs is not None else self.config.max_repairs)
        result = RunResult(goal=goal, root=str(self.config.default_root), started=_now())
        self._emit("run.start", goal, root=str(self.config.default_root))
        # El presupuesto se resuelve contra la ventana del motor ANTES de la primera llamada.
        self.engine.fit()
        self._emit("router.ready", self.router.info("worker").model,
                   roles={role: self.router.info(role).__dict__ for role in ("director", "worker", "judge")})
        plan = triad_brief.plan_for(self, goal)
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
                sandbox = (attempt and getattr(self.config, "worktree_repairs", False)
                           and getattr(self.config, "nexus_engines", True))
                text, steps = (isolated_repair(self, messages, max_steps) if sandbox else
                               self._work(messages, max_steps))
                steps_total += steps
                verdict = self._verify()
                self._verdict = verdict
                if verdict.ok:
                    break
                if attempt >= max_repairs:
                    break
                repairs += 1
                reds += 1
                maybe_escalate(self.router, self.portfolio, self.cost, reds, self._emit)
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
                text, steps = self._work(messages, max_steps)
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
        result.cost = self.cost.state()
        result.tokens = dict(self.tokens, total=sum(self.tokens.values()))
        result.savings = self.savings.as_dict()
        result.touched, result.finished = sorted(self.touched), _now()
        if self.relay is not None:
            self.relay.finish(result.exit)
            result.budget = self.relay.meter.state()
            result.sessions = self.relay.store.ids()
        learn(self.config, result.as_dict(), "run", self.skills, goal=result.goal)
        self._record(result)
        self._emit("run.end", "exit %s" % result.exit, ok=result.ok, summary=result.summary[:600])
        return result

    def _record(self, result):
        """Una linea en el libro por run, la escriba quien la escriba.

        `recorded` viaja en el resultado porque hay dos llamantes (chat y bucle autonomo) y una sola
        fila: contarla dos veces inflo el consumo medido al doble (411.886 en vez de 205.943).
        """
        root = str(self.config.default_root)
        result.recorded = ledger.TurnLedger(root).append(
            ledger.from_turn(result.as_dict(), root, (result.sessions or [""])[-1], "run"))

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