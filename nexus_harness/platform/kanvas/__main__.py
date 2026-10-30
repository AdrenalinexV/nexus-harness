"""CLI del tablero, para agentes de fuera y para el operador desde una terminal.

    python -m nexus_harness.platform.kanvas status --root .
    python -m nexus_harness.platform.kanvas claim TK-11 --root .
    python -m nexus_harness.platform.kanvas submit TK-11 --commits abc123 --gate 0
    python -m nexus_harness.platform.kanvas yolo TK-11 --chain

Las mismas reglas que la herramienta del modelo y que la cabina: aquí no hay puerta trasera. `approve`
existe en el CLI porque quien lo escribe es el operador.
"""
import argparse
import json
import sys

from .board import Board, KanvasError


def main(argv=None):
    parser = argparse.ArgumentParser(prog="kanvas", description="Tablero de tareas del proyecto")
    parser.add_argument("action", nargs="?", default="status",
                        choices=("status", "claim", "submit", "approve", "back", "yolo", "note"))
    parser.add_argument("task", nargs="?", default="")
    parser.add_argument("--root", default=".")
    parser.add_argument("--commits", default="")
    parser.add_argument("--gate", type=int, default=0)
    parser.add_argument("--judge", default="")
    parser.add_argument("--text", default="")
    parser.add_argument("--chain", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    board = Board.load(args.root)
    commits = [item.strip() for item in args.commits.replace(",", " ").split() if item.strip()]
    try:
        if args.action == "status":
            print(json.dumps(board.as_dict(), ensure_ascii=False, indent=2) if args.json
                  else _summary(board))
            return 0
        if args.action == "claim":
            board.claim(args.task)
        elif args.action == "submit":
            board.submit(args.task, commits=commits, gate=args.gate, judge=args.judge)
        elif args.action == "approve":
            board.approve(args.task, by="human", judge=args.judge)
        elif args.action == "back":
            board.send_back(args.task, by="human", reason=args.text)
        elif args.action == "yolo":
            board.toggle_yolo(args.task, chain=args.chain, by="human")
        elif args.action == "note":
            board.note(args.task, args.text, by="human")
        board.save()
    except KanvasError as exc:
        print("rechazado: %s" % exc, file=sys.stderr)
        return 10
    print(_summary(board))
    return 0


def _summary(board):
    stats = board.stats()
    head = "%s: %d/%d (%d%%)" % (board.project or "tablero", stats["done"], stats["total"],
                                 stats["percent"])
    rows = ["%s [%s] %s" % (task.id, board.effective(task), task.title) for task in board.tasks]
    return "\n".join([head] + rows)


if __name__ == "__main__":
    sys.exit(main())
