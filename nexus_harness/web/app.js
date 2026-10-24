/* Nexus-Harness client. One page, one engine: this file is what the desktop window and the browser
   load, so a fix here is a fix in both. No framework, no build step: vanilla DOM and fetch.

   Every interpolation below goes through esc(); the only unescaped strings are fixed markup this file
   writes itself. The thread carries model output, so that is not decoration. */

const $ = (id) => document.getElementById(id);
const TOKEN = new URLSearchParams(location.search).get('token') || '';
let since = 0, currentSession = null, polling = false;

const LABEL = {
  'chat.user': 'TÚ', 'chat.assistant': 'NEXUS', 'chat.turn': 'TURNO', 'chat.repair': 'REPARACIÓN',
  'chat.stopped': 'DETENIDO', 'chat.new': 'NUEVA', 'chat.load': 'ABIERTA', 'chat.limit': 'LÍMITE',
  'tool.call': 'TOOL', 'skills.injected': 'SKILLS', 'gate.verdict': 'GATE', 'judge.verdict': 'JUEZ',
  'worker.reasoning': 'RAZÓN', 'worker.error': 'ERROR', 'memory.add': 'MEMORIA',
  'memory.remove': 'MEMORIA-', 'bridge.claim': 'PUENTE', 'bridge.close': 'PUENTE',
  'tool.parallel': 'PARALELO', 'subagent.start': 'SUBAGENTES', 'subagent.result': 'SUBAGENTE',
  'subagent.tool': 'SUB-TOOL', 'subagent.end': 'SUBAGENTES', 'subagent.limit': 'SUB-LÍMITE',
  'chat.stopping': 'DETENIENDO', 'run.stopping': 'DETENIENDO', 'worker.stopped': 'DETENIDO',
  'session.relay': 'RELEVO',
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

/* ---------- thread ---------- */
function addMessage(role, text, meta) {
  const wrap = document.createElement('div');
  wrap.className = 'msg ' + role;
  wrap.innerHTML = `<div class="who">${role === 'user' ? 'TÚ' : 'NEXUS'}</div>
                    <div class="bubble">${esc(text)}</div>`;
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

function renderThread(messages) {
  $('thread').innerHTML = '';
  if (!messages.length) {
    $('thread').innerHTML = `<div class="empty"><h1>¿Qué construimos?</h1>
      <p>Pide una tarea o haz una pregunta. El gate (lint Nexus, ley de 400, tests) se ejecuta en cuanto
      se toca un fichero; si sale rojo, el obrero lo repara antes de contestarte.</p></div>`;
    return;
  }
  const pending = {};
  for (const message of messages) {
    if (message.role === 'user') {
      addMessage('user', message.content || '');
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
  $('thread').scrollTop = $('thread').scrollHeight;
}

/* ---------- panels ---------- */
function setSkills(names) {
  const list = names || [];
  $('skills-count').textContent = list.length ? String(list.length) : '';
  $('skills').innerHTML = list.map((name) => `<span>${esc(name)}</span>`).join('');
}

function fillSelect(el, options, value) {
  const current = value || el.value;
  el.innerHTML = options.map((option) => `<option value="${esc(option)}">${esc(option)}</option>`).join('');
  if (options.includes(current)) el.value = current;
}

function paintState(s) {
  const run = s.run || {};
  const last = (s.chat && s.chat.last) || {};
  const budget = (run.budget && run.budget.limit) ? run.budget
    : ((s.chat && s.chat.budget && s.chat.budget.limit) ? s.chat.budget
      : ((s.relay || {}).budget || {}));
  const limit = budget.limit || 0, used = budget.used || 0;
  const ratio = budget.ratio == null ? 0 : Math.min(1, budget.ratio);
  $('budget-fill').style.width = (ratio * 100).toFixed(1) + '%';
  $('budget-text').textContent = limit
    ? `${used}/${limit} tokens · ${(ratio * 100).toFixed(0)}% (relevo al 70%)` : 'unmeasured';
  const green = Boolean(last.verdict && last.verdict.ok && (last.verdict.checks || []).length);
  $('status').textContent = s.running ? 'trabajando' : green ? 'verde' : last.exit ? 'rojo' : 'en reposo';
  $('status').className = 'pill ' + (s.running ? 'warn' : green ? 'ok' : last.exit ? 'bad' : 'info');
  $('stop').disabled = !s.running;
  const chosen = $('project').value && $('project').value !== '— elige un proyecto —';
  $('send').disabled = !chosen;
  $('input').placeholder = chosen
    ? 'Escribe una tarea o una pregunta…  (Ctrl+Enter envía)'
    : 'Elige un proyecto en la barra lateral para empezar';
  $('bridge').textContent = `${(s.bridge || {}).pending || 0} en cola`;
  $('title').textContent = (s.chat && s.chat.session && (s.chat.session.title || s.chat.session.id))
    || 'sin conversación';
  $('engine').textContent = `${s.config.host}:${s.config.port} · ${s.config.root}`;
  if (last.verdict && (last.verdict.checks || []).length) {
    const checks = (last.verdict.checks || []).map((c) =>
      `<span class="pill ${c.ok ? 'ok' : 'bad'}">${esc(c.name)}</span>`).join(' ');
    $('gate').innerHTML = `<span class="pill ${last.verdict.ok ? 'ok' : 'bad'}">exit ${last.verdict.exit}</span> ${checks}`;
  }
  if (last.judgement && last.judgement.verdict) {
    const j = last.judgement;
    $('judge').innerHTML = `<span class="pill ${j.verdict === 'approve' ? 'ok' : j.verdict === 'skipped' ? 'warn' : 'bad'}">${esc(j.verdict)}</span> ${esc((j.reason || '').slice(0, 140))}`;
  }
  $('last-turn').textContent = last.steps
    ? `${last.steps} pasos · ${last.repairs || 0} reparaciones · ${(last.touched || []).length} ficheros`
      + ((last.touched || []).length ? '\n' + (last.touched || []).join(', ') : '')
    : 'todavía nada';
  if (last.skills) setSkills(last.skills);
  $('memory-count').textContent = `${(s.memory || {}).count || 0}`;
  const projects = (s.models || {}).projects || [];
  // The conversation's project is the authority, not the engine's start directory.
  const chatProject = (s.chat && s.chat.project) || s.config.root;
  const current = chatProject.split(/[\\/]/).pop();
  const known = projects.includes(current);
  const placeholder = '— elige un proyecto —';
  fillSelect($('project'), known ? projects : [placeholder].concat(projects),
             known ? current : placeholder);
  const options = (s.models || {}).options || [];
  for (const role of ['director', 'worker', 'judge']) {
    const info = (s.roles || {})[role] || {};
    fillSelect($('role-' + role), options.length ? options : [info.spec || ''], info.spec);
  }
}

function paintSessions(rows) {
  const list = $('sessions');
  list.innerHTML = '';
  for (const row of rows || []) {
    const item = document.createElement('li');
    item.textContent = `${row.title || row.id} · ${row.turns || 0}`;
    item.title = row.id;
    if (row.id === currentSession) item.className = 'active';
    item.onclick = () => loadSession(row.id);
    list.appendChild(item);
  }
}

function paintMemory(memory) {
  $('memory-count').textContent = `${memory.count || 0}/${memory.limit_entries || '?'}`;
  $('memory').innerHTML = (memory.entries || []).map((entry, index) =>
    `<li><span>${esc(entry)}</span><b data-index="${index}">✕</b></li>`).join('');
  for (const button of $('memory').querySelectorAll('b')) {
    button.onclick = async () => {
      const entry = memory.entries[Number(button.dataset.index)];
      await api('/api/memory', {method: 'POST', body: JSON.stringify({remove: entry})});
      refreshMemory();
    };
  }
}

/* ---------- data ---------- */
async function refreshState() {
  const {ok, data} = await api('/api/state');
  if (ok) paintState(data);
}

async function refreshChat() {
  const {ok, data} = await api('/api/chat');
  if (!ok) return;
  const next = data.session ? data.session.id : null;
  if (next !== currentSession) { since = 0; $('activity').innerHTML = ''; }
  currentSession = next;
  renderThread(data.messages || []);
  if (data.last && data.last.skills) setSkills(data.last.skills);
}

async function refreshSessions() {
  const {ok, data} = await api('/api/sessions');
  if (ok) paintSessions(data.sessions);
}

async function refreshMemory() {
  const {ok, data} = await api('/api/memory');
  if (ok) paintMemory(data);
}

/* ---------- actions ---------- */
async function send() {
  const text = $('input').value.trim();
  if (!text) return;
  $('input').value = '';
  addMessage('user', text);
  const {ok, status, data} = await api('/api/chat', {method: 'POST', body: JSON.stringify({text})});
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
  const {ok, data} = await api('/api/chat/new',
    {method: 'POST', body: JSON.stringify({project})});
  if (!ok) return;
  currentSession = data.session ? data.session.id : null;
  renderThread([]);
  $('activity').innerHTML = '';
  since = 0;
  refreshSessions();
}

async function loadSession(id) {
  const {ok} = await api('/api/chat/load', {method: 'POST', body: JSON.stringify({id})});
  if (!ok) return;
  currentSession = id;
  since = 0;
  $('activity').innerHTML = '';
  await refreshChat();
  refreshSessions();
}

async function swapRole(role, spec) {
  const {ok, data} = await api('/api/roles', {method: 'POST', body: JSON.stringify({role, spec})});
  if (!ok) addMessage('assistant', data.reason || 'modelo rechazado');
}

async function pollEvents() {
  if (polling) return;
  polling = true;
  try {
    const {ok, data} = await api('/api/events?since=' + since);
    if (!ok) return;
    for (const event of data.events || []) {
      since = Math.max(since, event.seq);
      const kind = LABEL[event.kind];
      if (!kind) continue;
      if (event.kind === 'skills.injected') setSkills((event.payload || {}).names || []);
      const row = document.createElement('div');
      row.innerHTML = `<span class="k">${kind}</span> ${esc((event.detail || '').slice(0, 120))}`;
      $('activity').appendChild(row);
      while ($('activity').children.length > 60) $('activity').removeChild($('activity').firstChild);
    }
    $('activity').scrollTop = $('activity').scrollHeight;
  } finally { polling = false; }
}

/* ---------- wiring ---------- */
$('send').onclick = send;
$('stop').onclick = stopTurn;
$('new-chat').onclick = newChat;
$('input').addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') send();
});
for (const role of ['director', 'worker', 'judge']) {
  $('role-' + role).addEventListener('change', (event) => swapRole(role, event.target.value));
}
$('project').addEventListener('change', newChat);
$('memory-add').onclick = async () => {
  const text = $('memory-input').value.trim();
  if (!text) return;
  await api('/api/memory', {method: 'POST', body: JSON.stringify({text})});
  $('memory-input').value = '';
  refreshMemory();
  refreshState();
};

(async function boot() {
  await refreshState();
  await refreshChat();
  await refreshSessions();
  await refreshMemory();
  setInterval(pollEvents, 800);
  setInterval(refreshState, 2500);
  setInterval(refreshChat, 2500);
})();
