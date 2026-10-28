"""Los proveedores que esta maquina YA usa, descubiertos en vez de pedidos otra vez.

El fallo que cierra: la cabina decia «no hay ninguna llave de nube en la bóveda» mientras el operador
trabajaba a diario contra `orca` (`https://api.orcarouter.ai/v1`, modelo `deepseek/deepseek-v4.1-flash`)
configurado en Hermes. La verdad estaba a dos ficheros de distancia, y el arnes no la miraba.

De donde se lee, en este orden y sin copiar secretos a ningun sitio nuevo:

1. **La configuracion de Hermes** (`%LOCALAPPDATA%/hermes/config.yaml` y sus perfiles): el bloque
   `providers:` con `base_url` y `key_env`. De ahi sale el ENDPOINT, que es lo que faltaba.
2. **La boveda del arnes** (`~/.nexus/secrets.json`, por DPAPI) y **el entorno** del proceso. De ahi
   sale la CLAVE, si esta. Si la clave solo vive dentro de Hermes, este modulo NO la inventa ni la
   copia: lo dice (`key_env` conocido, clave no visible) para que se pegue una vez en Seguridad.

`enrich(config)` añade los proveedores que falten, en memoria y sin pisar los que ya existan: el
`harness.json` del operador manda siempre. Lo que se gana es que `orca` sea un proveedor de primera
clase — aparece en el selector de proveedor y en los presets, sin tocar la configuracion a mano.

El lector de YAML es deliberadamente minimo (dos niveles, solo el bloque `providers:`): el motor
congelado no lleva PyYAML y una dependencia nueva por leer cuatro claves no se paga.
"""
import os
import re
from pathlib import Path

BLOCK = re.compile(r"^(?P<indent>\s*)providers:\s*$")
ENTRY = re.compile(r"^(?P<indent>\s{2})(?P<name>[A-Za-z0-9_.-]+):\s*$")
FIELD = re.compile(r"^(?P<indent>\s{4})(?P<key>[a-z_]+):\s*(?P<value>.+?)\s*$")
LOCAL_HOSTS = ("127.0.0.1", "localhost", "0.0.0.0", "[::1]")


def hermes_homes():
    """Las carpetas de configuracion de Hermes que existen en esta maquina."""
    roots = []
    for variable in ("LOCALAPPDATA", "APPDATA"):
        base = os.environ.get(variable)
        if base:
            roots.append(Path(base) / "hermes")
    homes = []
    for root in roots:
        if not root.is_dir():
            continue
        homes.append(root / "config.yaml")
        profiles = root / "profiles"
        if profiles.is_dir():
            homes.extend(sorted(profiles.glob("*/config.yaml")))
    return [path for path in homes if path.is_file()]


def read_providers(path):
    """`[{name, base_url, key_env}]` del bloque `providers:` de un config de Hermes."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found, current, inside = [], None, False
    for line in text.splitlines():
        if BLOCK.match(line):
            inside = True
            continue
        if not inside:
            continue
        if line.strip() and not line.startswith((" ", "\t")):
            break               # otro bloque de primer nivel: se acabo `providers:`
        entry = ENTRY.match(line)
        if entry:
            current = {"name": entry.group("name"), "base_url": "", "key_env": ""}
            found.append(current)
            continue
        field = FIELD.match(line)
        if field and current is not None:
            key = field.group("key")
            if key in ("base_url", "key_env"):
                current[key] = field.group("value").strip("'\"")
    return [row for row in found if row.get("base_url")]


def _is_local(url):
    return any(host in str(url or "") for host in LOCAL_HOSTS)


def _builtin(name):
    from .providers import VENDORS
    return str(name or "") in VENDORS


def candidates(config=None):
    """Los proveedores descubiertos, con su endpoint y si la clave es alcanzable desde aqui.

    Un endpoint repetido (el mismo `orca` en el config global y en tres perfiles) se cuenta UNA vez:
    cuatro filas iguales no son cuatro proveedores, son ruido. Y un nombre que el motor ya conoce de
    serie (`ollama`, `openai`...) se marca `builtin` y NO se importa: sustituir el transporte nativo de
    Ollama por el shim `/v1` de Hermes romperia `thinking` y las herramientas nativas.
    """
    secrets = dict(getattr(config, "secrets", None) or {})
    known = dict(getattr(config, "providers", None) or {})
    rows, seen_names, seen_urls = [], set(), set()
    for path in hermes_homes():
        for row in read_providers(path):
            name = row["name"]
            url = str(row.get("base_url") or "").rstrip("/")
            if name in seen_names or url in seen_urls:
                continue
            seen_names.add(name)
            seen_urls.add(url)
            env_name = row.get("key_env") or ""
            value = secrets.get(env_name) or os.environ.get(env_name, "")
            rows.append({"name": name, "base_url": row["base_url"], "key_env": env_name,
                         "secret": value, "local": _is_local(row["base_url"]),
                         "source": "hermes:%s" % path.parent.name,
                         "declared": name in known, "builtin": _builtin(name)})
    return rows


def enrich(config):
    """Añade a `config` los proveedores descubiertos que falten. Devuelve los nombres añadidos.

    No pisa nada declarado por el operador, y no escribe en disco: la clave se queda donde ya estaba
    (entorno o boveda) y solo viaja en memoria. Un secreto copiado a un segundo fichero es un secreto
    que ahora hay que proteger dos veces.
    """
    added = []
    providers = dict(getattr(config, "providers", None) or {})
    secrets = dict(getattr(config, "secrets", None) or {})
    for row in candidates(config):
        if row["declared"] or row.get("builtin"):
            continue
        providers[row["name"]] = {"wire": "openai", "base_url": row["base_url"],
                                  "keys": [row["key_env"]] if row["key_env"] else [],
                                  "local": bool(row["local"]), "origin": row["source"]}
        if row["secret"] and row["key_env"] and row["key_env"] not in secrets:
            secrets[row["key_env"]] = row["secret"]
        added.append(row["name"])
    if added:
        config.providers = providers
        config.secrets = secrets
    return added


def pending_key(config):
    """Proveedores descubiertos cuyo endpoint esta pero cuya clave no es visible desde el arnes.

    Son los que el panel debe ofrecer con un campo para pegarla UNA vez (va a la boveda DPAPI, no al
    fichero de configuracion).
    """
    return [row["name"] for row in candidates(config)
            if not row["secret"] and row.get("key_env") and not row.get("builtin")]


def selftest():
    problems = []

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    import tempfile
    sample = """model:
  provider: orca
providers:
  ollama:
    name: ollama
    base_url: http://127.0.0.1:11434/v1
    key_env: HERMES_CUSTOM_OLLAMA_API_KEY
  orca:
    name: orca
    base_url: https://api.orcarouter.ai/v1
    key_env: HERMES_CUSTOM_ORCA_API_KEY
    discover_models: true
agent:
  verbose: false
"""
    with tempfile.TemporaryDirectory(prefix="proveedores-") as room:
        path = Path(room) / "config.yaml"
        path.write_text(sample, encoding="utf-8")
        rows = read_providers(path)
        check("lee los dos proveedores", len(rows), 2)
        check("con su nombre", rows[1]["name"], "orca")
        check("su base_url", rows[1]["base_url"], "https://api.orcarouter.ai/v1")
        check("y el nombre de la variable de la clave", rows[1]["key_env"],
              "HERMES_CUSTOM_ORCA_API_KEY")
        check("no se cuela el siguiente bloque", any(row["name"] == "agent" for row in rows), False)
        check("un fichero que no existe no rompe", read_providers(Path(room) / "nada.yaml"), [])

    check("una url local se reconoce", _is_local("http://127.0.0.1:11434/v1"), True)
    check("una url de nube no", _is_local("https://api.orcarouter.ai/v1"), False)

    class Config:
        providers = {}
        secrets = {"HERMES_CUSTOM_ORCA_API_KEY": "sk-x"}

    with tempfile.TemporaryDirectory(prefix="proveedores-2-") as room:
        path = Path(room) / "config.yaml"
        path.write_text(sample, encoding="utf-8")
        original = globals()["hermes_homes"]
        globals()["hermes_homes"] = lambda: [path]
        try:
            config = Config()
            rows = candidates(config)
            check("el descubrimiento ve orca", [row["name"] for row in rows], ["ollama", "orca"])
            check("y sabe que la clave esta", rows[1]["secret"], "sk-x")
            added = enrich(config)
            check("se añade orca como proveedor de primera clase", sorted(added), ["orca"])
            check("y NO se pisa el ollama nativo", "ollama" in config.providers, False)
            check("con cable openai", config.providers["orca"]["wire"], "openai")
            check("y su endpoint", config.providers["orca"]["base_url"],
                  "https://api.orcarouter.ai/v1")
            check("un segundo pase no duplica", enrich(config), [])
            config.providers["orca"]["base_url"] = "https://otro/v1"
            enrich(config)
            check("lo declarado por el operador no se pisa", config.providers["orca"]["base_url"],
                  "https://otro/v1")
        finally:
            globals()["hermes_homes"] = original
    return problems


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("provider_discovery: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
