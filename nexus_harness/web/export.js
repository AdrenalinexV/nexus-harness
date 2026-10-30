/* Exportar el hilo: el cuaderno de obra se saca en Markdown, no en una captura.

   El documento ya está montado en la pantalla con sus folios; aquí se vuelca TAL CUAL: mismo número,
   mismo orden, mismo rol. Por eso el modelo no se re-deriva de `/api/chat` (que obligaría a repetir la
   reconstrucción de herramientas y a arriesgar un folio distinto al que el operador ve): se lee
   `state.doc`, que `chat_stream.js` rellena al pintar. Sin dependencias y sin red: un `Blob`. */
window.NexusExport = (function () {
  const {$, state} = window.NX;

  const ROLE = {user: 'TÚ', assistant: 'NEXUS'};

  function argLine(tool) {
    const args = tool.args && Object.keys(tool.args).length ? ' ' + JSON.stringify(tool.args) : '';
    return '- `' + tool.name + '`' + args + (tool.ok === false ? ' · fallo' : '');
  }

  /* Herramientas del mensaje, una por línea, con la primera línea del resultado debajo y sangrada.
     El resultado entero no entra: un `cat` de 400 líneas convertiría el export en un volcado. */
  function toolLines(tools) {
    const out = [];
    for (const tool of tools || []) {
      out.push(argLine(tool));
      const result = String(tool.result || '').trim().split('\n')[0].slice(0, 200);
      if (result) out.push('  ' + result);
    }
    return out;
  }

  /* El Markdown del hilo: `# título` y un `## folio NN · ROL` por asiento. */
  function build() {
    const title = String(($('title') && $('title').textContent) || '').trim() || 'conversación';
    const lines = ['# ' + title, ''];
    for (const entry of state.doc || []) {
      const folio = String(entry.folio || 0).padStart(2, '0');
      lines.push('## folio ' + folio + ' · ' + (ROLE[entry.role] || entry.role), '');
      const text = String(entry.text || '').trim();
      if (text) lines.push(text, '');
      if (entry.attachments && entry.attachments.length) {
        lines.push('Adjuntos: ' + entry.attachments.map((item) => item.name).join(', '), '');
      }
      const tools = toolLines(entry.tools);
      if (tools.length) lines.push('Herramientas', '', ...tools, '');
    }
    return lines.join('\n').replace(/\n{3,}/g, '\n\n').trimEnd() + '\n';
  }

  /* Nombre de fichero legible: el título sin acentos ni signos, o `hilo` si no queda nada. */
  function slug(text) {
    return String(text || '').toLowerCase().normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '').slice(0, 60) || 'hilo';
  }

  function save() {
    if (!(state.doc || []).length) return;
    const blob = new Blob([build()], {type: 'text/markdown;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = slug($('title').textContent) + '.md';
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const button = $('export-thread');
  if (button) button.onclick = save;

  return {build, save};
})();
