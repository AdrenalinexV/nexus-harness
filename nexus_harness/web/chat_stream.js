/* El hilo: mensajes, herramientas, la tira de lo que pasa y el sondeo del bus de eventos.

   Vive aparte de `app.js` por la ley de 400 líneas y, sobre todo, por responsabilidad: aquí se PINTA lo
   que el motor ya decidió; no se decide nada. Todo lo que viene del modelo pasa por `esc()`. */
window.NexusStream = (function () {
  const {$, api, esc, state} = window.NX;

  const LABEL = {
    'chat.user': 'TÚ', 'chat.assistant': 'NEXUS', 'chat.turn': 'TURNO', 'chat.repair': 'REPARACIÓN',
    'chat.stopped': 'DETENIDO', 'chat.new': 'NUEVA', 'chat.load': 'ABIERTA', 'chat.limit': 'LÍMITE',
    'tool.call': 'TOOL', 'skills.injected': 'SKILLS', 'gate.verdict': 'GATE', 'judge.verdict': 'JUEZ',
    'worker.reasoning': 'RAZÓN', 'worker.error': 'ERROR', 'memory.add': 'MEMORIA',
    'memory.remove': 'MEMORIA-', 'bridge.claim': 'PUENTE', 'bridge.close': 'PUENTE',
    'tool.parallel': 'PARALELO', 'subagent.start': 'SUBAGENTES', 'subagent.result': 'SUBAGENTE',
    'subagent.tool': 'SUB-TOOL', 'subagent.end': 'SUBAGENTES', 'subagent.limit': 'SUB-LÍMITE',
    'chat.stopping': 'DETENIENDO', 'run.stopping': 'DETENIENDO', 'worker.stopped': 'DETENIDO',
    'session.relay': 'RELEVO', 'chat.rename': 'RENOMBRADA', 'skills.saved': 'SKILL',
  };

  /* Portapapeles con red: la API moderna exige contexto seguro y, en algunos webviews, permiso; el
     camino viejo (textarea + execCommand) funciona en el escritorio y no pide nada. */
  function legacyCopy(text) {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.top = '-1000px';
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (error) { ok = false; }
    area.remove();
    if (!ok) throw new Error('execCommand fallo');
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).catch(() => legacyCopy(text));
    }
    return Promise.resolve().then(() => legacyCopy(text));
  }

  /* Un bloque cercado (```...```) del mensaje no se deja como texto: se pinta como `<pre>` con su
     propia acción de copiar, para no seleccionar el código a mano. El contenido va por `textContent`
     — nunca `innerHTML` — así que el modelo no puede inyectar marcado desde un mensaje. */
  const FENCE = /```([^\n`]*)\n?([\s\S]*?)(?:```|$)/g;

  function codeBlock(code, lang) {
    const box = document.createElement('figure');
    box.className = 'codeblock';
    const head = document.createElement('div');
    head.className = 'code-head';
    const tag = document.createElement('span');
    tag.className = 'code-lang';
    tag.textContent = lang || 'codigo';
    head.appendChild(tag);
    const copy = document.createElement('button');
    copy.className = 'copy code-copy';
    copy.type = 'button';
    copy.textContent = 'copiar';
    copy.title = 'Copiar este bloque';
    copy.onclick = async () => {
      try { await copyText(code); copy.textContent = 'copiado'; copy.classList.add('done'); }
      catch (error) { copy.textContent = 'no se pudo'; }
      window.setTimeout(() => { copy.textContent = 'copiar'; copy.classList.remove('done'); }, 1600);
    };
    head.appendChild(copy);
    const pre = document.createElement('pre');
    pre.className = 'code';
    pre.textContent = code.replace(/\n+$/, '');
    box.appendChild(head);
    box.appendChild(pre);
    return box;
  }

  /* El asiento alterna prosa y bloques: el texto se parte por las vallas y cada trozo se pinta como
     nodo de texto (respeta el `white-space: pre-wrap` del cuaderno) o como bloque de código. */
  function fillBubble(bubble, text) {
    const raw = String(text == null ? '' : text);
    bubble.textContent = '';
    FENCE.lastIndex = 0;
    let cursor = 0;
    let found = false;
    let match;
    while ((match = FENCE.exec(raw)) !== null) {
      if (match[0].length === 0) break; // red de seguridad: un match vacio no avanza el cursor
      if (match.index > cursor) bubble.appendChild(document.createTextNode(raw.slice(cursor, match.index)));
      bubble.appendChild(codeBlock(match[2], match[1].trim()));
      cursor = match.index + match[0].length;
      found = true;
    }
    if (cursor < raw.length) bubble.appendChild(document.createTextNode(raw.slice(cursor)));
    if (!found) bubble.textContent = raw;
  }

  function msgText(content) {
    if (Array.isArray(content)) {
      return content.filter((part) => part && part.type === 'text'
          && !String(part.text || '').startsWith('<document'))
        .map((part) => part.text || '').join('\n').trim();
    }
    return String(content || '');
  }

  function msgAttachments(message) {
    if (!Array.isArray(message.content)) return [];
    return message.content.filter((part) => part && part.type !== 'text')
      .map((part) => ({name: 'imagen', kind: 'image', preview: (part.image_url || {}).url || ''}));
  }

  /* Cada mensaje es un asiento del cuaderno: FOLIO en el margen + quien habla + lo que dijo. Se puede
     citar («folio 07») sin describir el mensaje, que es lo que hace un documento de obra. */
  function addMessage(role, text, meta) {
    state.folio = (state.folio || 0) + 1;
    // El mismo asiento que se pinta queda registrado para el export: folio, rol, texto, herramientas.
    state.doc.push({folio: state.folio, role, text: String(text || ''),
                    tools: (meta && meta.tools) || [], attachments: (meta && meta.attachments) || []});
    const wrap = document.createElement('article');
    wrap.className = 'msg ' + role;
    wrap.innerHTML = `<div class="folio">${String(state.folio).padStart(2, '0')}</div>
                      <div class="body"><div class="who">${role === 'user' ? 'TÚ' : 'NEXUS'}</div>
                      <div class="bubble"></div></div>`;
    fillBubble(wrap.querySelector('.bubble'), text);
    const body = wrap.querySelector('.body');
    if (meta && meta.attachments && meta.attachments.length) {
      const box = document.createElement('div');
      box.className = 'tools';
      for (const item of meta.attachments) {
        const chip = document.createElement('span');
        chip.className = 'attach';
        chip.textContent = item.name;
        chip.title = item.kind === 'image' ? 'imagen adjunta' : 'documento adjunto';
        box.appendChild(chip);
      }
      body.appendChild(box);
    }
    if (role === 'assistant' && String(text || '').trim()) {
      // Copiar lo que dijo el modelo, sin seleccionar a mano. El botón solo existe si hay texto.
      const copy = document.createElement('button');
      copy.className = 'copy';
      copy.type = 'button';
      copy.textContent = 'copiar';
      copy.title = 'Copiar este mensaje';
      copy.onclick = async () => {
        try {
          await copyText(String(text));
          copy.textContent = 'copiado';
          copy.classList.add('done');
        } catch (error) {
          copy.textContent = 'no se pudo';
        }
        window.setTimeout(() => { copy.textContent = 'copiar'; copy.classList.remove('done'); }, 1600);
      };
      wrap.querySelector('.body').appendChild(copy);
    }
    if (meta && meta.tools && meta.tools.length) {
      const chips = document.createElement('div');
      chips.className = 'tools';
      for (const tool of meta.tools) {
        const chip = document.createElement('span');
        chip.className = 'tool' + (tool.ok === false ? ' bad' : '');
        chip.textContent = tool.name;
        chip.title = ((tool.args ? JSON.stringify(tool.args) : '') + '\n' + (tool.result || '')).slice(0, 600);
        chips.appendChild(chip);
      }
      body.appendChild(chips);
    }
    $('thread').appendChild(wrap);
    $('thread').scrollTop = $('thread').scrollHeight;
    return wrap;
  }

  /* La tira de lo que pasa durante el turno: dentro del hilo, al final y discreta. */
  function paintFeed() {
    const box = $('inline');
    if (!box) return;
    box.innerHTML = '';
    for (const row of state.feed.slice(-14)) {
      const line = document.createElement('div');
      line.className = 'feed-row' + (row.kind === 'gate.verdict' || row.kind === 'judge.verdict' ? ' gate' : '');
      const detail = String(row.detail || '');
      if (row.kind.endsWith('.reasoning')) {
        /* El pensamiento de un modelo local no se tira ni se mezcla con la respuesta: va en un bloque
           plegable, entero y escapado. Un `<details>` no rompe el parser ni el JSON del juez. */
        const fold = document.createElement('details');
        fold.className = 'reasoning';
        fold.innerHTML = `<summary><span class="k">${esc(LABEL[row.kind] || row.kind)}</span>
          <span class="d">${esc(detail.slice(0, 120))}</span></summary>
          <pre>${esc(detail)}</pre>`;
        box.appendChild(fold);
        continue;
      }
      line.innerHTML = `<span class="k">${esc(LABEL[row.kind] || row.kind)}</span>
                        <span class="d">${esc(detail.slice(0, 160))}</span>`;
      box.appendChild(line);
    }
    if (state.feed.length) $('thread').scrollTop = $('thread').scrollHeight;
  }

  function renderThread(messages) {
    const thread = $('thread');
    thread.innerHTML = '';
    state.folio = 0;
    state.doc = [];
    if (!messages.length) {
      thread.innerHTML = `<div class="empty"><h1>¿Qué construimos?</h1>
        <p>Pide una tarea o haz una pregunta. El gate —lint Nexus, ley de 400 líneas, tests— corre en
        cuanto se toca un fichero; si sale rojo, el obrero lo repara antes de contestarte.</p>
        <div class="rule"></div>
        <p class="dim">La tríada de modelos, las claves, la memoria y las skills se cambian en
        <a href="/settings?token=${encodeURIComponent(window.NexusToken || '')}">Configuración</a>;
        el ledger y el gate, en <a href="/gov?token=${encodeURIComponent(window.NexusToken || '')}">Gobernanza</a>.</p></div>`;
    } else {
      const pending = {};
      for (const message of messages) {
        if (message.role === 'user') {
          addMessage('user', msgText(message.content) || '·', {attachments: msgAttachments(message)});
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
    }
    const inline = document.createElement('div');
    inline.id = 'inline';
    inline.className = 'inline-feed';
    thread.appendChild(inline);
    paintFeed();
    paintDraft();
    thread.scrollTop = thread.scrollHeight;
  }

  /* Firma de lo pintado: sesión, número de mensajes y tamaño del último. Repintar el hilo entero cada
     2,5 s rompía la selección de texto y el scroll: el operador seleccionaba una línea y el sondeo se
     la llevaba por delante. Con la firma, solo se repinta cuando de verdad cambió algo. */
  let painted = '';
  function signature(session, messages) {
    const last = messages[messages.length - 1];
    return [session, messages.length, last ? String(last.content || last.role || '').length : 0,
            last ? (last.role || '') : ''].join('|');
  }

  async function refreshChat() {
    if (document.hidden) return;
    const {ok, data} = await api('/api/chat');
    if (!ok) return;
    const next = data.session ? data.session.id : null;
    if (next !== state.session) { state.since = 0; state.feed = []; painted = ''; }
    state.session = next;
    const messages = data.messages || [];
    const current = signature(next, messages);
    if (current === painted) { paintFeed(); return; }
    painted = current;
    renderThread(messages);
  }

  /* El borrador del turno: los deltas se pintan aqui y el `chat.assistant` final los sustituye. Un
     elemento, no un asiento por trozo: el folio se gasta una vez, al mensaje de verdad. */
  let draftEl = null;
  let draftText = '';

  function clearDraft() {
    draftText = '';
    if (draftEl) { draftEl.remove(); draftEl = null; }
  }

  function paintDraft() {
    if (!draftText) return;
    if (!draftEl || !draftEl.isConnected) {
      draftEl = document.createElement('article');
      draftEl.className = 'msg assistant draft';
      draftEl.innerHTML = '<div class="folio">··</div><div class="body"><div class="who">NEXUS</div>' +
                          '<div class="bubble"></div></div>';
      $('thread').appendChild(draftEl);
    }
    fillBubble(draftEl.querySelector('.bubble'), draftText);
    $('thread').scrollTop = $('thread').scrollHeight;
  }

  /* Un evento del bus, venga por SSE o por sondeo: un solo camino, dos transportes. */
  function handle(event) {
    if (event.kind === 'worker.delta') {
      draftText += String(event.detail || '');
      paintDraft();
      return;
    }
    if (event.kind === 'chat.assistant' || event.kind === 'chat.turn' || event.kind === 'tool.call' ||
        event.kind === 'worker.error' || event.kind === 'chat.stopped' ||
        event.kind === 'chat.stopping') {
      // El turno cerro o paso a otra cosa: el borrador ya no es cierto.
      clearDraft();
    }
    if (!LABEL[event.kind]) return;
    state.feed.push({kind: event.kind, detail: event.detail || ''});
    paintFeed();
  }

  async function pollEvents() {
    if (state.polling) return;
    state.polling = true;
    try {
      const {ok, data} = await api('/api/events?since=' + state.since);
      if (!ok) return;
      for (const event of data.events || []) {
        state.since = Math.max(state.since, Number(event.seq) || 0);
        handle(event);
      }
    } finally { state.polling = false; }
  }

  /* SSE cuando el motor lo sirve (api >= 4); sondeo de 800 ms cuando no. El navegador reanuda con
     Last-Event-ID; si la ruta no existe, EventSource cierra y se cae al sondeo sin ruido. */
  let source = null;

  function startEvents() {
    if (!(state.engineApi >= 4) || !window.EventSource) {
      window.setInterval(pollEvents, 800);
      return;
    }
    const token = window.NexusToken ? '&token=' + encodeURIComponent(window.NexusToken) : '';
    source = new EventSource('/api/events/stream?since=' + state.since + token);
    source.onmessage = (message) => {
      let event;
      try { event = JSON.parse(message.data); } catch (error) { return; }
      state.since = Math.max(state.since, Number(event.seq) || 0);
      handle(event);
    };
    source.onerror = () => {
      if (source && source.readyState === EventSource.CLOSED) {
        source.close();
        source = null;
        window.setInterval(pollEvents, 800);
      }
    };
  }

  function noteSkills(skills) {
    if (state.feed.some((row) => row.kind === 'skills.injected')) return;
    state.feed.push({kind: 'skills.injected', detail: (skills || []).join(', ')});
    paintFeed();
  }

  function reset() {
    state.feed = [];
    state.since = 0;
    clearDraft();
    renderThread([]);
  }

  return {addMessage, renderThread, refreshChat, pollEvents, startEvents, noteSkills, reset};
}());
