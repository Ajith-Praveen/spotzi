/* SpotZⁱ 3D link-analysis view (portfolio: one island per community, the 3D twin of the 2D community board) (three.js, vendored locally — no CDN).
   Same visual language as the 2D view: the same cards, icons, risk colours and edge styles, on the stone theme.
   Space has meaning: horizontal position = the network layout; HEIGHT = risk, so high-risk entities rise above the
   portfolio and drop-lines to the ground grid make depth readable. Orbit / zoom / pan; hover to highlight neighbours. */
import * as THREE from "./vendor/three.module.js";
import { OrbitControls } from "./vendor/OrbitControls.js";
import { Line2 } from "./vendor/Line2.js";
import { LineGeometry } from "./vendor/LineGeometry.js";
import { LineMaterial } from "./vendor/LineMaterial.js";

const LIVE = {};          // id → { stop() }
const DPR = Math.min(2, window.devicePixelRatio || 1) * 1.6;
const FONT = getComputedStyle(document.body).fontFamily || "Inter, sans-serif";

function rr(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); }

function iconPath(ctx, d, cx, cy, sz, col, lw = 1.8) {
  ctx.save(); ctx.translate(cx - sz / 2, cy - sz / 2); ctx.scale(sz / 24, sz / 24);
  ctx.strokeStyle = col; ctx.lineWidth = lw * 24 / sz; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.stroke(new Path2D(d)); ctx.restore();
}

function texture(draw, w, h) {
  const c = document.createElement("canvas"); c.width = Math.ceil((w + 12) * DPR); c.height = Math.ceil((h + 12) * DPR);
  const ctx = c.getContext("2d"); ctx.scale(DPR, DPR); ctx.translate(6, 6);
  ctx.shadowColor = "rgba(24,24,27,.10)"; ctx.shadowBlur = 5; ctx.shadowOffsetY = 1.5;
  draw(ctx);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; t.minFilter = THREE.LinearFilter;
  return { tex: t, w: w + 12, h: h + 12 };
}

function nodeTexture(n, H) {
  const { riskColor, FICON, EICON, EDGE, FAM } = H;
  const ent = n.kind && n.kind !== "provider" && n.kind !== "patient", pat = n.kind === "patient";
  if (ent) {
    const c = EDGE[n.kind].c, w = Math.max(70, n.label.length * 6.4 + 34), h = 24;
    return texture(ctx => {
      rr(ctx, 0, 0, w, h, 5); ctx.fillStyle = "#F6F7F8"; ctx.fill(); ctx.shadowColor = "transparent";
      ctx.setLineDash([3, 2]); ctx.strokeStyle = c; ctx.globalAlpha = .7; ctx.lineWidth = 1; ctx.stroke(); ctx.globalAlpha = 1; ctx.setLineDash([]);
      iconPath(ctx, EICON[n.kind], 13, h / 2, 13, c);
      ctx.fillStyle = "#4A4E55"; ctx.font = `500 11px ${FONT}`; ctx.textBaseline = "middle"; ctx.fillText(n.label, 25, h / 2 + .5);
    }, w, h);
  }
  if (pat) {
    const prim = n.primary, w = prim ? 190 : 132, h = prim ? 44 : 30, ic = n.risk >= 60 ? "#B4423C" : n.risk >= 30 ? "#C28A1B" : "#A0A4AB";
    return texture(ctx => {
      rr(ctx, 0, 0, w, h, h / 2); ctx.fillStyle = "#fff"; ctx.fill(); ctx.shadowColor = "transparent";
      ctx.strokeStyle = prim ? "#1E2024" : "#C8CBD0"; ctx.lineWidth = prim ? 1.4 : 1; ctx.stroke();
      iconPath(ctx, "M12 11.5a3.8 3.8 0 1 0 0-7.6 3.8 3.8 0 0 0 0 7.6z M4.5 20.5a7.5 7.5 0 0 1 15 0", h / 2, h / 2, h * .5, "#3E4566");
      ctx.fillStyle = "#1E2024"; ctx.font = `${prim ? 600 : 500} ${prim ? 12.5 : 11}px ${FONT}`; ctx.textBaseline = "middle";
      ctx.fillText(n.label.replace("Patient ", ""), h - 2, prim ? h / 2 - 6 : h / 2 + .5);
      if (prim) { ctx.fillStyle = "#6E727A"; ctx.font = `400 10.5px ${FONT}`; ctx.fillText("Patient", h - 2, h / 2 + 9); }
      const bw = prim ? 28 : 22, bh = prim ? 20 : 16; rr(ctx, w - bw - 8, (h - bh) / 2, bw, bh, prim ? 5 : 8); ctx.fillStyle = ic; ctx.fill();
      ctx.fillStyle = "#fff"; ctx.font = `700 ${prim ? 11 : 9.5}px ${FONT}`; ctx.textAlign = "center"; ctx.fillText(Math.round(n.risk), w - bw / 2 - 8, h / 2 + .5);
    }, w, h);
  }
  const col = riskColor(n.risk), tint = n.risk >= 60 ? "#FCE6E6" : n.risk >= 40 ? "#FCEBD9" : n.risk >= 25 ? "#FBF0CF" : "#EEF0F3";
  if (!n._card) {
    return texture(ctx => {
      rr(ctx, 0, 0, 34, 34, 8); ctx.fillStyle = "#fff"; ctx.fill(); ctx.shadowColor = "transparent"; ctx.strokeStyle = "#C8CBD0"; ctx.lineWidth = 1; ctx.stroke();
      iconPath(ctx, FICON[n.family] || FICON.PRO, 17, 15.5, 17, "#5A5E66"); rr(ctx, 7, 29.5, 20, 2.5, 1.25); ctx.fillStyle = col; ctx.fill();
    }, 34, 34);
  }
  const w = 212, h = 44, isCase = n.primary || n.case_id;
  const name = n.label.length > 17 ? n.label.slice(0, 16).trimEnd() + "…" : n.label;
  return texture(ctx => {
    rr(ctx, 0, 0, w, h, 8); ctx.fillStyle = "#fff"; ctx.fill(); ctx.shadowColor = "transparent";
    ctx.save(); rr(ctx, 0, 0, w, h, 8); ctx.clip(); ctx.fillStyle = tint; ctx.fillRect(0, 0, 40, h); ctx.restore();
    rr(ctx, 0, 0, w, h, 8); ctx.strokeStyle = isCase ? "#1E2024" : "#C8CBD0"; ctx.lineWidth = isCase ? 1.4 : 1; ctx.stroke();
    ctx.beginPath(); ctx.moveTo(40, 0); ctx.lineTo(40, h); ctx.strokeStyle = "#E9EBF3"; ctx.lineWidth = 1; ctx.stroke();
    iconPath(ctx, FICON[n.family] || FICON.PRO, 20, h / 2, 19, n.risk >= 25 ? col : "#4A4E55");
    ctx.textBaseline = "middle"; ctx.fillStyle = "#1E2024"; ctx.font = `600 12.5px ${FONT}`; ctx.fillText(name, 49, h / 2 - 7);
    ctx.fillStyle = "#6E727A"; ctx.font = `400 10.5px ${FONT}`; ctx.fillText(`${FAM[n.family] || ""}${n.case_id ? " · " + n.case_id : ""}`, 49, h / 2 + 8);
    rr(ctx, w - 36, h / 2 - 10, 28, 20, 5); ctx.fillStyle = col; ctx.fill();
    ctx.fillStyle = "#fff"; ctx.font = `700 11px ${FONT}`; ctx.textAlign = "center"; ctx.fillText(Math.round(n.risk), w - 22, h / 2 + .5);
  }, w, h);
}

export function mount(wrap, G, H) {
  const id = wrap.dataset.g3d;
  if (LIVE[id]) LIVE[id].stop();
  const tip = wrap.querySelector(".gtip"), panel = wrap.querySelector(".gpanel"), host = wrap.querySelector(".g3c");
  const W = () => host.clientWidth, Ht = () => host.clientHeight;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1)); renderer.setSize(W(), Ht()); host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, W() / Ht(), 1, 20000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = .08; controls.minPolarAngle = 0; controls.maxPolarAngle = Math.PI; controls.screenSpacePanning = true;   // full 360° orbit (also from below)

  // ---- layout
  const ent = n => n.kind && n.kind !== "provider" && n.kind !== "patient";
  const lift = n => ent(n) ? 6 : 10 + (n.risk || 0) * 1.6 + (n.primary ? 20 : 0);
  const spread = (P, min, iters = 90, clampR = null) => {      // light repulsion keeps cards apart (optionally inside a radius)
    for (let it = 0; it < iters; it++) {
      for (let i = 0; i < P.length; i++) for (let j = i + 1; j < P.length; j++) {
        const a = P[i], b = P[j], dx = b.x - a.x, dz = b.z - a.z, d = Math.hypot(dx, dz) || .01;
        if (d < min) { const f = (min - d) / d * .5; a.x -= dx * f; a.z -= dz * f; b.x += dx * f; b.z += dz * f; }
      }
      if (clampR) P.forEach(p => { const r = Math.hypot(p.x - clampR.cx, p.z - clampR.cz); if (r > clampR.r) { p.x = clampR.cx + (p.x - clampR.cx) * clampR.r / r; p.z = clampR.cz + (p.z - clampR.cz) * clampR.r / r; } });
    }
  };
  const islandMode = !!G.communities;
  let ns = Object.values(G.nodes), P = [], islands = [];
  if (islandMode) {
    // the 3D twin of the 2D community board: every community is its own island (own layout, own floor, own cloud),
    // islands never overlap; links between communities are summarised as one arc per pair
    const active = G.communities.filter(c => c.max_risk >= 25 || c.ties > 0);
    const keep = new Set(active.map(c => c.id));
    ns = ns.filter(n => keep.has(n.community));
    const byC = {}; ns.forEach(n => (byC[n.community] = byC[n.community] || []).push(n));
    active.sort((x, y) => y.max_risk - x.max_risk).forEach((c, i) => {
      const mem = byC[c.id] || []; if (!mem.length) return;
      const r = 130 + 70 * Math.sqrt(mem.length);
      // place on a golden-angle spiral (highest risk at the centre), pushed out until it clears every earlier island
      let ang = i * 2.39996, dist = i ? 260 : 0, cx = 0, cz = 0;
      for (let t = 0; t < 400; t++) {
        cx = Math.cos(ang) * dist; cz = Math.sin(ang) * dist;
        if (islands.every(o => Math.hypot(o.cx - cx, o.cz - cz) >= o.r + r + 130)) break;
        dist += 25;
      }
      const xs = mem.map(n => n.x), ys = mem.map(n => n.y), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys), sp = Math.max(x1 - x0, y1 - y0) || 1;
      const local = mem.map(n => ({ n, x: cx + ((n.x - x0) / sp - .5) * r * 1.5, z: cz + ((n.y - y0) / sp - .5) * r * 1.5, y: lift(n) }));
      spread(local, 170, 140, { cx, cz, r: r * .82 });
      local.forEach(p => { p.n._lm = mem.length > 10 ? 40 : 25; });     // identical card/tile rule to the 2D board panel
      islands.push({ c, cx, cz, r, ids: new Set(mem.map(n => n.id)), mem: local });
      P.push(...local);
    });
  } else {
    const xs = ns.map(n => n.x), ys = ns.map(n => n.y), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const span = Math.max(x1 - x0, y1 - y0) || 1, R = Math.max(240, Math.min(1100, 78 * Math.sqrt(ns.length)));
    P = ns.map(n => ({ n, x: ((n.x - x0) / span - .5) * R * 2, z: ((n.y - y0) / span - .5) * R * 2, y: lift(n) }));
    spread(P, ns.length <= 40 ? 240 : 150);     // small graphs show full cards: keep them a card-width apart
  }
  const pos = {}; P.forEach(p => pos[p.n.id] = p);

  // ---- ground: subtle grid in the theme's line colours (+ one floor disc per island)
  const ext = Math.max(...P.map(p => Math.max(Math.abs(p.x), Math.abs(p.z))), ...islands.map(o => Math.max(Math.abs(o.cx), Math.abs(o.cz)) + o.r)) + 90;
  const grid = new THREE.GridHelper(ext * 2, Math.round(ext / 40), 0xD4D8E6, 0xE9EBF3); grid.material.transparent = true; grid.material.opacity = .8; scene.add(grid);
  const plane = new THREE.Mesh(new THREE.CircleGeometry(ext * 1.02, 64), new THREE.MeshBasicMaterial({ color: 0xF6F7FB, transparent: true, opacity: .7, side: THREE.DoubleSide, depthWrite: false }));
  plane.rotation.x = -Math.PI / 2; plane.position.y = -.5; scene.add(plane);
  islands.forEach(o => {
    const disc = new THREE.Mesh(new THREE.CircleGeometry(o.r, 64), new THREE.MeshBasicMaterial({ color: 0xFFFFFF, transparent: true, opacity: .85, depthWrite: false, side: THREE.DoubleSide }));
    disc.rotation.x = -Math.PI / 2; disc.position.set(o.cx, .2, o.cz); scene.add(disc);
    const rim = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(Array.from({ length: 97 }, (_, k) => new THREE.Vector3(o.cx + Math.cos(k / 96 * Math.PI * 2) * o.r, .6, o.cz + Math.sin(k / 96 * Math.PI * 2) * o.r))),
      new THREE.LineBasicMaterial({ color: 0xC9CDDC, transparent: true, opacity: .95 }));
    scene.add(rim); o.floor = [disc, rim];
  });

  // ---- nodes as camera-facing cards (identical artwork to the 2D view)
  const sprites = [], byId = {};
  const K = islandMode ? 1.25 : .95;   // world units per card pixel
  P.forEach(p => {
    const n = p.n; n._card = !ent(n) && n.kind !== "patient" && (n.primary || n.case_id || n.risk >= (n._lm ?? G.labelMin ?? -1) || (n._lm ?? G.labelMin ?? -1) < 0);
    const { tex, w, h } = nodeTexture(n, H);
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
    sp.scale.set(w * K, h * K, 1); sp.position.set(p.x, p.y + h * K / 2, p.z); sp.userData = { id: n.id }; sp.renderOrder = 2;
    scene.add(sp); sprites.push(sp); byId[n.id] = { sp, stems: [] };
    if (!ent(n)) {   // drop-line + footprint: reads height (risk) against the ground
      const g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(p.x, 0, p.z), new THREE.Vector3(p.x, p.y, p.z)]);
      const stem = new THREE.Line(g, new THREE.LineDashedMaterial({ color: 0x9A9FB6, dashSize: 4, gapSize: 4, transparent: true, opacity: .55 }));
      stem.computeLineDistances(); scene.add(stem);
      const dot = new THREE.Mesh(new THREE.RingGeometry(3, 5.5, 24), new THREE.MeshBasicMaterial({ color: new THREE.Color(H.riskColor(n.risk || 0)), transparent: true, opacity: .55, side: THREE.DoubleSide }));
      dot.rotation.x = -Math.PI / 2; dot.position.set(p.x, .3, p.z); scene.add(dot);
      byId[n.id].stems.push(stem, dot);
    }
  });

  const clouds = [];
  const label = (txt, red = true) => {
    const w = txt.length * 8.4 + 20, h = 22, { tex } = texture(ctx => { ctx.shadowColor = "transparent"; ctx.fillStyle = red ? "rgba(185,28,28,.9)" : "rgba(87,83,78,.9)"; ctx.font = `700 12px ${FONT}`; ctx.textBaseline = "middle"; ctx.letterSpacing = "1px"; ctx.fillText(txt, 4, h / 2); }, w, h);
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false })); sp.scale.set((w + 12) * K * 1.15, (h + 12) * K * 1.15, 1); sp.renderOrder = 3; return sp;
  };
  islands.forEach(o => {   // island label on the floor edge, facing the default camera — never on top of cards
    const lb = label(`COMMUNITY ${o.c.id + 1}  ·  MAX RISK ${Math.round(o.c.max_risk)}  ·  ${o.c.size} PROVIDERS`, false);
    lb.position.set(o.cx, 10, o.cz + o.r - 18); scene.add(lb); o.floor.push(lb);
  });

  // ---- edges: same colours / dash patterns / widths as 2D; referral-type edges get an arrowhead
  const res = new THREE.Vector2(W(), Ht()), edges = [];
  const DASH = k => k === "shared_members" || k === "shared_patients" ? [1.5, 4] : k === "primary_care" ? [2, 3] : k === "practices_at" ? [8, 4] : ["ownership", "address", "bank"].includes(k) ? [6, 4] : null;
  const between = {};
  G.edges.forEach(e => {
    const A = pos[e.source], B = pos[e.target]; if (!A || !B) return;
    if (islandMode && A.n.community !== B.n.community) {     // summarised as one arc per island pair (below)
      const k = [A.n.community, B.n.community].sort((x, y) => x - y).join("|"); (between[k] = between[k] || { n: 0, kinds: new Set() }).n++; between[k].kinds.add(e.kind); return;
    }
    const ek = e.kind === "billed" && e.flagged > 0 ? "billed_flag" : e.kind, arrow = H.ARROW.has(e.kind);
    const w = arrow ? 1.3 + Math.min(4, Math.log10((e.n || e.lines || 1) + 1) * 1.6) : e.kind === "shared_patients" ? 1 + Math.min(3, (e.jaccard || 0) * 8)
      : e.kind === "billed" ? (e.flagged > 0 ? 1.4 + Math.min(3.5, Math.log10(e.flagged + 1) * 2.2) : 1.1) : e.kind === "admitted" ? 1.8 : 1.5;
    const a = new THREE.Vector3(A.x, A.y + 6, A.z), b = new THREE.Vector3(B.x, B.y + 6, B.z), m = a.clone().add(b).multiplyScalar(.5);
    m.y += Math.min(40, a.distanceTo(b) * .05);
    const curve = new THREE.QuadraticBezierCurve3(a, m, b), pts = curve.getPoints(24);
    const geo = new LineGeometry(); geo.setPositions(pts.flatMap(v => [v.x, v.y, v.z]));
    const dash = DASH(e.kind);
    const op = e.kind === "shared_members" || e.kind === "shared_patients" ? .55 : e.kind === "billed" && !e.flagged ? .45 : .85;
    const mat = new LineMaterial({ color: new THREE.Color(H.EDGE[ek].c), linewidth: w * .7, transparent: true, opacity: op, dashed: !!dash, dashSize: dash ? dash[0] * 2 : 1, gapSize: dash ? dash[1] * 2 : 1, worldUnits: false, resolution: res });
    const line = new Line2(geo, mat); if (dash) line.computeLineDistances(); line.renderOrder = 1; scene.add(line);
    const parts = [line];
    if (arrow) {
      const t = curve.getTangent(.93), tipPt = curve.getPoint(.93);
      const cone = new THREE.Mesh(new THREE.ConeGeometry(4.2, 11, 12), new THREE.MeshBasicMaterial({ color: new THREE.Color(H.EDGE[ek].c), transparent: true, opacity: .9 }));
      cone.position.copy(tipPt); cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), t.normalize()); scene.add(cone); parts.push(cone);
    }
    edges.push({ a: e.source, b: e.target, parts, op });
  });

  // links between communities: one soft arc per pair of islands, width by number of links
  const isl = Object.fromEntries(islands.map(o => [o.c.id, o]));
  Object.entries(between).forEach(([k, v]) => {
    const [ca, cb] = k.split("|").map(Number), A = isl[ca], B = isl[cb]; if (!A || !B) return;
    const dx = B.cx - A.cx, dz = B.cz - A.cz, d = Math.hypot(dx, dz) || 1;
    const a = new THREE.Vector3(A.cx + dx / d * A.r, 2, A.cz + dz / d * A.r), b = new THREE.Vector3(B.cx - dx / d * B.r, 2, B.cz - dz / d * B.r);
    const m = a.clone().add(b).multiplyScalar(.5); m.y = 30 + a.distanceTo(b) * .18;
    const geo = new LineGeometry(); geo.setPositions(new THREE.QuadraticBezierCurve3(a, m, b).getPoints(32).flatMap(p => [p.x, p.y, p.z]));
    const line = new Line2(geo, new LineMaterial({ color: 0x6B7190, linewidth: Math.min(5, 1.2 + Math.log2(v.n + 1)), transparent: true, opacity: .5, dashed: true, dashSize: 14, gapSize: 10, resolution: res }));
    line.computeLineDistances(); scene.add(line); edges.push({ a: null, b: null, parts: [line], op: .5, between: [ca, cb] });
  });

  // ---- camera framing
  const box = new THREE.Box3(); P.forEach(p => box.expandByPoint(new THREE.Vector3(p.x, p.y + 30, p.z))); box.expandByPoint(new THREE.Vector3(0, 0, 0));
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const fit = () => {     // frame the whole network: distance from the bounding sphere and the camera's field of view
    const d = sphere.radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * (camera.aspect < 1 ? (islandMode ? .8 : .74) / camera.aspect : (islandMode ? .8 : .74));
    const dir = new THREE.Vector3(.35, .78, .62).normalize();
    controls.target.copy(sphere.center); camera.position.copy(sphere.center).addScaledVector(dir, d);
    camera.near = Math.max(1, d / 100); camera.far = d * 8; camera.updateProjectionMatrix(); controls.update();
  };
  fit();

  // ---- highlight (same semantics as the 2D view)
  const setOp = (o, v) => { o.material.opacity = v; };
  const focus = idn => {
    const keep = new Set([idn, ...(G.adj[idn] || [])]);
    sprites.forEach(s => setOp(s, keep.has(s.userData.id) ? 1 : .14));
    Object.entries(byId).forEach(([k, v]) => v.stems.forEach(o => setOp(o, keep.has(k) ? .55 : .08)));
    edges.forEach(e => { const on = e.a === idn || e.b === idn; e.parts.forEach(o => setOp(o, on ? 1 : .06)); });
    clouds.forEach(g => g.children.forEach(o => setOp(o, (o.userData.base ?? 1) * (g.userData.ids.has(idn) ? 1 : .25))));
  };
  const clear = () => { sprites.forEach(s => setOp(s, 1)); Object.values(byId).forEach(v => v.stems.forEach(o => setOp(o, .55))); edges.forEach(e => e.parts.forEach(o => setOp(o, e.op))); clouds.forEach(g => g.children.forEach(o => setOp(o, o.userData.base ?? 1))); };
  G.highlightPath = ids => {
    const on = new Set(ids), pairs = new Set(ids.slice(1).map((x, i) => [ids[i], x].sort().join("|")));
    sprites.forEach(s => setOp(s, on.has(s.userData.id) ? 1 : .14));
    edges.forEach(e => { const k = [e.a, e.b].sort().join("|"); e.parts.forEach(o => setOp(o, pairs.has(k) ? 1 : .05)); });
  };

  // ---- hover / click
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2(); let hover = null, down = null;
  const pick = ev => {
    const r = renderer.domElement.getBoundingClientRect(); mouse.set((ev.clientX - r.left) / r.width * 2 - 1, -(ev.clientY - r.top) / r.height * 2 + 1);
    ray.setFromCamera(mouse, camera); const hit = ray.intersectObjects(sprites, false)[0]; return hit ? hit.object.userData.id : null;
  };
  renderer.domElement.addEventListener("pointermove", ev => {
    const idn = pick(ev); renderer.domElement.style.cursor = idn ? "pointer" : "grab";
    if (idn !== hover) { hover = idn; if (idn) { focus(idn); tip.innerHTML = H.card(G.nodes[idn], G); tip.style.display = "block"; } else { tip.style.display = "none"; panel.dataset.open ? focus(panel.dataset.open) : clear(); } }
    if (idn) { const r = wrap.getBoundingClientRect(); tip.style.left = Math.min(r.width - 250, ev.clientX - r.left + 16) + "px"; tip.style.top = Math.max(8, ev.clientY - r.top - 10) + "px"; }
  });
  renderer.domElement.addEventListener("pointerdown", ev => { down = [ev.clientX, ev.clientY]; });
  renderer.domElement.addEventListener("pointerup", ev => {
    if (!down || Math.abs(ev.clientX - down[0]) + Math.abs(ev.clientY - down[1]) > 5) return;
    const idn = pick(ev);
    if (!idn) { if (panel.dataset.open) { panel.style.display = "none"; delete panel.dataset.open; clear(); } return; }
    H.onNode(G, idn, panel, focus, clear);
  });
  wrap.querySelectorAll("[data-g3]").forEach(b => b.addEventListener("click", ev => {
    ev.stopPropagation(); const k = b.dataset.g3;
    if (k === "fit") fit();
    else if (k === "spin") { controls.autoRotate = !controls.autoRotate; controls.autoRotateSpeed = .8; b.classList.toggle("on", controls.autoRotate); }
    else if (k === "top") { const r = ext * 1.6; camera.position.set(0, r, .01); controls.target.set(0, 0, 0); controls.update(); }
    else if (k === "rl" || k === "rr") {   // rotate the view 45° around the vertical axis
      const off = camera.position.clone().sub(controls.target); off.applyAxisAngle(new THREE.Vector3(0, 1, 0), (k === "rl" ? 1 : -1) * Math.PI / 4);
      camera.position.copy(controls.target).add(off); controls.update();
    }
    else { const d = camera.position.clone().sub(controls.target).multiplyScalar(k === "in" ? .8 : 1.25); camera.position.copy(controls.target).add(d); }
  }));

  // ---- loop + lifecycle
  let alive = true;
  const ro = new ResizeObserver(() => { renderer.setSize(W(), Ht()); camera.aspect = W() / Ht(); camera.updateProjectionMatrix(); res.set(W(), Ht()); edges.forEach(e => e.parts[0].material.resolution.copy(res)); });
  ro.observe(host);
  const tick = () => {
    if (!alive) return;
    if (!document.body.contains(wrap)) { stop(); return; }
    controls.update(); renderer.render(scene, camera); requestAnimationFrame(tick);
  };
  const stop = () => {
    alive = false; ro.disconnect(); controls.dispose();
    scene.traverse(o => { o.geometry?.dispose(); if (o.material) { o.material.map?.dispose(); o.material.dispose(); } });
    renderer.dispose(); renderer.domElement.remove(); delete LIVE[id];
  };
  LIVE[id] = { stop };
  tick();
}
