/* La pantalla de configuración funciona SIN este fichero: navegar es un `<a>` y guardar es un
   `<form>` que contesta un 303. Aquí van solo las tres cosas que de verdad necesitan script:
   1. Ctrl+K para buscar y Esc para volver al chat.
   2. El editor de `SKILL.md` en una ventana (lo único que habla JSON con el motor).
   3. Al elegir proveedor, la lista de modelos sugiere solo los de ese proveedor.

   Nota de seguridad: el único `innerHTML` de este fichero es el marcado FIJO de la ventana del editor
   (no lleva ni un dato interpolado). Todo lo que viene del motor se pinta con `textContent` o con
   `value`, nunca como marcado. */

(function () {
  const $ = (id) => document.getElementById(id);
  const TOKEN = new URLSearchParams(location.search).get('token') || '';

  function api(path, options = {}) {
    const headers = Object.assign({'Content-Type': 'application/json'}, options.headers || {});
    if (TOKEN) headers['X-Nexus-Token'] = TOKEN;
    return fetch(path, Object.assign({}, options, {headers})).then(async (response) => ({
      ok: response.ok, status: response.status, data: await response.json().catch(() => ({}))}));
  }

  /* ---------- 2. el editor de SKILL.md ---------- */
  const dialog = document.createElement('dialog');
  dialog.className = 'skilldlg';
  dialog.innerHTML =
    '<header><strong id="skdlg-name">SKILL.md</strong>'
    + '<span class="dim" id="skdlg-meta"></span>'
    + '<button class="ghost" id="skdlg-close">✕</button></header>'
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

  /* ---------- 1. atajos y filtro del árbol ---------- */
  const search = $('settings-search');
  if (search) {
    search.addEventListener('input', () => {
      const needle = search.value.trim().toLowerCase();
      for (const category of document.querySelectorAll('.scat')) {
        const text = category.textContent.toLowerCase();
        category.hidden = Boolean(needle) && !text.includes(needle);
        if (needle) category.open = text.includes(needle);
      }
    });
  }
  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && String(event.key).toLowerCase() === 'k') {
      event.preventDefault();
      if (search) { search.focus(); search.select(); }
    } else if (event.key === 'Escape' && !dialog.open) {
      window.location.href = '/';
    }
  });

  /* ---------- 3. los modelos que existen, por proveedor ---------- */
  document.addEventListener('change', (event) => {
    const select = event.target;
    if (!select.matches || !select.matches('select[name="vendor"]')) return;
    for (const option of document.querySelectorAll('#model-options option')) {
      option.disabled = Boolean(option.dataset.vendor) && option.dataset.vendor !== select.value;
    }
  });
}());
