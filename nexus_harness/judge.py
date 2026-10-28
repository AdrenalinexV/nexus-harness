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
from pathlib import Path

from .message import Message

# El JSON del juez se recorta ahora con `_objects` (escaneo de llaves), no con una regex codiciosa.
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


def _objects(text):
    """Todos los objetos `{...}` completos, contando llaves y respetando cadenas.

    La regex `\\{.*\\}` se comia DOS objetos cuando el modelo razonaba antes de contestar y devolvia
    `json.loads` con basura entre ellos ("the judge's JSON is malformed"), y el turno se rechazaba con
    el gate en verde. Un escaner de llaves no adivina: recorta objetos completos y elige el que parsea.
    """
    found, depth, start, quote, escape = [], 0, -1, "", False
    for index, char in enumerate(text):
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                found.append(text[start:index + 1])
    return found


def _load(candidate):
    """`json.loads` tolerante con lo que un modelo escribe de verdad: comillas curvas y comas finales."""
    cleaned = (candidate.replace("\u201c", '"').replace("\u201d", '"')
               .replace("\u2018", "'").replace("\u2019", "'"))
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    try:
        data = json.loads(cleaned)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _word(data):
    return str(data.get("verdict") or data.get("decision") or "").strip().lower()


def parse_verdict(text):
    """`(verdict, reason)` from a model answer, or `("reject", why_it_could_not_be_read)`."""
    raw = str(text or "")
    # Una respuesta que es SOLO la palabra (`Approved.`) es un veredicto, no prosa: el modelo lo dijo
    # entero. Extraerla de una frase larga seria adivinar; aqui no hay nada mas que la palabra.
    bare = raw.strip().strip(".!\"'`*_ ").lower()
    if bare in ("approve", "approved", "ok", "lgtm", "pass"):
        return "approve", "veredicto explicito sin JSON"
    if bare in ("reject", "rejected", "fail", "no"):
        return "reject", "rechazo explicito sin JSON"
    candidates = sorted(_objects(raw), key=len, reverse=True)
    for candidate in candidates:
        data = _load(candidate)
        if data is not None and _word(data):
            break
    else:
        # Sin objeto parseable, se acepta SOLO una declaracion explicita de veredicto. Extraer la
        # palabra `approve` de una frase suelta seria adivinar; exigir `"verdict": approve` no.
        loose = re.search(r"[\"']?(?:verdict|decision)[\"']?\s*[:=]\s*[\"']?"
                          r"(approve|approved|ok|pass|reject|rejected|fail|no)\b", raw, re.I)
        if not loose:
            return "reject", "the judge did not answer with JSON"
        data = {"verdict": loose.group(1),
                "reason": "veredicto leido de una respuesta con JSON roto"}
    verdict = _word(data)
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

    def review(self, goal, summary, files, gate_summary, mode=None, gate_ran=False, root=None):
        info = self.router.info("judge")
        mode = mode or mode_for(files, gate_summary, gate_ran)
        if not info.ready:
            return Judgement(verdict="skipped", ok=True, mode=mode,
                             reason="judge unavailable: %s" % (info.why_not_ready or "not configured"))
        system = (CONVERSATION if mode == "conversation" else SYSTEM)[self.lang]
        prompt = self._prompt(goal, summary, files, gate_summary, self._evidence(root, files))
        try:
            reply = self.router.role("judge").chat(
                [Message(role="system", content=system),
                 Message(role="user", content=prompt)],
                temperature=0.0, max_tokens=self.max_tokens)
        except Exception as exc:  # a judge that crashes must not fail the whole run open
            return Judgement(verdict="skipped", ok=True, mode=mode,
                             reason="judge call failed: %s: %s" % (type(exc).__name__, exc))
        verdict, reason = parse_verdict(reply.text or reply.reasoning)
        if reason == "the judge did not answer with JSON":
            # Un unico reintento con la instruccion pegada: un modelo pequeno a veces contesta prosa
            # correcta ("Approved") y no es justo condenar trabajo verde por formato. Dos fallos de
            # formato si son un rechazo, y se dice cual fue el motivo.
            verdict, reason = self._retry(system, prompt, verdict, reason)
        return Judgement(verdict=verdict, ok=(verdict != "reject"), reason=reason,
                         model=reply.model or info.model, mode=mode)

    def _retry(self, system, prompt, verdict, reason):
        """Segundo intento, solo para el fallo de formato. Devuelve `(verdict, reason)`."""
        try:
            again = self.router.role("judge").chat(
                [Message(role="system", content=system + " Responde SOLO el objeto JSON, sin nada mas."),
                 Message(role="user", content=prompt)],
                temperature=0.0, max_tokens=self.max_tokens)
        except Exception as exc:  # noqa: BLE001 -- sin reintento queda el rechazo original, declarado
            return verdict, "%s (reintento fallido: %s)" % (reason, type(exc).__name__)
        second, why = parse_verdict(again.text or again.reasoning)
        if second != "reject" or why != "the judge did not answer with JSON":
            return second, why
        return "reject", "el Juez no contesto JSON ni al segundo intento"

    def _evidence(self, root, files, limit_files=4, chars=700):
        """El contenido ACTUAL de lo tocado, recortado. Sin esto el juez opina sobre nombres.

        El fallo que arregla: un renombrado correcto fue rechazado porque el juez solo veia
        `Files touched: calc.py, main.py` y el resumen del Obrero. El gate estaba verde y el fichero
        era correcto; el juez no tenia con que comprobarlo.
        """
        if root is None or not files:
            return ""
        blocks = []
        for name in sorted(set(files or []))[:limit_files]:
            try:
                body = (Path(root) / str(name)).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            blocks.append("--- %s ---\n%s" % (name, body[:chars]))
        return "\n".join(blocks)

    def _prompt(self, goal, summary, files, gate_summary, evidence=""):
        listed = ", ".join(sorted(set(files or []))[:20]) or "(no file touched)"
        head = "Objetivo" if self.lang == "es" else "Goal"
        seen = ("Contenido actual de lo tocado (recortado):" if self.lang == "es"
                else "Current content of touched files (truncated):")
        body = ("%s:\n%s\n\nFiles touched: %s\n\nGate evidence:\n%s\n\nWork summary:\n%s"
                % (head, goal, listed, gate_summary[:1500], str(summary or "")[:MAX_SUMMARY]))
        return body + ("\n\n%s\n%s" % (seen, evidence) if evidence else "")
