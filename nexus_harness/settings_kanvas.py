"""El panel del manual que lleva al tablero: qué hay hecho en cada proyecto y qué toca ahora.

No repite la cola de importancia del §03 (esa se ordena allí, con arrastre); aquí se LEE el tablero de
cada proyecto y se abre el que interese. Dos puertas, una sola verdad: el orden y el estado salen de
`projects.queue` y de `.nexus/kanvas.json`, nunca de una copia.
"""
from pathlib import Path

from . import projects
from . import settings_kit as kit
from .platform.kanvas import Board


def _one(cockpit, row):
    """Una fila de la cola con el estado de su tablero: porcentaje, siguiente tarea y enlace."""
    name = row.get("name") or ""
    root = Path(row.get("root") or "")
    try:
        board = Board.load(root)
        stats = board.stats()
        ready = board.ready()
        doing = [task for task in board.tasks if board.effective(task) in ("doing", "review")]
    except Exception as exc:  # noqa: BLE001 -- un tablero ilegible se declara, no tumba el panel
        return ('<li class="kanvas-row bad"><span class="folio">%02d</span><b>%s</b>'
                '<span class="dim">tablero ilegible: %s: %s</span></li>'
                % (row.get("position") or 0, kit.esc(name), type(exc).__name__, kit.esc(str(exc))))
    now = doing[0].title if doing else (ready[0].title if ready else "sin tareas listas")
    if not stats["total"]:
        now = "sin tablero todavía"
    # token.js estampa la credencial en los enlaces internos de esta pantalla.
    link = '/kanvas?project=%s' % kit.esc(name)
    return ('<li class="kanvas-row">'
            '<div class="krow-top"><span class="folio">%02d</span><b>%s</b>'
            '<span class="mono">%d/%d · %d%%</span></div>'
            '<span class="kbar-mini"><i style="width:%d%%"></i></span>'
            '<div class="krow-bot"><span class="dim">ahora: %s</span>'
            '<a class="navlink" href="%s">abrir tablero</a></div></li>'
            % (row.get("position") or 0, kit.esc(name), stats["done"], stats["total"],
               stats["percent"], stats["percent"], kit.esc(now[:90]), link))


def panel(cockpit):
    rows = projects.queue(cockpit.config)
    body = ('<h3 class="ssub">Qué es</h3>'
            '<p class="dim">Cada proyecto tiene su tablero en <code>.nexus/kanvas.json</code>: carriles, '
            'tareas y dependencias. Una tarea solo pasa a <b>done</b> con el Gate en verde y, en modo '
            'yolo, con el Juez de acuerdo; el estado <b>blocked</b> lo calcula el motor con las flechas.</p>'
            '<h3 class="ssub">Proyectos en orden de importancia <span class="tag">%d</span></h3>'
            '<p class="dim">El orden es el del §03 <i>Espacio de trabajo</i>: el bucle autónomo empieza '
            'por el #1. Aquí se lee el estado; para mover la cola, arrastra allí.</p>'
            '<ol class="queue kanvas-queue">%s</ol>'
            '<p><a class="navlink" href="/kanvas">Abrir el tablero</a></p>'
            % (len(rows), "".join(_one(cockpit, row) for row in rows)
               or '<li class="dim">Ningún proyecto gobernado todavía.</li>'))
    return ("Tablero (Kanvas)",
            "Lo que está hecho en cada proyecto, qué toca ahora y el grafo de dependencias.", body)
