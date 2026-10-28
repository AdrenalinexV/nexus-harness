"""The second client: the same core, driven from a shell.

Exit codes are the harness's own, so this is usable from a script or a CI step:

    0   green      the gate is green and the judge did not object
    10  red        the gate stayed red after the repairs it was allowed
    20  unverified the gate could not run (no Nexus, no test command it could use)
    1   the command itself failed (bad arguments, missing project)
"""
import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .bridge import Bridge
from .config import HarnessConfig
from .skill_router import library
from .events import Bus
from .gate import Gate
from .judge import judge_for
from .providers import Router, SpecError
from .session_relay import SessionRelay
from .tools import default_registry
from .cli_ops import cmd_daemon, cmd_notify, cmd_task
from .triad_loop import Triad


def _config(args):
    config = HarnessConfig.load(root=getattr(args, "project", None))
    if getattr(args, "port", None):
        config.port = int(args.port)
    if getattr(args, "test_command", None):
        config.test_command = args.test_command
    return config


def _triad(config, bus, relay=None, lang=None):
    router = Router(config)
    return Triad(router, config, registry=default_registry(config.default_root, config),
                 gate=Gate(config.default_root, config), judge=judge_for(router, config, lang or config.lang),
                 skills=library(config.default_root), bus=bus, relay=relay)


def cmd_run(args):
    config = _config(args)
    if not config.default_root.is_dir():
        print("project not found: %s" % config.default_root)
        return 1
    bus = Bus()
    relay = SessionRelay(config.default_root, goal=args.goal, config=config, bus=bus)
    relay.start()
    triad = _triad(config, bus, relay)
    result = triad.run(args.goal, max_repairs=args.max_repairs)
    if args.json:
        print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
    else:
        print("goal      : %s" % result.goal)
        print("root      : %s" % config.default_root)
        print("gate      : exit %s · %s" % (result.verdict.get("exit"),
                                           ", ".join("%s=%s" % (c["name"], c["ok"])
                                                     for c in result.verdict.get("checks", []))))
        print("judge     : %s %s" % (result.judgement.get("verdict", "?"),
                                     result.judgement.get("reason", "")[:120]))
        print("steps     : %d · repairs: %d · sessions: %s"
              % (result.steps, result.repairs, ", ".join(result.sessions) or "-"))
        print("touched   : %s" % (", ".join(result.touched) or "-"))
        print("summary   : %s" % (result.summary or "-")[:300])
        print("verdict   : %s" % ("GREEN" if result.ok else "RED"))
    return result.exit


def cmd_serve(args):
    from . import sidecar
    from .cockpit import Cockpit
    from .ui import serve
    config = _config(args)
    # A shell-launched engine leaves when the shell does; a CLI `serve` (no token) keeps running.
    sidecar.arm_if_sidecar()
    serve(Cockpit(config), args.host, args.port, os.environ.get("NEXUS_HARNESS_TOKEN"))
    return 0


def cmd_chat(args):
    """One conversational turn from a shell: the same engine the window uses."""
    from .chat import Chat
    from .memory import Memory
    from .transcripts import Transcripts
    config = _config(args)
    bus = Bus()
    router = Router(config)
    chat = Chat(router, config, default_registry(config.default_root, config),
                Gate(config.default_root, config), library(config.default_root), bus=bus,
                memory=Memory(), transcripts=Transcripts(config.default_root),
                judge=judge_for(router, config))
    chat.new(args.message[:60])
    turn = chat.send(args.message)
    print(turn["reply"] or "(sin respuesta)")
    if turn.get("verdict"):
        print("[gate] exit %s · %s" % (turn["verdict"]["exit"],
                                       " ".join("%s=%s" % (check["name"], check["ok"])
                                                for check in turn["verdict"]["checks"])))
    if turn.get("judgement", {}).get("verdict"):
        print("[juez] %s: %s" % (turn["judgement"]["verdict"],
                                 turn["judgement"].get("reason", "")[:160]))
    return 0 if turn.get("exit", 0) == 0 else int(turn["exit"])


def cmd_checkpoint(args):
    """Ver y deshacer el turno: el diario vive en `<proyecto>/.nexus/checkpoints`.

    Exit codes: 0 hecho, 10 restauracion incompleta (falta una instantanea), 20 no hay diario.
    """
    from . import checkpoint
    root = Path(args.project) if args.project else HarnessConfig.load().default_root
    if args.undo is not None:
        journal = checkpoint.find(root, args.undo) if args.undo else checkpoint.latest(root)
        if journal is None:
            print("no hay turno que deshacer en %s" % checkpoint.checkpoints_dir(root))
            return 20
        report = journal.undo()
        print("undo %s: restored=%d deleted=%d skipped=%d %s"
              % (journal.name, report["restored"], report["deleted"], len(report["skipped"]),
                 report["note"]))
        for path in report["skipped"]:
            print("  - sin instantanea: %s" % path)
        return 0 if report["ok"] else 10
    rows = checkpoint.history(root)
    for journal in rows:
        row = journal.as_dict()
        print("%-24s %-16s undone=%-5s files=%d" % (row["turn"], row["label"], row["undone"],
                                                    row["files"]))
    print("turnos=%d" % len(rows))
    return 0


def cmd_selftest(args):
    from .selftests import run
    failures = run(args.suites or None)
    return 0 if not failures else 1


def cmd_lint(args):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        from nexus.checks import rules_lint
    except ImportError:
        print("could not import the Nexus linter (NEXUS_PROTOCOL?)")
        return 20
    report = rules_lint.lint_repo(str(Path(args.project or ".").resolve()))
    for finding in report["findings"]:
        print("%s %s:%s %s" % (finding["rule"], finding["file"], finding["line"],
                               finding["detail"]))
    print("files=%d findings=%d" % (report["files_scanned"], len(report["findings"])))
    return 0 if not report["findings"] else 10


def cmd_models(args):
    config = _config(args)
    router = Router(config)
    catalog = router.catalog()
    print("roles:")
    for role, info in catalog["roles"].items():
        print("  %-9s %-70s %s" % (role, info["spec"],
                                   "ready" if info["ready"] else info["why_not_ready"]))
    print("cloud ready: %s" % (", ".join(catalog["cloud_ready"]) or "none"))
    for vendor, models in catalog["local"].items():
        print("%s: %d models%s" % (vendor, len(models), (" -- " + ", ".join(models[:4]))
                                   if models else " (unreachable)"))
    return 0


def cmd_gate(args):
    config = _config(args)
    verdict = Gate(config.default_root, config).run(args.touched or [])
    for check in verdict.checks:
        print("%-9s %s  %s" % (check.name, "OK " if check.ok else "RED",
                               check.detail.splitlines()[0][:160]))
    if verdict.failures:
        print("\n" + verdict.failures[:2000])
    print("gate: exit %s" % verdict.exit)
    return verdict.exit


def cmd_spec(args):
    """Objetivo -> criterios ejecutables, validados hoy. Sin `--write` es un plan en seco."""
    from .providers import Router
    from .spec_synth import synthesize

    config = _config(args)
    router = Router(config) if getattr(args, "model", False) else None
    result = synthesize(config.default_root, args.goal, config=config, router=router,
                       write=bool(args.write), force=bool(args.force))
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        for row in result["rows"]:
            print("%-4s %-9s %s" % ("ok" if row["ok"] else "GAP",
                                    "exit %s" % (row["exit"] if row["exit"] is not None else "?"),
                                    row["title"]))
            print("     $ %s" % row["command"])
        for row in result["dropped"]:
            print("descartado: %s (%s)" % (row["title"], row["detail"]))
        print("spec: %s%s%s" % ("accionable" if result["actionable"] else "ya cumplida",
                                " · escrita en %s" % result.get("path") if result["written"] else "",
                                (" · " + result["reason"]) if result["reason"] else ""))
    if not result["ok"]:
        return 20
    return 0 if result["actionable"] or result["written"] else 10


def cmd_relay(args):
    config = _config(args)
    root = config.default_root
    try:
        from nexus.hive import relay
    except ImportError:
        print("nexus relay not importable")
        return 20
    status = relay.status(str(root))
    print(json.dumps(status, indent=2, ensure_ascii=False))
    if args.handover:
        bus = Bus()
        session = SessionRelay(root, goal=args.goal or "continuar", config=config, bus=bus)
        session.start()
        handover = session.hand_over(reason="manual")
        print("handover: %s -> %s (%s)" % (handover.from_session, handover.to_session,
                                           handover.prompt_path))
    return 0


def cmd_bridge(args):
    config = _config(args)
    bridge = Bridge(config.workspace, bus=Bus())
    pending = bridge.pending()
    print("workspace : %s" % config.workspace)
    print("pending   : %d" % len(pending))
    for item in pending:
        print("  - %s :: %s" % (item["project"], str(item["criterion"])[:80]))
    if not args.tick:
        return 0
    rows = bridge.tick(lambda goal, root: _triad(replace_root(config, root), Bus())
                       .run(goal).exit)
    for row in rows:
        print("ran %s -> exit %s" % (row.get("project"), row.get("exit")))
    return 0 if all(row.get("exit") == 0 for row in rows) else 10


def replace_root(config, root):
    from dataclasses import replace
    return replace(config, default_root=Path(root))


def build_parser():
    parser = argparse.ArgumentParser(prog="nexus_harness",
                                     description="Nexus-Harness: autonomous engineering with the "
                                                 "Nexus Protocol as the turn loop")
    parser.add_argument("--version", action="version", version="nexus-harness %s" % __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the triad on a goal")
    run.add_argument("goal")
    run.add_argument("--project", default=None)
    run.add_argument("--max-repairs", type=int, default=None)
    run.add_argument("--test-command", default=None,
                     help="the project's own proof command; absent means 'not configured'")
    run.add_argument("--json", action="store_true")
    run.set_defaults(func=cmd_run)

    serve = sub.add_parser("serve", help="start the cockpit")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--project", default=None)
    serve.set_defaults(func=cmd_serve)

    chat = sub.add_parser("chat", help="one conversational turn")
    chat.add_argument("message")
    chat.add_argument("--project", default=None)
    chat.add_argument("--test-command", default=None)
    chat.set_defaults(func=cmd_chat)

    checkpoint = sub.add_parser("checkpoint", help="el diario del turno: ver y deshacer")
    checkpoint.add_argument("--project", default=None)
    checkpoint.add_argument("--undo", nargs="?", const="", default=None,
                            help="deshacer el ultimo turno (o el que se nombre)")
    checkpoint.set_defaults(func=cmd_checkpoint)

    selftest = sub.add_parser("selftest", help="run the deterministic suites")
    selftest.add_argument("suites", nargs="*")
    selftest.set_defaults(func=cmd_selftest)

    lint = sub.add_parser("lint", help="the line law, via the Nexus linter")
    lint.add_argument("--project", default=None)
    lint.set_defaults(func=cmd_lint)

    models = sub.add_parser("models", help="which local models are reachable")
    models.add_argument("--project", default=None)
    models.set_defaults(func=cmd_models)

    gate = sub.add_parser("gate", help="run the gate once")
    gate.add_argument("--project", default=None)
    gate.add_argument("--test-command", default=None)
    gate.add_argument("--touched", nargs="*", default=[])
    gate.set_defaults(func=cmd_gate)

    relay = sub.add_parser("relay", help="the protocol's relay state")
    relay.add_argument("--project", default=None)
    relay.add_argument("--handover", action="store_true")
    relay.add_argument("--goal", default="")
    relay.set_defaults(func=cmd_relay)

    spec = sub.add_parser("spec", help="objetivo -> criterios ejecutables (plan en seco)")
    spec.add_argument("goal")
    spec.add_argument("--project", default=None)
    spec.add_argument("--write", action="store_true", help="congela la spec en .ai/CURRENT_SPEC.json")
    spec.add_argument("--force", action="store_true", help="congela aunque todo pase ya")
    spec.add_argument("--model", action="store_true", help="el Director propone criterios")
    spec.add_argument("--json", action="store_true")
    spec.set_defaults(func=cmd_spec)

    daemon = sub.add_parser("daemon", help="trabajo autonomo en bucle")
    daemon.add_argument("--once", action="store_true", help="un solo tick (para cron)")
    daemon.add_argument("--interval", type=int, default=None)
    daemon.add_argument("--iterations", type=int, default=None)
    daemon.add_argument("--rounds", type=int, default=None)
    daemon.add_argument("--project", default=None)
    daemon.add_argument("--json", action="store_true")
    daemon.set_defaults(func=cmd_daemon)

    task = sub.add_parser("task", help="bandeja de tareas del daemon")
    task.add_argument("action", choices=["add", "list", "done", "release"])
    task.add_argument("goal", nargs="?", default="")
    task.add_argument("--project", default=None)
    task.add_argument("--id", default=None)
    task.add_argument("--exit", type=int, default=0, dest="exit_code")
    task.add_argument("--note", default="")
    task.add_argument("--json", action="store_true")
    task.set_defaults(func=cmd_task)

    notify = sub.add_parser("notify", help="manda un aviso de prueba a los canales")
    notify.add_argument("text")
    notify.add_argument("--json", action="store_true")
    notify.set_defaults(func=cmd_notify)

    bridge = sub.add_parser("bridge", help="the mobile queue (.nexus/hive/queue.json)")
    bridge.add_argument("--tick", action="store_true", help="claim and run one item")
    bridge.add_argument("--project", default=None)
    bridge.set_defaults(func=cmd_bridge)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except SpecError as exc:
        print("model spec: %s" % exc)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
