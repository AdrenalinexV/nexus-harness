"""Los textos del bucle y el bloque de mapa AST: lo que el Director y el Obrero leen en cada llamada.

Vive fuera de `triad_loop.py` por una razon de tamano (ese fichero esta en el techo de 400 lineas) y
por una razon mejor: son datos con fecha, no logica. El prompt del Obrero cambio tres veces mientras se
calibraba el gate, y tenerlos en un sitio con nombre hace que un cambio de prompt sea un cambio de
prompt y no un diff enterrado entre dos `if`.

El bloque del mapa AST (Motor 3) se construye UNA vez por corrida y se cachea por `mtime` en
`repo_map.py`: se inyecta para que el modelo pida `read_file(offset, limit)` en vez de gastar cinco
turnos leyendo ficheros enteros para encontrar una funcion.
"""
from pathlib import Path

DIRECTOR_PROMPT = """Eres el Director de un harness de ingeniería autónomo.
Recibes un objetivo y el estado del repositorio. Devuelve un PLAN BREVE (máximo 6 pasos numerados)
que diga qué hay que cambiar y en qué ficheros, y termina con una línea "Criterio: <cómo se sabrá
que está hecho>". No escribas código, no llames herramientas: solo el plan."""

WORKER_PROMPT = """Eres el Obrero de un harness de ingeniería autónomo. Ejecutas el plan con las
herramientas disponibles.

Reglas que no se negocian:
- Ningún fichero puede pasar de 400 líneas. Si un módulo crece, divídelo.
- Para editar usa `patch` con el texto EXACTO que has leído; si falla por ambigüedad, lee más
  contexto y vuelve a intentarlo. `write_file` es para ficheros nuevos o reescrituras completas.
- Inspecciona antes de escribir: `read_file`, `search`, `list_dir`. Si el mapa de símbolos de abajo te
  dice la línea, pide SOLO ese rango (`read_file(path, offset=X, limit=Y)`): leer 350 líneas para una
  función cuesta tokens que no vuelven.
- No declares nada terminado: el gate lo comprobará. Cuando hayas terminado, responde con un
  resumen de una frase de lo que cambiaste y qué comando lo demuestra."""

REPAIR_PROMPT = """El gate ha devuelto ROJO (exit 10). Esto es lo que ha observado:

%s

Repara exactamente eso con las herramientas y vuelve a dejarlo. No expliques: actúa."""

CLOSE_PROMPT = """Se acabó el presupuesto de pasos. NO llames herramientas. Responde con DOS frases:
qué ficheros cambiaste y con qué comando se demuestra que funciona."""

JUDGE_REJECT = """El Juez rechazó el trabajo: %s

Corrige lo que señala y deja el repositorio en verde otra vez."""

MAP_TOKENS = 800
MAP_CHARS_PER_TOKEN = 4


def facts(root):
    """El estado minimo del repositorio para el Director: raiz y primeras entradas."""
    try:
        entries = sorted(path.name for path in Path(root).iterdir())[:40]
    except OSError:
        entries = []
    return "root: %s\nentries: %s" % (root, ", ".join(entries) or "(empty)")


def map_block(config):
    """`(texto, tokens)` del mapa AST de esta corrida. `("", 0)` si no se puede construir.

    Se guarda en la config (`config.repo_map_block`) porque una corrida llama decenas de veces: el
    mapa se calcula una vez y viaja igual en todas, asi que el coste se cuenta UNA vez por corrida.
    """
    cached = getattr(config, "repo_map_block", None)
    if isinstance(cached, tuple) and len(cached) == 2:
        return cached
    try:
        from .repo_map import RepoMap
        text = RepoMap(config.default_root, max_tokens=MAP_TOKENS).brief()
    except Exception:  # noqa: BLE001 -- sin mapa se trabaja igual, solo menos informado
        text = ""
    block = (text, len(text) // MAP_CHARS_PER_TOKEN if text else 0)
    try:
        config.repo_map_block = block
    except (AttributeError, ValueError) as exc:  # config congelada: se recalcula y se declara
        block = (block[0], block[1], "%s: %s" % (type(exc).__name__, exc))
    return block[:2]


def proof_block(config):
    """La comprobacion que el gate va a ejecutar, escrita para el Obrero.

    Sin esto, un test que comprueba mas de lo que dice el enunciado se convierte en un rojo que el
    modelo no puede explicarse (medido: el Obrero arreglo `add` y no miro `mul`, que el test tambien
    exigia). El Obrero tiene derecho a saber con que se le mide: es lo que hace un buen encargo.
    """
    command = getattr(config, "test_command", None)
    if not command:
        return ""
    return "## Comprobacion que ejecutara el gate\n%s\nDeja ESA comprobacion en verde." % command


def plan_for(triad, goal):
    """El plan del Director, con el estado del repositorio y su coste contado en el ahorro."""
    from .message import Message

    prompt = "OBJETIVO:\n%s\n\nESTADO DEL REPOSITORIO:\n%s" % (goal, facts(triad.config.default_root))
    try:
        reply = triad._ask("director", [Message(role="system", content=DIRECTOR_PROMPT),
                                       Message(role="user", content=prompt)],
                           max_tokens=min(triad.config.max_tokens, 1200))
    except Exception as exc:  # noqa: BLE001 -- sin plan la corrida sigue con el objetivo pelado
        triad._emit("director.error", "%s: %s" % (type(exc).__name__, exc))
        return "(sin plan: %s)" % exc
    triad._emit("director.plan", reply.text[:1500], model=reply.model)
    return reply.text or "(plan vacío)"


def selftest():
    problems = []
    # La raiz del repo se DERIVA, no se escribe: la que estaba clavada era la ruta de la maquina del
    # autor, y en cualquier otra (CI, un portatil) el mapa salia vacio y la suite se ponia roja.
    root = str(Path(__file__).resolve().parents[1])

    def check(name, got, expected):
        if got != expected:
            problems.append("%s: %r, esperaba %r" % (name, got, expected))

    check("el mapa se cachea por config", map_block(_Config(root))[1] > 0, True)
    config = _Config(root)
    first = map_block(config)
    second = map_block(config)
    check("y la segunda llamada no lo recalcula", first is second, True)
    check("el mapa cabe en el techo", first[1] <= MAP_TOKENS + 40, True)
    check("sin proyecto no hay mapa", map_block(_Config("C:/no/existe/xyz"))[1], 0)
    check("los hechos dicen la raiz", "root:" in facts(root), True)
    check("y las entradas", "nexus_harness" in facts(root), True)
    check("los prompts existen", bool(DIRECTOR_PROMPT and WORKER_PROMPT and REPAIR_PROMPT), True)
    check("el prompt del Obrero pide rangos", "offset=X" in WORKER_PROMPT, True)
    check("sin test_command no hay bloque", proof_block(_Config(".")), "")
    check("con test_command se dice cual",
          "pytest -q" in proof_block(_Config(".", test_command="pytest -q")), True)
    check("y se pide dejarlo verde",
          "en verde" in proof_block(_Config(".", test_command="pytest -q")), True)
    return problems


class _Config:
    """Una config minima para probar el mapa sin arrancar el motor."""

    def __init__(self, root, **extra):
        self.default_root = Path(root)
        self.__dict__.update(extra)


if __name__ == "__main__":
    found = selftest()
    for item in found:
        print("FALLO:", item)
    print("triad_brief: %s" % ("OK" if not found else "%d fallos" % len(found)))
    raise SystemExit(1 if found else 0)
