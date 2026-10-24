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
from dataclasses import dataclass, field

from .message import Message, as_text
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

    def as_dict(self):
        return {"reply": self.reply, "exit": self.exit, "steps": self.steps,
                "repairs": self.repairs, "touched": self.touched, "skills": self.skills,
                "verdict": self.verdict, "judgement": self.judgement, "stopped": self.stopped}


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
        self.used = 0
        self.children = []
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
        facts = "## Proyecto\n\nraíz: %s" % getattr(self.config, "default_root", ".")
        test = getattr(self.config, "test_command", None)
        facts += "\ntests: %s" % (test or "no configurado")
        parts.append(facts)
        return "\n\n".join(parts)

    # -- the loop ----------------------------------------------------------------------------
    def _turn(self, tools=True, max_steps=None):
        """Model calls until it stops asking for tools. Returns (text, steps)."""
        text, steps = "", 0
        for step in range(int(max_steps or self.config.max_steps)):
            if self._stop.is_set():
                return text, steps
            messages = [Message(role="system", content=self._system(self.touched))] + self.history
            reply = self.router.role("worker").chat(
                messages, tools=self.registry.schemas() if tools else None,
                temperature=self.config.temperature, max_tokens=self.config.max_tokens)
            steps += 1
            self.used += int(getattr(reply.usage, "total", 0) or 0)
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

    def _dispatch(self, calls):
        """Run the model's tool calls: read-only ones together, everything else in order."""
        calls = list(calls or [])
        ready = [(call, index) for index, call in enumerate(calls) if not call.parse_error]
        results = {}
        if len(ready) > 1:
            self._emit("tool.parallel", "%d llamadas en paralelo" % len(ready),
                       names=[call.name for call, _ in ready])
            for observation, (_call, index) in zip(parallel_reads(self.registry, ready, self._stop),
                                                   ready):
                results[index] = observation
        elif ready:
            call, index = ready[0]
            results[index] = self.registry.call(call.name, call.arguments)
        for index, call in enumerate(calls):
            yield (index, call,
                   results.get(index) or Observation(ok=False, text="argumentos ilegibles: %s"
                                                     % call.parse_error))

    def send(self, text):
        """One operator turn. Blocking; the cockpit runs it in a thread and streams events."""
        text = str(text or "").strip()
        if not text:
            return Turn(reply="", exit=0).as_dict()
        if self.session is None:
            self.new(text[:60])
        self._stop.clear()
        self._emit("chat.user", text[:1500])
        self.history.append(Message(role="user", content=text))
        turn = Turn()
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
        injection = getattr(self.skills, "last", None)
        turn.skills = list(getattr(injection, "names", []) or [])
        self.last_turn = turn
        self._persist(turn)
        self._emit("chat.turn", "exit %s" % turn.exit, turn=turn.as_dict())
        return turn.as_dict()

    def _persist(self, turn):
        if self.transcripts is None or self.session is None:
            return
        self.session["messages"] = [message.to_openai() for message in self.history]
        self.session["turns"] = int(self.session.get("turns", 0)) + 1
        self.session["exit"] = turn.exit
        if not self.session.get("title"):
            self.session["title"] = next((message.content for message in self.history
                                          if message.role == "user"), "")[:90]
        self.transcripts.save(self.session)

    def budget(self):
        limit = int(getattr(self.config, "budget_limit", 0) or 0)
        state = "unmeasured" if not limit else "measured"
        return {"used": self.used, "limit": limit, "ratio": (self.used / limit) if limit else None,
                "state": state, "threshold": getattr(self.config, "relay_threshold", 0.7)}

    def state(self):
        return {"session": self.session, "budget": self.budget(),
                "turns": len([m for m in self.history if m.role == "user"]),
                "messages": [message.to_openai() for message in self.history],
                "last": self.last_turn.as_dict(), "stopped": self.stopped}
