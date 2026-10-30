"""Autonomía: el planificador, su daemon, el grafo de plan y la consulta a una persona.

Cuatro módulos que trabajan juntos y que hasta la fase 2 vivían sueltos en la raíz del paquete:

    autonomy.py       Autopilot, model_planner, parse_plan — el bucle que trabaja solo
    autonomy_ask.py   la pregunta que se le hace a una persona, con su valor por defecto
    daemon.py         el residente que despierta ese bucle sin nadie delante
    plan_graph.py     el grafo del plan, con su detección de ciclos

**Re-exporta en diferido, y eso no es un capricho.** Lo que antes se importaba de los módulos sueltos
(`from nexus_harness.autonomy import Autopilot`) sigue funcionando, pero el paquete no importa nada al
cargarse: `daemon.py` usa `Autopilot` y `autonomy.py` usa `plan_graph`, así que un `__init__` que
importara a sus hijos de entrada cerraría el círculo (`ImportError: partially initialized module`). Con
`__getattr__` (PEP 562) el símbolo se resuelve la primera vez que alguien lo pide, y se queda cacheado.

`autonomy_ask` no se re-exporta a propósito: se importa como MÓDULO (`from nexus_harness.autonomy import
autonomy_ask`), que es lo que el sistema de imports resuelve solo. Dentro no hay ningún símbolo con ese
nombre — expone `question_text`, `ask_about_red` y `act`.
"""
__all__ = ["Autopilot", "Daemon", "GraphError", "model_planner", "parse_plan"]

_SYMBOLS = {
    "Autopilot": "autonomy",
    "model_planner": "autonomy",
    "parse_plan": "autonomy",
    "Daemon": "daemon",
    "GraphError": "plan_graph",
}


def __getattr__(name):
    module = _SYMBOLS.get(name)
    if module is None:
        raise AttributeError("module %r has no attribute %r" % (__name__, name))
    from importlib import import_module
    value = getattr(import_module("%s.%s" % (__name__, module)), name)
    globals()[name] = value  # cacheado: el segundo acceso no vuelve a importar
    return value


def __dir__():
    return sorted(__all__)
