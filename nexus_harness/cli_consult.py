"""`nexus-harness consult`: preguntar al operador desde una terminal, un cron o un bot.

Vive aparte porque `cli.py` no puede crecer: la ley de 400 no se negocia, se parte. Aqui no hay
argparse ni config: entran `args` ya parseados y sale un exit code.
"""
import json

from . import consult, consult_channels
from .config import HarnessConfig


def _config(args):
    return HarnessConfig.load(root=getattr(args, "project", None))


def _print_questions(rows):
    if not rows:
        print("consult: no hay preguntas abiertas")
        return 0
    for row in rows:
        print("%s  %s  %s" % (row.get("id"), row.get("at"), (row.get("text") or "")[:90]))
        for index, option in enumerate(row.get("options") or [], 1):
            print("     %d) %s" % (index, option))
        print("     plazo agotado en: %s min · defecto: %s"
              % (max(0, int(row.get("deadline_s") or 0) // 60), row.get("default") or "parar"))
    return 0


def cmd_consult(args):
    """Cuatro formas: preguntar, ver lo abierto, contestar, o medir los canales."""
    config = _config(args)
    root = config.default_root
    if args.answer:
        result = consult.answer(root, args.answer, args.text or "", "cli")
        print(json.dumps(result, ensure_ascii=False) if args.json
              else ("consult: %s" % ("contestada" if result.get("ok") else result.get("reason"))))
        return 0 if result.get("ok") else 1
    if args.check:
        found = consult_channels.channels(config)
        if args.json:
            print(json.dumps(found, indent=2, ensure_ascii=False))
        else:
            for channel in found:
                print("%-9s escribe=%s escucha=%s" % (channel.get("kind"), bool(channel.get("url")),
                                                      "si" if channel.get("readable") else "no"))
            if not found:
                print("consult: ningun canal declarado (notify en ~/.nexus/harness.json)")
        return 0
    if args.status or not (args.text or args.options):
        return _print_questions(consult.pending(root))

    options = [item.strip() for item in str(args.options or "").split(",") if item.strip()]
    outcome = consult_channels.ask_operator(root, config, args.text, options,
                                            args.default or "parar", config.default_root.name,
                                            deadline_s=int(args.wait or consult.DEFAULT_DEADLINE))
    if args.json:
        print(json.dumps(outcome, indent=2, ensure_ascii=False))
    else:
        print("consult: %s · respuesta: %s (%s)" % (outcome.get("state"), outcome.get("answer"),
                                                    outcome.get("source")))
    return 0 if outcome.get("state") == "answered" else 0
