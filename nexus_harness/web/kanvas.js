/* El tablero vivo: la cola de proyectos a la izquierda, UN proyecto a la derecha, y el bus (SSE) para
   refrescar. Nada de estado propio que pueda mentir: lo que se pinta es lo que devuelve `/api/kanvas`, y
   cada accion vuelve a pedirlo. Las flechas son bezier calculadas desde la posicion real de las entradas,
   asi que siguen siendo ciertas cuando la ventana cambia de ancho. */
window.NexusKanvas = (function () {
  const $ = (id) => document.getElementById(id);
  const TOKEN = window.NexusToken || '';
  const STATUS_ORDER = ['proposed', 'blocked', 'todo', 'doing', 'review', 'done'];
  // Lo que esta vivo primero; lo cerrado, al final y atenuado: asi se lee que toca sin contar ids.
  const WEIGHT = {doing: 0, review: 1, todo: 2, blocked: 3, proposed: 4, done: 5};
  const params = new URLSearchParams(location.search);
  const state = {board: null, filter: '', since: 0, running: false, source: null,
                 project: params.get('project') || ''};

  function esc(text) {
    return String(text == null ? '' : text)
      .replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  }

  async function api(path, options = {}) {
    const headers = Object.assign({'Content-Type': 'application/json'}, options.headers || {});
    if (TOKEN) headers['X-Nexus-Token'] = TOKEN;
    try {
      const response = await fetch(path, Object.assign({}, options, {headers}));
      const data = await response.json().catch(() => ({}));
      return {ok: response.ok, status: response.status, data};
    } catch (error) {
      return {ok: false, status: 0, data: {reason: 'sin respuesta del motor'}};
    }
  }

  function warn(text) {
    const box = $('k-warn');
    box.textContent = text || '';
    box.hidden = !text;
  }

  function url() {
    return '/api/kanvas' + (state.project ? '?project=' + encodeURIComponent(state.project) : '');
  }

  async function load() {
    const {ok, data} = await api(url());
    if (!ok) { warn('el motor no contesta a /api/kanvas'); return; }
    state.board = data;
    paintRail();
    paint();
  }

  /* Todo lo que entra por `innerHTML` pasa por `esc()`; las flechas solo llevan numeros.
     Un titulo de tarea lo escribe un modelo, asi que se trata como texto, nunca como marcado. */
  function card(task) {
    const el = document.createElement('article');
    el.className = 'ktask' + (task.status === 'done' ? ' closed' : '');
    el.dataset.id = task.id;
    el.dataset.status = task.status;
    el.dataset.deps = (task.depends_on || []).join(',');
    el.innerHTML =
      '<header><span class="kid">' + esc(task.id) + '</span>' +
      '<span class="kst">' + esc(task.status) + '</span></header>' +
      '<p class="ktitle">' + esc(task.title) + '</p>';
    const foot = document.createElement('footer');
    if (task.assigned_to) {
      const who = document.createElement('span');
      who.className = 'kwho';
      who.textContent = '@' + task.assigned_to;
      foot.appendChild(who);
    }
    if (task.pending && task.pending.length) {
      const wait = document.createElement('span');
      wait.className = 'kwho';
      wait.textContent = 'espera ' + task.pending.join(', ');
      foot.appendChild(wait);
    }
    if (task.yolo) {
      const mark = document.createElement('span');
      mark.className = 'kyolo';
      mark.textContent = 'yolo';
      foot.appendChild(mark);
    }
    for (const [label, action, show] of [
      ['Tomar', 'claim', (task.status === 'todo' || task.status === 'proposed') &&
        !(task.pending || []).length],
      ['Aprobar', 'approve', task.status === 'review'],
      ['Devolver', 'send_back', task.status === 'review' || task.status === 'doing'],
      ['yolo', 'toggle_yolo', task.status !== 'done'],
    ]) {
      if (!show) continue;
      const button = document.createElement('button');
      button.className = 'kact';
      button.type = 'button';
      button.dataset.act = action;
      button.textContent = label;
      button.title = action === 'approve' ? 'Cierra la tarea (el gate queda en la evidencia)'
        : action === 'toggle_yolo' ? 'Ejecucion autonoma gobernada por Gate y Juez'
        : action;
      button.onclick = () => act(action, {task: task.id});
      foot.appendChild(button);
    }
    el.appendChild(foot);
    if (!visible(task)) el.classList.add('hidden');
    return el;
  }

  function visible(task) {
    if (!state.filter) return true;
    const needle = state.filter.toLowerCase();
    return [task.id, task.title, task.track, task.status].join(' ').toLowerCase().includes(needle);
  }

  /* La cola de proyectos: el #1 es el que arranca el autopilot. Los botones suben/bajan el puesto y
     escriben la MISMA cola que el panel de Espacio de trabajo (`harness.json`), no una copia. */
  function paintRail() {
    const list = $('k-projects');
    const rows = (state.board && state.board.portfolio) || [];
    list.innerHTML = '';
    for (const row of rows) {
      const li = document.createElement('li');
      const mine = row.name === state.board.project;
      li.className = 'kproj' + (mine ? ' on' : '');
      const folio = document.createElement('span');
      folio.className = 'folio';
      folio.textContent = String(row.position || 0).padStart(2, '0');
      const link = document.createElement('a');
      link.className = 'kproj-name';
      link.href = '/kanvas?project=' + encodeURIComponent(row.name);
      link.textContent = row.name;
      const pct = document.createElement('span');
      pct.className = 'mono kproj-pct';
      pct.textContent = row.error ? '?' : (row.percent || 0) + '%';
      li.appendChild(folio);
      li.appendChild(link);
      li.appendChild(pct);
      if (!row.error) {
        const bar = document.createElement('span');
        bar.className = 'kproj-bar';
        bar.innerHTML = '<i style="width:' + Number(row.percent || 0) + '%"></i>';
        li.appendChild(bar);
        const next = document.createElement('span');
        next.className = 'kproj-next';
        next.textContent = row.next ? 'ahora: ' + row.next : 'sin tareas listas';
        li.appendChild(next);
      }
      const order = document.createElement('span');
      order.className = 'kproj-order';
      for (const [glyph, dir, title] of [['\u2191', 'up', 'Sube este proyecto en la cola'],
                                         ['\u2193', 'down', 'Baja este proyecto en la cola']]) {
        const button = document.createElement('button');
        button.className = 'kact';
        button.type = 'button';
        button.textContent = glyph;
        button.title = title;
        button.onclick = () => act('move_project', {project: row.name, dir});
        order.appendChild(button);
      }
      li.appendChild(order);
      list.appendChild(li);
    }
  }

  function paint() {
    const board = state.board;
    if (!board) return;
    $('k-project').textContent = board.project || 'sin nombre';
    $('k-updated').textContent = board.updated_at || '';
    $('k-percent').textContent = (board.stats.percent || 0) + '%';
    $('k-counts').innerHTML = STATUS_ORDER.map((name) =>
      '<li><b>' + (board.stats.counts[name] || 0) + '</b> ' + name + '</li>').join('');
    const alive = board.tasks.filter((task) => task.status === 'doing' || task.status === 'review');
    const now = $('k-now');
    now.hidden = !alive.length;
    now.textContent = alive.length
      ? 'En marcha: ' + alive.map((task) => task.id + ' ' + task.title).join(' \u00b7 ')
      : '';
    const lanes = $('k-lanes');
    lanes.innerHTML = '';
    const tracks = board.tracks && board.tracks.length ? board.tracks : [{id: 'core', title: 'Core'}];
    for (const track of tracks) {
      const tasks = board.tasks.filter((task) => task.track === track.id)
        .sort((a, b) => (WEIGHT[a.status] - WEIGHT[b.status]) || a.id.localeCompare(b.id));
      if (!tasks.length) continue;
      const lane = document.createElement('section');
      lane.className = 'klane';
      const head = document.createElement('h2');
      head.innerHTML = esc(track.title || track.id) + '<span>' + tasks.length + ' tareas</span>';
      const box = document.createElement('div');
      box.className = 'ktasks';
      for (const task of tasks) box.appendChild(card(task));
      lane.appendChild(head);
      lane.appendChild(box);
      lanes.appendChild(lane);
    }
    $('k-empty').hidden = Boolean(board.tasks.length);
    $('k-stop').hidden = !state.running;
    window.requestAnimationFrame(edges);
  }

  function edges() {
    const svg = $('k-edges');
    const board = $('k-board');
    if (!svg || !board) return;
    const frame = board.getBoundingClientRect();
    svg.setAttribute('viewBox', '0 0 ' + board.clientWidth + ' ' + board.clientHeight);
    const cards = new Map();
    for (const el of board.querySelectorAll('.ktask')) {
      if (!el.classList.contains('hidden')) cards.set(el.dataset.id, el);
    }
    const parts = [];
    for (const el of cards.values()) {
      const child = el.getBoundingClientRect();
      for (const dep of (el.dataset.deps || '').split(',').filter(Boolean)) {
        const parent = cards.get(dep);
        if (!parent) continue;
        const p = parent.getBoundingClientRect();
        const x1 = p.right - frame.left, y1 = p.top - frame.top + p.height / 2;
        const x2 = child.left - frame.left, y2 = child.top - frame.top + child.height / 2;
        const bend = Math.max(26, Math.abs(x2 - x1) / 2);
        const hot = el.dataset.status === 'doing' || el.dataset.status === 'blocked' ? ' hot' : '';
        parts.push('<path class="edge' + hot + '" d="M' + x1 + ',' + y1 + ' C' + (x1 + bend) + ',' +
                   y1 + ' ' + (x2 - bend) + ',' + y2 + ' ' + x2 + ',' + y2 + '"/>');
      }
    }
    svg.innerHTML = parts.join('');
  }

  async function act(action, payload) {
    const body = Object.assign({action}, payload || {});
    const result = await api('/api/kanvas', {method: 'POST', body: JSON.stringify(body)});
    if (!result.ok || result.data.ok === false) {
      warn(result.data.reason || result.data.detail || ('el motor respondio ' + result.status));
      return;
    }
    warn('');
    await load();
  }

  async function decompose(goal) {
    const text = 'Descompon este objetivo en el tablero: usa kanvas_board(action="decompose") con ' +
      'tareas pequenas y verificables (title, track, depends_on, verify_cmd) y despues ' +
      'kanvas_board(action="status") para confirmar. Objetivo: ' + goal;
    const result = await api('/api/chat', {method: 'POST', body: JSON.stringify({text})});
    warn(result.ok ? 'el Director esta descomponiendo; el tablero se refrescara solo'
      : (result.data.reason || 'no se pudo pedir la descomposicion'));
  }

  function startEvents() {
    if (!window.EventSource) { window.setInterval(load, 4000); return; }
    const token = TOKEN ? '&token=' + encodeURIComponent(TOKEN) : '';
    state.source = new EventSource('/api/events/stream?since=' + state.since + token);
    state.source.onmessage = (message) => {
      let event;
      try { event = JSON.parse(message.data); } catch (error) { return; }
      state.since = Math.max(state.since, Number(event.seq) || 0);
      if (String(event.kind || '').startsWith('kanvas.')) {
        if (event.kind === 'kanvas.chain') {
          state.running = false;
          $('k-stop').hidden = true;
          warn('cadena terminada: ' + (event.detail || ''));
        }
        load();
      }
    };
  }

  function wire() {
    $('k-filter').addEventListener('input', (event) => {
      state.filter = event.target.value.trim();
      paint();
    });
    $('k-add').onclick = () => {
      const title = window.prompt('Titulo de la tarea');
      if (!title) return;
      const track = window.prompt('Carril (core, ui, tests, release)', 'core') || 'core';
      act('add', {title, track});
    };
    $('k-decompose').onclick = () => {
      const goal = window.prompt('Objetivo a descomponer');
      if (goal) decompose(goal);
    };
    $('k-yolo').onclick = () => act('yolo_all', {chain: true});
    $('k-run').onclick = async () => {
      const result = await api('/api/kanvas',
        {method: 'POST', body: JSON.stringify({action: 'yolo_run', project: state.project})});
      if (!result.ok) { warn(result.data.reason || 'no se pudo arrancar la cadena'); return; }
      state.running = true;
      $('k-stop').hidden = false;
      warn('cadena en marcha: ' + (result.data.ready || []).join(', '));
    };
    $('k-stop').onclick = () => act('yolo_stop', {});
    window.addEventListener('resize', () => window.requestAnimationFrame(edges));
  }

  wire();
  load();
  startEvents();
  window.setInterval(() => { if (!state.source) load(); }, 4000);
  return {load, act, edges, state};
}());
