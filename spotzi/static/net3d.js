/* SpotZⁱ 3D link-analysis view (three.js, vendored locally — no CDN).
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
      rr(ctx, 0, 0, w, h, 5); ctx.fillStyle = "#FAFAF9"; ctx.fill(); ctx.shadowColor = "transparent";
      ctx.setLineDash([3, 2]); ctx.strokeStyle = c; ctx.globalAlpha = .7; ctx.lineWidth = 1; ctx.stroke(); ctx.globalAlpha = 1; ctx.setLineDash([]);
      iconPath(ctx, EICON[n.kind], 13, h / 2, 13, c);
      ctx.fillStyle = "#3F3F46"; ctx.font = `500 11px ${FONT}`; ctx.textBaseline = "middle"; ctx.fillText(n.label, 25, h / 2 + .5);
    }, w, h);
  }
  if (pat) {
    const prim = n.primary, w = prim ? 190 : 132, h = prim ? 44 : 30, ic = n.risk >= 60 ? "#B45309" : n.risk >= 30 ? "#CA8A04" : "#A8A29E";
    return texture(ctx => {
      rr(ctx, 0, 0, w, h, h / 2); ctx.fillStyle = "#fff"; ctx.fill(); ctx.shadowColor = "transparent";
      ctx.strokeStyle = prim ? "#18181B" : "#D6D3D1"; ctx.lineWidth = prim ? 1.4 : 1; ctx.stroke();
      iconPath(ctx, "M12 11.5a3.8 3.8 0 1 0 0-7.6 3.8 3.8 0 0 0 0 7.6z M4.5 20.5a7.5 7.5 0 0 1 15 0", h / 2, h / 2, h * .5, "#44403C");
      ctx.fillStyle = "#18181B"; ctx.font = `${prim ? 600 : 500} ${prim ? 12.5 : 11}px ${FONT}`; ctx.textBaseline = "middle";
      ctx.fillText(n.label.replace("Patient ", ""), h - 2, prim ? h / 2 - 6 : h / 2 + .5);
      if (prim) { ctx.fillStyle = "#78716C"; ctx.font = `400 10.5px ${FONT}`; ctx.fillText("Patient", h - 2, h / 2 + 9); }
      const bw = prim ? 28 : 22, bh = prim ? 20 : 16; rr(ctx, w - bw - 8, (h - bh) / 2, bw, bh, prim ? 5 : 8); ctx.fillStyle = ic; ctx.fill();
      ctx.fillStyle = "#fff"; ctx.font = `700 ${prim ? 11 : 9.5}px ${FONT}`; ctx.textAlign = "center"; ctx.fillText(Math.round(n.risk), w - bw / 2 - 8, h / 2 + .5);
    }, w, h);
  }
  const col = riskColor(n.risk), tint = n.risk >= 60 ? "#FEF2F2" : n.risk >= 40 ? "#FFF7ED" : n.risk >= 25 ? "#FEFCE8" : "#F5F5F4";
  if (!n._card) {
    return texture(ctx => {
      rr(ctx, 0, 0, 34, 34, 8); ctx.fillStyle = "#fff"; ctx.fill(); ctx.shadowColor = "transparent"; ctx.strokeStyle = "#D6D3D1"; ctx.lineWidth = 1; ctx.stroke();
      iconPath(ctx, FICON[n.family] || FICON.PRO, 17, 15.5, 17, "#57534E"); rr(ctx, 7, 29.5, 20, 2.5, 1.25); ctx.fillStyle = col; ctx.fill();
    }, 34, 34);
  }
  const w = 212, h = 44, isCase = n.primary || n.case_id;
  const name = n.label.length > 17 ? n.label.slice(0, 16).trimEnd() + "…" : n.label;
  return texture(ctx => {
    rr(ctx, 0, 0, w, h, 8); ctx.fillStyle = "#fff"; ctx.fill(); ctx.shadowColor = "transparent";
    ctx.save(); rr(ctx, 0, 0, w, h, 8); ctx.clip(); ctx.fillStyle = tint; ctx.fillRect(0, 0, 40, h); ctx.restore();
    rr(ctx, 0, 0, w, h, 8); ctx.strokeStyle = isCase ? "#18181B" : "#D6D3D1"; ctx.lineWidth = isCase ? 1.4 : 1; ctx.stroke();
    ctx.beginPath(); ctx.moveTo(40, 0); ctx.lineTo(40, h); ctx.strokeStyle = "#EEECEA"; ctx.lineWidth = 1; ctx.stroke();
    iconPath(ctx, FICON[n.family] || FICON.PRO, 20, h / 2, 19, n.risk >= 25 ? col : "#3F3F46");
    ctx.textBaseline = "middle"; ctx.fillStyle = "#18181B"; ctx.font = `600 12.5px ${FONT}`; ctx.fillText(name, 49, h / 2 - 7);
    ctx.fillStyle = "#78716C"; ctx.font = `400 10.5px ${FONT}`; ctx.fillText(`${FAM[n.family] || ""}${n.case_id ? " · " + n.case_id : ""}`, 49, h / 2 + 8);
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
  controls.enableDamping = true; controls.dampingFactor = .08; controls.maxPolarAngle = Math.PI * .495; controls.screenSpacePanning = true;

  // ---- layout: x/z from the 2D network layout, y (height) from risk; light 3D repulsion keeps cards apart
  const ns = Object.values(G.nodes);
  const xs = ns.map(n => n.x), ys = ns.map(n => n.y), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const span = Math.max(x1 - x0, y1 - y0) || 1, R = Math.max(240, Math.min(1100, 78 * Math.sqrt(ns.length)));
  const ent = n => n.kind && n.kind !== "provider" && n.kind !== "patient";
  const lift = n => ent(n) ? 6 : 10 + (n.risk || 0) * 1.6 + (n.primary ? 20 : 0);
  const P = ns.map(n => ({ n, x: ((n.x - x0) / span - .5) * R * 2, z: ((n.y - y0) / span - .5) * R * 2, y: lift(n) }));
  for (let it = 0; it < 90; it++) {
    for (let i = 0; i < P.length; i++) for (let j = i + 1; j < P.length; j++) {
      const a = P[i], b = P[j], dx = b.x - a.x, dz = b.z - a.z, dy = (b.y - a.y) * .6, d = Math.hypot(dx, dz, dy) || .01, min = 150;
      if (d < min) { const f = (min - d) / d * .5; a.x -= dx * f; a.z -= dz * f; b.x += dx * f; b.z += dz * f; }
    }
  }
  const pos = {}; P.forEach(p => pos[p.n.id] = p);

  // ---- ground: subtle grid in the theme's line colours
  const ext = Math.max(...P.map(p => Math.max(Math.abs(p.x), Math.abs(p.z)))) + 90;
  const grid = new THREE.GridHelper(ext * 2, Math.round(ext / 40), 0xD6D3D1, 0xECEAE7); grid.material.transparent = true; grid.material.opacity = .9; scene.add(grid);
  const plane = new THREE.Mesh(new THREE.CircleGeometry(ext * 1.02, 64), new THREE.MeshBasicMaterial({ color: 0xFAFAF9, transparent: true, opacity: .7 }));
  plane.rotation.x = -Math.PI / 2; plane.position.y = -.5; scene.add(plane);

  // ---- nodes as camera-facing cards (identical artwork to the 2D view)
  const sprites = [], byId = {};
  const K = .95;   // world units per card pixel
  P.forEach(p => {
    const n = p.n; n._card = !ent(n) && n.kind !== "patient" && (n.primary || n.case_id || n.risk >= (G.labelMin ?? -1) || (G.labelMin ?? -1) < 0);
    const { tex, w, h } = nodeTexture(n, H);
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
    sp.scale.set(w * K, h * K, 1); sp.position.set(p.x, p.y + h * K / 2, p.z); sp.userData = { id: n.id }; sp.renderOrder = 2;
    scene.add(sp); sprites.push(sp); byId[n.id] = { sp, stems: [] };
    if (!ent(n)) {   // drop-line + footprint: reads height (risk) against the ground
      const g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(p.x, 0, p.z), new THREE.Vector3(p.x, p.y, p.z)]);
      const stem = new THREE.Line(g, new THREE.LineDashedMaterial({ color: 0xA8A29E, dashSize: 4, gapSize: 4, transparent: true, opacity: .55 }));
      stem.computeLineDistances(); scene.add(stem);
      const dot = new THREE.Mesh(new THREE.RingGeometry(3, 5.5, 24), new THREE.MeshBasicMaterial({ color: new THREE.Color(H.riskColor(n.risk || 0)), transparent: true, opacity: .55, side: THREE.DoubleSide }));
      dot.rotation.x = -Math.PI / 2; dot.position.set(p.x, .3, p.z); scene.add(dot);
      byId[n.id].stems.push(stem, dot);
    }
  });

  // ---- edges: same colours / dash patterns / widths as 2D; referral-type edges get an arrowhead
  const res = new THREE.Vector2(W(), Ht()), edges = [];
  const DASH = k => k === "shared_members" || k === "shared_patients" ? [1.5, 4] : k === "primary_care" ? [2, 3] : k === "practices_at" ? [8, 4] : ["ownership", "address", "bank"].includes(k) ? [6, 4] : null;
  G.edges.forEach(e => {
    const A = pos[e.source], B = pos[e.target]; if (!A || !B) return;
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

  // ---- camera framing
  const box = new THREE.Box3(); P.forEach(p => box.expandByPoint(new THREE.Vector3(p.x, p.y + 30, p.z))); box.expandByPoint(new THREE.Vector3(0, 0, 0));
  const sphere = box.getBoundingSphere(new THREE.Sphere());
  const fit = () => {     // frame the whole network: distance from the bounding sphere and the camera's field of view
    const d = sphere.radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * (camera.aspect < 1 ? .74 / camera.aspect : .74);
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
  };
  const clear = () => { sprites.forEach(s => setOp(s, 1)); Object.values(byId).forEach(v => v.stems.forEach(o => setOp(o, .55))); edges.forEach(e => e.parts.forEach(o => setOp(o, e.op))); };
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
