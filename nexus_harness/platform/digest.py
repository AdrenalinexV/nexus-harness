"""Dos primitivas que media docena de modulos necesitaban y que estaban viviendo en `relay_state`.

Bajarlas a platform no es cosmetica: `skill_forge` las usa, y mientras vivieran arriba la herramienta de
forjar skills no podia estar en una capa baja sin mirar hacia arriba.
"""
import hashlib
import time


def utc_now():
    """UTC en ISO-8601 sin microsegundos: la forma que ya viaja en los ficheros de estado."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_text(text):
    """El hash de un texto, con `errors="replace"` para que un byte raro no tumbe la escritura."""
    return hashlib.sha256(str(text or "").encode("utf-8", "replace")).hexdigest()
