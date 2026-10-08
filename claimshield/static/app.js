/* SpotZ^i front end — vanilla JS, no build step */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = v => v == null ? "—" : "$" + Math.round(v).toLocaleString("en-US");
const num = v => v == null ? "—" : Math.round(v).toLocaleString("en-US");
const pc = (v, d = 0) => v == null ? "—" : (v * 100).toFixed(d) + "%";
const api = async (u, opt) => {
  const r = await fetch("/api/" + u, opt);
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.statusText); }
  return r.json();
};
const post = (u, body) => api(u, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const FAM = { PRO: "Professional", LAB: "Laboratory", FAC: "Facility", PHARM: "Pharmacy", AMB: "Ambulance", BH: "Behavioral health", HH: "Home health", DME: "DME" };
const COMP = { risk: "#d33a3a", forecast: "#6b4fd8", dollars: "#0f8b9d", members: "#d98a0b", severity: "#e0603a", evidence: "#1f4fd8" };
const COMP_L = { risk: "Risk", forecast: "Forecast", dollars: "Dollars", members: "Member impact", severity: "Severity", evidence: "Evidence" };
const riskColor = r => r < 25 ? "#8fb4e8" : r < 40 ? "#f0b429" : r < 60 ? "#ef7d2d" : "#d33a3a";
const sevTag = l => `<span class="tag ${l === "Critical" ? "t-crit" : l === "High" ? "t-high" : "t-med"}">${l}</span>`;
const laneTag = l => `<span class="tag ${l === "Investigate" ? "t-ok" : l === "Needs more data" ? "t-gray" : "t-high"}">${esc(l)}</span>`;

const S = { view: "overview", horizon: 60, inv: 3, hrs: 24, weeks: 2, weights: null, queue: null, status: null, reviewer: localStorage.getItem("cs_reviewer") || "", role: localStorage.getItem("cs_role") || "investigator", expl: { tab: "providers", prov: { q: "", fam: "" } }, checks: {} };
const capacity = () => S.inv * S.hrs * S.weeks;
let toastT;
function toast(msg) { let t = $(".toast"); if (t) t.remove(); t = document.createElement("div"); t.className = "toast"; t.textContent = msg; document.body.appendChild(t); clearTimeout(toastT); toastT = setTimeout(() => t.remove(), 3200); }

/* ------------------------------------------------------------ charts */
function barsH(items, { fmt = num, color = "#1f4fd8", max } = {}) {
  const m = max || Math.max(...items.map(i => i.value), 1);
  return items.map(i => `<div style="display:grid;grid-template-columns:150px 1fr 90px;gap:10px;align-items:center;margin:6px 0"><span class="sm">${esc(i.label)}</span><div class="bar"><i style="width:${Math.max(1, 100 * i.value / m)}%;background:${i.color || color}"></i></div><span class="sm num" style="text-align:right">${fmt(i.value)}</span></div>`).join("");
}
function monthChart(rows, { a = "paid", b = "flagged", h = 190 } = {}) {
  const W = 640, H = h, p = 28, n = rows.length, bw = (W - p * 2) / n;
  const mx = Math.max(...rows.map(r => r[a]), 1), mb = Math.max(...rows.map(r => r[b]), 1);
  let s = `<svg viewBox="0 0 ${W} ${H + 24}" width="100%">`;
  rows.forEach((r, i) => {
    const x = p + i * bw, hh = (H - 20) * r[a] / mx, h2 = (H - 20) * r[b] / mb;
    s += `<rect x="${x + 2}" y="${H - hh}" width="${bw - 4}" height="${hh}" fill="#dfe7fb"><title>${r.month || r.m}: ${money(r[a])} paid</title></rect>`;
    s += `<rect x="${x + bw * .25}" y="${H - h2}" width="${bw * .5}" height="${h2}" fill="#d33a3a" opacity=".85"><title>${r.month || r.m}: ${money(r[b])} flagged</title></rect>`;
    if (i % 3 === 0 || n < 10) s += `<text x="${x + bw / 2}" y="${H + 14}" font-size="10" text-anchor="middle" fill="#64708a">${(r.month || r.m).slice(2)}</text>`;
  });
  return s + `</svg><div class="sm mut row"><span><i style="display:inline-block;width:10px;height:10px;background:#dfe7fb"></i> total paid (scale 1)</span><span><i style="display:inline-block;width:10px;height:10px;background:#d33a3a"></i> flagged paid (own scale ${money(mb)})</span></div>`;
}
function funnel(rows) {
  const mx = Math.log10(rows[0].value + 1);
  return rows.map((r, i) => `<div style="margin:8px 0"><div class="row sm"><span>${esc(r.label)}</span><span class="sp"></span><b>${num(r.value)}</b></div><div class="bar" style="height:12px"><i style="width:${Math.max(3, 100 * Math.log10(r.value + 1) / mx)}%;background:hsl(${220 - i * 32},70%,${50 + i * 2}%)"></i></div></div>`).join("") + `<div class="sm mut">Bar length is log-scaled.</div>`;
}
function reliability(cal) {
  const W = 260, H = 220, p = 30;
  let s = `<svg viewBox="0 0 ${W} ${H}" width="100%"><rect x="${p}" y="10" width="${W - p - 10}" height="${H - p - 10}" fill="#fff" stroke="#e3e8f0"/><line x1="${p}" y1="${H - p}" x2="${W - 10}" y2="10" stroke="#aab4cc" stroke-dasharray="4"/>`;
  cal.forEach(c => { const x = p + (W - p - 10) * c.predicted, y = H - p - (H - p - 10) * c.observed; s += `<circle cx="${x}" cy="${y}" r="${4 + Math.min(8, c.n / 40)}" fill="#1f4fd8" opacity=".75"><title>n=${c.n} predicted ${pc(c.predicted)} observed ${pc(c.observed)}</title></circle>`; });
  return s + `<text x="${W / 2}" y="${H - 6}" text-anchor="middle" font-size="10" fill="#64708a">predicted probability</text><text transform="translate(10 ${H / 2}) rotate(-90)" text-anchor="middle" font-size="10" fill="#64708a">observed rate</text></svg>`;
}

/* ------------------------------------------------------------ graph */
function graphHTML(g, { height = 460, onNode = "openProv", id = "g", labelMin = -1 } = {}) {
  const ns = g.nodes; if (!ns.length) return `<div class="mut">No relationships.</div>`;
  const xs = ns.map(n => n.x), ys = ns.map(n => n.y), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const W = 1000, H = height / 460 * 560, P = 70;
  const px = n => P + (W - 2 * P) * ((n.x - x0) / ((x1 - x0) || 1)), py = n => P + (H - 2 * P) * ((n.y - y0) / ((y1 - y0) || 1));
  const pos = {}; ns.forEach(n => pos[n.id] = [px(n), py(n)]);
  const ecol = { referral: "#2f6bd7", ownership: "#6b4fd8", address: "#0f8b9d", bank: "#8a6d00", shared_members: "#98a2b8" };
  let s = `<div class="graph" style="height:${height}px"><svg id="${id}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" style="height:${height}px"><defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#2f6bd7"/></marker></defs><g class="vp">`;
  g.edges.forEach(e => {
    const a = pos[e.source], b = pos[e.target]; if (!a || !b) return;
    const w = e.kind === "referral" ? 1 + Math.min(5, Math.log10((e.n || 1) + 1) * 1.8) : 1.6;
    s += `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="${ecol[e.kind]}" stroke-width="${w}" ${e.kind === "shared_members" ? 'stroke-dasharray="2 4"' : e.kind !== "referral" ? 'stroke-dasharray="7 4"' : 'marker-end="url(#ar)"'} opacity=".75"><title>${esc(e.label || e.kind)}</title></line>`;
  });
  ns.forEach(n => {
    const [x, y] = pos[n.id];
    if (n.kind === "provider") {
      const r = 11 + (n.primary ? 4 : 0);
      s += `<g style="cursor:pointer" data-act="${onNode}" data-id="${n.id}"><circle cx="${x}" cy="${y}" r="${r}" fill="${riskColor(n.risk)}" stroke="${n.primary ? "#14213d" : "#fff"}" stroke-width="${n.primary ? 3 : 2}"><title>${esc(n.label)} · ${FAM[n.family]} · risk ${Math.round(n.risk)}</title></circle>${n.risk >= labelMin || n.primary ? `<text x="${x}" y="${y + r + 14}" text-anchor="middle" font-size="12" fill="#14213d">${esc(n.label.length > 24 ? n.label.slice(0, 23) + "…" : n.label)}</text>` : ""}</g>`;
    } else {
      s += `<g><rect x="${x - 9}" y="${y - 9}" width="18" height="18" rx="3" fill="${ecol[n.kind]}" opacity=".9"/><text x="${x}" y="${y + 24}" text-anchor="middle" font-size="11" fill="#38445f">${esc(n.label)}</text></g>`;
    }
  });
  s += `</g></svg><div class="legend"><b>Node</b> colour = risk · ring = case provider<br><span style="color:#2f6bd7">▬ referral</span> · <span style="color:#6b4fd8">▬ ownership</span> · <span style="color:#0f8b9d">▬ address</span> · <span style="color:#8a6d00">▬ bank</span> · <span style="color:#98a2b8">▪ shared members</span><br>Scroll to zoom · drag to pan</div></div>`;
  return s;
}
function wireGraph(id) {
  const svg = document.getElementById(id); if (!svg) return;
  const vb = svg.viewBox.baseVal; const o = { x: vb.x, y: vb.y, w: vb.width, h: vb.height }; let drag = null;
  svg.addEventListener("wheel", e => { e.preventDefault(); const k = e.deltaY > 0 ? 1.12 : .89; const r = svg.getBoundingClientRect(); const mx = vb.x + vb.width * (e.clientX - r.left) / r.width, my = vb.y + vb.height * (e.clientY - r.top) / r.height; vb.x = mx - (mx - vb.x) * k; vb.y = my - (my - vb.y) * k; vb.width *= k; vb.height *= k; }, { passive: false });
  svg.addEventListener("mousedown", e => { drag = { x: e.clientX, y: e.clientY, vx: vb.x, vy: vb.y }; });
  window.addEventListener("mouseup", () => drag = null);
  svg.addEventListener("mousemove", e => { if (!drag) return; const r = svg.getBoundingClientRect(); vb.x = drag.vx - (e.clientX - drag.x) * vb.width / r.width; vb.y = drag.vy - (e.clientY - drag.y) * vb.height / r.height; });
  svg.addEventListener("dblclick", () => { vb.x = o.x; vb.y = o.y; vb.width = o.w; vb.height = o.h; });
}

/* ------------------------------------------------------------ shell */
const NAV = [["overview", "Overview", "◧"], ["queue", "SIU queue", "☰"], ["network", "Network explorer", "◎"], ["explorer", "Providers & claims", "⌕"], ["data", "Data & pipeline", "▤"], ["governance", "Governance", "⛨"]];
function shell(inner) {
  const st = S.status, run = st?.run;
  return `<aside><div class="logo"><div class="mk"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2"><path d="M12 3 4.5 6v5.2c0 4.7 3.2 8.1 7.5 9.8 4.3-1.7 7.5-5.1 7.5-9.8V6L12 3Z"/><circle cx="12" cy="11" r="2"/></svg></div><div><b>SpotZ<sup>i</sup></b><small>FWA intelligence · SIU</small></div></div>
  ${NAV.map(([k, l, i]) => `<button class="nav ${S.view === k || (S.view === "case" && k === "queue") || (S.view === "provider" && k === "explorer") ? "on" : ""}" data-nav="${k}"><b style="width:18px;text-align:center">${i}</b><span>${l}</span>${k === "queue" && S.queue ? `<span class="n">${S.queue.queue.filter(r => r.status !== "Closed").length}</span>` : ""}</button>`).join("")}
  <div class="side-foot"><div><span class="dot ${st?.state === "running" ? "run" : ""}"></span><b>${st?.state === "running" ? "Analysing…" : "Analysis current"}</b></div>${run ? `<div>${run.run_id}</div><div>As of ${run.as_of}</div><div>${run.ruleset} · ${run.model}</div>` : ""}<div style="margin-top:6px">SYNTHETIC DATA ONLY<br>Human decides every outcome</div></div></aside><main>${inner}</main>`;
}
function hdr(title, sub, extra = "") { return `<div class="top"><div><h1>${title}</h1><p>${sub}</p></div><div class="sp"></div>${extra}</div>`; }
const loading = m => `<div class="loading"><span class="spin"></span>${m || "Loading…"}</div>`;

/* ------------------------------------------------------------ router */
function route() {
  const h = location.hash.replace(/^#\/?/, "").split("?")[0].split("/");
  S.view = h[0] || "overview"; S.arg = h[1]; S.tab = h[2];
  render();
}
window.addEventListener("hashchange", route);
const go = h => { location.hash = h; };

async function render() {
  const app = $("#app");
  if (!S.status?.ready) { app.innerHTML = shell(loading(`Running analysis pipeline: ${S.status?.step || "starting"}…`)); return; }
  try {
    const v = { overview: vOverview, queue: vQueue, case: vCase, network: vNetwork, explorer: vExplorer, provider: vProvider, data: vData, governance: vGovernance }[S.view] || vOverview;
    app.innerHTML = shell(loading());
    const html = await v();
    app.innerHTML = shell(html);
    afterRender();
  } catch (e) { app.innerHTML = shell(`<div class="banner red">Something went wrong: ${esc(e.message)}. The previous analysis remains available; no data was changed.</div>`); }
}
async function loadQueue() {
  const w = S.weights ? Object.entries(S.weights).map(([k, v]) => `&w_${k}=${v}`).join("") : "";
  S.queue = await api(`queue?horizon=${S.horizon}&capacity=${capacity()}${w}`);
  if (!S.weights) S.weights = { ...S.queue.defaults };
  return S.queue;
}

/* ------------------------------------------------------------ overview */
async function vOverview() {
  const [o, q] = await Promise.all([api(`overview?horizon=${S.horizon}&capacity=${capacity()}`), loadQueue()]);
  const k = o.kpis, ev = o.run.evaluation;
  return hdr("Overview", `Portfolio as of ${o.run.as_of} · ${num(k.lines)} synthetic claim lines → ${k.cases} evidence-backed cases`, `<a class="btn pri" href="#/queue">Open SIU queue →</a>`) +
    `<div class="journey"><div><b>1 · Load</b><span>9 tables validated</span></div><div><b>2 · Detect</b><span>7 rules + Isolation Forest</span></div><div><b>3 · Connect</b><span>ownership, referral, member graph</span></div><div><b>4 · Forecast</b><span>30/60/90-day repeat risk</span></div><div><b>5 · Rank</b><span>risk × dollars × capacity</span></div><div><b>6 · Investigate</b><span>brief, challenge, human decision</span></div></div>
    <div class="grid g5"><div class="card kpi"><div class="l">Alerts raised</div><div class="v">${num(k.flagged_lines)}</div><div class="s">flagged claim lines (${pc(k.flagged_lines / k.lines, 1)} of volume)</div></div>
    <div class="card kpi"><div class="l">Ranked cases</div><div class="v">${k.cases}</div><div class="s">${k.critical} critical · ${k.escalating} escalating</div></div>
    <div class="card kpi"><div class="l">Potential exposure</div><div class="v">${money(k.exposure)}</div><div class="s">gross flagged dollars, not recovery</div></div>
    <div class="card kpi"><div class="l">Members touched</div><div class="v">${num(k.members)}</div><div class="s">in flagged case lines</div></div>
    <div class="card kpi"><div class="l">Inside capacity</div><div class="v">${k.within}<span class="mut" style="font-size:14px"> / ${k.cases}</span></div><div class="s">${k.hours}h of ${capacity()}h budget</div></div></div>
    <div class="grid g21" style="margin-top:14px"><div class="card"><h3>Top priorities <small>horizon ${S.horizon} days</small></h3>${queueTable(q.queue.slice(0, 5), false)}</div>
    <div class="card"><h3>From alerts to action</h3>${funnel(o.funnel)}</div></div>
    <div class="grid g3" style="margin-top:14px"><div class="card"><h3>Flagged lines by rule</h3>${barsH(o.by_rule.map(r => ({ label: r.name, value: r.lines })))}<div class="sm mut">Rules overlap; one line can trigger several.</div></div>
    <div class="card"><h3>Flagged dollars by family</h3>${barsH(o.by_family.map(r => ({ label: FAM[r.family], value: r.paid })).sort((a, b) => b.value - a.value), { fmt: money, color: "#d33a3a" })}</div>
    <div class="card"><h3>Monthly paid vs flagged</h3>${monthChart(o.monthly.map(m => ({ month: m.m, paid: m.paid, flagged: m.flagged })))}</div></div>
    ${ev?.total_lines ? `<div class="banner blue" style="margin-top:14px"><b>Synthetic self-check.</b> Against hidden scenario labels the queue's top 5 cases are ${pc(ev.precision_at_5)} true-pattern, case recall of seeded bad actors is ${pc(ev.provider_recall)}, and line-level precision is ${pc(ev.line_precision)}. Not evidence of real-world performance — see Governance. ${ev.decoys_in_cases?.length ? `Decoys that look suspicious but are benign (e.g. oncology, dialysis) are deliberately included so the system must express uncertainty.` : ""}</div>` : ""}`;
}

/* ------------------------------------------------------------ queue */
function stackBar(r) { return `<div class="stack" title="${Object.entries(r.contributions).map(([k, v]) => COMP_L[k] + " " + v).join(" · ")}">${Object.entries(r.contributions).map(([k, v]) => `<i style="width:${v / 100 * 100 * 1.0}%;background:${COMP[k]}"></i>`).join("")}</div>`; }
function queueTable(rows, cut = true) {
  let out = `<div style="overflow:auto"><table><tr><th>#</th><th>Case</th><th>Priority</th><th class="num">Risk</th><th class="num">${S.horizon}d fcst</th><th class="num">Exposure</th><th class="num">Members</th><th>Severity</th><th class="num">Evidence</th><th class="num">Hours</th><th>Lane / status</th></tr>`;
  let cutDone = false;
  rows.forEach((r, i) => {
    out += `<tr class="click" data-go="case/${r.case_id}"><td class="b">${r.rank}</td><td style="min-width:260px"><div class="b">${esc(r.title)}</div><div class="sm mut">${r.case_id} · ${esc(r.type)} ${r.network ? `<span class="tag t-vio">network · ${r.n_providers}</span>` : ""} ${r.escalating ? `<span class="tag t-high">escalating</span>` : ""}</div></td>
    <td style="min-width:150px"><div class="row"><b style="width:36px">${r.priority}</b>${stackBar(r)}</div></td><td class="num">${Math.round(r.risk)}</td><td class="num">${r.forecast}%</td><td class="num">${money(r.exposure)}</td><td class="num">${r.members}${r.vulnerable ? `<span class="mut sm"> (${r.vulnerable}↑)</span>` : ""}</td><td>${sevTag(r.severity_label)}</td>
    <td class="num">${Math.round(r.evidence)}</td><td class="num">${r.effort_hours}</td><td>${laneTag(r.lane)} ${r.status !== "New" ? `<span class="tag t-vio">${r.status}</span>` : ""} ${r.capacity === "within" ? `<span class="tag t-ok">✓ scheduled</span>` : r.capacity === "closed" ? "" : `<span class="tag t-gray">${r.lane === "Needs more data" ? "not scheduled" : "over capacity"}</span>`}</td></tr>`;
  });
  return out + `</table></div>`;
}
async function vQueue() {
  const q = await loadQueue();
  const w = S.weights;
  return hdr("SIU queue", "Cases ranked by risk, forecast, potential dollars, member impact, severity and evidence — packed into the review capacity you set.",
    `<div class="seg" id="hz">${[30, 60, 90].map(h => `<button data-hz="${h}" class="${S.horizon === h ? "on" : ""}">${h}-day</button>`).join("")}</div><a class="btn" href="/api/queue.csv?horizon=${S.horizon}&capacity=${capacity()}">Export CSV</a>`) +
    `<div class="grid g2"><div class="card"><h3>Review capacity</h3><div class="grid g3"><div><label class="f">Investigators</label><input type="number" min="1" max="40" value="${S.inv}" data-cap="inv"></div><div><label class="f">Hours / week</label><input type="number" min="1" max="60" value="${S.hrs}" data-cap="hrs"></div><div><label class="f">Weeks</label><input type="number" min="1" max="26" value="${S.weeks}" data-cap="weeks"></div></div>
    <div class="sm mut" style="margin-top:8px">Budget <b>${capacity()}h</b> · scheduled <b>${q.used_hours}h</b> · ${q.queue.filter(r => r.capacity === "within").length} cases fit. Effort = 8h + 7h per primary provider + √flagged lines + member-sample time.</div>
    </div><div class="card"><h3>Priority weights <button class="btn sm" id="wreset" style="float:right">Reset</button></h3>
    ${Object.keys(w).map(k => `<div class="row sm"><span style="width:120px"><i style="display:inline-block;width:9px;height:9px;background:${COMP[k]};border-radius:2px"></i> ${COMP_L[k] === "Dollars" ? "Potential dollars" : COMP_L[k]}</span><input type="range" min="0" max="40" value="${Math.round(w[k] * 100)}" data-w="${k}"><b style="width:30px;text-align:right">${Math.round(w[k] * 100)}</b></div>`).join("")}
    <div class="sm mut" style="margin-top:6px">Priority is a transparent weighted sum. Weak-evidence cases are down-weighted (×0.65) and never scheduled; they surface as "Needs more data".</div></div>
    </div></div><div class="card" style="margin-top:14px"><h3>Ranked cases <small>${q.queue.length} total · click a row for the investigation brief</small></h3>${queueTable(q.queue)}</div>`;
}

/* ------------------------------------------------------------ case */
const TABS = [["brief", "Brief"], ["evidence", "Evidence"], ["network", "Network"], ["timeline", "Timeline"], ["forecast", "Forecast"], ["copilot", "AI copilot"], ["lab", "Challenge lab"], ["claims", "Claims"], ["decision", "Decision"]];
async function vCase() {
  const cid = S.arg, tab = S.tab || "brief";
  const d = await api(`cases/${cid}?horizon=${S.horizon}`);
  S.cd = d; const m = d.metrics;
  const conf = d.confidence;
  let body = "";
  if (tab === "brief") {
    body = `${d.lane === "Needs more data" ? `<div class="banner">⚠ <b>The system abstains.</b> Evidence strength is ${Math.round(m.evidence)}/100 — below the threshold for opening an investigation. Request more information instead; referral is blocked.</div>` : d.lane === "Validate context first" ? `<div class="banner">⚠ Benign context exists for this provider (${esc(d.providers.find(p => p.context)?.context || "")}). Validate it before investing review time.</div>` : ""}
    <div class="grid g21"><div class="card"><h3>Summary</h3><p style="margin-top:0">${esc(d.summary)}</p><h3>Recommended human-review action</h3><p style="margin-top:0">${esc(d.action)}</p>
    <h3>Why the system believes this <small>confidence: ${conf.label}</small></h3><ul style="margin:0;padding-left:18px">${conf.rationale.map(r => `<li>${esc(r)}</li>`).join("")}</ul>
    <div class="row wrap" style="margin-top:10px">${Object.entries(d.signal_flags).map(([k, v]) => `<span class="tag ${v ? "t-ok" : "t-gray"}">${v ? "✓" : "–"} ${{ rules: "Rules", anomaly: "Anomaly", graph: "Graph", temporal: "Escalation" }[k]}</span>`).join("")}</div></div>
    <div class="card"><h3>Competing explanations</h3>${d.hypotheses.map(h => `<div class="hyp"><div><span class="tag ${h.kind === "Suspicious" ? "t-crit" : h.kind === "Legitimate" ? "t-ok" : "t-gray"}">${h.kind}</span> <b>${esc(h.title)}</b><div class="sm mut">${esc(h.summary)}</div></div><div class="b" style="font-size:20px;text-align:right">${h.support}%</div></div>`).join("")}<div class="sm mut">Support scores are not probabilities and need not sum to 100: they show how much evidence leans each way.</div></div></div>
    ${aiCard(d.case_id)}<div class="card" style="margin-top:14px"><h3>Limitations</h3><ul style="margin:0;padding-left:18px">${d.limitations.map(r => `<li>${esc(r)}</li>`).join("")}</ul></div>`;
  } else if (tab === "evidence") {
    body = d.evidence.map(e => `<div class="ev"><h4><span class="mono mut">${e.id}</span> ${esc(e.label)} <span class="tag ${e.strength === "Strong" ? "t-crit" : e.strength === "Moderate" ? "t-high" : "t-gray"}">${e.strength}</span>${e.kind === "rule" ? `<span class="sp"></span><span class="sm mut">${num(e.n_lines)} lines · ${money(e.paid)} · ${e.members} members</span>` : ""}</h4>
      ${e.kind === "rule" ? `<div class="sm">${esc(e.rule_desc)}</div>${e.examples.map(x => `<div class="ex"><span class="mono">${x.line_id}</span> ${x.date} · ${x.code} · ${money(x.paid)} · member ${x.member_id}<br>${esc(x.reason)}</div>`).join("")}<a class="sm" href="#/explorer/claims?rule=${e.rule}&provider=${e.providers[0]}">Open all ${e.n_lines} lines →</a>`
        : e.kind === "anomaly" ? `<div class="sm">Provider ${e.provider} sits at the <b>${pc(e.pct)}</b> percentile of an Isolation Forest within its peer family. Main peer-relative drivers: ${e.drivers.map(x => `${esc(x.feature)} (${x.peer_z > 0 ? "+" : ""}${x.peer_z.toFixed(1)}σ)`).join(", ") || "n/a"}.</div>` : `<div class="sm">${esc(e.detail)}</div>`}
      <div class="sm mut" style="margin-top:6px">Source: ${esc(e.source)}</div></div>`).join("");
  } else if (tab === "network") {
    body = `<div class="grid g21"><div>${graphHTML(d.network, { id: "cg" })}</div><div class="card"><h3>Providers in this case</h3>${d.providers.map(p => `<div style="margin-bottom:10px"><a href="#/provider/${p.provider_id}" class="b">${esc(p.name)}</a> <span class="tag ${p.role === "primary" ? "t-crit" : "t-gray"}">${p.role}</span><div class="sm mut">${FAM[p.family]} · ${esc(p.specialty)} · ${p.city}<br>risk ${Math.round(p.risk)} · ${num(p.lines)} lines (180d) · flagged ${money(p.flagged_paid)}${p.context ? `<br><i>${esc(p.context)}</i>` : ""}</div></div>`).join("")}<div class="sm mut">Linked providers can be innocent bystanders (e.g. a referral source). Links show where to look, not who is culpable.</div></div></div>`;
  } else if (tab === "timeline") {
    body = `<div class="grid g21"><div class="card"><h3>Paid vs flagged by month <small>case providers, all history</small></h3>${monthChart(d.timeline.monthly, { h: 230 })}</div><div class="card"><h3>Key events</h3><div class="tl">${d.timeline.events.map(e => `<div class="${e.kind === "history" ? "h" : ""}"><b>${e.date}</b><br><span class="sm">${esc(e.label)}</span></div>`).join("") || "<span class='mut'>No events.</span>"}</div></div></div>`;
  } else if (tab === "forecast") {
    body = `<div class="banner blue">Forecast = chance the case providers bill ≥3 further simulated-confirmed FWA lines in the next N days. It is a model estimate on synthetic outcomes, not a prediction about any person.</div><div class="grid g3">${[30, 60, 90].map(h => { const f = d.forecast[h], me = f.metrics; return `<div class="card"><h3>${h}-day horizon</h3><div style="font-size:34px;font-weight:700;color:${f.p > .7 ? "#d33a3a" : f.p > .4 ? "#d98a0b" : "#1f9d62"}">${pc(f.p)}</div><div class="bar"><i style="width:${f.p * 100}%;background:#6b4fd8"></i></div>
      <div class="sm" style="margin-top:8px"><b>Why (logistic baseline contributions)</b></div>${f.why.length ? f.why.map(w => `<div class="sm">▲ ${esc(w.feature)} <span class="mut">(value ${w.value.toFixed(2)})</span></div>`).join("") : '<div class="sm mut">No dominant driver.</div>'}
      <div class="sm mut" style="margin-top:8px">Held-out test (later snapshots): AUC ${me.auc.toFixed(2)} · AP ${me.ap.toFixed(2)} · Brier ${me.brier.toFixed(3)} · base rate ${pc(me.base_rate)}. Probabilities are capped at 97% to avoid false certainty.</div></div>`; }).join("")}</div>`;
  } else if (tab === "copilot") {
    body = copilotPanel(d);
  } else if (tab === "lab") {
    const sel = S.checks[cid] || (S.checks[cid] = []);
    const saved = d.checks.filter(c => sel.includes(c.rule)), mins = saved.reduce((a, c) => a + c.minutes, 0), maybe = saved.reduce((a, c) => a + (d.evidence.find(e => e.rule === c.rule)?.paid || 0), 0);
    body = `<div class="banner blue"><b>SpotZ<sup>i</sup> Evidence Challenge Lab.</b> Pick the evidence checks that could distinguish the suspicious from the legitimate explanation. Choose the cheapest checks that could change your mind; your selection is saved with your decision.</div>
    <div class="grid g2"><div class="card"><h3>Hypotheses</h3>${d.hypotheses.map(h => `<div class="hyp"><div><span class="tag ${h.kind === "Suspicious" ? "t-crit" : h.kind === "Legitimate" ? "t-ok" : "t-gray"}">${h.kind}</span> <b>${esc(h.title)}</b></div><div class="b" style="font-size:20px;text-align:right">${h.support}%</div></div>`).join("")}
    <div style="margin-top:12px" class="card"><b>Selected plan:</b> ${saved.length} check(s) · ~${mins} min<br><span class="sm mut">If every selected check came back benign, up to <b>${money(maybe)}</b> of gross exposure (${pc(maybe / d.metrics.exposure)}) could be cleared; lines overlap between rules, so treat this as an upper bound. If none clear, exposure stays at ${money(d.metrics.exposure)}.</span></div></div>
    <div class="card"><h3>Evidence checks</h3>${d.checks.map(c => `<div class="chk ${sel.includes(c.rule) ? "on" : ""}" data-check="${c.rule}"><input type="checkbox" ${sel.includes(c.rule) ? "checked" : ""} style="margin-top:4px"><div><b>${esc(c.rule_name)}</b> <span class="tag t-gray">~${c.minutes} min</span><div class="sm">${esc(c.check)}</div><div class="sm mut">Benign alternatives: ${c.benign.map(esc).join(" · ")}</div><div class="sm" style="color:#17724a">${esc(c.resolves)}</div></div></div>`).join("")}</div></div>`;
  } else if (tab === "claims") {
    const c = await api(`claims?provider_id=${d.providers.find(p => p.role === "primary").provider_id}&limit=60`);
    body = `<div class="card"><h3>Highest-anomaly flagged lines <small>${d.sample_lines.length} sample across case providers; full list in Providers &amp; claims</small></h3>${linesTable(d.sample_lines.map(l => ({ ...l, date: l.date, provider_id: l.provider, member_id: l.member, reasons: [l.reason] })))}</div>`;
  } else if (tab === "decision") {
    body = decisionPanel(d);
  }
  return `<div class="noprint"><a href="#/queue">← SIU queue</a></div>` + hdr(`${esc(d.title)}`, `${d.case_id} · ${esc(d.type)} · ${laneTag(d.lane)} ${d.status !== "New" ? `<span class="tag t-vio">${d.status}</span>` : ""}`,
    `<a class="btn" href="/api/cases/${cid}/brief.md">Export brief (.md)</a><button class="btn" onclick="window.print()">Print</button>`) +
    `<div class="grid g5"><div class="card kpi"><div class="l">Risk</div><div class="v" style="color:${riskColor(m.risk)}">${Math.round(m.risk)}</div><div class="s">rules + anomaly + graph</div></div><div class="card kpi"><div class="l">Gross exposure</div><div class="v">${money(m.exposure)}</div><div class="s">${num(m.flagged_lines)} lines · not a recovery</div></div>
    <div class="card kpi"><div class="l">Members</div><div class="v">${m.members}</div><div class="s">${m.vulnerable} older / Medicaid</div></div><div class="card kpi"><div class="l">Evidence strength</div><div class="v">${Math.round(m.evidence)}</div><div class="s">confidence <b>${conf.label}</b></div></div>
    <div class="card kpi"><div class="l">${S.horizon}-day repeat risk</div><div class="v">${pc(d.forecast[S.horizon].p)}</div><div class="s">est. review ${m.effort_hours}h</div></div></div>
    <div class="tabs">${TABS.map(([k, l]) => `<button class="${tab === k ? "on" : ""}" data-go="case/${cid}/${k}">${l}</button>`).join("")}</div>` + body;
}
const AI = { narr: {}, chat: {}, busy: false };
const aiBadge = o => `<div class="sm mut" style="margin-top:6px">AI-generated by ${esc(o.model)} from the evidence package only · ${o.grounded ? `<span class="tag t-ok">citations verified: ${o.cited.join(", ")}</span>` : `<span class="tag t-crit">citation check failed${o.invalid.length ? ": unknown " + o.invalid.join(", ") : ": no citations"} — do not rely on this text</span>`} · wording only; the human decides.</div>`;
const mdLite = t => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\n\n/g, "<br><br>").replace(/\n/g, "<br>").replace(/\[(EV-\d{3})\]/g, '<a class="tag t-med" href="#/case/' + (S.cd?.case_id || "") + '/evidence">$1</a>');
function aiCard(cid) {
  const n = AI.narr[cid];
  return `<div class="card" style="margin-top:14px"><h3>AI narrative <small>optional · grounded in the evidence above</small> <button class="btn sm" id="genNarr" style="float:right" ${AI.busy ? "disabled" : ""}>${AI.busy ? "Writing…" : n ? "Regenerate" : "Generate"}</button></h3>${n ? (n.error ? `<div class="banner">${esc(n.error)}</div>` : `<div>${mdLite(n.text)}</div>${aiBadge(n)}`) : '<div class="mut sm">Claude rewrites the deterministic evidence as a readable narrative, cites evidence IDs, and states uncertainty. Output is citation-checked; the deterministic brief above is always the source of truth.</div>'}</div>`;
}
function copilotPanel(d) {
  const h = AI.chat[d.case_id] || (AI.chat[d.case_id] = []);
  const sugg = ["What is the strongest evidence and what is the weakest?", "What legitimate explanations could produce this pattern?", "Which single check would change your mind the most?", "What data is missing?"];
  return `<div class="banner blue"><b>AI copilot.</b> Ask about this case. Answers use only this case's evidence package, cite evidence IDs, and are verified. It cannot approve, deny, hold payment or refer — those stay with you.</div>
  <div class="card"><div id="chatlog" style="min-height:120px;max-height:420px;overflow:auto">${h.length ? h.map(m => `<div style="margin:10px 0;${m.role === "user" ? "text-align:right" : ""}"><div style="display:inline-block;max-width:85%;text-align:left;padding:9px 12px;border-radius:12px;background:${m.role === "user" ? "var(--brand)" : "#f1f4fa"};color:${m.role === "user" ? "#fff" : "inherit"}">${m.role === "user" ? esc(m.content) : m.error ? `<span style="color:#a62828">${esc(m.content)}</span>` : mdLite(m.content)}</div>${m.role === "assistant" && !m.error ? aiBadge(m) : ""}</div>`).join("") : `<div class="mut sm">Try a suggestion:</div><div class="pill-row" style="margin-top:8px">${sugg.map(q => `<button class="btn sm" data-ask="${esc(q)}">${esc(q)}</button>`).join("")}</div>`}${AI.busy ? '<div class="mut sm"><span class="spin"></span>Thinking…</div>' : ""}</div>
  <div class="row noprint" style="margin-top:10px"><input type="text" id="askq" placeholder="Ask about this case…" ${AI.busy ? "disabled" : ""}><button class="btn pri" id="askgo" ${AI.busy ? "disabled" : ""}>Ask</button></div></div>`;
}
async function askCopilot(q) {
  const cid = S.cd.case_id, h = AI.chat[cid] || (AI.chat[cid] = []);
  if (!q.trim() || AI.busy) return;
  const hist = h.filter(m => !m.error).map(m => ({ role: m.role, content: m.content }));
  h.push({ role: "user", content: q }); AI.busy = true; render();
  try { const r = await post(`cases/${cid}/ask`, { question: q, history: hist, reviewer: S.reviewer }); h.push({ role: "assistant", ...{ content: r.text, model: r.model, grounded: r.grounded, cited: r.cited, invalid: r.invalid } }); }
  catch (e) { h.push({ role: "assistant", content: e.message, error: true }); }
  AI.busy = false; render();
}
function linesTable(rows) {
  return `<div style="overflow:auto"><table><tr><th>Line</th><th>Date</th><th>Provider</th><th>Member</th><th>Code</th><th class="num">Paid</th><th>Rules</th><th class="num">Anomaly</th><th>Why flagged</th></tr>${rows.map(r => `<tr><td class="mono">${r.line_id}</td><td>${r.date}</td><td><a href="#/provider/${r.provider_id}">${r.provider_id}</a></td><td><a href="#/explorer/members?m=${r.member_id}">${r.member_id}</a></td><td class="mono">${r.code}</td><td class="num">${money(r.paid)}</td><td>${(r.rules || []).map(x => `<span class="tag t-high">${x}</span>`).join(" ")}</td><td class="num">${pc(r.anomaly)}</td><td class="sm">${esc((r.reasons || []).filter(Boolean).join("; "))}</td></tr>`).join("")}</table></div>`;
}
function decisionPanel(d) {
  const st = d.status, pending = st === "Pending supervisor approval";
  const opts = ["Open investigation", "Request more information", "Monitor", "Close - insufficient evidence", "Close - legitimate explanation", "Recommend referral"];
  const sup = ["Approve referral", "Reject referral"];
  return `<div class="grid g2"><div class="card"><h3>Record a human decision</h3><div class="banner blue">The system recommends; <b>you decide</b>. A written rationale is required and everything is logged. Referral needs a second person (supervisor) to approve.</div>
  <div class="grid g2"><div><label class="f">Your name</label><input type="text" id="rv" value="${esc(S.reviewer)}" placeholder="e.g. Alex Morgan"></div><div><label class="f">Role</label><select id="role"><option value="investigator" ${S.role === "investigator" ? "selected" : ""}>Investigator</option><option value="supervisor" ${S.role === "supervisor" ? "selected" : ""}>Supervisor</option></select></div></div>
  <label class="f">Outcome</label><select id="outcome">${(pending ? sup : opts).map(o => `<option>${o}</option>`).join("")}</select>
  <label class="f">Rationale (required)</label><textarea id="reason" placeholder="What evidence did you weigh, and what alternative explanations did you consider?"></textarea>
  <div class="sm mut">Checks selected in the Challenge lab: ${(S.checks[d.case_id] || []).join(", ") || "none"}.</div>
  <div style="margin-top:10px"><button class="btn pri" id="submitDec">Record decision</button></div>
  ${pending ? '<div class="sm mut" style="margin-top:8px">A referral is pending: a supervisor other than the recommender must approve or reject it.</div>' : ""}</div>
  <div class="card"><h3>Decision history <small>status: ${esc(st)}</small></h3>${d.decisions.length ? d.decisions.map(x => `<div style="margin-bottom:10px;border-left:3px solid var(--brand);padding-left:10px"><b>${esc(x.outcome)}</b> <span class="mut sm">${x.ts} · ${esc(x.reviewer)} (${x.role})</span><div class="sm">${esc(x.reason)}</div><div class="sm mut">Run ${x.run_id} · evidence ${Math.round(x.evidence)} · confidence ${x.confidence}</div></div>`).join("") : '<div class="mut">No decisions yet.</div>'}</div></div>`;
}

/* ------------------------------------------------------------ network */
async function vNetwork() {
  const n = await api("network"); S.net = n;
  const caseNodes = n.nodes.filter(x => x.case_id);
  const minRisk = S.netMin ?? 0, q = (S.netQ || "").toLowerCase();
  const keep = new Set(n.nodes.filter(x => x.risk >= minRisk && (!q || x.label.toLowerCase().includes(q) || x.id.toLowerCase().includes(q) || (x.case_id || "").toLowerCase().includes(q))).map(x => x.id));
  // keep neighbours of searched nodes
  if (q) n.edges.forEach(e => { if (keep.has(e.source) || keep.has(e.target)) { keep.add(e.source); keep.add(e.target); } });
  const nodes = n.nodes.filter(x => keep.has(x.id)).map(x => ({ ...x, kind: "provider", primary: !!x.case_id }));
  const edges = n.edges.filter(e => keep.has(e.source) && keep.has(e.target)).flatMap(e => e.kinds.map(k => ({ source: e.source, target: e.target, kind: k === "ownership" || k === "address" || k === "bank" ? k : k, strong: e.strong, label: k })));
  const comms = n.communities.sort((a, b) => b.max_risk - a.max_risk);
  return hdr("Network explorer", "Providers connected by referral flow, shared ownership, address, bank account and overlapping members. Rings ■ are case providers.",
    `<input type="text" id="netq" placeholder="Search provider or case…" value="${esc(S.netQ || "")}" style="width:220px"><div class="row sm">Min risk <input type="range" id="netmin" min="0" max="80" value="${minRisk}" style="width:120px"><b id="netminv">${minRisk}</b></div>`) +
    `<div class="grid g21"><div>${graphHTML({ nodes, edges }, { height: 620, id: "ng", labelMin: 25 })}<div class="sm mut" style="margin-top:6px">${nodes.length} connected providers · ${edges.length} relationships shown (${n.isolated} providers with no notable relationships hidden). Click a provider for details.</div></div>
    <div class="card"><h3>Communities <small>Louvain on weighted ties</small></h3>${comms.slice(0, 10).map(c => `<div style="margin-bottom:10px"><div class="row"><b>Community ${c.id + 1}</b><span class="sp"></span><span class="tag ${c.max_risk >= 40 ? "t-crit" : "t-gray"}">max risk ${Math.round(c.max_risk)}</span></div><div class="sm mut">${c.size} providers · ${c.ties} suspicious tie(s) · avg risk ${Math.round(c.avg_risk)} · ${money(c.paid)} paid (180d)</div><div class="sm">${c.providers.slice(0, 4).map(p => esc(n.nodes.find(x => x.id === p)?.label)).join(", ")}${c.size > 4 ? "…" : ""}</div></div>`).join("")}
    <div class="sm mut">Shared ownership alone is not suspicious (see chain pharmacies): it only matters when linked providers also show risky behaviour.</div></div></div>`;
}

/* ------------------------------------------------------------ explorer */
async function vExplorer() {
  const sub = S.arg || "providers";
  const params = new URLSearchParams((location.hash.split("?")[1] || ""));
  let body = "";
  if (sub === "providers") {
    const rows = await api("providers"); const f = S.expl.prov;
    const r = rows.filter(x => (!f.fam || x.family === f.fam) && (!f.q || (x.name + x.provider_id).toLowerCase().includes(f.q.toLowerCase())));
    body = `<div class="row wrap noprint" style="margin-bottom:10px"><input type="text" id="pq" placeholder="Search providers…" value="${esc(f.q)}" style="width:240px"><select id="pf" style="width:180px"><option value="">All families</option>${Object.entries(FAM).map(([k, v]) => `<option value="${k}" ${f.fam === k ? "selected" : ""}>${v}</option>`).join("")}</select></div>
    <div class="card" style="overflow:auto"><table><tr><th>Provider</th><th>Family</th><th class="num">Risk</th><th class="num">Rules</th><th class="num">Anomaly</th><th class="num">Graph</th><th class="num">60d fcst</th><th class="num">Lines 180d</th><th class="num">Flagged $</th><th>Case</th></tr>${r.slice(0, 80).map(p => `<tr class="click" data-go="provider/${p.provider_id}"><td><b>${esc(p.name)}</b><div class="sm mut">${p.provider_id} · ${p.city}</div></td><td>${FAM[p.family]}</td><td class="num"><b style="color:${riskColor(p.risk)}">${Math.round(p.risk)}</b></td><td class="num">${Math.round(p.rule_score * 100)}</td><td class="num">${pc(p.anomaly_pct)}</td><td class="num">${Math.round(p.graph_score * 100)}</td><td class="num">${pc(p.fc60)}</td><td class="num">${num(p.n_lines)}</td><td class="num">${money(p.flagged_paid)}</td><td>${p.case_id ? `<a href="#/case/${p.case_id}">${p.case_id}</a>` : ""}</td></tr>`).join("")}</table></div>`;
  } else if (sub === "claims") {
    const pv = params.get("provider") || "", rl = params.get("rule") || "", mm = params.get("member") || "", off = +(params.get("off") || 0);
    const c = await api(`claims?provider_id=${pv}&rule=${rl}&member_id=${mm}&limit=50&offset=${off}`);
    const base = `#/explorer/claims?provider=${pv}&rule=${rl}&member=${mm}`;
    body = `<div class="row wrap noprint" style="margin-bottom:10px"><input type="text" id="cp" placeholder="Provider ID (P-0047)" value="${esc(pv)}" style="width:170px"><input type="text" id="cm" placeholder="Member ID (M-00010)" value="${esc(mm)}" style="width:170px"><select id="cr" style="width:210px"><option value="">Any flagged rule</option>${["DUP", "REPEAT", "UNBUNDLE", "UPCODE", "PHANTOM", "TIMING", "EXCESS"].map(r => `<option ${rl === r ? "selected" : ""}>${r}</option>`).join("")}</select><button class="btn" id="cgo">Apply</button><span class="sm mut">${num(c.total)} lines · ${money(c.paid)}</span></div>
    <div class="card">${linesTable(c.rows)}<div class="row" style="margin-top:10px"><a class="btn sm" href="${base}&off=${Math.max(0, off - 50)}">← Prev</a><a class="btn sm" href="${base}&off=${off + 50}">Next →</a></div></div>`;
  } else {
    const mid = params.get("m") || "";
    let det = "";
    if (mid) { try { const m = await api("members/" + mid); det = `<div class="card"><h3>${m.member_id} <small>${m.profile.plan} · age ${m.profile.age} · ${m.profile.region}${m.profile.vulnerable ? " · vulnerable" : ""}${m.profile.death_date ? " · deceased " + m.profile.death_date : ""}${m.profile.term_date ? " · termed " + m.profile.term_date : ""}</small></h3>
      ${m.stays.length ? `<div class="banner blue">Inpatient stays: ${m.stays.map(s => `${s.admit_date.slice(0, 10)} → ${s.discharge_date.slice(0, 10)}`).join("; ")}</div>` : ""}
      <table><tr><th>Date</th><th>Provider</th><th>Code</th><th class="num">Paid</th><th>Rules</th></tr>${m.lines.map(l => `<tr><td>${l.date}</td><td>${l.provider}</td><td class="mono">${l.code}</td><td class="num">${money(l.paid)}</td><td>${l.rules.map(x => `<span class="tag t-high">${x}</span>`).join(" ")}</td></tr>`).join("")}</table></div>`; } catch (e) { det = `<div class="banner red">${esc(e.message)}</div>`; } }
    body = `<div class="row noprint" style="margin-bottom:10px"><input type="text" id="mq" placeholder="Member ID (M-00010)" value="${esc(mid)}" style="width:200px"><button class="btn" id="mgo">Look up</button></div>${det || '<div class="mut">Enter a synthetic member ID to see their service timeline against inpatient stays.</div>'}`;
  }
  return hdr("Providers & claims", "Drill from provider risk to individual claim lines with the rule that fired and why.",
    `<div class="seg">${["providers", "claims", "members"].map(t => `<button class="${sub === t ? "on" : ""}" data-go="explorer/${t}">${t[0].toUpperCase() + t.slice(1)}</button>`).join("")}</div>`) + body;
}
async function vProvider() {
  const p = await api("providers/" + S.arg);
  const pr = p.profile, sc = p.scores;
  return `<div class="noprint"><a href="#/explorer/providers">← Providers</a></div>` + hdr(esc(pr.name), `${p.provider_id} · ${FAM[pr.family]} · ${esc(pr.specialty)} · ${pr.city} · ${pr.npi} (synthetic)`) +
    (pr.context_note ? `<div class="banner">ℹ ${esc(pr.context_note)}</div>` : "") +
    `<div class="grid g5">${[["Risk", Math.round(sc.risk), riskColor(sc.risk)], ["Rule score", Math.round(sc.rule_score * 100)], ["Anomaly percentile", pc(sc.anomaly_pct)], ["Graph score", Math.round(sc.graph_score * 100)], ["Repeat risk 30/60/90", [sc.fc30, sc.fc60, sc.fc90].map(x => Math.round(x * 100)).join(" / ") + "%"]].map(([l, v, c]) => `<div class="card kpi"><div class="l">${l}</div><div class="v" style="${c ? "color:" + c : ""}">${v}</div></div>`).join("")}</div>
    <div class="grid g2" style="margin-top:14px"><div class="card"><h3>Rule hits <small>180-day lookback</small></h3>${barsH(Object.entries(p.rules).map(([k, r]) => ({ label: r.name, value: r.lines })))}<h3 style="margin-top:14px">Peer-relative anomaly drivers</h3>${p.anomaly_drivers.length ? p.anomaly_drivers.map(d => `<div class="sm">${esc(d.feature)}: ${d.peer_z > 0 ? "+" : ""}${d.peer_z.toFixed(1)}σ vs ${FAM[pr.family]} peers</div>`).join("") : '<div class="sm mut">No strong outliers.</div>'}</div>
    <div class="card"><h3>Paid vs flagged by month</h3>${monthChart(p.monthly)}<h3 style="margin-top:14px">Top codes</h3><table><tr><th>Code</th><th class="num">Lines</th><th class="num">Paid</th><th class="num">Flagged</th></tr>${p.codes.slice(0, 6).map(c => `<tr><td class="mono">${c.code}</td><td class="num">${num(c.lines)}</td><td class="num">${money(c.paid)}</td><td class="num">${num(c.flagged)}</td></tr>`).join("")}</table></div></div>
    <div class="card" style="margin-top:14px"><h3>Relationships <small>1-hop</small></h3>${graphHTML(p.network, { id: "pg", height: 420 })}<div style="margin-top:8px"><a class="btn sm" href="#/explorer/claims?provider=${p.provider_id}">View flagged claims →</a></div></div>`;
}

/* ------------------------------------------------------------ data */
async function vData() {
  const [d, st] = await Promise.all([api("data"), api("status")]);
  const v = d.validation;
  return hdr("Data & pipeline", "Synthetic claims and related tables are loaded, validated and analysed end-to-end. Validation failures stop a run and the previous analysis stays live.",
    `<div class="card" style="padding:10px 14px"><div class="row"><label class="sm">Seed</label><input type="number" id="seed" value="7" style="width:80px"><label class="sm">Members</label><input type="number" id="mem" value="2500" step="500" min="500" max="6000" style="width:90px"><button class="btn pri" id="rerun" ${st.state === "running" ? "disabled" : ""}>${st.state === "running" ? "Running…" : "Regenerate + re-run"}</button></div></div>`) +
    `<div class="grid g2"><div class="card"><h3>Validation <small>${v.errors.length} errors · ${v.warnings.length} warnings</small></h3>${v.checks.map(c => `<div class="row" style="padding:5px 0;border-bottom:1px solid #eef1f6"><span class="tag ${c.status === "pass" ? "t-ok" : c.status === "warn" ? "t-high" : "t-crit"}">${c.status}</span><b class="sm">${esc(c.name)}</b><span class="sp"></span><span class="sm mut">${esc(c.detail)}</span></div>`).join("")}</div>
    <div class="card"><h3>Pipeline run <small>${d.log.length ? d.log[d.log.length - 1].seconds + "s total" : ""}</small></h3>${d.log.map(l => `<div style="padding:5px 0;border-bottom:1px solid #eef1f6"><b class="sm">${esc(l.step)}</b> <span class="mut sm">+${l.seconds}s</span><div class="sm mut">${esc(l.detail)}</div></div>`).join("")}</div></div>
    <div class="card" style="margin-top:14px"><h3>Tables</h3><div class="grid g3">${d.tables.map(t => `<div style="border:1px solid var(--line);border-radius:10px;padding:10px"><b>${t.name}</b> <span class="mut sm">${num(t.rows)} rows</span><div class="sm mut" style="margin:4px 0;word-break:break-word">${t.columns.join(" · ")}</div></div>`).join("")}</div></div>
    <div class="card" style="margin-top:14px"><h3>Code reference <small>public billing-code identifiers with invented prices</small></h3><div style="max-height:260px;overflow:auto"><table><tr><th>Code</th><th>Family</th><th>Description</th><th class="num">Base price</th></tr>${d.codes.map(c => `<tr><td class="mono">${c.code}</td><td>${FAM[c.family]}</td><td>${esc(c.description)}</td><td class="num">${money(c.price)}</td></tr>`).join("")}</table></div></div>`;
}

/* ------------------------------------------------------------ governance */
async function vGovernance() {
  const [g, a] = await Promise.all([api("governance"), api("audit")]);
  const ev = g.run.evaluation, fm = g.forecast.metrics;
  return hdr("Governance & responsible AI", "How the system keeps humans in control, shows uncertainty, and fails safely.") +
    `<div class="grid g2"><div class="card"><h3>Principles in the product</h3><ul style="margin:0;padding-left:18px">${g.principles.map(p => `<li style="margin-bottom:6px">${esc(p)}</li>`).join("")}</ul></div>
    <div class="card"><h3>Known limitations</h3><ul style="margin:0;padding-left:18px">${g.limitations.map(p => `<li style="margin-bottom:6px">${esc(p)}</li>`).join("")}</ul>
    <h3 style="margin-top:14px">Synthetic self-evaluation</h3><div class="sm">${ev.note}</div><table><tr><td>Line-level precision / recall</td><td class="num">${pc(ev.line_precision)} / ${pc(ev.line_recall)}</td></tr><tr><td>Raw alerts → cases</td><td class="num">${num(ev.raw_flagged_lines)} → ${ev.cases}</td></tr><tr><td>Precision@5 / @10 of case queue</td><td class="num">${pc(ev.precision_at_5)} / ${pc(ev.precision_at_10)}</td></tr><tr><td>Seeded bad-actor provider recall</td><td class="num">${pc(ev.provider_recall)}</td></tr><tr><td>Benign providers surfaced as cases (decoys)</td><td class="num">${ev.decoys_in_cases.length}</td></tr></table></div></div>
    <div class="card" style="margin-top:14px"><h3>Forecast model card <small>logistic regression + gradient boosting ensemble · temporal split</small></h3><div class="grid g3">${[30, 60, 90].map(h => `<div><b>${h}-day</b><table><tr><td>Test AUC</td><td class="num">${fm[h].auc.toFixed(3)}</td></tr><tr><td>Rules-only AUC baseline</td><td class="num">${fm[h].baseline_auc_flag_share.toFixed(3)}</td></tr><tr><td>Average precision</td><td class="num">${fm[h].ap.toFixed(3)}</td></tr><tr><td>Brier</td><td class="num">${fm[h].brier.toFixed(3)}</td></tr><tr><td>Base rate</td><td class="num">${pc(fm[h].base_rate)}</td></tr><tr><td>Train / test rows</td><td class="num">${fm[h].train_rows} / ${fm[h].test_rows}</td></tr></table>${reliability(g.forecast.calibration[h])}</div>`).join("")}</div>
    <div class="sm mut">Training uses only snapshots whose label window ends before the test period (no leakage). Synthetic data is easy; expect much lower real-world performance. The ensemble barely beats the simple flag-rate baseline, which is itself a useful honesty check.</div></div>
    <div class="card" style="margin-top:14px"><h3>Rule catalogue <small>${g.run.ruleset}</small></h3><div style="overflow:auto"><table><tr><th>Rule</th><th>What it detects</th><th>Benign explanations considered</th><th>Check that distinguishes</th></tr>${g.rules.map(r => `<tr><td><b>${r.name}</b><div class="mono mut">${r.key}</div></td><td class="sm">${esc(r.desc)}</td><td class="sm">${r.benign.map(esc).join("<br>")}</td><td class="sm">${esc(r.check)}</td></tr>`).join("")}</table></div></div>
    <div class="grid g2" style="margin-top:14px"><div class="card"><h3>Decision log</h3>${a.decisions.length ? a.decisions.map(x => `<div class="sm" style="padding:5px 0;border-bottom:1px solid #eef1f6"><b>${x.case_id}</b> ${esc(x.outcome)} <span class="mut">· ${esc(x.reviewer)} (${x.role}) · ${x.ts}</span><br>${esc(x.reason)}</div>`).join("") : '<div class="mut">No decisions recorded yet.</div>'}</div>
    <div class="card"><h3>Audit trail</h3><div style="max-height:360px;overflow:auto">${a.audit.map(x => `<div class="sm" style="padding:4px 0;border-bottom:1px solid #eef1f6"><span class="mut">${x.ts}</span> <b>${esc(x.actor)}</b> ${esc(x.action)} ${esc(x.target)}</div>`).join("") || '<div class="mut">Empty.</div>'}</div></div></div>`;
}

/* ------------------------------------------------------------ events */
document.addEventListener("click", async e => {
  const t = e.target;
  const nav = t.closest("[data-nav]"); if (nav) return go("/" + nav.dataset.nav);
  const g = t.closest("[data-go]"); if (g) return go("/" + g.dataset.go);
  const hz = t.closest("[data-hz]"); if (hz) { S.horizon = +hz.dataset.hz; return render(); }
  const op = t.closest('[data-act="openProv"]'); if (op) return go("/provider/" + op.dataset.id);
  const ck = t.closest("[data-check]"); if (ck) { const c = S.cd.case_id, arr = S.checks[c] || (S.checks[c] = []), r = ck.dataset.check; const i = arr.indexOf(r); i >= 0 ? arr.splice(i, 1) : arr.push(r); return render(); }
  if (t.id === "genNarr") { const cid = S.cd.case_id; AI.busy = true; render(); try { AI.narr[cid] = await post(`cases/${cid}/narrative`, {}); } catch (err) { AI.narr[cid] = { error: err.message }; } AI.busy = false; return render(); }
  if (t.id === "askgo") return askCopilot($("#askq").value);
  const aq = t.closest("[data-ask]"); if (aq) return askCopilot(aq.dataset.ask);
  if (t.id === "wreset") { S.weights = null; return render(); }
  if (t.id === "submitDec") {
    const body = { reviewer: $("#rv").value, role: $("#role").value, outcome: $("#outcome").value, reason: $("#reason").value, checks: S.checks[S.cd.case_id] || [] };
    S.reviewer = body.reviewer; S.role = body.role; localStorage.setItem("cs_reviewer", S.reviewer); localStorage.setItem("cs_role", S.role);
    try { const r = await post(`cases/${S.cd.case_id}/decision`, body); toast("Recorded · status: " + r.status); render(); } catch (err) { toast(err.message); }
  }
  if (t.id === "cgo") go(`/explorer/claims?provider=${$("#cp").value}&rule=${$("#cr").value}&member=${$("#cm").value}`);
  if (t.id === "mgo") go(`/explorer/members?m=${$("#mq").value}`);
  if (t.id === "rerun") { await post("run", { seed: +$("#seed").value, members: +$("#mem").value }); toast("Pipeline started; the current analysis stays live until it finishes"); poll(); }
});
document.addEventListener("input", e => {
  const t = e.target;
  if (t.dataset.w) { S.weights[t.dataset.w] = t.value / 100; t.nextElementSibling.textContent = t.value; clearTimeout(S.wt); S.wt = setTimeout(render, 350); }
  if (t.dataset.cap) { S[t.dataset.cap] = Math.max(1, +t.value || 1); clearTimeout(S.ct); S.ct = setTimeout(render, 500); }
  if (t.id === "pq") { S.expl.prov.q = t.value; clearTimeout(S.pt); S.pt = setTimeout(async () => { const p = $("#pq"); const pos = p.selectionStart; await render(); const n = $("#pq"); n.focus(); n.setSelectionRange(pos, pos); }, 300); }
  if (t.id === "netq") { S.netQ = t.value; clearTimeout(S.nt); S.nt = setTimeout(async () => { await render(); const n = $("#netq"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }, 400); }
  if (t.id === "netmin") { S.netMin = +t.value; $("#netminv").textContent = t.value; clearTimeout(S.nt); S.nt = setTimeout(render, 300); }
});
document.addEventListener("keydown", e => { if (e.key === "Enter" && e.target.id === "askq") askCopilot(e.target.value); });
document.addEventListener("change", e => { if (e.target.id === "pf") { S.expl.prov.fam = e.target.value; render(); } });
function afterRender() { ["cg", "ng", "pg"].forEach(wireGraph); }

async function poll() {
  S.status = await api("status");
  if (S.status.state === "running" || !S.status.ready) { if (!S.status.ready || S.view === "data") render(); setTimeout(poll, 1500); }
  else { S.queue = null; S.weights = S.weights; render(); }
}
(async function boot() { S.status = await api("status"); route(); if (S.status.state === "running") poll(); })();
