"""Aprendizaje: lo que el motor saca de sus propios turnos y lo que decide mejorar después.

Dos módulos, y ninguno más, porque el grafo de dependencias manda:

    reflection.py   lee el turno cerrado, escribe `skill_outcomes.jsonl` y produce lecciones
    improve.py      lee el ledger y convierte lo que salió mal en trabajo concreto para la cola

Los otros dos que la propuesta v2 ponía aquí **no pueden venir**, y se dice con la medición delante:
`skill_forge` lo usa `tools/toolbox/skill_tools.py` (capa tools) y `skill_router` lo usa
`context/savings.py` (capa context); moverlos aquí haría que tools y context importaran hacia arriba —
el mismo defecto que esta fase está cerrando, solo que al revés. Se quedan donde su consumidor los
necesita.

Re-exporta en diferido (PEP 562) por la misma razón que los otros paquetes de la fase: que mover un
módulo no rompa un import que ya funcionaba ni cree un ciclo.
"""
__all__ = ["learn", "queue"]

_SYMBOLS = {"learn": "reflection", "queue": "improve"}


def __getattr__(name):
    module = _SYMBOLS.get(name)
    if module is None:
        raise AttributeError("module %r has no attribute %r" % (__name__, name))
    from importlib import import_module
    value = getattr(import_module("%s.%s" % (__name__, module)), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(__all__)
