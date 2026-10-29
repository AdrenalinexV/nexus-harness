"""La cola de prioridad, el alta gobernada y el snapshot previo. Todo sobre carpetas de usar y tirar.

Dos cosas se prueban con cuidado, porque son las que muerden:

* **El orden se guarda de verdad.** `save_order` escribe `~/.nexus/harness.json`; aqui se apunta ese
  fichero a un temporal y se devuelve como estaba, o la suite le cambiaria la configuracion al operador.
* **Un backup que falla no deja editar.** `snapshot()` sobre un repositorio sin ni un commit devuelve
  `ok: False` con su motivo: es preferible un bucle que se para a uno que borra la tarde.
"""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .. import backup, onboarding, projects
from ..config import HarnessConfig

# `creationflags` is a Windows-only kwarg: on POSIX, Python raises ValueError even for a plain flag
# value, so the kwarg itself must be absent -- not zero. (CI measured exactly that on ubuntu.)
WINDOWS_FLAGS = {"creationflags": 0x08000000} if os.name == "nt" else {}


def check(name, got, expect, failures):
    if got != expect:
        failures.append("%s: %r, esperaba %r" % (name, got, expect))


def _git(root, *args):
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          errors="replace", **WINDOWS_FLAGS)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def _workspace(names, governed=()):
    """Un workspace falso: carpetas, y las gobernadas con su spec congelada."""
    root = Path(tempfile.mkdtemp(prefix="nexus-projects-"))
    for name in names:
        (root / name).mkdir()
        if name in governed:
            (root / name / ".ai").mkdir()
            (root / name / ".ai" / "CURRENT_SPEC.json").write_text(
                json.dumps({"format": "nexus.spec/1", "id": "spec-%s" % name.lower(),
                            "goal": "objetivo de %s" % name, "cas_count": 3,
                            "cas_sha256": "b" * 64}), encoding="utf-8")
    return root


def _config(workspace, order=None):
    return HarnessConfig(workspace=workspace, default_root=workspace, project_order=list(order or []))


def _with_temp_config(function):
    """`save_settings` escribe en el `CONFIG_FILE` del modulo: se apunta a un temporal y se restaura."""
    original = onboarding.CONFIG_FILE
    folder = tempfile.mkdtemp(prefix="nexus-config-")
    onboarding.CONFIG_FILE = Path(folder) / "harness.json"
    try:
        return function(onboarding.CONFIG_FILE)
    finally:
        onboarding.CONFIG_FILE = original
        shutil.rmtree(folder, ignore_errors=True)


def test_order(failures):
    root = _workspace(["Gamma", "Alpha", "Beta", "Suelta"], governed=("Alpha", "Beta", "Gamma"))
    try:
        config = _config(root, ["Gamma", "Alpha"])
        check("governed only, declared first", projects.order(config), ["Gamma", "Alpha", "Beta"],
              failures)
        check("a plain folder is not in the queue", "Suelta" in projects.order(config), False, failures)
        check("and is listed as plain", projects.plain(root), ["Suelta"], failures)
        check("a declared name that no longer exists is ignored",
              projects.order(_config(root, ["Fantasma", "Beta"])), ["Beta", "Alpha", "Gamma"], failures)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_save_order(failures):
    root = _workspace(["Alpha", "Beta", "Gamma"], governed=("Alpha", "Beta", "Gamma"))
    try:
        def exercise(config_file):
            config = _config(root)
            saved, notes = projects.save_order(config, ["Gamma", "Alpha", "Beta"])
            check("the order is accepted", saved, ["Gamma", "Alpha", "Beta"], failures)
            check("with no complaints", notes, [], failures)
            written = json.loads(config_file.read_text(encoding="utf-8"))
            check("it is on disk", written.get("project_order"), ["Gamma", "Alpha", "Beta"], failures)
            reloaded = HarnessConfig.load(path=config_file, root=root)
            check("and survives a reload", reloaded.project_order, ["Gamma", "Alpha", "Beta"], failures)
            dropped, warnings = projects.save_order(config, ["Alpha", "NoExiste"])
            check("one that is not a project is not saved, but the real queue stays complete",
                  dropped, ["Alpha", "Beta", "Gamma"], failures)
            check("and it says what fell out", any("NoExiste" in note for note in warnings), True,
                  failures)
        _with_temp_config(exercise)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_move(failures):
    root = _workspace(["Alpha", "Beta", "Gamma"], governed=("Alpha", "Beta", "Gamma"))
    try:
        def exercise(_config_file):
            config = _config(root, ["Alpha", "Beta", "Gamma"])
            order, note = projects.move(config, "Gamma", "up")
            check("up swaps with the one above", order, ["Alpha", "Gamma", "Beta"], failures)
            check("with no complaint", note, "", failures)
            config.project_order = order
            order, _note = projects.move(config, "Alpha", "up")
            check("the first one cannot go higher", order, ["Alpha", "Gamma", "Beta"], failures)
            order, _note = projects.move(config, "Beta", "down")
            check("the last one cannot go lower", order, ["Alpha", "Gamma", "Beta"], failures)
            order, note = projects.move(config, "Fantasma", "up")
            check("a project outside the queue is refused with a reason", "Fantasma" in note, True,
                  failures)
        _with_temp_config(exercise)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_create(failures):
    root = _workspace(["Alpha"], governed=("Alpha",))
    try:
        def exercise(_config_file):
            config = _config(root, ["Alpha"])
            result = projects.create(config, "Beta-Nueva", "llegar a servidor de ofertas")
            check("the project is created", result.get("ok"), True, failures)
            folder = root / "Beta-Nueva"
            check("its folder exists", folder.is_dir(), True, failures)
            check("with its rules", (folder / ".ai" / "PROJECT_RULES.md").is_file(), True, failures)
            check("and the goal is written down",
                  "servidor de ofertas" in (folder / ".ai" / "PROJECT_RULES.md")
                  .read_text(encoding="utf-8"), True, failures)
            governance = result.get("governance") or {}
            governed = bool(governance.get("ok"))
            if governed:
                check("the auto-spec ran", True, True, failures)
                check("the spec is frozen on disk",
                      (folder / ".ai" / "CURRENT_SPEC.json").is_file(), True, failures)
            else:
                # Sin gobernador el alta sigue siendo un alta: se exige el motivo, ninguna spec
                # inventada, y que el proyecto NO ocupe un sitio en la cola gobernada.
                check("without the governor the result says why",
                      "NexusProtocol" in str(governance.get("reason")), True, failures)
                check("and no spec is invented on disk",
                      (folder / ".ai" / "CURRENT_SPEC.json").is_file(), False, failures)
            if shutil.which("git"):
                check("git was initialised", (folder / ".git").exists(), True, failures)
                code, _out = _git(folder, "rev-parse", "HEAD")
                check("with a first commit, so a snapshot has something to point at", code, 0,
                      failures)
            check("and it goes to the END of the queue", result.get("order"),
                  ["Alpha", "Beta-Nueva"] if governed else ["Alpha"], failures)
            again = projects.create(config, "Beta-Nueva", "")
            check("creating it twice is refused", again.get("ok"), False, failures)
            for bad in ("../../escape", "con/slash", ""):
                check("the name %r is refused" % bad, projects.create(config, bad, "").get("ok"), False,
                      failures)
        _with_temp_config(exercise)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_queue(failures):
    root = _workspace(["Alpha", "Beta"], governed=("Alpha", "Beta"))
    try:
        config = _config(root, ["Beta", "Alpha"])
        rows = projects.queue(config)
        check("one row per governed project, in order", [row["name"] for row in rows], ["Beta", "Alpha"],
              failures)
        check("positions are 1..n", [row["position"] for row in rows], [1, 2], failures)
        check("the spec is read from disk", rows[0]["spec"]["criteria"], 3, failures)
        check("the goal travels too", rows[0]["spec"]["goal"], "objetivo de Beta", failures)
        check("no test command is invented", rows[0]["test"], "", failures)
        projects.save_progress(root / "Beta", {"steps": [{"step": "a", "ok": True}], "done": False})
        check("the autonomy progress is read back", len(projects.progress(root / "Beta")["steps"]), 1,
              failures)
        check("a project without progress says so",
              projects.progress(root / "Alpha"), {"steps": [], "iterations": 0, "done": False,
                                                  "goal": ""}, failures)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_backup_zip(failures):
    root = Path(tempfile.mkdtemp(prefix="nexus-backup-zip-"))
    try:
        (root / "src").mkdir()
        (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
        (root / ".nexus" / "harness").mkdir(parents=True)
        (root / ".nexus" / "harness" / "ledger.jsonl").write_text("{}\n", encoding="utf-8")
        result = backup.snapshot(root, "test")
        check("without git it is a zip", result.get("kind"), "zip", failures)
        check("and it is reported ok", result.get("ok"), True, failures)
        target = Path(result.get("path") or "")
        check("the file exists", target.is_file(), True, failures)
        import zipfile
        with zipfile.ZipFile(target) as bundle:
            names = bundle.namelist()
        check("the source is inside", "src/a.py" in names, True, failures)
        check("and the harness state is not (it would grow with every snapshot)",
              any(name.startswith(".nexus") for name in names), False, failures)
        rows = backup.listing(root)
        check("the listing finds it", any(row["ref"] == target.name for row in rows), True, failures)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_backup_git(failures):
    if not shutil.which("git"):
        return
    root = Path(tempfile.mkdtemp(prefix="nexus-backup-git-"))
    try:
        check("git init", _git(root, "init", "-q")[0], 0, failures)
        empty = backup.snapshot(root, "test")
        check("a repository without HEAD cannot be snapshotted", empty.get("ok"), False, failures)
        check("and says why", bool(empty.get("reason")), True, failures)
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
        (root / "a.py").write_text("x = 2\n", encoding="utf-8")
        result = backup.snapshot(root, "test")
        check("with git it is a tag", result.get("kind"), "tag", failures)
        check("it is ok", result.get("ok"), True, failures)
        check("it captured the dirty tree, not just HEAD", result.get("dirty"), True, failures)
        code, out = _git(root, "tag", "--list", "nexus-backup-*")
        check("the tag is on disk", result.get("ref") in out, True, failures)
        check("and the working tree is untouched",
              (root / "a.py").read_text(encoding="utf-8"), "x = 2\n", failures)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def run():
    failures = []
    test_order(failures)
    test_save_order(failures)
    test_move(failures)
    test_create(failures)
    test_queue(failures)
    test_backup_zip(failures)
    test_backup_git(failures)
    return failures
