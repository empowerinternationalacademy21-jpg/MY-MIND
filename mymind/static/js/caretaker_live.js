/* Caretaker dashboard: live refresh + local time.
   - Polls the same page every 30 s and swaps only the data panels, so new child activity shows up (and the charts
     recalculate) without a reload. The world preview, forms and open pickers are never touched.
   - Server times are UTC; they are shown in the caregiver's own time zone. */
(function () {
  "use strict";
  var POLL_MS = 30000;
  var live = document.getElementById("ct-live");
  if (!live) return;
  var timer = null, busy = false, lastRun = 0, stopped = false;

  function pad(n) { return String(n).padStart(2, "0"); }
  function localHM(d) { return pad(d.getHours()) + ":" + pad(d.getMinutes()); }
  function ago(d) {
    var s = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + " min ago";
    if (s < 86400) return Math.floor(s / 3600) + " h ago";
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short" }) + " " + localHM(d);
  }

  function localiseTimes(root) {
    (root || document).querySelectorAll("time[data-utc]").forEach(function (t) {
      var d = new Date(t.getAttribute("data-utc"));
      if (isNaN(d)) return;
      t.textContent = t.hasAttribute("data-rel") ? ago(d) : localHM(d);
      t.setAttribute("datetime", d.toISOString());
      t.title = d.toLocaleString();
    });
  }

  /* hour-of-day bars arrive bucketed by UTC hour; rotate them so 09:00 means 09:00 where the caregiver is */
  function localiseHours(root) {
    (root || document).querySelectorAll("[data-hours]").forEach(function (chart) {
      var bars = Array.prototype.slice.call(chart.children);
      if (bars.length !== 24 || chart.getAttribute("data-localised") === "1") return;
      var off = Math.round(-new Date().getTimezoneOffset() / 60);
      var ordered = new Array(24), peak = 0, peakIdx = -1;
      bars.forEach(function (bar, utcHour) {
        var local = (utcHour + off + 24) % 24;
        ordered[local] = bar;
        var v = parseInt(bar.style.getPropertyValue("--hour"), 10) || 0;
        bar.title = pad(local) + ":00" + bar.title.replace(/^\d{2}:00/, "");
        if (v > peak) { peak = v; peakIdx = local; }
      });
      ordered.forEach(function (bar) { chart.appendChild(bar); });
      chart.setAttribute("data-localised", "1");
      var strong = chart.parentNode.querySelector(".ct-peak strong");
      if (strong && peakIdx >= 0) strong.textContent = pad(peakIdx) + ":00";
    });
  }

  function paint(root) { localiseTimes(root); localiseHours(root); }

  function remember() {
    document.querySelectorAll("[data-live]").forEach(function (el) { el.__raw = el.innerHTML; });
  }

  function userIsBusy() {
    var a = document.activeElement;
    if (a && /^(INPUT|SELECT|TEXTAREA)$/.test(a.tagName) && a.closest(".ctx-window")) return true;
    return false;
  }

  function setLive(text, fresh) {
    var label = live.querySelector("[data-live-text]");
    if (!label) return;
    if (text) label.innerHTML = text;
    live.classList.toggle("is-fresh", !!fresh);
    if (fresh) setTimeout(function () { live.classList.remove("is-fresh"); }, 4000);
  }

  async function refresh() {
    if (busy || stopped || document.hidden || userIsBusy() || !navigator.onLine) return;
    busy = true; lastRun = Date.now();
    try {
      var res = await fetch(location.href, { credentials: "same-origin", cache: "no-store",
        headers: { "X-Requested-With": "fetch", "Accept": "text/html" } });
      if (!res.ok || res.redirected) { stopped = true; live.classList.add("is-paused"); return; }
      var doc = new DOMParser().parseFromString(await res.text(), "text/html");
      var changed = false;
      document.querySelectorAll("[data-live]").forEach(function (el) {
        var fresh = doc.querySelector('[data-live="' + el.getAttribute("data-live") + '"]');
        if (!fresh || fresh.innerHTML === el.__raw) return;
        if (el.contains(document.activeElement) && userIsBusy()) return;
        el.innerHTML = fresh.innerHTML; el.__raw = fresh.innerHTML;
        paint(el); changed = true;
      });
      var nl = doc.getElementById("ct-live");
      if (nl) {
        var newest = nl.getAttribute("data-last") || "";
        var isNew = newest && newest !== live.getAttribute("data-last");
        live.setAttribute("data-last", newest);
        var tmp = nl.querySelector("[data-live-text]");
        if (tmp) setLive(tmp.innerHTML, isNew);
        paint(live);
      }
      live.classList.remove("is-paused");
    } catch (e) { /* offline or server hiccup: try again next tick */ }
    finally { busy = false; }
  }

  function tick() {
    paint(live);                                   /* keeps "x min ago" honest between polls */
    document.querySelectorAll("time[data-rel]").forEach(function (t) { localiseTimes(t.parentNode); });
  }

  remember();
  paint(document);
  setInterval(refresh, POLL_MS);
  setInterval(tick, 20000);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && Date.now() - lastRun > 10000) refresh();
  });
  window.addEventListener("online", refresh);
})();
