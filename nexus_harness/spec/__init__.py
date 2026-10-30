"""Spec: la especificación que el motor sintetiza y congela antes de trabajar.

Un solo módulo, y se dice por qué: la propuesta de arquitectura v2 daba por hecho un `spec/` con
`spec_synth` y `criteria` separados, pero `criteria` **nunca existió** — `Candidate`, `GREEN` y el
resto de la maquinaria de criterios viven dentro de `spec_synth.py`. Se mueve lo que hay y no se
inventa un fichero para que el dibujo cuadre.

El paquete re-exporta en diferido por la misma razón que `autonomy`: nadie debe pagar un import circular
porque un módulo haya ganado una carpeta.
"""
__all__ = ["Candidate", "synthesize"]

_SYMBOLS = {"Candidate": "spec_synth", "synthesize": "spec_synth"}


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
