"""Los comandos del trabajo autonomo: daemon, bandeja y avisos.

Viven aparte porque `cli.py` estaba en 434 lineas al anadirlos: la ley de 400 no se negocia, se parte.
Este modulo no sabe de argparse ni de config: recibe `args` ya parseados y devuelve un exit code.
"""
import json
from pathlib import Path

from .config import HarnessConfig


def _config(args):
    return HarnessConfig.load(root=getattr(args, "project", None))


def cmd_daemon(args):
    """Trabajo autonomo en bucle. `--once` es un tick (para cron); sin el, hasta Ctrl-C o rondas."""
    import threading
    from .daemon import Daemon

    config = _config(args)
    daemon = Daemon(config, interval=args.interval, iterations=args.iterations)
    if args.once:
        row = daemon.tick()
        if args.json:
            print(json.dumps(row, indent=2, sort_keys=True, ensure_ascii=False))
        else:
            print("daemon: %s%s%s" % (row.get("status"),
                                      " · %s" % (row.get("project") or row.get("task") or ""),
                                      (" · " + row["note"]) if row.get("note") else ""))
        return 0 if row.get("ok") or row.get("status") in ("sin trabajo", "ya verde",
                                                           "spec congelada") else 10
    stop = threading.Event()
    try:
        outcome = daemon.run(stop=stop, rounds=args.rounds)
    except KeyboardInterrupt:
        stop.set()
        outcome = {"ok": True, "rounds": daemon.rounds, "stopped": True}
    print("daemon: %s rondas%s" % (outcome.get("rounds"), " (parado)" if outcome.get("stopped") else ""))
    return 0 if outcome.get("ok") else 10


def cmd_task(args):
    """La bandeja: lo que un bot, un cron o una persona dejan para el daemon."""
    from .tasks import Inbox

    config = _config(args)
    inbox = Inbox(Path(config.workspace))
    if args.action == "add":
        row = inbox.add(args.project or "", args.goal, source="cli")
        print(json.dumps(row, sort_keys=True, ensure_ascii=False) if args.json
              else ("tarea %s encolada" % row.get("id") if row.get("ok")
                    else "no se pudo: %s" % row.get("reason")))
        return 0 if row.get("ok") else 1
    if args.action == "list":
        status = inbox.status()
        print(json.dumps(status, indent=2, sort_keys=True, ensure_ascii=False) if args.json
              else "abiertas: %d · %s" % (status["counts"]["queued"] + status["counts"]["claimed"],
                                          ", ".join(one["goal"][:60] for one in status["open"])
                                          or "(nada)"))
        return 0
    if not args.id:
        print("hace falta --id")
        return 1
    row = inbox.close(args.id, args.exit_code, args.note or "") if args.action == "done"         else inbox.release(args.id, args.note or "")
    print(json.dumps(row, sort_keys=True, ensure_ascii=False) if args.json
          else ("%s: %s" % (args.id, "cerrada" if row else "no encontrada")))
    return 0 if row else 1


def cmd_notify(args):
    """Un aviso de prueba: comprueba los canales sin esperar a que el daemon tenga trabajo."""
    from .notify import Notifier

    rows = Notifier(config=_config(args)).send(args.text, "test")
    if args.json:
        print(json.dumps(rows, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        for row in rows:
            print("%-8s %s  %s" % (row["channel"], "OK" if row["ok"] else "FAIL", row["detail"]))
        if not rows:
            print("sin canales declarados en `notify` (~/.nexus/harness.json)")
    return 0 if rows and all(row["ok"] for row in rows) else 10


