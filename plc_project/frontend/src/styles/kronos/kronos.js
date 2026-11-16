/*!
 * KRONOS · 纸本建筑主义 — kronos.js v4.2
 * 零依赖：初触微颤引擎 / 纸面倾斜 / 无遮罩活页抽屉 / 昼夜双卷 / 呼吸降噪 / 朱砂落印
 * 用法：<script src="kronos.js"></script> 后调用 KRONOS.init()；
 *      或 import KRONOS from "./kronos.js"（CommonJS / 打包器互操作）。
 * SSR 安全：加载时不访问 document，只有调用 init() 才挂载。
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
    module.exports.default = api;
  } else {
    root.KRONOS = api;
    root.initKRONOSMicroExpressions = api.initMicroExpressions; // v4.0 兼容
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var THEME_KEY = "kronos-theme";
  var CALM_KEY = "kronos-calm";
  var NIGHT_CLASS = "rubbing-mode";
  var CALM_CLASS = "kronos-calm";
  var ALIVE_CLASS = "kronos-alive";
  var INPUT_CLASS = "kronos-alive-input";
  var TREMBLE_CLASS = "is-trembling";
  var TILT_CLASS = "kronos-tilt";
  var TILTING_CLASS = "is-tilting";
  var TREMOR_ANIMATIONS = { slyFirstTouchTremor: 1, slyInputAwaken: 1 };

  var DEFAULTS = {
    root: null,
    alive: "button, [role='button'], .k-btn, .kronos-card, .chromatic-isolation-vault, [data-kronos-alive]",
    input: "input:not([type='hidden']):not([type='checkbox']):not([type='radio']):not([type='range']):not([type='file']), textarea, select",
    ignore: "[data-kronos-still]",
    tilt: "[data-kronos-tilt]",
    cooldown: 320,
    touch: false,
    observe: true
  };

  function docOf(node) {
    return (node && node.ownerDocument) || (typeof document !== "undefined" ? document : null);
  }

  function isDisabled(el) {
    return el.matches(":disabled, [aria-disabled='true'], .is-disabled");
  }

  function safeMatches(el, selector) {
    try { return el.matches(selector); } catch (e) { return false; }
  }

  function prefersReducedMotion(win) {
    return !!(win && win.matchMedia && win.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  /* ---------------------------------------------------------------------
   * 1. 初触微颤引擎
   *    - 事件委托：动态渲染（React / Vue / SPA）的节点同样生效
   *    - 每次"进入"只颤一次，结束后稳定停在放大态，绝不持续抖动
   *    - 点击已悬停的元素不会二次触发；键盘 Tab 聚焦才触发 focus 微颤
   *    - 尊重 prefers-reduced-motion 与呼吸降噪模式；默认忽略触屏
   * ------------------------------------------------------------------- */
  function initMicroExpressions(options) {
    var o = Object.assign({}, DEFAULTS, options || {});
    var doc = docOf(o.root);
    if (!doc) return function () {};
    var scope = o.root || doc;
    var win = doc.defaultView;
    var lastTrigger = new WeakMap();

    function tag(node) {
      if (!node || node.nodeType !== 1) return;
      var list = [node];
      if (node.querySelectorAll) list = list.concat(Array.prototype.slice.call(node.querySelectorAll(o.alive + "," + o.input + "," + o.tilt)));
      list.forEach(function (el) {
        if (o.ignore && el.closest(o.ignore)) return;
        if (safeMatches(el, o.tilt)) { el.classList.add(TILT_CLASS); return; } // 倾斜体不再叠加微颤
        if (safeMatches(el, o.input)) el.classList.add(INPUT_CLASS);
        else if (safeMatches(el, o.alive)) el.classList.add(ALIVE_CLASS);
      });
    }

    function tremble(el) {
      if (isDisabled(el) || prefersReducedMotion(win)) return;
      if (doc.documentElement.classList.contains(CALM_CLASS)) return;
      var now = win.performance ? win.performance.now() : Date.now();
      if (now - (lastTrigger.get(el) || -Infinity) < o.cooldown) return;
      lastTrigger.set(el, now);
      el.classList.remove(TREMBLE_CLASS);
      void el.offsetWidth; // 强制回流，保证每次进入干净重播
      el.classList.add(TREMBLE_CLASS);
    }

    // 从事件目标向上遍历所有活体祖先；祖先已包含 relatedTarget 说明是内部移动，停止
    function walk(target, related, fn) {
      if (!target || !target.closest) return;
      var el = target.closest("." + ALIVE_CLASS + ", ." + INPUT_CLASS);
      while (el && scope.contains(el)) {
        if (related && el.contains(related)) break;
        fn(el);
        el = el.parentElement ? el.parentElement.closest("." + ALIVE_CLASS + ", ." + INPUT_CLASS) : null;
      }
    }

    function onPointerOver(e) {
      if (!o.touch && e.pointerType === "touch") return;
      walk(e.target, e.relatedTarget, tremble);
    }

    function onPointerOut(e) {
      walk(e.target, e.relatedTarget, function (el) { el.classList.remove(TREMBLE_CLASS); });
    }

    function onFocusIn(e) {
      var t = e.target;
      if (!t || !t.matches) return;
      var keyboardish = safeMatches(t, ":focus-visible") || safeMatches(t, o.input);
      if (!keyboardish) return;
      walk(t, e.relatedTarget, function (el) {
        if (!safeMatches(el, ":hover")) tremble(el);
      });
    }

    function onFocusOut(e) {
      walk(e.target, e.relatedTarget, function (el) { el.classList.remove(TREMBLE_CLASS); });
    }

    function onAnimationEnd(e) {
      if (TREMOR_ANIMATIONS[e.animationName] && e.target.classList) e.target.classList.remove(TREMBLE_CLASS);
    }

    // 纸面倾斜：指针位置 → --tx/--ty（-1…1）与光斑 --mx/--my；每帧最多写一次
    var pendingTilt = null;
    var tiltFrame = 0;

    function applyTilt() {
      tiltFrame = 0;
      var p = pendingTilt;
      pendingTilt = null;
      if (!p) return;
      var r = p.el.getBoundingClientRect();
      if (!r.width || !r.height) return;
      var tx = Math.max(-1, Math.min(1, ((p.x - r.left) / r.width) * 2 - 1));
      var ty = Math.max(-1, Math.min(1, ((p.y - r.top) / r.height) * 2 - 1));
      p.el.style.setProperty("--tx", tx.toFixed(3));
      p.el.style.setProperty("--ty", ty.toFixed(3));
      p.el.style.setProperty("--mx", ((tx + 1) * 50).toFixed(1) + "%");
      p.el.style.setProperty("--my", ((ty + 1) * 50).toFixed(1) + "%");
      p.el.classList.add(TILTING_CLASS);
    }

    function resetTilt(el) {
      el.style.setProperty("--tx", "0");
      el.style.setProperty("--ty", "0");
      el.classList.remove(TILTING_CLASS);
    }

    function onPointerMove(e) {
      if (!o.touch && e.pointerType === "touch") return;
      var el = e.target && e.target.closest ? e.target.closest("." + TILT_CLASS) : null;
      if (!el || prefersReducedMotion(win) || doc.documentElement.classList.contains(CALM_CLASS)) return;
      pendingTilt = { el: el, x: e.clientX, y: e.clientY };
      if (!tiltFrame) tiltFrame = win.requestAnimationFrame(applyTilt);
    }

    function onTiltOut(e) {
      var el = e.target && e.target.closest ? e.target.closest("." + TILT_CLASS) : null;
      if (el && !(e.relatedTarget && el.contains(e.relatedTarget))) {
        if (pendingTilt && pendingTilt.el === el) pendingTilt = null;
        resetTilt(el);
      }
    }

    tag(scope === doc ? doc.body : scope);

    var observer = null;
    if (o.observe && win.MutationObserver) {
      observer = new win.MutationObserver(function (records) {
        records.forEach(function (r) { r.addedNodes.forEach(tag); });
      });
      observer.observe(scope === doc ? doc.body : scope, { childList: true, subtree: true });
    }

    scope.addEventListener("pointerover", onPointerOver, true);
    scope.addEventListener("pointerout", onPointerOut, true);
    scope.addEventListener("focusin", onFocusIn, true);
    scope.addEventListener("focusout", onFocusOut, true);
    scope.addEventListener("animationend", onAnimationEnd, true);
    scope.addEventListener("pointermove", onPointerMove, { capture: true, passive: true });
    scope.addEventListener("pointerout", onTiltOut, true);

    return function destroy() {
      if (observer) observer.disconnect();
      if (tiltFrame) win.cancelAnimationFrame(tiltFrame);
      scope.removeEventListener("pointermove", onPointerMove, { capture: true });
      scope.removeEventListener("pointerout", onTiltOut, true);
      scope.removeEventListener("pointerover", onPointerOver, true);
      scope.removeEventListener("pointerout", onPointerOut, true);
      scope.removeEventListener("focusin", onFocusIn, true);
      scope.removeEventListener("focusout", onFocusOut, true);
      scope.removeEventListener("animationend", onAnimationEnd, true);
    };
  }

  /* ---------------------------------------------------------------------
   * 2. 昼夜双卷：day | rubbing | auto（跟随系统）
   * ------------------------------------------------------------------- */
  var mediaListener = null;

  function readStore(key) {
    try { return window.localStorage.getItem(key); } catch (e) { return null; }
  }
  function writeStore(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* 隐私模式忽略 */ }
  }

  function applyNight(isNight) {
    var html = document.documentElement;
    html.classList.toggle(NIGHT_CLASS, isNight);
    if (document.body) document.body.classList.toggle(NIGHT_CLASS, isNight);
    document.querySelectorAll("[data-kronos-theme-toggle]").forEach(function (btn) {
      btn.setAttribute("aria-pressed", String(isNight));
    });
  }

  function setTheme(mode) {
    if (typeof document === "undefined") return;
    var mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
    if (mediaListener && mq) { mq.removeEventListener("change", mediaListener); mediaListener = null; }
    if (mode !== "day" && mode !== "rubbing") mode = "auto";
    writeStore(THEME_KEY, mode);
    document.documentElement.setAttribute("data-kronos-theme-mode", mode);
    if (mode === "auto") {
      applyNight(!!(mq && mq.matches));
      if (mq) {
        mediaListener = function (e) { applyNight(e.matches); };
        mq.addEventListener("change", mediaListener);
      }
    } else {
      applyNight(mode === "rubbing");
    }
  }

  function getTheme() {
    return readStore(THEME_KEY) || "auto";
  }

  function toggleTheme() {
    var night = document.documentElement.classList.contains(NIGHT_CLASS);
    setTheme(night ? "day" : "rubbing");
  }

  /* ---------------------------------------------------------------------
   * 3. 呼吸降噪
   * ------------------------------------------------------------------- */
  function setCalm(on) {
    if (typeof document === "undefined") return;
    document.documentElement.classList.toggle(CALM_CLASS, !!on);
    writeStore(CALM_KEY, on ? "1" : "0");
    document.querySelectorAll("[data-kronos-calm-toggle]").forEach(function (btn) {
      btn.setAttribute("aria-pressed", String(!!on));
    });
  }
  function toggleCalm() {
    setCalm(!document.documentElement.classList.contains(CALM_CLASS));
  }

  /* ---------------------------------------------------------------------
   * 4. 无遮罩活页抽屉
   *    触发器：data-kronos-drawer-open="drawerId"；关闭：data-kronos-drawer-close；Esc 关闭最近打开的
   * ------------------------------------------------------------------- */
  var openStack = [];

  function resolveDrawer(target) {
    if (!target) return null;
    return typeof target === "string" ? document.getElementById(target) : target;
  }

  function focusFirst(container) {
    var f = container.querySelector("[autofocus], input, textarea, select, button, [href], [tabindex]:not([tabindex='-1'])");
    if (!f) { container.setAttribute("tabindex", "-1"); f = container; }
    f.focus({ preventScroll: true });
  }

  function openDrawer(target, trigger) {
    var el = resolveDrawer(target);
    if (!el || el.classList.contains("is-open")) return;
    el.classList.add("is-open");
    el.setAttribute("aria-hidden", "false");
    el.__kronosTrigger = trigger || document.activeElement;
    if (el.__kronosTrigger && el.__kronosTrigger.setAttribute) el.__kronosTrigger.setAttribute("aria-expanded", "true");
    openStack.push(el);
    window.setTimeout(function () { focusFirst(el); }, 30);
  }

  function closeDrawer(target) {
    var el = resolveDrawer(target) || openStack[openStack.length - 1];
    if (!el || !el.classList.contains("is-open")) return;
    el.classList.remove("is-open");
    el.setAttribute("aria-hidden", "true");
    openStack = openStack.filter(function (d) { return d !== el; });
    var trigger = el.__kronosTrigger;
    if (trigger && trigger.setAttribute) trigger.setAttribute("aria-expanded", "false");
    if (trigger && trigger.focus && el.contains(document.activeElement)) trigger.focus({ preventScroll: true });
  }

  /* ---------------------------------------------------------------------
   * 5. 朱砂落印：重播毛细微渗
   * ------------------------------------------------------------------- */
  function stamp(el) {
    if (!el) return;
    el.classList.remove("k-stamp--fresh");
    void el.offsetWidth;
    el.classList.add("k-stamp--fresh");
  }

  /* ---------------------------------------------------------------------
   * 6. 一次性总挂载
   * ------------------------------------------------------------------- */
  var mounted = null;

  function init(options) {
    if (typeof document === "undefined") return { destroy: function () {} };
    if (mounted) return mounted;
    if (!document.body) {
      var deferred = { destroy: function () { if (mounted) mounted.destroy(); } };
      document.addEventListener("DOMContentLoaded", function () { init(options); }, { once: true });
      return deferred;
    }
    var o = options || {};

    setTheme(o.theme || getTheme());
    if (readStore(CALM_KEY) === "1") setCalm(true);

    var destroyMotion = initMicroExpressions(o);

    function onClick(e) {
      var t = e.target.closest ? e.target : null;
      if (!t) return;
      var opener = t.closest("[data-kronos-drawer-open]");
      if (opener) { e.preventDefault(); openDrawer(opener.getAttribute("data-kronos-drawer-open"), opener); return; }
      var closer = t.closest("[data-kronos-drawer-close]");
      if (closer) { e.preventDefault(); closeDrawer(closer.closest(".k-drawer")); return; }
      if (t.closest("[data-kronos-theme-toggle]")) { toggleTheme(); return; }
      if (t.closest("[data-kronos-calm-toggle]")) { toggleCalm(); return; }
      var stampTrigger = t.closest("[data-kronos-stamp]");
      if (stampTrigger) stamp(document.getElementById(stampTrigger.getAttribute("data-kronos-stamp")));
    }

    function onKey(e) {
      if (e.key === "Escape" && openStack.length) closeDrawer();
    }

    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);

    mounted = {
      destroy: function () {
        destroyMotion();
        document.removeEventListener("click", onClick);
        document.removeEventListener("keydown", onKey);
        mounted = null;
      }
    };
    return mounted;
  }

  return {
    version: "4.2.0",
    init: init,
    initMicroExpressions: initMicroExpressions,
    setTheme: setTheme,
    getTheme: getTheme,
    toggleTheme: toggleTheme,
    setCalm: setCalm,
    toggleCalm: toggleCalm,
    openDrawer: openDrawer,
    closeDrawer: closeDrawer,
    stamp: stamp
  };
});
