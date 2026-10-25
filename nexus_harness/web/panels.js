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

  /* ---------- lo que queda: adjuntos, modal y el editor de SKILL.md ----------
     Los conectores MCP, el puente movil y los selectores de modelos vivian aqui, en un modal pobre.
     Ahora son la vista 01 de la gobernanza (la GUI real de NexusProtocol, con la barra del arnes
     dentro), asi que este fichero no los dibuja dos veces: los enlaces de la cabecera llevan alli. */

  window.NexusUI = {
    take: () => { const items = pending.splice(0, pending.length); paintPending(); return items; },
    skill: openSkill,
  };
}());
