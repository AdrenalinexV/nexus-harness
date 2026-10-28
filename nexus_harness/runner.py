"""Una corrida de la triada, en un sitio, para los tres que la piden.

`Cockpit` la pide desde el chat lanzado a mano, el puente movil desde su cola y el bucle autonomo desde
cada iteracion. Antes de este modulo la construccion estaba copiada en dos metodos de `cockpit.py`, y
una copia que se desvia es una corrida que se comporta distinto segun quien la lance.

Devuelve el `RunResult` entero y no solo el codigo: el bucle autonomo necesita el veredicto (que
fallo, que ficheros toco) para decidir si repara, si hace commit o si pasa al proyecto siguiente. El
codigo de salida es una consecuencia, no la medida.
"""
from dataclasses import replace
from pathlib import Path

from .skill_router import library
from .gate import Gate
from .judge import judge_for
from .session_relay import SessionRelay
from .tools import default_registry
from .triad_loop import Triad


def config_for(config, root, test_command=None):
    """La configuracion de ESTA corrida: el proyecto manda su comando de test, el turno puede pisarlo."""
    per_project = (getattr(config, "project_tests", None) or {}).get(Path(root).name) or ""
    return replace(config, default_root=Path(root),
                   test_command=test_command or per_project or config.test_command)


def run_triad(config, root, goal, router, bus=None, test_command=None):
    """Corre la triada en `root` de forma sincrona. Devuelve `(RunResult, Triad)`."""
    local = config_for(config, root, test_command)
    relay = SessionRelay(root, goal=goal, config=local, bus=bus)
    relay.start()
    triad = Triad(router, local, registry=default_registry(root, local), gate=Gate(root, local),
                  judge=judge_for(router, local), skills=library(root), bus=bus,
                  relay=relay)
    return triad.run(goal), triad
