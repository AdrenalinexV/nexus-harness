"""La maquina de estados del turno de noche: una rubrica, una prueba por criterio, cero opinion.

El problema que resuelve es el de siempre con un agente autonomo: decir "ya esta" sin que nadie lo
compruebe. Aqui un criterio no tiene estado propio: tiene **un comando** y su exit code. `check` corre
ese comando, guarda lo que salio y decide. `next` devuelve exactamente **un** criterio pendiente, para
que la iteracion sea profunda y no un barrido de titulares.

    python tools/nightshift.py init                 # crea el estado desde la rubrica (idempotente)
    python tools/nightshift.py status [--json]      # donde estamos
    python tools/nightshift.py next   [--json]      # que toca ahora (uno solo)
    python tools/nightshift.py check <id>           # corre SU prueba y guarda el veredicto
    python tools/nightshift.py mark  <id> blocked --note "..."
    python tools/nightshift.py report [--check]     # escribe/valida docs/NIGHT_REPORT.md
    python tools/nightshift.py install --check      # el instalador deja un motor verificable

Codigos de salida, los del protocolo donde tiene sentido: `0` verde (criterio cumplido o comando ok),
`10` rojo (la prueba fallo), `20` no verificable (falta el artefacto o el comando no existe).
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUBRIC = ROOT / ".ai" / "HARNESS_RUBRIC.json"
STATE = ROOT / ".ai" / "HARNESS_STATE.json"
REPORT = ROOT / "docs" / "NIGHT_REPORT.md"
INSTALLER = ROOT / "dist" / "NexusHarness-Setup-0.3.0.exe"
PROOF_TIMEOUT = 900
STATUSES = ("unmet", "met", "blocked")


# -- estado ----------------------------------------------------------------------------------
def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def head():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), text=True,
                              capture_output=True, timeout=20).stdout.strip() or "no-git"
    except (OSError, subprocess.SubprocessError):
        return "no-git"


def load_rubric():
    data = json.loads(RUBRIC.read_text(encoding="utf-8"))
    criteria = data.get("criteria") or []
    ids = [row["id"] for row in criteria]
    if len(ids) != len(set(ids)):
        raise ValueError("la rubrica repite ids")
    for row in criteria:
        for key in ("id", "title", "proof", "priority"):
            if not row.get(key):
                raise ValueError("criterio sin %s: %r" % (key, row.get("id")))
    return data


def load_state():
    if not STATE.is_file():
        raise SystemExit("no hay estado: ejecuta `python tools/nightshift.py init`")
    return json.loads(STATE.read_text(encoding="utf-8"))


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_name(".HARNESS_STATE.json.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(STATE)
    return state


def ordered(rubric):
    return sorted(rubric["criteria"], key=lambda row: (int(row["priority"]), row["id"]))


def entry(state, cid):
    return state["criteria"].setdefault(
        cid, {"status": "unmet", "attempts": 0, "note": "", "last": {}})


# -- pruebas ---------------------------------------------------------------------------------
def run_proof(criterion, timeout=PROOF_TIMEOUT):
    """Corre el comando del criterio y devuelve `{exit, ok, tail, at, head, command}`."""
    command = str(criterion["proof"])
    try:
        # shell=True es el contrato: el comando lo escribe el operador en .ai/HARNESS_RUBRIC.json
        # (un fichero del repositorio, versionado), no un modelo ni una pagina web.
        completed = subprocess.run(command, cwd=str(ROOT), shell=True, capture_output=True,
                                   text=True, errors="replace", timeout=timeout)
        code = completed.returncode
        output = ((completed.stdout or "") + (completed.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        code, output = 124, "timeout tras %ss" % timeout
    except OSError as exc:
        code, output = 127, "no se pudo ejecutar: %s" % exc
    wanted = criterion.get("contains")
    ok = code == 0 and (wanted is None or wanted in output)
    return {"exit": code, "ok": ok, "tail": output[-1200:], "at": now(), "head": head(),
            "command": command}


# -- comandos --------------------------------------------------------------------------------
def cmd_init(args):
    rubric = load_rubric()
    state = load_state() if STATE.is_file() and not args.force else {
        "version": 1, "iteration": 0, "started": now(),
        "rubric_version": rubric.get("version", 1), "criteria": {}, "history": []}
    for row in rubric["criteria"]:
        slot = state["criteria"].setdefault(row["id"], {})
        slot.setdefault("status", "unmet")
        slot.setdefault("attempts", 0)
        slot.setdefault("note", "")
        slot.setdefault("last", {})
    save_state(state)
    print("estado listo: %d criterios (%d pendientes)" % (
        len(state["criteria"]), sum(1 for row in state["criteria"].values()
                                    if row["status"] != "met")))
    return 0


def cmd_status(args):
    rubric = load_rubric()
    state = load_state()
    rows = []
    for row in ordered(rubric):
        slot = entry(state, row["id"])
        rows.append({"id": row["id"], "area": row.get("area", ""), "status": slot["status"],
                     "attempts": slot["attempts"], "exit": (slot.get("last") or {}).get("exit"),
                     "title": row["title"]})
    if args.json:
        print(json.dumps({"iteration": state.get("iteration", 0), "criteria": rows}, indent=2,
                         ensure_ascii=False))
        return 0
    done = sum(1 for row in rows if row["status"] == "met")
    for row in rows:
        mark = {"met": "OK  ", "blocked": "BLOQ", "unmet": "---- "}[row["status"]]
        print("%s %-20s %-12s exit=%-4s %s" % (mark, row["id"], row["area"], row["exit"] or "-",
                                               row["title"][:64]))
    print("cumplidos %d/%d · iteracion %s" % (done, len(rows), state.get("iteration", 0)))
    return 0


def cmd_next(args):
    rubric = load_rubric()
    state = load_state()
    for row in ordered(rubric):
        slot = entry(state, row["id"])
        if slot["status"] != "met":
            payload = {"id": row["id"], "title": row["title"], "area": row.get("area", ""),
                       "why": row.get("why", ""), "proof": row["proof"],
                       "contains": row.get("contains"), "status": slot["status"],
                       "attempts": slot["attempts"], "note": slot.get("note", "")}
            print(json.dumps(payload, indent=2, ensure_ascii=False) if args.json
                  else "TOCA: %s — %s\n  prueba: %s\n  estado: %s (intentos %s)" % (
                      row["id"], row["title"], row["proof"], slot["status"], slot["attempts"]))
            return 0
    print("nada pendiente: todos los criterios estan en verde" if not args.json
          else json.dumps({"done": True}, indent=2))
    return 0


def cmd_check(args):
    rubric = load_rubric()
    state = load_state()
    criterion = next((row for row in rubric["criteria"] if row["id"] == args.id), None)
    if criterion is None:
        print("criterio desconocido: %s" % args.id)
        return 20
    result = run_proof(criterion)
    slot = entry(state, args.id)
    slot["attempts"] = int(slot.get("attempts", 0)) + 1
    slot["last"] = result
    slot["status"] = "met" if result["ok"] else ("blocked" if slot["status"] == "blocked"
                                                 else "unmet")
    state["iteration"] = int(state.get("iteration", 0)) + 1
    state.setdefault("history", []).append({"at": result["at"], "id": args.id,
                                            "exit": result["exit"], "ok": result["ok"],
                                            "head": result["head"]})
    state["history"] = state["history"][-200:]
    save_state(state)
    print("%s -> exit %s (%s)\n%s" % (args.id, result["exit"],
                                      "VERDE" if result["ok"] else "ROJO", result["tail"][-600:]))
    return 0 if result["ok"] else 10


def cmd_mark(args):
    if args.status not in STATUSES:
        print("estado invalido: %s (usa %s)" % (args.status, ", ".join(STATUSES)))
        return 20
    state = load_state()
    slot = entry(state, args.id)
    slot["status"] = args.status
    if args.note:
        slot["note"] = args.note
    save_state(state)
    print("%s marcado %s" % (args.id, args.status))
    return 0


def cmd_report(args):
    rubric = load_rubric()
    state = load_state()
    rows, evidence = [], []
    for row in ordered(rubric):
        slot = entry(state, row["id"])
        last = slot.get("last") or {}
        rows.append("| `%s` | %s | %s | %s | %s |" % (
            row["id"], row.get("area", ""), row["title"],
            "OK" if slot["status"] == "met" else slot["status"],
            last.get("exit") if last.get("exit") is not None else "—"))
        if last:
            evidence.append("### %s (exit %s, %s)\n\n```\n$ %s\n%s\n```\n" % (
                row["id"], last.get("exit"), last.get("at", ""), last.get("command", ""),
                (last.get("tail") or "").strip()[-800:]))
    done = sum(1 for row in rubric["criteria"] if entry(state, row["id"])["status"] == "met")
    body = ["# Turno de noche — evidencia", "",
            "Generado por `tools/nightshift.py report` (no se escribe a mano).",
            "", "- fecha: %s" % now(), "- HEAD: `%s`" % head(),
            "- iteracion: %s" % state.get("iteration", 0),
            "- criterios: **%d/%d**" % (done, len(rubric["criteria"])), "",
            "## Rubrica", "", "| criterio | area | que se exige | estado | exit |",
            "|---|---|---|---|---|", *rows, "", "## Evidencia cruda", "", *evidence]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(body) + "\n", encoding="utf-8")
    print("escrito %s (%d/%d en verde)" % (REPORT.relative_to(ROOT), done, len(rubric["criteria"])))
    if not args.check:
        return 0
    missing = [row["id"] for row in rubric["criteria"] if row["id"] not in REPORT.read_text(
        encoding="utf-8")]
    if missing:
        print("informe incompleto, faltan: %s" % ", ".join(missing))
        return 10
    print("ok: el informe cubre los %d criterios" % len(rubric["criteria"]))
    return 0


def cmd_install(args):
    """Verifica el instalador sin instalar: existe, y el motor instalado es el del repo."""
    if not INSTALLER.is_file():
        print("no hay instalador en %s" % INSTALLER.relative_to(ROOT))
        return 20
    installed = Path(os.environ.get("LOCALAPPDATA", "")) / "Nexus Harness" / "engine" / \
        "nexus-harness-engine.exe"
    if not installed.is_file():
        print("no hay instalacion en %s" % installed)
        return 20
    def version(binary):
        completed = subprocess.run([str(binary), "--version"], capture_output=True, text=True,
                                   errors="replace", timeout=180)
        return (completed.stdout or "").strip()
    source = version(ROOT / "dist" / "nexus-harness-engine.exe")
    target = version(installed)
    print("instalador : %s (%d bytes)" % (INSTALLER.name, INSTALLER.stat().st_size))
    print("repo       : %s" % source)
    print("instalado  : %s" % target)
    if source and source == target:
        print("ok: el motor instalado es el del repositorio")
        return 0
    print("el motor instalado NO es el del repositorio (fichero en uso o instalacion vieja)")
    return 10


def selftest():
    """La maquina de estados, con una rubrica y un estado temporales: no toca los reales."""
    import tempfile

    global RUBRIC, STATE
    original = (RUBRIC, STATE)
    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    with tempfile.TemporaryDirectory(prefix="nightshift-") as workspace:
        base = Path(workspace)
        rubric, state = base / "r.json", base / "s.json"
        rubric.write_text(json.dumps({"version": 1, "criteria": [
            {"id": "a", "title": "pasa", "proof": "python -c \"print('findings=0')\"",
             "contains": "findings=0", "priority": 1, "area": "x"},
            {"id": "b", "title": "falla", "proof": "python -c \"raise SystemExit(10)\"",
             "priority": 2, "area": "x"}]}), encoding="utf-8")
        RUBRIC, STATE = rubric, state
        cmd_init(argparse.Namespace(force=True))
        check("el estado nace con dos criterios", len(load_state()["criteria"]), 2)
        check("el primero pasa", cmd_check(argparse.Namespace(id="a")), 0)
        check("y queda en verde", load_state()["criteria"]["a"]["status"], "met")
        check("el segundo falla", cmd_check(argparse.Namespace(id="b")), 10)
        check("y sigue pendiente", load_state()["criteria"]["b"]["status"], "unmet")
        check("next devuelve el pendiente", json.loads(_capture(cmd_next, argparse.Namespace(
            json=True)))["id"], "b")
        check("marcar bloqueado se guarda", cmd_mark(argparse.Namespace(
            id="b", status="blocked", note="falta el binario")), 0)
        check("y el estado lo refleja", load_state()["criteria"]["b"]["status"], "blocked")
        check("un id desconocido no rompe", cmd_check(argparse.Namespace(id="zzz")), 20)
    RUBRIC, STATE = original
    return problems


def _capture(function, args):
    import io
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        function(args)
    return buffer.getvalue()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="nightshift")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="crea el estado desde la rubrica")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)
    nxt = sub.add_parser("next")
    nxt.add_argument("--json", action="store_true")
    nxt.set_defaults(func=cmd_next)
    check_cmd = sub.add_parser("check")
    check_cmd.add_argument("id")
    check_cmd.set_defaults(func=cmd_check)
    mark = sub.add_parser("mark")
    mark.add_argument("id")
    mark.add_argument("status")
    mark.add_argument("--note", default="")
    mark.set_defaults(func=cmd_mark)
    report = sub.add_parser("report")
    report.add_argument("--check", action="store_true")
    report.set_defaults(func=cmd_report)
    install = sub.add_parser("install")
    install.add_argument("--check", action="store_true")
    install.set_defaults(func=cmd_install)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
