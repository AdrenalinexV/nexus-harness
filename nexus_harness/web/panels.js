/* Lo que el chat necesita además de app.js: adjuntar ficheros al mensaje.

   Aquí vivía también el modal de configuración (modelos, claves, MCP, puente) y el editor de
   SKILL.md. Todo eso se fue a su propia pantalla (`/settings`), que se sirve con su HTML y su script:
   tenerlo en los dos sitios era tener dos sitios donde arreglarlo. Lo que queda es lo único que el
   compositor necesita de verdad: coger ficheros del sistema y dejarlos listos para enviar. */

(function () {
  const $ = (id) => document.getElementById(id);
  const LIMIT = 6 * 1024 * 1024;
  let pending = [];

  function paintPending() {
    const box = $('pending');
    box.textContent = '';
    pending.forEach((item, index) => {
      const chip = document.createElement('span');
      chip.className = 'tool';
      chip.textContent = `${item.kind === 'image' ? '🖼' : '📄'} ${item.name} ✕`;
      chip.title = 'quitar';
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

  window.NexusUI = {
    take: () => { const items = pending.splice(0, pending.length); paintPending(); return items; },
  };
}());
