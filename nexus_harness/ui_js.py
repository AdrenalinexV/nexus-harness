"""The cockpit's behaviour: poll, render, dispatch. Vanilla JS, no build step.

Polling `/api/events?since=` is what makes the cockpit a viewer of a run that happens on the server:
close the tab, reopen it, and the transcript is still there because the bus lives in the server, not
in the page.
"""

JS = r"""
const $ = (id) => document.getElementById(id);
let since = 0, state = null, polling = false;

const LABEL = {
  "run.start": ["run", "INICIO"], "run.end": ["run", "FIN"],
  "director.plan": ["plan", "DIRECTOR"], "director.reasoning": ["plan", "DIRECTOR·razón"],
  "director.error": ["error", "DIRECTOR"], "router.ready": ["run", "MODELOS"],
  "worker.turn": ["worker", "OBRERO"], "worker.reasoning": ["worker", "OBRERO·razón"],
  "worker.blocked": ["error", "BLOQUEO"], "worker.error": ["error", "ERROR"],
  "worker.limit": ["error", "LÍMITE"], "tool.call": ["tool", "TOOL"],
  "skills.injected": ["skills", "SKILLS"], "gate.verdict": ["gate", "GATE"],
  "judge.verdict": ["judge", "JUEZ"], "judge.reasoning": ["judge", "JUEZ·razón"],
  "repair": ["gate", "REPARACIÓN"], "phase.start": ["run", "FASE"],
  "phase.checkpoint": ["gate", "FASE CIERRE"], "session.start": ["session", "SESIÓN"],
  "session.relay": ["session", "RELEVO"], "budget": ["session", "PRESUPUESTO"],
  "relay.warning": ["error", "RELEVO"],
};

// Every interpolation below passes through esc(); the only unescaped strings are fixed markup this
// file writes itself. The feed carries model output, so this is not decoration.
function esc(text) {
  return String(text == null ? "" : text).replace(/[&<>]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;"}[c]));
}

function addRow(kind, detail, payload) {
  const feed = $("feed");
  const meta = LABEL[kind] || ["worker", kind];
  const row = document.createElement("div");
  row.className = "row";
  const bad = (kind === "gate.verdict" && payload && payload.verdict && !payload.verdict.ok);
  row.innerHTML = `<div class="k ${meta[0]} ${bad ? "bad" : ""}">${meta[1]}</div>
                   <div class="v">${esc(detail || "")}</div>`;
  feed.appendChild(row);
  feed.scrollTop = feed.scrollHeight;
  while (feed.children.length > 400) feed.removeChild(feed.firstChild);
}

function paint(stateObj) {
  state = stateObj;
  const run = state.run || {};
  const relay = state.relay || {};
  const budget = (run.budget && run.budget.state) || relay.budget || {};
  const used = budget.used || 0, limit = budget.limit || 0;
  const ratio = budget.ratio == null ? 0 : Math.min(1, budget.ratio);
  $("budget-fill").style.width = (ratio * 100).toFixed(1) + "%";
  $("budget-mark").style.left = ((budget.threshold || 0.7) * 100).toFixed(1) + "%";
  $("budget-text").textContent = !limit
    ? "presupuesto: unmeasured"
    : `presupuesto: ${used}/${limit} tokens (${(ratio * 100).toFixed(0)}%) · relevo a ${((budget.threshold || .7) * 100).toFixed(0)}%`;
  const sid = typeof relay.session === "string" ? relay.session
              : (relay.session && relay.session.id) || "";
  $("session-id").textContent = sid || "—";
  $("relay-tag").textContent = relay.prompt_exists ? "prompt listo" : "";
  $("relay").textContent = sid
    ? `${sid} · ${(relay.sessions || []).length} sesiones · ${(relay.handovers || []).length} relevos`
    : "sin sesión activa";
  $("sessions").innerHTML = (relay.sessions || []).map((s) => `<li>${esc(s)}</li>`).join("");
  $("status").textContent = state.running ? "ejecutando" : (run.exit === 0 ? "verde" : run.exit ? "rojo" : "en reposo");
  $("status").className = "pill " + (state.running ? "warn" : run.exit === 0 ? "ok" : run.exit ? "bad" : "info");
  $("run").disabled = !!state.running;
  $("run-meta").textContent = run.goal
    ? `exit ${run.exit} · ${run.steps || 0} pasos · ${run.repairs || 0} reparaciones · ${(run.root || "").split(/[\\/]/).pop()}`
    : "sin ejecución";
  if (run.verdict) {
    const checks = (run.verdict.checks || []).map((c) =>
      `<span class="pill ${c.ok ? "ok" : "bad"}">${esc(c.name)}${c.exit == null ? "" : " " + c.exit}</span>`).join(" ");
    $("gate").innerHTML = `<span class="pill ${run.verdict.ok ? "ok" : "bad"}">exit ${run.verdict.exit}</span>
      <div class="chips" style="margin-top:8px">${checks}</div>
      <div style="margin-top:8px;color:var(--dim)">${esc((run.verdict.failures || "").slice(0, 400))}</div>`;
    $("verdict-exit").textContent = "exit " + run.verdict.exit;
  }
  if (run.judgement) {
    const j = run.judgement;
    $("judge").innerHTML = `<span class="pill ${j.verdict === "approve" ? "ok" : j.verdict === "skipped" ? "warn" : "bad"}">${esc(j.verdict)}</span>
      <div style="margin-top:6px;color:var(--dim)">${esc(j.reason || "")}${j.model ? " · " + esc(j.model) : ""}</div>`;
  }
  if (run.plan) $("plan").textContent = run.plan;
  if (run.skills) {
    $("skills-count").textContent = (run.skills.names || []).length + " activas";
    $("skills").innerHTML = (run.skills.names || []).map((n) => `<span>${esc(n)}</span>`).join("");
    $("skills-note").textContent = run.skills.note || `≈${run.skills.tokens} tokens inyectados en este turno`;
  }
  const bridge = state.bridge || {pending: 0, items: []};
  $("bridge-tag").textContent = bridge.pending + " en cola";
  $("bridge-items").innerHTML = (bridge.items || []).map((i) =>
    `<li>${esc(i.project)} · ${esc((i.criterion || "").slice(0, 60))} <em>${esc(i.state)}</em></li>`).join("");
  $("footer").textContent = `Nexus-Harness · ${state.config.host}:${state.config.port} · proyecto ${state.config.root} · ${state.config.source}`;
}

function fillSelect(el, options, value) {
  const current = value || el.value;
  el.innerHTML = options.map((o) => `<option value="${esc(o)}">${esc(o)}</option>`).join("");
  if (options.includes(current)) el.value = current;
}

function paintModels(models) {
  const opts = models.options || [];
  fillSelect($("project"), models.projects || [], state && state.config.root);
  for (const role of ["director", "worker", "judge"]) {
    const info = (models.roles || {})[role] || {};
    fillSelect($("role-" + role), opts.length ? opts : [info.spec || ""], info.spec);
  }
}

async function getJSON(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  return {ok: response.ok, data};
}

async function poll() {
  if (polling) return;
  polling = true;
  try {
    const {data} = await getJSON("/api/events?since=" + since);
    for (const event of data.events || []) {
      since = Math.max(since, event.seq);
      addRow(event.kind, event.detail, event.payload || {});
      if (event.kind === "skills.injected" && event.payload) {
        $("skills-count").textContent = (event.payload.names || []).length + " activas";
        $("skills").innerHTML = (event.payload.names || []).map((n) => `<span>${esc(n)}</span>`).join("");
        $("skills-note").textContent = event.payload.note || `≈${event.payload.tokens} tokens`;
      }
      if (event.kind === "director.plan") { $("plan").textContent = event.detail; $("plan-model").textContent = event.payload.model || ""; }
    }
    const st = await getJSON("/api/state");
    if (st.ok) paint(st.data);
  } finally {
    polling = false;
  }
}

async function startRun() {
  const goal = $("goal").value.trim();
  if (!goal) { $("goal").focus(); return; }
  const body = JSON.stringify({goal, project: $("project").value,
                               test_command: $("test-command").value.trim()});
  const {ok, data} = await getJSON("/api/run", {method: "POST", headers: {"Content-Type": "application/json"}, body});
  if (!ok) { addRow("worker.error", data.reason || "no se pudo arrancar", {}); return; }
  $("feed").innerHTML = "";
  addRow("run.start", goal, {});
}

async function swapRole(role, spec) {
  const {ok, data} = await getJSON("/api/roles", {method: "POST",
    headers: {"Content-Type": "application/json"}, body: JSON.stringify({role, spec})});
  if (!ok) addRow("worker.error", data.reason || "modelo rechazado", {});
  else addRow("router.ready", `${role} → ${spec}`, {});
}

$("run").addEventListener("click", startRun);
$("goal").addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") startRun(); });
for (const role of ["director", "worker", "judge"]) {
  $("role-" + role).addEventListener("change", (e) => swapRole(role, e.target.value));
}
$("bridge-run").addEventListener("click", async () => {
  const {ok, data} = await getJSON("/api/bridge", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
  addRow(ok ? "run.start" : "worker.error", ok ? `cola procesada: ${data.ran || 0}` : (data.reason || "fallo"), {});
});

(async function boot() {
  const st = await getJSON("/api/state");
  if (st.ok) { paint(st.data); paintModels(st.data.models || {}); }
  else addRow("worker.error", "el servidor no responde", {});
  const {data} = await getJSON("/api/events?since=0");
  for (const event of data.events || []) { since = Math.max(since, event.seq); addRow(event.kind, event.detail, event.payload || {}); }
  setInterval(poll, 900);
})();
"""
