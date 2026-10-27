"""Chat: the same harness, but as a conversation instead of a one-shot goal.

`triad_loop` answers "make this true and prove it". A chat has to answer "what do you need?" first, and
only then touch the repository. Both share everything below the loop: the provider router, the toolbox,
the Nexus skills prefilter, the gate and the judge. What changes is when the gate runs:

* a turn that touched files runs the gate, and a red gate is repaired in the same turn (the model sees
  the exact finding, not a sentence about it);
* a turn that only read, answered or fetched does not run the gate, because there is nothing to prove;
* the judge is consulted only when the gate ran and passed -- and a rejection is reported, not hidden.

History is a list of `Message`s persisted by `Transcripts` on every turn, so closing the window is not
losing the conversation. `stop()` sets an event the loop checks between tool calls: a harness you
cannot interrupt is a harness that owns your afternoon.
"""
import threading
from pathlib import Path
from dataclasses import dataclass, field

from . import attachments as attachment_tools
from . import checkpoint, ledger
from .budget import CostBudget
from . import triad_brief
from .compaction import Compactor
from .context_pruner import prune
from .message import Message, as_text
from .savings import CACHE_REL as SKILLS_CACHE, SavingsLedger
from .subagents import Delegate
from .toolbox import process_manager
from .tools import Observation, parallel_reads

CHAT_SYSTEM = """Eres Nexus-Harness, un agente de ingeniería que trabaja en el proyecto abierto.

Cómo trabajas:
- Antes de escribir, inspecciona: `list_dir`, `read_file`, `search`.
- Para editar usa `patch` (texto exacto, una sola coincidencia) o `write_file` para ficheros nuevos.
- Ningún fichero puede pasar de 400 líneas: si crece, divídelo por responsabilidad.
- Después de tocar código, el gate comprueba lint, ley de 400 y los tests del proyecto. Si sale rojo,
  te llegarán los hallazgos exactos y debes repararlos tú.
- No inventes resultados: si algo no lo has ejecutado, di que no lo has verificado.
- Responde en el idioma del operador, breve, diciendo qué has hecho y cómo se comprueba."""

REPAIR = """El gate ha devuelto ROJO (exit 10). Hallazgos observados:

%s

Repara exactamente eso. No expliques: actúa."""


@dataclass
class Turn:
    reply: str = ""
    exit: int = 0
    steps: int = 0
    repairs: int = 0
    touched: list = field(default_factory=list)
    skills: list = field(default_factory=list)
    verdict: dict = field(default_factory=dict)
    judgement: dict = field(default_factory=dict)
    stopped: bool = False
    attachments: list = field(default_factory=list)
    checkpoint: str = ""
    budget: dict = field(default_factory=dict)
    tokens: dict = field(default_factory=dict)
    savings: dict = field(default_factory=dict)

    def as_dict(self):
        return {"reply": self.reply, "exit": self.exit, "steps": self.steps,
                "repairs": self.repairs, "touched": self.touched, "skills": self.skills,
                "verdict": self.verdict, "judgement": self.judgement, "stopped": self.stopped,
                "attachments": self.attachments, "checkpoint": self.checkpoint,
                "budget": self.budget, "tokens": self.tokens, "savings": self.savings}


class Chat:
    """One conversation, many turns, one gate at the end of any turn that changed something."""

    def __init__(self, router, config, registry, gate, skills, bus=None, memory=None,
                 transcripts=None, judge=None, clock=None, delegate=None):
        self.router = router
        self.config = config
        self.registry = registry
        self.gate = gate
        self.skills = skills
        self.bus = bus
        self.memory = memory
        self.transcripts = transcripts
        self.judge = judge
        self._clock = clock
        self.session = None
        self.history = []
        self.touched = set()
        self._stop = threading.Event()
        self.last_turn = Turn()
        self.checkpoint = None
        self.turn_tokens = {"prompt": 0, "completion": 0}
        self.used = 0
        self.cost = CostBudget(limit_usd=float(getattr(config, "cost_limit", 0.0) or 0.0))
        self.compactor = Compactor(limit=int(getattr(config, "budget_limit", 60000) or 0),
                                   threshold=float(getattr(config, "compact_threshold", 0.55) or 0.0))
        self.children = []
        # Los cuatro motores miden aqui: skills dormidas, poda, mapa AST y reparacion aislada.
        self.savings = SavingsLedger.for_root(cache_path=Path(config.default_root) / SKILLS_CACHE)
        self._injected_tokens = 0
        self._map_tokens = 0
        registry.stop = self._stop
        registry.delegate = delegate or Delegate(
            router, config, stop=self._stop, bus=bus, root=config.default_root)

    # -- lifecycle ---------------------------------------------------------------------------
    def _emit(self, kind, detail="", **payload):
        if self.bus is not None:
            self.bus.emit(kind, detail, **payload)

    def new(self, title=""):
        if self.transcripts is None:
            self.session = {"id": "chat-local", "title": title, "messages": [], "turns": 0}
        else:
            self.session = self.transcripts.new(title)
        self.history = []
        self.touched = set()
        self._stop.clear()
        self._emit("chat.new", self.session.get("id", ""), title=title)
        return self.session

    def load(self, session_id):
        if self.transcripts is None:
            return None
        session = self.transcripts.load(session_id)
        if session is None:
            return None
        self.session = session
        self.history = [Message.from_openai(row) for row in session.get("messages") or []]
        self.touched = set()
        self._stop.clear()
        self._emit("chat.load", session_id)
        return session

    def stop(self):
        """Detener: the loop, the subagents and every background process this turn started."""
        self._stop.set()
        killed = process_manager.kill_all_managers()
        self._emit("chat.stopping", "interrupción pedida", processes_killed=killed)

    @property
    def stopped(self):
        return self._stop.is_set()

    # -- prompt ------------------------------------------------------------------------------
    def _system(self, files):
        parts = [CHAT_SYSTEM]
        self._injected_tokens = 0
        if not getattr(self.config, "nexus_engines", True):
            # Modo tradicional (benchmark A): TODAS las skills instaladas en el prompt de cada llamada.
            from .savings import full_index_brief
            brief = full_index_brief()
            if brief:
                parts.append(brief)
                self._injected_tokens = len(brief) // 4
            return "\n\n".join(parts)
        if self.memory is not None:
            block = self.memory.block()
            if block:
                parts.append(block)
        if self.skills is not None:
            injection = self.skills.select(sorted(files))
            self._emit("skills.injected", ", ".join(injection.names) or "(none)",
                       names=injection.names, tokens=injection.tokens,
                       available=injection.available, note=injection.note)
            if injection.brief:
                parts.append(injection.brief)
            self._injected_tokens = int(injection.tokens or 0)
        block, self._map_tokens = triad_brief.map_block(self.config)
        if block:
            parts.append("## Mapa de simbolos (pide rangos con read_file offset/limit)\n%s" % block)
        facts = "## Proyecto\n\nraíz: %s" % getattr(self.config, "default_root", ".")
        test = getattr(self.config, "test_command", None)
        facts += "\ntests: %s" % (test or "no configurado")
        parts.append(facts)
        return "\n\n".join(parts)

    # -- the loop ----------------------------------------------------------------------------
    def _maybe_compact(self, messages):
        """Poda deslizante + compactacion: los dos niveles del presupuesto, medidos.

        La poda corre en CADA paso (es lo que corta el crecimiento cuadratico de tokens de entrada) y
        la compactacion es la rampa previa al relevo del 70 %.
        """
        if not getattr(self.config, "nexus_engines", True):
            return False
        report = prune(messages)
        if report.pruned:
            self.savings.observe_pruned(report)
            self._emit("context.pruned", "%d salidas podadas (%d tokens menos)"
                       % (report.pruned, report.tokens_saved), count=report.pruned,
                       tokens_saved=report.tokens_saved, references=report.receipts[:8])
        result = self.compactor.maybe(messages)
        if result.applied:
            self._emit("context.compacted", result.reason, compaction=result.as_dict())
        return bool(result.applied or report.pruned)

    def _turn(self, tools=True, max_steps=None):
        """Model calls until it stops asking for tools. Returns (text, steps)."""
        text, steps = "", 0
        for step in range(int(max_steps or self.config.max_steps)):
            if self._stop.is_set():
                return text, steps
            if self.cost.stop("chat"):
                # La parada dura va ANTES de la llamada: cruzar el techo no pide una llamada mas.
                self._emit("budget.stop", self.cost.reason, budget=self.cost.state())
                break
            messages = [Message(role="system", content=self._system(self.touched))] + self.history
            if self._maybe_compact(messages):
                # The system message was just rebuilt; the compacted remainder is the new history.
                self.history = messages[1:]
            reply = self.router.role("worker").chat(
                messages, tools=self.registry.schemas() if tools else None,
                temperature=self.config.temperature, max_tokens=self.config.max_tokens)
            steps += 1
            self.used += int(getattr(reply.usage, "total", 0) or 0)
            self._count(reply.usage)
            self._count_savings(reply, messages)
            self.cost.observe(reply.usage, reply.model)
            if reply.reasoning:
                self._emit("worker.reasoning", reply.reasoning[:1000], model=reply.model)
            self.history.append(reply.as_message())
            if reply.text:
                text = reply.text
                self._emit("chat.assistant", reply.text[:1500], step=step)
            if not reply.wants_tools:
                break
            for index, call, observation in self._dispatch(reply.tool_calls):
                self.touched.update(observation.files)
                self.history.append(Message(role="tool", content=as_text(observation),
                                            tool_call_id=call.id, name=call.name))
                self._emit("tool.call", call.name, ok=observation.ok, args=call.arguments,
                           result=observation.text[:600])
        else:
            self._emit("chat.limit", "max_steps=%d" % int(max_steps or self.config.max_steps))
        return text, steps

    def _count_savings(self, reply, messages):
        """Cierra la request en el libro de ahorro del turno (baseline, ahorro y multiplicador)."""
        from .compaction import estimate
        sent = int(getattr(reply.usage, "prompt", 0) or 0) or estimate(messages)[1]
        first_map = 0 if self.savings.repomap_tokens else self._map_tokens
        row = self.savings.request(sent, injected_skill_tokens=self._injected_tokens,
                                   repomap_tokens=first_map,
                                   measured=bool(getattr(reply.usage, "measured", False)))
        self._emit("context.savings", self.savings.note(), row=row, totals=self.savings.as_dict())
        return row

    def _count(self, usage):
        """Suma los tokens del turno. Sin esto, el libro de turnos no puede decir cuanto costo."""
        self.turn_tokens["prompt"] += int(getattr(usage, "prompt", 0) or 0)
        self.turn_tokens["completion"] += int(getattr(usage, "completion", 0) or 0)

    def _dispatch(self, calls):
        """Run the model's tool calls: read-only ones together, everything else in order."""
        calls = list(calls or [])
        ready = [(call, index) for index, call in enumerate(calls) if not call.parse_error]
        results = {}
        if len(ready) > 1:
            self._emit("tool.parallel", "%d llamadas en paralelo" % len(ready),
                       names=[call.name for call, _ in ready],
                       args={"paths": [str((call.arguments or {}).get("path") or
                                           (call.arguments or {}).get("pattern") or "")
                                        for call, _ in ready][:4]})
            # La barra en vivo necesita saber que EMPEZO, no solo que acabo: `tool.start` es el aviso
            # de que el motor esta tocando algo ahora mismo.
            self._emit("tool.start", "%d tools" % len(ready),
                       names=[call.name for call, _ in ready])
            workers = int(getattr(self.config, "tool_workers", 4) or 4)
            for observation, (_call, index) in zip(
                    parallel_reads(self.registry, ready, self._stop, workers), ready):
                results[index] = observation
        elif ready:
            call, index = ready[0]
            self._emit("tool.start", call.name, args=call.arguments)
            results[index] = self.registry.call(call.name, call.arguments)
        for index, call in enumerate(calls):
            yield (index, call,
                   results.get(index) or Observation(ok=False, text="argumentos ilegibles: %s"
                                                     % call.parse_error))

    def send(self, text, attachments=None):
        """One operator turn. Blocking; the cockpit runs it in a thread and streams events."""
        text = str(text or "").strip()
        blocks, rejected = attachment_tools.ingest(self.config.default_root, attachments or [])
        if rejected:
            self._emit("attachments.rejected", "; ".join(rejected)[:600], notes=rejected)
        if not text and not blocks:
            return Turn(reply="", exit=0).as_dict()
        if self.session is None:
            self.new(text[:60] or (blocks[0].get("name") if blocks else "adjuntos"))
        self._stop.clear()
        content = attachment_tools.as_content(blocks, text) if blocks else text
        self._emit("chat.user", text[:1500] or attachment_tools.summary(blocks),
                   attachments=attachment_tools.chips(blocks), notes=rejected)
        self.history.append(Message(role="user", content=content))
        turn = Turn(attachments=attachment_tools.chips(blocks))
        self.checkpoint = checkpoint.begin(self.config.default_root, self.session.get("id", "turno"))
        checkpoint.set_active(self.checkpoint)
        turn.checkpoint = self.checkpoint.name
        self._emit("turn.checkpoint", self.checkpoint.name)
        self.turn_tokens = {"prompt": 0, "completion": 0}
        reply, steps = self._turn(tools=True)
        turn.steps += steps
        if self._stop.is_set():
            turn.stopped = True
        verdict = None
        if self.touched:
            verdict = self.gate.run(sorted(self.touched))
            self._emit("gate.verdict", "exit %s" % verdict.exit, verdict=verdict.as_dict())
        attempts = 0
        while verdict is not None and not verdict.ok and attempts < int(self.config.max_repairs):
            if self._stop.is_set():
                break
            attempts += 1
            self._emit("chat.repair", "intento %d" % attempts, failures=verdict.failures[:800])
            self.history.append(Message(role="user", content=REPAIR % verdict.failures))
            more, steps = self._turn(tools=True)
            turn.steps += steps
            reply = more or reply
            verdict = self.gate.run(sorted(self.touched))
            self._emit("gate.verdict", "exit %s" % verdict.exit, verdict=verdict.as_dict())
        if verdict is not None:
            turn.exit = verdict.exit
            turn.verdict = verdict.as_dict()
        turn.repairs = attempts
        if verdict is not None and verdict.ok and self.judge is not None:
            judgement = self.judge.review(text, reply, self.touched,
                                          "\n".join("%s: %s" % (check.name, check.detail)
                                                    for check in verdict.checks))
            self._emit("judge.verdict", judgement.verdict, judgement=judgement.as_dict())
            turn.judgement = judgement.as_dict()
        turn.reply, turn.touched = reply, sorted(self.touched)
        turn.budget = self.cost.state()
        turn.tokens = dict(self.turn_tokens, total=sum(self.turn_tokens.values()))
        turn.savings = self.savings.as_dict()
        injection = getattr(self.skills, "last", None)
        turn.skills = list(getattr(injection, "names", []) or [])
        self.last_turn = turn
        self._persist(turn)
        self._emit("chat.turn", "exit %s" % turn.exit, turn=turn.as_dict())
        return turn.as_dict()

    def _persist(self, turn):
        if self.checkpoint is not None:
            # El turno termina aqui, y con el el diario: lo que venga despues (otro turno, el gate de
            # la manana) no debe caer dentro de la instantanea de este.
            self._emit("checkpoint.closed", self.checkpoint.name, files=len(self.checkpoint.entries))
            checkpoint.set_active(None)
        # El libro de turnos se escribe ANTES de guardar el transcript: una conversacion sin fichero
        # (sin transcripts) sigue midiendo su gate, y las graficas de estadisticas se alimentan de aqui.
        ledger.TurnLedger(self.config.default_root).append(
            ledger.from_turn(turn.as_dict(), str(self.config.default_root),
                             str((self.session or {}).get("id") or ""), "chat"))
        if self.transcripts is None or self.session is None:
            return
        self.session["messages"] = [message.to_openai() for message in self.history]
        self.session["turns"] = int(self.session.get("turns", 0)) + 1
        self.session["exit"] = turn.exit
        if not self.session.get("title"):
            self.session["title"] = next((message.text_content() for message in self.history
                                          if message.role == "user"), "")[:90]
        self.transcripts.save(self.session)

    def budget(self):
        limit = int(getattr(self.config, "budget_limit", 0) or 0)
        state = "unmeasured" if not limit else "measured"
        return {"used": self.used, "limit": limit, "ratio": (self.used / limit) if limit else None,
                "state": state, "threshold": getattr(self.config, "relay_threshold", 0.7),
                "cost": self.cost.state()}

    def state(self):
        return {"session": self.session, "budget": self.budget(),
                "turns": len([m for m in self.history if m.role == "user"]),
                "messages": [message.to_openai() for message in self.history],
                "last": self.last_turn.as_dict(), "stopped": self.stopped}