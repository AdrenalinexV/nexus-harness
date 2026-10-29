"""Cloud keys at rest: DPAPI on Windows, a 0600 file elsewhere, and a loud fallback.

The rule this module exists to enforce: **a key never travels back out**. `save()` accepts values,
`names()` reports which keys exist, and nothing in the API can read a secret out again -- the UI can
say "OPENAI_API_KEY: saved" but not show it, so a screen share cannot leak what the operator pasted.

On Windows the payload is sealed with `CryptProtectData` (the same DPAPI the Nexus vault uses), bound
to the current user account: the file is useless when copied to another machine or account. Without
`ctypes`/DPAPI the values are written as plain JSON with owner-only permissions and the result says
so -- an honest downgrade, never a silent one.
"""
import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path

NEXUS_HOME = Path(os.environ.get("NEXUS_HOME") or (Path.home() / ".nexus"))
SECRETS = NEXUS_HOME / "secrets.json"
KEY_HINTS = ("_API_KEY", "_TOKEN", "_SECRET")


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data):
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _dpapi():
    """`(protect, unprotect)` or `None` when this platform cannot seal anything."""
    if os.name != "nt":
        return None
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
    except (AttributeError, OSError):
        return None

    def protect(data):
        incoming, keep = _blob(data)
        outgoing = _Blob()
        if not crypt32.CryptProtectData(ctypes.byref(incoming), "nexus-harness", None, None, None,
                                        0, ctypes.byref(outgoing)):
            raise OSError("CryptProtectData failed")
        try:
            return ctypes.string_at(outgoing.pbData, outgoing.cbData)
        finally:
            kernel32.LocalFree(outgoing.pbData)

    def unprotect(data):
        incoming, keep = _blob(data)
        outgoing = _Blob()
        if not crypt32.CryptUnprotectData(ctypes.byref(incoming), None, None, None, None, 0,
                                          ctypes.byref(outgoing)):
            raise OSError("CryptUnprotectData failed")
        try:
            return ctypes.string_at(outgoing.pbData, outgoing.cbData)
        finally:
            kernel32.LocalFree(outgoing.pbData)

    return protect, unprotect


def load(path=None):
    """Every secret on this machine, decrypted when it was sealed. `{}` when there is nothing."""
    location = Path(path) if path else SECRETS
    if not location.is_file():
        return {}
    try:
        payload = json.loads(location.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if isinstance(payload, dict) and isinstance(payload.get("dpapi"), str):
        sealing = _dpapi()
        if sealing is None:
            return {}
        try:
            plain = sealing[1](base64.b64decode(payload["dpapi"]))
            data = json.loads(plain.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}
    return {str(key): str(value) for key, value in (payload or {}).items()
            if isinstance(value, (str, int, float))} if isinstance(payload, dict) else {}


def save(values, path=None, keep_existing=True):
    """Merge `values` into the store and seal it. Returns `{'sealed': bool, 'names': [...]}`."""
    location = Path(path) if path else SECRETS
    location.parent.mkdir(parents=True, exist_ok=True)
    merged = load(location) if keep_existing else {}
    for key, value in (values or {}).items():
        if value in (None, ""):
            merged.pop(str(key), None)
        else:
            merged[str(key)] = str(value)
    sealing = _dpapi()
    if sealing is not None and merged:
        blob = sealing[0](json.dumps(merged).encode("utf-8"))
        document = {"dpapi": base64.b64encode(blob).decode("ascii"), "names": sorted(merged)}
        sealed = True
    else:
        document = merged
        sealed = False
    location.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    if not sealed:
        _private(location)
    return {"sealed": sealed, "names": sorted(merged), "path": str(location)}


def _private(path):
    """Best effort: owner-only permissions, reported instead of swallowed."""
    try:
        os.chmod(path, 0o600)
        return True
    except OSError:
        return False


def names(path=None):
    """Which keys exist. Never their values: that is the whole point of the module."""
    return sorted(load(path))


def looks_like_key(name):
    return any(str(name).upper().endswith(hint) for hint in KEY_HINTS)


def sealed(path=None):
    """`True` cuando el cofre esta realmente cifrado con DPAPI, no solo escrito con permisos.

    La diferencia importa y no se adivina: un `secrets.json` en claro es un downgrade honesto que el
    modulo declara, y la interfaz tiene que poder decirlo con la misma honestidad en vez de pintar un
    candado verde sobre un fichero legible.
    """
    location = Path(path) if path else SECRETS
    if not location.is_file():
        return False
    try:
        payload = json.loads(location.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(payload, dict) and isinstance(payload.get("dpapi"), str)
