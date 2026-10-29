"""tools: la superficie de acciones que un modelo puede llamar.

`registry.py` es el registro (esquemas + despacho) y `toolbox/` las implementaciones. Este `__init__`
es solo la cara publica de la capa: `from .tools import default_registry` sigue significando lo mismo
que antes de la migracion, sin un segundo nombre para el mismo objeto.
"""
from .registry import (MAX_PARALLEL, READ_ONLY, ROOT_HANDLERS, SCHEMAS, WRITE_TOOLS, Observation,
                       Registry, default_registry, parallel_reads)

__all__ = ["MAX_PARALLEL", "READ_ONLY", "ROOT_HANDLERS", "SCHEMAS", "WRITE_TOOLS", "Observation",
           "Registry", "default_registry", "parallel_reads"]
