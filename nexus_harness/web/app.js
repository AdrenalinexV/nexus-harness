/* Nexus-Harness — el chat. Una pagina, un motor: lo que carga la ventana de escritorio y lo que
   carga el navegador, asi que un arreglo aqui lo es en los dos. Sin framework y sin build.

   Reglas de este fichero:
   - Toda interpolacion pasa por esc(); lo unico sin escapar es el marcado fijo que escribe el propio
     fichero. El hilo lleva salida de un modelo: no es decoracion.
   - Nada de la barra lateral derecha: se quito. La configuracion vive en `/settings` y lo que pasa
     durante un turno (tool, gate, juez, skills) se cuenta EN EL HILO, en una tira discreta.
   - `API_VERSION` es el contrato con el motor. Si el proceso en marcha es mas viejo que esta pagina,
     se dice en una banda: un boton que no responde es la peor forma de enterarse. */

const $ = (id) => document.getElementById(id);
const TOKEN = new URLSearchParams(location.search).get('token') || '';
const WANTED = new URLSearchParams(location.search).get('project') || '';
// Contrato con el motor (`api.API_VERSION`). 3 = barra en vivo, cola de proyectos y bucle autonomo.
const API_VERSION = 3;
let since = 0, currentSession = null, polling = false, allSessions = [], feed = [];

const LABEL = {
  'chat.user': 'TÚ', 'chat.assistant': 'NEXUS', 'chat.turn': 'TURNO', 'chat.repair': 'REPARACIÓN',
  'chat.stopped': 'DETENIDO', 'chat.new': 'NUEVA', 'chat.load': 'ABIERTA', 'chat.limit': 'LÍMITE',
  'tool.call': 'TOOL', 'skills.injected': 'SKILLS', 'gate.verdict': 'GATE', 'judge.verdict': 'JUEZ',
  'worker.reasoning': 'RAZÓN', 'worker.error': 'ERROR', 'memory.add': 'MEMORIA',
  'memory.remove': 'MEMORIA-', 'bridge.claim': 'PUENTE', 'bridge.close': 'PUENTE',
  'tool.parallel': 'PARALELO', 'subagent.start': 'SUBAGENTES', 'subagent.result': 'SUBAGENTE',
  'subagent.tool': 'SUB-TOOL', 'subagent.end': 'SUBAGENTES', 'subagent.limit': 'SUB-LÍMITE',
  'chat.stopping': 'DETENIENDO', 'run.stopping': 'DETENIENDO', 'worker.stopped': 'DETENIDO',
  'session.relay': 'RELEVO', 'chat.rename': 'RENOMBRADA', 'skills.saved': 'SKILL',
};

function esc(text) {
  return String(text == null ? '' : text).replace(/[&<>]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;'}[c]));
}

function api(path, options = {}) {
  const headers = Object.assign({'Content-Type': 'application/json'}, options.headers || {});
  if (TOKEN) headers['X-Nexus-Token'] = TOKEN;
  return fetch(path, Object.assign({}, options, {headers})).then(async (response) => {
    const data = await response.json().catch(() => ({}));
    return {ok: response.ok, status: response.status, data};
  });
}

function warn(message) {
  $('warn').hidden = false;
  $('warn').textContent = message;
}

/* ---------- el motor que esta en marcha ---------- */
async function checkEngine() {
  const {ok, data} = await api('/api/health');
  if (!ok) {
    warn('El motor no contesta a /api/health. Si acabas de actualizar el código, cierra esta ventana y vuelve a lanzar Nexus-Harness.bat.');
    return;
  }
  if ((data.api || 0) < API_VERSION) {
    warn(`El motor en marcha es más viejo que esta interfaz (api ${data.api || 0} < ${API_VERSION}): por eso los botones no hacen nada. Cierra esta ventana y vuelve a lanzar Nexus-Harness.bat.`);
  }
}

/* ---------- hilo ---------- */
function msgText(content) {
  if (Array.isArray(content)) {
    return content.filter((part) => part && part.type === 'text' && !String(part.text || '').startsWith('<document'))
      .map((part) => part.text || '').join('\n').trim();
  }
  return String(content || '');
}

function msgAttachments(message) {
  if (!Array.isArray(message.content)) return [];
  return message.content.filter((part) => part && part.type !== 'text')
    .map((part) => ({name: 'imagen', kind: 'image', preview: (part.image_url || {}).url || ''}));
}

function addMessage(role, text, meta) {
  const wrap = document.createElement('div');
  wrap.className = 'msg ' + role;
  wrap.innerHTML = `<div class="who">${role === 'user' ? 'TÚ' : 'NEXUS'}</div>
                    <div class="bubble">${esc(text)}</div>`;
  if (meta && meta.attachments && meta.attachments.length) {
    const box = document.createElement('div');
    box.className = 'tools';
    for (const item of meta.attachments) {
      const chip = document.createElement('span');
      chip.className = 'attach';
      chip.textContent = `${item.kind === 'image' ? '🖼' : '📄'} ${item.name}`;
      if (item.preview) chip.style.backgroundImage = `url(${item.preview})`;
      box.appendChild(chip);
    }
    wrap.appendChild(box);
  }
  if (meta && meta.tools && meta.tools.length) {
    const chips = document.createElement('div');
    chips.className = 'tools';
    for (const tool of meta.tools) {
      const chip = document.createElement('span');
      chip.className = 'tool' + (tool.ok === false ? ' bad' : '');
      chip.textContent = tool.name + (tool.ok === false ? ' ✕' : '');
      chip.title = ((tool.args ? JSON.stringify(tool.args) : '') + '\n' + (tool.result || '')).slice(0, 600);
      chips.appendChild(chip);
    }
    wrap.appendChild(chips);
  }
  $('thread').appendChild(wrap);
  $('thread').scrollTop = $('thread').scrollHeight;
  return wrap;
}

/* La tira de lo que pasa durante el turno: dentro del hilo, al final, discreta. Es lo que antes vivia
   en una barra lateral derecha fija, que sobraba en el chat. */
function paintFeed() {
  const box = $('inline');
  if (!box) return;
  box.innerHTML = '';
  for (const row of feed.slice(-14)) {
    const line = document.createElement('div');
    line.className = 'feed-row' + (row.kind === 'gate.verdict' || row.kind === 'judge.verdict' ? ' gate' : '');
    const detail = String(row.detail || '');
    if (row.kind.endsWith('.reasoning')) {
      /* El pensamiento de un modelo local (Qwen/DeepSeek) no se tira ni se mezcla con la respuesta:
         va en un bloque plegable, entero y escapado. Un `<details>` no rompe el parser ni el JSON del
         juez, y el operador puede leerlo sin que ocupe la conversacion. */
      const fold = document.createElement('details');
      fold.className = 'reasoning';
      fold.innerHTML = `<summary><span class="k">${esc(LABEL[row.kind] || row.kind)}</span>
        <span class="d">${esc(detail.slice(0, 120))}</span></summary>
        <pre>${esc(detail)}</pre>`;
      box.appendChild(fold);
      continue;
    }
    line.innerHTML = `<span class="k">${esc(LABEL[row.kind] || row.kind)}</span>
                      <span class="d">${esc(detail.slice(0, 160))}</span>`;
    box.appendChild(line);
  }
  if (feed.length) $('thread').scrollTop = $('thread').scrollHeight;
}

function renderThread(messages) {
  const thread = $('thread');
  thread.innerHTML = '';
  if (!messages.length) {
    thread.innerHTML = `<div class="empty"><h1>¿Qué construimos?</h1>
      <p>Pide una tarea o haz una pregunta. El gate (lint Nexus, ley de 400, tests) se ejecuta en cuanto
      se toca un fichero; si sale rojo, el obrero lo repara antes de contestarte.</p>
      <p class="dim">El modelo de la tríada, las claves, la memoria y las skills se cambian en
      <a href="/settings">Configuración</a>.</p></div>`;
  } else {
    const pending = {};
    for (const message of messages) {
      if (message.role === 'user') {
        addMessage('user', msgText(message.content) || '·', {attachments: msgAttachments(message)});
      } else if (message.role === 'assistant') {
        const tools = (message.tool_calls || []).map((call) => {
          let args = {};
          try { args = JSON.parse(call.function.arguments || '{}'); } catch (error) { args = {}; }
          const tool = {name: call.function.name, args, id: call.id, ok: true};
          pending[tool.id] = tool;
          return tool;
        });
        if ((message.content || '').trim() || tools.length) {
          addMessage('assistant', (message.content || '').trim() || '·', {tools});
        }
      } else if (message.role === 'tool') {
        const tool = pending[message.tool_call_id];
        if (tool) {
          tool.result = message.content || '';
          tool.ok = !String(message.content || '').startsWith('ERROR');
        }
      }
    }
  }
  const inline = document.createElement('div');
  inline.id = 'inline';
  inline.className = 'inline-feed';
  thread.appendChild(inline);
  paintFeed();
  thread.scrollTop = thread.scrollHeight;
}

/* ---------- estado y conversaciones ---------- */
function fillSelect(el, options, value) {
  const current = value || el.value;
  el.innerHTML = options.map((option) => `<option value="${esc(option)}">${esc(option)}</option>`).join('');
  if (options.includes(current)) el.value = current;
}

function paintState(s) {
  const run = s.run || {};
  const last = (s.chat && s.chat.last) || {};
  // La pildora de la esquina NO se pinta aqui: la lleva `activity.js` desde `/api/activity`, que sabe
  // la fase viva y el progreso. Este `state()` solo manda lo que es de esta pantalla.
  $('stop').disabled = !s.running;
  $('stop').style.display = s.running ? '' : 'none';
  const chosen = $('project').value && $('project').value !== '— elige un proyecto —';
  $('send').disabled = !chosen;
  $('input').placeholder = chosen
    ? 'Escribe una tarea o una pregunta…  (Ctrl+Enter envía)'
    : 'Elige un proyecto en la barra lateral para empezar';
  $('title').textContent = (s.chat && s.chat.session && (s.chat.session.title || s.chat.session.id))
    || 'sin conversación';
  $('engine').textContent = `${s.config.host}:${s.config.port} · ${s.config.root}`;
  if (last.skills && last.skills.length && !feed.some((row) => row.kind === 'skills.injected')) {
    feed.push({kind: 'skills.injected', detail: last.skills.join(', ')});
    paintFeed();
  }
  void run;
  const projects = (s.models || {}).projects || [];
  // The conversation's project is the authority, not the engine's start directory.
  const chatProject = (s.chat && s.chat.project) || s.config.root;
  const current = chatProject.split(/[\\/]/).pop();
  const known = projects.includes(current);
  const placeholder = '— elige un proyecto —';
  fillSelect($('project'), known ? projects : [placeholder].concat(projects),
             known ? current : placeholder);
  const options = (s.models || {}).options || [];
  const director = ((s.roles || {}).director) || {};
  fillSelect($('quick-director'), options.length ? options : [director.spec || ''], director.spec);
}

function matchesSession(row, needle) {
  return !needle || `${row.title || ''} ${row.id || ''}`.toLowerCase().includes(needle);
}

function paintSessions(rows) {
  allSessions = rows || [];
  const needle = String($('session-search').value || '').trim().toLowerCase();
  const list = $('sessions');
  list.innerHTML = '';
  const visible = allSessions.filter((row) => matchesSession(row, needle));
  if (!visible.length) {
    const empty = document.createElement('li');
    empty.className = 'dim';
    empty.textContent = allSessions.length ? 'sin resultados' : 'todavía ninguna';
    list.appendChild(empty);
    return;
  }
  for (const row of visible) {
    const item = document.createElement('li');
    if (row.id === currentSession) item.className = 'active';
    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = `${row.title || row.id} · ${row.turns || 0}`;
    name.title = row.id;
    name.onclick = () => loadSession(row.id);
    item.appendChild(name);
    for (const [glyph, label, handler] of [['✎', 'renombrar', () => renameSession(row)],
                                           ['✕', 'borrar', () => deleteSession(row)]]) {
      const act = document.createElement('span');
      act.className = 'act';
      act.textContent = glyph;
      act.title = label;
      act.onclick = (event) => { event.stopPropagation(); handler(); };
      item.appendChild(act);
    }
    list.appendChild(item);
  }
}

/* ---------- datos ---------- */
async function refreshState() {
  const {ok, data} = await api('/api/state');
  if (ok) paintState(data);
}

async function refreshChat() {
  const {ok, data} = await api('/api/chat');
  if (!ok) return;
  const next = data.session ? data.session.id : null;
  if (next !== currentSession) { since = 0; feed = []; }
  currentSession = next;
  renderThread(data.messages || []);
}

async function refreshSessions() {
  const {ok, data} = await api('/api/sessions');
  if (ok) paintSessions(data.sessions);
}

/* ---------- acciones ---------- */
async function send() {
  const attachments = (window.NexusUI && window.NexusUI.take()) || [];
  const text = $('input').value.trim();
  if (!text && !attachments.length) return;
  $('input').value = '';
  addMessage('user', text || '·', {attachments: attachments.map((item) => ({
    name: item.name, kind: item.kind, preview: item.preview || ''}))});
  const {ok, status, data} = await api('/api/chat',
    {method: 'POST', body: JSON.stringify({text, attachments})});
  if (!ok) {
    addMessage('assistant', status === 409 ? 'Ya hay un turno en marcha.' : (data.reason || 'no se pudo enviar'));
    return;
  }
  setTimeout(refreshChat, 700);
}

async function stopTurn() {
  await api('/api/stop', {method: 'POST', body: '{}'});
}

async function newChat() {
  const project = $('project').value;
  if (!project || project === '— elige un proyecto —') return;
  const {ok, data} = await api('/api/chat/new', {method: 'POST', body: JSON.stringify({project})});
  if (!ok) return;
  currentSession = data.session ? data.session.id : null;
  feed = [];
  renderThread([]);
  since = 0;
  refreshSessions();
}

async function loadSession(id) {
  const {ok} = await api('/api/chat/load', {method: 'POST', body: JSON.stringify({id})});
  if (!ok) return;
  currentSession = id;
  since = 0;
  await refreshChat();
  refreshSessions();
}

async function renameSession(row) {
  const title = window.prompt('Nuevo título de la conversación', row.title || row.id);
  if (title === null || !title.trim()) return;
  const {ok} = await api('/api/chat/rename',
    {method: 'POST', body: JSON.stringify({id: row.id, title: title.trim()})});
  if (ok) refreshSessions();
  else warn('No se pudo renombrar la conversación.');
}

async function deleteSession(row) {
  if (!window.confirm(`¿Borrar «${row.title || row.id}»? No se puede deshacer.`)) return;
  const {ok} = await api('/api/chat/delete', {method: 'POST', body: JSON.stringify({id: row.id})});
  if (!ok) {
    warn('No se pudo borrar la conversación.');
    return;
  }
  if (row.id === currentSession) {
    currentSession = null;
    feed = [];
    renderThread([]);
  }
  refreshSessions();
}

async function swapDirector(spec) {
  if (!spec) return;
  const {ok, data} = await api('/api/roles', {method: 'POST', body: JSON.stringify({role: 'director', spec})});
  if (!ok) warn(data.reason || 'modelo rechazado');
  refreshState();
}

async function pollEvents() {
  if (polling) return;
  polling = true;
  try {
    const {ok, data} = await api('/api/events?since=' + since);
    if (!ok) return;
    for (const event of data.events || []) {
      since = Math.max(since, event.seq);
      if (!LABEL[event.kind]) continue;
      feed.push({kind: event.kind, detail: event.detail || ''});
    }
    if ((data.events || []).length) paintFeed();
  } finally { polling = false; }
}

/* ---------- wiring ---------- */
$('send').onclick = send;
$('stop').onclick = stopTurn;
$('new-chat').onclick = newChat;
$('session-search').addEventListener('input', () => paintSessions(allSessions));
$('quick-director').addEventListener('change', (event) => swapDirector(event.target.value));
$('input').addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') send();
});
$('project').addEventListener('change', newChat);

async function openProject(name) {
  const option = Array.from($('project').options).find((item) => item.value === name);
  if (!option) return;
  $('project').value = name;
  if (!currentSession) await newChat();
}

(async function boot() {
  await checkEngine();
  await refreshState();
  await refreshChat();
  await refreshSessions();
  if (WANTED) await openProject(WANTED);
  setInterval(pollEvents, 800);
  setInterval(refreshState, 2500);
  setInterval(refreshChat, 2500);
})();
