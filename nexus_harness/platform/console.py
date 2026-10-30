"""La consola habla UTF-8 aunque el sistema sea cp1252.

Un diagnóstico que mata al proceso que lo imprime es peor que el defecto que describe: en el runner de
Windows (cp1252) bastaba un signo menos tipográfico (U+2212) dentro de un mensaje para que el gate entero
muriera con `UnicodeEncodeError` en vez de contar el hallazgo. `errors="replace"` degrada el glifo,
nunca el veredicto.

No se traga el fallo: devuelve la lista de streams que no se pudieron reconfigurar. Un llamante que
quiera saberlo lo tiene; uno que no, sigue a lo suyo sin una excepción en la cara.
"""
import sys


def enable_utf8(streams=None):
    """Reconfigura stdout/stderr a UTF-8. Devuelve los que no se pudieron (vacío = todos)."""
    failures = []
    for stream in streams if streams is not None else (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not reconfigure:
            failures.append("%r no admite reconfigure" % (stream,))
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError) as exc:
            failures.append("%r: %s" % (stream, exc))
    return failures
