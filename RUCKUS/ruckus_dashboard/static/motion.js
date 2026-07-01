"use strict";

// SP5 motion utilities — dependency-free, same-origin (CSP script-src 'self').
// Leak-safe: at most one requestAnimationFrame handle per node, stored on the
// node and cancelled before re-arming and on hidden. No interval timers of any
// kind are used. Fail-open: callers wrap these so a throw never breaks
// rendering — the final value is always written even when the tween is skipped.

(function (global) {
  // True when the OS asks for reduced motion. matchMedia may be absent in odd
  // embeddings — treat absence as "motion allowed" (the CSS guard still applies).
  function motionReduced() {
    try {
      return !!(global.matchMedia &&
        global.matchMedia("(prefers-reduced-motion: reduce)").matches);
    } catch (_e) {
      return false;
    }
  }

  // Animate a numeric text node from its current numeric value to `to`,
  // formatting each frame via `fmt`. Snaps to final under reduced motion or a
  // hidden tab. No-ops gracefully on a non-element / non-finite target.
  function animateCount(el, to, opts) {
    opts = opts || {};
    var fmt = typeof opts.fmt === "function" ? opts.fmt : String;
    var duration = typeof opts.duration === "number" ? opts.duration : 320;
    if (!el || typeof el !== "object") return;

    var target = Number(to);
    var snap = function () { el.textContent = isFinite(target) ? fmt(target) : String(to); };

    // Cancel any in-flight tween on this node before re-arming (leak guard).
    if (el._rkRaf) { global.cancelAnimationFrame(el._rkRaf); el._rkRaf = 0; }

    if (!isFinite(target) || motionReduced() ||
        (global.document && global.document.hidden)) {
      snap();
      return;
    }

    var from = parseFloat(String(el.textContent).replace(/[^0-9.\-]/g, ""));
    if (!isFinite(from)) from = 0;
    if (from === target) { snap(); return; }

    var start = 0;
    var step = function (ts) {
      if (!start) start = ts;
      var p = Math.min(1, (ts - start) / duration);
      // ease-out cubic to match --ease-out
      var e = 1 - Math.pow(1 - p, 3);
      var cur = from + (target - from) * e;
      el.textContent = fmt(p >= 1 ? target : Math.round(cur));
      if (p < 1) {
        el._rkRaf = global.requestAnimationFrame(step);
      } else {
        el._rkRaf = 0;
      }
    };
    el._rkRaf = global.requestAnimationFrame(step);
  }

  // Fire a one-shot CSS pulse by toggling `<base>-ed` class with a reflow
  // re-arm and animationend self-clean. No-op under reduced motion.
  function pulse(el, cls) {
    cls = cls || "refreshed";
    var full = "module-" + cls; // e.g. "module-refreshed"
    if (!el || typeof el !== "object" || motionReduced()) return;
    el.classList.remove(full);
    // force reflow so re-adding the class restarts the animation
    void el.offsetWidth;
    el.classList.add(full);
    var clear = function () { el.classList.remove(full); el.removeEventListener("animationend", clear); };
    el.addEventListener("animationend", clear);
  }

  var api = { animateCount: animateCount, pulse: pulse, motionReduced: motionReduced };
  global.RuckusMotion = api;
  // Explicit window alias (same object) so callers and tests can reference
  // window.RuckusMotion directly even in non-window `global` contexts.
  if (typeof window !== "undefined") window.RuckusMotion = api;
})(typeof window !== "undefined" ? window : this);
