/* La columna izquierda: qué proyecto, qué conversación, y las acciones de cada fila.

   La lista se filtra en sitio (el operador escribe y ve), y cada acción habla con su endpoint. Una
   conversación borrada que era la actual deja el hilo vacío en vez de fingir que sigue abierta. */
window.NexusSessions = (function () {
  const {$, api, state, warn} = window.NX;

  function matchesSession(row, needle) {
    return !needle || `${row.title || ''} ${row.id || ''}`.toLowerCase().includes(needle);
  }

  /* El índice es un `listbox`: el foco entra por UNA fila (tabindex móvil, no un `tabindex=0` en
     cada una) y las flechas lo recorren. Sin esto la lista era ratón-only: las `li` no eran
     enfocables y un operador de teclado no podía abrir una conversación. */
  function optionItems() {
    const list = $('sessions');
    return list ? Array.from(list.querySelectorAll('[role="option"]')) : [];
  }

  function setRoving(items, index) {
    items.forEach((item, position) => { item.tabIndex = position === index ? 0 : -1; });
  }

  function wireKeys() {
    const list = $('sessions');
    if (!list || list.dataset.keys === 'on') return;
    list.dataset.keys = 'on';
    list.addEventListener('keydown', (event) => {
      const items = optionItems();
      if (!items.length) return;
      const at = items.indexOf(document.activeElement);
      if ((event.key === 'Enter' || event.key === ' ') && at >= 0) {
        event.preventDefault();
        loadSession(items[at].dataset.id);
        return;
      }
      let next = null;
      if (event.key === 'ArrowDown') next = at < 0 ? 0 : (at + 1) % items.length;
      else if (event.key === 'ArrowUp') next = at < 0 ? items.length - 1 : (at - 1 + items.length) % items.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = items.length - 1;
      if (next === null) return;
      event.preventDefault();
      setRoving(items, next);
      items[next].focus();
    });
  }

  function paintSessions(rows) {
    state.sessions = rows || [];
    const needle = String($('session-search').value || '').trim().toLowerCase();
    const list = $('sessions');
    list.innerHTML = '';
    const visible = state.sessions.filter((row) => matchesSession(row, needle));
    if (!visible.length) {
      const empty = document.createElement('li');
      empty.className = 'dim';
      empty.textContent = state.sessions.length ? 'sin resultados' : 'todavía ninguna';
      list.appendChild(empty);
      return;
    }
    const active = visible.findIndex((row) => row.id === state.session);
    for (const row of visible) {
      const item = document.createElement('li');
      const position = visible.indexOf(row);
      if (row.id === state.session) item.className = 'active';
      // Contrato de `listbox`: una opción enfocable por Tab (la activa, o la primera si no hay) y el
      // resto alcanzable con las flechas.
      item.setAttribute('role', 'option');
      item.setAttribute('aria-selected', String(row.id === state.session));
      item.dataset.id = row.id;
      item.tabIndex = position === (active >= 0 ? active : 0) ? 0 : -1;
      // El folio del índice es el mismo número con el que se cita la conversación.
      const folio = document.createElement('span');
      folio.className = 'folio';
      folio.textContent = String(position + 1).padStart(2, '0');
      const name = document.createElement('span');
      name.className = 'name';
      name.textContent = row.title || row.id;
      name.title = `${row.id} · ${row.turns || 0} turnos · doble clic para renombrar`;
      name.onclick = () => loadSession(row.id);
      name.ondblclick = () => renameSession(row);
      const acts = document.createElement('span');
      acts.className = 'acts';
      for (const [text, label, handler] of [['renombrar', 'renombrar', () => renameSession(row)],
                                            ['×', 'borrar', () => deleteSession(row)]]) {
        const act = document.createElement('span');
        act.className = 'act';
        act.textContent = text;
        act.title = label;
        act.setAttribute('role', 'button');
        act.setAttribute('aria-label', label);
        act.onclick = (event) => { event.stopPropagation(); handler(); };
        acts.appendChild(act);
      }
      item.append(folio, name, acts);
      list.appendChild(item);
    }
    wireKeys();
  }

  async function refreshSessions() {
    const {ok, data} = await api('/api/sessions');
    if (ok) paintSessions(data.sessions);
  }

  async function newChat() {
    const project = $('project').value;
    if (!project || String(project).startsWith('—')) return;
    const {ok, data} = await api('/api/chat/new', {method: 'POST', body: JSON.stringify({project})});
    if (!ok) return;
    state.session = data.session ? data.session.id : null;
    window.NexusStream.reset();
    refreshSessions();
  }

  async function loadSession(id) {
    const {ok} = await api('/api/chat/load', {method: 'POST', body: JSON.stringify({id})});
    if (!ok) return;
    state.session = id;
    await window.NexusStream.refreshChat();
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
    if (row.id === state.session) {
      state.session = null;
      window.NexusStream.reset();
    }
    refreshSessions();
  }

  async function openProject(name) {
    const option = Array.from($('project').options).find((item) => item.value === name);
    if (!option) return;
    $('project').value = name;
    if (!state.session) await newChat();
  }

  return {refreshSessions, paintSessions, repaint: () => paintSessions(state.sessions),
          newChat, loadSession, openProject};
}());
