/* SpotZⁱ front end — vanilla JS, no build step */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = v => v == null ? "—" : "$" + Math.round(v).toLocaleString("en-US");
const num = v => v == null ? "—" : Math.round(v).toLocaleString("en-US");
const pc = (v, d = 0) => v == null ? "—" : (v * 100).toFixed(d) + "%";
const CONTRACT = "4";
const api = async (u, opt = {}) => {
  if (!navigator.onLine && opt.method && opt.method !== "GET") throw new Error("You are offline. SpotZⁱ is read-only until the connection returns; nothing was queued.");
  opt.headers = { ...(opt.headers || {}), "X-SpotZi-Contract": CONTRACT };
  let r;
  try { r = await fetch("/api/" + u, opt); } catch (e) { throw new Error(navigator.onLine ? "Server unreachable" : "You are offline. Showing nothing rather than stale data."); }
  if (r.status === 409) { const e = await r.clone().json().catch(() => ({})); if (e.refresh) { showUpdate(true); throw new Error(e.detail); } }
  if (r.status === 401 && u !== "login") { S.user = null; renderLogin(); throw new Error("Sign in required"); }
  if (r.status === 403) { const e = await r.clone().json().catch(() => ({})); if (e.detail === "mfa_enrollment_required") { renderEnrol(); throw new Error("Two-factor setup required"); } }
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.statusText); }
  return r.json();
};
const post = (u, body) => api(u, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const FAM = { PRO: "Professional", LAB: "Laboratory", FAC: "Facility", PHARM: "Pharmacy", AMB: "Ambulance", BH: "Behavioral health", HH: "Home health", DME: "DME" };
const COMP = { risk: "#B4423C", forecast: "#A0A4AB", dollars: "#5A5E66", members: "#C28A1B", severity: "#D9772B", evidence: "#1E2024" };
const COMP_L = { risk: "Risk", forecast: "Forecast", dollars: "Dollars", members: "Member impact", severity: "Severity", evidence: "Evidence" };
const riskColor = r => r < 25 ? "#A0A4AB" : r < 40 ? "#C28A1B" : r < 60 ? "#D9772B" : "#B4423C";
const sevTag = l => `<span class="tag ${l === "Critical" ? "t-crit" : l === "High" ? "t-high" : "t-med"}">${l}</span>`;
const laneTag = l => `<span class="tag ${l === "Investigate" ? "t-ok" : l === "Needs more data" || l === "Explained by context" ? "t-gray" : l === "Brain lead" ? "t-vio" : "t-high"}">${esc(l)}</span>`;

const S = { view: "overview", horizon: 60, inv: 3, hrs: 24, weeks: 2, weights: null, queue: null, status: null, reviewer: localStorage.getItem("cs_reviewer") || "", role: localStorage.getItem("cs_role") || "investigator", expl: { tab: "providers", prov: { q: "", fam: "" } }, checks: {} };
const capacity = () => S.inv * S.hrs * S.weeks;
let toastT;
function toast(msg) { let t = $(".toast"); if (t) t.remove(); t = document.createElement("div"); t.className = "toast"; t.textContent = msg; document.body.appendChild(t); clearTimeout(toastT); toastT = setTimeout(() => t.remove(), 3200); }

/* ------------------------------------------------------------ charts */
function barsH(items, { fmt = num, color = "#1E2024", max } = {}) {
  const m = max || Math.max(...items.map(i => i.value), 1);
  return items.map(i => `<div style="display:grid;grid-template-columns:150px 1fr 90px;gap:10px;align-items:center;margin:6px 0"><span class="sm">${esc(i.label)}</span><div class="bar"><i style="width:${Math.max(1, 100 * i.value / m)}%;background:${i.color || color}"></i></div><span class="sm num" style="text-align:right">${fmt(i.value)}</span></div>`).join("");
}
function monthChart(rows, { a = "paid", b = "flagged", h = 190 } = {}) {
  const W = 640, H = h, p = 28, n = rows.length, bw = (W - p * 2) / n;
  const mx = Math.max(...rows.map(r => r[a]), 1), mb = Math.max(...rows.map(r => r[b]), 1);
  let s = `<svg viewBox="0 0 ${W} ${H + 24}" width="100%">`;
  rows.forEach((r, i) => {
    const x = p + i * bw, hh = (H - 20) * r[a] / mx, h2 = (H - 20) * r[b] / mb;
    s += `<rect x="${x + 2}" y="${H - hh}" width="${bw - 4}" height="${hh}" fill="#DDE0EA"><title>${r.month || r.m}: ${money(r[a])} paid</title></rect>`;
    s += `<rect x="${x + bw * .25}" y="${H - h2}" width="${bw * .5}" height="${h2}" fill="#B4423C" opacity=".85"><title>${r.month || r.m}: ${money(r[b])} flagged</title></rect>`;
    if (i % 3 === 0 || n < 10) s += `<text x="${x + bw / 2}" y="${H + 14}" font-size="10" text-anchor="middle" fill="#6E727A">${(r.month || r.m).slice(2)}</text>`;
  });
  return s + `</svg><div class="sm mut row"><span><i style="display:inline-block;width:10px;height:10px;background:#DDE0EA"></i> total paid (scale 1)</span><span><i style="display:inline-block;width:10px;height:10px;background:#B4423C"></i> flagged paid (own scale ${money(mb)})</span></div>`;
}
function funnel(rows) {
  const mx = Math.log10(rows[0].value + 1);
  return rows.map((r, i) => `<div style="margin:8px 0"><div class="row sm"><span>${esc(r.label)}</span><span class="sp"></span><b>${num(r.value)}</b></div><div class="bar" style="height:12px"><i style="width:${Math.max(3, 100 * Math.log10(r.value + 1) / mx)}%;background:${["#1E2024","#3E4566","#6E727A","#A0A4AB","#55595F","#B4423C"][i] || "#6E727A"}"></i></div></div>`).join("") + `<div class="sm mut">Bar length is log-scaled.</div>`;
}
function reliability(cal) {
  const W = 260, H = 220, p = 30;
  let s = `<svg viewBox="0 0 ${W} ${H}" width="100%"><rect x="${p}" y="10" width="${W - p - 10}" height="${H - p - 10}" fill="#fff" stroke="#DDE0EA"/><line x1="${p}" y1="${H - p}" x2="${W - 10}" y2="10" stroke="#A0A4AB" stroke-dasharray="4"/>`;
  cal.forEach(c => { const x = p + (W - p - 10) * c.predicted, y = H - p - (H - p - 10) * c.observed; s += `<circle cx="${x}" cy="${y}" r="${4 + Math.min(8, c.n / 40)}" fill="#1E2024" opacity=".75"><title>n=${c.n} predicted ${pc(c.predicted)} observed ${pc(c.observed)}</title></circle>`; });
  return s + `<text x="${W / 2}" y="${H - 6}" text-anchor="middle" font-size="10" fill="#6E727A">predicted probability</text><text transform="translate(10 ${H / 2}) rotate(-90)" text-anchor="middle" font-size="10" fill="#6E727A">observed rate</text></svg>`;
}

/* ------------------------------------------------------------ graph */
const FICON = {   // 24×24 stroke glyphs, one per provider type
  PRO: "M7 3v5a4 4 0 0 0 8 0V3 M11 12v2.5a4.5 4.5 0 0 0 9 0V13 M20 13a1.6 1.6 0 1 0 0-3.2 1.6 1.6 0 0 0 0 3.2z M5.5 3h3 M13.5 3h3",
  LAB: "M9 3h6 M10 3v6.5L5 18a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 18l-5-8.5V3 M7.6 15h8.8",
  FAC: "M4 21V8l8-4.5L20 8v13 M3 21h18 M9.5 21v-5h5v5 M12 8.5v4 M10 10.5h4",
  PHARM: "M10.2 3.8a5 5 0 0 1 7 7l-6.4 6.4a5 5 0 0 1-7-7z M7.5 10.5l6 6",
  AMB: "M2.5 16.5V7.5h11v9 M13.5 10.5h4.2l3.3 3.3v2.7h-7.5 M6.5 19.3a1.8 1.8 0 1 0 0-3.6 1.8 1.8 0 0 0 0 3.6z M17 19.3a1.8 1.8 0 1 0 0-3.6 1.8 1.8 0 0 0 0 3.6z M8 9.5v4 M6 11.5h4",
  BH: "M12 20.5s-7.5-4.6-7.5-10.3A4.2 4.2 0 0 1 12 7.6a4.2 4.2 0 0 1 7.5 2.6c0 5.7-7.5 10.3-7.5 10.3z M8.5 12h2l1-2 1.5 4 1-2h1.5",
  HH: "M3 11.5 12 4l9 7.5 M5.5 9.5V20h13V9.5 M12 12.5v5 M9.5 15h5",
  DME: "M10 5.2a1.6 1.6 0 1 0 0-3.2 1.6 1.6 0 0 0 0 3.2z M10 7.5V14h5.5l3 5.5 M10 10.5h5 M14.5 19.5A5 5 0 1 1 7.6 12.4",
};
const EICON = {
  ownership: "M4 20h16 M6 20V9.5l6-5 6 5V20 M10 20v-4h4v4",
  address: "M12 21s-6-5.6-6-10.5a6 6 0 0 1 12 0C18 15.4 12 21 12 21z M12 12a1.8 1.8 0 1 0 0-3.6 1.8 1.8 0 0 0 0 3.6z",
  bank: "M3 9.5 12 4.5l9 5 M5 10.5v7 M9.7 10.5v7 M14.3 10.5v7 M19 10.5v7 M3 20h18",
};
const ARROW = new Set(["referral", "ordered_tests", "prescribed", "ordered_equipment", "home_care", "behavioral_referral", "transport"]);
const EDGE = { ordered_tests: { c: "#4A4E55", l: "Ordered tests at" }, prescribed: { c: "#4A4E55", l: "Prescribed (filled at)" }, ordered_equipment: { c: "#4A4E55", l: "Ordered equipment from" },
  home_care: { c: "#4A4E55", l: "Referred for home care" }, behavioral_referral: { c: "#4A4E55", l: "Referred for behavioral care" }, transport: { c: "#4A4E55", l: "Requested transport" },
  primary_care: { c: "#6E727A", l: "Primary-care physician of" }, practices_at: { c: "#0F766E", l: "Practises at hospital" }, shared_patients: { c: "#A0A4AB", l: "Shares many patients" },
  billed: { c: "#A0A4AB", l: "Billed for patient" }, billed_flag: { c: "#B4423C", l: "Billed — flagged claims" }, admitted: { c: "#0F766E", l: "Admitted (inpatient stay)" }, referral: { c: "#4A4E55", l: "Referral flow" }, ownership: { c: "#55595F", l: "Shared ownership" }, address: { c: "#4D7C0F", l: "Shared address" }, bank: { c: "#7B2323", l: "Shared bank account" }, shared_members: { c: "#A0A4AB", l: "Shared members" } };
const riskBand = r => r >= 60 ? "Critical" : r >= 40 ? "High" : r >= 25 ? "Elevated" : "Low";
const GRAPHS = {};

function hullPts(pts) {   // monotone-chain convex hull
  if (pts.length < 3) return pts;
  const p = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]), cr = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lo = [], up = [];
  for (const q of p) { while (lo.length >= 2 && cr(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); }
  for (const q of p.reverse()) { while (up.length >= 2 && cr(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q); }
  return lo.slice(0, -1).concat(up.slice(0, -1));
}

function graphHTML(g, { height = 460, onNode = "openProv", id = "g", labelMin = -1, hulls = false, hullSet = null, canvas = null, legend = true } = {}) {
  const ns = g.nodes; if (!ns.length) return `<div class="mut">No relationships.</div>`;
  const ent = n => n.kind && n.kind !== "provider" && n.kind !== "patient";
  const pat = n => n.kind === "patient";
  const isCard = n => !ent(n) && !pat(n) && (n.primary || n.case_id || n.risk >= labelMin || labelMin < 0);
  const size = n => pat(n) ? [n.primary ? 190 : 132, n.primary ? 44 : 30] : ent(n) ? [Math.max(70, n.label.length * 6.4 + 34), 24] : isCard(n) ? [212, 44] : [34, 34];
  // 1) map layout to a canvas sized for cards, 2) separate overlapping boxes (axis-aligned), 3) fit viewBox
  const xs = ns.map(n => n.x), ys = ns.map(n => n.y), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const span = Math.max(x1 - x0, y1 - y0) || 1, CW = canvas || Math.max(ns.length < 12 ? 240 : 520, Math.min(1500, 105 * Math.sqrt(ns.length)));
  const P = ns.map(n => ({ n, x: (n.x - x0) / span * CW, y: (n.y - y0) / span * CW, w: size(n)[0], h: size(n)[1] }));
  for (let it = 0; it < 140; it++) {
    let moved = false;
    for (let i = 0; i < P.length; i++) for (let j = i + 1; j < P.length; j++) {
      const a = P[i], b = P[j], ox = (a.w + b.w) / 2 + 18 - Math.abs(a.x - b.x), oy = (a.h + b.h) / 2 + 22 - Math.abs(a.y - b.y);
      if (ox > 0 && oy > 0) {
        moved = true;
        if (ox * .55 < oy) { const d = (a.x <= b.x ? -1 : 1) * ox / 2; a.x += d; b.x -= d; } else { const d = (a.y <= b.y ? -1 : 1) * oy / 2; a.y += d; b.y -= d; }
      }
    }
    if (!moved) break;
  }
  const M = 60, bx0 = Math.min(...P.map(p => p.x - p.w / 2)) - M, by0 = Math.min(...P.map(p => p.y - p.h / 2)) - M - 30, bx1 = Math.max(...P.map(p => p.x + p.w / 2)) + M, by1 = Math.max(...P.map(p => p.y + p.h / 2)) + M;
  const W = bx1 - bx0, H = by1 - by0;
  const pos = {}; P.forEach(p => pos[p.n.id] = p);
  const adj = {}; const add = (a, b) => ((adj[a] = adj[a] || new Set()).add(b));
  g.edges.forEach(e => { add(e.source, e.target); add(e.target, e.source); });
  GRAPHS[id] = { nodes: Object.fromEntries(ns.map(n => [n.id, n])), adj: Object.fromEntries(Object.entries(adj).map(([k, v]) => [k, [...v]])), onNode, edges: g.edges };
  const clip = (p, dx, dy, pad) => { const hw = p.w / 2 + pad, hh = p.h / 2 + pad; const t = Math.min(hw / (Math.abs(dx) || 1e-9), hh / (Math.abs(dy) || 1e-9)); return [p.x + dx * t, p.y + dy * t]; };
  const present = new Set(g.edges.map(e => e.kind === "billed" && e.flagged > 0 ? "billed_flag" : e.kind));
  let s = `<div class="graph net" id="${id}-wrap" style="height:${height}px"><svg id="${id}" viewBox="${bx0} ${by0} ${W} ${H}" preserveAspectRatio="xMidYMid meet" style="height:${height}px">
  <defs>${Object.entries(EDGE).map(([k, v]) => `<marker id="${id}-ar-${k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 1.5 10 5 0 8.5z" fill="${v.c}"/></marker>`).join("")}
  <filter id="${id}-sh" x="-20%" y="-30%" width="140%" height="170%"><feDropShadow dx="0" dy="1.5" stdDeviation="2" flood-color="#1E2024" flood-opacity=".10"/></filter></defs><g class="vp">`;
  if (hulls) {
    const byC = {}; ns.forEach(n => { if (n.community >= 0) (byC[n.community] = byC[n.community] || []).push(pos[n.id]); });
    Object.entries(byC).forEach(([c, m]) => {
      if (m.length < 3 || Math.max(...m.map(p => p.n.risk)) < 40 || (hullSet && !hullSet.has(+c))) return;
      const corners = m.flatMap(p => [[p.x - p.w / 2, p.y - p.h / 2], [p.x + p.w / 2, p.y - p.h / 2], [p.x + p.w / 2, p.y + p.h / 2], [p.x - p.w / 2, p.y + p.h / 2]]);
      const pts = hullPts(corners); const minx = Math.min(...pts.map(p => p[0])), top = Math.min(...pts.map(p => p[1]));
      s += `<g class="hull"><polygon points="${pts.map(p => p.join(",")).join(" ")}" fill="#B4423C" fill-opacity=".035" stroke="#B4423C" stroke-opacity=".22" stroke-width="1.2" stroke-dasharray="5 5" stroke-linejoin="round" transform="translate(0,0)"/><text x="${minx}" y="${top - 10}" class="hull-l">COMMUNITY ${+c + 1}</text></g>`;
    });
  }
  const pairN = {};
  g.edges.forEach(e => {
    const A = pos[e.source], B = pos[e.target]; if (!A || !B) return;
    const key = [e.source, e.target].sort().join("|"); const k = pairN[key] = (pairN[key] || 0) + 1;
    const dx = B.x - A.x, dy = B.y - A.y;
    const isArrow = ARROW.has(e.kind);
    const [ax, ay] = clip(A, dx, dy, 3), [bx, by] = clip(B, -dx, -dy, isArrow ? 5 : 3);
    const bend = (isArrow ? .12 : .05) * (k % 2 ? 1 : -1) * Math.ceil(k / 2);
    const mx = (ax + bx) / 2 - (by - ay) * bend, my = (ay + by) / 2 + (bx - ax) * bend;
    const ek = e.kind === "billed" && e.flagged > 0 ? "billed_flag" : e.kind;
    const w = isArrow ? 1.3 + Math.min(4, Math.log10((e.n || e.lines || 1) + 1) * 1.6) : e.kind === "shared_patients" ? 1 + Math.min(3, (e.jaccard || 0) * 8) : e.kind === "billed" ? (e.flagged > 0 ? 1.4 + Math.min(3.5, Math.log10(e.flagged + 1) * 2.2) : 1.1) : e.kind === "admitted" ? 1.8 : 1.5;
    const dash = e.kind === "billed" || e.kind === "admitted" || isArrow ? "" : e.kind === "shared_members" || e.kind === "shared_patients" ? 'stroke-dasharray="1.5 4" stroke-linecap="round"' : e.kind === "primary_care" ? 'stroke-dasharray="2 3"' : e.kind === "practices_at" ? 'stroke-dasharray="8 3 2 3"' : 'stroke-dasharray="6 4"';
    const etip = isArrow ? `${EDGE[ek].l}: ${e.lines || e.n} orders · ${money(e.paid || 0)}${e.flagged ? ` · ${e.flagged} flagged` : ""}` : e.kind === "shared_patients" ? `Share ${e.patients} patients (overlap ${pc(e.jaccard)})` : e.kind === "practices_at" ? `Practises here: ${e.lines} hospital claims, ${e.patients} patients` : e.kind === "primary_care" ? "Primary-care physician of this patient" : e.kind === "billed" ? `${e.lines} claim lines · ${money(e.paid)} · ${e.flagged} flagged${e.rules?.length ? " (" + e.rules.join(", ") + ")" : ""} · ${e.first} → ${e.last}` : e.kind === "admitted" ? `${e.stays} inpatient stay(s)` : e.label || EDGE[ek].l;
    s += `<path class="edge" data-a="${e.source}" data-b="${e.target}" d="M${ax},${ay} Q${mx},${my} ${bx},${by}" fill="none" stroke="${EDGE[ek].c}" stroke-width="${w}" ${dash} ${isArrow ? `marker-end="url(#${id}-ar-referral)"` : ""} opacity="${e.kind === "shared_members" || e.kind === "shared_patients" ? .55 : e.kind === "billed" && !e.flagged ? .45 : .8}"><title>${esc(etip)}</title></path>`;
  });
  const icon = (d, cx, cy, sz, col) => `<path d="${d}" transform="translate(${cx - sz / 2},${cy - sz / 2}) scale(${sz / 24})" fill="none" stroke="${col}" stroke-width="${1.8 * 24 / sz}" stroke-linecap="round" stroke-linejoin="round"/>`;
  P.forEach(p => {
    const n = p.n, { w, h } = p;
    if (ent(n)) {
      const c = EDGE[n.kind].c;
      s += `<g class="node ent" data-id="${n.id}" transform="translate(${p.x},${p.y})"><rect x="${-w / 2}" y="${-h / 2}" width="${w}" height="${h}" rx="5" fill="#F6F7F8" stroke="${c}" stroke-opacity=".55" stroke-dasharray="3 2"/>${icon(EICON[n.kind], -w / 2 + 13, 0, 13, c)}<text x="${-w / 2 + 25}" y="3.8" class="et">${esc(n.label)}</text></g>`;
      return;
    }
    if (pat(n)) {
      const ic = n.risk >= 60 ? "#55595F" : n.risk >= 30 ? "#C28A1B" : "#A0A4AB";
      const PI = "M12 11.5a3.8 3.8 0 1 0 0-7.6 3.8 3.8 0 0 0 0 7.6z M4.5 20.5a7.5 7.5 0 0 1 15 0";
      s += `<g class="node prov patient" data-id="${n.id}" data-act="${onNode}" transform="translate(${p.x},${p.y})"><rect x="${-w / 2}" y="${-h / 2}" width="${w}" height="${h}" rx="${h / 2}" fill="#fff" stroke="${n.primary ? "#1E2024" : "#C8CBD0"}" stroke-width="${n.primary ? 1.4 : 1}" filter="url(#${id}-sh)"/>${icon(PI, -w / 2 + h / 2, 0, h * .5, "#3E4566")}<text x="${-w / 2 + h - 2}" y="${n.primary ? -2 : 4}" class="${n.primary ? "cn" : "pt"}">${esc(n.label.replace("Patient ", ""))}</text>${n.primary ? `<text x="${-w / 2 + h - 2}" y="12" class="cs">Patient</text>` : ""}<rect x="${w / 2 - (n.primary ? 36 : 30)}" y="${n.primary ? -10 : -8}" width="${n.primary ? 28 : 22}" height="${n.primary ? 20 : 16}" rx="${n.primary ? 5 : 8}" fill="${ic}"/><text x="${w / 2 - (n.primary ? 22 : 19)}" y="${n.primary ? 4 : 3.5}" text-anchor="middle" class="rk" style="font-size:${n.primary ? 11 : 9.5}px">${Math.round(n.risk)}</text></g>`;
      return;
    }
    const col = riskColor(n.risk), tint = n.risk >= 60 ? "#FCE6E6" : n.risk >= 40 ? "#FCEBD9" : n.risk >= 25 ? "#FBF0CF" : "#EEF0F3";
    const isCase = n.primary || n.case_id;
    if (!isCard(n)) {
      s += `<g class="node prov tile" data-id="${n.id}" data-act="${onNode}" transform="translate(${p.x},${p.y})"><rect x="-17" y="-17" width="34" height="34" rx="8" fill="#fff" stroke="#C8CBD0" filter="url(#${id}-sh)"/>${icon(FICON[n.family] || FICON.PRO, 0, -1.5, 17, "#5A5E66")}<rect x="-10" y="12.5" width="20" height="2.5" rx="1.25" fill="${col}"/></g>`;
      return;
    }
    const name = n.label.length > 17 ? n.label.slice(0, 16).trimEnd() + "…" : n.label;
    const sub = `${FAM[n.family]}${n.case_id ? " · " + n.case_id : ""}`;
    s += `<g class="node prov card" data-id="${n.id}" data-act="${onNode}" transform="translate(${p.x},${p.y})">
      <rect x="${-w / 2}" y="${-h / 2}" width="${w}" height="${h}" rx="8" fill="#fff" stroke="${isCase ? "#1E2024" : "#C8CBD0"}" stroke-width="${isCase ? 1.4 : 1}" filter="url(#${id}-sh)"/>
      <path d="M${-w / 2 + 8},${-h / 2} h32 v${h} h-32 a8 8 0 0 1 -8 -8 v${-(h - 16)} a8 8 0 0 1 8 -8z" fill="${tint}"/>
      <line x1="${-w / 2 + 40}" y1="${-h / 2}" x2="${-w / 2 + 40}" y2="${h / 2}" stroke="#E9EBF3"/>
      ${icon(FICON[n.family] || FICON.PRO, -w / 2 + 20, 0, 19, n.risk >= 25 ? col : "#4A4E55")}
      <text x="${-w / 2 + 49}" y="-3" class="cn"><title>${esc(n.label)}</title>${esc(name)}</text>
      <text x="${-w / 2 + 49}" y="12" class="cs">${esc(sub)}</text>
      <rect x="${w / 2 - 36}" y="-10" width="28" height="20" rx="5" fill="${col}"/>
      <text x="${w / 2 - 22}" y="4" text-anchor="middle" class="rk">${Math.round(n.risk)}</text>
    </g>`;
  });
  s += `</g></svg>
  <div class="gctl"><button data-gz="in" data-g="${id}" title="Zoom in">+</button><button data-gz="out" data-g="${id}" title="Zoom out">−</button><button data-gz="fit" data-g="${id}" title="Fit">⤢</button></div>
  <div class="gtip" id="${id}-tip"></div><div class="gpanel" id="${id}-panel"></div>
  </div>${legend ? graphLegend(present) : ""}`;
  return s;
}

function graphLegend(present) {
  return `<div class="gleg"><div class="row" style="gap:14px;flex-wrap:wrap">${Object.entries(FAM).map(([k, l]) => `<span class="row" style="gap:5px"><svg width="14" height="14" viewBox="0 0 24 24"><path d="${FICON[k]}" fill="none" stroke="#4A4E55" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>${l}</span>`).join("")}</div>
  <div class="row" style="gap:14px;margin-top:6px;flex-wrap:wrap"><span class="row" style="gap:5px">${[["#B4423C", "60+"], ["#D9772B", "40–59"], ["#C28A1B", "25–39"], ["#A0A4AB", "<25"]].map(([c, l]) => `<span class="rkl" style="background:${c}">${l}</span>`).join("")} risk score</span><span class="row" style="gap:5px"><span class="casel"></span>case provider</span><span class="row" style="gap:5px"><span class="tilel"></span>low-risk provider</span>${Object.entries(EDGE).filter(([k]) => present.has(k)).map(([k, v]) => `<span class="row" style="gap:5px"><svg width="22" height="8"><line x1="1" y1="4" x2="21" y2="4" stroke="${v.c}" stroke-width="2" ${k === "shared_members" || k === "shared_patients" ? 'stroke-dasharray="1.5 3.5" stroke-linecap="round"' : ARROW.has(k) || k === "billed" || k === "billed_flag" || k === "admitted" ? "" : k === "primary_care" ? 'stroke-dasharray="2 3"' : k === "practices_at" ? 'stroke-dasharray="8 3 2 3"' : 'stroke-dasharray="5 3"'}/></svg>${v.l}</span>`).join("")}</div></div>`;
}

// card + click behaviour shared by the 2D (SVG) and 3D (three.js) views
function nodeCard(n, G) {
  return n.kind && n.kind !== "provider" && n.kind !== "patient"
    ? `<div class="b">${esc(n.label)}</div><div class="sm mut">${EDGE[n.kind].l} shared by ${(G.adj[n.id] || []).length} providers</div>`
    : `<div class="row" style="gap:10px;align-items:flex-start"><svg width="22" height="22" viewBox="0 0 24 24" style="flex:none;margin-top:2px"><path d="${FICON[n.family] || FICON.PRO}" fill="none" stroke="#1E2024" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg><div><div class="b">${esc(n.label)}</div><div class="sm mut">${FAM[n.family] || (n.kind === "patient" ? "Patient" : "")}${n.city ? " · " + esc(n.city) : ""}</div></div></div>
       <div class="gstats"><div><span>Risk</span><b style="color:${riskColor(n.risk)}">${Math.round(n.risk)}</b><em>${riskBand(n.risk)}</em></div>${n.brain != null ? `<div><span>Brain</span><b>${Math.round(n.brain * 100)}</b></div>` : ""}${n.lines != null ? `<div><span>Lines 180d</span><b>${num(n.lines)}</b></div>` : ""}<div><span>Links</span><b>${(G.adj[n.id] || []).length}</b></div></div>
       ${n.rule != null ? `<div class="sm mut">Rules ${Math.round(n.rule * 100)} · Anomaly ${pc(n.anomaly)}</div>` : ""}${n.case_id ? `<div class="sm" style="margin-top:4px">In case <b>${n.case_id}</b></div>` : ""}`;
}
function nodeClick(G, idn, panel, focus, clear) {
  const n = G.nodes[idn]; if (!n) return;
  if (n.kind && n.kind !== "provider" && n.kind !== "patient" && G.onNode !== "inspect") return;
  if (G.onNode === "inspect") { panel.dataset.open = n.id; focus(n.id); return window.wbInspect && window.wbInspect(n.id); }
  if (G.onNode !== "select") return go("/provider/" + n.id);
  panel.dataset.open = n.id; focus(n.id);
  const nb = (G.adj[n.id] || []).map(k => G.nodes[k]).filter(Boolean).sort((a, b) => (b.risk || 0) - (a.risk || 0));
  panel.innerHTML = `<button class="gx" data-gclose="1">×</button>${nodeCard(n, G)}<div class="sm b" style="margin-top:10px">Connected to</div>${nb.slice(0, 8).map(m => `<div class="sm row" style="gap:6px;padding:3px 0"><i style="width:8px;height:8px;border-radius:50%;background:${m.kind && m.kind !== "provider" && m.kind !== "patient" ? EDGE[m.kind].c : riskColor(m.risk)}"></i>${esc(m.label)}</div>`).join("")}
    <div class="row" style="gap:6px;margin-top:10px"><a class="btn sm" href="#/provider/${n.id}">Open provider</a>${n.case_id ? `<a class="btn sm pri" href="#/case/${n.case_id}">Open ${n.case_id}</a>` : ""}</div>`;
  panel.style.display = "block";
  panel.querySelector("[data-gclose]").addEventListener("click", () => { panel.style.display = "none"; delete panel.dataset.open; clear(); });
}

// 3D view (three.js). Same data, cards, colours and interactions as graphHTML; height = risk.
function graph3dHTML(g, { height = 640, onNode = "openProv", id = "g", labelMin = -1, hullSet = null, communities = null } = {}) {
  if (!g.nodes.length) return `<div class="mut">No relationships.</div>`;
  const adj = {}; const add = (a, b) => ((adj[a] = adj[a] || new Set()).add(b));
  g.edges.forEach(e => { add(e.source, e.target); add(e.target, e.source); });
  GRAPHS[id] = { nodes: Object.fromEntries(g.nodes.map(n => [n.id, { ...n }])), adj: Object.fromEntries(Object.entries(adj).map(([k, v]) => [k, [...v]])), onNode, edges: g.edges, labelMin, three: true, hullSet: hullSet ? [...hullSet] : null, communities };
  const present = new Set(g.edges.map(e => e.kind === "billed" && e.flagged > 0 ? "billed_flag" : e.kind));
  return `<div class="graph net g3d" id="${id}-wrap" data-g3d="${id}" style="height:${height}px"><div class="g3c"></div>
    <div class="gctl"><button data-g3="in" title="Zoom in">+</button><button data-g3="out" title="Zoom out">−</button><button data-g3="fit" title="Reset view">⤢</button><button data-g3="rl" title="Rotate left 45°">⟲</button><button data-g3="rr" title="Rotate right 45°">⟳</button><button data-g3="top" title="Top-down">⊙</button><button data-g3="spin" title="Auto-rotate 360°">↻</button></div>
    <div class="g3hint">Drag to rotate 360° · scroll to zoom · right-drag to pan · height = risk${g.nodes.some(n => n.community != null) ? " · one island per community · dashed arcs = links between communities" : ""}</div>
    <div class="gtip"></div><div class="gpanel"></div></div>${graphLegend(present)}`;
}
function mount3d() {
  const els = document.querySelectorAll("[data-g3d]"); if (!els.length) return;
  import("/static/net3d.js").then(m => els.forEach(el => m.mount(el, GRAPHS[el.dataset.g3d], { riskColor, FICON, EICON, EDGE, FAM, ARROW, card: nodeCard, onNode: nodeClick })))
    .catch(err => els.forEach(el => { el.querySelector(".g3c").innerHTML = `<div class="loading">3D view unavailable in this browser (${esc(err.message)}). Switch to 2D.</div>`; }));
}
// one header + one toolbar for both Link-analysis views: view switch left; search and 2D | 3D right, always in the same place
function netTop(view, extra) {
  const sub = view === "map" ? "Every provider with a notable relationship, grouped into communities — highest risk first. Click a provider to pin its details."
    : "Pick a hospital, doctor, supplier or patient and follow its relationships — claims billed, referrals, hospital stays, shared ownership.";
  return hdr("Link analysis", "How providers, patients and organisations are connected, and where risk concentrates.") +
    `<div class="nettools"><div class="seg"><button data-netview="investigate" class="${view === "investigate" ? "on" : ""}">Investigate an entity</button><button data-netview="map" class="${view === "map" ? "on" : ""}">Portfolio risk map</button></div>
     <span class="sm mut nettools-sub">${sub}</span><span class="sp"></span>${extra}${dimSeg()}</div>`;
}
const dimSeg = () => `<div class="seg" title="View"><button data-netdim="2d" class="${NET.dim !== "3d" ? "on" : ""}">2D</button><button data-netdim="3d" class="${NET.dim === "3d" ? "on" : ""}">3D</button></div>`;

function wireGraph(id) {
  const svg = document.getElementById(id); if (!svg) return;
  const G = GRAPHS[id], wrap = document.getElementById(id + "-wrap"), tip = document.getElementById(id + "-tip"), panel = document.getElementById(id + "-panel");
  const vb = svg.viewBox.baseVal; const o = { x: vb.x, y: vb.y, w: vb.width, h: vb.height }; let drag = null, moved = false;
  // size the frame to the drawing's own proportions (no empty bands)
  const small = id.startsWith("ngc"), fitH = Math.round(Math.max(small ? 240 : 380, Math.min(small ? 480 : 820, wrap.clientWidth * vb.height / vb.width)));
  if (fitH > 0 && wrap.clientWidth > 0) { wrap.style.height = fitH + "px"; svg.style.height = fitH + "px"; }
  const zoomAt = (k, cx, cy) => { vb.x = cx - (cx - vb.x) * k; vb.y = cy - (cy - vb.y) * k; vb.width *= k; vb.height *= k; };
  svg.addEventListener("wheel", e => { e.preventDefault(); const r = svg.getBoundingClientRect(); zoomAt(e.deltaY > 0 ? 1.12 : .89, vb.x + vb.width * (e.clientX - r.left) / r.width, vb.y + vb.height * (e.clientY - r.top) / r.height); }, { passive: false });
  svg.addEventListener("mousedown", e => { drag = { x: e.clientX, y: e.clientY, vx: vb.x, vy: vb.y }; moved = false; });
  window.addEventListener("mouseup", () => { drag = null; svg.style.cursor = ""; });
  svg.addEventListener("mousemove", e => { if (!drag) return; const r = svg.getBoundingClientRect(); if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 4) { moved = true; svg.style.cursor = "grabbing"; } vb.x = drag.vx - (e.clientX - drag.x) * vb.width / r.width; vb.y = drag.vy - (e.clientY - drag.y) * vb.height / r.height; });
  wrap.querySelectorAll("[data-gz]").forEach(b => b.addEventListener("click", ev => { ev.stopPropagation(); const k = b.dataset.gz; if (k === "fit") { vb.x = o.x; vb.y = o.y; vb.width = o.w; vb.height = o.h; } else zoomAt(k === "in" ? .8 : 1.25, vb.x + vb.width / 2, vb.y + vb.height / 2); }));
  const focus = idn => {
    const keep = new Set([idn, ...(G.adj[idn] || [])]);
    svg.querySelectorAll(".node").forEach(el => el.classList.toggle("dim", !keep.has(el.dataset.id)));
    svg.querySelectorAll(".edge").forEach(el => el.classList.toggle("dim", !(el.dataset.a === idn || el.dataset.b === idn)));
    svg.querySelectorAll(".edge").forEach(el => el.classList.toggle("hot", el.dataset.a === idn || el.dataset.b === idn));
  };
  const clear = () => svg.querySelectorAll(".dim,.hot").forEach(el => el.classList.remove("dim", "hot"));
  const card = n => nodeCard(n, G);
  svg.querySelectorAll(".node").forEach(el => {
    const n = G.nodes[el.dataset.id];
    el.addEventListener("mouseenter", () => { focus(n.id); tip.innerHTML = card(n); tip.style.display = "block"; });
    el.addEventListener("mousemove", ev => { const r = wrap.getBoundingClientRect(); tip.style.left = Math.min(r.width - 250, ev.clientX - r.left + 16) + "px"; tip.style.top = Math.max(8, ev.clientY - r.top - 10) + "px"; });
    el.addEventListener("mouseleave", () => { tip.style.display = "none"; if (!panel.dataset.open) clear(); else focus(panel.dataset.open); });
    el.addEventListener("click", ev => { ev.stopPropagation(); if (moved || !n) return; nodeClick(G, n.id, panel, focus, clear); });
  });
  svg.addEventListener("click", () => { if (!moved && panel.dataset.open) { panel.style.display = "none"; delete panel.dataset.open; clear(); } });
  G.highlightPath = ids => {
    const on = new Set(ids), pairs = new Set(ids.slice(1).map((x, i) => [ids[i], x].sort().join("|")));
    svg.querySelectorAll(".node").forEach(el => el.classList.toggle("dim", !on.has(el.dataset.id)));
    svg.querySelectorAll(".edge").forEach(el => { const k = [el.dataset.a, el.dataset.b].sort().join("|"); el.classList.toggle("dim", !pairs.has(k)); el.classList.toggle("hot", pairs.has(k)); });
  };
}

/* ------------------------------------------------------------ shell */
const NAV = [["#Work"], ["my", "My work"], ["queue", "SIU queue"], ["prepay", "Claim check"], ["tips", "Tips"],
  ["#Intelligence"], ["overview", "Overview"], ["brain", "Nexus Brain"], ["network", "Link analysis"], ["explorer", "Providers & claims"], ["knowledge", "Knowledge"],
  ["#Operations"], ["outcomes", "Outcomes & reports"], ["rules", "Rule studio"], ["data", "Data & pipeline"], ["governance", "Governance"]];
const NAVIC = {
  my: '<circle cx="12" cy="8" r="3.6"/><path d="M5 20c.8-3.7 3.6-5.6 7-5.6s6.2 1.9 7 5.6"/>',
  queue: '<path d="M7 3.5h7l4 4V20a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1z"/><path d="M14 3.5V8h4M9.5 13h5M9.5 16.5h5"/>',
  prepay: '<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.3 2.4 2.4 4.6-5"/>',
  tips: '<rect x="3.5" y="5.5" width="17" height="13" rx="3"/><path d="m4.5 7.5 7.5 5.5 7.5-5.5"/>',
  overview: '<rect x="4" y="4" width="6.5" height="6.5" rx="1.8"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.8"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.8"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.8"/>',
  brain: '<path d="M12 3.5v17M12 7.5c-2.5-2-6-1-6 2 0 1 .4 1.7 1 2.2-1 .7-1.5 1.6-1.5 2.6 0 2 2 3.2 3.7 2.7M12 7.5c2.5-2 6-1 6 2 0 1-.4 1.7-1 2.2 1 .7 1.5 1.6 1.5 2.6 0 2-2 3.2-3.7 2.7"/>',
  network: '<circle cx="6" cy="7" r="2.3"/><circle cx="18" cy="6" r="2.3"/><circle cx="12" cy="18" r="2.3"/><path d="m8 8 2.8 7.6M16.2 7.7 13.4 15.7M8.3 6.8l7.4-.6"/>',
  explorer: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  knowledge: '<path d="M4 5.5c2.7-1 5.3-.8 8 1 2.7-1.8 5.3-2 8-1v13c-2.7-1-5.3-.8-8 1-2.7-1.8-5.3-2-8-1z"/><path d="M12 6.5v13"/>',
  outcomes: '<path d="M5 20V10M12 20V4M19 20v-7"/>',
  rules: '<path d="M5 8h9M18 8h1M5 16h1M10 16h9"/><circle cx="16" cy="8" r="2"/><circle cx="8" cy="16" r="2"/>',
  data: '<ellipse cx="12" cy="6" rx="7" ry="2.8"/><path d="M5 6v6c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8V6M5 12v6c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-6"/>',
  governance: '<path d="M12 3.5 5 6v5.5c0 4.2 2.8 7.4 7 9 4.2-1.6 7-4.8 7-9V6z"/><path d="m9 12 2.2 2.2L15.2 10"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M18.4 5.6l-1.8 1.8M7.4 16.6l-1.8 1.8"/>',
  users: '<circle cx="9" cy="8.5" r="3.2"/><path d="M3.5 19.5c.7-3.3 2.9-5 5.5-5s4.8 1.7 5.5 5M16 5.5a3 3 0 0 1 0 6M17.5 14.8c1.7.5 2.8 2 3.2 4.7"/>',
  out: '<path d="M14 4.5h4a1.5 1.5 0 0 1 1.5 1.5v12a1.5 1.5 0 0 1-1.5 1.5h-4M10 8l-4 4 4 4M6 12h9"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  bell: '<path d="M6.5 16.5V11a5.5 5.5 0 0 1 11 0v5.5l1.5 2h-14z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  chevl: '<path d="m14.5 6-6 6 6 6"/>', chevr: '<path d="m9.5 6 6 6-6 6"/>', back: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
  panel: '<rect x="4" y="4.5" width="16" height="15" rx="2.5"/><path d="M14.5 4.5v15M10 10l-2 2 2 2"/>',
  panelr: '<rect x="4" y="4.5" width="16" height="15" rx="2.5"/><path d="M14.5 4.5v15M8 10l2 2-2 2"/>',
  shield: '<path d="M12 3.5 5 6v5.5c0 4.2 2.8 7.4 7 9 4.2-1.6 7-4.8 7-9V6z"/><path d="m9 12 2.2 2.2L15.2 10"/>',
  file: '<path d="M7 3.5h7l4 4V20a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1z"/><path d="M14 3.5V8h4M9.5 13h5M9.5 16.5h5"/>',
  alert: '<path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4M12 17.3v.1"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  checkc: '<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.3 2.4 2.4 4.6-5"/>',
  clip: '<rect x="5.5" y="4.5" width="13" height="16" rx="2"/><path d="M9 4.5h6v2.5H9zM9 13l2 2 4-4"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18"/>',
  trend: '<path d="m3.5 16.5 6-6 4 4 7-7"/><path d="M15 7.5h5.5V13"/>',
  trenddn: '<path d="m3.5 7.5 6 6 4-4 7 7"/><path d="M15 16.5h5.5V11"/>',
  help: '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.5a2.5 2.5 0 0 1 4.8.9c0 1.7-2.4 2.2-2.4 3.6M12 17.2v.1"/>',
  filter: '<path d="M4 5h16l-6 7.5V19l-4-2v-4.5z"/>',
  cal: '<rect x="4" y="5.5" width="16" height="14" rx="2.5"/><path d="M8 3.5v4M16 3.5v4M4 10h16"/>',
  note: '<rect x="4.5" y="4.5" width="15" height="15" rx="2.5"/><path d="M8 9h8M8 12.5h8M8 16h5"/>',
  x: '<path d="m6 6 12 12M18 6 6 18"/>',
  users2: '<circle cx="9" cy="8.5" r="3.2"/><path d="M3.5 19.5c.7-3.3 2.9-5 5.5-5s4.8 1.7 5.5 5M16 5.5a3 3 0 0 1 0 6M17.5 14.8c1.7.5 2.8 2 3.2 4.7"/>'
};
const ico = (k, s = 18) => `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${NAVIC[k] || ""}</svg>`;
const navKey = () => S.view === "case" ? "queue" : S.view === "provider" ? "explorer" : S.view;
function navSection(k) { let sec = "Workspace"; for (const [a] of NAV) { if (a.startsWith("#")) sec = a.slice(1); else if (a === k) return sec; } return "Workspace"; }
function crumbs() {
  const k = navKey(), hit = NAV.find(n => n[0] === k), out = [];
  if (S.view === "settings") out.push("Workspace", "Settings"); else if (S.view === "users") out.push("Workspace", "Users");
  else { out.push(navSection(k)); if (hit) out.push(hit[1]); if ((S.view === "case" || S.view === "provider") && S.arg) out.push(decodeURIComponent(S.arg)); }
  return out;
}
const initials = n => (n || "?").split(/\s+/).filter(Boolean).slice(0, 2).map(x => x[0].toUpperCase()).join("");
const UI = { sb: localStorage.getItem("spotzi.sb") === "1", ctx: JSON.parse(localStorage.getItem("spotzi.ctx") || "{}"), sel: null, qf: { lane: "", sev: "", asg: "", q: "" } };
const CTX_DEFAULT = ["overview", "queue", "my"];
const ctxOpen = () => UI.ctx[S.view] ?? CTX_DEFAULT.includes(S.view);
const riskLvl = r => r >= 60 ? ["high", "t-crit"] : r >= 40 ? ["elevated", "t-high"] : r >= 25 ? ["medium", "t-med"] : ["low", "t-ok"];
const riskPill = r => { const [l, c] = riskLvl(r); return `<span class="tag ${c}">${Math.round(r)} · ${l}</span>`; };
const riskNum = r => `<span class="rnum ${riskLvl(r)[1]}">${Math.round(r)}</span>`;
const kpiI = (l, v, s2, ic) => `<div class="card kpi"><div class="kh"><div class="l">${l}</div>${ic ? `<span class="ki">${ico(ic, 17)}</span>` : ""}</div><div class="v">${v}</div><div class="s">${s2 || ""}</div></div>`;
const STATUS_IC = { New: "file", "In investigation": "clock", "Awaiting information": "file", Monitoring: "clock", "Pending supervisor approval": "clip", Closed: "checkc", "Referral approved": "checkc" };
const STATUS_C = { New: "t-gray", "In investigation": "t-blue", "Awaiting information": "t-med", Monitoring: "t-blue", "Pending supervisor approval": "t-vio", Closed: "t-ok", "Referral approved": "t-ok" };
const statusTag = st => `<span class="tag ${STATUS_C[st] || "t-blue"}">${ico(STATUS_IC[st] || "clock", 13)}${esc(st)}</span>`;
function shell(inner) {
  const st = S.status, run = st?.run, k = navKey(), cr = crumbs(), busy = st?.state === "running", co = ctxOpen();
  const navBtn = (key, label, extra = "") => `<button class="nav ${S.view === key || k === key ? "on" : ""}" data-nav="${key}" title="${label}"><span class="ic">${ico(key)}</span><span>${label}</span>${extra}</button>`;
  document.getElementById("app")?.classList.toggle("sb-min", UI.sb);
  document.getElementById("app")?.classList.toggle("ctx-on", co);
  return `<aside class="side"><div class="logo"><div class="mk"><img class="brandlogo" src="/static/logo-192.png" alt="SpotZⁱ logo"></div><div><b>SpotZ<sup>i</sup></b><small>ClaimShield Nexus</small></div><button class="sbtog" id="sbtog" title="${UI.sb ? "Expand" : "Collapse"} sidebar" aria-label="Toggle sidebar">${ico(UI.sb ? "chevr" : "chevl", 15)}</button></div>
  ${NAV.map(([key, l]) => key.startsWith("#") ? `<div class="navsec">${key.slice(1)}</div>` : navBtn(key, l, `${key === "queue" && S.queue ? `<span class="n">${S.queue.queue.filter(r => r.status !== "Closed").length}</span>` : ""}${key === "my" && S.unread ? `<span class="n" style="color:var(--accent-ink);font-weight:600">${S.unread}</span>` : ""}`)).join("")}
  <div class="side-foot"><div class="side-stat"><div><span class="dot ${busy ? "run" : ""}"></span><b>${busy ? "Analysing…" : "Analysis current"}</b></div>${run ? `<span class="mono" title="${esc(run.ruleset)} · ${esc(run.model)}">${run.run_id} · as of ${run.as_of}</span>` : ""}<span class="mono" style="margin-top:3px;letter-spacing:.08em">SYNTHETIC DATA ONLY</span></div>
  ${S.user ? `<div class="side-links">${navBtn("settings", "Settings")}${S.user.role === "admin" ? navBtn("users", "Users") : ""}</div>
  <div class="usercard"><div class="av">${esc(initials(S.user.name))}</div><div><b>${esc(S.user.name)}</b><span>${esc(ROLE_L[S.user.role] || S.user.role)}</span></div><button class="out" id="logout" title="Sign out" aria-label="Sign out">${ico("out")}</button></div>` : ""}</div></aside>
  <section class="stage"><header class="topbar"><nav class="crumbs"><span>SpotZ<sup style="color:var(--accent)">i</sup></span>${cr.slice(-2).map((c, i, a) => `<i>›</i>${i === a.length - 1 ? `<b>${esc(c)}</b>` : `<span>${esc(c)}</span>`}`).join("")}</nav>
  <div class="gsearch"><span class="gi">${ico("search", 17)}</span><input type="text" id="gq" placeholder="Search cases, providers, members…" autocomplete="off" value="${esc(UI.gq || "")}"><div id="gres"></div></div>
  <button class="iconbtn" data-nav="my" title="Notifications" aria-label="Notifications">${ico("bell", 18)}${S.unread ? `<i class="bdot"></i>` : ""}</button>
  <button class="btn pri" id="newcase" title="Log a new lead for triage">${ico("plus", 16)}New lead</button></header><main>${inner}</main></section>
  ${co ? `<aside class="ctx" id="ctx"><div class="ctxh"><div><span class="eyebrow">Context</span><div class="ctxt">${S.view === "queue" ? "Case focus" : S.view === "case" ? "Case focus" : "Today’s focus"}</div></div><button class="iconbtn sm" data-ctx="0" title="Hide context panel" aria-label="Hide context panel">${ico("panelr", 17)}</button></div><div id="ctxb"><div class="loading" style="padding:30px"><span class="spin"></span></div></div></aside>`
    : `<button class="iconbtn ctxopen" data-ctx="1" title="Show context panel" aria-label="Show context panel">${ico("panel", 17)}</button>`}`;
}
const ROLE_L = { investigator: "SIU investigator", supervisor: "SIU supervisor", analyst: "Data analyst", admin: "Administrator" };
function hdr(title, sub, extra = "") { const ey = ["settings", "users"].includes(S.view) ? "Workspace" : navSection(navKey()); return `<div class="top"><div><span class="eyebrow">${ey}</span><h1>${title}</h1><p>${sub}</p></div><div class="sp"></div>${extra}</div>`; }
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
    const v = { overview: vOverview, queue: vQueue, case: vCase, network: vNetwork, explorer: vExplorer, prepay: vPrepay, tips: vTips, outcomes: vOutcomes, rules: vRules, settings: vSettings, my: vMy, users: vUsers, brain: vBrain, knowledge: vKnowledge, provider: vProvider, data: vData, governance: vGovernance }[S.view] || vOverview;
    app.innerHTML = shell(loading());
    const html = await v();
    app.innerHTML = shell(html);
    afterRender();
  } catch (e) {
    const m = /merged into (CS-[\w-]+)/.exec(e.message);
    app.innerHTML = shell(m ? `<div class="banner">${esc(e.message)}. <a href="#/case/${m[1]}">Open ${m[1]} →</a></div>` : `<div class="banner red">Something went wrong: ${esc(e.message)}. The previous analysis remains available; no data was changed.</div>`);
  }
}
async function loadQueue() {
  const w = S.weights ? Object.entries(S.weights).map(([k, v]) => `&w_${k}=${v}`).join("") : "";
  S.queue = await api(`queue?horizon=${S.horizon}&capacity=${capacity()}${w}`);
  if (!S.weights) S.weights = { ...S.queue.defaults };
  return S.queue;
}

/* ------------------------------------------------------------ overview */
const greet = () => { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; };
const today = () => new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
const firstName = () => (S.user?.name || "").split(" ")[0];
function trendChart(vals, { w = 420, h = 130 } = {}) {
  if (vals.length < 2) return "";
  const mx = Math.max(...vals) * 1.15, mn = Math.min(...vals) * .85, x = i => 6 + i * (w - 12) / (vals.length - 1), y = v => 8 + (h - 16) * (1 - (v - mn) / (mx - mn || 1));
  const pts = vals.map((v, i) => [x(i), y(v)]);
  const d = pts.map((p, i) => { if (!i) return `M${p[0]},${p[1]}`; const q = pts[i - 1], cx = (q[0] + p[0]) / 2; return `C${cx},${q[1]} ${cx},${p[1]} ${p[0]},${p[1]}`; }).join(" ");
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" class="trend"><defs><linearGradient id="tg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#6E727A" stop-opacity=".32"/><stop offset="1" stop-color="#6E727A" stop-opacity="0"/></linearGradient></defs><path d="${d} L${x(vals.length - 1)},${h} L${x(0)},${h}Z" fill="url(#tg)"/><path d="${d}" fill="none" stroke="#6E727A" stroke-width="2.4" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>`;
}
const LANE_IC = { Investigate: "file", "Validate context first": "clock", "Explained by context": "checkc", "Needs more data": "note", "Brain lead": "spark" };
function focusList(rows) {
  return `<div class="flist">${rows.map(r => `<button class="frow" data-go="case/${r.case_id}"><span class="fav">${esc(initials(r.title.replace(/\+.*$/, "")))}</span><span class="ft"><b>${esc(r.title)}</b><span>${r.case_id} · ${esc(r.type)}</span></span><span class="fx"><span>Exposure</span><b>${money(r.exposure)}</b></span>${riskPill(r.risk)}<span class="fch">${ico("chevr", 16)}</span></button>`).join("")}</div>`;
}
function portfolio(q) {
  const rows = q.queue, n = rows.length || 1, by = {};
  rows.forEach(r => { by[r.lane] = (by[r.lane] || 0) + 1; });
  const mx = Math.max(...Object.values(by), 1);
  return `<div class="pbal">${Object.entries(by).sort((a, b) => b[1] - a[1]).map(([l, c]) => `<div class="pb"><div class="row"><span class="pic">${ico(LANE_IC[l] || "file", 15)}</span><span>${esc(l)}</span><span class="sp"></span><b>${c}</b></div><div class="bar"><i style="width:${c / mx * 100}%"></i></div></div>`).join("")}</div>
  <div class="insight">${ico("trend", 17)}<div><b>${rows.filter(r => r.capacity === "within").length} of ${n} cases fit this cycle</b><span>${q.used_hours}h scheduled of a ${q.capacity_hours}h review budget · ${rows.filter(r => r.network).length} network cases span several providers.</span></div></div>`;
}
async function vOverview() {
  const [o, q] = await Promise.all([api(`overview?horizon=${S.horizon}&capacity=${capacity()}`), loadQueue()]);
  const k = o.kpis, ev = o.run.evaluation;
  const share = o.monthly.slice(-8).map(m => m.paid ? m.flagged / m.paid : 0);
  const delta = share.length > 1 ? (share[share.length - 1] - share[0]) / (share[0] || 1) : 0;
  const crit = q.queue.filter(r => r.severity_label === "Critical" && r.lane === "Investigate");
  const mon = m => new Date(m + "-01T00:00").toLocaleDateString("en-US", { month: "short", year: "2-digit" });
  return `<div class="top"><div><span class="eyebrow">${today()}</span><h1>${greet()}, ${esc(firstName())}</h1><p>A calm, current view of the cases that need your attention · analysis as of ${o.run.as_of}.</p></div></div>
    <div class="card hero"><div class="hl"><span class="pill">${ico("spark", 14)}Investigation pulse</span><h2>${crit.length} critical case${crit.length === 1 ? "" : "s"} need${crit.length === 1 ? "s" : ""} a decision this cycle</h2><p>${num(k.flagged_lines)} flagged claim lines were condensed into ${k.cases} evidence-backed cases. ${k.within} fit the current review capacity${k.escalating ? `, and ${k.escalating} are escalating` : ""}.</p><a class="btn pri" href="#/queue">Open SIU queue ${ico("chevr", 15)}</a></div>
    <div class="hc"><div class="row"><span class="mut">Flagged-dollar share trend</span><span class="sp"></span><span class="tdelta ${delta <= 0 ? "dn" : "up"}">${ico(delta <= 0 ? "trenddn" : "trend", 26)}${Math.abs(delta * 100).toFixed(0)}%</span></div>${trendChart(share)}<div class="row mono mut"><span>${mon(o.monthly.slice(-8)[0].m)}</span><span class="sp"></span><span>${mon(o.monthly[o.monthly.length - 1].m)}</span></div></div></div>
    <div class="grid g4" style="margin-top:16px">${kpiI("Active exposure", money(k.exposure), `${k.cases} ranked cases · not recovery`, "file")}${kpiI("Critical cases", k.critical, `${k.escalating} escalating`, "alert")}${kpiI("Alerts raised", num(k.flagged_lines), `${pc(k.flagged_lines / k.lines, 1)} of ${num(k.lines)} lines`, "note")}${kpiI("Inside capacity", `${k.within}<span class="mut" style="font-size:15px"> / ${k.cases}</span>`, `${k.hours}h of ${capacity()}h budget`, "clip")}</div>
    <div class="card flush" style="margin-top:16px"><div class="ch"><div><h3>Investigator focus<small>Priority cases · ${S.horizon}-day horizon</small></h3></div><a class="btn" href="#/queue">View full queue</a></div>${focusList(q.queue.slice(0, 5))}</div>
    <div class="card" style="margin-top:16px"><h3>Honest evaluation<small>Where it works and where it weakens · hidden synthetic labels, 3 test worlds</small></h3><div class="grid g4">
      <div><span class="eyebrow2">Beyond the rules</span><b style="display:block;margin:6px 0 4px">Juniper Clinical Lab: rule score 0</b><span class="sm mut">No rule was written for the recruitment mill. The Brain still ranks the lab #11 of 132 and it reaches an investigator in <a href="#/case/CS-0009">CS-0009</a>.</span></div>
      <div><span class="eyebrow2">Look-alikes</span><b style="display:block;margin:6px 0 4px">0 legitimate providers escalated</b><span class="sm mut">0 of 109 legitimate, 0 of 3 decoys, 0 of 4 legitimate anomalies with real business events.</span></div>
      <div><span class="eyebrow2">Where it weakens</span><b style="display:block;margin:6px 0 4px">14 → 11 → 10 of 16 caught</b><span class="sm mut">As a scheme is cut to 50% / 25% / 10% intensity. At 10% a scheme is only a handful of claims.</span></div>
      <div><span class="eyebrow2">No label leakage</span><b style="display:block;margin:6px 0 4px">Same cases without the labels</b><span class="sm mut">An automated test reruns detection with the label files removed and gets identical cases; the forecast then shows "unavailable".</span></div>
    </div><div class="sm mut" style="margin-top:14px">Synthetic benchmark: it shows the workflow works on controlled scenarios. It is not proof of real-world accuracy; models would be recalibrated on real investigation outcomes.</div></div>
    <div class="card flush" style="margin-top:16px"><div class="ch"><h3>Current portfolio<small>Workflow balance</small></h3></div><div style="padding:16px 22px 20px">${portfolio(q)}</div></div>
    <div class="sech">Pipeline &amp; analytics</div>
    <div class="journey"><div><b>1 · Load</b><span>9 tables validated</span></div><div><b>2 · Detect</b><span>rules + Isolation Forest</span></div><div><b>3 · Connect</b><span>ownership, referral, member graph</span></div><div><b>4 · Forecast</b><span>30/60/90-day repeat risk</span></div><div><b>5 · Rank</b><span>risk × dollars × capacity</span></div><div><b>6 · Investigate</b><span>brief, challenge, human decision</span></div></div>
    <div class="grid g2"><div class="card"><h3>From alerts to action</h3>${funnel(o.funnel)}</div><div class="card"><h3>Monthly paid vs flagged</h3>${monthChart(o.monthly.map(m => ({ month: m.m, paid: m.paid, flagged: m.flagged })))}</div></div>
    <div class="grid g2" style="margin-top:16px"><div class="card"><h3>Flagged lines by rule</h3>${barsH(o.by_rule.map(r => ({ label: r.name, value: r.lines })))}<div class="sm mut">Rules overlap; one line can trigger several.</div></div>
    <div class="card"><h3>Flagged dollars by family</h3>${barsH(o.by_family.map(r => ({ label: FAM[r.family], value: r.paid })).sort((a, b) => b.value - a.value), { fmt: money, color: "#B4423C" })}</div></div>
    ${ev?.total_lines ? `<div class="banner blue" style="margin-top:16px"><b>Synthetic self-check.</b> Against hidden scenario labels the queue's top 5 cases are ${pc(ev.precision_at_5)} true-pattern, case recall of seeded bad actors is ${pc(ev.provider_recall)}, and line-level precision is ${pc(ev.line_precision)}. Not evidence of real-world performance — see Governance. ${ev.decoys_in_cases?.length ? `Decoys that look suspicious but are benign (e.g. oncology, dialysis) are deliberately included so the system must express uncertainty.` : ""}</div>` : ""}`;
}

/* ------------------------------------------------------------ queue */
function stackBar(r) { return `<div class="stack" title="${Object.entries(r.contributions).map(([k, v]) => COMP_L[k] + " " + v).join(" · ")}">${Object.entries(r.contributions).map(([k, v]) => `<i style="width:${v / 100 * 100 * 1.0}%;background:${COMP[k]}"></i>`).join("")}</div>`; }
function queueTable(rows) {
  const sel = UI.sel || rows[0]?.case_id;
  return `<div class="qwrap"><table class="qt"><thead><tr><th class="stk">Case / provider</th><th>Priority</th><th>Risk</th><th class="num">${S.horizon}d fcst</th><th class="num">Exposure</th><th class="num">Members</th><th class="num">Evidence</th><th class="num">Hours</th><th>Lane</th><th>Status</th><th>Assignee</th></tr></thead><tbody>${rows.map(r => `<tr class="click ${ctxOpen() && r.case_id === sel ? "sel" : ""}" data-sel="${r.case_id}"><td class="stk"><div class="row" style="gap:12px"><span class="rk">${r.rank}</span><div><a class="b qa" href="#/case/${r.case_id}">${esc(r.title)}</a><div class="sm mut">${r.case_id} · ${esc(r.type)}</div><div class="pill-row" style="margin-top:4px">${r.network ? `<span class="tag t-vio">network · ${r.n_providers}</span>` : ""}${r.escalating ? `<span class="tag t-high">escalating</span>` : ""}${r.capacity === "within" ? `<span class="tag t-ok">✓ scheduled</span>` : r.capacity === "closed" ? "" : `<span class="tag t-gray">${r.lane === "Needs more data" ? "not scheduled" : "over capacity"}</span>`}</div></div></div></td>
    <td style="min-width:150px"><div class="row"><b class="mono" style="width:34px">${Math.round(r.priority)}</b>${stackBar(r)}</div></td><td>${riskPill(r.risk)}</td><td class="num">${r.forecast == null ? "–" : r.forecast + "%"}</td><td class="num">${money(r.exposure)}</td><td class="num">${r.members}${r.vulnerable ? `<span class="mut sm"> (${r.vulnerable}↑)</span>` : ""}</td>
    <td class="num">${Math.round(r.evidence)}</td><td class="num">${r.effort_hours}</td><td>${laneTag(r.lane)}</td><td>${statusTag(r.status)}</td><td>${r.assignee ? `<span class="who"><span class="av2">${esc(initials(r.assignee))}</span>${esc(r.assignee)}</span>` : '<span class="mut sm">Unassigned</span>'}</td></tr>`).join("")}</tbody></table></div>`;
}
function qFiltered(q) {
  const f = UI.qf, t = f.q.trim().toLowerCase();
  return q.queue.filter(r => (!f.lane || r.lane === f.lane) && (!f.sev || r.severity_label === f.sev) && (!f.asg || (f.asg === "-" ? !r.assignee : r.assignee === f.asg)) && (!t || `${r.case_id} ${r.title} ${r.type}`.toLowerCase().includes(t)));
}
async function vQueue() {
  const q = await loadQueue();
  const w = S.weights, rows = qFiltered(q), uniq = k => [...new Set(q.queue.map(r => r[k]).filter(Boolean))];
  const open = q.queue.filter(r => r.status !== "Closed");
  const sel = (id, label, opts, v) => `<label class="fsel"><span>${label}</span><select data-qf="${id}"><option value="">All</option>${opts.map(o => `<option value="${esc(o[0])}" ${v === o[0] ? "selected" : ""}>${esc(o[1])}</option>`).join("")}</select></label>`;
  return `<div class="top"><div><span class="eyebrow">Investigations</span><h1>SIU queue</h1><p>Triage, review and advance investigations from one focused queue — ranked by risk, forecast, dollars, member impact, severity and evidence, packed into your review capacity.</p></div><div class="sp"></div>
    <div class="hstat"><div><b>${open.length}</b><span>Active</span></div><div><b>${money(open.reduce((a, r) => a + r.exposure, 0))}</b><span>Exposure</span></div></div></div>
    <div class="grid g2"><div class="card"><h3>Review capacity<small>Budget ${capacity()}h · scheduled ${q.used_hours}h · ${q.queue.filter(r => r.capacity === "within").length} cases fit</small></h3><div class="grid g3"><div><label class="f">Investigators</label><input type="number" min="1" max="40" value="${S.inv}" data-cap="inv"></div><div><label class="f">Hours / week</label><input type="number" min="1" max="60" value="${S.hrs}" data-cap="hrs"></div><div><label class="f">Weeks</label><input type="number" min="1" max="26" value="${S.weeks}" data-cap="weeks"></div></div>
    <div class="row" style="margin-top:14px"><span class="sm mut">Forecast horizon</span><div class="seg" id="hz">${[30, 60, 90].map(h => `<button data-hz="${h}" class="${S.horizon === h ? "on" : ""}">${h}-day</button>`).join("")}</div></div>
    <div class="sm mut" style="margin-top:10px">Effort = 8h + 7h per primary provider + √flagged lines + member-sample time.</div>
    </div><div class="card"><h3>Priority weights <button class="btn sm" id="wreset" style="float:right">Reset</button><small>Transparent weighted sum — drag to re-rank</small></h3>
    ${Object.keys(w).map(k => `<div class="row sm"><span style="width:130px"><i style="display:inline-block;width:9px;height:9px;background:${COMP[k]};border-radius:3px"></i> ${COMP_L[k] === "Dollars" ? "Potential dollars" : COMP_L[k]}</span><input type="range" min="0" max="40" value="${Math.round(w[k] * 100)}" data-w="${k}"><b class="mono" style="width:30px;text-align:right">${Math.round(w[k] * 100)}</b></div>`).join("")}
    <div class="sm mut" style="margin-top:6px">Weak-evidence cases are down-weighted (×0.65) and never scheduled; they surface as “Needs more data”.</div></div></div>
    <div class="card flush qcard" style="margin-top:16px"><div class="fbar"><span class="fi">${ico("filter", 17)}</span>${sel("lane", "Lane", uniq("lane").map(x => [x, x]), UI.qf.lane)}${sel("sev", "Severity", ["Critical", "High", "Medium"].map(x => [x, x]), UI.qf.sev)}${sel("asg", "Assignee", [["-", "Unassigned"], ...uniq("assignee").map(x => [x, x])], UI.qf.asg)}<div class="fsearch">${ico("search", 15)}<input type="text" id="qfq" placeholder="Filter cases…" value="${esc(UI.qf.q)}"></div><span class="sp"></span><a class="btn sm" href="/api/queue.csv?horizon=${S.horizon}&capacity=${capacity()}">Export CSV</a></div>
    ${rows.length ? queueTable(rows) : `<div class="loading" style="padding:40px">No cases match these filters.</div>`}
    <div class="qfoot"><span>Showing <b>${rows.length}</b> of ${q.queue.length} cases</span><span class="sp"></span><span>${ctxOpen() ? "Click a row to focus it · open with the title or the panel" : "Click a row to open the investigation brief"}</span></div></div>`;
}

/* ------------------------------------------------------------ case */
const TABS = [["brief", "Brief"], ["plan", "Action plan"], ["chain", "Decision chain"], ["evidence", "Evidence"], ["charts", "Chart review"], ["network", "Network"], ["timeline", "Timeline"], ["forecast", "Forecast"], ["lab", "Challenge lab"], ["precedents", "Precedents"], ["copilot", "AI copilot"], ["claims", "Claims"], ["activity", "Activity"], ["decision", "Decision"]];
async function vCase() {
  const cid = S.arg, tab = S.tab || "brief";
  const d = await api(`cases/${cid}?horizon=${S.horizon}`);
  S.cd = d; const m = d.metrics;
  const conf = d.confidence;
  let body = "";
  if (tab === "brief") {
    body = `${briefTop(d)}${readinessCard(d)}${contextCard(d)}${d.lane === "Needs more data" ? `<div class="banner">⚠ <b>The system abstains.</b> Evidence strength is ${Math.round(m.evidence)}/100 — below the threshold for opening an investigation. Request more information instead; referral is blocked.</div>` : d.lane === "Validate context first" ? `<div class="banner">⚠ Benign context exists for this provider (${esc(d.providers.find(p => p.context)?.context || "")}). Validate it before investing review time.</div>` : ""}
    ${d.tips?.length ? `<div class="banner" style="border-left:3px solid var(--accent)"><b>${d.tips.length} linked tip(s).</b> ${d.tips.map(t => `#${t.id} ${esc(t.channel)} · ${t.ts.slice(0, 10)}: “${esc(t.allegation.slice(0, 140))}”`).join(" · ")}</div>` : ""}
    <div class="grid g21"><div class="card"><h3>Summary</h3><p style="margin-top:0">${esc(d.summary)}</p><h3>Recommended human-review action</h3><p style="margin-top:0">${esc(d.action)}</p>
    <h3>Why the system believes this <small>confidence: ${conf.label}</small></h3><ul style="margin:0;padding-left:18px">${conf.rationale.map(r => `<li>${esc(r)}</li>`).join("")}</ul>
    <div class="row wrap" style="margin-top:10px">${Object.entries(d.signal_flags).map(([k, v]) => `<span class="tag ${v ? "t-ok" : "t-gray"}">${v ? "✓" : "–"} ${{ rules: "Rules", anomaly: "Anomaly", graph: "Graph", temporal: "Escalation", sentinel: "Learned models" }[k]}</span>`).join("")}</div></div>
    <div class="card"><h3>Competing explanations</h3>${d.hypotheses.map(h => `<div class="hyp"><div><span class="tag ${h.kind === "Suspicious" ? "t-crit" : h.kind === "Legitimate" ? "t-ok" : "t-gray"}">${h.kind}</span> <b>${esc(h.title)}</b><div class="sm mut">${esc(h.summary)}</div></div><div class="b" style="font-size:20px;text-align:right">${h.support}%</div></div>`).join("")}<div class="sm mut">Support scores are not probabilities and need not sum to 100: they show how much evidence leans each way.</div></div></div>
    ${aiCard(d.case_id)}<div class="card" style="margin-top:14px"><h3>Limitations</h3><ul style="margin:0;padding-left:18px">${d.limitations.map(r => `<li>${esc(r)}</li>`).join("")}</ul></div>`;
  } else if (tab === "evidence") {
    body = d.evidence.map(e => `<div class="ev"><h4><span class="mono mut">${e.id}</span> ${esc(e.label)} <span class="tag ${e.strength === "Strong" ? "t-crit" : e.strength === "Moderate" ? "t-high" : "t-gray"}">${e.strength}</span>${e.kind === "rule" ? `<span class="sp"></span><span class="sm mut">${num(e.n_lines)} lines · ${money(e.paid)} · ${e.members} members</span>` : ""}</h4>
      ${e.kind === "rule" ? `<div class="sm">${esc(e.rule_desc)}</div>${e.examples.map(x => `<div class="ex"><span class="mono">${x.line_id}</span> ${x.date} · ${x.code} · ${money(x.paid)} · member ${x.member_id}<br>${esc(x.reason)}</div>`).join("")}<a class="sm" href="#/explorer/claims?rule=${e.rule}&provider=${e.providers[0]}">Open all ${e.n_lines} lines →</a>`
        : e.kind === "brain" ? `<div class="sm">${esc(e.detail)}</div><div style="margin-top:8px">${barsH(e.parts.map(([l, v]) => ({ label: l, value: v, color: l.startsWith("Rules") ? "#6E727A" : "#55595F" })), { fmt: v => v.toFixed(2) })}</div><div class="sm mut">Contribution = learned weight × how far the detector sits above its normal range. Quiet detectors add nothing; silence is not exoneration.</div>`
        : e.kind === "drift" ? `<div class="sm">${esc(e.detail)}</div><table style="margin-top:6px"><tr><th>Measure</th><th class="num">Before</th><th class="num">After</th><th class="num">Shift (σ)</th></tr>${e.changes.map(c => `<tr><td class="sm">${esc(c.metric)}</td><td class="num">${esc(c.before)}</td><td class="num"><b>${esc(c.after)}</b></td><td class="num">${c.z.toFixed(1)}</td></tr>`).join("")}</table>`
        : e.kind === "sentinel" ? `<div class="sm">${esc(e.detail)}</div>${(e.transitions || []).map(t => `<div class="ex"><span class="mono">${esc(t.example)}</span> · ${esc(t.text)} <span class="mut">· backed by ${num(t.support)} comparable transitions</span></div>`).join("")}`
        : e.kind === "anomaly" ? `<div class="sm">Provider ${e.provider} sits at the <b>${pc(e.pct)}</b> percentile of an Isolation Forest within its peer family. Main peer-relative drivers: ${e.drivers.map(x => `${esc(x.feature)} (${x.peer_z > 0 ? "+" : ""}${x.peer_z.toFixed(1)}σ)`).join(", ") || "n/a"}.</div>` : `<div class="sm">${esc(e.detail)}</div>`}
      <div class="sm mut" style="margin-top:6px">Source: ${esc(e.source)}</div></div>`).join("");
  } else if (tab === "network") {
    body = `<div class="row" style="margin-bottom:8px"><span class="sm mut">Case providers and every provider directly linked to them — referrals, shared ownership, address, bank account, shared patients.</span><span class="sp"></span>${dimSeg()}</div>
    <div class="card" style="padding:0;overflow:hidden">${NET.dim === "3d" ? graph3dHTML(d.network, { id: "cg", height: 560 }) : graphHTML(d.network, { id: "cg", height: 520 })}</div><div class="card" style="margin-top:12px"><h3>Providers in this case</h3><div class="grid g3">${d.providers.map(p => `<div style="margin-bottom:10px"><a href="#/provider/${p.provider_id}" class="b">${esc(p.name)}</a> <span class="tag ${p.role === "primary" ? "t-crit" : "t-gray"}">${p.role}</span><div class="sm mut">${FAM[p.family]} · ${esc(p.specialty)} · ${p.city}<br>risk ${Math.round(p.risk)} · ${num(p.lines)} lines (180d) · flagged ${money(p.flagged_paid)}${p.context ? `<br><i>${esc(p.context)}</i>` : ""}</div></div>`).join("")}</div><div class="sm mut">Linked providers can be innocent bystanders (e.g. a referral source). Links show where to look, not who is culpable.</div></div>`;
  } else if (tab === "timeline") {
    body = `<div class="grid g21"><div class="card"><h3>Paid vs flagged by month <small>case providers, all history</small></h3>${monthChart(d.timeline.monthly, { h: 230 })}</div><div class="card"><h3>Key events</h3><div class="tl">${d.timeline.events.map(e => `<div class="${e.kind === "history" ? "h" : ""}"><b>${e.date}</b><br><span class="sm">${esc(e.label)}</span></div>`).join("") || "<span class='mut'>No events.</span>"}</div></div></div>`;
  } else if (tab === "forecast") {
    if (d.forecast[30].p == null) body = `<div class="banner">Forecasts are unavailable for this dataset: there are no confirmed-outcome labels to learn from yet. SpotZⁱ never fills a probability field with a guess. Forecasts switch on once investigator outcomes accumulate.</div>`; else
    body = `<div class="banner blue">Forecast = chance the case providers bill ≥3 further simulated-confirmed FWA lines in the next N days. It is a model estimate on synthetic outcomes, not a prediction about any person.</div><div class="grid g3">${[30, 60, 90].map(h => { const f = d.forecast[h], me = f.metrics; return `<div class="card"><h3>${h}-day horizon</h3><div style="font-size:34px;font-weight:700;color:${f.p > .7 ? "#B4423C" : f.p > .4 ? "#C28A1B" : "#15803D"}">${pc(f.p)}</div><div class="bar"><i style="width:${f.p * 100}%;background:#55595F"></i></div>
      <div class="sm" style="margin-top:8px"><b>Why (logistic baseline contributions)</b></div>${f.why.length ? f.why.map(w => `<div class="sm">▲ ${esc(w.feature)} <span class="mut">(value ${w.value.toFixed(2)})</span></div>`).join("") : '<div class="sm mut">No dominant driver.</div>'}
      <div class="sm mut" style="margin-top:8px">Held-out test (later snapshots): AUC ${me.auc.toFixed(2)} · AP ${me.ap.toFixed(2)} · Brier ${me.brier.toFixed(3)} · base rate ${pc(me.base_rate)}. Probabilities are capped at 97% to avoid false certainty.</div></div>`; }).join("")}</div>`;
  } else if (tab === "plan") {
    body = planPanel(d);
  } else if (tab === "charts") {
    body = chartPanel(d);
  } else if (tab === "copilot") {
    body = copilotPanel(d);
  } else if (tab === "chain") {
    body = await chainPanel(d);
  } else if (tab === "lab") {
    body = await labPanel(d);
  } else if (tab === "precedents") {
    body = await precedentsPanel(d);
  } else if (tab === "claims") {
    const c = await api(`claims?provider_id=${d.providers.find(p => p.role === "primary").provider_id}&limit=60`);
    body = `<div class="card"><h3>Highest-anomaly flagged lines <small>${d.sample_lines.length} sample across case providers; full list in Providers &amp; claims</small></h3>${linesTable(d.sample_lines.map(l => ({ ...l, date: l.date, provider_id: l.provider, member_id: l.member, reasons: [l.reason] })))}</div>`;
  } else if (tab === "decision") {
    body = decisionPanel(d);
  } else if (tab === "activity") {
    body = await activityPanel(d);
  }
  const rd = d.readiness, fc = d.forecast[S.horizon].p, prim = d.providers.filter(p => p.role === "primary");
  const canAsg = ["supervisor", "admin"].includes(S.user.role);
  return `<div class="chead"><button class="iconbtn noprint" data-go="queue" title="Back to SIU queue" aria-label="Back to SIU queue">${ico("back", 18)}</button><div class="cht"><span class="eyebrow">${d.case_id}</span><h1>${esc(d.title)}</h1><p>${esc(d.type)} · ${prim.length} primary provider${prim.length === 1 ? "" : "s"}${d.providers.length > prim.length ? ` + ${d.providers.length - prim.length} linked` : ""}</p></div></div>
    <div class="cbar"><div class="cmeta"><div class="cexp"><span>Exposure</span><b>${money(m.exposure)}</b></div><div class="cdiv"></div>${riskPill(m.risk)}${laneTag(d.lane)}${statusTag(d.status)}</div><span class="sp"></span><div class="cact noprint">${canAsg ? `<select id="asgsel"><option value="">Assign to…</option>${(S.users || []).filter(u => ["investigator", "supervisor"].includes(u.role)).map(u => `<option value="${u.username}">${esc(u.name)}</option>`).join("")}</select>` : ""}<a class="btn sm" href="/api/cases/${cid}/brief.md">Export brief (.md)</a><button class="btn sm" id="printbtn">Print</button></div></div>
    <div class="tabs">${TABS.map(([k, l]) => `<button class="${tab === k ? "on" : ""}" data-go="case/${cid}/${k}">${l}${k === "evidence" ? ` <span class="tcount">${d.evidence.length}</span>` : ""}</button>`).join("")}</div>
    <div class="grid g4" style="margin-bottom:16px"><div class="card kpi"><div class="l">Fraud risk</div><div class="v">${Math.round(m.risk)}</div><div class="s">${riskPill(m.risk)}</div></div>
    <div class="card kpi"><div class="l">Evidence strength</div><div class="v">${Math.round(m.evidence)}%</div><div class="bar" style="margin-top:10px"><i style="width:${m.evidence}%"></i></div><div class="s">confidence <b>${conf.label}</b></div></div>
    <div class="card kpi"><div class="l">Investigation readiness</div><div class="v">${rd ? rd.score + "%" : "–"}</div><div class="bar" style="margin-top:10px"><i class="blue" style="width:${rd ? rd.score : 0}%"></i></div><div class="s">${rd ? esc(RLV[rd.level]?.[1] || "") : ""}</div></div>
    <div class="card kpi"><div class="l">${S.horizon}-day repeat risk</div><div class="v">${fc == null ? "n/a" : pc(fc)}</div><div class="s">${num(m.flagged_lines)} lines · ${m.members} members · est. ${m.effort_hours}h</div></div></div>` + body;
}
function briefTop(d) {
  const m = d.metrics, prim = d.providers.find(p => p.role === "primary") || d.providers[0];
  const strong = d.evidence.find(e => e.strength === "Strong" && e.kind === "rule") || d.evidence.find(e => e.strength === "Strong") || d.evidence[0];
  const unc = [...d.hypotheses].filter(h => h.kind !== "Suspicious").sort((a, b) => b.support - a.support)[0];
  const nx = d.readiness?.plan?.next;
  return `<div class="grid bgrid"><div class="card"><h3>Case brief<small>Why this case was flagged</small></h3><p class="lead">${esc(d.summary)}</p>
    <div class="grid g2">${strong ? `<button class="etile" data-go="case/${d.case_id}/evidence"><span class="eic ok">${ico("checkc", 18)}</span><span><span class="eyebrow2">Strongest evidence</span><b>${esc(strong.label)}</b><span>${strong.kind === "rule" ? `${num(strong.n_lines)} lines · ${money(strong.paid)} · ${strong.members} members` : esc((strong.detail || strong.source || "").slice(0, 110))}</span></span><span class="ech">${ico("chevr", 16)}</span></button>` : ""}
    ${unc ? `<button class="etile" data-go="case/${d.case_id}/lab"><span class="eic warn">${ico("alert", 18)}</span><span><span class="eyebrow2">Biggest uncertainty</span><b>${esc(unc.title)} · ${unc.support}%</b><span>${esc(unc.summary)}</span></span><span class="ech">${ico("chevr", 16)}</span></button>` : ""}</div>
    ${nx ? `<div class="nextact"><span class="n1">1</span><div><span class="eyebrow2">Recommended next action</span><b>${esc(nx.title)}</b><span>${esc(nx.how)}</span></div><button class="btn pri" data-go="case/${d.case_id}/${nx.action === "chart_review" ? "charts" : "plan"}">${ico("file", 15)}${nx.action === "chart_review" ? "Request records" : "Open action plan"}</button></div>` : ""}</div>
    <div class="card flush snap"><div class="ch"><h3>Primary provider<small>Case snapshot</small></h3></div><dl>
    <div><dt>Case</dt><dd class="mono">${d.case_id}</dd></div><div><dt>Provider</dt><dd>${prim ? `<a href="#/provider/${prim.provider_id}">${esc(prim.name)}</a>` : "–"}</dd></div><div><dt>Family</dt><dd>${prim ? esc(FAM[prim.family] || prim.family) : "–"}</dd></div><div><dt>Specialty</dt><dd>${prim ? esc(prim.specialty) : "–"}</dd></div>
    <div><dt>Flagged lines</dt><dd class="mono">${num(m.flagged_lines)}</dd></div><div><dt>Gross exposure</dt><dd class="mono">${money(m.exposure)}</dd></div><div><dt>Members</dt><dd class="mono">${m.members}${m.vulnerable ? ` <span class="mut">(${m.vulnerable} older/Medicaid)</span>` : ""}</dd></div><div><dt>Providers linked</dt><dd class="mono">${d.providers.length}</dd></div></dl>
    <div style="padding:0 20px 20px"><button class="btn" style="width:100%;justify-content:center" data-go="case/${d.case_id}/network">${ico("network", 16)}View linked providers</button></div></div></div>`;
}
const ACT_L = { case_assigned: "Case assigned", export_brief: "Brief exported", plan_step_done: "Plan step completed", plan_step_skipped: "Plan step marked not applicable", plan_step_todo: "Plan step reopened", chart_review: "Chart review run", document_uploaded: "Document uploaded", document_downloaded: "Document downloaded", recovery_updated: "Recovery updated", case_merged: "Case merged", case_split: "Case split", tip_linked: "Tip linked" };
const fmtTs = t => { const d = new Date(String(t).replace(" ", "T")); return isNaN(d) ? esc(t) : d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) + " · " + d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }); };
async function activityPanel(d) {
  const [a, n] = await Promise.all([api(`audit?target=${encodeURIComponent(d.case_id)}&limit=200`), api(`cases/${d.case_id}/notes`)]);
  const ev = [
    ...d.decisions.map(x => ({ ts: x.ts, kind: "dec", title: `Decision: ${x.outcome}`, text: x.reason, who: `${x.reviewer} · ${x.role}` })),
    ...n.notes.map(x => ({ ts: x.ts, kind: "note", title: "Note added", text: x.text, who: `${x.author} · ${x.role}` })),
    ...a.audit.filter(x => x.action !== "note_added" && !x.action.startsWith("decision:")).map(x => ({ ts: x.ts, kind: "sys", title: ACT_L[x.action] || (x.action.charAt(0).toUpperCase() + x.action.slice(1)).replace(/[_:]/g, " "), text: x.detail && !x.detail.startsWith("{") ? x.detail : "", who: `${x.actor}${x.role ? " · " + x.role : ""}` }))
  ].sort((x, y) => String(y.ts).localeCompare(String(x.ts)));
  return `<div class="grid g21"><div class="card flush"><div class="ch"><h3>Immutable case history<small>Activity log · ${ev.length} entr${ev.length === 1 ? "y" : "ies"}</small></h3></div><div class="alog">${ev.map(x => `<div class="ai ${x.kind}"><span class="adot"></span><div><span class="mono mut">${fmtTs(x.ts)}</span><b>${esc(x.title)}</b>${x.text ? `<p>${esc(x.text)}</p>` : ""}<span class="mut sm">${esc(x.who)}</span></div></div>`).join("") || '<div class="mut sm" style="padding:8px 0">No activity recorded on this case yet.</div>'}</div></div>
    <div><div class="card flush"><div class="ch"><h3>Session note<small>Add an update</small></h3></div><div style="padding:16px 20px 20px">${n.assignment ? `<div class="sm" style="margin-bottom:10px">Assigned to <b>${esc(n.assignment.assignee_name)}</b> · due ${n.assignment.due}</div>` : ""}${S.perms.includes("investigate") ? `<label class="f" style="margin-top:0">Investigation note</label><textarea id="actnote" placeholder="Document a finding, call, or next step…"></textarea><button class="btn pri" id="actadd" style="margin-top:12px">${ico("note", 15)}Add note</button>` : '<div class="sm mut">Your role can read but not add notes.</div>'}<div class="sm mut" style="margin-top:12px">Notes are saved to the case and written to the audit log. Avoid member IDs unless necessary.</div></div></div></div></div>`;
}
const RLV = { ready: ["#15803D", "Ready for a referral decision"], almost: ["#C28A1B", "Nearly ready"], not_ready: ["#B4423C", "Investigation not yet sufficiently supported"], stop: ["#5A5E66", "Documentation supports the billing"] };
function readinessCard(d) {
  const r = d.readiness; if (!r) return "";
  const [col, lbl] = RLV[r.level];
  return `<div class="card" style="margin-bottom:12px;border-left:4px solid ${col}"><div class="grid g21" style="align-items:start"><div>
    <div class="row"><h3 style="margin:0">Investigation readiness</h3><span class="sp"></span><span class="sm mut">referral bar ${r.referral_bar}%</span></div>
    <div class="row" style="margin:6px 0"><span style="font-size:34px;font-weight:700;color:${col}">${r.score}%</span><b style="color:${col}">${lbl}</b></div>
    <div class="bar" style="height:10px"><i style="width:${r.score}%;background:${col}"></i></div>
    <div style="margin-top:10px"><b>Recommendation:</b> ${esc(r.recommendation)}</div>
    ${r.plan.next ? `<div class="sm" style="margin-top:6px">Next step: <b>${esc(r.plan.next.title)}</b> · ${esc(r.plan.next.owner)} · ~${r.plan.next.minutes} min · <a href="#/case/${d.case_id}/plan">open action plan →</a></div>` : ""}</div>
    <div>${r.items.map(i => `<div class="sm" style="display:flex;gap:8px;padding:4px 0;border-bottom:1px solid var(--line2)"><span style="color:${i.done ? "#15803D" : "#B4423C"};font-size:15px;line-height:1">${i.done ? "☑" : "☐"}</span><div><b>${esc(i.label)}</b><div class="mut">${esc(i.detail)}</div></div></div>`).join("")}
    <div class="sm mut" style="margin-top:6px">Readiness is a checklist of the evidence an SIU needs for this type of case, not a probability of fraud.</div></div></div></div>`;
}
function contextCard(d) {
  const cx = d.context || {}; const ps = Object.entries(cx); if (!ps.length) return "";
  return `<div class="card" style="margin-bottom:12px;border-left:4px solid #5A5E66"><h3 style="margin-top:0">Business context on file <small>enrolment, credentialing, contracts, ownership</small></h3>${ps.map(([p, a]) => `<div class="sm" style="margin-bottom:8px"><b>${esc(p)}</b> · ${a.status === "full" ? '<span class="tag t-ok">explains every signal</span>' : a.status === "partial" ? '<span class="tag t-high">explains some signals</span>' : '<span class="tag t-gray">does not explain the signals</span>'}
    ${a.events.map(e => `<div>• ${e.date} — ${esc(e.detail)} <span class="mut">(${esc(e.type.replace("_", " "))}, ${esc(e.source)})</span></div>`).join("")}
    ${(a.why || []).map(w => `<div class="mut">→ ${esc(w.reason)}: explains ${w.explains.join(", ")}</div>`).join("")}${a.unexplained?.length ? `<div style="color:#B4423C">Not explained: ${a.unexplained.join(", ")}${a.blocking?.length ? " — billing-integrity findings are never excused by business context" : ""}</div>` : ""}</div>`).join("")}
    <div class="sm mut">Context can explain growth, panel and mix changes that start after the event. It never explains duplicates, services after death, impossible timing, unbundling or exclusions. SpotZⁱ never closes a case because of context — a human decides.</div></div>`;
}
function planPanel(d) {
  const r = d.readiness; if (!r) return "";
  const can = S.perms.includes("investigate"), p = r.plan;
  const btn = st => st.action === "chart_review" ? `<a class="btn sm pri" href="#/case/${d.case_id}/charts">Request chart sample</a>` : st.action === "link" ? `<a class="btn sm pri" href="#/case/${d.case_id}/decision">Go to decision</a>`
    : can ? `<button class="btn sm pri" data-pstep="${st.key}" data-pst="done">Mark done</button><button class="btn sm" data-pstep="${st.key}" data-pst="skipped">Not applicable</button>` : "";
  return `<div class="banner blue"><b>What should I do next?</b> Steps are ordered so each one either rules the case out early or adds the evidence a referral needs. Total ≈ ${p.total_minutes} minutes. Readiness ${r.score}% → ${esc(r.recommendation)}</div>
   ${p.steps.map((st, i) => `<div class="card" style="margin-top:10px;${i === 0 ? "border-left:4px solid var(--accent)" : ""}"><div class="row"><b>${st.order}. ${esc(st.title)}</b>${i === 0 ? '<span class="tag t-high">next</span>' : ""}<span class="sp"></span><span class="sm mut">${esc(st.owner)} · ~${st.minutes} min${st.weight ? ` · +${st.weight} readiness` : ""}</span></div>
     <div class="sm" style="margin-top:4px">${esc(st.how)}</div>${st.why ? `<div class="sm mut" style="margin-top:4px">Why: ${esc(st.why)}</div>` : ""}${st.benign?.length ? `<div class="sm mut">Benign explanations to test: ${st.benign.map(esc).join("; ")}</div>` : ""}
     <div class="row" style="margin-top:8px">${btn(st)}</div></div>`).join("")}
   ${p.completed.length ? `<div class="card" style="margin-top:12px"><h3>Completed</h3>${p.completed.map(c => `<div class="row sm" style="padding:4px 0;border-bottom:1px solid var(--line2)"><span class="tag ${c.status === "done" ? "t-ok" : "t-gray"}">${c.status}</span><b>${esc(c.title)}</b><span class="mut">${esc(c.note)} — ${esc(c.user)}, ${c.ts}</span><span class="sp"></span>${can ? `<button class="btn sm" data-pstep="${c.key}" data-pst="todo">Undo</button>` : ""}</div>`).join("")}</div>` : ""}`;
}
function aiEngineTag(engine, model) {
  return engine === "llm" ? `<span class="tag t-vio">LLM · ${esc(model || "")}</span>` : `<span class="tag t-gray">${esc(engine || "deterministic")}</span>`;
}
function chartPanel(d) {
  const r = d.chart_review, ai = d.ai || {}, can = S.perms.includes("investigate");
  const intro = `<div class="banner blue">Investigators confirm upcoding, timing and phantom-service patterns by requesting charts for a sample of lines and checking whether the documentation supports what was billed. SpotZⁱ requests a sample from the (synthetic) record system and ${(ai.features || {}).chart_review ? `an LLM (${esc(ai.model || "")}) audits each note, with SpotZⁱ's trained chart-documentation model as a second opinion` : "SpotZⁱ's trained chart-documentation model audits each note (no LLM configured)"}. Every finding quotes the note verbatim; quotes are checked automatically and ungrounded findings are discarded. Findings are for a human reviewer — they never decide the case.</div>`;
  const ctl = can ? `<div class="row" style="margin:10px 0"><span class="sm">Sample size</span><input type="number" id="cr_n" value="8" min="4" max="16" style="width:70px"><button class="btn pri" id="crgo">${r ? "Request a new sample" : "Request &amp; review sample charts"}</button>${(ai.features || {}).chart_review ? '<label class="sm"><input type="checkbox" id="cr_llm" checked> use LLM</label>' : ""}</div>` : '<div class="sm mut">Investigators can request chart reviews.</div>';
  if (!r) return intro + ctl;
  return intro + ctl + `<div class="card"><div class="row"><h3 style="margin:0">${esc(r.summary)}</h3><span class="sp"></span>${aiEngineTag(r.engine, r.model)}<span class="sm mut">${r.ts} · ${esc(r.by)}${r.ungrounded_dropped ? ` · ${r.ungrounded_dropped} ungrounded LLM finding(s) discarded` : ""}</span></div>
    <table style="margin-top:8px"><tr><th>Line</th><th>Date</th><th>Billed</th><th>Documented</th><th>Supports billed?</th><th>Evidence in the note</th><th>Reviewer</th></tr>${r.rows.map(x => `<tr><td class="mono sm">${esc(x.line_id)}</td><td class="sm">${x.date}</td><td class="mono">${esc(x.code)}</td><td class="mono">${esc(x.documented_code || "—")}</td>
      <td>${x.supports_billed ? '<span class="tag t-ok">yes</span>' : '<span class="tag t-crit">no</span>'} <span class="sm mut">${esc(x.basis)}</span></td><td class="sm">“${esc(x.quote)}”<div class="mut">${esc(x.rationale)}</div><details><summary class="sm mut">full note</summary><div class="sm">${esc(x.note)}</div></details></td><td class="sm">${x.engine === "llm" ? "LLM" : esc(x.engine)}${x.engine === "llm" && !x.agree_with_second_opinion ? ` <span class="tag t-high">${esc(r.second_opinion)} disagrees</span>` : ""}</td></tr>`).join("")}</table>
    <div class="sm mut" style="margin-top:8px">A sample, not the population. Extrapolating an overpayment needs a statistically valid sampling plan and a human decision.</div></div>`;
}
const STC = { unsupported: "#B4423C", legitimate: "#15803D", data_gap: "#A0A4AB" };
function stateBars(states, key) {
  return states.map(x => `<div style="margin:8px 0"><div class="row sm"><b>${esc(x.label)}</b><span class="sp"></span><span class="mut">prior ${pc(x.prior)}</span><b style="width:50px;text-align:right">${pc(x[key])}</b></div><div class="bar" style="height:11px"><i style="width:${x[key] * 100}%;background:${STC[x.key]}"></i></div></div>`).join("");
}
async function labPanel(d) {
  const L = await api(`cases/${d.case_id}/lab`), fr = L.fragility;
  const done = L.observed;
  return `<div class="banner blue"><b>Nexus Evidence Challenge Lab.</b> The system ranks which evidence check would most reduce uncertainty per review hour — including checks that could <i>clear</i> the provider. You approve each check; it reveals only a pre-generated synthetic artifact. Nothing is sent to anyone.</div>
  <div class="grid g2"><div class="card"><h3>Competing explanations <small>belief after ${done.length} check(s) · entropy ${L.entropy_bits.toFixed(2)} bits (was ${L.entropy_prior_bits.toFixed(2)})</small></h3>${stateBars(L.states, "posterior")}
  <div class="sm mut">${esc(L.caveat)}</div>
  ${done.length ? `<h3 style="margin-top:12px">Evidence revealed</h3>${done.map(e => `<div class="ex"><b>${esc(e.rule)}</b>: ${esc(e.outcome)}<div class="mut sm">approved by ${esc(e.reviewer)} · ${e.ts}</div></div>`).join("")}` : ""}</div>
  <div class="card"><h3>Next best evidence check <small>expected information gain ÷ review time</small></h3>${L.ranking.length ? L.ranking.map((r, i) => `<div class="chk ${i === 0 ? "on" : ""}" style="cursor:default"><div style="flex:1"><div class="row"><b>${i + 1}. ${esc(r.name)}</b><span class="sp"></span><span class="tag t-gray">~${r.minutes} min</span></div><div class="sm mut">${r.eig_bits.toFixed(2)} bits · ${r.bits_per_hour.toFixed(2)} bits/hour · ${r.can_clear ? '<span class="tag t-ok">can clear</span>' : ""} ${r.can_confirm ? '<span class="tag t-crit">can confirm</span>' : ""}</div></div>${L.vault ? `<button class="btn sm" data-reveal="${r.rule}">Approve &amp; reveal</button>` : ""}</div>`).join("") : '<div class="mut">All available checks performed.</div>'}<div class="sm mut">${esc(L.method)}</div><div class="sm mut">Checks are approved and logged as ${esc(S.user.name)}.</div></div></div>
  <div class="card" style="margin-top:14px"><h3>Scenario branches <small>hypothetical — never overwrites observed evidence</small></h3><div class="grid g3">${L.branches.map(b => `<div style="border:1px solid var(--line);border-radius:10px;padding:10px"><b class="sm">${esc(b.name)}</b>${b.outcomes.map(o => `<div style="margin:8px 0;padding-top:6px;border-top:1px solid #eef1f6"><div class="sm"><b>${esc(o.outcome)}</b> <span class="mut">(${pc(o.probability)} chance)</span></div><div class="sm mut">→ unsupported ${pc(o.posterior.unsupported)} · legitimate ${pc(o.posterior.legitimate)} · gap ${pc(o.posterior.data_gap)}</div><div class="sm">${esc(o.reading)}${o.exposure_if < L.case_exposure ? `; exposure up to ${money(o.exposure_if)}` : ""}</div></div>`).join("")}</div>`).join("") || '<span class="mut">No further checks.</span>'}</div><div class="sm mut">A branch shows model sensitivity, not causation or a guarantee of what the evidence will say.</div></div>
  <div class="card" style="margin-top:14px"><h3>Evidence fragility <small>concern supported under ${fr.supported} of ${fr.total} configured tests</small></h3>${fr.tests.map(t => `<div class="row sm" style="padding:4px 0;border-bottom:1px solid #eef1f6"><span class="tag ${t.supported ? "t-ok" : "t-high"}">${t.supported ? "still supported" : "weakens"}</span><span>${esc(t.test)}</span><span class="sp"></span><span class="mut">${t.signals} signal famil${t.signals === 1 ? "y" : "ies"} · ${t.rules} rule(s)</span></div>`).join("")}<div class="sm mut">${esc(fr.note)}</div></div>`;
}
async function precedentsPanel(d) {
  const P = await api(`cases/${d.case_id}/precedents`), bp = await api(`cases/${d.case_id}/blueprint`);
  const fp = P.fingerprint;
  const cur = `<div class="card"><h3>Current case fingerprint</h3><div class="sm">${FAM_L[fp.family] || fp.family} · ${esc(fp.setting)} · motif ${esc(fp.motif)} · ownership ${esc(fp.ownership)} · coverage ${pc(fp.coverage)} · ${fp.escalating ? "escalating" : "steady"}${fp.exceptions.length ? " · context: " + fp.exceptions.map(x => x.replace(/_/g, " ")).join(", ") : ""}</div><div class="pill-row" style="margin-top:8px">${Object.entries(fp.rules).filter(([, v]) => v > .05).map(([k, v]) => `<span class="tag t-med">${k} ${Math.round(v * 100)}</span>`).join("")}</div><div class="sm mut" style="margin-top:6px">${esc(P.notice)} Library: ${P.library_size} reviewed cases (${P.library_size - P.live_precedents} simulated, ${P.live_precedents} live quality-approved).</div></div>`;
  if (!P.matches.length || !P.safe_precedent) return cur + `<div class="banner" style="margin-top:14px"><b>No safe precedent found.</b> That is a normal result — review this case from its own evidence.</div>`;
  return `<div class="banner blue">Precedents are shown <b>after</b> the current evidence, differences first. A prior outcome is context to reason with — it is never copied into your decision.</div>${cur}
  ${P.matches.map((m, i) => `<div class="card" style="margin-top:14px"><div class="row"><h3 style="margin:0">${i + 1}. ${esc(m.precedent.title)}</h3><span class="tag t-gray mono">${m.precedent.id}</span><span class="sp"></span><span class="tag t-vio">retrieval similarity ${pc(m.similarity)}</span></div>
    ${m.warnings.map(w => `<div class="banner" style="margin:8px 0">⚠ ${esc(w)}</div>`).join("")}
    <div class="grid g2"><div><b class="sm">Material differences first</b>${m.differences.length ? `<table><tr><th>Area</th><th>This case</th><th>Precedent</th></tr>${m.differences.map(x => `<tr><td class="sm"><b>${esc(x.area)}</b><div class="mut">${esc(x.impact)}</div></td><td class="sm">${esc(x.current)}</td><td class="sm">${esc(x.precedent)}</td></tr>`).join("")}</table>` : '<div class="sm mut">None found.</div>'}
    <div class="sm" style="margin-top:6px"><b>Matched:</b> ${m.matches.map(esc).join(", ") || "—"}</div></div>
    <div><b class="sm">What the earlier reviewer did</b>${m.precedent.checks.map(c => `<div class="ex"><b>${esc(c.check)}</b><br>${esc(c.result)}</div>`).join("")}<details><summary>Prior human outcome &amp; reasoning (read after the differences)</summary><div class="sm"><b>${esc(m.precedent.outcome)}</b><br>${esc(m.precedent.rationale)}<div class="mut">${esc(m.precedent.source)} · closed ${m.precedent.closed} · ${esc(m.precedent.reviewer_role)}</div></div></details></div></div>
    <div class="sm mut">Similarity parts: ${Object.entries(m.components).map(([k, v]) => `${k} ${Math.round(v * 100)}`).join(" · ")}</div></div>`).join("")}
  <div class="card" style="margin-top:14px"><h3>Review blueprint <small>editable checklist · every item shows its source</small></h3>${bp.blueprint ? blueprintView(bp, d) : `<label class="sm"><input type="checkbox" id="bpack"> I have read the material differences above and understand the prior outcomes do not apply automatically.</label><div style="margin-top:8px"><button class="btn pri" id="mkbp">Create review blueprint from top 3</button></div>`}</div>`;
}
const FAM_L = { PRO: "Professional", LAB: "Laboratory", FAC: "Facility", PHARM: "Pharmacy", AMB: "Ambulance", BH: "Behavioral health", HH: "Home health", DME: "DME" };
function blueprintView(bp, d) {
  return `${bp.items.map(i => `<div class="row" style="padding:7px 0;border-bottom:1px solid #eef1f6"><input type="checkbox" data-bp="${i.id}" ${i.state === "done" ? "checked" : ""} ${i.state === "skipped" ? "disabled" : ""}><div style="flex:1"><div class="${i.state === "done" ? "mut" : ""}" style="${i.state === "done" ? "text-decoration:line-through" : ""}">${esc(i.text)} ${i.state === "skipped" ? '<span class="tag t-gray">skipped</span>' : ""} ${i.added_by_human ? '<span class="tag t-vio">added by you</span>' : ""}</div><div class="sm mut">${esc(i.why)}${i.sources.length ? " · from " + i.sources.join(", ") : ""}${i.note ? " · note: " + esc(i.note) : ""}</div></div>${i.state === "todo" ? `<button class="btn sm" data-skip="${i.id}">Skip…</button>` : ""}</div>`).join("")}<div class="row" style="margin-top:8px"><input type="text" id="bpnew" placeholder="Add your own item…"><button class="btn sm" data-addbp="${bp.blueprint.id}">Add</button></div><div class="sm mut" style="margin-top:6px">${esc(bp.note)}</div>`;
}


/* ------------------------------------------------------------ PWA: offline read-only + updates */
function offlineBanner() {
  let b = $("#offbar");
  if (navigator.onLine) { b && b.remove(); document.body.classList.remove("offline"); return; }
  document.body.classList.add("offline");
  if (!b) { b = document.createElement("div"); b.id = "offbar"; document.body.prepend(b); }
  const run = S.status?.run;
  b.innerHTML = `<b>Offline — read-only.</b> Showing the last screen you loaded${run ? ` (run ${esc(run.run_id)}, as of ${run.as_of})` : ""}. Values may be out of date; decisions, approvals and evidence checks are disabled and nothing is queued.`;
}
function showUpdate(force) {
  let b = $("#updbar"); if (b) return;
  b = document.createElement("div"); b.id = "updbar";
  b.innerHTML = `${force ? "SpotZⁱ was updated on the server." : "An update to SpotZⁱ is ready."} <button class="btn sm" id="updgo">Refresh when ready</button> <span class="sm">Unsaved text in a rationale box will be kept until you click.</span>`;
  document.body.appendChild(b);
}
window.addEventListener("online", offlineBanner); window.addEventListener("offline", offlineBanner);
// every data table sits in its own scroll box, so wide columns scroll instead of spilling out of the card (covers late async cards too);
// short values (ids, dates, money) stay on one line and only long prose cells wrap
function wrapTables() { $$("#app table:not(.wbfacts)").forEach(t => { const p = t.parentElement; if (p.classList.contains("tw") || p.classList.contains("qwrap")) return; const w = document.createElement("div"); w.className = "tw"; p.insertBefore(w, t); w.appendChild(t); }); $$("#app td:not([data-w])").forEach(td => { td.dataset.w = ""; if (td.textContent.trim().length > 34) td.classList.add("wrap"); }); }
new MutationObserver(wrapTables).observe($("#app"), { childList: true, subtree: true });
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").then(reg => {
    if (reg.waiting) showUpdate();
    reg.addEventListener("updatefound", () => { const w = reg.installing; w && w.addEventListener("statechange", () => { if (w.state === "installed" && navigator.serviceWorker.controller) showUpdate(); }); });
  }).catch(() => {});
  let reloading = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => { if (!reloading) { reloading = true; location.reload(); } });
}
function deliveryCard(c) {
  const st = (on, ok) => on && ok ? '<span class="tag t-ok">on</span>' : on ? '<span class="tag t-high">incomplete</span>' : '<span class="tag t-gray">off</span>';
  return `<div class="card" style="margin-bottom:12px"><div class="row"><h3 style="margin:0">Email &amp; Slack delivery</h3><span class="sp"></span>${c.test_inbox ? '<span class="tag t-vio">local test inbox</span>' : ""}</div>
    <div class="sm mut" style="margin:6px 0 10px">Copies of in-app notifications for users who opt in. Messages carry only case IDs and actions — never provider, patient or outcome details.</div>
    <div class="row"><b class="sm">Email (SMTP)</b>${st(c.email_enabled, c.channels.email)}<span class="sp"></span><label class="sm"><input type="checkbox" id="dl_em" ${c.email_enabled ? "checked" : ""}> send email</label></div>
    <div class="grid g2" style="gap:8px;margin-top:4px"><div><label class="f">SMTP host</label><input type="text" id="dl_host" value="${esc(c.smtp_host)}" placeholder="smtp.yourcompany.com"></div>
      <div><label class="f">Port · security</label><div class="row"><input type="number" id="dl_port" value="${c.smtp_port}" style="width:90px"><select id="dl_sec">${["starttls", "ssl", "none"].map(x => `<option ${c.smtp_security === x ? "selected" : ""}>${x}</option>`).join("")}</select></div></div>
      <div><label class="f">Username</label><input type="text" id="dl_user" value="${esc(c.smtp_user)}" autocomplete="off"></div>
      <div><label class="f">Password</label><input type="password" id="dl_pw" autocomplete="new-password" placeholder="${c.smtp_password_set ? "saved — type to replace" : "SMTP password / app password"}"></div>
      <div><label class="f">From address</label><input type="text" id="dl_from" value="${esc(c.smtp_from)}" placeholder="spotzi@yourcompany.com"></div>
      <div><label class="f">Send test to</label><div class="row"><input type="text" id="dl_to" placeholder="you@yourcompany.com"><button class="btn sm" data-dltest="email">Test</button></div></div></div>
    <div class="row" style="margin-top:12px"><b class="sm">Slack</b>${st(c.slack_enabled, c.channels.slack)}<span class="sp"></span><label class="sm"><input type="checkbox" id="dl_sl" ${c.slack_enabled ? "checked" : ""}> post to Slack</label></div>
    <label class="f">Incoming-webhook URL</label><div class="row"><input type="password" id="dl_hook" autocomplete="off" placeholder="${c.slack_webhook_set ? `saved (${esc(c.slack_webhook_hint)}) — type to replace` : "https://hooks.slack.com/services/…"}"><button class="btn sm" data-dltest="slack">Test</button></div>
    <label class="f">Link prefix in messages</label><input type="text" id="dl_base" value="${esc(c.base_url)}">
    <div class="row" style="margin-top:10px"><button class="btn pri" id="dl_save">Save</button><button class="btn" id="dl_inbox" title="Route both channels to a built-in local inbox (127.0.0.1 only)">Use local test inbox</button><span class="sm mut" id="dl_res"></span></div>
    <div class="sm mut" style="margin-top:8px">${esc(c.note)} For Slack, create an incoming webhook in your workspace (Apps → Incoming Webhooks) and paste its URL.</div>
    ${c.test_inbox ? `<div class="wbh" style="margin-top:12px">Local test inbox <span class="mut" style="font-weight:400">${c.test_inbox_running ? "running on 127.0.0.1:2525 (SMTP) and :2526 (webhook)" : "not running"}</span></div>${c.inbox.length ? c.inbox.map(m => `<div class="sm" style="padding:6px 0;border-bottom:1px solid var(--line2)"><span class="tag ${m.channel === "email" ? "t-med" : "t-vio"}">${m.channel}</span> <span class="mut">${m.ts} · ${esc(m.recipient)}</span>${m.subject ? `<div><b>${esc(m.subject)}</b></div>` : ""}<div style="white-space:pre-wrap">${esc(m.body.slice(0, 300))}</div></div>`).join("") : '<div class="sm mut">Nothing received yet — press Test, or trigger a notification (e.g. assign a case to a user who opted in).</div>'}` : ""}</div>`;
}
function llmCard(c) {
  const pv = c.providers[c.provider] || {};
  const st = c.active ? `<span class="tag t-ok">active · ${esc(c.active)} · ${esc(c.active_model || "")}</span>` : `<span class="tag t-gray">off</span>`;
  return `<div class="card"><div class="row"><h3 style="margin:0">AI &amp; LLM <small>optional</small></h3><span class="sp"></span>${st}</div>
    <div class="sm mut" style="margin:6px 0 8px">SpotZⁱ runs fully without an LLM (trained models and rules). Switch an LLM on to add chart reading, tip structuring, rule drafting and the case copilot.</div>
    <label class="sm" style="display:block"><input type="checkbox" id="ll_on" ${c.enabled ? "checked" : ""}> <b>Use an LLM</b></label>
    <label class="f">Provider</label><select id="ll_pv">${[["none", "None"], ["deepseek", "DeepSeek"], ["zai", "z.ai (GLM)"], ["openai", "OpenAI-compatible"], ["anthropic", "Anthropic"], ["local", "Local server (OpenAI-compatible)"]].map(([k, l]) => `<option value="${k}" ${c.provider === k ? "selected" : ""}>${l}</option>`).join("")}</select>
    <label class="f">Model</label><input type="text" id="ll_md" value="${esc(c.model)}" placeholder="${esc(pv.model || "default")}">
    <label class="f">Base URL <span class="mut">(leave blank for the provider default)</span></label><input type="text" id="ll_url" value="${esc(c.base_url)}" placeholder="${esc(pv.base_url || "")}">
    <label class="f">API key</label><div class="row"><input type="password" id="ll_key" autocomplete="off" placeholder="${c.key_set ? `saved (${esc(c.key_hint)}) — type to replace` : "paste key"}">${c.key_set ? '<button class="btn sm" id="ll_clear">Remove key</button>' : ""}</div>
    <div class="sm b" style="margin-top:10px">Features</div>${Object.entries(c.feature_labels).map(([k, l]) => `<label class="sm" style="display:block"><input type="checkbox" class="ll_f" value="${k}" ${c.features[k] !== false ? "checked" : ""}> ${esc(l)}</label>`).join("")}
    <div class="row" style="margin-top:10px"><button class="btn pri" id="ll_save">Save</button><button class="btn" id="ll_test">Test connection</button><span class="sm mut" id="ll_res"></span></div>
    <div class="sm mut" style="margin-top:8px">${esc(c.note)} Only case evidence needed for the task is sent; data is synthetic.</div></div>`;
}
async function vSettings() {
  const meR = await api("me"), u = meR.user; const admin = S.perms.includes("manage_users");
  const sec = admin ? await api("security") : null, ob = admin ? await api("outbox") : null, lc = admin ? await api("settings/llm") : null, dc = admin ? await api("settings/delivery") : null;
  return hdr("Settings", `${esc(u.name)} · ${esc(u.role)}`) + `<div class="grid g2"><div>
   <div class="card"><h3>Two-factor sign-in</h3><div class="sm">${u.mfa_enabled ? '<span class="tag t-ok">on</span> Codes from your authenticator app are required at sign-in.' : '<span class="tag t-gray">off</span> Protect your account with an authenticator app.'}${u.mfa_required ? ' <span class="tag t-high">required for your role</span>' : ""}</div>${u.mfa_enabled ? "" : '<button class="btn" id="mfaon" style="margin-top:10px">Set up two-factor</button>'}</div>
   <div class="card" style="margin-top:12px"><h3>Change password</h3><label class="f">Current password</label><input type="password" id="pwc" style="width:100%;border:1px solid var(--line);border-radius:6px;padding:7px 10px"><label class="f">New password (10+ characters)</label><input type="password" id="pwn" style="width:100%;border:1px solid var(--line);border-radius:6px;padding:7px 10px"><button class="btn" id="pwgo" style="margin-top:10px">Change password</button></div>
   <div class="card" style="margin-top:12px"><h3>Notifications</h3><div class="sm mut">In-app notifications are always on. External copies contain only case IDs and actions — never provider, member or outcome details.</div><label class="f">Work email</label><input type="text" id="pfem" value="${esc(u.email || "")}"><label class="sm" style="display:block;margin-top:8px"><input type="checkbox" id="pfe" ${u.notify_email ? "checked" : ""}> Email me</label><label class="sm" style="display:block"><input type="checkbox" id="pfs" ${u.notify_slack ? "checked" : ""}> Post to the team Slack channel</label><button class="btn" id="pfgo" style="margin-top:10px">Save</button></div></div>
   ${admin ? `<div>${deliveryCard(dc)}${llmCard(lc)}<div class="card" style="margin-top:12px"><h3>Security policy</h3><div class="sm">Require two-factor for:</div>${["investigator", "supervisor", "analyst", "admin"].map(r => `<label class="sm" style="display:block"><input type="checkbox" class="mfarole" value="${r}" ${sec.mfa_required_roles.includes(r) ? "checked" : ""}> ${r}</label>`).join("")}<button class="btn" id="secgo" style="margin-top:8px">Save policy</button><div class="sm mut" style="margin-top:8px">Users in these roles must enrol before they can use SpotZⁱ. Single sign-on: ${sec.sso ? '<span class="tag t-ok">configured</span>' : '<span class="tag t-gray">not configured</span> (set SPOTZI_OIDC_ISSUER, _CLIENT_ID, _CLIENT_SECRET)'}</div>
     <table style="margin-top:8px"><tr><th>User</th><th>Role</th><th>Two-factor</th></tr>${sec.users.map(x => `<tr><td class="sm">${esc(x.name)}</td><td class="sm">${x.role}</td><td>${x.mfa ? '<span class="tag t-ok">on</span>' : '<span class="tag t-gray">off</span>'}</td></tr>`).join("")}</table></div>
     <div class="card" style="margin-top:12px"><h3>Delivery outbox <small>email ${ob.channels.email ? "configured" : "not configured"} · Slack ${ob.channels.slack ? "configured" : "not configured"}</small></h3><button class="btn sm" id="obtest">Send me a test notification</button><table style="margin-top:8px"><tr><th>Channel</th><th>To</th><th>Status</th><th>Tries</th><th>Error</th></tr>${ob.rows.slice(0, 15).map(o => `<tr><td class="sm">${o.channel}</td><td class="sm">${esc(o.recipient)}</td><td><span class="tag ${o.status === "sent" ? "t-ok" : o.status === "failed" ? "t-crit" : "t-gray"}">${o.status}</span></td><td class="num">${o.attempts}</td><td class="sm mut">${esc(o.last_error || "")}</td></tr>`).join("") || '<tr><td colspan="5" class="mut sm">Nothing sent yet.</td></tr>'}</table></div></div>` : ""}</div>`;
}
async function scopeCard(cid) {
  const el = $("#scopecard"); if (!el) return;
  const sc = await api(`cases/${cid}/scope`); const d = S.cd;
  const prim = d.providers.filter(p => p.role === "primary"); const others = (S.queue?.queue || []).filter(r => r.case_id !== cid);
  el.innerHTML = `<h3>Case scope <small>supervisors can merge or split system-proposed cases</small></h3>
  ${prim.length > 1 ? `<div class="sm"><b>Split</b> — move providers into their own case:</div>${prim.map(p => `<label class="sm" style="display:block"><input type="checkbox" class="splitp" value="${p.provider_id}"> ${esc(p.name)}</label>`).join("")}` : '<div class="sm mut">Only one primary provider; nothing to split.</div>'}
  <div class="sm" style="margin-top:8px"><b>Merge</b> another case into this one:</div><select id="mergeother"><option value="">Choose a case…</option>${others.map(r => `<option value="${r.case_id}">${r.case_id} ${esc(r.title)}</option>`).join("")}</select>
  <label class="f">Reason (required)</label><input type="text" id="scopewhy" placeholder="Why the scope should change"><div class="row" style="margin-top:8px">${prim.length > 1 ? '<button class="btn sm" id="splitgo">Split</button>' : ""}<button class="btn sm" id="mergego">Merge</button></div>
  ${sc.edits.length ? `<div style="margin-top:10px">${sc.edits.map(e => `<div class="ex">${e.kind} ${e.kind === "merge" ? `${e.other} → ${e.target}` : `${JSON.parse(e.providers).join(", ")} → ${e.new_id}`} · ${esc(e.actor)} · ${e.ts}<br><span class="mut">${esc(e.reason)}</span> <button class="btn sm" data-undo="${e.id}">Undo</button></div>`).join("")}</div>` : ""}`;
}
/* ------------------------------------------------------------ auth + my work */
function renderLogin(msg) {
  document.body.classList.add("landing"); $("#app").classList.add("bare"); $("#app").style.display = "block";
  const F = [["spark", "Multi-signal detection", "Combines rules, peer anomaly detection, change-points, learned case-mix models and network analysis to surface patterns that individual rules miss."],
    ["queue", "Risk-aware case prioritization", "Ranks cases by risk, forecast, evidence strength, potential exposure, member impact and the review capacity your team actually has."],
    ["explorer", "Explainable investigations", "Connects every recommendation to claim-level findings, provider relationships, timelines and the reasoning behind suggested actions."],
    ["shield", "Human-controlled outcomes", "Supports investigation and review without declaring fraud or making referral decisions. Referrals need a second person to approve."],
    ["knowledge", "Learning from approved decisions", "Uses governed, human-approved knowledge and recorded outcomes to inform similar future investigations."]];
  $("#app").innerHTML = `<div class="lp"><div class="lpnav"><span class="mk"><img class="brandlogo" src="/static/logo-192.png" alt="SpotZⁱ logo"></span><div><b>SpotZ<sup>i</sup></b><small>ClaimShield Nexus · FWA intelligence</small></div></div>
  <div class="lphero"><div><h1>Fewer alerts. Ranked, explained cases.</h1><p>Evidence-first healthcare claims intelligence for Special Investigations Units. SpotZⁱ turns thousands of claim alerts into a short queue of cases an investigator can defend.</p><div class="lpbtns"><a class="lpb w" href="#signin" id="lpsign">${ico("chevr", 16)}Sign in</a><a class="lpb" href="#lpwork" id="lpwk">${ico("file", 16)}Explore the workflow</a></div></div>
  <div class="lpcard" id="signin"><h2>Sign in</h2><div class="sub">Synthetic environment · access is logged</div>${msg ? `<div class="err">${esc(msg)}</div>` : ""}
  <form id="loginf"><label for="lu">Username</label><input type="text" id="lu" autocomplete="username" autofocus><label for="lp">Password</label><input type="password" id="lp" autocomplete="current-password"><button class="lpb w" type="submit">Sign in</button></form>
  <div id="ssobox"></div><div class="foot">Demo accounts are in <span class="mono">spotzi/data/seed_users.json</span> on the server.</div></div></div>
  <div class="lpsec"><h2>Built to make complex investigations more manageable.</h2><div class="lpstats">
   <div><div class="big">9</div><b>Detection methods</b><p>Rules, peer anomaly detection, change-points, learned case-mix models, network analysis and other complementary signals.</p></div>
   <div><div class="big">Ranked</div><b>Prioritized cases</b><p>Thousands of flagged claim lines condensed into a short queue that fits your team's review capacity.</p></div>
   <div><div class="big">Traceable</div><b>Evidence and reasoning</b><p>Findings link to supporting claims, explanations and decision records.</p></div>
   <div><div class="big">Human-led</div><b>Final decisions</b><p>Investigators review the evidence and retain decision-making authority.</p></div></div>
   <div class="lpdisc">Demonstration figures are based on synthetic data and internal evaluation, not validated real-world healthcare outcomes. <a class="lpchip" href="https://github.com/Ajith-Praveen/spotzi" target="_blank" rel="noopener noreferrer">${ico("network", 13)}GitHub</a></div></div>
  <div class="lpsec lpfeat" id="lpwork">${F.map(([i, t, d]) => `<div>${ico(i, 22)}<div><b>${t}</b><p>${d}</p></div></div>`).join("")}</div>
  <div class="lpcta"><img src="/static/logo-192.png" alt="SpotZⁱ logo" style="width:44px;height:44px;border-radius:11px;display:block;margin:0 auto"><h2>Better investigations start with better evidence.</h2><p>Move beyond isolated claim alerts. Bring patterns, context and evidence together to make healthcare claims investigations more structured, transparent and accountable.</p><div class="lpbtns"><a class="lpb" href="#signin" id="lpsign2">${ico("chevr", 15)}Explore SpotZⁱ</a><a class="lpb" href="#lpwork" id="lpwk2">${ico("file", 15)}Explore the workflow</a></div></div></div>`;
  fetch("/api/sso/config").then(r => r.json()).then(c => { if (c.enabled) $("#ssobox").innerHTML = `<a class="lpb" style="width:100%;justify-content:center;margin-top:10px" href="/api/sso/login">${esc(c.label)}</a>`; });
  const q = new URLSearchParams(location.hash.split("?")[1] || ""); if (q.get("sso_error") && !msg) renderLogin(q.get("sso_error"));
}
function renderMfa(ticket, msg) {
  document.body.classList.remove("landing"); $("#app").style.display = "block"; $("#app").classList.add("bare");
  $("#app").innerHTML = `<div style="min-height:calc(100vh - 30px);display:grid;place-items:center"><div class="card" style="width:360px;padding:28px"><h2 style="margin:0 0 4px;font-size:18px">Two-factor check</h2><div class="sm mut" style="margin-bottom:12px">Enter the 6-digit code from your authenticator app, or a recovery code.</div>${msg ? `<div class="banner red">${esc(msg)}</div>` : ""}<form id="mfaf" data-ticket="${esc(ticket)}"><input type="text" id="mfac" inputmode="numeric" autocomplete="one-time-code" autofocus placeholder="123 456"><button class="btn pri" style="width:100%;justify-content:center;margin-top:12px" type="submit">Verify</button></form></div></div>`;
}
async function renderEnrol(step) {
  document.body.classList.remove("landing"); $("#app").style.display = "block"; $("#app").classList.add("bare");
  if (!step) { const r = await fetch("/api/mfa/begin", { method: "POST", headers: { "X-SpotZi-Contract": CONTRACT } }); step = await r.json(); }
  $("#app").innerHTML = `<div style="min-height:calc(100vh - 30px);display:grid;place-items:center"><div class="card" style="width:460px;padding:28px"><h2 style="margin:0 0 4px;font-size:18px">Set up two-factor sign-in</h2><div class="sm mut" style="margin-bottom:12px">Your organisation requires it for your role. Add this key to any authenticator app (Google Authenticator, Microsoft Authenticator, 1Password…), then enter the current code.</div>
  <label class="f">Setup key</label><div class="mono" style="padding:8px 10px;background:var(--sunk);border:1px solid var(--line);border-radius:6px;word-break:break-all">${esc(step.secret.replace(/(.{4})/g, "$1 ").trim())}</div><details style="margin-top:6px"><summary>Setup link (otpauth)</summary><div class="mono sm" style="word-break:break-all">${esc(step.uri)}</div></details>
  <form id="enrolf"><label class="f">Code from the app</label><input type="text" id="enc" inputmode="numeric" autocomplete="one-time-code"><button class="btn pri" style="width:100%;justify-content:center;margin-top:12px" type="submit">Turn on two-factor</button></form><div id="encodes"></div></div></div>`;
}
async function loadMe() {
  try { const r = await fetch("/api/me"); if (!r.ok) return false; const d = await r.json(); S.user = d.user; S.perms = d.permissions; S.reviewer = d.user.name; S.users = await api("users"); return true; } catch { return false; }
}
async function vMy() {
  const m = await api("my"); S.unread = 0; post("notifications/read", {});
  const row = r => `<tr class="click" data-go="case/${r.case_id}"><td><b>${r.case_id}</b> ${esc(r.title || "")}</td><td class="num">${r.priority ?? "–"}</td><td>${laneTag(r.lane || "")}</td><td><span class="tag t-med">${esc(r.status)}</span></td><td>${r.assignee ? esc(r.assignee) : '<span class="mut">unassigned</span>'}</td><td>${r.due ? (r.overdue ? `<span class="tag t-crit">overdue ${r.due}</span>` : r.due) : "–"}</td></tr>`;
  const tbl = rows => rows.length ? `<table><tr><th>Case</th><th class="num">Priority</th><th>Lane</th><th>Status</th><th>Assignee</th><th>Due</th></tr>${rows.map(row).join("")}</table>` : '<div class="mut sm">Nothing here.</div>';
  return hdr(`Good to see you, ${esc(m.user.name.split(" ")[0])}`, `${esc(m.user.role)} · your cases, approvals and reviews in one place`) +
  `<div class="grid g4"><div class="card kpi"><div class="l">Assigned to me</div><div class="v">${m.mine.filter(r => r.status !== "Closed").length}</div><div class="s">${m.mine.filter(r => r.overdue).length} overdue</div></div>
   <div class="card kpi"><div class="l">Approvals waiting</div><div class="v">${(m.approvals || []).length}</div><div class="s">${m.approvals ? "referrals needing a second person" : "supervisors only"}</div></div>
   <div class="card kpi"><div class="l">Knowledge reviews</div><div class="v">${m.wiki_pending ?? "–"}</div><div class="s">${m.wiki_pending != null ? '<a href="#/knowledge">open queue</a>' : "analysts & supervisors"}</div></div>
   <div class="card kpi"><div class="l">Unassigned cases</div><div class="v">${m.unassigned ? m.unassigned.length : "–"}</div><div class="s">${m.unassigned ? "ready to assign" : "supervisors only"}</div></div></div>
  <div class="grid g21" style="margin-top:12px"><div>
   <div class="card"><h3>My cases</h3>${tbl(m.mine)}</div>
   ${m.approvals ? `<div class="card" style="margin-top:12px"><h3>Referral approvals <small>four-eyes: you cannot approve your own recommendation</small></h3>${m.approvals.map(a => `<div style="padding:8px 0;border-bottom:1px solid var(--line2)"><a href="#/case/${a.case_id}/decision" class="b">${a.case_id}</a> <span class="sm mut">recommended by ${esc(a.recommender)} · ${a.ts}</span><div class="sm">${esc(a.reason)}</div></div>`).join("") || '<div class="mut sm">None.</div>'}</div>` : ""}
   ${m.unassigned ? `<div class="card" style="margin-top:12px"><h3>Unassigned</h3>${tbl(m.unassigned)}</div><div class="card" style="margin-top:12px"><h3>Team workload</h3>${tbl(m.team)}</div>` : ""}
   ${m.precedent_candidates ? `<div class="card" style="margin-top:12px"><h3>Precedent quality review <small>approved cases join the precedent library</small></h3>${m.precedent_candidates.map(p => `<div style="padding:8px 0;border-bottom:1px solid var(--line2)"><div class="row"><a href="#/case/${p.case_id}" class="b">${p.case_id}</a><span class="tag t-med">${esc(p.outcome)}</span><span class="sm mut">by ${esc(p.reviewer)}</span><span class="sp"></span>${p.quality === "pending" ? `<button class="btn sm" data-pq="approve" data-id="${p.case_id}">Approve as precedent</button><button class="btn sm" data-pq="reject" data-id="${p.case_id}">Reject</button>` : `<span class="tag ${p.quality === "approved" ? "t-ok" : "t-gray"}">${p.quality}</span>`}</div><div class="sm mut">${esc(p.reason)}</div></div>`).join("") || '<div class="mut sm">No closed cases yet.</div>'}</div>` : ""}
  </div><div class="card"><h3>Notifications</h3>${m.notifications.map(n => `<div style="padding:7px 0;border-bottom:1px solid var(--line2)" class="${n.read ? "mut" : ""}"><div class="sm">${n.link ? `<a href="#/${n.link}">${esc(n.text)}</a>` : esc(n.text)}</div><div class="sm mut">${n.ts}</div></div>`).join("") || '<div class="mut sm">You are all caught up.</div>'}</div></div>`;
}
async function vUsers() {
  const us = await api("users");
  return hdr("Users & roles", "Admin only. Passwords are hashed (PBKDF2); deactivation ends all sessions.") +
  `<div class="grid g21"><div class="card"><table><tr><th>Name</th><th>Username</th><th>Role</th><th>Status</th><th></th></tr>${us.map(u => `<tr><td><b>${esc(u.name)}</b><div class="sm mut">${esc(u.email || "no email")} · 2FA ${u.mfa ? "on" : "off"}</div></td><td class="mono">${esc(u.username)}</td><td><select data-urole="${u.id}" style="width:140px">${["investigator", "supervisor", "analyst", "admin"].map(r => `<option ${r === u.role ? "selected" : ""}>${r}</option>`).join("")}</select></td><td>${u.active ? '<span class="tag t-ok">active</span>' : '<span class="tag t-gray">inactive</span>'}</td><td><button class="btn sm" data-uact="${u.id}" data-on="${u.active ? 0 : 1}">${u.active ? "Deactivate" : "Activate"}</button> <button class="btn sm" data-upw="${u.id}">Reset password</button>${u.mfa ? ` <button class="btn sm" data-umfa="${u.id}">Reset 2FA</button>` : ""}</td></tr>`).join("")}</table></div>
  <div class="card"><h3>Add user</h3><label class="f">Full name</label><input type="text" id="nu_name"><label class="f">Username</label><input type="text" id="nu_user"><label class="f">Role</label><select id="nu_role"><option>investigator</option><option>supervisor</option><option>analyst</option><option>admin</option></select><label class="f">Work email (for SSO and notifications)</label><input type="text" id="nu_email"><label class="f">Initial password (10+ characters)</label><input type="text" id="nu_pw"><button class="btn pri" id="nu_go" style="margin-top:12px">Create</button></div></div>`;
}
async function loadNotes(cid) {
  const el = $("#notescard"); if (!el) return;
  const n = await api(`cases/${cid}/notes`);
  el.innerHTML = `<h3>Assignment &amp; notes</h3><div class="sm">${n.assignment ? `Assigned to <b>${esc(n.assignment.assignee_name)}</b> by ${esc(n.assignment.assigned_by)} · due ${n.assignment.due}` : '<span class="mut">Not assigned.</span>'}</div>
  <div style="margin-top:8px;max-height:220px;overflow:auto">${n.notes.map(x => `<div class="ex"><b>${esc(x.author)}</b> <span class="mut">${x.ts}</span><br>${esc(x.text)}</div>`).join("") || '<div class="sm mut">No notes yet.</div>'}</div>
  ${S.perms.includes("investigate") ? `<div class="row" style="margin-top:8px"><input type="text" id="notetxt" placeholder="Add a working note…"><button class="btn sm" id="noteadd">Add</button></div>` : ""}`;
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
  <div class="card"><div id="chatlog" style="min-height:120px;max-height:420px;overflow:auto">${h.length ? h.map(m => `<div style="margin:10px 0;${m.role === "user" ? "text-align:right" : ""}"><div style="display:inline-block;max-width:85%;text-align:left;padding:9px 12px;border-radius:12px;background:${m.role === "user" ? "var(--brand)" : "#EEF0F3"};color:${m.role === "user" ? "#fff" : "inherit"}">${m.role === "user" ? esc(m.content) : m.error ? `<span style="color:#7B2323">${esc(m.content)}</span>` : mdLite(m.content)}</div>${m.role === "assistant" && !m.error ? aiBadge(m) : ""}</div>`).join("") : `<div class="mut sm">Try a suggestion:</div><div class="pill-row" style="margin-top:8px">${sugg.map(q => `<button class="btn sm" data-ask="${esc(q)}">${esc(q)}</button>`).join("")}</div>`}${AI.busy ? '<div class="mut sm"><span class="spin"></span>Thinking…</div>' : ""}</div>
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
  <div class="sm">Signed in as <b>${esc(S.user.name)}</b> · ${esc(S.user.role)}</div>
  <label class="f">Outcome</label><select id="outcome">${(pending ? sup : opts).map(o => `<option>${o}</option>`).join("")}</select>
  <label class="f">Rationale (required)</label><textarea id="reason" placeholder="What evidence did you weigh, and what alternative explanations did you consider?"></textarea>
  <div class="sm mut">Checks selected in the Challenge lab: ${(S.checks[d.case_id] || []).join(", ") || "none"}.</div>
  <div style="margin-top:10px"><button class="btn pri" id="submitDec">Record decision</button></div>
  ${pending ? '<div class="sm mut" style="margin-top:8px">A referral is pending: a supervisor other than the recommender must approve or reject it.</div>' : ""}</div>
  <div>${["supervisor", "admin"].includes(S.user.role) ? '<div class="card" id="scopecard" style="margin-bottom:12px"><div class="mut sm">Loading scope…</div></div><div class="card" id="reccard" style="margin-bottom:12px"><div class="mut sm">Loading recovery…</div></div>' : ""}<div class="card" id="doccard" style="margin-bottom:12px"><div class="mut sm">Loading documents…</div></div><div class="card" id="notescard"><h3>Assignment &amp; notes</h3><div class="mut sm">Loading…</div></div><div class="card" style="margin-top:12px"><h3>Decision history <small>status: ${esc(st)}</small></h3>${d.decisions.length ? d.decisions.map(x => `<div style="margin-bottom:10px;border-left:3px solid var(--brand);padding-left:10px"><b>${esc(x.outcome)}</b> <span class="mut sm">${x.ts} · ${esc(x.reviewer)} (${x.role})</span><div class="sm">${esc(x.reason)}</div><div class="sm mut">Run ${x.run_id} · evidence ${Math.round(x.evidence)} · confidence ${x.confidence}</div></div>`).join("") : '<div class="mut">No decisions yet.</div>'}</div></div></div>`;
}

/* ------------------------------------------------------------ network */
const TFAM = { hospital: "FAC", doctor: "PRO", lab: "LAB", pharmacy: "PHARM", ambulance: "AMB", behavioral: "BH", homehealth: "HH", dme: "DME" };
const TLAB = { hospital: "Hospital", doctor: "Doctor / practice", lab: "Laboratory", pharmacy: "Pharmacy", ambulance: "Ambulance", behavioral: "Behavioral health", homehealth: "Home health", dme: "Equipment supplier", patient: "Patient", ownership: "Ownership", address: "Address", bank: "Bank account" };
const TPLU = { hospital: "Hospitals", doctor: "Doctors / practices", lab: "Laboratories", pharmacy: "Pharmacies", ambulance: "Ambulance services", behavioral: "Behavioral health providers", homehealth: "Home health agencies", dme: "Equipment suppliers", patient: "Patients", ownership: "Ownership groups", address: "Addresses", bank: "Bank accounts" };
const PICON = "M12 11.5a3.8 3.8 0 1 0 0-7.6 3.8 3.8 0 0 0 0 7.6z M4.5 20.5a7.5 7.5 0 0 1 15 0";
const typeIcon = (t, sz = 15, col = "#4A4E55") => `<svg width="${sz}" height="${sz}" viewBox="0 0 24 24" style="flex:none"><path d="${t === "patient" ? PICON : FICON[TFAM[t]] || EICON[t] || FICON.PRO}" fill="none" stroke="${col}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const NET = { dim: (() => { try { return localStorage.getItem("spotzi.netdim") || "2d"; } catch (e) { return "2d"; } })(), focus: null, flagged: false, kinds: new Set(["billed", "referred", "admitted", "primary_care", "practices_at", "shared_patients", "ownership", "address", "bank"]), trail: [], pathA: null, view: "investigate", limit: 24 };

function toGraph(d) {   // link-analysis payload -> renderer format
  const nodes = d.nodes.map(n => n.type === "patient" ? { id: n.id, label: n.label, kind: "patient", risk: n.score || 0, primary: n.role === "focus", x: n.x, y: n.y }
    : ["ownership", "address", "bank"].includes(n.type) ? { id: n.id, label: n.label, kind: n.type, x: n.x, y: n.y }
    : { id: n.id, label: n.label, kind: "provider", family: TFAM[n.type], risk: n.score || 0, case_id: n.case_id, primary: n.role === "focus", city: n.city, x: n.x, y: n.y });
  const edges = d.edges.map(e => ({ ...e, kind: e.kind === "referred" ? "referral" : e.kind, n: e.lines }));
  return { nodes, edges };
}
const entRow = (e, extra = "") => `<button class="wbrow" data-focus="${e.id}">${typeIcon(e.type)}<span class="wbl">${esc(e.label)}<em>${TLAB[e.type] || ""}${e.case_id ? " · " + e.case_id : ""}${extra}</em></span>${e.score != null ? `<b class="wbs" style="background:${e.type === "patient" ? (e.score >= 60 ? "#55595F" : e.score >= 30 ? "#C28A1B" : "#A0A4AB") : riskColor(e.score)}">${Math.round(e.score)}</b>` : ""}</button>`;

async function vNetwork() {
  if (NET.view === "map") return vNetworkMap();
  const st = await api("graph/start");
  if (!NET.focus) NET.focus = st.providers[0].id;
  const kinds = [...NET.kinds].join(",");
  const g = await api(`graph/entity?id=${encodeURIComponent(NET.focus)}&flagged_only=${NET.flagged}&kinds=${kinds}&limit=${NET.limit}`);
  const focusNode = g.nodes.find(n => n.id === NET.focus);
  const types = {}; g.nodes.forEach(n => { if (n.id !== NET.focus) types[n.type] = (types[n.type] || 0) + 1; });
  const flaggedEdges = g.edges.filter(e => e.flagged > 0).length;
  setTimeout(() => wbInspect(NET.focus), 0);
  return netTop("investigate", "") + `
  <div class="wb">
    <aside class="wbside">
      <div class="wbsearch"><input type="text" id="wbq" placeholder="Search hospital, doctor, lab, patient ID…" autocomplete="off"><div id="wbres"></div></div>
      <div class="wbsec"><div class="wbh">Show relationships</div>${[["billed", "Claims billed for patients"], ["referred", "Orders & referrals (tests, prescriptions, equipment, home care…)"], ["primary_care", "Primary-care physician"], ["practices_at", "Doctor practises at hospital"], ["admitted", "Hospital admissions"], ["shared_patients", "Providers sharing many patients"], ["ownership", "Shared ownership"], ["address", "Shared address"], ["bank", "Shared bank account"]].map(([k, l]) => `<label class="wbchk"><input type="checkbox" data-kind="${k}" ${NET.kinds.has(k) ? "checked" : ""}> ${l}</label>`).join("")}
        <label class="wbchk" style="margin-top:6px"><input type="checkbox" id="wbflag" ${NET.flagged ? "checked" : ""}> <b>Only links with flagged claims</b></label></div>
      ${NET.trail.length ? `<div class="wbsec"><div class="wbh">Your trail</div>${NET.trail.slice(-6).map(t => `<button class="wbcrumb" data-focus="${t.id}">← ${esc(t.label)}</button>`).join("")}</div>` : ""}
      <div class="wbsec"><div class="wbh">Highest-risk providers</div>${st.providers.slice(0, 7).map(e => entRow(e)).join("")}</div>
      <div class="wbsec"><div class="wbh">Hospitals</div>${st.hospitals.map(e => entRow(e)).join("")}</div>
      <div class="wbsec"><div class="wbh">Most-involved patients <span class="mut" style="font-weight:400">(may be victims)</span></div>${st.patients.slice(0, 6).map(e => entRow(e, ` · ${e.flagged} flagged`)).join("")}</div>
    </aside>
    <section class="wbmain">
      <div class="wbbar">${typeIcon(focusNode.type, 18, "#1E2024")}<div><b>${esc(focusNode.label)}</b><div class="sm mut">${TLAB[focusNode.type]} · ${g.nodes.length - 1} connected · ${flaggedEdges} link(s) with flagged claims${g.more.patients ? ` · showing ${types.patient || 0} of ${(types.patient || 0) + g.more.patients} patients (most flagged first) <button class="btn sm" data-more="1" style="margin-left:6px">Show ${Math.min(24, g.more.patients)} more</button>` : ""}${NET.limit > 24 ? ` <button class="btn sm" data-more="0">Show fewer</button>` : ""}</div></div><span class="sp"></span><div class="pill-row">${Object.entries(types).map(([t, c]) => `<span class="tag t-med">${typeIcon(t, 12)}&nbsp;${c} ${(c > 1 ? TPLU[t] : TLAB[t]).toLowerCase()}</span>`).join("")}</div></div>
      <div class="wbgraph">${g.nodes.length > 1 ? (NET.dim === "3d" ? graph3dHTML(toGraph(g), { id: "lg", height: 640, onNode: "inspect" }) : graphHTML(toGraph(g), { id: "lg", height: 640, onNode: "inspect", canvas: Math.max(560, Math.min(1250, 170 * Math.sqrt(g.nodes.length))) })) : `<div class="loading">No relationships of the selected types${NET.flagged ? " with flagged claims" : ""}.</div>`}</div>
    </section>
    <aside class="wbinspect" id="wbinsp"><div class="mut sm">Select an entity.</div></aside>
  </div>`;
}

window.wbInspect = async id => {
  const el = $("#wbinsp"); if (!el) return;
  let d; try { d = await api("graph/inspect?id=" + encodeURIComponent(id)); } catch (e) { el.innerHTML = `<div class="banner red">${esc(e.message)}</div>`; return; }
  const sc = d.score == null ? "" : `<div class="wbscore"><b style="color:${d.kind === "patient" ? (d.score >= 60 ? "#55595F" : "#C28A1B") : riskColor(d.score)}">${Math.round(d.score)}</b><span>${d.score_kind}</span></div>`;
  const fv = (k, v) => v == null ? "–" : typeof v === "number" ? (k.toLowerCase().includes("paid") ? money(v) : k.toLowerCase().includes("share") ? pc(v) : num(v)) : esc(v);
  const isFocus = id === NET.focus;
  el.innerHTML = `<div class="row" style="gap:10px;align-items:flex-start">${typeIcon(d.type, 26, "#1E2024")}<div style="flex:1;min-width:0"><div class="b" style="font-size:15px">${esc(d.title)}</div><div class="sm mut">${esc(d.subtitle || "")}</div></div>${sc}</div>
    ${d.case_id ? `<a class="btn sm pri" style="margin-top:10px" href="#/case/${d.case_id}">Open case ${d.case_id} →</a>` : ""}
    <table class="wbfacts">${d.facts.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${fv(k, v)}</td></tr>`).join("")}</table>
    ${d.relations?.length ? `<div class="wbh">All relationships</div><table class="wbfacts" style="margin-top:0">${d.relations.map(r => `<tr><td>${esc(r.rel)}${r.note ? `<div class="sm mut">${esc(r.note)}</div>` : ""}</td><td class="num"><b>${num(r.count)}</b></td></tr>`).join("")}</table>` : ""}
    ${d.signals?.length ? `<div class="wbh">Rule findings (180d)</div><div class="pill-row">${d.signals.map(x => `<span class="tag t-high">${esc(x.name)} · ${x.lines}</span>`).join("")}</div>` : ""}
    ${d.models ? `<div class="wbh">Detectors</div><div class="wbmodels">${Object.entries(d.models).filter(([, v]) => v != null).map(([k, v]) => `<div><span>${k}</span><div class="bar"><i style="width:${v * 100}%;background:${v > .8 ? "#B4423C" : v > .6 ? "#D9772B" : "#A0A4AB"}"></i></div><b>${Math.round(v * 100)}</b></div>`).join("")}</div>` : ""}
    ${d.explanations ? `<div class="wbh">Possible explanations</div><ul class="wbul">${d.explanations.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    ${d.note ? `<div class="banner" style="margin-top:10px;font-size:12px">${esc(d.note)}</div>` : ""}
    <div class="wbactions">${isFocus ? "" : `<button class="btn sm pri" data-focus="${d.id}">Pivot here</button>`}${d.kind === "provider" ? `<a class="btn sm" href="#/provider/${d.id}">Provider page</a>` : ""}<button class="btn sm" data-patha="${d.id}">${NET.pathA ? "Connect to " + esc(NET.pathA.label) : "Find connection from here…"}</button></div>
    <div id="wbpath"></div>`;
};

// 2D portfolio map as a board of communities: one clean panel per community (own layout, no overlapping hulls or
// labels); links between communities are listed, not drawn across the page. Quiet communities collapse into a list.
function communityBoard(nodes, edges, comms, n) {
  const byC = {}; nodes.forEach(x => (byC[x.community] = byC[x.community] || []).push(x));
  const cOf = Object.fromEntries(nodes.map(x => [x.id, x.community]));
  const active = comms.filter(c => (byC[c.id] || []).length && (c.max_risk >= 25 || c.ties > 0));
  const quiet = comms.filter(c => (byC[c.id] || []).length && !(c.max_risk >= 25 || c.ties > 0));
  const nameOf = id => nodes.find(x => x.id === id)?.label || id;
  const panel = c => {
    const ns = byC[c.id].slice().sort((a, b) => b.risk - a.risk), ids = new Set(ns.map(x => x.id));
    const inner = edges.filter(e => ids.has(e.source) && ids.has(e.target));
    const out = {}; edges.forEach(e => { const a = ids.has(e.source), b = ids.has(e.target); if (a !== b) { const o = cOf[a ? e.target : e.source]; if (o != null && o >= 0) { out[o] = out[o] || new Set(); out[o].add(e.kind); } } });
    const big = ns.length > 10, h = Math.min(460, 230 + ns.length * 12);
    const top = ns.filter(x => x.risk >= 40 || x.case_id).slice(0, 3);
    return `<div class="card cpanel"><div class="cphead"><div><b>Community ${c.id + 1}</b><div class="sm mut">${c.size} providers · ${c.ties} suspicious tie${c.ties === 1 ? "" : "s"} · ${money(c.paid)}</div></div><span class="sp"></span><span class="tag ${c.max_risk >= 60 ? "t-crit" : c.max_risk >= 40 ? "t-high" : "t-gray"}">max risk ${Math.round(c.max_risk)}</span></div>
      ${top.length ? `<div class="cptop">${top.map(x => `<a href="#/provider/${x.id}" class="cpchip"><i style="background:${riskColor(x.risk)}"></i>${esc(x.label)}${x.case_id ? ` <span class="mut">· ${x.case_id}</span>` : ""}</a>`).join("")}</div>` : ""}
      <div class="cpgraph">${graphHTML({ nodes: ns, edges: inner }, { height: h, id: "ngc" + c.id, labelMin: big ? 40 : 25, onNode: "select", canvas: Math.max(300, Math.min(620, 105 * Math.sqrt(ns.length))), legend: false })}</div>
      <div class="cpfoot sm">${Object.keys(out).length ? "Links to " + Object.entries(out).sort((a, b) => b[1].size - a[1].size).slice(0, 4).map(([o, k]) => `<b>Community ${+o + 1}</b> <span class="mut">(${[...k].map(x => (EDGE[x]?.l || x).toLowerCase()).join(", ")})</span>`).join(" · ") : '<span class="mut">No links to other communities.</span>'}</div></div>`;
  };
  const present = new Set(edges.map(e => e.kind));
  return `<div class="cboard">${active.map(panel).join("")}</div>
    <div class="card" style="margin-top:12px;padding:10px 14px">${graphLegend(present)}</div>
    ${quiet.length ? `<details class="card" style="margin-top:12px;padding:12px 14px"><summary class="sm"><b>${quiet.length} quiet communities</b> <span class="mut">— no suspicious ties and every provider below risk 25</span></summary><div class="grid g3" style="margin-top:10px">${quiet.map(c => `<div class="sm"><b>Community ${c.id + 1}</b> <span class="mut">${c.size} providers · ${money(c.paid)}</span><div>${c.providers.slice(0, 4).map(p => esc(nameOf(p))).join(", ")}${c.size > 4 ? "…" : ""}</div></div>`).join("")}</div></details>` : ""}`;
}
async function vNetworkMap() {
  const n = await api("network"); S.net = n;
  const minRisk = S.netMin ?? 0, q = (S.netQ || "").toLowerCase();
  const keep = new Set(n.nodes.filter(x => x.risk >= minRisk && (!q || x.label.toLowerCase().includes(q) || x.id.toLowerCase().includes(q) || (x.case_id || "").toLowerCase().includes(q))).map(x => x.id));
  if (q) n.edges.forEach(e => { if (keep.has(e.source) || keep.has(e.target)) { keep.add(e.source); keep.add(e.target); } });
  const nodes = n.nodes.filter(x => keep.has(x.id)).map(x => ({ ...x, kind: "provider", primary: false }));
  const edges = n.edges.filter(e => keep.has(e.source) && keep.has(e.target)).flatMap(e => e.kinds.map(k => ({ source: e.source, target: e.target, kind: k, strong: e.strong, label: k })));
  const comms = n.communities.sort((a, b) => b.max_risk - a.max_risk);
  return netTop("map", `<input type="text" id="netq" placeholder="Search provider or case…" value="${esc(S.netQ || "")}" style="width:220px">`) + `
    ${NET.dim === "3d" ? `<div class="card" style="padding:0;overflow:hidden">${graph3dHTML({ nodes, edges }, { height: 760, id: "ng", labelMin: 40, onNode: "select", communities: comms.map(c => ({ id: c.id, max_risk: c.max_risk, ties: c.ties, size: c.size, paid: c.paid })) })}</div>` : communityBoard(nodes, edges, comms, n)}`;
}


/* ------------------------------------------------------------ operations */
const sevTag2 = s => `<span class="tag ${s >= .9 ? "t-crit" : s >= .6 ? "t-high" : "t-med"}">${s >= .9 ? "high" : s >= .6 ? "medium" : "low"}</span>`;
const PP = { claim: null, result: null };
async function vPrepay() {
  const [ex, log] = await Promise.all([api("prepay/examples"), api("prepay?limit=30")]);
  const c = PP.claim || ex[0].claim; PP.ex = ex;
  const lines = c.lines.length ? c.lines : [{ code: "", units: 1 }];
  const r = PP.result;
  const recCls = r ? (r.recommendation === "PEND" ? "red" : r.recommendation === "PAY_MONITOR" ? "" : "green") : "";
  return hdr("Claim check", "Score a claim before it is paid. SpotZⁱ recommends Pay or Pend for human review, with reasons — it never denies a claim on its own.") +
  `<div class="grid g2"><div class="card"><h3>Claim</h3><div class="pill-row" style="margin-bottom:10px"><span class="sm mut">Load an example:</span>${ex.map((e, i) => `<button class="btn sm" data-ppex="${i}">${esc(e.title)}</button>`).join("")}</div>
    <div class="grid g2"><div><label class="f">Member ID</label><input type="text" id="pp_m" value="${esc(c.member_id || "")}"></div><div><label class="f">Billing provider ID</label><input type="text" id="pp_p" value="${esc(c.provider_id || "")}"></div>
    <div><label class="f">Service date</label><input type="text" id="pp_d" value="${esc(c.service_date || "")}" placeholder="YYYY-MM-DD"></div><div><label class="f">Place of service · diagnosis</label><div class="row"><input type="text" id="pp_pos" value="${esc(c.pos || "11")}" style="width:70px"><input type="text" id="pp_dx" value="${esc(c.dx || "")}" placeholder="dx (optional)"></div></div></div>
    <label class="f">Service lines</label><table><tr><th>Code</th><th class="num">Units</th><th class="num">Billed $</th><th></th></tr>${lines.map((l, i) => `<tr><td><input type="text" class="pp_code" value="${esc(l.code)}"></td><td><input type="number" class="pp_units" value="${l.units || 1}" style="width:80px"></td><td><input type="number" class="pp_billed" value="${l.billed || ""}" placeholder="auto" style="width:110px"></td><td><button class="btn sm" data-pprm="${i}">×</button></td></tr>`).join("")}</table>
    <div class="row" style="margin-top:10px"><button class="btn sm" id="ppadd">+ Line</button><span class="sp"></span><button class="btn pri" id="ppgo">Check claim</button></div></div>
   <div>${r ? `<div class="banner ${recCls}" style="font-size:15px"><b>${esc(r.label)}</b> <span class="sm">· score ${r.score} · ${r.latency_ms} ms · expected paid ${money(r.expected_paid)}</span></div>
     <div class="card"><h3>Why</h3>${r.reasons.length ? r.reasons.map(x => `<div class="ex">${sevTag2(x.severity)} <b>${esc(x.name)}</b>${x.line != null ? ` <span class="mut">(line ${x.line + 1})</span>` : ""}<br>${esc(x.text)}</div>`).join("") : '<div class="sm mut">No rule or history check fired.</div>'}
     ${r.context.length ? `<div class="wbh">Provider context</div>${r.context.map(x => `<div class="sm">• ${esc(x)}</div>`).join("")}` : ""}
     <div class="wbh">Lines</div><table><tr><th>Code</th><th>Description</th><th class="num">Units</th><th class="num">Expected paid</th><th>Flags</th><th class="num">Model risk</th></tr>${r.lines.map(l => `<tr><td class="mono">${esc(l.code)}</td><td class="sm">${esc(l.description)}</td><td class="num">${l.units}</td><td class="num">${money(l.expected_paid)}</td><td>${l.flags.map(f => `<span class="tag t-high">${f}</span>`).join(" ")}</td><td class="num">${l.model_risk == null ? "–" : `<b style="color:${l.model_risk >= .8 ? "#B4423C" : l.model_risk >= .4 ? "#C28A1B" : "inherit"}">${pc(l.model_risk)}</b>${(l.model_drivers || []).length ? `<div class="sm mut">${l.model_drivers.map(x => esc(x.feature)).join(", ")}</div>` : ""}`}</td></tr>`).join("")}</table>${r.model ? '<div class="sm mut" style="margin-top:6px">Model risk = trained pre-payment line-risk model (see Governance → Task models). Context for the reviewer, never an automatic denial.</div>' : ""}
     <div class="sm mut" style="margin-top:8px">${esc(r.note)}</div></div>` : `<div class="card"><div class="mut">Enter a claim or load an example, then “Check claim”. Checks: eligibility & death, inpatient-stay overlap, excluded providers, duplicates, repeat intervals, unbundling, daily unit limits, impossible hours, excessive visits, level-5 patterns, and whether the provider is already under review.</div></div>`}</div></div>
  <div class="card" style="margin-top:14px"><h3>Recent checks <small>pended claims wait for a human</small></h3><table><tr><th>#</th><th>When</th><th>Member · provider</th><th>Recommendation</th><th class="num">Expected paid</th><th>Status</th><th></th></tr>${log.map(p => `<tr><td>${p.id}</td><td class="sm">${p.ts}</td><td class="sm mono">${esc(p.claim.member_id)} · ${esc(p.claim.provider_id)}</td><td><span class="tag ${p.recommendation === "PEND" ? "t-crit" : p.recommendation === "PAY" ? "t-ok" : "t-high"}">${p.recommendation === "PEND" ? "Pend" : p.recommendation === "PAY" ? "Pay" : "Pay + monitor"}</span> <span class="sm mut">${p.reasons.map(x => x.name).slice(0, 2).join(", ")}</span></td><td class="num">${money(p.amount)}</td><td class="sm">${p.status === "pending" ? '<span class="tag t-high">awaiting review</span>' : p.status === "resolved" ? `${esc(p.resolution || "")}${p.avoided ? ` · avoided ${money(p.avoided)}` : ""}` : "paid"}</td><td>${p.status === "pending" && S.perms.includes("investigate") ? `<button class="btn sm" data-ppres="${p.id}" data-r="Released for payment">Release</button> <button class="btn sm" data-ppres="${p.id}" data-r="Adjusted">Adjust</button> <button class="btn sm" data-ppres="${p.id}" data-r="Denied by reviewer">Deny</button>` : ""}</td></tr>`).join("") || '<tr><td colspan="7" class="mut sm">No checks yet.</td></tr>'}</table></div>`;
}
function readClaim() {
  const codes = $$(".pp_code"), units = $$(".pp_units"), billed = $$(".pp_billed");
  return { member_id: $("#pp_m").value.trim(), provider_id: $("#pp_p").value.trim(), service_date: $("#pp_d").value.trim(), pos: $("#pp_pos").value.trim(), dx: $("#pp_dx").value.trim() || null,
    lines: codes.map((c, i) => ({ code: c.value.trim(), units: +units[i].value || 1, billed: billed[i].value ? +billed[i].value : null })).filter(l => l.code) };
}

async function vTips() {
  const tips = await api("tips"); const sup = S.perms.includes("assign");
  return hdr("Tips & referrals in", "Allegations from hotlines, members, employees or providers. Logged, triaged by a supervisor, and linked to cases.") +
  `<div class="grid g12"><div class="card"><h3>Log a tip</h3><label class="f">Channel</label><select id="tp_ch">${["Hotline", "Member", "Employee", "Provider", "Law enforcement", "Other"].map(x => `<option>${x}</option>`).join("")}</select>
    <label class="f">About</label><div class="row"><select id="tp_st" style="width:120px"><option value="provider">Provider</option><option value="member">Member</option><option value="other">Other</option></select><input type="text" id="tp_id" placeholder="ID, e.g. P-0119"></div>
    <label class="f">Allegation</label><textarea id="tp_al" placeholder="What was reported, by whom (no unnecessary personal details), when"></textarea><button class="btn pri" id="tpgo" style="margin-top:10px">Log tip</button>
    <div class="sm mut" style="margin-top:8px">Tips are allegations, not evidence. Record only what is needed; supervisors triage every tip.</div></div>
   <div class="card"><h3>Inbox <small>${tips.filter(t => t.status === "new").length} new</small></h3>${tips.map(t => `<div style="padding:10px 0;border-bottom:1px solid var(--line2)"><div class="row"><b>#${t.id}</b><span class="tag t-med">${esc(t.channel)}</span><span class="tag ${t.status === "new" ? "t-high" : t.status === "linked" ? "t-ok" : "t-gray"}">${t.status}</span><span class="sm mut">${t.ts} · by ${esc(t.received_by)}</span><span class="sp"></span>${t.case_id ? `<a class="sm" href="#/case/${t.case_id}">${t.case_id} →</a>` : ""}</div>
     <div class="sm" style="margin-top:4px">About <b>${esc(t.subject_name || t.subject_id || "—")}</b>${t.subject_risk != null ? ` · risk ${Math.round(t.subject_risk)}` : ""}${t.suggested_case && !t.case_id ? ` · <span style="color:var(--accent)">matches open case ${t.suggested_case}</span>` : ""}</div><div class="sm">“${esc(t.allegation)}”</div>${t.ai ? `<div class="sm" style="margin-top:6px;padding:8px;border:1px solid var(--line2);border-radius:6px"><div class="row">${aiEngineTag(t.ai.engine, t.ai.model)}<b>${esc(t.ai.scheme)}</b><span class="tag ${t.ai.urgency === "high" ? "t-crit" : t.ai.urgency === "medium" ? "t-high" : "t-gray"}">${esc(t.ai.urgency)} urgency</span></div>${t.ai.summary ? `<div style="margin-top:4px">${esc(t.ai.summary)}</div>` : ""}${t.ai.matched_providers?.length ? `<div style="margin-top:4px">Matches: ${t.ai.matched_providers.map(m => `<a href="#/provider/${m.provider_id}">${esc(m.name)}</a> <span class="mut">(${m.provider_id}, match ${Math.round(m.match * 100)}%, risk ${Math.round(m.risk)})</span>`).join(" · ")}</div>` : '<div class="mut" style="margin-top:4px">No provider matched in claims data.</div>'}${t.ai.checks?.length ? `<div class="mut" style="margin-top:4px">Suggested checks: ${t.ai.checks.map(esc).join(" · ")}</div>` : ""}</div>` : ""}${t.triage_note ? `<div class="sm mut">Triage: ${esc(t.triage_note)} (${esc(t.triaged_by)})</div>` : ""}
     ${sup && t.status === "new" ? `<div class="row" style="margin-top:6px">${t.suggested_case ? `<button class="btn sm pri" data-tip="${t.id}" data-act2="link" data-case="${t.suggested_case}">Link to ${t.suggested_case}</button>` : ""}<button class="btn sm" data-tip="${t.id}" data-act2="link">Link to case…</button><button class="btn sm" data-tip="${t.id}" data-act2="watch">Watchlist</button><button class="btn sm" data-tip="${t.id}" data-act2="close">Close</button></div>` : ""}</div>`).join("") || '<div class="mut sm">No tips yet.</div>'}</div></div>`;
}

async function vOutcomes() {
  const o = await api(`outcomes?rate=${S.rate || 65}`);
  const kpi = (l, v, s2) => `<div class="card kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="s">${s2 || ""}</div></div>`;
  return hdr("Outcomes & reports", "What SIU work returned: overpayments identified and recovered, payments avoided before they went out, and the review effort it took.",
    `<div class="row sm">Hourly cost $<input type="number" id="rate" value="${S.rate || 65}" style="width:80px"></div><a class="btn" href="/api/reports/siu.csv?rate=${S.rate || 65}">Export SIU report (CSV)</a><button class="btn" id="printbtn">Print</button>`) +
  `<div class="grid g5">${kpi("Identified overpayment", money(o.identified), `${o.cases_with_recovery} case(s)`)}${kpi("Recovered", money(o.recovered), o.identified ? pc(o.recovered / o.identified) + " of identified" : "")}${kpi("Avoided before payment", money(o.avoided), `${o.prepay.pended} pended · ${o.prepay.resolved} resolved`)}${kpi("Review effort", `${Math.round(o.hours)}h`, `${money(o.cost)} at $${o.rate}/h`)}${kpi("Return on review", o.roi == null ? "–" : o.roi.toFixed(1) + "×", "(recovered + avoided) ÷ cost")}</div>
  <div class="grid g2" style="margin-top:12px"><div class="card"><h3>By scheme</h3><table><tr><th>Type</th><th class="num">Cases</th><th class="num">Identified</th><th class="num">Recovered</th></tr>${o.by_type.map(t => `<tr><td>${esc(t.type)}</td><td class="num">${t.cases}</td><td class="num">${money(t.identified)}</td><td class="num">${money(t.recovered)}</td></tr>`).join("") || '<tr><td colspan="4" class="mut sm">No recoveries recorded yet. Supervisors add them on a case’s Decision tab.</td></tr>'}</table></div>
   <div class="card"><h3>Decisions</h3><table><tr><td>Decisions recorded</td><td class="num">${o.decisions}</td></tr><tr><td>Cases decided</td><td class="num">${o.cases_decided}</td></tr><tr><td>Referrals approved</td><td class="num">${o.referrals}</td></tr>${Object.entries(o.outcomes).map(([k, v]) => `<tr><td class="sm">${esc(k)}</td><td class="num">${v}</td></tr>`).join("")}<tr><td>Claims checked before payment</td><td class="num">${o.prepay.checked}</td></tr></table></div></div>
  <div class="card" style="margin-top:12px"><h3>Recovery ledger</h3><table><tr><th>Case</th><th>Stage</th><th class="num">Identified</th><th class="num">Recovered</th><th>Updated</th><th>Note</th></tr>${o.recoveries.map(r => `<tr><td><a href="#/case/${r.case_id}">${r.case_id}</a></td><td>${esc(r.stage)}</td><td class="num">${money(r.identified)}</td><td class="num">${money(r.recovered)}</td><td class="sm">${r.ts} · ${esc(r.user_name)}</td><td class="sm">${esc(r.note || "")}</td></tr>`).join("") || '<tr><td colspan="6" class="mut sm">Empty.</td></tr>'}</table><div class="sm mut" style="margin-top:8px">Figures are only what reviewers recorded. Gross flagged exposure is never counted as savings.</div></div>`;
}

const RS = { conds: [{ field: "code", op: "in", value: "RX-COMP" }, { field: "paid", op: ">", value: "500" }], preview: null };
async function vRules() {
  const r = await api("rules/custom"); const can = S.perms.includes("run_models");
  const fields = Object.keys(r.fields);
  const pv = RS.preview;
  return hdr("Rule studio", "Write a detection rule from simple conditions, see exactly what it would flag, then switch it on. No code needed; every change is audited.") +
  `<div class="card" style="margin-bottom:12px"><h3>Describe a rule in plain English <small>an LLM drafts the conditions; you preview, save and activate</small></h3><div class="row"><input type="text" id="rs_nl" placeholder="e.g. flag psychotherapy 90837 sessions shorter than 53 minutes" value="${esc(RS.nl || "")}">${can ? '<button class="btn" id="rsdraft">Draft conditions</button>' : ""}</div>${RS.draftMsg ? `<div class="sm mut" style="margin-top:6px">${esc(RS.draftMsg)}</div>` : ""}</div>
  <div class="grid g2"><div class="card"><h3>New rule</h3><label class="f">Name</label><input type="text" id="rs_name" placeholder="e.g. High-cost compounded drugs" value="${esc(RS.name || "")}">
    <label class="f">Conditions (all must match)</label>${RS.conds.map((c, i) => `<div class="row" style="margin-bottom:6px"><select class="rs_f" style="width:180px">${fields.map(f => `<option ${f === c.field ? "selected" : ""}>${f}</option>`).join("")}</select><select class="rs_o" style="width:90px">${r.ops.map(o => `<option ${o === c.op ? "selected" : ""}>${esc(o)}</option>`).join("")}</select><input type="text" class="rs_v" value="${esc(c.value)}"><button class="btn sm" data-rsrm="${i}">×</button></div>`).join("")}
    <div class="row"><button class="btn sm" id="rsadd">+ Condition</button><span class="sp"></span>${can ? `<button class="btn" id="rsprev">Preview</button><button class="btn pri" id="rssave">Save rule</button>` : '<span class="sm mut">Analysts and admins can create rules.</span>'}</div>
    <div class="sm mut" style="margin-top:8px">Fields: code, family, pos, dx, units, paid, billed, duration_min, weekday (0=Mon), provider_lines_per_day, member_lines_per_day, member_age, provider_id. Use “in” with comma-separated values.</div></div>
   <div class="card"><h3>Preview <small>what this rule would flag in the current data</small></h3>${pv ? `${pv.warning ? `<div class="banner">${esc(pv.warning)}</div>` : ""}<div class="grid g4">${[["Lines", num(pv.lines)], ["Providers", pv.providers], ["Members", pv.members], ["Paid", money(pv.paid)]].map(([l, v]) => `<div class="kpi" style="padding:4px 0"><div class="l">${l}</div><div class="v" style="font-size:20px">${v}</div></div>`).join("")}</div>
     <div class="sm">${pc(pv.already_flagged)} already flagged by existing rules · ${pc(pv.in_cases)} from providers already in cases</div><div class="wbh">Top providers</div>${pv.top.map(t => `<div class="sm row"><a href="#/provider/${t.provider_id}">${esc(t.name)}</a><span class="sp"></span>${num(t.lines)} lines · ${money(t.paid)}</div>`).join("")}` : '<div class="mut sm">Press Preview to test the rule before saving.</div>'}</div></div>
  <div class="card" style="margin-top:12px"><div class="row"><h3 style="margin:0">Saved rules</h3><span class="sp"></span>${can ? `<button class="btn" id="rsapply">Re-run analysis with active rules</button>` : ""}</div><table style="margin-top:8px"><tr><th>Name</th><th>Conditions</th><th>Author</th><th>Status</th><th></th></tr>${r.rules.map(x => `<tr><td><b>${esc(x.name)}</b></td><td class="sm mono">${x.conditions.map(c => `${esc(c.field)} ${esc(c.op)} ${esc(c.value)}`).join(" AND ")}</td><td class="sm">${esc(x.author)} · ${x.ts}</td><td>${x.active ? '<span class="tag t-ok">active</span>' : '<span class="tag t-gray">draft</span>'}</td><td>${can ? `<button class="btn sm" data-rstog="${x.id}">${x.active ? "Deactivate" : "Activate"}</button>` : ""}</td></tr>`).join("") || '<tr><td colspan="5" class="mut sm">No custom rules yet.</td></tr>'}</table><div class="sm mut" style="margin-top:8px">Active rules flag lines as “Analyst-defined rule” on the next analysis run and flow into cases, the Brain and briefs like any other rule.</div></div>`;
}
function readConds() { return $$(".rs_f").map((f, i) => ({ field: f.value, op: $$(".rs_o")[i].value, value: $$(".rs_v")[i].value })); }

async function recCard(cid) {
  const el = $("#reccard"); if (!el) return; const r = await api(`cases/${cid}/recovery`);
  const last = r.history[r.history.length - 1];
  el.innerHTML = `<h3>Recovery <small>money actually identified and recovered</small></h3>${last ? `<div class="sm"><b>${esc(last.stage)}</b> · identified ${money(last.identified)} · recovered ${money(last.recovered)} <span class="mut">(${last.ts})</span></div>` : '<div class="sm mut">Nothing recorded.</div>'}
   <div class="grid g3" style="margin-top:8px"><select id="rc_st">${r.stages.map(x => `<option ${last && last.stage === x ? "selected" : ""}>${x}</option>`).join("")}</select><input type="number" id="rc_id" placeholder="Identified $" value="${last ? last.identified : ""}"><input type="number" id="rc_rv" placeholder="Recovered $" value="${last ? last.recovered : ""}"></div>
   <div class="row" style="margin-top:6px"><input type="text" id="rc_note" placeholder="Note (letter ref, plan terms…)"><button class="btn sm" id="rcgo">Update</button></div>`;
}
async function docCard(cid) {
  const el = $("#doccard"); if (!el) return; const ds = await api(`cases/${cid}/documents`);
  el.innerHTML = `<h3>Documents <small>records received for this case</small></h3>${ds.map(d => `<div class="sm row" style="padding:3px 0"><a href="/api/documents/${d.id}">${esc(d.filename)}</a><span class="mut">${Math.round(d.size / 1024)} KB · ${esc(d.uploaded_by)} · ${d.ts}</span></div>`).join("") || '<div class="sm mut">No documents yet.</div>'}
   ${S.perms.includes("investigate") ? `<div class="row" style="margin-top:8px"><input type="file" id="docf" multiple accept=".pdf,.png,.jpg,.jpeg,.txt,.csv,.docx,.xlsx"><button class="btn sm" id="docgo">Upload</button></div><div class="sm mut">PDF, images, text, CSV, Word, Excel · max 20 MB · content-checked · every download is audited.</div>` : ""}`;
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
    <div class="card" style="overflow:auto"><table><tr><th>Provider</th><th>Family</th><th class="num">Risk</th><th class="num">Rules</th><th class="num">Anomaly</th><th class="num">Graph</th><th class="num">Sentinel</th><th class="num">Panel</th><th class="num">60d fcst</th><th class="num">Lines 180d</th><th class="num">Flagged $</th><th>Case</th></tr>${r.slice(0, 80).map(p => `<tr class="click" data-go="provider/${p.provider_id}"><td><b>${esc(p.name)}</b><div class="sm mut">${p.provider_id} · ${p.city}</div></td><td>${FAM[p.family]}</td><td class="num"><b style="color:${riskColor(p.risk)}">${Math.round(p.risk)}</b></td><td class="num">${Math.round(p.rule_score * 100)}</td><td class="num">${pc(p.anomaly_pct)}</td><td class="num">${Math.round(p.graph_score * 100)}</td><td class="num">${p.sentinel == null ? "–" : pc(p.sentinel)}</td><td class="num">${p.panel_pct == null ? "–" : pc(p.panel_pct)}</td><td class="num">${pc(p.fc60)}</td><td class="num">${num(p.n_lines)}</td><td class="num">${money(p.flagged_paid)}</td><td>${p.case_id ? `<a href="#/case/${p.case_id}">${p.case_id}</a>` : ""}</td></tr>`).join("")}</table></div>`;
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
    `<div class="grid g4">${[["Risk", Math.round(sc.risk), riskColor(sc.risk)], ["Rule score", Math.round(sc.rule_score * 100)], ["Anomaly percentile", pc(sc.anomaly_pct)], ["Graph score", Math.round(sc.graph_score * 100)], ["Sentinel", sc.sentinel == null ? "n/a" : pc(sc.sentinel)], ["Patient-panel shift", sc.panel_pct == null ? "n/a" : pc(sc.panel_pct)], ["Case-outcome model", sc.outcome_p == null ? "n/a" : pc(sc.outcome_p)], ["Repeat risk 30/60/90", [sc.fc30, sc.fc60, sc.fc90].map(x => Math.round(x * 100)).join(" / ") + "%"]].map(([l, v, c]) => `<div class="card kpi"><div class="l">${l}</div><div class="v" style="${c ? "color:" + c : ""}">${v}</div></div>`).join("")}</div>
    <div class="grid g2" style="margin-top:14px"><div class="card"><h3>Rule hits <small>180-day lookback</small></h3>${barsH(Object.entries(p.rules).map(([k, r]) => ({ label: r.name, value: r.lines })))}<h3 style="margin-top:14px">Peer-relative anomaly drivers</h3>${p.anomaly_drivers.length ? p.anomaly_drivers.map(d => `<div class="sm">${esc(d.feature)}: ${d.peer_z > 0 ? "+" : ""}${d.peer_z.toFixed(1)}σ vs ${FAM[pr.family]} peers</div>`).join("") : '<div class="sm mut">No strong outliers.</div>'}</div>
    <div class="card"><h3>Paid vs flagged by month</h3>${monthChart(p.monthly)}<h3 style="margin-top:14px">Top codes</h3><table><tr><th>Code</th><th class="num">Lines</th><th class="num">Paid</th><th class="num">Flagged</th></tr>${p.codes.slice(0, 6).map(c => `<tr><td class="mono">${c.code}</td><td class="num">${num(c.lines)}</td><td class="num">${money(c.paid)}</td><td class="num">${num(c.flagged)}</td></tr>`).join("")}</table></div></div>
    <div class="card" style="margin-top:14px"><h3>Relationships <small>1-hop</small></h3>${graphHTML(p.network, { id: "pg", height: 420 })}<div style="margin-top:8px"><a class="btn sm" href="#/explorer/claims?provider=${p.provider_id}">View flagged claims →</a></div></div>`;
}

/* ------------------------------------------------------------ knowledge + decision chain */
function md(t) {
  return esc(t).replace(/^# (.+)$/gm, "<h2 style='font-size:18px;margin:0 0 10px'>$1</h2>").replace(/^## (.+)$/gm, "<h3 style='margin:16px 0 6px'>$1</h3>")
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\[\[([a-z0-9\-\/]+)\]\]/g, '<a href="#/knowledge/page?slug=$1" class="tag t-med" style="text-decoration:none">$1</a>')
    .replace(/\(source: ([^)]+)\)/g, '<span class="mut sm" style="font-size:11px"> · $1</span>')
    .replace(/^- (.+)$/gm, "<div style='padding:3px 0 3px 14px;position:relative'><span style='position:absolute;left:0;color:var(--faint)'>•</span>$1</div>").replace(/\n\n/g, "<br>");
}
const LINTC = { ok: "t-ok", warn: "t-high", review: "t-vio", block: "t-crit" };
async function vKnowledge() {
  const sub = S.arg || "home"; const params = new URLSearchParams(location.hash.split("?")[1] || "");
  if (sub === "page") {
    const slug = params.get("slug"); let p;
    try { p = await api("wiki/page?slug=" + encodeURIComponent(slug)); } catch (e) { return hdr("Knowledge", "") + `<div class="banner">${esc(slug)}: ${esc(e.message)}. It may still be a pending proposal in the review queue.</div><a href="#/knowledge">← Knowledge</a>`; }
    return `<div class="noprint"><a href="#/knowledge">← Knowledge</a></div>` + hdr(esc(p.page.title), `${p.page.kind} · <span class="mono">${esc(p.page.slug)}</span> · version ${p.page.version} · approved by ${esc(p.page.author)} · ${p.page.updated}`, p.pending_proposal ? `<a class="btn" href="#/knowledge/review?id=${p.pending_proposal}">Pending update →</a>` : "") +
      `<div class="grid g21"><div class="card">${md(p.page.body)}</div><div><div class="card"><h3>Linked from</h3>${p.backlinks.map(b => `<div class="sm"><a href="#/knowledge/page?slug=${b.slug}">${esc(b.title)}</a></div>`).join("") || '<div class="sm mut">No backlinks.</div>'}</div><div class="card" style="margin-top:12px"><h3>Version history</h3>${p.history.map(h => `<div class="sm" style="padding:4px 0;border-bottom:1px solid var(--line2)"><b>v${h.version}</b> · ${esc(h.author)} · ${h.ts}<div class="mut">${esc(h.note || "")}</div></div>`).join("")}</div></div></div>`;
  }
  if (sub === "review") {
    const pr = await api("wiki/proposals/" + params.get("id"));
    return `<div class="noprint"><a href="#/knowledge">← Knowledge</a></div>` + hdr("Review update", `<span class="mono">${esc(pr.slug)}</span> · ${esc(pr.reason)} · from ${esc(pr.source)}`) +
      `<div class="card"><h3>Lint</h3><div class="pill-row">${pr.lint.map(l => `<span class="tag ${LINTC[l.level]}">${esc(l.check)}${l.detail ? ": " + esc(l.detail) : ""}</span>`).join("")}</div></div>
      <div class="grid g2" style="margin-top:12px"><div class="card"><h3>Current approved ${pr.current ? "v" + pr.current.version : "(new page)"}</h3>${pr.current ? md(pr.current.body) : '<div class="mut">No approved version yet.</div>'}</div><div class="card" style="box-shadow:inset 3px 0 0 var(--accent)"><h3>Proposed</h3>${md(pr.body)}</div></div>
      ${pr.status === "pending" ? `<div class="card" style="margin-top:12px"><div class="grid g2"><div><label class="f">Reviewer</label><input type="text" id="wrv" value="${esc(S.user.name)}" disabled></div><div><label class="f">Review note ${pr.lint.some(l => l.level === "review") ? "(required)" : "(optional)"}</label><input type="text" id="wnote"></div></div><div class="row" style="margin-top:10px"><button class="btn pri" data-wiki="approve" data-id="${pr.id}">Approve into knowledge</button><button class="btn" data-wiki="reject" data-id="${pr.id}">Reject</button><span class="sm mut">Only approved knowledge is retrieved by the decision chain.</span></div></div>` : `<div class="banner">Status: ${esc(pr.status)}</div>`}`;
  }
  const w = await api("wiki"); const q = S.wq || ""; const res = q ? await api("wiki/search?q=" + encodeURIComponent(q)) : null;
  const byKind = {}; w.pages.forEach(p => (byKind[p.kind] = byKind[p.kind] || []).push(p));
  const clean = w.proposals.filter(p => p.lint.every(l => l.level === "ok")).length;
  return hdr("Knowledge", "SpotZⁱ's persistent, linked memory: policies, schemes, providers, cases and human decisions — maintained by the system, approved by people.",
      `<input type="text" id="wq" placeholder="Ask the knowledge base…" value="${esc(q)}" style="width:280px">`) +
    `<div class="journey"><div><b>Ingest</b><span>runs + decisions propose updates</span></div><div><b>Lint</b><span>citations · privacy · contradictions</span></div><div><b>Review</b><span>${w.proposals.length} pending</span></div><div><b>Update</b><span>${w.pages.length} approved pages, versioned</span></div><div><b>Compounds</b><span>retrieved by every decision chain</span></div></div>` +
    (res ? `<div class="card" style="margin-bottom:12px"><h3>Results for “${esc(q)}”</h3>${res.map(r => `<div style="padding:7px 0;border-bottom:1px solid var(--line2)"><a href="#/knowledge/page?slug=${r.slug}" class="b">${esc(r.title)}</a> <span class="tag t-gray">${r.kind}</span> <span class="sm mut">v${r.version} · relevance ${r.score.toFixed(2)}</span><div class="sm mut">${esc(r.snippet)}</div></div>`).join("") || '<div class="mut">No approved knowledge matches.</div>'}</div>` : "") +
    `<div class="grid g12"><div class="card"><h3>Approved knowledge</h3>${Object.entries(byKind).map(([k, ps]) => `<div style="margin-bottom:10px"><div class="sm mut" style="text-transform:capitalize;font-weight:600;margin-bottom:3px">${k} (${ps.length})</div>${ps.slice(0, 14).map(p => `<div class="sm" style="padding:2px 0"><a href="#/knowledge/page?slug=${p.slug}">${esc(p.title)}</a> <span class="mut">v${p.version}</span></div>`).join("")}${ps.length > 14 ? `<div class="sm mut">+${ps.length - 14} more</div>` : ""}</div>`).join("")}</div>
    <div><div class="card"><div class="row"><h3 style="margin:0">Review queue</h3><span class="sp"></span>${clean ? `<button class="btn sm" id="wclean">Approve ${clean} lint-clean update(s)</button>` : ""}</div><table style="margin-top:8px"><tr><th>Page</th><th>Why</th><th>Lint</th></tr>${w.proposals.slice(0, 40).map(p => `<tr class="click" data-go="knowledge/review?id=${p.id}"><td><b class="sm">${esc(p.title)}</b><div class="mono mut">${esc(p.slug)}</div></td><td class="sm">${esc(p.reason)}</td><td>${p.lint.map(l => `<span class="tag ${LINTC[l.level]}">${esc(l.check)}</span>`).join(" ")}</td></tr>`).join("") || '<tr><td colspan="3" class="mut">Nothing to review.</td></tr>'}</table></div>
    <div class="card" style="margin-top:12px"><h3>Recent knowledge updates</h3>${w.history.map(h => `<div class="sm" style="padding:3px 0"><a href="#/knowledge/page?slug=${h.slug}">${esc(h.slug)}</a> v${h.version} · ${esc(h.author)} · <span class="mut">${h.ts}</span></div>`).join("")}</div></div></div>`;
}
async function chainPanel(d) {
  const c = await api(`cases/${d.case_id}/chain`);
  const st = Object.fromEntries(c.steps.map(s => [s.key, s]));
  const box = (s, inner) => `<div class="card" style="position:relative"><div class="row"><span style="width:22px;height:22px;border-radius:50%;background:var(--ink);color:#fff;display:grid;place-items:center;font-size:11px;font-weight:600">${s.n}</span><h3 style="margin:0">${s.title}</h3><span class="sp"></span><span class="sm mut">${esc(s.summary)}</span></div><div style="margin-top:10px">${inner}</div></div>`;
  const R = st.retrieve, I = st.interpret, A = st.rules, P = st.propose, Sc = st.score, C = st.cite;
  return `<div class="banner blue">Traceable decision chain: each checkpoint strengthens evidence, confidence and accountability. Everything here is derived from SpotZⁱ's own detectors and approved knowledge — no external model.</div>
  <div class="row" style="gap:6px;margin-bottom:12px;flex-wrap:wrap">${c.steps.map(s => `<span class="tag t-med">${s.n} ${s.title}</span>${s.n < 6 ? '<span class="mut">→</span>' : ""}`).join("")}</div>
  <div class="grid g2">
  ${box(R, `<div class="sm mut">Query: ${esc(R.query)}</div>${R.policy.map(p => `<div class="ex"><a href="#/knowledge/page?slug=${p.slug}">${esc(p.title)}</a> <span class="mut">${p.kind} v${p.version}</span><br>${esc(p.snippet)}</div>`).join("")}${R.memory.map(p => `<div class="ex"><a href="#/knowledge/page?slug=${p.slug}">${esc(p.title)}</a> <span class="tag t-vio">memory</span></div>`).join("") || '<div class="sm mut" style="margin-top:6px">No approved memory pages yet — approve wiki updates to let past work inform this chain.</div>'}`)}
  ${box(I, `${I.facts.map(f => `<div class="sm"><span class="tag t-ok">fact</span> ${esc(f.text)} <span class="mono mut">${f.ref}</span></div>`).join("")}${I.hypotheses.map(h => `<div class="sm" style="margin-top:4px"><span class="tag t-med">hypothesis</span> ${esc(h.text)} <span class="mut">support ${h.support}</span></div>`).join("")}${I.gaps.map(g => `<div class="sm" style="margin-top:4px"><span class="tag t-high">gap</span> ${esc(g.text)}</div>`).join("")}`)}
  ${box(A, A.applied.map(a => `<div class="ex"><b>${esc(a.rule)}</b>: ${esc(a.result)}<br><span class="mut">Exception logic: ${esc(a.exception)}</span></div>`).join(""))}
  ${box(P, `<div class="sm"><b>${esc(P.recommendation)}</b></div>${P.next_check ? `<div class="ex">Next evidence check: <b>${esc(P.next_check)}</b> <span class="mut">(${P.next_check_value.toFixed(2)} bits/hour)</span>${P.alternatives.length ? `<br><span class="mut">Alternatives: ${P.alternatives.map(esc).join(" · ")}</span>` : ""}</div>` : ""}<div class="sm mut">${esc(P.requires)}</div>`)}
  ${box(Sc, `<table><tr><td>Evidence strength</td><td class="num"><b>${Math.round(Sc.evidence_strength)}</b>/100</td></tr><tr><td>Ambiguity</td><td class="num">${Sc.ambiguity_label} (${Sc.ambiguity_bits.toFixed(2)} bits)</td></tr><tr><td>Impact</td><td class="num">${esc(Sc.impact)}</td></tr><tr><td>Precedent fit</td><td class="num">${Sc.precedent_fit == null ? "no safe precedent" : `${pc(Sc.precedent_fit)} · ${Sc.precedent} · ${Sc.precedent_warnings} difference(s)`}</td></tr><tr><td>Confidence</td><td class="num"><b>${Sc.confidence}</b></td></tr></table>`)}
  ${box(C, `<div class="pill-row">${C.sources.map(s => `<span class="tag t-gray">${esc(s.kind)}: <span class="mono">${esc(s.ref)}</span></span>`).join("")}</div><h3 style="margin:12px 0 6px">Human checkpoints</h3>${C.checkpoints.map((x, i) => `<div class="sm">${i + 1}. ${esc(x)}</div>`).join("")}`)}
  </div><div class="card" style="margin-top:12px;border-left:3px solid var(--accent)"><b>The output.</b> ${esc(c.output)} <a href="#/case/${d.case_id}/decision">Go to decision →</a></div>`;
}
/* ------------------------------------------------------------ nexus brain */
const FEEDK = { lead: ["Lead", "t-vio"], change: ["Behaviour change", "t-high"], disagree: ["Disagreement", "t-gray"], learned: ["Learned", "t-ok"] };
async function vBrain() {
  const b = await api("brain");
  const held = b.held_out || [];
  return hdr("Nexus Brain", "Every detector feeds one memory. It fuses their evidence, learns from your decisions, and tells you what changed — including schemes no rule was written for.") +
    `<div class="journey"><div><b>${b.detectors.length} detectors</b><span>${b.detectors.map(d => esc(d.label.toLowerCase())).join(" · ")}</span></div><div><b>One-sided fusion</b><span>quiet detectors add nothing</span></div><div><b>Learns from you</b><span>${b.decisions_used} decision(s) used so far</span></div><div><b>Feed</b><span>${b.feed.length} insight(s) now</span></div><div><b>Human decides</b><span>never auto-acts</span></div></div>` +
    (held.length ? `<div class="banner green"><b>Recruitment mill: no rule was written for it.</b> We injected a patient-recruitment mill (members from distant regions, one templated visit + lab bundle); the patient-panel detector is designed for this typology. Rules can still fire incidentally on a co-subject; a provider with rules 0/100 reaches an investigator only through the Brain. ${held.map(h => `<b>${esc(h.provider)}</b>: rules ${Math.round(h.rules * 100)}/100 → Brain ${Math.round(h.brain * 100)}/100, ranked #${h.brain_rank} of 132${h.case_id ? ` · opened as <a href="#/case/${h.case_id}">${h.case_id}</a>` : ""}`).join("; ")}. Synthetic test only.</div>` : "") +
    `<div class="grid g21"><div class="card"><h3>Insight feed <small>ranked by importance</small></h3>${b.feed.map(f => `<div style="padding:10px 0;border-bottom:1px solid var(--line2)"><div class="row"><span class="tag ${FEEDK[f.kind][1]}">${FEEDK[f.kind][0]}</span><b>${esc(f.title)}</b><span class="sp"></span>${f.case_id ? `<a class="sm" href="#/case/${f.case_id}">${f.case_id} →</a>` : f.provider ? `<a class="sm" href="#/provider/${f.provider}">provider →</a>` : ""}</div><div class="sm mut" style="margin-top:3px">${esc(f.text)}</div></div>`).join("") || '<div class="mut">Nothing new.</div>'}</div>
    <div><div class="card"><h3>Detector weights <small>prior → learned</small></h3>${b.detectors.map(d => `<div style="margin:8px 0"><div class="row sm"><span>${esc(d.label)}</span><span class="sp"></span><span class="mut">${d.prior.toFixed(2)}</span><span>→</span><b>${d.learned.toFixed(2)}</b></div><div class="bar"><i style="width:${Math.min(100, d.learned / 1.5 * 100)}%;background:${Math.abs(d.learned - d.prior) > .05 ? "#55595F" : "#1E2024"}"></i></div></div>`).join("")}<div class="sm mut">Weights start from expert priors and move only as investigators substantiate or clear cases (MAP logistic update with a strong prior). Every change is recomputed from the decision log, so it is reproducible and auditable.</div></div>
    ${b.auc ? `<div class="card" style="margin-top:12px"><h3>Ranking power <small>synthetic labels · AUC</small></h3>${barsH(Object.entries(b.auc).map(([k, v]) => ({ label: k, value: v, color: k.startsWith("Nexus") ? "#1E2024" : k.startsWith("Rules") ? "#A0A4AB" : "#55595F" })), { fmt: v => v.toFixed(3), max: 1 })}</div>` : ""}</div></div>
    <div class="card" style="margin-top:12px"><h3>Highest Brain suspicion</h3><table><tr><th>Provider</th><th class="num">Brain</th><th class="num">Rule-based risk</th><th>What drives it</th><th>Case</th></tr>${b.top.map(t => `<tr class="click" data-go="provider/${t.provider_id}"><td><b>${esc(t.name)}</b><div class="sm mut">${FAM[t.family]}</div></td><td class="num"><b>${Math.round(t.brain * 100)}</b></td><td class="num">${Math.round(t.risk)}</td><td>${stackParts(t.parts)}</td><td>${t.case_id ? `<a href="#/case/${t.case_id}">${t.case_id}</a>` : '<span class="tag t-vio">no case</span>'}</td></tr>`).join("")}</table><div class="sm mut" style="margin-top:6px">${legendParts()}</div></div>`;
}
const PARTC = { rules: "#A0A4AB", iforest: "#6E727A", graph: "#3E4566", twin: "#D97706", path: "#55595F", drift: "#B4423C", mix: "#D9772B" };
const PARTL = { rules: "rules", iforest: "isolation forest", graph: "graph", twin: "case-mix twin", path: "care pathway", drift: "change-point", mix: "code mix" };
function stackParts(p) { const t = Object.values(p).reduce((a, b) => a + b, 0) || 1; return `<div class="stack" style="min-width:180px">${Object.entries(p).map(([k, v]) => `<i title="${PARTL[k]} ${v.toFixed(2)}" style="width:${v / t * 100}%;background:${PARTC[k]}"></i>`).join("")}</div>`; }
function legendParts() { return Object.entries(PARTL).map(([k, l]) => `<span style="margin-right:10px"><i style="display:inline-block;width:9px;height:9px;background:${PARTC[k]};border-radius:2px"></i> ${l}</span>`).join(""); }
/* ------------------------------------------------------------ data */
async function vData() {
  const [d, st, tpl] = await Promise.all([api("data"), api("status"), api("data/template")]); d.template = tpl; d.dataset = st.run?.dataset;
  const v = d.validation;
  return hdr("Data & pipeline", "Synthetic claims and related tables are loaded, validated and analysed end-to-end. Validation failures stop a run and the previous analysis stays live.",
    `<div class="card" style="padding:10px 14px"><div class="row"><label class="sm">Seed</label><input type="number" id="seed" value="7" style="width:80px"><label class="sm">Members</label><input type="number" id="mem" value="2500" step="500" min="500" max="6000" style="width:90px"><button class="btn pri" id="rerun" ${st.state === "running" ? "disabled" : ""}>${st.state === "running" ? "Running…" : "Regenerate + re-run"}</button></div></div>`) +
    `<div class="grid g2"><div class="card"><h3>Validation <small>${v.errors.length} errors · ${v.warnings.length} warnings</small></h3>${v.checks.map(c => `<div class="row" style="padding:5px 0;border-bottom:1px solid #eef1f6"><span class="tag ${c.status === "pass" ? "t-ok" : c.status === "warn" ? "t-high" : "t-crit"}">${c.status}</span><b class="sm">${esc(c.name)}</b><span class="sp"></span><span class="sm mut">${esc(c.detail)}</span></div>`).join("")}</div>
    <div class="card"><h3>Pipeline run <small>${d.log.length ? d.log[d.log.length - 1].seconds + "s total" : ""}</small></h3>${d.log.map(l => `<div style="padding:5px 0;border-bottom:1px solid #eef1f6"><b class="sm">${esc(l.step)}</b> <span class="mut sm">+${l.seconds}s</span><div class="sm mut">${esc(l.detail)}</div></div>`).join("")}</div></div>
    ${S.perms.includes("run_models") ? `<div class="card" style="margin-top:14px"><h3>Load synthetic data <small>synthetic files only — never upload real member, provider or claims data · dataset in use: ${esc(d.dataset || "synthetic")}</small></h3><div class="grid g2"><div><div class="sm">Upload CSVs named after the tables. Required: <span class="mono">claim_lines.csv</span>, <span class="mono">providers.csv</span>, <span class="mono">members.csv</span>. Optional: referrals, relationships, investigations, inpatient_stays, facilities. Files are validated before anything runs; a failed run keeps the current analysis live.</div><input type="file" id="upf" multiple accept=".csv,.837,.edi,.x12,.txt" style="margin-top:10px"><div class="sm mut" style="margin-top:6px">Also accepts X12 837 claim files (professional 837P and institutional 837I). Sample files: <a href="/api/data/sample.837?kind=P">837P</a> · <a href="/api/data/sample.837?kind=I">837I</a></div><div class="row" style="margin-top:10px"><button class="btn pri" id="upgo">Validate &amp; analyse</button><button class="btn" id="usesyn">Switch to synthetic demo</button></div></div><div class="sm"><b>Required columns</b>${Object.entries(d.template.required).map(([k, v]) => `<div class="ex"><span class="mono">${k}.csv</span>: ${v.join(", ")}</div>`).join("")}${d.template.notes.map(n => `<div class="sm mut">• ${esc(n)}</div>`).join("")}</div></div></div>` : ""}
    <div class="card" style="margin-top:14px"><h3>Tables</h3><div class="grid g3">${d.tables.map(t => `<div style="border:1px solid var(--line);border-radius:10px;padding:10px"><b>${t.name}</b> <span class="mut sm">${num(t.rows)} rows</span><div class="sm mut" style="margin:4px 0;word-break:break-word">${t.columns.join(" · ")}</div></div>`).join("")}</div></div>
    <div class="card" style="margin-top:14px"><h3>Code reference <small>public billing-code identifiers with invented prices</small></h3><div style="max-height:260px;overflow:auto"><table><tr><th>Code</th><th>Family</th><th>Description</th><th class="num">Base price</th></tr>${d.codes.map(c => `<tr><td class="mono">${c.code}</td><td>${FAM[c.family]}</td><td>${esc(c.description)}</td><td class="num">${money(c.price)}</td></tr>`).join("")}</table></div></div>`;
}

/* ------------------------------------------------------------ governance */
function validationCard(v) {
  if (!v || !v.generated) return "";
  const row = (l, x) => `<tr><td class="sm">${l}</td><td class="num sm">${x}</td></tr>`;
  const t = (v.truth || []).map(d => `<tr><td class="sm">${esc(d.dataset)}</td><td class="num sm">${d.provider_detectors.p_fraud ? d.provider_detectors.p_fraud.auc.toFixed(3) + " / " + d.provider_detectors.p_fraud.ap.toFixed(3) : "–"}</td><td class="num sm">${pc(d.queue["@10"].precision || 0)} / ${pc(d.queue["@10"].recall)}</td><td class="num sm">${(v.calibration || []).find(c => c.dataset === d.dataset)?.ece ?? "–"}</td><td class="num sm">${(v.gap?.datasets?.[d.dataset]?.ood_rate ?? 0) * 100 | 0}%</td></tr>`).join("");
  const cf = v.counterfactual ? Object.entries(v.counterfactual.summary).map(([k, x]) => row(esc(k.replace(/_/g, " ")), `${x.passed}/${x.total}`)).join("") : "";
  const adv = (v.adversarial || []).map(x => row(esc(x.attack), `${x.detected}/${x.of}`)).join("");
  const ab = v.ablation ? Object.entries(v.ablation.total_caught).map(([k, c]) => row(esc(k) + (k === v.ablation.chosen ? " ✓" : ""), `${c} caught · ${v.ablation.total_false_leads[k]} false leads · AP ${v.ablation.mean_brain_ap[k]}`)).join("") : "";
  return `<div class="card" style="margin-top:14px"><h3>Model validation <small>backend evaluation engine · ${esc(v.generated)} · hidden ground truth used only here</small></h3>
    <div class="grid g2"><div><b class="sm">Ground truth, calibration, distribution shift</b><table><tr><th>Dataset</th><th class="num">p_fraud AUC / AP</th><th class="num">Queue P / R @10</th><th class="num">ECE</th><th class="num">OOD</th></tr>${t}</table>
    ${v.delay ? `<div class="sm" style="margin-top:8px">Detection delay (rolling as-of replays): median <b>${v.delay.median_days_to_case ?? "–"} days</b> from scheme start to case; early-warning stage after <b>${v.delay.median_days_to_early_warning ?? "–"} days</b>.</div>` : ""}
    ${v.quality ? `<div class="sm" style="margin-top:6px">Corrupted-data test: confidence never High: <b>${v.quality.confidence_never_high ? "yes" : "no"}</b>; data quality dropped: <b>${v.quality.dq_dropped ? "yes" : "no"}</b>; innocent risk inflated: <b>${v.quality.legit_risk_inflated}</b>.</div>` : ""}</div>
    <div>${cf ? `<b class="sm">Counterfactual tests (score moves the expected way) · ${pc(v.counterfactual.pass_rate)}</b><table>${cf}</table>` : ""}${adv ? `<b class="sm" style="display:block;margin-top:8px">Adversarial evasion</b><table>${adv}</table>` : ""}${ab ? `<b class="sm" style="display:block;margin-top:8px">Detector ablation (all datasets)</b><table>${ab}</table>` : ""}</div></div>
    ${byTypeTable(v.truth || [])}
    <div class="sm mut" style="margin-top:8px">Run <span class="mono">python3 -m evaluation.engine</span>. Details in EVALUATION.md.</div></div>`;
}
function byTypeTable(truth) {
  const fams = {};
  truth.forEach(d => Object.entries(d.by_provider_type || {}).forEach(([f, x]) => {
    const a = fams[f] || (fams[f] = { providers: 0, fraud: 0, caught: 0, legit: 0, fp: 0, auc: [] });
    a.providers += x.providers; a.fraud += x.fraudulent; a.caught += x.caught; a.legit += x.legitimate; a.fp += x.false_positives; if (x.auc != null) a.auc.push(x.auc);
  }));
  const rows = Object.entries(fams);
  if (!rows.length) return "";
  return `<b class="sm" style="display:block;margin-top:12px">Performance by provider type (all ${truth.length} test worlds)</b>
    <table><tr><th>Type</th><th class="num">Providers</th><th class="num">Fraud caught</th><th class="num">False positives</th><th class="num">p_fraud AUC (min–max)</th></tr>
    ${rows.map(([f, a]) => `<tr><td class="sm b">${esc(FAM[f] || f)}</td><td class="num sm">${a.providers}</td><td class="num sm">${a.caught} / ${a.fraud}</td><td class="num sm">${a.fp} / ${a.legit}</td><td class="num sm"${a.auc.length && Math.min(...a.auc) < 0.9 ? ' style="color:var(--amber)"' : ""}>${a.auc.length ? Math.min(...a.auc).toFixed(2) + "–" + Math.max(...a.auc).toFixed(2) : "–"}</td></tr>`).join("")}</table>
    <div class="sm mut">Fraudulent providers per type are few (1–4 per world), so per-type figures are noisy; the weakest ranking is highlighted.</div>`;
}
function modelsCard(mdl) {
  const fmt = v => typeof v === "number" ? (Math.abs(v) <= 1 && !Number.isInteger(v) ? v.toFixed(3) : num(v)) : esc(String(v));
  const llm = mdl.llm || {};
  return `<div class="card" style="margin-top:14px"><h3>Task models <small>trained in-house on synthetic training worlds · each tested on data it never saw</small></h3>
    <div class="sm" style="margin-bottom:10px">LLM: ${llm.available ? `<b>${esc(llm.provider)} · ${esc(llm.model)}</b> — used for chart review, tip structuring and rule drafting; every output is schema-checked and quote-verified.` : "<b>not configured</b> — chart review and tip triage run on the trained models below; rule drafting is unavailable. An admin can switch one on under Settings → AI &amp; LLM."}</div>
    ${mdl.models.length ? `<div class="grid g2">${mdl.models.map(m => `<div style="border:1px solid var(--line);border-radius:8px;padding:12px"><div class="row"><b>${esc(m.task)}</b><span class="sp"></span><span class="sm mut mono">${esc(m.sha256)}</span></div>
      <div class="sm mut" style="margin:4px 0">${esc(m.kind)}<br>Process: ${esc(m.process)}<br>Trained on ${esc(m.trained_on)} · ${m.trained}</div>
      <table>${Object.entries(m.held_out || {}).map(([k, v]) => typeof v === "object" ? `<tr><td colspan="2" class="sm b" style="padding-top:6px">${esc(k)}</td></tr>${Object.entries(v).map(([k2, v2]) => `<tr><td class="sm">${esc(k2.replace(/_/g, " "))}</td><td class="num sm">${fmt(v2)}</td></tr>`).join("")}` : `<tr><td class="sm">${esc(k.replace(/_/g, " "))}</td><td class="num sm">${fmt(v)}</td></tr>`).join("")}</table>
      <div class="sm" style="margin-top:6px">${esc(m.use)}</div><ul class="sm mut" style="margin:4px 0 0;padding-left:16px">${(m.limitations || []).map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>`).join("")}</div>` : '<div class="mut sm">No task models trained yet. Run <span class="mono">python3 -m ai.models.train_all</span>.</div>'}</div>`;
}
function forecastVsBaseline(fm) {
  const H = [30, 60, 90].filter(h => fm[h] && fm[h].baseline);
  if (!H.length) return "";
  const f = v => v == null ? "–" : v.toFixed(3), ci = c => c ? `<span class="mut">[${c[0].toFixed(2)}–${c[1].toFixed(2)}]</span>` : "";
  const d = fm[H[0]].ci95?.delta_ap || [0, 0], sig = d[0] > 0, no = fm[H[0]].new_onset || {};
  const verdict = sig ? `The forecast adds statistically significant value over the baseline (PR-AUC gain ${d[0].toFixed(2)}–${d[1].toFixed(2)}).`
    : `The forecast scores above the baseline, but the 95% interval of the gain includes zero (PR-AUC ${d[0].toFixed(2)} to +${d[1].toFixed(2)}), so the edge is not proven. For previously unflagged providers the signal is weak (${no.positives} new-onset positives in ${no.rows}). The forecast is therefore a secondary priority signal; detection evidence carries each case.`;
  return `<div class="card" style="margin-top:14px"><h3>Forecast vs recent-flag baseline <small>temporal holdout · trained before the cutoff, tested on a later untouched window · ${fm[H[0]].bootstrap?.resamples || ""} provider-cluster bootstrap resamples</small></h3>
    <div class="banner ${sig ? "green" : "blue"}" style="margin-bottom:10px">${verdict}</div>
    <table><tr><th>Horizon</th><th class="num">Model ROC-AUC</th><th class="num">Baseline ROC-AUC</th><th class="num">Model PR-AUC</th><th class="num">Baseline PR-AUC</th><th class="num">Precision @ ${fm[H[0]].capacity_k} (model / baseline)</th><th class="num">Brier · ECE</th><th class="num">New-onset ROC / PR-AUC</th></tr>
    ${H.map(h => { const m = fm[h], b = m.baseline, n = m.new_onset || {}; return `<tr><td><b>${h} days</b></td><td class="num">${f(m.auc)} ${ci(m.ci95?.auc)}</td><td class="num">${f(b.auc)}</td><td class="num">${f(m.ap)} ${ci(m.ci95?.ap)}</td><td class="num">${f(b.ap)}</td><td class="num">${f(m.p_at_k)} / ${f(b.p_at_k)}</td><td class="num">${f(m.brier)} · ${f(m.ece)}</td><td class="num">${f(n.auc)} / ${f(n.ap)} <span class="mut">(${n.positives}/${n.rows})</span></td></tr>`; }).join("")}</table>
    <div class="sm mut" style="margin-top:8px">Baseline = recent-flag persistence: the share of a provider's last-90-day lines flagged by rules at the forecast date. New-onset = providers with no rule flags in that window.</div></div>`;
}
function chainCard(ch) {
  if (!ch) return "";
  const ok = ch.ok;
  return `<div class="card" style="margin-top:14px"><h3>Tamper-evident audit chain <small>SHA-256 hash chain over every audit entry · hashed policy</small></h3>
    <div class="row wrap" style="gap:14px"><span class="tag ${ok ? "t-ok" : "t-crit"}" style="font-size:14px">${ok ? "✓ Chain verified" : "Tampering detected"}</span>
    <span class="sm"><b>${num(ch.entries)}</b> sealed entries</span>${ok ? `<span class="sm mono">head ${esc((ch.head || "").slice(0, 16))}…</span>` : `<span class="sm" style="color:var(--red)">entry #${ch.first_bad.audit_id}: ${esc(ch.first_bad.reason)}</span>`}
    <span class="sm">policy <b class="mono">${esc(ch.policy.version)}</b></span><span class="sp"></span><button class="btn sm" id="verifychain">Verify now</button></div>
    <div class="sm mut" style="margin-top:8px">Each entry's hash covers the previous hash, the row and the policy version, so editing, deleting or re-ordering any past entry is detected and named. Refused actions (e.g. an analyst attempting a decision) are logged too.</div></div>`;
}

async function vGovernance() {
  const [g, a, mdl, vl, ch] = await Promise.all([api("governance"), api("audit"), api("models"), api("validation"), api("audit/verify")]);
  const ev = g.run.evaluation || {}, fm = g.forecast.metrics || {};
  if (!ev.total_lines) ev.note = "This dataset has no evaluation labels, so accuracy cannot be measured here.";
  return hdr("Governance & responsible AI", "How the system keeps humans in control, shows uncertainty, and fails safely.") +
    `<div class="grid g2"><div class="card"><h3>Principles in the product</h3><ul style="margin:0;padding-left:18px">${g.principles.map(p => `<li style="margin-bottom:6px">${esc(p)}</li>`).join("")}</ul></div>
    <div class="card"><h3>Known limitations</h3><ul style="margin:0;padding-left:18px">${g.limitations.map(p => `<li style="margin-bottom:6px">${esc(p)}</li>`).join("")}</ul>
    <h3 style="margin-top:14px">Synthetic self-evaluation</h3><div class="sm">${ev.note}</div><table><tr><td>Line-level precision / recall</td><td class="num">${pc(ev.line_precision)} / ${pc(ev.line_recall)}</td></tr><tr><td>Raw alerts → cases</td><td class="num">${num(ev.raw_flagged_lines)} → ${ev.cases}</td></tr><tr><td>Precision@5 / @10 of case queue</td><td class="num">${pc(ev.precision_at_5)} / ${pc(ev.precision_at_10)}</td></tr><tr><td>Seeded bad-actor provider recall</td><td class="num">${pc(ev.provider_recall)}</td></tr><tr><td>Benign providers surfaced as cases (decoys)</td><td class="num">${(ev.decoys_in_cases || []).length}</td></tr></table></div></div>
    ${modelsCard(mdl)}${validationCard(vl)}
    <div class="card" style="margin-top:14px"><h3>Forecast model card <small>discrete-time hazard · P60 = 1-(1-h1)(1-h2) · horizons can never contradict</small></h3><div class="sm" style="margin-bottom:8px">Chosen model (frozen rule: lower training-period log loss): <b>${g.run.model_choice.chosen}</b>.${g.run.model_choice.reason ? ` <span class="tag t-high">${esc(g.run.model_choice.reason)}</span>` : ""} Trained on anchors through ${g.run.model_choice.cut} (${g.run.model_choice.train_anchors} anchors); purged 90 days; tested on ${g.run.model_choice.eval_anchors} later anchors from ${g.run.model_choice.eval_from}. Sigmoid calibration cross-fitted by provider group on the training period only. Production bundle refit on all fully observed history with frozen hyper-parameters.</div><div class="grid g3">${[30, 60, 90].map(h => { const m = fm[h]; return m ? `<div><b>${h}-day</b> <span class="mut sm">(${m.positives} positive / ${m.test_rows} test rows)</span><table><tr><th></th><th class="num">Logistic</th><th class="num">Boosting</th></tr><tr><td>AUC</td><td class="num">${m.logistic.auc.toFixed(3)}</td><td class="num">${m.gboost.auc.toFixed(3)}</td></tr><tr><td>Avg precision</td><td class="num">${m.logistic.ap.toFixed(3)}</td><td class="num">${m.gboost.ap.toFixed(3)}</td></tr><tr><td>Brier</td><td class="num">${m.logistic.brier.toFixed(3)}</td><td class="num">${m.gboost.brier.toFixed(3)}</td></tr><tr><td>Calibration error</td><td class="num">${m.logistic.ece.toFixed(3)}</td><td class="num">${m.gboost.ece.toFixed(3)}</td></tr><tr><td>Flag-rate baseline AUC</td><td class="num" colspan="2">${m.baseline_auc_flag_share.toFixed(3)}</td></tr></table>${reliability(g.forecast.calibration[h] || [])}</div>` : ""; }).join("")}</div>
    <div class="sm mut">Synthetic data is easy; expect far lower real-world performance. Probabilities are capped to 1–97% to avoid false certainty.</div></div>
    ${forecastVsBaseline(fm)}${chainCard(ch)}
    <div class="card" style="margin-top:14px"><h3>SpotZ Sentinel <small>in-house learned detectors · no rules, no labels</small></h3><div class="grid g2"><div class="sm"><p style="margin-top:0"><b>Case-mix twin.</b> Gradient-boosted model of what each provider's own patients would normally cost (age, plan, diagnosis profile, utilisation elsewhere, service family). Cross-fitted by provider groups so a provider never shapes its own expectation; small panels shrunk toward "explained". Fit R² ${(g.run.sentinel_fit || {}).r2_paid?.toFixed(2)} (paid), ${(g.run.sentinel_fit || {}).r2_lines?.toFixed(2)} (lines) on ${num((g.run.sentinel_fit || {}).rows)} provider–member pairs.</p><p><b>Care-pathway model.</b> Back-off sequence model of member journeys: next service given previous service, time gap, inside-inpatient-stay and after-coverage-end context. Counts are leave-provider-out, so a ring billing the same odd pattern cannot make it look normal.</p></div>
    <div><b class="sm">Ranking power per detector (synthetic labels, AUC)</b>${barsH(Object.entries(ev.detector_auc || {}).map(([k, v]) => ({ label: k, value: v, color: k.startsWith("Sentinel") ? "#55595F" : k === "Combined risk" ? "#1E2024" : "#A0A4AB" })), { fmt: v => v.toFixed(3), max: 1 })}<div class="sm mut">The synthetic scenarios were written with rules in mind, so rules look near-perfect here. Sentinel's value is that it reaches 0.84 without knowing any rule — it is the detector most likely to generalise to schemes nobody wrote a rule for.</div></div></div></div>
    <div class="card" style="margin-top:14px"><h3>Rule catalogue <small>${g.run.ruleset}</small></h3><div style="overflow:auto"><table><tr><th>Rule</th><th>What it detects</th><th>Benign explanations considered</th><th>Check that distinguishes</th></tr>${g.rules.map(r => `<tr><td><b>${r.name}</b><div class="mono mut">${r.key}</div></td><td class="sm">${esc(r.desc)}</td><td class="sm">${r.benign.map(esc).join("<br>")}</td><td class="sm">${esc(r.check)}</td></tr>`).join("")}</table></div></div>
    <div class="grid g2" style="margin-top:14px"><div class="card"><h3>Decision log</h3>${a.decisions.length ? a.decisions.map(x => `<div class="sm" style="padding:5px 0;border-bottom:1px solid #eef1f6"><b>${x.case_id}</b> ${esc(x.outcome)} <span class="mut">· ${esc(x.reviewer)} (${x.role}) · ${x.ts}</span><br>${esc(x.reason)}</div>`).join("") : '<div class="mut">No decisions recorded yet.</div>'}</div>
    <div class="card"><h3>Audit trail</h3><div style="max-height:360px;overflow:auto">${a.audit.map(x => `<div class="sm" style="padding:4px 0;border-bottom:1px solid #eef1f6"><span class="mut">${x.ts}</span> <b>${esc(x.actor)}</b> ${esc(x.action)} ${esc(x.target)}</div>`).join("") || '<div class="mut">Empty.</div>'}</div></div></div>`;
}

/* ------------------------------------------------------------ context panel, search, quick create */
async function ctxFill() {
  const el = $("#ctxb"); if (!el) return;
  try {
    const q = S.queue || await loadQueue(); const rows = q.queue;
    if (S.view === "queue" || S.view === "case") {
      const cid = S.view === "case" ? S.arg : (UI.sel || rows[0]?.case_id); const r = rows.find(x => x.case_id === cid);
      if (!r) { el.innerHTML = '<div class="sm mut">Select a case to see its focus.</div>'; return; }
      const p = await api(`cases/${cid}/plan`).catch(() => null);
      const steps = (p?.plan?.steps || []).slice(0, 4);
      el.innerHTML = `<div class="cfh"><span class="fav">${esc(initials(r.title.replace(/\+.*$/, "")))}</span><div><span class="mono mut">${r.case_id}</span><b>${esc(r.title)}</b><span class="mut sm">${esc(r.type)}</span></div></div>
      <div class="grid g2" style="gap:10px;margin:14px 0"><div class="mini"><span>Exposure</span><b>${money(r.exposure)}</b></div><div class="mini"><span>Risk</span><b>${Math.round(r.risk)}</b></div><div class="mini"><span>Priority</span><b>${Math.round(r.priority)}</b></div><div class="mini"><span>Readiness</span><b>${p ? p.score + "%" : "–"}</b></div></div>
      <div class="ctxl">Case status</div><div class="pill-row">${laneTag(r.lane)}${statusTag(r.status)}</div>
      ${steps.length ? `<div class="ctxl" style="margin-top:16px">Next steps</div><div class="nsteps">${steps.map(x => `<div class="${x.status === "done" ? "done" : ""}">${ico(x.status === "done" ? "checkc" : "clock", 15)}<span>${esc(x.title)}</span></div>`).join("")}</div>` : ""}
      ${S.view === "queue" ? `<button class="btn pri" style="width:100%;justify-content:center;margin-top:16px" data-go="case/${cid}">${ico("chevr", 15)}Open case</button>` : `<button class="btn" style="width:100%;justify-content:center;margin-top:16px" data-go="case/${cid}/plan">Open action plan</button>`}`;
      return;
    }
    const my = await api("my").catch(() => null); S.unread = my ? my.notifications.filter(n => !n.read).length : S.unread;
    const t0 = new Date().toISOString().slice(0, 10), mine = (my?.mine || []).filter(r => r.status !== "Closed");
    const due = mine.filter(r => r.due && r.due <= t0), over = mine.filter(r => r.overdue);
    const top = rows.filter(r => r.status !== "Closed").slice(0, 4);
    const appr = my?.approvals?.length || 0;
    el.innerHTML = `<div class="dcard"><span class="dn">${due.length + appr}</span><div><b>${appr ? "Due & approvals" : "Deadlines today"}</b><span>${due.length ? `${due.length} case${due.length === 1 ? "" : "s"} due${over.length ? ` · ${over.length} overdue` : ""}` : "Nothing due today"}${appr ? ` · ${appr} referral approval${appr === 1 ? "" : "s"} waiting` : ""}</span></div></div>
    <div class="ctxl" style="margin-top:20px">Highest priority</div>${top.map(r => `<button class="hp" data-go="case/${r.case_id}"><div><b>${esc(r.title)}</b><span>${r.case_id} · ${r.capacity === "within" ? "scheduled" : esc(r.lane)}</span></div>${riskNum(r.risk)}</button>`).join("")}
    <div class="qins"><b>${ico("spark", 14)}Queue insight</b><span>${rows.filter(r => r.escalating).length ? `${rows.filter(r => r.escalating).length} case(s) are escalating. ` : ""}${rows.filter(r => r.lane !== "Investigate").length} case(s) were routed away from investigation because legitimate context or weak evidence was found.</span></div>`;
  } catch (e) { el.innerHTML = `<div class="sm mut">${esc(e.message)}</div>`; }
}
async function gSearch(v) {
  const box = $("#gres"); if (!box) return; const q = v.trim().toLowerCase(); UI.gq = v;
  if (!q) { box.innerHTML = ""; return; }
  const rows = (S.queue || await loadQueue()).queue.filter(r => `${r.case_id} ${r.title} ${r.type}`.toLowerCase().includes(q)).slice(0, 5);
  let ents = []; try { ents = q.length > 1 ? (await api("graph/search?q=" + encodeURIComponent(v.trim()))).slice(0, 6) : []; } catch { }
  if ($("#gq")?.value !== v) return;
  box.innerHTML = `<div class="gdrop">${rows.length ? `<div class="gh">Cases</div>${rows.map(r => `<button class="grow" data-go="case/${r.case_id}"><span class="mono">${r.case_id}</span><span class="gl">${esc(r.title)}</span>${riskNum(r.risk)}</button>`).join("")}` : ""}
  ${ents.length ? `<div class="gh">Providers, members &amp; entities</div>${ents.map(e => `<button class="grow" data-go="${e.type === "patient" ? `explorer/members?m=${encodeURIComponent(e.id)}` : /^P-\d+$/.test(e.id) ? `provider/${e.id}` : e.case_id ? `case/${e.case_id}` : "network"}">${typeIcon(e.type)}<span class="gl">${esc(e.label)}<em>${TLAB[e.type] || ""}${e.case_id ? " · " + e.case_id : ""}</em></span></button>`).join("")}` : ""}
  ${!rows.length && !ents.length ? `<div class="sm mut" style="padding:10px 12px">No match. Try a case ID (CS-0107), provider ID (P-0119) or member ID (M-00010).</div>` : ""}</div>`;
}
function newCaseModal() {
  const m = document.createElement("div"); m.className = "modal"; m.id = "ncm";
  m.innerHTML = `<div class="mbox" role="dialog" aria-modal="true" aria-labelledby="ncmt"><div class="mh"><span class="mk2">${ico("plus", 18)}</span><div><span class="eyebrow">Quick create</span><h2 id="ncmt">Open a new lead</h2><p>Log the essentials now. A supervisor triages it, and the analysis links it to a ranked case when the provider matches.</p></div><button class="iconbtn sm" id="ncx" aria-label="Close">${ico("x", 16)}</button></div>
  <form id="ncf"><div class="mbody grid g2" style="gap:6px 16px"><div><label class="f">Provider or organization</label><input type="text" id="nc_prov" placeholder="e.g. P-0119 or Northpoint Imaging"></div><div><label class="f">Member (optional)</label><input type="text" id="nc_mem" placeholder="e.g. M-00010"></div>
  <div style="grid-column:1/-1"><label class="f">Service category</label><input type="text" id="nc_svc" placeholder="e.g. Durable medical equipment"></div>
  <div><label class="f">Estimated exposure</label><input type="number" id="nc_exp" min="0" placeholder="42000"></div><div><label class="f">Source channel</label><select id="nc_ch">${["Hotline", "Member", "Employee", "Provider", "Law enforcement", "Other"].map(x => `<option>${x}</option>`).join("")}</select></div>
  <div style="grid-column:1/-1"><label class="f">What was reported</label><textarea id="nc_al" placeholder="What was reported, when, and why it looks wrong (no unnecessary personal details)"></textarea></div></div>
  <div class="mf"><span class="sm mut">Leads are allegations, not evidence.</span><span class="sp"></span><button type="button" class="btn" id="ncc">Cancel</button><button type="submit" class="btn pri">${ico("plus", 15)}Create lead</button></div></form></div>`;
  document.body.appendChild(m); setTimeout(() => $("#nc_prov")?.focus(), 30);
}
const closeModal = () => $("#ncm")?.remove();
document.addEventListener("keydown", e => { if (e.key === "Escape") { closeModal(); const b = $("#gres"); if (b) b.innerHTML = ""; } });
document.addEventListener("submit", async e => {
  if (e.target.id !== "ncf") return; e.preventDefault();
  const prov = $("#nc_prov").value.trim(), mem = $("#nc_mem").value.trim(), svc = $("#nc_svc").value.trim(), ex = $("#nc_exp").value, al = $("#nc_al").value.trim();
  const isId = /^P-\d+$/i.test(prov);
  const text = [al, svc && `Service: ${svc}.`, !isId && prov && `Provider named: ${prov}.`, mem && `Member: ${mem}.`, ex && `Estimated exposure: ${money(+ex)}.`].filter(Boolean).join(" ");
  try { const r = await post("tips", { channel: $("#nc_ch").value, subject_type: isId || !mem ? "provider" : "member", subject_id: isId ? prov.toUpperCase() : mem, allegation: text }); closeModal(); toast(`Lead #${r.id} created · sent to supervisor triage`); if (S.view === "tips") render(); }
  catch (err) { toast(err.message); }
});

/* ------------------------------------------------------------ events */
document.addEventListener("click", async e => {
  const t = e.target;
  const lpa = t.closest("#lpsign,#lpsign2,#lpwk,#lpwk2"); if (lpa) { e.preventDefault(); const tg = lpa.id.startsWith("lpsign") ? "#signin" : "#lpwork"; $(tg)?.scrollIntoView({ behavior: "smooth", block: "center" }); if (tg === "#signin") setTimeout(() => $("#lu")?.focus(), 350); return; }
  if (!t.closest(".gsearch")) { const b = $("#gres"); if (b) b.innerHTML = ""; }
  if (t.closest("#verifychain")) { toast("Re-verifying the audit chain…"); return render(); }
  if (t.closest("#sbtog")) { UI.sb = !UI.sb; localStorage.setItem("spotzi.sb", UI.sb ? "1" : "0"); $("#app").classList.toggle("sb-min", UI.sb); $("#sbtog").innerHTML = ico(UI.sb ? "chevr" : "chevl", 15); return; }
  const cx = t.closest("[data-ctx]"); if (cx) { UI.ctx[S.view] = cx.dataset.ctx === "1"; localStorage.setItem("spotzi.ctx", JSON.stringify(UI.ctx)); return render(); }
  if (t.closest("#newcase")) return newCaseModal();
  if (t.closest("#ncx") || t.closest("#ncc") || t.id === "ncm") return closeModal();
  const sr = t.closest("[data-sel]"); if (sr && !t.closest("a")) { if (!ctxOpen()) return go("/case/" + sr.dataset.sel); UI.sel = sr.dataset.sel; $$("tr[data-sel]").forEach(x => x.classList.toggle("sel", x === sr)); return ctxFill(); }
  if (t.closest("#actadd")) { const txt = $("#actnote").value; try { await post(`cases/${S.arg}/notes`, { text: txt }); toast("Note added"); } catch (err) { if (err.message.includes("member IDs") && confirm(err.message + " Save anyway?")) { await post(`cases/${S.arg}/notes`, { text: txt, confirm_member_ids: true }); } else return toast(err.message); } return render(); }
  const nav = t.closest("[data-nav]"); if (nav) return go("/" + nav.dataset.nav);
  const g = t.closest("[data-go]"); if (g) { if (g.closest("#gres")) UI.gq = ""; return go("/" + g.dataset.go); }
  const hz = t.closest("[data-hz]"); if (hz) { S.horizon = +hz.dataset.hz; return render(); }
  const ck = t.closest("[data-check]"); if (ck) { const c = S.cd.case_id, arr = S.checks[c] || (S.checks[c] = []), r = ck.dataset.check; const i = arr.indexOf(r); i >= 0 ? arr.splice(i, 1) : arr.push(r); return render(); }
  if (t.id === "genNarr") { const cid = S.cd.case_id; AI.busy = true; render(); try { AI.narr[cid] = await post(`cases/${cid}/narrative`, {}); } catch (err) { AI.narr[cid] = { error: err.message }; } AI.busy = false; return render(); }
  if (t.id === "askgo") return askCopilot($("#askq").value);
  const aq = t.closest("[data-ask]"); if (aq) return askCopilot(aq.dataset.ask);
  const rv = t.closest("[data-reveal]"); if (rv) { try { const r = await post(`cases/${S.cd.case_id}/lab/reveal`, { rule: rv.dataset.reveal, reviewer: S.reviewer }); toast("Revealed: " + r.outcome); } catch (err) { toast(err.message); } return render(); }
  if (t.id === "mkbp") { try { await post(`cases/${S.cd.case_id}/blueprint`, { reviewer: S.reviewer, acknowledged_differences: $("#bpack").checked }); toast("Blueprint created"); } catch (err) { toast(err.message); } return render(); }
  const bpc = t.closest("[data-bp]"); if (bpc && t.tagName === "INPUT") { await api("blueprint/items/" + bpc.dataset.bp, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ state: t.checked ? "done" : "todo", reviewer: S.reviewer }) }); return render(); }
  const sk = t.closest("[data-skip]"); if (sk) { const why = prompt("Reason for skipping this item (required):"); if (why) { try { await api("blueprint/items/" + sk.dataset.skip, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ state: "skipped", note: why, reviewer: S.reviewer }) }); } catch (err) { toast(err.message); } render(); } return; }
  const ab = t.closest("[data-addbp]"); if (ab) { try { await post(`blueprint/${ab.dataset.addbp}/items`, { text: $("#bpnew").value }); } catch (err) { toast(err.message); } return render(); }
  const wk = t.closest("[data-wiki]"); if (wk) { const rv = $("#wrv").value.trim(); if (rv) { S.reviewer = rv; localStorage.setItem("cs_reviewer", rv); } try { await post(`wiki/proposals/${wk.dataset.id}/review`, { action: wk.dataset.wiki, reviewer: rv, note: $("#wnote").value }); toast(wk.dataset.wiki === "approve" ? "Approved into knowledge" : "Rejected"); go("/knowledge"); } catch (err) { toast(err.message); } return; }
  if (t.id === "wclean") { try { const r = await post("wiki/proposals/approve-clean", { reviewer: S.reviewer }); toast(`Approved ${r.approved} page(s)`); } catch (err) { toast(err.message); } return render(); }
  if (t.closest("#logout")) { navigator.serviceWorker?.controller?.postMessage("clearCaches"); await post("logout", {}); S.user = null; location.hash = ""; return renderLogin(); }
  if (t.id === "noteadd") { try { await post(`cases/${S.arg}/notes`, { text: $("#notetxt").value }); } catch (err) { if (err.message.includes("member IDs") && confirm(err.message + " Save anyway?")) await post(`cases/${S.arg}/notes`, { text: $("#notetxt").value, confirm_member_ids: true }); else toast(err.message); } return loadNotes(S.arg); }
  const pq = t.closest("[data-pq]"); if (pq) { const why = prompt(`Reason to ${pq.dataset.pq} ${pq.dataset.id} as a precedent (10+ characters):`); if (!why) return; try { await post(`precedents/${pq.dataset.id}/quality`, { action: pq.dataset.pq, reason: why }); toast("Recorded"); } catch (err) { toast(err.message); } return render(); }
  const ua = t.closest("[data-uact]"); if (ua) { try { await api("users/" + ua.dataset.uact, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ active: ua.dataset.on === "1" }) }); } catch (err) { toast(err.message); } return render(); }
  const up = t.closest("[data-upw]"); if (up) { const pw = prompt("New password (10+ characters):"); if (!pw) return; try { await api("users/" + up.dataset.upw, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: pw }) }); toast("Password reset; user signed out"); } catch (err) { toast(err.message); } return; }
  if (t.id === "nu_go") { try { await post("users", { name: $("#nu_name").value, username: $("#nu_user").value, role: $("#nu_role").value, password: $("#nu_pw").value, email: $("#nu_email").value }); toast("User created"); } catch (err) { toast(err.message); } return render(); }
  if (t.id === "upgo") { const fs = $("#upf").files; if (!fs.length) return toast("Choose CSV files first"); const fd = new FormData(); [...fs].forEach(f => fd.append("files", f)); const r = await fetch("/api/data/upload", { method: "POST", body: fd }); const j = await r.json(); if (!r.ok) return toast(j.detail || "Upload failed"); toast("Validated" + (j.x12 ? ` · ${j.x12.map(x => `${x.kind} ${x.lines} lines`).join(", ")}` : "") + " · analysis running on " + j.workspace); return poll(); }
  if (t.id === "usesyn") { await post("data/use-synthetic", {}); toast("Switching to synthetic demo"); return poll(); }
  if (t.id === "printbtn") return window.print();
  if (t.id === "enrdone") return afterLogin();
  if (t.id === "updgo") { navigator.serviceWorker?.getRegistration().then(r => r && r.waiting ? r.waiting.postMessage("skipWaiting") : location.reload()); if (!navigator.serviceWorker) location.reload(); return; }
  if (t.id === "mfaon") return renderEnrol();
  if (t.id === "pwgo") { try { await post("me/password", { current: $("#pwc").value, new: $("#pwn").value }); toast("Password changed. Please sign in again."); S.user = null; return renderLogin(); } catch (err) { return toast(err.message); } }
  if (t.id === "pfgo") { try { await post("me/prefs", { email: $("#pfem").value, notify_email: $("#pfe").checked, notify_slack: $("#pfs").checked }); toast("Saved"); } catch (err) { toast(err.message); } return; }
  if (t.id === "secgo") { try { await post("security", { mfa_required_roles: $$(".mfarole").filter(x => x.checked).map(x => x.value) }); toast("Policy saved"); } catch (err) { toast(err.message); } return render(); }
  if (t.id === "obtest") { try { await post("outbox/test", {}); toast("Queued"); } catch (err) { toast(err.message); } setTimeout(render, 6000); return; }
  const um = t.closest("[data-umfa]"); if (um) { if (!confirm("Reset two-factor for this user? They will be signed out.")) return; try { await post(`users/${um.dataset.umfa}/mfa-reset`, {}); toast("Two-factor reset"); } catch (err) { toast(err.message); } return render(); }
  if (t.id === "splitgo") { const ps = $$(".splitp").filter(x => x.checked).map(x => x.value); try { const r = await post(`cases/${S.arg}/split`, { providers: ps, reason: $("#scopewhy").value }); toast("Split into " + r.new_case); S.queue = null; } catch (err) { return toast(err.message); } return render(); }
  if (t.id === "mergego") { try { await post(`cases/${S.arg}/merge`, { other: $("#mergeother").value, reason: $("#scopewhy").value }); toast("Merged"); S.queue = null; } catch (err) { return toast(err.message); } return render(); }
  const ud = t.closest("[data-undo]"); if (ud) { try { await post(`scope/${ud.dataset.undo}/undo`, {}); toast("Scope change undone"); S.queue = null; } catch (err) { return toast(err.message); } return render(); }
  const fb = t.closest("[data-focus]"); if (fb) { const cur = NET.focus; if (cur && cur !== fb.dataset.focus) { const lbl = $(".wbbar b")?.textContent || cur; NET.trail = NET.trail.filter(x => x.id !== cur).concat([{ id: cur, label: lbl }]); } NET.focus = fb.dataset.focus; NET.view = "investigate"; NET.limit = 24; if (S.view !== "network") return go("/network"); return render(); }
  const mo = t.closest("[data-more]"); if (mo) { NET.limit = mo.dataset.more === "1" ? NET.limit + 24 : 24; return render(); }
  const nv = t.closest("[data-netview]"); if (nv) { NET.view = nv.dataset.netview; return render(); }
  const nd = t.closest("[data-netdim]"); if (nd) { NET.dim = nd.dataset.netdim; try { localStorage.setItem("spotzi.netdim", NET.dim); } catch (e) { } return render(); }
  const pa = t.closest("[data-patha]"); if (pa) {
    const idx = pa.dataset.patha;
    if (!NET.pathA) { NET.pathA = { id: idx, label: $(".wbinspect .b")?.textContent || idx }; toast("Now click another entity (or search one) and choose “Connect to …”"); return wbInspect(idx); }
    if (NET.pathA.id === idx) { NET.pathA = null; return wbInspect(idx); }
    const r = await api(`graph/path?a=${encodeURIComponent(NET.pathA.id)}&b=${encodeURIComponent(idx)}`);
    const box = $("#wbpath"); const KL = { billed: "billed claims for", referred: "referred to", admitted: "was admitted to", owned_by: "is owned by", located_at: "is located at", paid_to_account: "is paid into", primary_care: "is the primary-care physician of", practices_at: "practises at" };
    box.innerHTML = `<div class="wbh">How they connect</div>` + (r.found ? `<div class="wbpath">${r.steps.map(x => `<div><b>${esc(x.a)}</b> <span class="mut">${x.kind === "billed" && x.a_id.startsWith("M-") ? "was billed by" : x.kind === "admitted" && !x.a_id.startsWith("M-") ? "admitted" : KL[x.kind] || x.kind}</span> <b>${esc(x.b)}</b></div>`).join("")}</div><div class="sm mut">${r.length} step(s). A connection is a lead to check, not evidence of wrongdoing.</div>` : `<div class="sm mut">${esc(r.note || "No connection found.")}</div>`);
    if (r.found) GRAPHS.lg?.highlightPath?.(r.ids);
    NET.pathA = null; return;
  }
  const pe = t.closest("[data-ppex]"); if (pe) { PP.claim = PP.ex[+pe.dataset.ppex].claim; PP.result = null; return render(); }
  if (t.id === "ppadd") { PP.claim = readClaim(); PP.claim.lines.push({ code: "", units: 1 }); return render(); }
  const prm = t.closest("[data-pprm]"); if (prm) { PP.claim = readClaim(); PP.claim.lines.splice(+prm.dataset.pprm, 1); return render(); }
  if (t.id === "ppgo") { PP.claim = readClaim(); try { PP.result = await post("prepay/score", PP.claim); } catch (err) { return toast(err.message); } return render(); }
  const prs = t.closest("[data-ppres]"); if (prs) { const note = prompt(`${prs.dataset.r}: reason (required)`); if (!note) return; try { const r = await post(`prepay/${prs.dataset.ppres}/resolve`, { resolution: prs.dataset.r, note }); toast(r.avoided ? `Recorded · avoided ${money(r.avoided)}` : "Released"); } catch (err) { toast(err.message); } return render(); }
  if (t.id === "tpgo") { try { const r = await post("tips", { channel: $("#tp_ch").value, subject_type: $("#tp_st").value, subject_id: $("#tp_id").value, allegation: $("#tp_al").value }); toast(`Tip #${r.id} logged`); } catch (err) { toast(err.message); } return render(); }
  const tp = t.closest("[data-tip]"); if (tp) { const act = tp.dataset.act2; let cid = tp.dataset.case || null; if (act === "link" && !cid) { cid = prompt("Case ID to link (e.g. CS-0107):"); if (!cid) return; } const note = prompt("Triage note (required):", act === "link" ? "Consistent with the case pattern" : ""); if (!note) return; try { await post(`tips/${tp.dataset.tip}/triage`, { action: act, case_id: cid, note }); toast("Triaged"); } catch (err) { toast(err.message); } return render(); }
  if (t.id === "rsadd") { RS.conds = readConds(); RS.name = $("#rs_name").value; RS.conds.push({ field: "code", op: "=", value: "" }); return render(); }
  const rrm = t.closest("[data-rsrm]"); if (rrm) { RS.conds = readConds(); RS.name = $("#rs_name").value; RS.conds.splice(+rrm.dataset.rsrm, 1); return render(); }
  if (t.id === "dl_save") {
    const body = { email_enabled: $("#dl_em").checked, smtp_host: $("#dl_host").value, smtp_port: +$("#dl_port").value, smtp_security: $("#dl_sec").value, smtp_user: $("#dl_user").value,
      smtp_from: $("#dl_from").value, slack_enabled: $("#dl_sl").checked, base_url: $("#dl_base").value };
    if ($("#dl_pw").value) body.smtp_password = $("#dl_pw").value;
    if ($("#dl_hook").value) body.slack_webhook = $("#dl_hook").value;
    try { await api("settings/delivery", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); toast("Delivery settings saved"); } catch (err) { toast(err.message); } return render();
  }
  if (t.id === "dl_inbox") { try { await post("settings/delivery/test-inbox", {}); toast("Email and Slack now go to the local test inbox"); } catch (err) { toast(err.message); } return render(); }
  const dlt = t.closest("[data-dltest]"); if (dlt) { $("#dl_res").textContent = "Sending…"; try { const r = await post("settings/delivery/test", { channel: dlt.dataset.dltest, to: $("#dl_to").value }); $("#dl_res").textContent = r.ok ? `Test ${dlt.dataset.dltest} sent` : r.error; if (r.ok) setTimeout(render, 600); } catch (err) { $("#dl_res").textContent = err.message; } return; }
  if (t.id === "ll_save" || t.id === "ll_clear") {
    const body = { enabled: $("#ll_on").checked, provider: $("#ll_pv").value, model: $("#ll_md").value, base_url: $("#ll_url").value, features: Object.fromEntries($$(".ll_f").map(x => [x.value, x.checked])) };
    if (t.id === "ll_clear") { if (!confirm("Remove the saved API key?")) return; body.clear_key = true; } else if ($("#ll_key").value) body.api_key = $("#ll_key").value;
    try { await api("settings/llm", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); toast("AI settings saved"); } catch (err) { toast(err.message); } return render();
  }
  if (t.id === "ll_test") { $("#ll_res").textContent = "Testing…"; try { const r = await post("settings/llm/test", {}); $("#ll_res").textContent = r.ok ? `OK · ${r.provider} · ${r.model} · ${r.latency_ms} ms` : r.error; } catch (err) { $("#ll_res").textContent = err.message; } return; }
  if (t.id === "rsdraft") { RS.nl = $("#rs_nl").value; t.disabled = true; try { const r = await post("rules/draft", { text: RS.nl }); if (r.ok) { RS.conds = r.conditions; RS.name = r.name; RS.preview = null; RS.draftMsg = `Drafted by ${r.model}. ${r.rejected.length ? r.rejected.length + " invalid condition(s) discarded. " : ""}${r.unsupported ? "Not expressible: " + r.unsupported + ". " : ""}${r.note}`; } else RS.draftMsg = r.error || r.unsupported || "Could not draft a rule from that description."; } catch (err) { toast(err.message); } return render(); }
  if (t.id === "crgo") { t.disabled = true; t.textContent = "Reviewing charts…"; try { await post(`cases/${S.arg}/chart-review`, { n: +$("#cr_n").value || 8, use_llm: $("#cr_llm") ? $("#cr_llm").checked : false }); } catch (err) { toast(err.message); } return render(); }
  if (t.id === "rsprev") { RS.conds = readConds(); RS.name = $("#rs_name").value; try { RS.preview = await post("rules/preview", { conditions: RS.conds }); } catch (err) { return toast(err.message); } return render(); }
  if (t.id === "rssave") { RS.conds = readConds(); RS.name = $("#rs_name").value; try { await post("rules/custom", { name: RS.name, conditions: RS.conds }); toast("Saved as draft — activate it below"); RS.preview = null; RS.name = ""; } catch (err) { return toast(err.message); } return render(); }
  const rtg = t.closest("[data-rstog]"); if (rtg) { try { await post(`rules/custom/${rtg.dataset.rstog}/toggle`, {}); } catch (err) { toast(err.message); } return render(); }
  if (t.id === "rsapply") { try { await post("rules/apply", {}); toast("Re-running analysis with active rules…"); poll(); } catch (err) { toast(err.message); } return; }
  if (t.id === "rcgo") { try { await post(`cases/${S.arg}/recovery`, { stage: $("#rc_st").value, identified: $("#rc_id").value, recovered: $("#rc_rv").value, note: $("#rc_note").value }); toast("Recovery updated"); } catch (err) { toast(err.message); } return recCard(S.arg); }
  if (t.id === "docgo") { const fs = $("#docf").files; if (!fs.length) return toast("Choose files"); const fd = new FormData(); [...fs].forEach(f => fd.append("files", f)); const r = await fetch(`/api/cases/${S.arg}/documents`, { method: "POST", body: fd, headers: { "X-SpotZi-Contract": CONTRACT } }); const j = await r.json(); if (!r.ok) return toast(j.detail || "Upload failed"); toast(`Uploaded ${j.files.length} file(s)`); return docCard(S.arg); }
  if (t.id === "wreset") { S.weights = null; return render(); }
  if (t.id === "submitDec") {
    const body = { outcome: $("#outcome").value, reason: $("#reason").value, checks: S.checks[S.cd.case_id] || [] };
    try { const r = await post(`cases/${S.cd.case_id}/decision`, body); toast("Recorded · status: " + r.status); render(); }
    catch (err) {
      if (/readiness/i.test(err.message) && confirm(err.message + "\n\nRefer anyway? The gaps will be recorded with your decision.")) {
        try { const r = await post(`cases/${S.cd.case_id}/decision`, { ...body, acknowledge_gaps: true }); toast("Recorded · status: " + r.status); render(); } catch (e2) { toast(e2.message); }
      } else toast(err.message);
    }
  }
  const pst = t.closest("[data-pstep]"); if (pst) {
    const st = pst.dataset.pst; let note = "";
    if (st !== "todo") { note = prompt(st === "done" ? "What was done / found? (required)" : "Why is this step not applicable? (required)"); if (!note) return; }
    try { await post(`cases/${S.arg}/plan/${pst.dataset.pstep}`, { status: st, note }); toast("Plan updated"); } catch (err) { toast(err.message); } return render();
  }
  if (t.id === "cgo") go(`/explorer/claims?provider=${$("#cp").value}&rule=${$("#cr").value}&member=${$("#cm").value}`);
  if (t.id === "mgo") go(`/explorer/members?m=${$("#mq").value}`);
  if (t.id === "rerun") { await post("run", { seed: +$("#seed").value, members: +$("#mem").value }); toast("Pipeline started; the current analysis stays live until it finishes"); poll(); }
});
document.addEventListener("dblclick", e => { const sr = e.target.closest("[data-sel]"); if (sr) go("/case/" + sr.dataset.sel); });
document.addEventListener("input", e => {
  const t = e.target;
  if (t.id === "gq") { clearTimeout(UI.gt); UI.gt = setTimeout(() => gSearch(t.value), 180); }
  if (t.id === "qfq") { UI.qf.q = t.value; clearTimeout(UI.qt); UI.qt = setTimeout(async () => { await render(); const n = $("#qfq"); if (n) { n.focus(); n.setSelectionRange(n.value.length, n.value.length); } }, 300); }
  if (t.dataset.w) { S.weights[t.dataset.w] = t.value / 100; t.nextElementSibling.textContent = t.value; clearTimeout(S.wt); S.wt = setTimeout(render, 350); }
  if (t.dataset.cap) { S[t.dataset.cap] = Math.max(1, +t.value || 1); clearTimeout(S.ct); S.ct = setTimeout(render, 500); }
  if (t.id === "pq") { S.expl.prov.q = t.value; clearTimeout(S.pt); S.pt = setTimeout(async () => { const p = $("#pq"); const pos = p.selectionStart; await render(); const n = $("#pq"); n.focus(); n.setSelectionRange(pos, pos); }, 300); }
  if (t.id === "wq") { S.wq = t.value; clearTimeout(S.wt2); S.wt2 = setTimeout(async () => { await render(); const n = $("#wq"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }, 450); }
  if (t.id === "wbq") { clearTimeout(S.wbt); S.wbt = setTimeout(async () => { const q = t.value.trim(); const box = $("#wbres"); if (!box) return; if (!q) { box.innerHTML = ""; return; } const r = await api("graph/search?q=" + encodeURIComponent(q)); box.innerHTML = `<div class="wbdrop">${r.map(e => entRow(e)).join("") || '<div class="sm mut" style="padding:8px">No match. Patients: search by member ID (e.g. M-00010).</div>'}</div>`; }, 220); }
  if (t.id === "netq") { S.netQ = t.value; clearTimeout(S.nt); S.nt = setTimeout(async () => { await render(); const n = $("#netq"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }, 400); }
  if (t.id === "netmin") { S.netMin = +t.value; $("#netminv").textContent = t.value; clearTimeout(S.nt); S.nt = setTimeout(render, 300); }
});
document.addEventListener("keydown", e => { if (e.key === "Enter" && e.target.id === "askq") askCopilot(e.target.value); if (e.key === "Enter" && e.target.id === "gq") { const f = $("#gres .grow"); if (f) { UI.gq = ""; f.click(); } } if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "")) { const g = $("#gq"); if (g) { e.preventDefault(); g.focus(); } } });
document.addEventListener("submit", async e => {
  if (e.target.id !== "loginf") return; e.preventDefault();
  const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: $("#lu").value, password: $("#lp").value }) });
  if (!r.ok) return renderLogin("Wrong username or password");
  const j = await r.json(); if (j.mfa_required) return renderMfa(j.ticket);
  await afterLogin();
});
async function afterLogin() {
  document.body.classList.remove("landing"); $("#app").style.display = ""; $("#app").classList.remove("bare"); if (!(await loadMe())) return renderLogin();
  if (S.user.mfa_required && !S.user.mfa_enabled) return renderEnrol();
  S.status = await api("status"); if (!location.hash || location.hash === "#" || location.hash.startsWith("#/login")) location.hash = "#/my"; route();
}
document.addEventListener("submit", async e => {
  if (e.target.id === "mfaf") { e.preventDefault(); const r = await fetch("/api/login/mfa", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ticket: e.target.dataset.ticket, code: $("#mfac").value }) }); if (!r.ok) { const j = await r.json().catch(() => ({})); return (j.detail || "").includes("expired") ? renderLogin(j.detail) : renderMfa(e.target.dataset.ticket, "Code not accepted"); } return afterLogin(); }
  if (e.target.id === "enrolf") { e.preventDefault(); const r = await fetch("/api/mfa/confirm", { method: "POST", headers: { "Content-Type": "application/json", "X-SpotZi-Contract": CONTRACT }, body: JSON.stringify({ code: $("#enc").value }) }); const j = await r.json(); if (!r.ok) return toast(j.detail); $("#enrolf").remove(); $("#encodes").innerHTML = `<div class="banner green" style="margin-top:12px"><b>Two-factor is on.</b> Save these one-time recovery codes somewhere safe; they are shown only once.</div><div class="mono" style="columns:2">${j.recovery_codes.map(c => `<div>${c}</div>`).join("")}</div><button class="btn pri" style="width:100%;justify-content:center;margin-top:12px" id="enrdone">Continue</button>`; }
});
document.addEventListener("change", async e => {
  if (e.target.id === "rate") { S.rate = +e.target.value || 65; return render(); }
  if (e.target.dataset?.qf) { UI.qf[e.target.dataset.qf] = e.target.value; return render(); }
  if (e.target.dataset && e.target.dataset.kind) { e.target.checked ? NET.kinds.add(e.target.dataset.kind) : NET.kinds.delete(e.target.dataset.kind); return render(); }
  if (e.target.id === "wbflag") { NET.flagged = e.target.checked; return render(); }
  if (e.target.id === "asgsel" && e.target.value) { try { const r = await post(`cases/${S.arg}/assign`, { assignee: e.target.value, days: 10 }); toast("Assigned · due " + r.due); } catch (err) { toast(err.message); } return render(); }
  if (e.target.dataset && e.target.dataset.urole) { try { await api("users/" + e.target.dataset.urole, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role: e.target.value }) }); toast("Role updated"); } catch (err) { toast(err.message); } return; }
 if (e.target.id === "pf") { S.expl.prov.fam = e.target.value; render(); } });
function afterRender() { ctxFill(); Object.keys(GRAPHS).forEach(id => { if (!GRAPHS[id]?.three && document.getElementById(id)) wireGraph(id); }); mount3d(); if (S.view === "case" && S.tab === "decision") { loadNotes(S.arg); scopeCard(S.arg); recCard(S.arg); docCard(S.arg); } offlineBanner(); }

async function poll() {
  S.status = await api("status");
  if (S.status.state === "running" || !S.status.ready) { if (!S.status.ready || S.view === "data") render(); setTimeout(poll, 1500); }
  else { S.queue = null; S.weights = S.weights; render(); }
}
(async function boot() {
  if (!(await loadMe())) return renderLogin();
  S.status = await api("status");
  try { const m = await api("my"); S.unread = m.notifications.filter(n => !n.read).length; } catch {}
  if (!location.hash || location.hash === "#") location.hash = "#/my";
  route(); if (S.status.state === "running") poll();
})();
