/* SpotZⁱ (ClaimShield Nexus) landing page.
   - Hero: mounts the Network-Brain canvas animation (brain-network.js).
   - Light slides: scroll-reveal + stat count-up.
   External file because the app's CSP is script-src 'self' (no inline JS). */
(function () {
  'use strict';

  var reduce = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  /* ── Hero brain animation ─────────────────────────────── */
  (function hero() {
    if (typeof BrainNetwork === 'undefined') return;
    var section = document.querySelector('.hero');
    var canvas = section && section.querySelector('.hero-canvas');
    if (!section || !canvas) return;

    var params = new URLSearchParams(location.search);
    var theme = params.get('theme');
    if (theme !== 'spotzi' && theme !== 'kernel') theme = 'signal';

    var h = BrainNetwork.mount(canvas, {
      layout: 'auto',
      theme: theme,
      onSettle: function () { section.classList.add('is-settled'); },
    });

    if (params.has('t')) {
      var t = parseFloat(params.get('t'));
      if (!isNaN(t)) { h.renderAt(t); if (t >= 6.6) section.classList.add('is-settled'); }
    }
  })();

  /* ── Scroll reveal for the light slides ───────────────── */
  (function reveal() {
    var els = Array.prototype.slice.call(document.querySelectorAll('.reveal'));
    if (!els.length) return;
    if (reduce || !('IntersectionObserver' in window)) {
      els.forEach(function (el) { el.classList.add('in'); });
      return;
    }
    // Stagger siblings within the same grid/row.
    var seen = new WeakMap();
    els.forEach(function (el) {
      var p = el.parentElement;
      var i = seen.get(p) || 0; seen.set(p, i + 1);
      el.style.transitionDelay = Math.min(i * 70, 350) + 'ms';
    });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -8% 0px' });
    els.forEach(function (el) { io.observe(el); });
  })();

  /* ── Count-up for the solution stats ──────────────────── */
  (function counters() {
    var nums = Array.prototype.slice.call(document.querySelectorAll('[data-count]'));
    if (!nums.length) return;
    if (reduce || !('IntersectionObserver' in window)) return; // numbers already printed in HTML

    var run = function (el) {
      var target = parseInt(el.getAttribute('data-count'), 10) || 0;
      var dur = 1100, t0 = null;
      el.textContent = '0';
      var step = function (now) {
        if (t0 === null) t0 = now;
        var p = Math.min(1, (now - t0) / dur);
        var eased = 1 - Math.pow(1 - p, 3);
        el.textContent = String(Math.round(target * eased));
        if (p < 1) requestAnimationFrame(step);
        else el.textContent = String(target);
      };
      requestAnimationFrame(step);
    };

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { run(e.target); io.unobserve(e.target); }
      });
    }, { threshold: 0.6 });
    nums.forEach(function (el) { io.observe(el); });
  })();
})();
