"""Panel 02: la cola de importancia, el alta de proyectos y lo que no esta gobernado.

Lo que cambio y por que: antes eran 28 tarjetas iguales, cada una con un boton azul gigante. Eso no es
una pantalla, es un muro: no decia cual manda ni en que orden, y el operador no tenia donde arrastrar.

Ahora hay tres cosas, en el orden en que se usan:

1. **La cola** (`project_order`): tarjetas compactas, arrastrables (HTML5 nativo, sin libreria) y con
   flechas ↑/↓ para quien prefiere el teclado. El orden se guarda en `~/.nexus/harness.json` y es el
   que obedece el bucle autonomo: primero el #1.
2. **Otras carpetas** en una tabla plegada con buscador: existen, no molestan, y se pueden gobernar
   desde ahi en un clic. Una lista compacta en vez de 28 tarjetas.
3. **El alta**: nombre, objetivo y a trabajar. Crea la carpeta, `git init`, las reglas y el Auto-Spec,
   y la mete al final de la cola.

El boton del Autopilot vive en cada tarjeta porque es una decision POR PROYECTO: lanzar el bucle sobre
el #1 sin decir cual es el #1 es como pedir un taxi sin decir a donde.
"""
from pathlib import Path

from . import onboarding, projects
from . import settings_kit as kit


def _spec_raw(root):
    path = Path(root) / projects.SPEC_REL
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _chips(row):
    """Lo medido de un proyecto, en cuatro pastillas. Un dato ausente se dice, no se rellena."""
    spec = row.get("spec") or {}
    criteria = spec.get("criteria") or 0
    chips = ['<span class="chip %s">%s criterios de spec</span>'
             % ("ok" if criteria else "warn", kit.esc(criteria))]
    if spec.get("sha"):
        chips.append('<span class="chip">sha %s</span>' % kit.esc(spec["sha"]))
    chips.append('<span class="chip %s">%s</span>'
                 % ("ok" if row.get("test") else "off",
                    kit.esc(row["test"] if row.get("test") else "sin comando de test")))
    progress = row.get("progress") or {}
    steps = [one for one in progress.get("steps") or [] if one.get("ok")]
    if progress.get("done"):
        chips.append('<span class="chip ok">100 %% autónomo</span>')
    elif steps:
        chips.append('<span class="chip warn">%d pasos autónomos</span>' % len(steps))
    if row.get("backups"):
        chips.append('<span class="chip">%d backups</span>' % row["backups"])
    return "".join(chips)


def _card(row):
    """Una tarjeta de la cola: puesto, nombre, lo medido y las acciones. Arrastrable."""
    name = row["name"]
    goal = (row.get("spec") or {}).get("goal") or "sin objetivo declarado"
    move = ('<form class="qmove" method="post" action="/api/settings/do">%s%s%s'
            '<button class="ghost" title="Subir un puesto">▲</button></form>'
            '<form class="qmove" method="post" action="/api/settings/do">%s%s%s'
            '<button class="ghost" title="Bajar un puesto">▼</button></form>'
            % (kit.hidden("section", "espacio"), kit.hidden("what", "project_move"),
               kit.hidden("name", name) + kit.hidden("dir", "up"),
               kit.hidden("section", "espacio"), kit.hidden("what", "project_move"),
               kit.hidden("name", name) + kit.hidden("dir", "down")))
    auto = ('<form class="qauto" method="post" action="/api/settings/do">%s%s%s'
            '<input type="number" name="iterations" value="3" min="1" max="50" '
            'title="iteraciones del bucle">'
            '<button class="primary" title="Backup, planifica, ejecuta, verifica y avanza">🚀 Autopilot</button>'
            '</form>'
            % (kit.hidden("section", "espacio"), kit.hidden("what", "autonomy_start"),
               kit.hidden("project", name)))
    spec_form = ('<form class="qmove" method="post" action="/api/settings/do">%s%s%s'
                 '<button class="ghost">Regenerar Auto-Spec</button></form>'
                 % (kit.hidden("section", "espacio"), kit.hidden("what", "auto_spec"),
                    kit.hidden("project", name)))
    # El comando de test del proyecto se guardaba antes en la tarjeta; al rehacerla no se puede perder:
    # es lo que el gate ejecuta, y sin el un proyecto se queda en "sin comando de test" para siempre.
    test = ('<form class="sform qtest" method="post" action="/api/settings">%s'
            '<input name="test:%s" value="%s" placeholder="comando de test (pytest, npm test…)">'
            '<button class="ghost">Guardar test</button></form>'
            % (kit.hidden("section", "espacio"), kit.esc(name), kit.esc(row.get("test") or "")))
    return ('<li class="qcard" draggable="true" data-project="%s">'
            '<span class="qpos"><i class="qgrip" title="arrastra para reordenar" '
            'aria-hidden="true">⠿</i><b class="qnum">#%s</b></span>'
            '<div class="qmain"><div class="qtitle"><strong>%s</strong>'
            '<a class="chip" href="/?project=%s">Abrir en el Chat</a></div>'
            '<p class="qgoal">%s</p><div class="chips">%s</div>%s</div>'
            '<div class="qacts">%s%s%s</div>'
            '<details class="specview"><summary>Ver Spec JSON (qué exige el Gate)</summary>'
            '<pre class="sout">%s</pre></details></li>'
            % (kit.esc(name), kit.esc(row.get("position")), kit.esc(name), kit.esc(name),
               kit.esc(goal), _chips(row), test, move, auto, spec_form,
               kit.esc(_spec_raw(row.get("root")) or "(no se pudo leer el spec)")))


def _create():
    """El alta: un campo para el nombre, otro para el objetivo, un boton. Sin asistentes."""
    return ('<details class="newproj"><summary class="primary-sum">+ Crear Nuevo Proyecto</summary>'
            '<form class="sform" method="post" action="/api/settings/do">'
            + kit.hidden("section", "espacio") + kit.hidden("what", "project_new")
            + '<div class="sgrid">'
            + kit.field("Nombre de la carpeta", '<input name="name" placeholder="Omni-Nexus" required>',
                        "se crea en el workspace, con git y gobernanza")
            + kit.field("Objetivo inicial (prompt semilla)",
                        '<input name="goal" placeholder="qué tiene que llegar a ser este proyecto">')
            + '</div><div class="sactions"><button class="primary">Crear y poner en cola</button>'
              '<span class="dim">carpeta + git init + .ai/CURRENT_SPEC.json (Auto-Spec)</span>'
              '</div></form></details>')


def _plain(names):
    """Las carpetas sin gobernanza: una fila cada una, dentro de un desplegable con buscador."""
    if not names:
        return '<p class="dim">Todas las carpetas del workspace están gobernadas.</p>'
    rows = "".join(
        '<tr data-name="%s"><td><code>%s</code></td><td>'
        '<form class="sform inline" method="post" action="/api/settings/do">%s%s%s'
        '<button class="ghost">Gobernar</button></form></td>'
        '<td><a class="chip" href="/?project=%s">Abrir</a></td></tr>'
        % (kit.esc(name.lower()), kit.esc(name), kit.hidden("section", "espacio"),
           kit.hidden("what", "auto_spec"), kit.hidden("project", name), kit.esc(name))
        for name in names)
    return ('<details class="plainbox"><summary>Ver las %d carpetas sin gobernanza</summary>'
            '<input class="search plainsearch" type="search" placeholder="filtrar carpeta…" '
            'data-filter=".plainbox table tr" aria-label="filtrar carpetas">'
            '<table class="stable plainlist"><thead><tr><th>Carpeta</th><th>Gobernanza</th>'
            '<th>Chat</th></tr></thead><tbody>%s</tbody></table>'
            '<p class="dim">Gobernar genera el Auto-Spec (lenguaje, comando de test y ley de 400) '
            'desde lo que hay en la carpeta: no se inventa nada.</p></details>'
            % (len(names), rows))


def espacio(cockpit):
    """La pantalla entera del panel 02."""
    config = cockpit.config
    rows = projects.queue(config)
    plain = projects.plain(config.workspace)
    autopilot = cockpit.autopilot.state()
    runner = ('<span class="chip %s">Autopilot %s</span>'
              % ("ok" if autopilot.get("running") else "off",
                 kit.esc("ON · %s %d/%d" % (autopilot.get("project") or "",
                                            autopilot.get("iteration") or 0,
                                            autopilot.get("iterations") or 0))
                 if autopilot.get("running") else "OFF"))
    board = ("".join(_card(row) for row in rows)
             or '<li class="dim">Ningún proyecto gobernado todavía: crea uno o gobierna una carpeta.</li>')
    body = ('<div class="sstack">'
            '<div class="boardhead"><div>%s'
            '<p class="dim">Arrastra las tarjetas para ordenar la cola: el bucle autónomo empieza por '
            'el #1. El orden se guarda en <code>harness.json</code>.</p></div>%s</div>'
            '<h3 class="ssub">1 · Cola de importancia <span class="tag">%d gobernados</span></h3>'
            '<ol class="queue" id="queue">%s</ol>'
            '<h3 class="ssub">2 · Otras carpetas del workspace <span class="tag">%d</span></h3>'
            '%s'
            '<h3 class="ssub">3 · Carpeta de proyectos (workspace)</h3>%s'
            '</div>'
            % (runner, _create(), len(rows), board, len(plain), _plain(plain),
               kit.form("/api/settings", "espacio",
                        kit.field("Workspace", '<input name="workspace" value="%s">'
                                  % kit.esc(config.workspace),
                                  "donde viven los proyectos y de donde salen las conversaciones"),
                        submit="Guardar workspace")))
    return ("Espacio de trabajo & Proyectos",
            "Qué proyecto manda, en qué orden, y quién puede correr solo hasta terminarlo.", body)


# -- guardar y actuar -----------------------------------------------------------------------------
def save(cockpit, body):
    """Lo que guarda el formulario del panel: workspace y comandos de test por proyecto."""
    notes = []
    tests = {str(key)[5:]: str(value).strip() for key, value in body.items()
             if str(key).startswith("test:")}
    if tests:
        merged = dict(cockpit.config.project_tests or {})
        for name, command in tests.items():
            if command:
                merged[name] = command
            else:
                merged.pop(name, None)
        saved, problems = onboarding.save_settings({"project_tests": merged})
        notes += problems
        if "project_tests" in saved:
            notes.append("%d comandos de test por proyecto" % len(saved["project_tests"]))
    if "workspace" in body:
        saved, problems = onboarding.save_settings({"workspace": body.get("workspace")})
        notes += problems
        if saved:
            notes.append("espacio de trabajo → %s" % saved.get("workspace", ""))
    cockpit.reload_config()
    return (" · ".join(note for note in notes if note) or "sin cambios", True)


def action(cockpit, body):
    """Las acciones del panel: crear, mover, gobernar y arrancar el bucle. `(nota, ok, seccion)`."""
    what = str(body.get("what") or "")
    if what == "auto_spec":
        return _auto_spec(cockpit, str(body.get("project") or "").strip())
    if what == "project_move":
        names, note = projects.move(cockpit.config, str(body.get("name") or ""),
                                    str(body.get("dir") or "up"))
        cockpit.config.project_order = list(names)
        return (note or "cola reordenada (%d proyectos)" % len(names), True, "espacio")
    if what == "project_new":
        return _create_project(cockpit, body)
    if what == "autonomy_start":
        return _autonomy_start(cockpit, body)
    if what == "autonomy_stop":
        stopped = cockpit.autopilot.stop()
        return ("autopilot: %s" % ("deteniendo" if stopped else "no estaba corriendo"),
                True, "espacio")
    return ("acción desconocida: %s" % what, False, "espacio")


def _auto_spec(cockpit, project):
    if not project:
        return ("falta el nombre del proyecto", False, "espacio")
    result = onboarding.apply(cockpit.config, {"project": project, "governance": True})
    spec = result.get("saved", {}).get("spec") or {}
    ok = bool(result.get("saved", {}).get("governance"))
    if ok:
        cockpit.reload_config()
        return ("Auto-Spec de %s: %s criterios (sha %s)"
                % (project, spec.get("cas_count", "?"), str(spec.get("sha256") or "")[:12]),
                True, "espacio")
    return ("%s · %s" % (project, "; ".join(result.get("notes") or ["sin cambios"])), False,
            "espacio")


def _create_project(cockpit, body):
    name = str(body.get("name") or "").strip()
    result = projects.create(cockpit.config, name, str(body.get("goal") or ""))
    if not result.get("ok"):
        return (result.get("reason") or "no se pudo crear", False, "espacio")
    cockpit.config.project_order = list(result.get("order") or [])
    cockpit.bus.emit("project.created", result["name"], root=result["root"])
    notes = [note for note in result.get("notes") or [] if note]
    spec = (result.get("governance") or {})
    return ("proyecto %s creado%s · git %s · spec %s%s"
            % (result["name"], " y gobernado" if spec.get("ok") else " (sin gobernanza)",
               "sí" if result.get("git") else "no",
               "sha %s" % str(spec.get("sha256") or "")[:10] if spec.get("ok") else "pendiente",
               (" · " + "; ".join(notes)) if notes else ""), True, "espacio")


def _autonomy_start(cockpit, body):
    project = str(body.get("project") or "").strip()
    try:
        iterations = int(body.get("iterations") or 3)
    except (TypeError, ValueError):
        iterations = 3
    if cockpit.busy:
        return ("hay un turno en marcha: el bucle espera a que acabe", False, "espacio")
    ok, payload = cockpit.autopilot.start(project=project, iterations=iterations,
                                         goal=str(body.get("goal") or ""))
    if not ok:
        return ("autopilot no arrancó: %s" % payload, False, "espacio")
    return ("autopilot ON sobre %s · %d iteraciones · backup previo en cada ciclo"
            % (project or (payload.get("queue") or ["cola"])[0], iterations), True, "espacio")
