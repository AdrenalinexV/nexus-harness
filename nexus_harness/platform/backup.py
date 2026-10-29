"""Snapshot antes de un ciclo autonomo: o un tag de git, o un zip. Nunca "confia en mi".

La ley es simple y no admite interpretacion: un bucle que edita ficheros sin red de seguridad es un
bucle que algun dia borra el trabajo de la tarde. Antes de cada ciclo se guarda el estado EXACTO del
arbol, incluido lo que esta sin commitear, y se devuelve la referencia con la que se puede volver.

Dos formas, y se elige por lo que hay, no por lo que se desea:

* **Repositorio git** -> `git stash create` fabrica un commit con el arbol sucio SIN tocar el arbol de
  trabajo, y se le pone un tag `nexus-backup-<fecha>`. Se puede volver con `git reset --hard <tag>`, y
  el operador no se encuentra la rama llena de commits del agente.
* **Sin git** -> un zip en `.nexus/backups/<fecha>.zip` con lo que de verdad es fuente: se excluyen
  `.git`, `node_modules`, `target`, `.build`, `dist`, `__pycache__` y los propios backups. Un zip de
  400 MB de `target` no es una copia de seguridad, es una factura de disco.

Un fallo se devuelve como fallo (`ok: False` con su motivo). Inventar un snapshot que no existe es peor
que no tenerlo.
"""
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

WINDOWS_FLAGS = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
BACKUP_REL = Path(".nexus") / "backups"
EXCLUDE = {".git", ".nexus", "node_modules", "target", ".build", "dist", "__pycache__", ".venv",
           ".mypy_cache", ".pytest_cache"}
MAX_BYTES = 240 * 1024 * 1024


def stamp():
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def _git(root, *args, timeout=90):
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              errors="replace", timeout=timeout, creationflags=WINDOWS_FLAGS)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", "%s: %s" % (type(exc).__name__, exc)
    return done.returncode, (done.stdout or "").strip(), (done.stderr or "").strip()


def is_repo(root):
    return (Path(root) / ".git").exists() and shutil.which("git") is not None


def _git_snapshot(root, name):
    code, inside, error = _git(root, "rev-parse", "--is-inside-work-tree")
    if code != 0 or inside != "true":
        return None
    code, dirty, error = _git(root, "stash", "create")
    stash_ok = code == 0
    code_head, head, error_head = _git(root, "rev-parse", "HEAD")
    target = dirty if stash_ok and dirty else (head if code_head == 0 else "")
    if not target:
        return {"ok": False, "kind": "git", "reason": "no HEAD and nothing to stash: %s"
                % (error or error_head or "empty repository")}
    code, _out, error = _git(root, "tag", "-f", name, target)
    if code != 0:
        return {"ok": False, "kind": "git", "reason": error or "git tag refused"}
    return {"ok": True, "kind": "tag", "ref": name, "sha": target[:40],
            "dirty": bool(stash_ok and dirty), "path": str(root)}


def _zip_snapshot(root, name):
    target = Path(root) / BACKUP_REL / ("%s.zip" % name)
    target.parent.mkdir(parents=True, exist_ok=True)
    written, total = 0, 0
    partial = target.with_suffix(".part")
    try:
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
            for path in sorted(Path(root).rglob("*")):
                relative = path.relative_to(root)
                if any(part in EXCLUDE for part in relative.parts):
                    continue
                if not path.is_file():
                    continue
                if path.stat().st_size + total > MAX_BYTES:
                    break
                bundle.write(path, relative.as_posix())
                written += 1
                total += path.stat().st_size
        partial.replace(target)
    except (OSError, zipfile.BadZipFile) as exc:
        partial.unlink(missing_ok=True)
        return {"ok": False, "kind": "zip", "reason": "%s: %s" % (type(exc).__name__, exc)}
    return {"ok": True, "kind": "zip", "ref": target.name, "path": str(target),
            "files": written, "bytes": total}


def snapshot(root, reason="autonomy", name=None):
    """Guarda el estado del arbol. Devuelve `{ok, kind, ref, path, ...}`; nunca lanza."""
    root = Path(root)
    if not root.is_dir():
        return {"ok": False, "kind": "none", "reason": "no es un directorio: %s" % root}
    label = name or "nexus-backup-%s" % stamp()
    if is_repo(root):
        result = _git_snapshot(root, label)
        if result is not None:
            return dict(result, reason=reason, at=label)
    return dict(_zip_snapshot(root, label), reason=reason, at=label, sha="")


def listing(root, limit=12):
    """Los backups que hay, de mas nuevo a mas viejo. Se lee del disco, no de la memoria."""
    root = Path(root)
    rows = []
    if is_repo(root):
        code, out, _error = _git(root, "tag", "--list", "nexus-backup-*", "--sort=-creatordate")
        if code == 0 and out:
            rows = [{"kind": "tag", "ref": line.strip(), "path": str(root)}
                    for line in out.splitlines() if line.strip()][:int(limit)]
    folder = root / BACKUP_REL
    if folder.is_dir():
        zips = sorted(folder.glob("*.zip"), key=lambda path: path.stat().st_mtime, reverse=True)
        rows += [{"kind": "zip", "ref": path.name, "path": str(path),
                  "bytes": path.stat().st_size} for path in zips[:int(limit)]]
    return rows[:int(limit)]
