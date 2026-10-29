/* La pantalla de configuración funciona SIN este fichero: navegar es un `<a>` y guardar es un
   `<form>` que contesta un 303. Aquí van solo las cosas que de verdad necesitan script:

   1. Ctrl+K: un buscador de DESTINOS (los trece), con flechas y Enter. Sin script, el mismo campo es
      el filtro del árbol que atiende el servidor (`/settings?q=`), así que no se pierde nada.
   2. Esc: cierra el buscador; si ya está cerrado, vuelve al chat.
   3. El editor de `SKILL.md` en una ventana (lo único que habla JSON con el motor).
   4. La cola de proyectos: arrastrar y soltar.
   5. Al elegir proveedor, los modelos de ese proveedor.

   Seguridad: el único `innerHTML` es el marcado FIJO de la ventana del editor. Todo lo que viene del
   motor se pinta con `textContent` o `value`. */
(function () {
  const $ = (id) => document.getElementById(id);
  const TOKEN = window.NexusToken || '';

  function api(path, options = {}) {
    const headers = Object.assign({'Content-Type': 'application/json'}, options.headers || {});
    if (TOKEN) headers['X-Nexus-Token'] = TOKEN;
    return fetch(path, Object.assign({}, options, {headers})).then(async (response) => ({
      ok: response.ok, status: response.status, data: await response.json().catch(() => ({}))}));
  }

  /* ---------- 1 y 2. Ctrl+K: destinos, flechas, Enter y Esc ---------- */
  const search = $('settings-search');
  const palette = $('sk-palette');
  let index = [];
  try {
    index = JSON.parse(($('sk-index') || {}).textContent || '[]');
  } catch (error) {
    index = [];
  }
  let cursor = -1;

  function matches(entry, needle) {
    if (!needle) return true;
    const haystack = [entry.label, entry.where, entry.terms].join(' ').toLowerCase();
    return needle.split(/\s+/).every((word) => haystack.includes(word));
  }

  function paintPalette() {
    const needle = String(search.value || '').trim().toLowerCase();
    const rows = index.filter((entry) => matches(entry, needle));
    palette.textContent = '';
    cursor = -1;
    if (!rows.length) {
      const empty = document.createElement('li');
      empty.className = 'empty-row';
      empty.textContent = 'Ningún destino coincide con «' + search.value + '». Pulsa Enter para filtrar el árbol.';
      palette.appendChild(empty);
    }
    rows.forEach((entry) => {
      const item = document.createElement('li');
      const link = document.createElement('a');
      link.href = entry.href;
      link.textContent = entry.label;
      if (entry.where) {
        const where = document.createElement('span');
        where.className = 'where';
        where.textContent = entry.where;
        link.appendChild(where);
      }
      item.appendChild(link);
      palette.appendChild(item);
    });
    palette.hidden = false;
  }

  function move(step) {
    const links = Array.from(palette.querySelectorAll('a'));
    if (!links.length) return;
    cursor = (cursor + step + links.length) % links.length;
    links.forEach((link, position) => link.classList.toggle('on', position === cursor));
    links[cursor].scrollIntoView({block: 'nearest'});
  }

  function closePalette() {
    palette.hidden = true;
    cursor = -1;
  }

  function openPalette() {
    paintPalette();
  }

  if (search && palette) {
    search.addEventListener('focus', openPalette);
    search.addEventListener('input', openPalette);
    search.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown') { event.preventDefault(); move(1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); move(-1); }
      else if (event.key === 'Enter' && cursor >= 0) {
        event.preventDefault();
        window.location.href = palette.querySelectorAll('a')[cursor].href;
      } else if (event.key === 'Escape') {
        event.stopPropagation();
        closePalette();
        search.blur();
      }
    });
    document.addEventListener('click', (event) => {
      if (!event.target.closest('.settings-search')) closePalette();
    });
  }

  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && String(event.key).toLowerCase() === 'k') {
      event.preventDefault();
      if (search) { search.focus(); search.select(); openPalette(); }
    } else if (event.key === 'Escape' && !document.querySelector('dialog[open]')) {
      if (palette && !palette.hidden) { closePalette(); return; }
      window.location.href = '/?token=' + encodeURIComponent(TOKEN);
    }
  });

  /* ---------- 3. el editor de SKILL.md ---------- */
  const dialog = document.createElement('dialog');
  dialog.className = 'skilldlg';
  dialog.innerHTML =
    '<header><strong id="skdlg-name">SKILL.md</strong>'
    + '<span class="dim" id="skdlg-meta"></span>'
    + '<button class="ghost" id="skdlg-close" aria-label="Cerrar">Cerrar</button></header>'
    + '<textarea id="skdlg-text" spellcheck="false"></textarea>'
    + '<footer><span class="dim" id="skdlg-note"></span>'
    + '<button class="primary" id="skdlg-save">Guardar SKILL.md</button></footer>';
  document.body.appendChild(dialog);
  let current = {name: '', root: ''};

  function note(text, bad) {
    const box = $('skdlg-note');
    box.textContent = text;
    box.className = 'dim' + (bad ? ' bad' : '');
  }

  async function openSkill(name, root) {
    current = {name, root};
    note('cargando…');
    $('skdlg-name').textContent = name;
    $('skdlg-text').value = '';
    dialog.showModal();
    const {ok, data} = await api('/api/settings/skill?name=' + encodeURIComponent(name)
      + '&root=' + encodeURIComponent(root));
    if (!ok) { note(data.reason || 'no se pudo leer', true); return; }
    $('skdlg-text').value = data.text || '';
    $('skdlg-meta').textContent = (data.lines || '?') + ' líneas · sha '
      + String(data.sha256 || '').slice(0, 12);
    note('el contrato se valida antes de escribir');
  }

  async function saveSkill() {
    note('guardando…');
    const {ok, data} = await api('/api/settings/skill', {method: 'POST', body: JSON.stringify({
      name: current.name, root: current.root, text: $('skdlg-text').value})});
    if (!ok) { note(data.reason || 'rechazado', true); return; }
    note('guardado · sha ' + String(data.sha256 || '').slice(0, 12)
      + ' · provenance: ' + (data.provenance || '?'));
    $('skdlg-meta').textContent = (data.lines || '?') + ' líneas · sha '
      + String(data.sha256 || '').slice(0, 12);
  }

  $('skdlg-close').onclick = () => dialog.close();
  $('skdlg-save').onclick = saveSkill;
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-skill]');
    if (!button) return;
    event.preventDefault();
    openSkill(button.dataset.skill, button.dataset.root || '');
  });

  /* ---------- 4. la cola de proyectos: arrastrar y soltar ---------- */
  const queue = $('queue');
  let dragged = null;

  function renumber() {
    Array.from(queue.querySelectorAll('.qcard')).forEach((card, position) => {
      const num = card.querySelector('.qnum');
      if (num) num.textContent = '#' + (position + 1);
    });
  }

  async function persistOrder() {
    const names = Array.from(queue.querySelectorAll('.qcard')).map((card) => card.dataset.project);
    const {ok, data} = await api('/api/projects/order', {method: 'POST', body: JSON.stringify({names})});
    const box = document.createElement('p');
    box.className = 'snote ' + (ok ? 'ok' : 'bad');
    box.textContent = ok ? 'cola guardada: ' + (data.order || []).join(' → ')
      : ('no se pudo guardar: ' + (data.reason || 'motivo desconocido'));
    queue.parentNode.insertBefore(box, queue);
    window.setTimeout(() => box.remove(), 6000);
  }

  if (queue) {
    queue.addEventListener('dragstart', (event) => {
      const card = event.target.closest('.qcard');
      if (!card) return;
      dragged = card;
      card.classList.add('dragging');
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', card.dataset.project || '');
    });
    queue.addEventListener('dragend', () => {
      if (dragged) dragged.classList.remove('dragging');
      dragged = null;
    });
    queue.addEventListener('dragover', (event) => {
      event.preventDefault();
      const over = event.target.closest('.qcard');
      if (!over || !dragged || over === dragged) return;
      const box = over.getBoundingClientRect();
      const after = (event.clientY - box.top) > box.height / 2;
      queue.insertBefore(dragged, after ? over.nextSibling : over);
    });
    queue.addEventListener('drop', (event) => {
      event.preventDefault();
      if (!dragged) return;
      renumber();
      persistOrder();
    });
  }

  /* ---------- 5. las carpetas sin gobernanza y los modelos por proveedor ---------- */
  for (const input of document.querySelectorAll('[data-filter]')) {
    input.addEventListener('input', () => {
      const needle = input.value.trim().toLowerCase();
      for (const row of document.querySelectorAll(input.dataset.filter)) {
        row.hidden = Boolean(needle) && !(row.dataset.name || '').includes(needle);
      }
    });
  }

  document.addEventListener('change', (event) => {
    const select = event.target;
    if (!select.matches || !select.matches('select[name="vendor"]')) return;
    for (const option of document.querySelectorAll('#model-options option')) {
      option.disabled = Boolean(option.dataset.vendor) && option.dataset.vendor !== select.value;
    }
  });
}());
