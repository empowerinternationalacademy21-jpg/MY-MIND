/* MyMind - left / right arrows for horizontally scrolling topic bars.
 *
 * Add the attribute  data-scroll-arrows  to any row that scrolls sideways
 * (Pictures, Videos, Shots and Music topic bars use it). This script wraps the
 * row, adds a "previous" and a "next" arrow, and keeps them in step with the
 * scroll position. The row's own buttons are never recreated or moved out of the
 * page, so every page script that listens to them keeps working.
 *
 * - Arrows only appear when the topics do not all fit on screen.
 * - An arrow is dimmed and disabled once you reach that end of the row.
 * - Touch swiping, mouse-wheel / trackpad scrolling and keyboard Tab still work.
 * - Smooth scrolling is switched off for people who asked for reduced motion.
 */
(function () {
  "use strict";

  var SELECTOR = "[data-scroll-arrows]";
  var CHEVRON_LEFT = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M15 5l-7 7 7 7"/></svg>';
  var CHEVRON_RIGHT = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5l7 7-7 7"/></svg>';

  function prefersReducedMotion() {
    return document.body.classList.contains("reduced-motion") ||
      (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }

  function makeArrow(direction) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "ts-btn ts-" + direction;
    b.setAttribute("aria-label", direction === "prev" ? "Show earlier topics" : "Show more topics");
    b.innerHTML = direction === "prev" ? CHEVRON_LEFT : CHEVRON_RIGHT;
    return b;
  }

  function enhance(row) {
    if (row.getAttribute("data-ts-ready")) return;
    row.setAttribute("data-ts-ready", "1");

    var wrap = document.createElement("div");
    wrap.className = "ts-wrap";
    row.parentNode.insertBefore(wrap, row);
    wrap.appendChild(row);

    var prev = makeArrow("prev");
    var next = makeArrow("next");
    wrap.insertBefore(prev, row);
    wrap.appendChild(next);

    var queued = false;

    function centreArrows() {
      /* line the arrows up with the middle of the pills (or of the round icons on Pictures) */
      var target = row.querySelector(".topic-ring") || row.firstElementChild;
      if (!target) return;
      var t = target.getBoundingClientRect();
      var w = wrap.getBoundingClientRect();
      var centre = t.top - w.top + t.height / 2;
      if (centre > 0) {
        prev.style.top = centre + "px";
        next.style.top = centre + "px";
      }
    }

    function update() {
      queued = false;
      var overflowing = row.scrollWidth > row.clientWidth + 2;
      wrap.classList.toggle("ts-overflow", overflowing);
      if (!overflowing) return;
      var max = row.scrollWidth - row.clientWidth;
      prev.disabled = row.scrollLeft <= 2;
      next.disabled = row.scrollLeft >= max - 2;
      centreArrows();
    }

    function queueUpdate() {
      if (queued) return;
      queued = true;
      window.requestAnimationFrame(update);
    }

    function scrollByPage(direction) {
      /* move by most of a screenful, so the last topic you saw stays in view */
      var step = Math.max(120, Math.round(row.clientWidth * 0.8));
      row.scrollBy({ left: direction * step, behavior: prefersReducedMotion() ? "auto" : "smooth" });
    }

    prev.addEventListener("click", function () { scrollByPage(-1); });
    next.addEventListener("click", function () { scrollByPage(1); });
    row.addEventListener("scroll", queueUpdate, { passive: true });
    window.addEventListener("resize", queueUpdate);
    window.addEventListener("load", queueUpdate);   /* fonts and icons can change the row's width */

    if ("ResizeObserver" in window) {
      var ro = new ResizeObserver(queueUpdate);
      ro.observe(row);
      Array.prototype.forEach.call(row.children, function (c) { ro.observe(c); });
    }

    /* when a topic gets chosen, make sure it is fully visible (not hidden behind an arrow) */
    row.addEventListener("click", function (e) {
      var item = e.target.closest("button");
      if (!item || !row.contains(item)) return;
      var r = item.getBoundingClientRect();
      var rr = row.getBoundingClientRect();
      var gutter = wrap.classList.contains("ts-overflow") ? 48 : 0;
      if (r.left < rr.left + gutter) {
        row.scrollBy({ left: r.left - rr.left - gutter, behavior: prefersReducedMotion() ? "auto" : "smooth" });
      } else if (r.right > rr.right - gutter) {
        row.scrollBy({ left: r.right - rr.right + gutter, behavior: prefersReducedMotion() ? "auto" : "smooth" });
      }
    });

    update();
  }

  function init() {
    Array.prototype.forEach.call(document.querySelectorAll(SELECTOR), enhance);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
