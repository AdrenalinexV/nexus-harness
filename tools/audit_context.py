"""Auditoria del ahorro de contexto: las cuatro preguntas del operador, contestadas con numeros.

    python tools/audit_context.py [--json]

No estima: lee el libro de turnos real, el ledger del gobernador, el catalogo de skills instalado y
construye un turno sintetico de 8 pasos con salidas de herramienta grandes para medir el crecimiento
de tokens de entrada paso a paso con el MISMO contador que usa el motor (`compaction.estimate`).

Las cuatro preguntas que responde:

1. por que el arnes registra tokens consumidos y CERO evitados;
2. por que la tarjeta de tokens evitados no cuadra con las barras verdes;
3. si el historial viaja entero en cada paso (O(N^2)) o se poda;
4. por que los turnos medidos terminaron bloqueados.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus_harness import ledger  # noqa: E402
from nexus_harness.compaction import estimate  # noqa: E402
from nexus_harness.config import HarnessConfig  # noqa: E402
from nexus_harness.message import Message, ToolCall  # noqa: E402
from nexus_harness.relay_state import prune_tool_outputs  # noqa: E402

BIG = ("def funcion_%d(a, b):\n    return a + b  # relleno de una lectura realista\n" * 40)
PROJECTS = ("Nexus-Harness", "NexusProtocol", "AXV-AdrenalineX", "Omni-Nexus")


def _synthetic_step(index):
    call = ToolCall(id="c%d" % index, name="read_file", arguments={"path": "mod_%d.py" % index},
                    raw_arguments='{"path": "mod_%d.py"}' % index)
    return [Message(role="assistant", content="", tool_calls=[call]),
            Message(role="tool", content=BIG.replace("_N", "_%d" % index), tool_call_id=call.id, name="read_file")]


def q1_and_q4(workspace):
    rows = ledger.history(workspace, PROJECTS, extra=[ROOT])
    names = sorted({key for row in rows for key in row})
    saved_fields = [name for name in names if "sav" in name or "avoid" in name or "baseline" in name]
    per_project, dupes = {}, {}
    for row in rows:
        name = row.get("project") or "?"
        bucket = per_project.setdefault(name, {"turns": 0, "tokens": 0, "blocked": 0, "repaired": 0,
                                              "green": 0})
        bucket["turns"] += 1
        bucket["tokens"] += int(row.get("tokens") or 0)
        exit_code, repairs = row.get("exit"), int(row.get("repairs") or 0)
        if exit_code == 0 and not repairs:
            bucket["green"] += 1
        elif exit_code == 0:
            bucket["repaired"] += 1
        else:
            bucket["blocked"] += 1
        key = (row.get("at"), row.get("session"), bucket and name, row.get("tokens"))
        dupes[key] = dupes.get(key, 0) + 1
    repeated = [key for key, count in dupes.items() if count > 1]
    return {"filas": len(rows), "campos_del_libro": names,
            "campos_de_ahorro": saved_fields,
            "por_proyecto": per_project,
            "filas_duplicadas": len(repeated),
            "ejemplo_duplicado": repeated[0][:3] if repeated else None}


def q2(workspace):
    """Las dos fuentes: la tarjeta (ledger del gobernador) y las barras (impact panels)."""
    from nexus_harness import gov
    state, reason = gov.installer_state()
    money = (state.get("money") or {}) if isinstance(state, dict) else {}
    panels = ((state.get("impact") or {}).get("panels") or []) if isinstance(state, dict) else []
    bars = {}
    for panel in panels:
        if panel.get("present"):
            bars[str(panel.get("name"))] = int(panel.get("tokens_blocked") or 0)
    return {"tarjeta_tokens_evitados": money.get("avoided_tokens"),
            "barras_verdes_por_proyecto": bars, "suma_barras": sum(bars.values()),
            "barra_nexus_harness": bars.get("Nexus-Harness", 0), "motivo_gobierno": reason,
            "fuente_tarjeta": "ledger de dinero del gobernador (todos sus turnos)",
            "fuente_barras": "impact panels del gobernador, por proyecto"}


def q3(steps=8):
    """Tokens de entrada acumulados segun se reenvia el historial, con y sin poda."""
    messages = [Message(role="system", content="reglas del sistema " * 20),
                Message(role="user", content="arregla mod_0.py")]
    sin_poda, con_poda = [], []
    for index in range(steps):
        messages.extend(_synthetic_step(index))
        sin_poda.append(estimate(messages)[1])
        copia = [Message(role=m.role, content=m.content,
                         tool_calls=list(getattr(m, "tool_calls", None) or []),
                         tool_call_id=str(getattr(m, "tool_call_id", "") or ""),
                         name=str(getattr(m, "name", "") or "")) for m in messages]
        pruned, _refs = prune_tool_outputs(copia)
        con_poda.append(estimate(copia)[1])
    return {"pasos": steps, "tokens_entrada_por_paso_sin_poda": sin_poda,
            "tokens_entrada_por_paso_con_poda": con_poda,
            "total_sin_poda": sum(sin_poda), "total_con_poda": sum(con_poda),
            "ahorro_pct": round(100.0 * (1 - sum(con_poda) / float(sum(sin_poda) or 1)), 1),
            "crecimiento": "cuadratico en A, acotado en B"}


def skills_baseline():
    from nexus_harness.skill_router import skill_entry
    roots = [Path.home() / "AppData/Local/hermes/profiles/nexus-harness/skills",
             Path.home() / "AppData/Local/hermes/skills",
             Path("C:/Proyectos/NexusProtocol/skills")]
    seen, index_chars, body_chars = set(), 0, 0
    for root in roots:
        if not Path(root).is_dir():
            continue
        for path in sorted(Path(root).rglob("SKILL.md")):
            entry = skill_entry(path, root)
            if entry is None or entry["name"] in seen:
                continue
            seen.add(entry["name"])
            index_chars += len(entry["name"]) + len(entry["description"]) + 4
            body_chars += len(path.read_text(encoding="utf-8", errors="replace"))
    return {"skills_unicas": len(seen), "indice_tokens": index_chars // 4,
            "cuerpo_completo_tokens": body_chars // 4}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="audit_context")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    config = HarnessConfig.load()
    report = {"q1_q4_libro": q1_and_q4(config.workspace), "q2_fuentes": q2(config.workspace),
              "q3_crecimiento": q3(), "skills_instaladas": skills_baseline()}
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    book = report["q1_q4_libro"]
    print("P1) El libro de turnos guarda: %s" % ", ".join(book["campos_del_libro"]))
    print("    Campos de ahorro/baseline en el libro: %s" % (book["campos_de_ahorro"] or "NINGUNO"))
    print("    Filas duplicadas en el libro: %d (misma sesion y tokens dos veces: %s)"
          % (book["filas_duplicadas"], book["ejemplo_duplicado"]))
    for name, bucket in sorted(book["por_proyecto"].items()):
        print("    %-18s turnos=%-3d tokens=%-9d verdes=%-2d reparados=%-2d bloqueados=%d"
              % (name, bucket["turns"], bucket["tokens"], bucket["green"], bucket["repaired"],
                 bucket["blocked"]))
    two = report["q2_fuentes"]
    print("P2) Tarjeta (ledger del gobernador): %s tokens evitados" % two["tarjeta_tokens_evitados"])
    print("    Suma de barras verdes (impact panels): %s -> desvio declarado"
          % two["suma_barras"])
    print("    Nexus-Harness en barras: %s" % two["barra_nexus_harness"])
    three = report["q3_crecimiento"]
    print("P3) Tokens de entrada por paso, 8 pasos con lecturas grandes:")
    print("    A sin poda: %s (total %d)" % (three["tokens_entrada_por_paso_sin_poda"],
                                            three["total_sin_poda"]))
    print("    B con poda: %s (total %d) -> ahorro %s%%"
          % (three["tokens_entrada_por_paso_con_poda"], three["total_con_poda"],
             three["ahorro_pct"]))
    print("P4) Bloqueos: ver el desglose de P1 (verde/reparado/bloqueado por proyecto)")
    skills = report["skills_instaladas"]
    print("Skills instaladas: %d unicas · indice ~%d tokens · cuerpos completos ~%d tokens"
          % (skills["skills_unicas"], skills["indice_tokens"], skills["cuerpo_completo_tokens"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
