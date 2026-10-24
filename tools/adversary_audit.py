"""Adversarial audit: hand the modules to a second model and ask it for defects, not praise.

This is the one check in the project that needs a model, so it says out loud what it did:

    python tools/adversary_audit.py nexus_harness/triad_loop.py nexus_harness/ui.py

It prints a JSON list of findings per file, never edits anything, and returns `20` when the reviewer
cannot be reached -- "could not verify" is a result, and a green-looking audit that never ran is not.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus_harness.config import HarnessConfig  # noqa: E402
from nexus_harness.message import Message  # noqa: E402
from nexus_harness.providers import Router, SpecError  # noqa: E402

SYSTEM = """Eres un auditor adversarial de código Python. Te dan UN módulo y su contrato.

Devuelve SOLO un array JSON de defectos reales, cada uno:
{"severity": "alta"|"media"|"baja", "where": "<función o línea>", "what": "<el defecto>",
 "why": "<qué se rompe en producción>", "fix": "<el cambio concreto>"}

Reglas:
- Solo defectos que puedas señalar en el código que ves. Nada de estilo, nada de "considera añadir".
- Si el módulo no tiene defectos reales, devuelve [].
- Prohibido inventar: si no estás seguro, no lo incluyas.
- Máximo 6 hallazgos, los más graves primero."""

MAX_CHARS = 18000


def audit(router, path, spec_role="worker"):
    source = Path(path).read_text(encoding="utf-8")[:MAX_CHARS]
    prompt = ("MÓDULO: %s (%d líneas en disco)\n\n```python\n%s\n```\n\n"
              "Recuerda: solo defectos reales, en JSON." % (path, source.count("\n") + 1, source))
    reply = router.role(spec_role).chat(
        [Message(role="system", content=SYSTEM), Message(role="user", content=prompt)],
        temperature=0.1, max_tokens=2000)
    return reply.text or reply.reasoning, reply


def parse(text):
    """The JSON array inside an answer, or `None` when the model did not keep its side."""
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def main(argv=None):
    parser = argparse.ArgumentParser(prog="adversary_audit")
    parser.add_argument("files", nargs="*", default=["nexus_harness/triad_loop.py",
                                                     "nexus_harness/session_relay.py",
                                                     "nexus_harness/ui.py"])
    parser.add_argument("--role", default="worker")
    args = parser.parse_args(argv)
    config = HarnessConfig.load(root=ROOT)
    router = Router(config)
    info = router.info(args.role)
    if not info.ready:
        print(json.dumps({"ok": False, "reason": "reviewer not available: %s" % info.why_not_ready}))
        return 20
    print(json.dumps({"reviewer": info.model, "files": args.files}))
    findings_total = 0
    for name in args.files:
        try:
            text, reply = audit(router, name, args.role)
        except (SpecError, OSError) as exc:
            print(json.dumps({"file": name, "ok": False, "reason": str(exc)}))
            continue
        except Exception as exc:  # a transport failure is reported, never swallowed
            print(json.dumps({"file": name, "ok": False,
                              "reason": "%s: %s" % (type(exc).__name__, exc)}))
            findings_total += 1
            continue
        rows = parse(text)
        print(json.dumps({"file": name, "ok": rows is not None, "verdict": rows,
                          "raw": None if rows is not None else text[:600],
                          "usage": reply.usage.total}, ensure_ascii=False))
        findings_total += len(rows or [])
    return 0 if findings_total == 0 else 10


if __name__ == "__main__":
    sys.exit(main())
