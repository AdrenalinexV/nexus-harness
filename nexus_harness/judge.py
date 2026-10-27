"""The judge: a second model, asked one question, allowed to answer in one word.

Rules that make it a judge and not a cheerleader:

* **It runs only after the gate is green.** A model's opinion about broken code is noise.
* **It sees the goal, the gate's evidence and the diff summary** -- not the worker's self-report
  alone, because the worker is the party on trial.
* **An unparsable verdict is a rejection.** "I could not tell" is not an approval, and a judge that
  fails open is a rubber stamp with a token bill.
* **A judge that is not configured is `skipped`**, and the run says so instead of inventing consent.

The default judge model is deliberately different from the worker's: in `config.py`, `judge` points at
the reasoning model, not the coder, so the same weights do not grade their own edit.
"""
import json
import re
from dataclasses import dataclass

from .message import Message

JSON_BLOCK = re.compile(r"\{.*\}", re.S)
MAX_SUMMARY = 2500

SYSTEM = {
    "es": ("Eres el Juez de un harness de ingeniería. Recibes un objetivo, la evidencia del gate "
           "(lint, ley de 400 líneas, tests) y el resumen del trabajo. Decides si el trabajo "
           "responde al objetivo SIN inventar nada. Responde SOLO con un objeto JSON: "
           '{"verdict": "approve" | "reject", "reason": "<una frase>"}. '
           "Rechaza si el trabajo no toca lo que el objetivo pedía, si el resumen promete en vez de "
           "demostrar, o si la evidencia no cubre el objetivo. No apruebes por cortesía."),
    "en": ("You are the judge of an engineering harness. You receive a goal, the gate's evidence "
           "(lint, the 400-line law, tests) and a summary of the work. Decide whether the work "
           "answers the goal WITHOUT inventing anything. Answer ONLY with a JSON object: "
           '{"verdict": "approve" | "reject", "reason": "<one sentence>"}. '
           "Reject when the work does not touch what the goal asked for, when the summary promises "
           "instead of demonstrating, or when the evidence does not cover the goal."),
}


CONVERSATION = {
    "es": ("Eres el Juez de un harness de ingeniería. Este turno NO tocó ficheros: es una consulta o "
           "una conversación. Evalúa si la respuesta es ÚTIL, correcta y responde a lo que se preguntó. "
           "NO la rechaces por no haber editado nada: en un turno de solo lectura no editar es lo "
           'correcto. Responde SOLO con JSON: {"verdict": "approve" | "reject", "reason": "<una frase>"}.'),
    "en": ("You are the judge of an engineering harness. This turn touched NO files: it is a question "
           "or a conversation. Judge whether the answer is USEFUL, correct and answers what was asked. "
           "Do NOT reject it for not editing anything: in a read-only turn, not editing is correct. "
           'Answer ONLY with JSON: {"verdict": "approve" | "reject", "reason": "<one sentence>"}.'),
}


def mode_for(files, gate_summary="", gate_ran=False):
    """`conversation` o `code`, decidido con hechos: ficheros tocados y gate ejecutado.

    Es la diferencia que evita el fallo mas caro de un juez: rechazar una respuesta correcta a una
    pregunta porque "no hay diff". Sin ficheros y sin gate no hay nada que aprobar en codigo, y exigir
    edicion convertiria cada consulta en un rojo.
    """
    if list(files or ()) or gate_ran:
        return "code"
    text = str(gate_summary or "").strip().lower()
    if text and "no gate" not in text and "no se ejecuto" not in text:
        return "code"
    return "conversation"


@dataclass
class Judgement:
    verdict: str = "skipped"
    ok: bool = True
    reason: str = ""
    model: str = ""
    mode: str = "code"

    def as_dict(self):
        return {"verdict": self.verdict, "ok": self.ok, "reason": self.reason,
                "model": self.model, "mode": self.mode}


def parse_verdict(text):
    """`(verdict, reason)` from a model answer, or `("reject", why_it_could_not_be_read)`."""
    match = JSON_BLOCK.search(str(text or ""))
    if not match:
        return "reject", "the judge did not answer with JSON"
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return "reject", "the judge's JSON is malformed"
    verdict = str(data.get("verdict") or data.get("decision") or "").strip().lower()
    reason = str(data.get("reason") or data.get("why") or "").strip()[:400]
    if verdict in ("approve", "approved", "ok", "pass"):
        return "approve", reason or "approved"
    if verdict in ("reject", "rejected", "fail", "no"):
        return "reject", reason or "rejected"
    return "reject", "the judge's verdict is not approve/reject (%r)" % verdict[:40]


class Judge:
    def __init__(self, router, lang="es", max_tokens=400):
        self.router = router
        self.lang = lang if lang in SYSTEM else "en"
        self.max_tokens = max_tokens

    def review(self, goal, summary, files, gate_summary, mode=None, gate_ran=False):
        info = self.router.info("judge")
        mode = mode or mode_for(files, gate_summary, gate_ran)
        if not info.ready:
            return Judgement(verdict="skipped", ok=True, mode=mode,
                             reason="judge unavailable: %s" % (info.why_not_ready or "not configured"))
        system = (CONVERSATION if mode == "conversation" else SYSTEM)[self.lang]
        prompt = self._prompt(goal, summary, files, gate_summary)
        try:
            reply = self.router.role("judge").chat(
                [Message(role="system", content=system),
                 Message(role="user", content=prompt)],
                temperature=0.0, max_tokens=self.max_tokens)
        except Exception as exc:  # a judge that crashes must not fail the whole run open
            return Judgement(verdict="skipped", ok=True, mode=mode,
                             reason="judge call failed: %s: %s" % (type(exc).__name__, exc))
        verdict, reason = parse_verdict(reply.text or reply.reasoning)
        return Judgement(verdict=verdict, ok=(verdict != "reject"), reason=reason,
                         model=reply.model or info.model, mode=mode)

    def _prompt(self, goal, summary, files, gate_summary):
        listed = ", ".join(sorted(set(files or []))[:20]) or "(no file touched)"
        head = "Objetivo" if self.lang == "es" else "Goal"
        return ("%s:\n%s\n\nFiles touched: %s\n\nGate evidence:\n%s\n\nWork summary:\n%s"
                % (head, goal, listed, gate_summary[:1500],
                   str(summary or "")[:MAX_SUMMARY]))
