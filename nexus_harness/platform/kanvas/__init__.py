"""El tablero de un proyecto: lo que ya esta hecho, lo que toca y lo que espera a otro.

Se puede leer desde cualquier sitio (CLI, herramienta del modelo, `.exe` congelado) porque es un JSON
y nada mas. Las reglas viven en `board.py`; aqui solo se publica lo publico.
"""
from .board import (AGENTS, ALLOWED, BOARD_REL, DEFAULT_TRACKS, FORMAT, STATUSES, STORED, Board,
                    KanvasError, Task)

__all__ = ["AGENTS", "ALLOWED", "BOARD_REL", "DEFAULT_TRACKS", "FORMAT", "STATUSES", "STORED",
           "Board", "KanvasError", "Task"]
