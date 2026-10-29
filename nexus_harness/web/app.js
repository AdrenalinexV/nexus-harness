/* El núcleo del chat: DOM, red, aviso y estado de esta pantalla.

   `token.js` resolvió la credencial antes que este fichero. Aquí se publica `window.NX`, el único sitio
   del que beben `chat_stream.js`, `sessions.js` y `composer.js`: si cada módulo guardase su copia del
   hilo o de la sesión, la pantalla tendría tres verdades y se desincronizarían al primer turno.

   Reglas: toda interpolación pasa por `esc()`; el estado se pinta desde `/api/*` y nunca se estima. */
const $ = (id) => document.getElementById(id);
const TOKEN = window.NexusToken || '';
// Contrato con el motor (`api.API_VERSION`). 3 = barra en vivo, cola de proyectos y bucle autonomo.
const API_VERSION = 3;

const state = {
  since: 0, session: null, feed: [], sessions: [], polling: false, last: null,
};

function esc(text) {
  return String(text == null ? '' : text)
    .replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
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
  const box = $('warn');
  if (!box) return;
  box.hidden = false;
  box.textContent = message;
}

function icon(name, cls = '') {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', ('icon ' + cls).trim());
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', '#i-' + name);
  svg.appendChild(use);
  return svg;
}

window.NX = {$, api, esc, warn, icon, state, TOKEN, API_VERSION};

/* ---------- el motor que está en marcha ---------- */
async function checkEngine() {
  const {ok, status, data} = await api('/api/health');
  // Un 401 NO es un motor caído y no se arregla relanzando nada: es que a esta página le falta la
  // credencial. Antes las dos cosas se pintaban igual y el consejo mandaba a reiniciar un proceso sano.
  if (status === 401) {
    warn('El motor está en marcha pero pide token: esta página se abrió sin la credencial. Ábrela desde la ventana de escritorio o añade ?token=… a la dirección.');
    return;
  }
  if (status === 403) {
    warn('El motor rechazó la petición por venir de otro sitio (cross-site). Abre la cabina desde su propia dirección.');
    return;
  }
  if (!ok) {
    warn('El motor no contesta a /api/health (' + (status || 'sin respuesta') + '). Si acabas de actualizar el código, cierra esta ventana y vuelve a lanzar Nexus-Harness.bat.');
    return;
  }
  if ((data.api || 0) < API_VERSION) {
    warn(`El motor en marcha es más viejo que esta interfaz (api ${data.api || 0} < ${API_VERSION}): por eso los botones no hacen nada. Cierra esta ventana y vuelve a lanzar Nexus-Harness.bat.`);
  }
}

/* ---------- estado y conversaciones ---------- */
function fillSelect(el, options, value) {
  const current = value || el.value;
  el.innerHTML = options.map((option) => `<option value="${esc(option)}">${esc(option)}</option>`).join('');
  if (options.includes(current)) el.value = current;
}

function paintState(s) {
  const last = (s.chat && s.chat.last) || {};
  const session = (s.chat && s.chat.session) || null;
  state.last = last;
  $('stop').disabled = !s.running;
  $('stop').style.display = s.running ? '' : 'none';
  const chosen = $('project').value && !String($('project').value).startsWith('—');
  $('send').disabled = !chosen;
  $('input').placeholder = chosen
    ? 'Escribe una tarea o una pregunta…  Ctrl+Enter envía'
    : 'Elige un proyecto en el índice para empezar';
  // Sin conversación no hay título de página que enseñar: la portada ya dice qué hacer, y dos
  // titulares compitiendo («sin conversación» + «¿Qué construimos?») es ruido de dashboard.
  const head = document.querySelector('.doc-head');
  if (head) head.hidden = !session;
  $('title').textContent = session ? (session.title || session.id) : '';
  $('doc-meta').textContent = session ? `${session.id} · ${session.turns || 0} turnos` : '';
  const config = s.config || {};
  $('engine').textContent = `${config.host}:${config.port}`;
  $('version').textContent = s.version || '?';
  $('engine-root').textContent = config.root || '';
  if (last.skills && last.skills.length) window.NexusStream.noteSkills(last.skills);
  const projects = (s.models || {}).projects || [];
  // El proyecto de la conversación manda; la raíz del motor solo es el punto de partida.
  const chatProject = (s.chat && s.chat.project) || config.root || '';
  const current = chatProject.split(/[\\/]/).pop();
  const known = projects.includes(current);
  const placeholder = '— elige un proyecto —';
  fillSelect($('project'), known ? projects : [placeholder].concat(projects),
             known ? current : placeholder);
  const options = (s.models || {}).options || [];
  const director = ((s.roles || {}).director) || {};
  fillSelect($('quick-director'), options.length ? options : [director.spec || ''], director.spec);
}

async function refreshState() {
  const {ok, data} = await api('/api/state');
  if (ok) paintState(data);
}

async function swapDirector(spec) {
  if (!spec) return;
  const {ok, data} = await api('/api/roles', {method: 'POST', body: JSON.stringify({role: 'director', spec})});
  if (!ok) warn(data.reason || 'modelo rechazado');
  refreshState();
}

/* ---------- cableado y arranque ---------- */
function wire() {
  $('send').onclick = () => window.NexusComposer.send();
  $('stop').onclick = () => window.NexusComposer.stopTurn();
  $('new-chat').onclick = () => window.NexusSessions.newChat();
  $('session-search').addEventListener('input', () => window.NexusSessions.repaint());
  $('quick-director').addEventListener('change', (event) => swapDirector(event.target.value));
  $('project').addEventListener('change', () => window.NexusSessions.newChat());
  $('input').addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') window.NexusComposer.send();
  });
}

async function boot() {
  wire();
  await checkEngine();
  await refreshState();
  await window.NexusStream.refreshChat();
  await window.NexusSessions.refreshSessions();
  const wanted = new URLSearchParams(location.search).get('project') || '';
  if (wanted) await window.NexusSessions.openProject(wanted);
  window.setInterval(() => window.NexusStream.pollEvents(), 800);
  window.setInterval(refreshState, 2500);
  window.setInterval(() => window.NexusStream.refreshChat(), 2500);
}

document.addEventListener('DOMContentLoaded', boot);
