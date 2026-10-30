/* El núcleo del chat: DOM, red, aviso y estado de esta pantalla.

   `token.js` resolvió la credencial antes que este fichero. Aquí se publica `window.NX`, el único sitio
   del que beben `chat_stream.js`, `sessions.js` y `composer.js`: si cada módulo guardase su copia del
   hilo o de la sesión, la pantalla tendría tres verdades y se desincronizarían al primer turno.

   Reglas: toda interpolación pasa por `esc()`; el estado se pinta desde `/api/*` y nunca se estima. */
const $ = (id) => document.getElementById(id);
const TOKEN = window.NexusToken || '';
// Contrato con el motor (`api.API_VERSION`). 4 = SSE en /api/events/stream y `worker.delta`.
const API_VERSION = 4;

const state = {
  since: 0, session: null, feed: [], sessions: [], polling: false, last: null, engineApi: 0,
  failures: 0, offline: false,
  // El hilo como documento: `{folio, role, text, tools, attachments}`. Lo llena `chat_stream.js` y lo
  // lee `export.js`, para que el .md salga con los MISMOS folios que están en pantalla.
  doc: [],
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
  // Un aviso escrito a mano retira la banda de reintento: el texto de `#warn` tiene un solo dueño.
  state.offline = false;
  delete box.dataset.kind;
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
  let result;
  try {
    result = await api('/api/health');
  } catch (error) {
    // Sin motor no hay respuesta que leer: no se aborta el arranque, el sondeo levanta la banda.
    return;
  }
  const {ok, status, data} = result;
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
  // Lo que el motor dice de si mismo. `chat_stream` solo abre SSE contra un motor que lo sirve.
  state.engineApi = data.api || 0;
  // Arrancar en la cabeza del bus: al abrir la ventana no se reproduce el turno de ayer en la tira.
  if (!state.since && data.seq) state.since = data.seq;
  if (state.engineApi < API_VERSION) {
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
  if (last.skills && last.skills.length) window.NexusStream.noteSkills(last.skills);
  const projects = (s.models || {}).projects || [];
  // El proyecto de la conversación manda; la raíz del motor solo es el punto de partida.
  const chatProject = (s.chat && s.chat.project) || config.root || '';
  const current = chatProject.split(/[\\/]/).pop();
  const known = projects.includes(current);
  const placeholder = '— elige un proyecto —';
  fillSelect($('project'), known ? projects : [placeholder].concat(projects),
             known ? current : placeholder);
}

/* ---------- la banda de reintento ----------
   Si el motor deja de contestar, el sondeo falla en silencio y la pantalla se queda congelada sin decir
   por qué. A los tres sondeos seguidos (≈5 s con el intervalo de 2,5 s) se levanta esta banda con un
   botón que reintenta YA; en cuanto un sondeo vuelve, la banda se retira sola. */
const OFFLINE_AFTER = 3;

function showOffline() {
  const box = $('warn');
  if (!box || state.offline) return;
  state.offline = true;
  box.dataset.kind = 'offline';
  // Marcado fijo, CERO interpolación: la banda no lleva datos del motor, así que no hay nada que
  // escapar aquí (toda cifra o texto del motor sigue pasando por `esc()`).
  box.innerHTML = '<span>motor sin respuesta</span> · '
    + '<button id="retry" type="button">Reintentar</button>';
  const retry = $('retry');
  if (retry) retry.onclick = () => { refreshState(); };
  box.hidden = false;
}

function hideOffline() {
  const box = $('warn');
  if (!box || !state.offline) return;
  state.offline = false;
  box.hidden = true;
  box.innerHTML = '';
  delete box.dataset.kind;
}

function markReachable(reachable) {
  if (reachable) {
    state.failures = 0;
    hideOffline();
    return;
  }
  state.failures += 1;
  if (state.failures >= OFFLINE_AFTER) showOffline();
}

async function refreshState() {
  // Con la pestaña oculta no se sondea: gastar bateria/CPU por un panel que nadie mira es ruido.
  if (document.hidden) return;
  let result;
  try {
    result = await api('/api/state');
  } catch (error) {
    // Red caída: `fetch` rechaza y no hay respuesta que leer. No es un motor lento: no contesta nadie.
    markReachable(false);
    return;
  }
  if (result.ok) paintState(result.data);
  // 401/403 dicen que el motor ESTÁ: contesta, lo que falta es la credencial. Eso no es "sin respuesta"
  // y no debe levantar la banda de reintento.
  markReachable(result.ok || result.status === 401 || result.status === 403);
}



/* ---------- la hoja de atajos (`?`) ----------
   Sin framework y sin dependencias: un `<dialog>` nativo, marcado fijo (cero interpolación) y se abre
   con la tecla `?` salvo que el foco esté en un campo de texto. */
const SHORTCUTS = [
  ['Ctrl + Enter', 'enviar el mensaje'],
  ['Esc', 'cerrar el panel de estado o este cuadro'],
  ['Ctrl + K', 'buscar en la configuración (allí)'],
  ['?', 'esta lista'],
  ['↑ ↓', 'recorrer el índice · Enter abre'],
  ['Tab', 'saltar al hilo (primer Tab)'],
];

function buildHelp() {
  const dialog = document.createElement('dialog');
  dialog.className = 'helpdlg';
  dialog.setAttribute('aria-label', 'Atajos de teclado');
  const rows = SHORTCUTS.map(([key, what]) =>
    `<div class="helprow"><kbd>${key}</kbd><span>${what}</span></div>`).join('');
  dialog.innerHTML = `<header><strong>Atajos</strong>
      <button class="ghost" type="button" data-close>Cerrar</button></header>
    <div class="helpbody">${rows}</div>`;
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog || event.target.closest('[data-close]')) dialog.close();
  });
  document.body.appendChild(dialog);
  return dialog;
}

let helpDialog = null;
function toggleHelp() {
  helpDialog = helpDialog || buildHelp();
  if (helpDialog.open) { helpDialog.close(); return; }
  helpDialog.showModal();
}

document.addEventListener('keydown', (event) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((event.target.tagName || '').toUpperCase());
  if (event.key === '?' && !typing && !event.ctrlKey && !event.metaKey) {
    event.preventDefault();
    toggleHelp();
  }
});

/* ---------- cableado y arranque ---------- */
function wire() {
  $('send').onclick = () => window.NexusComposer.send();
  $('stop').onclick = () => window.NexusComposer.stopTurn();
  $('new-chat').onclick = () => window.NexusSessions.newChat();
  $('session-search').addEventListener('input', () => window.NexusSessions.repaint());
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
  window.NexusStream.startEvents();
  window.setInterval(refreshState, 2500);
  window.setInterval(() => window.NexusStream.refreshChat(), 2500);
}

document.addEventListener('DOMContentLoaded', boot);
