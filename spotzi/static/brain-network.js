/*!
 * brain-network.js
 * Hero animation: a network bursts out from the centre of the screen, then
 * its ends gather into a 3D brain. Canvas 2D, no dependencies.
 *
 *   const hero = BrainNetwork.mount(canvasEl, {
 *     layout: 'auto',   // 'auto' | 'split' (brain settles right of centre) | 'center'
 *     theme: 'signal',  // 'signal' (slate brain, red network) | 'kernel' (cyan core) | 'spotzi' (navy)
 *     labels: [],       // names shown on a few network nodes; those nodes then orbit the brain
 *     onSettle() {},    // called once, when the brain has formed (~6.6 s in)
 *   });
 *   hero.replay();  hero.setTheme('kernel');  hero.seek(4.2);  hero.renderAt(8);  hero.destroy();
 */
(function (global) {
  'use strict';

  const THEMES = {
    signal: {
      bg: [0, 1, 2],
      grid: [181, 196, 201],
      net: [229, 72, 77],
      nodes: [[229, 72, 77], [247, 107, 21], [245, 184, 61], [128, 138, 146]],
      org: [245, 184, 61],
      fiber: [118, 132, 142],
      mesh: [181, 196, 201],
      tip: [247, 248, 249],
      halo: [181, 196, 201],
      core: [229, 72, 77],
      pulse: [255, 104, 104],
    },
    kernel: {
      bg: [0, 1, 2],
      grid: [181, 196, 201],
      net: [229, 72, 77],
      nodes: [[229, 72, 77], [247, 107, 21], [245, 184, 61], [128, 138, 146]],
      org: [245, 184, 61],
      fiber: [86, 122, 140],
      mesh: [140, 200, 222],
      tip: [247, 248, 249],
      halo: [96, 200, 236],
      core: [32, 160, 214],
      pulse: [150, 232, 255],
    },
    spotzi: {
      bg: [27, 40, 54],
      grid: [200, 217, 230],
      net: [229, 72, 77],
      nodes: [[229, 72, 77], [247, 107, 21], [245, 184, 61], [86, 124, 141]],
      org: [245, 184, 61],
      fiber: [86, 124, 141],
      mesh: [200, 217, 230],
      tip: [247, 248, 249],
      halo: [200, 217, 230],
      core: [229, 72, 77],
      pulse: [255, 104, 104],
    },
  };

  // Timeline, in seconds.
  const TL = {
    hubIn: 0.05,       // hub appears at the centre
    grow: 0.45,        // first network line starts growing
    morph: 2.6,        // line ends start gathering into the brain
    settle: 6.0,       // brain eases into its resting position
    settleEvent: 6.6,  // onSettle fires
    life: 6.4,         // idle motion fades in
  };

  const TAU = Math.PI * 2;
  const DEPTH = [0.4, 0.72, 1];
  const CAM = 5;

  const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
  const lerp = (a, b, t) => a + (b - a) * t;
  const prog = (t, start, dur) => clamp((t - start) / dur, 0, 1);
  const smooth = (a, b, t) => { const x = prog(t, a, b - a); return x * x * (3 - 2 * x); };
  const outCubic = (x) => 1 - (1 - x) * (1 - x) * (1 - x);
  const inOutCubic = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
  const outBack = (x) => (x <= 0 ? 0 : 1 + 2.9 * Math.pow(x - 1, 3) + 1.9 * Math.pow(x - 1, 2));
  const rgba = (c, a) => 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')';
  const mix = (a, b, t) => [0, 1, 2].map((i) => Math.round(lerp(a[i], b[i], t)));

  function mulberry32(seed) {
    return function () {
      seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function hash(n) {
    n = (n ^ 61) ^ (n >>> 16);
    n = n + (n << 3);
    n = n ^ (n >>> 4);
    n = Math.imul(n, 0x27d4eb2d);
    return (n ^ (n >>> 15)) >>> 0;
  }

  function randDir(rng, out) {
    const u = rng() * 2 - 1, ph = rng() * TAU, s = Math.sqrt(1 - u * u);
    out.x = s * Math.cos(ph); out.y = u; out.z = s * Math.sin(ph);
    return out;
  }

  function segDist(px, py, ax, ay, bx, by) {
    const vx = bx - ax, vy = by - ay;
    const k = clamp(((px - ax) * vx + (py - ay) * vy) / (vx * vx + vy * vy), 0, 1);
    const dx = px - ax - vx * k, dy = py - ay - vy * k;
    return Math.sqrt(dx * dx + dy * dy);
  }

  // ── Brain surface ──────────────────────────────────────────────────────
  // x: back(-) → front(+), y: down → up, z: left → right. Frontal lobe faces +x.

  function cerebrumPoint(rng, d) {
    randDir(rng, d);
    // Keep sampling even per unit of surface area (ellipsoid 1 × .76 × .42).
    const w = Math.sqrt((0.319 * d.x) ** 2 + (0.42 * d.y) ** 2 + (0.76 * d.z) ** 2);
    if (rng() * 0.76 > w) return null;
    const side = rng() < 0.5 ? -1 : 1;
    if (d.z * side < -0.2) return null;             // medial wall stays hidden
    if (d.y < -0.8 && rng() < 0.6) return null;     // thin out the underside
    const x = d.x;
    let y = d.y * 0.76, z = side * 0.4 + d.z * 0.42;
    if (y < 0) y *= (0.3 + 0.34 * Math.exp(-2 * ((x - 0.08) / 0.46) ** 2)) / 0.76; // temporal lobe
    else y *= 1 - 0.14 * Math.max(0, x - 0.25);
    if (d.z * side > 0.3) {                          // lateral fissure
      const k = segDist(x, y, 0.52, -0.22, -0.3, 0.14);
      if (k < 0.035) return null;
      if (k < 0.1) z -= side * 0.07 * (1 - k / 0.1);
    }
    const g = 0.024 * Math.sin(9 * x + 4 * y + 1.3) * Math.sin(8 * y - 5 * z + 2 * x); // gyri
    return { x: x + d.x * g, y: y + d.y * g, z: z + d.z * g };
  }

  function cerebellumPoint(rng, d) {
    randDir(rng, d);
    const w = Math.sqrt((0.15 * d.x) ** 2 + (0.216 * d.y) ** 2 + (0.09 * d.z) ** 2);
    if (rng() * 0.216 > w) return null;
    if (d.y > 0.35) return null;                     // tucked under the cerebrum
    if (d.x > 0.5 && d.y > -0.3) return null;
    const f = 0.012 * Math.sin(d.y * 26);            // folia
    return { x: -0.6 + d.x * (0.36 + f), y: -0.47 + d.y * (0.25 + f), z: d.z * (0.6 + f) };
  }

  function sampleSurface(n, rng) {
    const pts = [], d = { x: 0, y: 0, z: 0 };
    while (pts.length < n) {
      const p = rng() < 0.86 ? cerebrumPoint(rng, d) : cerebellumPoint(rng, d);
      if (p) pts.push(p);
    }
    return pts;
  }

  const dist2 = (a, b) => (a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2;

  function farthest(pts, idxs, k, rng) {
    const n = idxs.length;
    if (k >= n) return idxs.slice();
    const d = new Float32Array(n).fill(Infinity);
    const out = [];
    let cur = Math.floor(rng() * n);
    for (let s = 0; s < k; s++) {
      out.push(idxs[cur]);
      const a = pts[idxs[cur]];
      let best = -1, bi = 0;
      for (let i = 0; i < n; i++) {
        const dd = dist2(a, pts[idxs[i]]);
        if (dd < d[i]) d[i] = dd;
        if (d[i] > best) { best = d[i]; bi = i; }
      }
      cur = bi;
    }
    return out;
  }

  function strand(rng, extra) {
    const n = randDir(rng, {});
    return Object.assign({
      nx: n.x, ny: n.y, nz: n.z,
      tp: rng() * TAU, tf: 0.5 + rng() * 1.6,
      on: false, g: 0, arr: 0, b: 1, z: 0, f: 1,
      ox: 0, oy: 0, oz: 0, cx: 0, cy: 0, cz: 0, ex: 0, ey: 0, ez: 0,
      sox: 0, soy: 0, scx: 0, scy: 0, sex: 0, sey: 0, qx: 0, qy: 0, rx: 0, ry: 0,
    }, extra);
  }

  // Each primary line of the network ends on one brain-surface point and owns
  // the nearby patch of surface; its branches (secondaries) and twigs
  // (tertiaries) grow out to fill that patch.
  function buildGeometry(nSurf, nPrim, seed) {
    const rng = mulberry32(seed);
    const pts = sampleSurface(nSurf, rng);
    const N = pts.length;
    const all = [];
    for (let i = 0; i < N; i++) all.push(i);

    const primIdx = farthest(pts, all, nPrim, rng);
    const clusters = primIdx.map(() => []);
    for (let i = 0; i < N; i++) {
      let best = Infinity, bk = 0;
      for (let k = 0; k < primIdx.length; k++) {
        const dd = dist2(pts[i], pts[primIdx[k]]);
        if (dd < best) { best = dd; bk = k; }
      }
      clusters[bk].push(i);
    }

    const owner = new Array(N);
    const prims = [], secs = [], ters = [];
    const CLS = [0.42, 0.22, 0.16, 0.2]; // high, elevated, watch, low

    primIdx.forEach((pi, k) => {
      const T = pts[pi];
      const ang = Math.atan2(T.y, T.x) + (rng() - 0.5) * 0.35;
      let r = rng(), cls = 0;
      while (cls < 3 && r > CLS[cls]) { r -= CLS[cls]; cls++; }
      const g0 = TL.grow + rng() * 1.3, gd = 0.7 + rng() * 0.5;
      const m0 = Math.max(TL.morph + rng() * 0.9, g0 + gd + 0.15), md = 1.7 + rng() * 0.5;
      const p = strand(rng, {
        tx: T.x, ty: T.y, tz: T.z,
        fc: Math.cos(ang), fs: Math.sin(ang), fr: 0.55 + Math.pow(rng(), 0.9) * 1.05,
        kx: (rng() - 0.5) * 0.55, ky: (rng() - 0.5) * 0.35 - 0.05, kz: (rng() - 0.5) * 0.45,
        g0, gd, m0, md, land: m0 + md, cls, m: 0, pop: 0,
      });
      prims.push(p);
      owner[pi] = p;

      const others = clusters[k].filter((i) => i !== pi);
      if (!others.length) return;
      const seeds = farthest(pts, others, clamp(Math.round(others.length / 4.5), 1, 7), rng);
      const base = secs.length;
      seeds.forEach((si) => {
        const S = pts[si];
        const sg0 = m0 + 0.2 + rng() * 0.9, sgd = 1.0 + rng() * 0.6;
        const s = strand(rng, {
          p: k, u: 0.45 + rng() * 0.35,
          Tx: S.x, Ty: S.y, Tz: S.z, dx: S.x - T.x, dy: S.y - T.y, dz: S.z - T.z,
          g0: sg0, gd: sgd, land: Math.max(m0 + md, sg0 + sgd),
        });
        secs.push(s);
        owner[si] = s;
      });
      others.forEach((ti) => {
        if (owner[ti]) return;
        const P = pts[ti];
        let best = Infinity, bj = base;
        for (let j = base; j < secs.length; j++) {
          const s = secs[j];
          const dd = (P.x - s.Tx) ** 2 + (P.y - s.Ty) ** 2 + (P.z - s.Tz) ** 2;
          if (dd < best) { best = dd; bj = j; }
        }
        const s = secs[bj];
        const tg0 = s.g0 + s.gd * 0.45 + rng() * 0.6, tgd = 0.7 + rng() * 0.5;
        const q = strand(rng, {
          s: bj, u: 0.5 + rng() * 0.35,
          dx: P.x - s.Tx, dy: P.y - s.Ty, dz: P.z - s.Tz,
          g0: tg0, gd: tgd, land: Math.max(s.land, tg0 + tgd),
        });
        ters.push(q);
        owner[ti] = q;
      });
    });

    // Cortex mesh: each surface point links to its nearest neighbours.
    const edges = [], seen = new Set(), MAX = 0.24 * 0.24;
    for (let i = 0; i < N; i++) {
      const a = pts[i];
      const bi = [-1, -1, -1], bd = [Infinity, Infinity, Infinity];
      for (let j = 0; j < N; j++) {
        if (j === i) continue;
        const dd = dist2(a, pts[j]);
        if (dd >= bd[2]) continue;
        let s = 2;
        while (s > 0 && dd < bd[s - 1]) { bd[s] = bd[s - 1]; bi[s] = bi[s - 1]; s--; }
        bd[s] = dd; bi[s] = j;
      }
      for (let s = 0; s < 3; s++) {
        if (bi[s] < 0 || bd[s] > MAX) continue;
        const lo = Math.min(i, bi[s]), hi = Math.max(i, bi[s]), key = lo * N + hi;
        if (seen.has(key)) continue;
        seen.add(key);
        edges.push(lo, hi);
      }
    }

    // Dashed "organisation" links between neighbouring network nodes.
    const org = [];
    for (let i = 0; i < prims.length; i++) {
      for (let j = i + 1; j < prims.length; j++) {
        const a = prims[i], b = prims[j];
        const dx = a.fc * a.fr - b.fc * b.fr, dy = a.fs * a.fr - b.fs * b.fr;
        if (dx * dx + dy * dy < 0.12) org.push([i, j]);
      }
    }
    for (let i = org.length - 1; i > 0; i--) {
      const j = Math.floor(rng() * (i + 1));
      const tmp = org[i]; org[i] = org[j]; org[j] = tmp;
    }
    org.length = Math.min(org.length, 14);

    // Brain stem: fibres bundle under the brain and trail off downwards.
    const stem = [];
    const nStem = Math.round(prims.length * 0.8);
    for (let i = 0; i < nStem; i++) {
      stem.push({
        ox: -0.12 + (rng() - 0.5) * 0.35, oy: -0.22 + (rng() - 0.5) * 0.22, oz: (rng() - 0.5) * 0.4,
        cx: -0.3 + (rng() - 0.5) * 0.07, cy: -0.85 + (rng() - 0.5) * 0.1, cz: (rng() - 0.5) * 0.09,
        ex: -0.44 + (rng() - 0.5) * 0.16, ey: -1.42 - rng() * 0.2, ez: (rng() - 0.5) * 0.16,
        g0: 4.3 + rng() * 1.3, gd: 1.3 + rng() * 0.7, g: 0,
        sox: 0, soy: 0, qx: 0, qy: 0, rx: 0, ry: 0,
      });
    }

    const pulses = [];
    for (let j = 0; j < 34; j++) pulses.push({ sec: false, per: 2.4 + rng() * 2.6, ph: rng() * 6, dur: 0.85 + rng() * 0.4 });
    for (let j = 0; j < 44; j++) pulses.push({ sec: true, per: 2.0 + rng() * 2.4, ph: rng() * 6, dur: 0.6 + rng() * 0.3 });

    return { prims, secs, ters, owner, edges: Int32Array.from(edges), edgeLvl: new Uint8Array(edges.length / 2), org, stem, pulses };
  }

  // ── Sprites ────────────────────────────────────────────────────────────

  function sprite(core, halo, size, solid) {
    const c = document.createElement('canvas');
    c.width = c.height = size;
    const g = c.getContext('2d'), r = size / 2;
    const grd = g.createRadialGradient(r, r, 0, r, r, r);
    if (solid) {
      grd.addColorStop(0, rgba(mix(core, [255, 255, 255], 0.35), 1));
      grd.addColorStop(0.2, rgba(core, 1));
      grd.addColorStop(0.27, rgba(core, 0.45));
      grd.addColorStop(0.5, rgba(halo, 0.12));
      grd.addColorStop(1, rgba(halo, 0));
    } else {
      grd.addColorStop(0, 'rgba(255,255,255,1)');
      grd.addColorStop(0.12, rgba(core, 0.9));
      grd.addColorStop(0.3, rgba(halo, 0.3));
      grd.addColorStop(0.62, rgba(halo, 0.07));
      grd.addColorStop(1, rgba(halo, 0));
    }
    g.fillStyle = grd;
    g.fillRect(0, 0, size, size);
    return c;
  }

  function buildSprites(th) {
    return {
      tip: sprite(th.tip, th.halo, 64),
      pulse: sprite(th.pulse, th.pulse, 64),
      nodes: th.nodes.map((n) => sprite(n, n, 64, true)),
    };
  }

  // ── Renderer ───────────────────────────────────────────────────────────

  function mount(canvas, options) {
    const o = Object.assign({
      layout: 'auto', theme: 'signal', density: 1, maxDpr: 2,
      width: 0, height: 0, interactive: true, observe: true, seed: 11, onSettle: null, labels: [],
    }, options);

    const ctx = canvas.getContext('2d');
    const bloom = document.createElement('canvas');
    const bctx = bloom.getContext('2d');
    const canFilter = typeof bctx.filter === 'string';
    const DIV = canFilter ? 4 : 8;
    const reduce = !!(global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches);

    let theme = THEMES[o.theme] || THEMES.signal;
    let spr = buildSprites(theme);

    const measure = () => {
      if (o.width && o.height) return { w: o.width, h: o.height };
      const r = canvas.getBoundingClientRect();
      return { w: Math.max(1, r.width), h: Math.max(1, r.height) };
    };

    const first = measure();
    const nSurf = Math.round(clamp((first.w * first.h) / 1100, 700, 1900) * o.density);
    const G = buildGeometry(nSurf, Math.round(clamp(nSurf / 18, 60, 110)), o.seed);

    // Labelled nodes: a few primaries, spread around the burst, carry a name
    // while the network is on show, then break away as red dots that orbit
    // the brain.
    const ORX = 1.42, ORZ = 1.18, ORY = 0.02, ORT = 0.4, SPIN = 0.2; // tilted orbit, rad/s
    const tagged = [];
    (o.labels || []).slice(0, 12).forEach((text, i, all) => {
      const want = -Math.PI / 2 + 0.35 + (i / all.length) * TAU;
      let best = -1, bd = Infinity;
      for (let pass = 0; pass < 2 && best < 0; pass++) {
        for (let k = 0; k < G.prims.length; k++) {
          const p = G.prims[k];
          if (p.lab || (pass === 0 && (p.fr < 0.58 || p.fr > 0.85))) continue; // keep labels on screen
          const d = Math.abs((((Math.atan2(p.fs, p.fc) - want) % TAU) + TAU + Math.PI) % TAU - Math.PI);
          if (d < bd) { bd = d; best = k; }
        }
      }
      if (best < 0) return;
      const p = G.prims[best];
      p.lab = text;
      p.g0 = TL.grow + 0.15 + i * 0.16;
      p.gd = 0.75;
      p.m0 = Math.max(p.m0, 3.5 + i * 0.07);
      p.land = p.m0 + p.md;
      tagged.push({ p, text, th: (i / all.length) * TAU, x: 0, y: 0, la: 0 });
    });

    let W = 1, H = 1, dpr = 1, unit = 1, split = false, portrait = false, sz = 1;
    let gridPat = null, vignette = null, bloomOn = true;

    function resize() {
      const m = measure();
      W = m.w; H = m.h;
      dpr = o.width ? 1 : Math.min(global.devicePixelRatio || 1, o.maxDpr);
      canvas.width = Math.max(1, Math.round(W * dpr));
      canvas.height = Math.max(1, Math.round(H * dpr));
      split = o.layout === 'split' || (o.layout === 'auto' && W >= 900 && W / H > 1.15);
      portrait = o.layout === 'auto' && !split;
      unit = portrait ? Math.min(W * 0.4, H * 0.3) : Math.min(W * 0.2, H * 0.36);
      sz = dpr * clamp(unit / 360, 0.7, 1.3);
      bloom.width = Math.ceil(canvas.width / DIV);
      bloom.height = Math.ceil(canvas.height / DIV);
      if (canFilter) bctx.filter = 'blur(3px)';
      makeGrid();
      makeVignette();
    }

    function makeGrid() {
      const s = Math.max(8, Math.round(24 * dpr));
      const c = document.createElement('canvas');
      c.width = c.height = s;
      const g = c.getContext('2d');
      g.fillStyle = rgba(theme.grid, 0.16);
      g.beginPath();
      g.arc(s / 2, s / 2, Math.max(0.6, 0.85 * dpr), 0, TAU);
      g.fill();
      gridPat = ctx.createPattern(c, 'repeat');
    }

    function makeVignette() {
      vignette = vignette || document.createElement('canvas');
      vignette.width = canvas.width;
      vignette.height = canvas.height;
      const g = vignette.getContext('2d'), w = vignette.width, h = vignette.height;
      const r = Math.hypot(w, h) / 2;
      const grd = g.createRadialGradient(w / 2, h / 2, r * 0.35, w / 2, h / 2, r);
      grd.addColorStop(0, rgba(theme.bg, 0));
      grd.addColorStop(1, rgba(theme.bg, 0.92));
      g.clearRect(0, 0, w, h);
      g.fillStyle = grd;
      g.fillRect(0, 0, w, h);
    }

    // Projection state, set once per frame.
    let CX = 0, CY = 0, K = 1, cyw = 1, syw = 0, cpt = 1, spt = 0;
    let PX = 0, PY = 0, PZ = 0, PF = 1;

    function proj(x, y, z) {
      const x1 = x * cyw + z * syw, z1 = z * cyw - x * syw;
      const y2 = y * cpt - z1 * spt, z2 = y * spt + z1 * cpt;
      const f = CAM / (CAM - z2);
      PX = CX + x1 * K * f; PY = CY - y2 * K * f; PZ = z2; PF = f;
    }

    function bend(s, k) {
      const dx = s.ex - s.ox, dy = s.ey - s.oy, dz = s.ez - s.oz;
      const L = Math.sqrt(dx * dx + dy * dy + dz * dz) * k;
      s.cx = (s.ox + s.ex) * 0.5 + s.nx * L;
      s.cy = (s.oy + s.ey) * 0.5 + s.ny * L;
      s.cz = (s.oz + s.ez) * 0.5 + s.nz * L;
    }

    // Projects a strand and works out the visible part of it (0..g).
    function place(s, g) {
      proj(s.ox, s.oy, s.oz); s.sox = PX; s.soy = PY;
      proj(s.cx, s.cy, s.cz); s.scx = PX; s.scy = PY;
      proj(s.ex, s.ey, s.ez); s.sex = PX; s.sey = PY; s.z = PZ; s.f = PF;
      const a = 1 - g;
      s.qx = s.sox * a + s.scx * g; s.qy = s.soy * a + s.scy * g;
      s.rx = a * a * s.sox + 2 * a * g * s.scx + g * g * s.sex;
      s.ry = a * a * s.soy + 2 * a * g * s.scy + g * g * s.sey;
      s.b = PZ < -0.28 ? 0 : PZ < 0.28 ? 1 : 2;
    }

    function branchFrom(s, parent) {
      const u = s.u, a = (1 - u) * (1 - u), b = 2 * (1 - u) * u, c = u * u;
      s.ox = a * parent.ox + b * parent.cx + c * parent.ex;
      s.oy = a * parent.oy + b * parent.cy + c * parent.ey;
      s.oz = a * parent.oz + b * parent.cz + c * parent.ez;
      s.ex = parent.ex + s.dx; s.ey = parent.ey + s.dy; s.ez = parent.ez + s.dz;
    }

    function strokeGroup(list, color, alpha, width) {
      ctx.lineWidth = width;
      for (let b = 0; b < 3; b++) {
        ctx.beginPath();
        let any = false;
        for (let i = 0; i < list.length; i++) {
          const s = list[i];
          if (!s.on || s.b !== b) continue;
          ctx.moveTo(s.sox, s.soy);
          ctx.quadraticCurveTo(s.qx, s.qy, s.rx, s.ry);
          any = true;
        }
        if (any) { ctx.strokeStyle = rgba(color, alpha * DEPTH[b]); ctx.stroke(); }
      }
    }

    function glow(x, y, r, color, a, stretch) {
      if (a <= 0.004 || r <= 0) return;
      ctx.save();
      ctx.translate(x, y);
      ctx.scale(stretch, 1);
      const g = ctx.createRadialGradient(0, 0, 0, 0, 0, r);
      g.addColorStop(0, rgba(color, a));
      g.addColorStop(0.4, rgba(color, a * 0.35));
      g.addColorStop(1, rgba(color, 0));
      ctx.fillStyle = g;
      ctx.fillRect(-r, -r, 2 * r, 2 * r);
      ctx.restore();
    }

    let mx = 0, my = 0, tmx = 0, tmy = 0;

    function frame(t) {
      const th = theme;
      const cw = canvas.width, ch = canvas.height;
      const M = smooth(TL.morph, 5.6, t);                         // network → brain colours
      const S = inOutCubic(prog(t, TL.settle, 2.0));               // settle into place
      const L = smooth(TL.life, 8.6, t);                           // idle life
      const zoom = lerp(1.32, 1, inOutCubic(prog(t, 0.2, 6.8)));
      const turn = inOutCubic(prog(t, 3.0, 4.2));

      mx += (tmx - mx) * 0.045;
      my += (tmy - my) * 0.045;
      const live = 0.25 + 0.75 * L;
      const yaw = -0.32 * turn + L * 0.2 * Math.sin(0.23 * (t - TL.life)) + mx * 0.16 * live;
      const pitch = 0.14 * turn + L * 0.05 * Math.sin(0.17 * (t - TL.life)) + my * 0.09 * live;
      cyw = Math.cos(yaw); syw = Math.sin(yaw); cpt = Math.cos(pitch); spt = Math.sin(pitch);

      const tx = split ? W * 0.665 : W / 2;
      const ty = portrait ? H * 0.36 : H / 2 - 0.22 * unit;
      CX = lerp(W / 2, tx, S) * dpr;
      CY = lerp(H / 2, ty, S) * dpr;
      K = unit * zoom * dpr;

      // World half-extents of the screen while the network is on show, so
      // the network fills the frame whatever its shape.
      const HX = W / 2 / (unit * 1.3), HY = H / 2 / (unit * 1.3);

      // ── update ──
      const prims = G.prims, secs = G.secs, ters = G.ters;
      for (let i = 0; i < prims.length; i++) {
        const p = prims[i];
        p.arr = smooth(p.land - 0.2, p.land + 0.5, t);
        p.g = outCubic(prog(t, p.g0, p.gd));
        if (p.g <= 0) { p.on = false; continue; }
        p.on = true;
        p.pop = outBack(prog(t, p.g0 + p.gd * 0.8, 0.45));
        const m = (p.m = inOutCubic(prog(t, p.m0, p.md)));
        let fx = p.fc * p.fr * HX, fy = p.fs * p.fr * HY;
        const need = 1.15 * Math.hypot(p.tx, p.ty), mag = Math.hypot(fx, fy);
        if (mag < need) { fx *= need / mag; fy *= need / mag; }
        p.nwx = fx; p.nwy = fy; p.nwz = p.tz * 0.2; // where the node sits in the network
        const sw = Math.sin(Math.PI * m) * 0.22 * Math.hypot(fx - p.tx, fy - p.ty); // swirl inwards
        p.ox = p.kx * m; p.oy = p.ky * m; p.oz = p.kz * m;
        p.ex = lerp(fx, p.tx, m) - p.fs * sw;
        p.ey = lerp(fy, p.ty, m) + p.fc * sw;
        p.ez = lerp(p.tz * 0.2, p.tz, m);
        bend(p, 0.15 * m);
        place(p, p.g);
      }
      for (let i = 0; i < secs.length; i++) {
        const s = secs[i], p = prims[s.p];
        s.arr = smooth(s.land, s.land + 0.7, t);
        s.g = outCubic(prog(t, s.g0, s.gd));
        if (s.g <= 0 || !p.on) { s.on = false; continue; }
        s.on = true;
        branchFrom(s, p);
        bend(s, 0.22);
        place(s, s.g);
      }
      for (let i = 0; i < ters.length; i++) {
        const q = ters[i], s = secs[q.s];
        q.arr = smooth(q.land, q.land + 0.7, t);
        q.g = outCubic(prog(t, q.g0, q.gd));
        if (q.g <= 0 || !s.on) { q.on = false; continue; }
        q.on = true;
        branchFrom(q, s);
        bend(q, 0.25);
        place(q, q.g);
      }

      // ── background ──
      ctx.globalCompositeOperation = 'source-over';
      ctx.globalAlpha = 1;
      ctx.fillStyle = rgba(th.bg, 1);
      ctx.fillRect(0, 0, cw, ch);
      ctx.globalAlpha = (0.75 - 0.45 * M) * smooth(0, 0.6, t);
      ctx.fillStyle = gridPat;
      ctx.fillRect(0, 0, cw, ch);
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = 'lighter';

      const hubV = smooth(TL.hubIn, 0.5, t) * (1 - smooth(3.0, 5.2, t));
      proj(0, -0.05, 0);
      glow(PX, PY, 0.55 * K, th.net, 0.45 * hubV, 1);
      glow(PX, PY, 1.25 * K, th.core, 0.13 * M, 1.3);
      glow(PX, PY, 0.5 * K, th.core, 0.1 * M, 1.2);

      // ── dashed org links (network phase only) ──
      const orgA = smooth(1.9, 2.4, t) * (1 - smooth(2.7, 3.6, t));
      if (orgA > 0) {
        ctx.setLineDash([5 * sz, 6 * sz]);
        ctx.lineWidth = 1.1 * sz;
        ctx.strokeStyle = rgba(th.org, 0.5 * orgA);
        ctx.beginPath();
        for (let i = 0; i < G.org.length; i++) {
          const a = prims[G.org[i][0]], b = prims[G.org[i][1]];
          if (!a.on || !b.on || a.pop < 0.9 || b.pop < 0.9) continue;
          ctx.moveTo(a.rx, a.ry);
          ctx.lineTo(b.rx, b.ry);
        }
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // ── brain stem ──
      if (t > 4.3) {
        proj(-0.22, -0.3, 0); const x0 = PX, y0 = PY;
        proj(-0.46, -1.6, 0);
        const sg = ctx.createLinearGradient(x0, y0, PX, PY);
        sg.addColorStop(0, rgba(th.mesh, 0.2));
        sg.addColorStop(0.45, rgba(th.mesh, 0.07));
        sg.addColorStop(1, rgba(th.mesh, 0));
        ctx.strokeStyle = sg;
        ctx.lineWidth = 0.55 * sz;
        ctx.beginPath();
        for (let i = 0; i < G.stem.length; i++) {
          const s = G.stem[i];
          s.g = outCubic(prog(t, s.g0, s.gd));
          if (s.g <= 0) continue;
          place(s, s.g);
          ctx.moveTo(s.sox, s.soy);
          ctx.quadraticCurveTo(s.qx, s.qy, s.rx, s.ry);
        }
        ctx.stroke();
      }

      // ── fibres ──
      strokeGroup(prims, mix(th.net, th.fiber, M), lerp(0.62, 0.4, M), lerp(1.5, 1.05, M) * sz);
      strokeGroup(secs, th.fiber, 0.32, 0.85 * sz);
      strokeGroup(ters, th.fiber, 0.27, 0.62 * sz);

      // ── cortex mesh ──
      const E = G.edges, lvl = G.edgeLvl, owner = G.owner;
      if (t > 4) {
        for (let e = 0; e < lvl.length; e++) {
          const A = owner[E[2 * e]], B = owner[E[2 * e + 1]];
          const a = Math.min(A.arr, B.arr);
          if (a <= 0.02) { lvl[e] = 255; continue; }
          const dz = (A.z + B.z) * 0.5;
          const df = dz < -0.28 ? DEPTH[0] : dz < 0.28 ? DEPTH[1] : DEPTH[2];
          lvl[e] = Math.min(3, Math.floor(a * df * 4));
        }
        ctx.lineWidth = 0.6 * sz;
        for (let l = 0; l < 4; l++) {
          ctx.beginPath();
          let any = false;
          for (let e = 0; e < lvl.length; e++) {
            if (lvl[e] !== l) continue;
            const A = owner[E[2 * e]], B = owner[E[2 * e + 1]];
            ctx.moveTo(A.sex, A.sey);
            ctx.lineTo(B.sex, B.sey);
            any = true;
          }
          if (any) { ctx.strokeStyle = rgba(th.mesh, (0.22 * (l + 1)) / 4); ctx.stroke(); }
        }
      }

      // ── tips ──
      const ts = 15 * sz;
      const tip = spr.tip;
      for (let li = 0; li < 2; li++) {
        const list = li ? secs : ters;
        for (let i = 0; i < list.length; i++) {
          const s = list[i];
          if (!s.on) continue;
          const df = DEPTH[s.b];
          let a, size;
          if (s.g < 1) {
            a = 0.1 + 0.9 * df;
            size = ts * 1.15;
          } else {
            const tw = 0.5 + 0.5 * Math.sin(t * s.tf + s.tp);
            const flash = Math.max(0, 1 - (t - s.g0 - s.gd) * 2.5);
            a = df * (0.5 + 0.5 * tw * tw * tw) + flash * 0.6;
            size = ts * (0.85 + 0.25 * tw);
          }
          size *= s.f;
          ctx.globalAlpha = a > 1 ? 1 : a;
          ctx.drawImage(tip, s.rx - size / 2, s.ry - size / 2, size, size);
        }
      }
      const NODE = [1.15, 1, 0.95, 0.8];
      for (let i = 0; i < prims.length; i++) {
        const p = prims[i];
        if (!p.on) continue;
        if (p.m < 1 && !p.lab) {
          const size = (p.g < 1 ? 14 : 30 * NODE[p.cls] * p.pop) * sz * p.f;
          ctx.globalAlpha = 1 - p.m;
          ctx.drawImage(spr.nodes[p.cls], p.rx - size / 2, p.ry - size / 2, size, size);
        }
        if (p.m > 0) {
          const tw = 0.5 + 0.5 * Math.sin(t * p.tf + p.tp);
          const size = ts * 1.3 * p.f;
          ctx.globalAlpha = p.m * DEPTH[p.b] * (0.65 + 0.35 * tw);
          ctx.drawImage(tip, p.rx - size / 2, p.ry - size / 2, size, size);
        }
      }

      // ── labelled nodes: leave the network and orbit the brain ──
      if (tagged.length) {
        const ringA = smooth(4.4, 6.6, t);
        if (ringA > 0) {
          ctx.globalAlpha = 1;
          ctx.lineWidth = 1.2 * dpr;
          ctx.strokeStyle = rgba(th.net, 0.32 * ringA);
          ctx.beginPath();
          for (let k = 0; k <= 72; k++) {
            const a = (k / 72) * TAU;
            proj(ORX * Math.cos(a), ORY + ORT * Math.sin(a), ORZ * Math.sin(a));
            if (k) ctx.lineTo(PX, PY); else ctx.moveTo(PX, PY);
          }
          ctx.stroke();
        }
        const dot = spr.nodes[0];
        for (let i = 0; i < tagged.length; i++) {
          const L = tagged[i], p = L.p;
          L.la = 0;
          if (!p.on) continue;
          const k = inOutCubic(prog(t, p.m0, p.md + 0.5));
          const ang = L.th + SPIN * Math.max(0, t - p.m0);
          let x = p.rx, y = p.ry, f = p.f, depth = 1;
          if (k > 0) {
            proj(lerp(p.nwx, ORX * Math.cos(ang), k), lerp(p.nwy, ORY + ORT * Math.sin(ang), k), lerp(p.nwz, ORZ * Math.sin(ang), k));
            x = PX; y = PY; f = PF;
            depth = lerp(1, PZ < -0.25 ? 0.45 : PZ < 0.25 ? 0.75 : 1, k);
            const trail = smooth(p.m0 + p.md + 0.5, p.m0 + p.md + 1.3, t);
            for (let j = 1; trail > 0 && j <= 4; j++) {
              const b = ang - j * 0.07;
              proj(ORX * Math.cos(b), ORY + ORT * Math.sin(b), ORZ * Math.sin(b));
              const ss = 26 * sz * PF * (1 - j * 0.16);
              ctx.globalAlpha = trail * depth * 0.35 * (1 - j * 0.2);
              ctx.drawImage(dot, PX - ss / 2, PY - ss / 2, ss, ss);
            }
          }
          const size = (p.g < 1 ? 14 : lerp(30 * NODE[0] * p.pop, 30, k)) * sz * f;
          if (k > 0) { // red glow around the orbiting dot
            const gs = size * 2.6, beat = 0.75 + 0.25 * Math.sin(t * 2.2 + L.th * 3);
            ctx.globalAlpha = k * depth * 0.55 * beat;
            ctx.drawImage(spr.pulse, x - gs / 2, y - gs / 2, gs, gs);
          }
          ctx.globalAlpha = depth;
          ctx.drawImage(dot, x - size / 2, y - size / 2, size, size);
          L.x = x; L.y = y;
          L.la = p.pop * (1 - smooth(p.m0 - 0.15, p.m0 + 0.55, t));
        }
      }

      // ── pulses: signals travelling outwards along the fibres ──
      const pulseA = smooth(1.8, 2.6, t) * (reduce ? 0.5 : 1);
      if (pulseA > 0) {
        const ps = 20 * sz;
        for (let j = 0; j < G.pulses.length; j++) {
          const q = G.pulses[j];
          if (q.sec && L <= 0) continue;
          const tt = t + q.ph, cyc = Math.floor(tt / q.per), local = (tt - cyc * q.per) / q.dur;
          if (local > 1.3) continue;
          const list = q.sec ? secs : prims;
          const s = list[hash(j * 131 + cyc * 7919) % list.length];
          if (!s.on || s.g < 1) continue;
          const base = pulseA * (q.sec ? L : 1) * DEPTH[s.b];
          if (local > 1) {
            const size = ps * 1.6 * s.f;
            ctx.globalAlpha = base * (1.3 - local) / 0.3;
            ctx.drawImage(spr.pulse, s.sex - size / 2, s.sey - size / 2, size, size);
            continue;
          }
          for (let k = 0; k < 3; k++) {
            const u = local - k * 0.035;
            if (u < 0) break;
            const a = 1 - u;
            const x = a * a * s.sox + 2 * a * u * s.scx + u * u * s.sex;
            const y = a * a * s.soy + 2 * a * u * s.scy + u * u * s.sey;
            const size = ps * (1 - k * 0.25) * s.f;
            ctx.globalAlpha = base * (1 - k * 0.3);
            ctx.drawImage(spr.pulse, x - size / 2, y - size / 2, size, size);
          }
        }
      }

      // ── hub ──
      if (hubV > 0) {
        proj(0, 0, 0);
        const hs = 64 * sz * PF * (0.6 + 0.4 * outBack(prog(t, TL.hubIn, 0.6)));
        ctx.globalAlpha = hubV;
        ctx.drawImage(spr.nodes[0], PX - hs / 2, PY - hs / 2, hs, hs);
        ctx.drawImage(tip, PX - hs * 0.3, PY - hs * 0.3, hs * 0.6, hs * 0.6);
        ctx.globalAlpha = 1;
        ctx.lineWidth = 1.2 * sz;
        for (let k = 0; k < 3; k++) {
          const ph = (t * 0.55 + k / 3) % 1;
          ctx.strokeStyle = rgba(th.net, 0.4 * (1 - ph) * hubV);
          ctx.beginPath();
          ctx.arc(PX, PY, (14 + 70 * ph) * sz, 0, TAU);
          ctx.stroke();
        }
        ctx.strokeStyle = rgba(th.net, 0.7 * hubV);
        ctx.beginPath();
        ctx.arc(PX, PY, 13 * sz, 0, TAU);
        ctx.stroke();
      }

      // ── bloom + vignette ──
      if (bloomOn) {
        ctx.globalAlpha = 1;
        bctx.clearRect(0, 0, bloom.width, bloom.height);
        bctx.drawImage(canvas, 0, 0, bloom.width, bloom.height);
        ctx.globalAlpha = 0.85;
        ctx.drawImage(bloom, 0, 0, cw, ch);
      }
      ctx.globalCompositeOperation = 'source-over';
      ctx.globalAlpha = 1;
      ctx.drawImage(vignette, 0, 0);

      // ── node labels, drawn crisp on top of the bloom ──
      if (tagged.length) {
        const ls = dpr * clamp(unit / 260, 0.9, 1.25);
        const fsz = Math.round(12 * ls);
        const padX = 10 * ls, h = fsz + 12 * ls, gap = 16 * ls, edge = 8 * ls;
        ctx.font = '500 ' + fsz + 'px "IBM Plex Mono", ui-monospace, Menlo, monospace';
        ctx.textBaseline = 'middle';
        ctx.lineWidth = dpr;
        for (let i = 0; i < tagged.length; i++) {
          const L = tagged[i];
          if (L.la <= 0.01) continue;
          const text = L.text.toUpperCase();
          const bw = ctx.measureText(text).width + 2 * padX;
          const right = L.x >= CX;
          const bx = clamp(right ? L.x + gap : L.x - gap - bw, edge, cw - bw - edge);
          const by = clamp(L.y - h / 2, edge, ch - h - edge);
          ctx.globalAlpha = L.la;
          ctx.strokeStyle = rgba(th.net, 0.6);
          ctx.beginPath();
          ctx.moveTo(L.x + (right ? 9 : -9) * ls, L.y);
          ctx.lineTo(right ? bx : bx + bw, by + h / 2);
          ctx.stroke();
          ctx.beginPath();
          if (ctx.roundRect) ctx.roundRect(bx, by, bw, h, h / 2); else ctx.rect(bx, by, bw, h);
          ctx.fillStyle = rgba(th.bg, 0.82);
          ctx.fill();
          ctx.stroke();
          ctx.fillStyle = rgba(th.tip, 0.95);
          ctx.fillText(text, bx + padX, by + h / 2 + 0.5 * ls);
        }
        ctx.globalAlpha = 1;
      }
    }

    // ── clock ──
    let raf = 0, t0 = performance.now(), pausedAt = 0, frozen = null, settled = false;
    let inView = true, docVisible = !document.hidden, held = false;
    let lastNow = 0, slow = 0;

    function tick(now) {
      raf = requestAnimationFrame(tick);
      let t = frozen !== null ? frozen : (now - t0) / 1000;
      if (reduce && frozen === null) t = 8.8 + t * 0.15;
      // Drop the bloom pass if the device can't keep up.
      if (lastNow && bloomOn && t > 2) {
        slow = (now - lastNow > 28) ? slow + 1 : Math.max(0, slow - 1);
        if (slow > 45) bloomOn = false;
      }
      lastNow = now;
      frame(t);
      if (!settled && t >= TL.settleEvent) {
        settled = true;
        if (o.onSettle) o.onSettle();
      }
    }

    function sync() {
      const want = inView && docVisible && !held;
      if (want && !raf) {
        if (pausedAt) { t0 += performance.now() - pausedAt; pausedAt = 0; }
        lastNow = 0;
        raf = requestAnimationFrame(tick);
      } else if (!want && raf) {
        cancelAnimationFrame(raf);
        raf = 0;
        pausedAt = performance.now();
      }
    }

    const onPointer = (e) => {
      tmx = (e.clientX / global.innerWidth) * 2 - 1;
      tmy = (e.clientY / global.innerHeight) * 2 - 1;
    };
    const onVisibility = () => { docVisible = !document.hidden; sync(); };

    let ro = null, io = null;
    if (!(o.width && o.height) && global.ResizeObserver) {
      ro = new ResizeObserver(resize);
      ro.observe(canvas);
    }
    if (o.observe && global.IntersectionObserver) {
      io = new IntersectionObserver((entries) => { inView = entries[0].isIntersecting; sync(); });
      io.observe(canvas);
    }
    if (o.interactive && !reduce) global.addEventListener('pointermove', onPointer, { passive: true });
    document.addEventListener('visibilitychange', onVisibility);

    resize();
    sync();

    return {
      replay() {
        t0 = performance.now();
        pausedAt = raf ? 0 : t0;
        frozen = null;
        settled = false;
        slow = 0;
      },
      seek(t) { frozen = t; },
      // Draws one frame immediately, e.g. for a poster image or a hidden tab.
      renderAt(t) { frozen = t; frame(t); },
      setTheme(name) {
        theme = THEMES[name] || THEMES.signal;
        spr = buildSprites(theme);
        makeGrid();
        makeVignette();
      },
      pause() { held = true; sync(); },
      resume() { held = false; sync(); },
      destroy() {
        held = true; sync();
        if (ro) ro.disconnect();
        if (io) io.disconnect();
        global.removeEventListener('pointermove', onPointer);
        document.removeEventListener('visibilitychange', onVisibility);
      },
      get time() { return (performance.now() - t0) / 1000; },
    };
  }

  global.BrainNetwork = { mount, themes: Object.keys(THEMES) };
})(window);
