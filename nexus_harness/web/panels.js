/* The four product surfaces, as one file the composer and the rail share.

   Everything here talks to a real endpoint; nothing pretends. Three rules kept deliberately:

   * **Attachments are read in the browser but normalised on the engine.** The UI sends bytes; the
     server decides the mime, resizes, refuses and stages them, so a pasted screenshot and a dropped
     file follow exactly one code path.
   * **The modal is built with DOM nodes and textContent.** Skill bodies and model names are data.
   * **A failure is shown where it happened** (`modal-note`, the connector row), never in an alert. */

(function () {
  const $ = (id) => document.getElementById(id);
  const TOKEN = new URLSearchParams(location.search).get('token') || '';
  const IMAGE = /^image\//;
  const MAX_MB = 8;

  async function api(path, options = {}) {
    const headers = Object.assign({'Content-Type': 'application/json'}, options.headers || {});
    if (TOKEN) headers['X-Nexus-Token'] = TOKEN;
    const response = await fetch(path, Object.assign({}, options, {headers}));
    const data = await response.json().catch(() => ({}));
    return {ok: response.ok, status: response.status, data};
  }

  /* ---------- attachments ---------- */
  const pending = [];

  function paintPending() {
    const box = $('pending');
    box.textContent = '';
    pending.forEach((item, index) => {
      const chip = document.createElement('span');
      chip.className = 'attach';
      chip.textContent = `${item.kind === 'image' ? '🖼' : '📄'} ${item.name}`;
      if (item.preview) chip.style.backgroundImage = `url(${item.preview})`;
      const remove = document.createElement('b');
      remove.textContent = '×';
      remove.onclick = () => { pending.splice(index, 1); paintPending(); };
      chip.appendChild(remove);
      box.appendChild(chip);
    });
  }

  function base64Of(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const raw = String(reader.result || '');
        resolve(raw.includes(',') ? raw.split(',').pop() : raw);
      };
      reader.onerror = () => reject(new Error('no se pudo leer el fichero'));
      reader.readAsDataURL(file);
    });
  }

  async function addFiles(files) {
    for (const file of Array.from(files || [])) {
      const kind = IMAGE.test(file.type || '') ? 'image' : 'document';
      if (file.size > MAX_MB * 1024 * 1024) {
        $('modal-note').textContent = `${file.name}: supera ${MAX_MB} MB`;
        continue;
      }
      try {
        const data = await base64Of(file);
        pending.push({name: file.name, kind, data,
                      preview: kind === 'image' ? `data:${file.type};base64,${data}` : ''});
      } catch (error) {
        $('modal-note').textContent = `${file.name}: ${error.message}`;
      }
    }
    paintPending();
  }

  document.addEventListener('paste', (event) => {
    const files = Array.from((event.clipboardData || {}).items || [])
      .filter((item) => item.kind === 'file').map((item) => item.getAsFile())
      .filter(Boolean);
    if (files.length) { event.preventDefault(); addFiles(files); }
  });

  const composer = document.querySelector('.composer');
  if (composer) {
    composer.addEventListener('dragover', (event) => { event.preventDefault(); composer.classList.add('drag'); });
    composer.addEventListener('dragleave', () => composer.classList.remove('drag'));
    composer.addEventListener('drop', (event) => {
      event.preventDefault();
      composer.classList.remove('drag');
      addFiles(event.dataTransfer.files);
    });
  }

  $('attach').onclick = () => $('file').click();
  $('file').onchange = (event) => { addFiles(event.target.files); event.target.value = ''; };

  /* ---------- modal ---------- */
  let onSave = null;

  function openModal(title, body, saveHandler, note = '') {
    $('modal-title').textContent = title;
    $('modal-body').textContent = '';
    $('modal-body').appendChild(body);
    $('modal-note').textContent = note;
    onSave = saveHandler;
    $('modal').hidden = false;
  }

  function closeModal() { $('modal').hidden = true; onSave = null; }
  $('modal-close').onclick = closeModal;
  $('modal').addEventListener('click', (event) => { if (event.target === $('modal')) closeModal(); });

  $('modal-save').onclick = async () => {
    if (!onSave) return;
    $('modal-note').textContent = 'guardando…';
    const message = await onSave();
    $('modal-note').textContent = message || 'guardado';
  };

  function field(label, node) {
    const wrap = document.createElement('label');
    wrap.className = 'field';
    const span = document.createElement('span');
    span.textContent = label;
    wrap.append(span, node);
    return wrap;
  }

  function select(options, value) {
    const el = document.createElement('select');
    for (const option of options) {
      const item = document.createElement('option');
      item.value = option;
      item.textContent = option;
      el.appendChild(item);
    }
    if (options.includes(value)) el.value = value;
    return el;
  }

  /* ---------- onboarding ---------- */
  async function openOnboarding() {
    const {ok, data} = await api('/api/onboarding');
    if (!ok) return;
    const body = document.createElement('div');
    const heading = document.createElement('p');
    heading.className = 'dim mono';
    const alive = ['lmstudio', 'ollama']
      .map((name) => `${name}: ${(data.local || {})[name] && data.local[name].ready
        ? `${(data.local[name].models || []).length} modelos` : 'apagado'}`).join(' · ');
    heading.textContent = `Detectado ahora — ${alive}`;
    body.appendChild(heading);

    const choices = [];
    for (const [vendor, row] of Object.entries(data.local || {})) {
      for (const model of row.models || []) choices.push(`${vendor}:${model}`);
    }
    const roles = {};
    for (const role of ['director', 'worker', 'judge']) {
      const current = (data.roles || {})[role] || {};
      const options = [current.spec || '', ...choices, 'openai:gpt-4o-mini',
                       'anthropic:claude-sonnet-4-5', 'deepseek:deepseek-chat']
        .filter((value, index, all) => value && all.indexOf(value) === index);
      const el = select(options, current.spec || '');
      roles[role] = el;
      body.appendChild(field(role[0].toUpperCase() + role.slice(1), el));
    }

    const projectList = document.createElement('datalist');
    projectList.id = 'project-options';
    for (const name of data.projects || []) {
      const option = document.createElement('option');
      option.value = name;
      projectList.appendChild(option);
    }
    const project = document.createElement('input');
    project.value = data.project || '';
    project.setAttribute('list', 'project-options');
    body.append(projectList, field('Proyecto', project));

    const keys = {};
    for (const name of ['OPENROUTER_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY']) {
      const input = document.createElement('input');
      input.type = 'password';
      input.placeholder = (data.keys || []).includes(name) ? 'guardada (DPAPI)' : 'no configurada';
      keys[name] = input;
      body.appendChild(field(name, input));
    }

    const governance = document.createElement('input');
    governance.type = 'checkbox';
    governance.checked = !(data.governance || {}).complete;
    body.appendChild(field('Generar gobernanza (.ai/CURRENT_SPEC.json)', governance));

    openModal('Configuración', body, async () => {
      const payload = {roles: {}, project: project.value.trim(), governance: governance.checked,
                       keys: {}};
      for (const [role, el] of Object.entries(roles)) if (el.value) payload.roles[role] = el.value;
      for (const [name, input] of Object.entries(keys)) if (input.value.trim()) payload.keys[name] = input.value.trim();
      const saved = await api('/api/onboarding', {method: 'POST', body: JSON.stringify(payload)});
      if (!saved.ok) return saved.data.reason || 'no se pudo guardar';
      const notes = (saved.data.notes || []).join(' · ');
      if (window.refreshState) window.refreshState();
      return notes || 'guardado: modelos y proyecto aplicados';
    }, (data.governance || {}).complete ? 'gobernanza ya presente' : 'se generará la spec inicial');
  }

  /* ---------- skills ---------- */
  async function openSkill(name) {
    const {ok, data} = await api('/api/skills?name=' + encodeURIComponent(name));
    if (!ok) return;
    const body = document.createElement('div');
    const meta = document.createElement('p');
    meta.className = 'dim mono';
    meta.textContent = `${data.path} · ${data.lines} líneas · sha ${String(data.sha256).slice(0, 12)}`;
    const area = document.createElement('textarea');
    area.className = 'editor';
    area.value = data.text;
    body.append(meta, area);
    openModal(`SKILL.md — ${data.name}`, body, async () => {
      const saved = await api('/api/skills', {method: 'POST',
        body: JSON.stringify({name: data.name, text: area.value})});
      if (!saved.ok) return saved.data.reason || 'rechazado';
      return `guardado · sha ${String(saved.data.sha256 || '').slice(0, 12)} · ${saved.data.provenance}`;
    }, 'el contrato se valida antes de escribir');
  }

  /* ---------- connectors and the mobile bridge ---------- */
  async function refreshMCP() {
    const {ok, data} = await api('/api/mcp');
    if (!ok) return;
    const list = $('mcp');
    list.textContent = '';
    $('mcp-count').textContent = data.tools ? String(data.tools) : '';
    for (const server of data.servers || []) {
      const row = document.createElement('li');
      row.textContent = `${server.ready ? '●' : '○'} ${server.name} · ${(server.tools || []).length} tools`;
      row.title = server.error || '';
      list.appendChild(row);
    }
    if (!(data.servers || []).length) {
      const row = document.createElement('li');
      row.className = 'dim';
      row.textContent = 'sin conectores';
      list.appendChild(row);
    }
  }

  async function refreshDaemon() {
    const {ok, data} = await api('/api/bridge/daemon');
    if (!ok) return;
    const button = $('daemon');
    button.textContent = data.running ? 'ON' : 'OFF';
    button.classList.toggle('on', !!data.running);
    button.title = data.running ? `pid ${data.pid} · ${data.queue} en cola` : 'detenido';
  }

  $('mcp-reload').onclick = async () => {
    $('mcp-reload').textContent = 'recargando…';
    await api('/api/mcp', {method: 'POST', body: '{}'});
    await refreshMCP();
    $('mcp-reload').textContent = 'Recargar conectores';
  };
  $('daemon').onclick = async () => {
    const result = await api('/api/bridge/daemon', {method: 'POST', body: JSON.stringify({action: 'toggle'})});
    if (!result.ok) $('daemon').title = result.data.reason || 'no se pudo cambiar';
    refreshDaemon();
  };
  $('onboarding').onclick = openOnboarding;

  window.NexusUI = {
    take: () => { const items = pending.splice(0, pending.length); paintPending(); return items; },
    skill: openSkill,
    onboarding: openOnboarding,
  };

  refreshMCP();
  refreshDaemon();
  setInterval(refreshDaemon, 8000);
  setInterval(refreshMCP, 20000);
}());
