"""The cockpit page: one HTML file, assembled from three strings so no file owns two languages.

Tokens `__CSS__` and `__JS__` are replaced by `ui.page()`. Nothing else in the page is templated: the
data arrives over `/api/state`, so the page is a viewer and not a server-side render.
"""

HTML = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nexus-Harness — Cabina</title>
<style>__CSS__</style>
</head>
<body>
<header>
  <div class="brand">NEXUS<span>·</span>HARNESS</div>
  <div class="controls">
    <label class="field">Proyecto<select id="project"></select></label>
    <label class="field">Director<select id="role-director"></select></label>
    <label class="field">Obrero<select id="role-worker"></select></label>
    <label class="field">Juez<select id="role-judge"></select></label>
    <span class="pill info" id="status">iniciando</span>
  </div>
</header>

<main>
  <section class="panel">
    <h2>Cabina de trabajo <span class="tag" id="run-meta">sin ejecución</span></h2>
    <div class="goal">
      <div style="flex:1;display:flex;flex-direction:column;gap:8px">
        <textarea id="goal" placeholder="Objetivo para la tríada: qué debe quedar hecho y cómo se sabrá…"></textarea>
        <input id="test-command" placeholder="comando que demuestra el trabajo (opcional; sin él, tests = no configurado)">
      </div>
      <div style="display:flex;flex-direction:column;gap:8px">
        <button id="run">Ejecutar</button>
        <button id="stop" class="ghost" disabled>En cola…</button>
      </div>
    </div>
    <div class="bar"><i id="budget-fill"></i><b id="budget-mark" style="left:70%"></b></div>
    <div class="meta"><span id="budget-text">presupuesto: unmeasured</span><span id="session-id">—</span></div>
    <div class="feed" id="feed"></div>
  </section>

  <section style="display:flex;flex-direction:column;gap:14px">
    <div class="panel">
      <h2>Plan del Director <span class="tag" id="plan-model"></span></h2>
      <div class="cards"><div class="card"><div class="big" id="plan">(sin plan todavía)</div></div></div>
    </div>
    <div class="panel">
      <h2>Skills inyectadas en RAM <span class="tag" id="skills-count">0</span></h2>
      <div class="cards"><div class="card">
        <div class="chips" id="skills"></div>
        <div class="big" style="margin-top:8px;color:var(--dim)" id="skills-note">nada inyectado aún</div>
      </div></div>
    </div>
    <div class="panel">
      <h2>Gate y Juez <span class="tag" id="verdict-exit"></span></h2>
      <div class="cards"><div class="card">
        <h3>Gate determinista</h3>
        <div id="gate" class="big">pendiente</div>
        <h3 style="margin-top:10px">Juez</h3>
        <div id="judge" class="big">pendiente</div>
      </div></div>
    </div>
    <div class="panel">
      <h2>Sesión y auto-relevo <span class="tag" id="relay-tag"></span></h2>
      <div class="cards"><div class="card">
        <div class="big" id="relay">sin sesión</div>
        <ul class="plain" id="sessions" style="margin-top:8px"></ul>
      </div></div>
    </div>
    <div class="panel">
      <h2>Nexus Control Center <span class="tag" id="bridge-tag">0 en cola</span></h2>
      <div class="cards"><div class="card">
        <div class="big" id="bridge">cola leída de .nexus/hive/queue.json</div>
        <ul class="plain" id="bridge-items" style="margin-top:6px"></ul>
        <button class="ghost" id="bridge-run" style="margin-top:10px">Procesar cola</button>
      </div></div>
    </div>
  </section>
</main>
<footer id="footer">Nexus-Harness · local · sin dependencias externas</footer>
<script>__JS__</script>
</body>
</html>
"""


def page(css, js):
    return HTML.replace("__CSS__", css).replace("__JS__", js)
