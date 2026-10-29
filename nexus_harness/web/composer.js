/* El compositor: enviar, detener y adjuntar.

   Aquí vive lo que antes estaba en `panels.js` (adjuntar ficheros) porque es la misma caja de escribir:
   separarlo obligaba a dos ficheros para una sola pregunta. Límite de 6 MB por fichero, y el nombre va
   tal cual: es del operador, no lo inventa el modelo. */
window.NexusComposer = (function () {
  const {$, api, state} = window.NX;
  const LIMIT = 6 * 1024 * 1024;
  let pending = [];

  function paintPending() {
    const box = $('pending');
    box.textContent = '';
    pending.forEach((item, index) => {
      const chip = document.createElement('span');
      chip.className = 'attach';
      chip.textContent = item.name;
      chip.title = 'quitar';
      chip.setAttribute('role', 'button');
      chip.onclick = () => { pending.splice(index, 1); paintPending(); };
      box.appendChild(chip);
    });
  }

  function base64Of(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || '').split(',')[1] || '');
      reader.onerror = () => reject(new Error('no se pudo leer el fichero'));
      reader.readAsDataURL(file);
    });
  }

  async function addFiles(files) {
    for (const file of Array.from(files || [])) {
      if (file.size > LIMIT) {
        window.alert(`${file.name} pesa más de 6 MB`);
        continue;
      }
      const kind = file.type.startsWith('image/') ? 'image' : 'document';
      const data = await base64Of(file);
      pending.push({name: file.name, kind, media_type: file.type || 'application/octet-stream', data});
      paintPending();
    }
  }

  async function send() {
    const attachments = pending.splice(0, pending.length);
    paintPending();
    const text = $('input').value.trim();
    if (!text && !attachments.length) return;
    $('input').value = '';
    window.NexusStream.addMessage('user', text || '·', {attachments: attachments.map((item) => ({
      name: item.name, kind: item.kind}))});
    const {ok, status, data} = await api('/api/chat',
      {method: 'POST', body: JSON.stringify({text, attachments})});
    if (!ok) {
      window.NexusStream.addMessage('assistant',
        status === 409 ? 'Ya hay un turno en marcha.' : (data.reason || 'no se pudo enviar'));
      return;
    }
    window.setTimeout(() => window.NexusStream.refreshChat(), 700);
  }

  async function stopTurn() {
    await api('/api/stop', {method: 'POST', body: '{}'});
  }

  $('attach').onclick = () => $('file').click();
  $('file').onchange = () => { addFiles($('file').files); $('file').value = ''; };
  $('input').addEventListener('paste', (event) => {
    const files = Array.from(event.clipboardData ? event.clipboardData.files : []);
    if (files.length) { event.preventDefault(); addFiles(files); }
  });
  $('input').addEventListener('dragover', (event) => event.preventDefault());
  $('input').addEventListener('drop', (event) => {
    event.preventDefault();
    addFiles(event.dataTransfer ? event.dataTransfer.files : []);
  });

  return {send, stopTurn, take: () => pending.splice(0, pending.length), state};
}());
