"""Sintesis de spec: un objetivo en lenguaje natural se convierte en criterios EJECUTABLES.

El agujero que tapa: la autonomia leia una spec escrita a mano y congelada. El bucle sabia ejecutar
un plan y probarlo, pero nadie escribia los criterios: el proyecto no podia empezar a construirse solo.

Tres reglas hacen que esto no sea teatro con JSON:

1. **Un criterio es un comando y un exit esperado.** Sin comando no entra; la prosa no se valida.
2. **Se valida contra el estado actual.** Cada candidato se ejecuta al congelar, y su exit queda como
   evidencia. Un criterio que revienta al lanzarse (comando inexistente, politica de shell) se descarta
   y se dice por que.
3. **Una spec que ya esta verde no sirve.** Si todos los criterios pasan hoy, no hay nada que construir:
   `actionable=False` y no se escribe (salvo `force`). Un plan sin hueco es una firma, no un plan.

La spec congelada no se debilita: al fusionar se conservan los criterios que ya estaban y solo se
ANADEN los nuevos. Quitar un criterio es una decision del operador, no un efecto secundario.
"""
import json
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .platform import policy
from .verify import oracle

SPEC_REL = Path(".ai") / "CURRENT_SPEC.json"
MAX_CAS = 8
TIMEOUT = 240
WINDOWS_FLAGS = 0x08000000 if os.name == "nt" else 0
SLUG = re.compile(r"[^a-z0-9]+")
BUILD_HINTS = (("package.json", '{"scripts": {"build"', "npm run build"),
               ("Cargo.toml", None, "cargo build -q"),
               ("go.mod", None, "go build ./..."))


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def slug(text):
    clean = SLUG.sub("-", str(text or "spec").strip().lower()
                     .replace("á", "a").replace("é", "e").replace("í", "i")
                     .replace("ó", "o").replace("ú", "u").replace("ñ", "n"))
    return clean.strip("-")[:48] or "spec"


@dataclass
class Candidate:
    """Un criterio propuesto, antes de saber si el proyecto lo cumple o no."""

    title: str
    command: str
    expect_exit: int = 0
    source: str = "proyecto"

    def as_dict(self):
        return {"title": self.title, "command": self.command, "expect_exit": self.expect_exit,
                "source": self.source}


def project_candidates(root, config=None):
    """Lo que ESTE repositorio ya sabe probar: su test y su build. Sin modelo, sin invencion."""
    declared = str(getattr(config, "test_command", None) or "").strip()
    found = oracle.detect(root)
    rows = []
    if declared or found:
        rows.append(Candidate("los tests del proyecto pasan", declared or found["command"],
                              source="declarado" if declared else found.get("source", "detectado")))
    for name, needle, command in BUILD_HINTS:
        path = Path(root) / name
        if not path.is_file():
            continue
        if needle and needle not in path.read_text(encoding="utf-8", errors="replace"):
            continue
        rows.append(Candidate("el proyecto compila", command, source=name))
        break
    return rows


def _object(text):
    """El primer objeto JSON del texto, o `None`. Los modelos envuelven el JSON en vallas y prosa."""
    raw = str(text or "")
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(raw[start:end + 1])
            return data if isinstance(data, dict) else None
        except ValueError:
            return None
    return None


def director_candidates(router, root, goal, config=None):
    """El Director propone criterios; el arnes los valida. Su opinion no basta para congelarlos."""
    from .core.message import Message

    prompt = ("Proyecto: %s\nObjetivo: %s\n\nPropone entre 2 y %d criterios de aceptacion "
              "EJECUTABLES: cada uno con un comando de shell que salga 0 cuando el objetivo este "
              "cumplido y no-cero mientras no lo este. Nada de prosa.\n"
              'Responde SOLO JSON: {"cas": [{"title": "...", "command": "...", '
              '"expect_exit": 0}]}' % (Path(root).name, goal or "(sin objetivo)", MAX_CAS))
    try:
        reply = router.role("director").chat([Message(role="system", content="Eres el Director de un "
                                                      "arnes de ingenieria. Solo JSON."),
                                              Message(role="user", content=prompt)],
                                             temperature=0.1, max_tokens=700)
    except Exception:  # noqa: BLE001 -- sin modelo quedan los criterios del proyecto
        return []
    data = _object(getattr(reply, "text", "") or getattr(reply, "reasoning", "")) or {}
    rows = []
    for item in (data.get("cas") or [])[:MAX_CAS]:
        if not isinstance(item, dict):
            continue
        command = str(item.get("command") or "").strip()
        if not command:
            continue
        expect = item.get("expect_exit", 0)
        rows.append(Candidate(str(item.get("title") or command)[:160], command,
                              int(expect) if str(expect).lstrip("-").isdigit() else 0, "director"))
    return rows


def _argv(command):
    """El comando como argv. `posix=True` quita las comillas y subprocess las vuelve a poner bien."""
    try:
        return shlex.split(str(command or ""))
    except ValueError:
        return []


def validate(root, candidates, timeout=TIMEOUT, config=None):
    """Ejecuta cada candidato AHORA. `exit=None` significa que no se pudo lanzar."""
    mode = policy.mode_of(config)
    rows = []
    for candidate in candidates:
        argv = _argv(candidate.command)
        if not argv:
            rows.append(dict(candidate.as_dict(), exit=None, ok=False, detail="comando ilegible"))
            continue
        verdict = policy.classify(candidate.command, mode)
        if not verdict.allowed:
            rows.append(dict(candidate.as_dict(), exit=None, ok=False,
                             detail="refusado por politica: %s" % verdict.reason))
            continue
        try:
            done = subprocess.run(argv, cwd=str(root), capture_output=True, text=True,
                                  errors="replace", timeout=int(timeout),
                                  creationflags=WINDOWS_FLAGS)
        except (OSError, subprocess.SubprocessError) as exc:
            rows.append(dict(candidate.as_dict(), exit=None, ok=False,
                             detail="%s: %s" % (type(exc).__name__, exc)))
            continue
        output = ((done.stdout or "") + (done.stderr or "")).strip()
        rows.append(dict(candidate.as_dict(), exit=done.returncode,
                         ok=done.returncode == candidate.expect_exit,
                         detail=output[-400:] or "(sin salida)", at=_now()))
    return rows


def _cas_rows(rows):
    """Los criterios que merecen congelarse: se ejecutaron de verdad y su exit es interpretable."""
    keep = []
    for row in rows:
        if row.get("exit") is None:
            continue
        keep.append({"title": row["title"], "command": _argv(row["command"]),
                     "expect_exit": int(row.get("expect_exit") or 0), "source": row.get("source", ""),
                     "evidence": {"exit": row["exit"], "at": row.get("at", "")}})
    return keep


def merge(previous, fresh, limit=MAX_CAS):
    """Conserva lo congelado y ANADE lo nuevo. Dos criterios con el mismo comando son uno."""
    kept = [dict(row) for row in (previous or {}).get("cas") or [] if isinstance(row, dict)]
    seen = {tuple(row.get("command") or ()) for row in kept}
    for row in fresh:
        key = tuple(row.get("command") or ())
        if not key or key in seen:
            continue
        kept.append(row)
        seen.add(key)
        if len(kept) >= limit:
            break
    for index, row in enumerate(kept, start=1):
        row["id"] = "CA%d" % index
    return kept[:limit]


def build_spec(goal, cas, previous=None, origin="synthesized"):
    """El documento `nexus.spec/1`, con su sha256 sobre los criterios (lo que se congela)."""
    body = {"protocol": "nexus", "format": "nexus.spec/1",
            "id": (previous or {}).get("id") or slug(goal),
            "goal": str(goal or (previous or {}).get("goal") or ""),
            "frozen_at": _now(), "origin": origin, "cas": cas}
    body["cas_sha256"] = _sha(cas)
    return body


def _sha(cas):
    import hashlib
    payload = json.dumps(cas, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load(root):
    try:
        data = json.loads((Path(root) / SPEC_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(root, spec):
    path = Path(root) / SPEC_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return str(path)


def synthesize(root, goal, config=None, router=None, candidates=None, write=False, force=False,
               limit=MAX_CAS):
    """Objetivo -> criterios ejecutables -> spec validada. `write=False` es un plan en seco."""
    root = Path(root)
    proposed = list(candidates or [])
    if router is not None:
        proposed += director_candidates(router, root, goal, config)
    if not proposed:
        proposed = project_candidates(root, config)
    rows = validate(root, proposed, config=config)
    fresh = _cas_rows(rows)
    dropped = [row for row in rows if row.get("exit") is None]
    actionable = any(not row["ok"] for row in rows if row.get("exit") is not None)
    previous = load(root)
    cas = merge(previous, fresh, limit)
    spec = build_spec(goal or previous.get("goal"), cas, previous)
    result = {"ok": bool(cas), "actionable": actionable, "written": False, "spec": spec,
              "rows": rows, "dropped": dropped,
              "reason": "" if cas else "ningun criterio se pudo ejecutar"}
    if not cas:
        return result
    if not actionable and not force:
        result["reason"] = ("todos los criterios ya pasan: no hay nada que construir "
                            "(usa force para congelarla igual)")
        return result
    if write:
        result["written"] = True
        result["path"] = save(root, spec)
    return result


# -- la spec viva: evaluarla y ampliarla --------------------------------------------------------
def evaluate(root, timeout=TIMEOUT, config=None):
    """Ejecuta los criterios CONGELADOS y dice como esta el proyecto ahora mismo.

    Es la unica definicion de "terminado" del bucle autonomo: no lo que el Director opine, sino el exit
    de cada criterio. Una spec sin comandos (solo `cas_count`) devuelve `[]` y no opina.
    """
    rows = []
    for index, ca in enumerate((load(root).get("cas") or []), start=1):
        if not isinstance(ca, dict):
            continue
        argv = ca.get("command")
        command = " ".join(argv) if isinstance(argv, list) else str(argv or "")
        if not command.strip():
            continue
        exit_code, detail = _run_once(root, argv if isinstance(argv, list) else _argv(command),
                                      command, timeout, config)
        expect = int(ca.get("expect_exit") or 0)
        rows.append({"id": ca.get("id") or "CA%d" % index, "title": ca.get("title") or command,
                     "command": command, "expect_exit": expect, "exit": exit_code,
                     "ok": exit_code is not None and exit_code == expect, "detail": detail,
                     "at": _now()})
    return rows


def met(rows):
    """`True` solo si hay criterios y todos cumplen. Vacio no es exito: es ausencia de medida."""
    return bool(rows) and all(row.get("ok") for row in rows)


def _run_once(root, argv, command, timeout, config=None):
    """Un comando, con la politica delante. `(exit, detalle)`; `exit=None` = no se pudo lanzar."""
    if not argv:
        return None, "comando ilegible"
    verdict = policy.classify(command, policy.mode_of(config))
    if not verdict.allowed:
        return None, "refusado por politica: %s" % verdict.reason
    try:
        done = subprocess.run(argv, cwd=str(root), capture_output=True, text=True,
                              errors="replace", timeout=int(timeout),
                              creationflags=WINDOWS_FLAGS)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)
    output = ((done.stdout or "") + (done.stderr or "")).strip()
    return done.returncode, output[-400:] or "(sin salida)"


def add_criterion(root, title, command, expect_exit=0, origin="finding", signature="",
                  config=None, timeout=TIMEOUT):
    """ANADE un criterio descubierto durante el trabajo. Nunca quita ni debilita los congelados.

    Se niega en dos casos, y los dos importan: un comando que no se puede ejecutar (seria una promesa
    sin prueba) y un criterio que YA se cumple (no es un hueco, es ruido en la lista).
    """
    argv = _argv(command)
    exit_code, detail = _run_once(root, argv, command, timeout, config)
    if exit_code is None:
        return {"ok": False, "reason": detail, "command": str(command)}
    expect = int(expect_exit or 0)
    if exit_code == expect:
        return {"ok": False, "reason": "ya se cumple (exit %s): no es un hueco" % exit_code,
                "command": str(command)}
    previous = load(root)
    cas = merge(previous, [{"title": str(title or command)[:160], "command": argv,
                            "expect_exit": expect, "source": origin,
                            "evidence": {"exit": exit_code, "at": _now()}}])
    if len(cas) == len(previous.get("cas") or []):
        return {"ok": False, "reason": "ese comando ya esta en la spec", "command": str(command)}
    spec = build_spec(previous.get("goal"), cas, previous, origin="grown")
    spec["grown_at"] = _now()
    spec["grown_by"] = str(signature or origin)
    path = save(root, spec)
    return {"ok": True, "path": path, "added": cas[-1], "spec": spec, "exit": exit_code}
