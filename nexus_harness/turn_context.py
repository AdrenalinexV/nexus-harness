"""El contexto de un turno, compartido por el Chat y por la Triada.

Existe por dos razones, y las dos son deuda que ya se pago una vez:

1. **Una sola definicion de "prefijo estable + delta"**. `chat.py` y `triad_loop.py` tenian cada uno su
   copia de la construccion del `system`, y una copia que se desvia es un turno que se comporta distinto
   segun quien lo lance. Aqui vive la unica.
2. **Caber en la ley de 400 lineas**. Al anadir el prefijo congelado, los dos bucles pasaron de 399 y
   379 a 434 y 430. Partir por responsabilidad era la unica salida honesta.

Lo que NO vive aqui: el bucle. Este modulo construye lo que viaja; quien decide cuando llamar al modelo
es el llamante.
"""
from .context_compiler import DELTA_MARKER, TurnWindow, build_prefix
from .context_pruner import prune
from . import triad_brief


def is_delta(message):
    """Un mensaje de contexto de turno, no una frase del operador."""
    return str(getattr(message, "content", "") or "").startswith(DELTA_MARKER)


def model_of(router, role):
    """El id del modelo de un rol. Un router que no contesta no puede tumbar un turno."""
    try:
        return str(router.info(role).model or "")
    except Exception:  # noqa: BLE001 -- la calibracion es una mejora, no un requisito
        return ""


def map_text(config):
    """El bloque del mapa AST con su encabezado, o cadena vacia. El coste se declara aparte."""
    block, tokens = triad_brief.map_block(config)
    if not block:
        return "", 0
    return "## Mapa de simbolos (pide rangos con read_file offset/limit)\n%s" % block, int(tokens)


def prefix_sections(config, base, memory_block="", project_facts="", with_map=True,
                    recall_block=""):
    """`[(nombre, texto)]` estables del turno: reglas, memoria, mapa y hechos.

    El orden importa y es fijo: reglas primero, porque es lo unico que no cambia nunca; hechos al
    final, porque son los que mas se parecen a datos. Un prefijo cuyo orden baila no se cachea.
    """
    parts = [("rules", base)]
    if memory_block:
        parts.append(("memory", memory_block))
    if recall_block:
        parts.append(("recall", recall_block))
    if with_map:
        block, _tokens = map_text(config)
        if block:
            parts.append(("map", block))
    proof = triad_brief.proof_block(config)
    if proof:
        parts.append(("facts", proof))
    if project_facts:
        parts.append(("project", project_facts))
    return parts


def build_turn_prefix(config, base, router=None, role="worker", memory_block="", project_facts="",
                      with_map=True, recall_block=""):
    """El `Prefix` medido y con digest de este turno."""
    model = model_of(router, role) if router is not None else ""
    return build_prefix(prefix_sections(config, base, memory_block, project_facts, with_map,
                                        recall_block), model)


def inject_skills(skills, files, emit=None, kind="skills"):
    """Pide las skills del turno y las emite al bus. Devuelve `(bloque_delta, tokens)`.

    Se llama en CADA paso (el conjunto de ficheros crece), pero el bloque solo se anade si su texto
    cambio: dos pasos con los mismos ficheros no duplican contexto.
    """
    if skills is None:
        return "", 0
    try:
        injection = (skills.inject(list(files or ())) if hasattr(skills, "inject")
                     else skills.select(sorted(files or ())))
    except Exception as exc:  # noqa: BLE001 -- sin skills se trabaja; con el turno caido, no
        if emit is not None:
            emit("skills.injected", "(error)", names=[], tokens=0, available=False,
                 note="%s: %s" % (type(exc).__name__, exc))
        return "", 0
    names = list(getattr(injection, "names", []) or [])
    tokens = int(getattr(injection, "tokens", 0) or 0)
    if emit is not None:
        emit("skills.injected", ", ".join(names) or "(none)", names=names, tokens=tokens,
             available=bool(getattr(injection, "available", True)),
             note=str(getattr(injection, "note", "") or ""))
    brief = str(getattr(injection, "brief", "") or "")
    if not brief:
        return "", 0
    return "%s\n### %s\n%s" % (DELTA_MARKER, kind, brief), tokens


def split_history(messages, has_prefix):
    """Separa lo que se persiste (historia) de lo que solo vive en el turno (deltas)."""
    kept = messages[1:] if has_prefix else list(messages)
    return ([one for one in kept if not is_delta(one)], [one for one in kept if is_delta(one)])


def apply_budget(messages, config, savings=None, compactor=None, emit=None):
    """Poda deslizante + compactacion, con lo podado medido. `True` si toco algo.

    La poda corre SIEMPRE (es barata y determinista); la compactacion, cuando toca por presupuesto.
    """
    if not getattr(config, "nexus_engines", True):
        return False
    report = prune(messages)
    if report.pruned:
        if savings is not None:
            savings.observe_pruned(report)
        if emit is not None:
            emit("context.pruned", "%d salidas podadas (%d tokens menos)"
                 % (report.pruned, report.tokens_saved), count=report.pruned,
                 tokens_saved=report.tokens_saved, references=report.receipts[:8])
    applied = False
    if compactor is not None:
        result = compactor.maybe(messages)
        applied = bool(result.applied)
        if applied and emit is not None:
            emit("context.compacted", result.reason, compaction=result.as_dict())
    return bool(applied or report.pruned)


def window_for(prefix, delta, files, model="", max_deltas=8):
    """La ventana del turno con su primer delta ya puesto."""
    window = TurnWindow(prefix, model=model, max_deltas=max_deltas)
    if delta:
        window.note("skills", delta)
    return window


def chat_prefix(config, router, base, memory=None, goal=""):
    """El prefijo del Chat: reglas, memoria manual, memoria por capas, mapa y hechos.

    Devuelve `(Prefix, tokens_inyectados)`. En modo tradicional (benchmark A) inyecta el indice
    completo de skills y lo declara; en modo Nexus, las skills viajan como delta del turno.
    """
    if not getattr(config, "nexus_engines", True):
        from .savings import full_index_brief
        brief = full_index_brief()
        parts = [("rules", base)]
        if brief:
            parts.append(("skills", brief))
        return build_prefix(parts), len(brief) // 4
    from .tools.recall import Recall
    remembered = (Recall(config.default_root).block(goal)
                  if getattr(config, "recall_enabled", True) else "")
    facts = ("## Proyecto" + chr(10) * 2 + "raíz: %s" + chr(10) + "tests: %s") % (
        getattr(config, "default_root", "."),
        getattr(config, "test_command", None) or "no configurado")
    return build_turn_prefix(config, base, router, "worker",
                             memory_block=memory.block() if memory is not None else "",
                             project_facts=facts, recall_block=remembered), 0
