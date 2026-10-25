"""El único endpoint con JSON de la pantalla de configuración: el editor de `SKILL.md`.

Todo lo demás de esa pantalla funciona sin script (enlaces y formularios con 303). Lo que no puede es
abrir el editor de una skill en una ventana y guardarla sin recargar la pantalla entera: eso necesita
dos llamadas JSON, y viven aquí para que el transporte (`ui.py`) no crezca y para que la validación
tenga un sitio con nombre.

`root` viaja desde el navegador, así que se **comprueba** contra las raíces que este mismo motor
descubrió al escanear. Sin esa lista, este endpoint sería un lector/escritor de ficheros arbitrario
para cualquier proceso local: el escaneo de skills es la lista blanca.
"""
from . import panels, settings_skills

PATH = "/api/settings/skill"


def _value(source, key, default=""):
    """El valor de `key`, venga de `parse_qs` (lista) o de un formulario ya aplanado (texto)."""
    value = (source or {}).get(key, default)
    if isinstance(value, list):
        value = value[0] if value else default
    return default if value is None else value


def handle(cockpit, method, path, query, body):
    """`(status, payload)`, o `None` cuando el camino no es de este módulo."""
    if path != PATH:
        return None
    editor = panels._protocol("nexus.skills.editor")
    if editor is None:
        return 503, {"ok": False, "reason": "NexusProtocol no es importable"}
    source = body if method == "POST" else query
    name = str(_value(source, "name") or "").strip()
    root = str(_value(source, "root") or "").strip()
    if not name:
        return 400, {"ok": False, "reason": "falta el nombre de la skill"}
    allowed = [str(folder) for _label, folder in settings_skills.roots(cockpit)]
    if root not in allowed:
        return 403, {"ok": False,
                     "reason": "esa ruta no es una de las raíces de skills de este motor"}
    if method == "GET":
        try:
            return 200, editor.read_skill(name, root)
        except ValueError as exc:
            return 404, {"ok": False, "reason": str(exc)}
    try:
        saved = editor.save_skill(name, str(_value(source, "text") or ""), root)
    except ValueError as exc:
        return 400, {"ok": False, "reason": str(exc)}
    return 200, dict(saved, ok=True)
