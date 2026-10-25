/* La barra de estado en vivo de la esquina: que hace el motor AHORA y como acabo lo ultimo.
 *
 * Antes ahi vivia un `en reposo` quieto que no decia nada y no se podia ni pulsar. Esto es lo mismo
 * que el motor ya sabe (`/api/activity`: fase, herramienta, progreso, autopilot y el resultado del
 * ultimo turno) puesto donde el ojo esta.
 *
 * Reglas de este fichero:
 * - Nada de `innerHTML` con datos del motor: todo se pinta con `textContent` y nodos. La etiqueta lleva
 *   nombres de ficheros y de herramientas, que vienen de un modelo.
 * - Si el motor no contesta, se dice: una pildora congelada en "Listo" mientras el turno corre es peor
 *   que una que admite que perdio el hilo.
 * - El bucle autonomo se arranca y se para DESDE AQUI, con su limite de iteraciones a la vista.
 */
(function () {
  const $ = (id) => document.getElementById(id);
  const TOKEN = new URLSearchParams(location.search).get('token') || '';
  // Sondeo adaptativo: rapido mientras hay un turno (para que la herramienta en curso se vea de
  // verdad), lento cuando no pasa nada (que es el 99 % del tiempo). Un sondeo fijo de 900 ms se pierde
  // las fases cortas; uno fijo de 300 ms es una peticion constante por nada.
  const POLL_LIVE_MS = 400;
  const POLL_IDLE_MS = 1600;
  const TONE = ['ok', 'warn', 'bad', 'info', 'idle'];
  let last = null;
  let failures = 0;

  function api(path, options = {}) {
    const headers = Object.assign({'Content-Type': 'application/json'}, options.headers || {});
    if (TOKEN) headers['X-Nexus-Token'] = TOKEN;
    return fetch(path, Object.assign({}, options, {headers})).then(async (response) => ({
      ok: response.ok, status: response.status, data: await response.json().catch(() => ({}))}));
  }

  /* ---------- la pildora ---------- */
  function paint(data) {
    const pill = $('activity');
    if (!pill) return;
    pill.className = 'activity ' + (TONE.includes(data.tone) ? data.tone : 'idle');
    $('activity-glyph').textContent = data.glyph || '🟢';
    $('activity-label').textContent = data.label || '';
    const bar = $('activity-bar');
    const progress = data.progress || {};
    if (progress.total) {
      bar.hidden = false;
      const ratio = Math.max(0, Math.min(1, (progress.done || 0) / progress.total));
      bar.firstElementChild.style.width = (ratio * 100).toFixed(0) + '%';
      bar.title = progress.label || '';
    } else {
      bar.hidden = true;
    }
    pill.title = [data.label, (data.summary || {}).text, 'Pulsa para ver el último turno']
      .filter(Boolean).join(' · ');
  }

  /* ---------- el desplegable del ultimo turno ---------- */
  function row(label, value, tone) {
    const line = document.createElement('div');
    line.className = 'poprow';
    const key = document.createElement('span');
    key.className = 'k';
    key.textContent = label;
    const val = document.createElement('span');
    val.className = 'v' + (tone ? ' ' + tone : '');
    val.textContent = value == null || value === '' ? '—' : String(value);
    line.append(key, val);
    return line;
  }

  function paintPopover(data) {
    const detail = data.detail || {};
    const gate = detail.gate || {};
    const judge = detail.judge || {};
    const tokens = detail.tokens || {};
    const summary = data.summary || {};
    $('pop-summary').textContent = summary.text || 'todavía sin turnos en este proyecto';
    $('pop-summary').className = summary.tone && TONE.includes(summary.tone) ? summary.tone : 'dim';
    $('pop-when').textContent = detail.at || '';
    const files = $('pop-files');
    files.textContent = '';
    const touched = detail.files || [];
    if (!touched.length) {
      const none = document.createElement('span');
      none.className = 'chip off';
      none.textContent = 'sin ficheros tocados';
      files.appendChild(none);
    }
    for (const name of touched) {
      const chip = document.createElement('span');
      chip.className = 'chip';
      chip.textContent = name;
      files.appendChild(chip);
    }
    const body = $('pop-gate');
    body.textContent = '';
    body.append(
      row('Gate', gate.exit == null ? 'sin gate' : 'exit ' + gate.exit, gate.ok ? 'ok' : 'bad'),
      row('Juez', judge.verdict || 'no consultado',
          judge.verdict === 'approve' ? 'ok' : (judge.verdict === 'reject' ? 'bad' : '')),
      row('Tokens', tokens.total ? (tokens.prompt || 0) + ' entrada · ' + (tokens.completion || 0)
        + ' salida' : 'sin medir'),
      row('Pasos / reparaciones', (detail.steps || 0) + ' / ' + (detail.repairs || 0)));
    // El diff del turno, medido contra el diario del checkpoint (bytes de antes vs disco de ahora).
    const diff = detail.diff || [];
    const totals = detail.diff_totals || {};
    if (diff.length) {
      body.append(row('Diff', '+' + (totals.added || 0) + ' · −' + (totals.removed || 0)));
      for (const one of diff.slice(0, 6)) {
        body.append(row('· ' + (one.path || '?'),
          one.added == null ? (one.note || 'no medido') : '+' + one.added + ' −' + one.removed));
      }
    }
    for (const check of gate.checks || []) {
      body.append(row('· ' + check.name, check.detail || (check.ok ? 'ok' : 'falla'),
        check.ok ? 'ok' : 'bad'));
    }
    const auto = data.autopilot || {};
    $('auto-start').hidden = Boolean(auto.running);
    $('auto-stop').hidden = !auto.running;
    if (auto.running) {
      $('auto-iterations').value = auto.iterations || 3;
    }
    $('pop-note').textContent = [auto.note, auto.last, touched.length > 12
      ? '… y ' + (touched.length - 12) + ' ficheros más' : ''].filter(Boolean).join(' · ');
  }

  function toggle(open) {
    const pop = $('activity-pop');
    const wants = open == null ? pop.hidden : open;
    pop.hidden = !wants;
    $('activity').setAttribute('aria-expanded', String(wants));
    if (wants && last) paintPopover(last);
  }

  /* ---------- el bucle autonomo, desde el chat ---------- */
  async function startAutopilot() {
    const iterations = Number($('auto-iterations').value) || 3;
    // Sin proyecto elegido se manda vacio y el motor usa el #1 de la cola de prioridad: enviar el
    // texto del marcador ("— elige un proyecto —") seria pedirle un ciclo a una carpeta que no existe.
    const chosen = ($('project') || {}).value || '';
    const project = chosen.startsWith('—') ? '' : chosen;
    const {ok, data} = await api('/api/autonomy', {method: 'POST',
      body: JSON.stringify({project, iterations})});
    $('pop-note').textContent = ok
      ? 'autopilot arrancado: backup previo en cada ciclo'
      : ('no arrancó: ' + (data.reason || 'motivo desconocido'));
    if (ok) await tick();
  }

  async function stopAutopilot() {
    const {ok, data} = await api('/api/autonomy', {method: 'POST', body: JSON.stringify({action: 'stop'})});
    $('pop-note').textContent = ok && data.ok ? 'deteniendo el bucle…' : 'el bucle no estaba corriendo';
    await tick();
  }

  /* ---------- el sondeo ---------- */
  /* `tick` pregunta UNA vez y devuelve si hay trabajo; `loop` es el unico que programa la siguiente.
     Se separan para que refrescar a mano (tras arrancar el Autopilot) no abra un segundo bucle. */
  async function tick() {
    const {ok, data} = await api('/api/activity');
    if (!ok) {
      failures += 1;
      if (failures > 2 && $('activity-label')) {
        $('activity').className = 'activity bad';
        $('activity-glyph').textContent = '⚠️';
        $('activity-label').textContent = 'motor sin respuesta';
      }
      return failures > 2;
    }
    failures = 0;
    last = data;
    paint(data);
    if (!$('activity-pop').hidden) paintPopover(data);
    return Boolean(data.running) || Boolean((data.autopilot || {}).running);
  }

  async function loop() {
    let busy = false;
    try {
      busy = await tick();
    } catch (error) {
      busy = false;
    }
    window.setTimeout(loop, busy ? POLL_LIVE_MS : POLL_IDLE_MS);
  }

  function wire() {
    if (!$('activity')) return;
    $('activity').addEventListener('click', () => toggle());
    $('auto-start').addEventListener('click', startAutopilot);
    $('auto-stop').addEventListener('click', stopAutopilot);
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') toggle(false);
    });
    document.addEventListener('click', (event) => {
      if (!$('activity-pop').hidden && !event.target.closest('.top-right')) toggle(false);
    });
    loop();
  }

  window.NexusActivity = {refresh: tick};
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
}());
